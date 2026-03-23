"""WebSocket manager for real-time price and order-fill streaming.

:class:`WSManager` owns one :class:`~agentexchange.AgentExchangeWS` connection,
subscribes to ``ticker:{symbol}`` for every configured trading pair, and
subscribes to the ``orders`` channel for fill notifications.

Incoming ticks are written into a local ``_price_buffer`` dict (symbol → latest
price).  The :class:`~agent.trading.loop.TradingLoop` reads from this buffer
instead of polling ``GET /api/v1/market/prices``, eliminating per-tick REST
round-trips.

When an order-fill event arrives the manager sets an internal
:class:`asyncio.Event` so that the trading loop can immediately trigger a
position-monitor check instead of waiting for the next scheduled tick.

Architecture::

    WSManager
        │
        ├── AgentExchangeWS.on_ticker(symbol)  ─► _price_buffer[symbol] = price
        ├── AgentExchangeWS.on_order_update()  ─► _order_fill_event.set()
        │
        ├── connect()   — start WS as background asyncio.Task (non-blocking)
        ├── disconnect() — cancel task, disconnect WS client
        │
        ├── get_price(symbol) → Decimal | None
        ├── get_all_prices()  → dict[str, Decimal]
        └── wait_for_order_fill(timeout) → bool

Reconnection is handled transparently by :class:`~agentexchange.AgentExchangeWS`
(exponential back-off 1 s → 60 s).  If the WS disconnects, the price buffer
retains the last known values; the trading loop falls back to REST polling when
``get_price()`` returns ``None`` for a symbol.

Usage::

    from agent.config import AgentConfig
    from agent.trading.ws_manager import WSManager

    manager = WSManager(config=config)
    await manager.connect()           # starts background task, returns immediately

    price = manager.get_price("BTCUSDT")  # None until first tick arrives
    triggered = await manager.wait_for_order_fill(timeout=5.0)

    await manager.disconnect()        # clean shutdown
"""

from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from agent.config import AgentConfig

logger = structlog.get_logger(__name__)

# Reconnect delay cap re-exported from AgentExchangeWS constants.
_BACKOFF_MAX: float = 60.0


class WSManager:
    """Real-time WebSocket price buffer and order-fill notifier.

    Owns one :class:`~agentexchange.AgentExchangeWS` instance.  The WS
    connection runs in a background asyncio task; the manager provides
    synchronous read access to the buffered prices and an async primitive for
    order-fill events.

    Thread-safety: this class is **not** thread-safe.  It is designed for use
    in a single-threaded asyncio event loop.

    Args:
        config: Agent configuration (API key, base URL, symbols list).
    """

    def __init__(self, config: AgentConfig) -> None:
        self._config = config
        self._log = logger.bind(component="ws_manager", agent_id="agent")

        # Latest known price per symbol.  Written by the WS handler; read by
        # the trading loop.  Populated only after the first ticker message.
        self._price_buffer: dict[str, Decimal] = {}

        # Set when an order-fill arrives; cleared after the caller processes it.
        self._order_fill_event: asyncio.Event = asyncio.Event()

        # Track the most-recent fill payload for debugging / audit.
        self._last_fill: dict[str, Any] | None = None

        # Whether we have ever received at least one price tick.
        self._has_prices: bool = False

        # Whether the WS connection is currently live (best-effort flag).
        self._connected: bool = False

        # Background asyncio task running ws.connect()
        self._connect_task: asyncio.Task[None] | None = None

        # Lazily constructed WS client (built in connect() so we can
        # register handlers before connecting).
        self._ws: Any | None = None  # agentexchange.AgentExchangeWS

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the WebSocket connection as a background asyncio task.

        Builds the :class:`~agentexchange.AgentExchangeWS` client, registers
        ticker and order-update handlers for all configured symbols, and
        launches ``ws.connect()`` as a non-blocking background task.

        Calling :meth:`connect` on an already-running manager is a no-op.

        Raises:
            RuntimeError: If called outside a running asyncio event loop.
        """
        if self._connect_task is not None and not self._connect_task.done():
            self._log.debug("ws_manager.connect.already_running")
            return

        if not self._config.platform_api_key:
            self._log.warning(
                "ws_manager.connect.no_api_key",
                hint="Set PLATFORM_API_KEY in agent/.env to enable WebSocket streaming.",
            )
            return

        self._ws = self._build_ws_client()
        self._register_handlers()

        self._connect_task = asyncio.get_event_loop().create_task(
            self._run_ws(), name="ws_manager_connect"
        )
        self._log.info(
            "ws_manager.connect.task_started",
            symbols=self._config.symbols,
        )

    async def disconnect(self) -> None:
        """Stop the WebSocket connection and cancel the background task.

        Safe to call multiple times and when the manager was never started.
        After calling this method the price buffer is preserved but will no
        longer be updated.
        """
        self._connected = False

        if self._ws is not None:
            try:
                await self._ws.disconnect()
            except Exception as exc:  # noqa: BLE001
                self._log.debug("ws_manager.disconnect.ws_error", error=str(exc))
            self._ws = None

        if self._connect_task is not None and not self._connect_task.done():
            self._connect_task.cancel()
            try:
                await self._connect_task
            except asyncio.CancelledError:
                pass
        self._connect_task = None

        self._log.info("ws_manager.disconnected")

    # ------------------------------------------------------------------
    # Price buffer — synchronous reads
    # ------------------------------------------------------------------

    def get_price(self, symbol: str) -> Decimal | None:
        """Return the latest buffered price for *symbol*, or ``None``.

        Returns ``None`` when no tick has been received for that symbol yet.
        The caller should fall back to REST polling in that case.

        Args:
            symbol: Trading pair in the canonical format used by the platform
                (e.g. ``"BTCUSDT"``).

        Returns:
            Latest price as a :class:`~decimal.Decimal`, or ``None`` if no
            tick has been buffered for *symbol*.
        """
        return self._price_buffer.get(symbol)

    def get_all_prices(self) -> dict[str, Decimal]:
        """Return a shallow copy of the entire price buffer.

        Returns an empty dict when no ticks have been received yet.

        Returns:
            Dict mapping symbol → latest price.
        """
        return dict(self._price_buffer)

    @property
    def has_prices(self) -> bool:
        """``True`` after the first ticker message has been received."""
        return self._has_prices

    @property
    def is_connected(self) -> bool:
        """``True`` while the WebSocket background task is alive."""
        return (
            self._connect_task is not None
            and not self._connect_task.done()
            and self._connected
        )

    @property
    def price_buffer_size(self) -> int:
        """Number of symbols with at least one buffered tick."""
        return len(self._price_buffer)

    # ------------------------------------------------------------------
    # Order-fill events — async waiter
    # ------------------------------------------------------------------

    async def wait_for_order_fill(self, timeout: float = 5.0) -> bool:
        """Block until an order-fill arrives or *timeout* seconds elapse.

        Clears the internal event after waking so the next call blocks again.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            ``True`` if a fill arrived within *timeout*; ``False`` on timeout.
        """
        try:
            await asyncio.wait_for(self._order_fill_event.wait(), timeout=timeout)
            self._order_fill_event.clear()
            return True
        except TimeoutError:
            return False

    def clear_order_fill_event(self) -> None:
        """Clear the order-fill event without waiting.

        Useful when the caller processes a fill externally and wants to reset
        the event for the next notification.
        """
        self._order_fill_event.clear()

    @property
    def last_fill(self) -> dict[str, Any] | None:
        """The most-recently received order-fill payload, or ``None``."""
        return self._last_fill

    # ------------------------------------------------------------------
    # Internal construction helpers
    # ------------------------------------------------------------------

    def _build_ws_client(self) -> Any:  # noqa: ANN401 — returns AgentExchangeWS
        """Construct and return an :class:`~agentexchange.AgentExchangeWS` instance.

        The base URL is derived from ``config.platform_base_url`` by swapping
        the ``http`` scheme to ``ws`` (or ``https`` → ``wss``).

        Returns:
            A freshly constructed ``AgentExchangeWS`` client without active
            subscriptions or an open connection.
        """
        from agentexchange import AgentExchangeWS  # noqa: PLC0415

        ws_url = (
            self._config.platform_base_url
            .replace("https://", "wss://")
            .replace("http://", "ws://")
        )
        return AgentExchangeWS(
            api_key=self._config.platform_api_key,
            base_url=ws_url,
        )

    def _register_handlers(self) -> None:
        """Register ticker and order-update handlers on the WS client.

        Uses the decorator interface of :class:`~agentexchange.AgentExchangeWS`
        to set up per-symbol ticker handlers and a single order-fill handler.
        All configured symbols (``config.symbols``) get a dedicated handler.
        """
        if self._ws is None:
            return

        for symbol in self._config.symbols:
            # Capture symbol in closure via default arg.
            @self._ws.on_ticker(symbol)
            async def _on_tick(data: dict[str, Any], _sym: str = symbol) -> None:
                await self._handle_ticker(data, _sym)

        @self._ws.on_order_update()
        async def _on_fill(data: dict[str, Any]) -> None:
            await self._handle_order_fill(data)

        self._log.debug(
            "ws_manager.handlers_registered",
            symbols=self._config.symbols,
        )

    # ------------------------------------------------------------------
    # WS event handlers
    # ------------------------------------------------------------------

    async def _handle_ticker(self, data: dict[str, Any], symbol: str) -> None:
        """Update the price buffer when a ticker message arrives.

        Args:
            data: Raw ticker message dict from the server.  Expected to
                contain a ``price`` or ``last_price`` field.
            symbol: The trading pair this handler is registered for.
        """
        raw_price = data.get("price") or data.get("last_price") or data.get("close")
        if raw_price is None:
            self._log.debug(
                "ws_manager.ticker.no_price",
                symbol=symbol,
                keys=list(data.keys()),
            )
            return

        try:
            price = Decimal(str(raw_price))
        except InvalidOperation:
            self._log.warning(
                "ws_manager.ticker.bad_price",
                symbol=symbol,
                raw=str(raw_price)[:40],
            )
            return

        self._price_buffer[symbol] = price
        self._has_prices = True
        self._log.debug(
            "ws_manager.ticker.updated",
            symbol=symbol,
            price=str(price),
        )

    async def _handle_order_fill(self, data: dict[str, Any]) -> None:
        """Signal an order-fill event when an order-update arrives.

        Any order update triggers the event.  The trading loop should call
        ``wait_for_order_fill`` and then check positions to act on fills.

        Args:
            data: Raw order-update message dict from the server.  Contains
                ``order_id``, ``status``, ``symbol``, ``filled_quantity``, etc.
        """
        status = data.get("status", "")
        self._last_fill = data
        self._log.info(
            "ws_manager.order_fill",
            order_id=data.get("order_id", ""),
            symbol=data.get("symbol", ""),
            status=status,
            filled_qty=data.get("filled_quantity", data.get("executed_quantity", "")),
        )
        # Notify waiting coroutines that a fill has arrived.
        self._order_fill_event.set()

    # ------------------------------------------------------------------
    # Background connect runner
    # ------------------------------------------------------------------

    async def _run_ws(self) -> None:
        """Run ``ws.connect()`` and update the ``_connected`` flag.

        Wraps the blocking :meth:`~agentexchange.AgentExchangeWS.connect` call.
        Sets ``_connected = True`` before starting and ``_connected = False``
        when the task exits (normally or via cancellation).

        Any :class:`~agentexchange.exceptions.AuthenticationError` is logged
        at ERROR level.  All other errors are handled internally by the WS
        client's reconnection loop.
        """
        self._connected = True
        self._log.info("ws_manager.run_ws.started")
        try:
            if self._ws is not None:
                await self._ws.connect()
        except asyncio.CancelledError:
            self._log.info("ws_manager.run_ws.cancelled")
            raise
        except Exception as exc:  # noqa: BLE001
            self._log.error("ws_manager.run_ws.error", error=str(exc))
        finally:
            self._connected = False
            self._log.info("ws_manager.run_ws.exited")
