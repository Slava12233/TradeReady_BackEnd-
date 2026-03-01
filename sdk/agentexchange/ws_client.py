"""WebSocket client for the AgentExchange trading platform.

Provides a decorator-based interface for subscribing to real-time data
channels (ticker, candles, orders, portfolio) served by the platform's
WebSocket endpoint at ``/ws/v1``.

Usage::

    from agentexchange import AgentExchangeWS

    ws = AgentExchangeWS(api_key="ak_live_...")

    @ws.on_ticker("BTCUSDT")
    async def handle_btc(data: dict) -> None:
        print(f"BTC price: {data['price']}")

    @ws.on_ticker("all")
    async def handle_all(data: dict) -> None:
        print(data)

    @ws.on_order_update()
    async def handle_order(data: dict) -> None:
        print(f"Order {data['order_id']} is {data['status']}")

    @ws.on_portfolio()
    async def handle_portfolio(data: dict) -> None:
        print(f"Portfolio value: {data['total_value']}")

    # Blocks until interrupted:
    await ws.connect()

    # Or manage subscribe/unsubscribe manually before connecting:
    ws.subscribe("candles:ETHUSDT:1m")
    await ws.connect()
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from agentexchange.exceptions import AuthenticationError, ConnectionError

logger = logging.getLogger(__name__)

# Type aliases
_Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]

_DEFAULT_BASE_URL = "ws://localhost:8000"
_WS_PATH = "/ws/v1"

# Reconnect back-off: start at 1 s, double each attempt, cap at 60 s.
_BACKOFF_MIN: float = 1.0
_BACKOFF_MAX: float = 60.0

# Heartbeat: server sends ping every 30 s; pong must arrive within 10 s.
_SERVER_PING_INTERVAL: float = 30.0
_PONG_TIMEOUT: float = 10.0


class AgentExchangeWS:
    """WebSocket client for the AgentExchange platform.

    Establishes a persistent WebSocket connection to ``/ws/v1``, manages
    channel subscriptions, dispatches server-pushed messages to registered
    handlers, responds to server heartbeat pings, and automatically
    reconnects after disconnections using exponential back-off.

    Args:
        api_key:  Agent API key (``ak_live_...`` format).
        base_url: WebSocket base URL of the platform.
                  Defaults to ``ws://localhost:8000``.

    Example::

        ws = AgentExchangeWS(api_key="ak_live_abc")

        @ws.on_ticker("BTCUSDT")
        async def on_btc(data):
            print(data["price"])

        await ws.connect()
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

        # channel -> list of async handlers
        self._handlers: dict[str, list[_Handler]] = defaultdict(list)
        # Channels to subscribe to on (re)connect. Managed by subscribe/unsubscribe.
        self._subscriptions: set[str] = set()
        # Running flag; set to False to stop reconnection loop.
        self._running = False
        # Active websocket connection (set while connected).
        self._ws: Any | None = None
        # Background tasks managed internally.
        self._tasks: list[asyncio.Task[None]] = []

    # ------------------------------------------------------------------
    # Decorator helpers
    # ------------------------------------------------------------------

    def on_ticker(self, symbol: str) -> Callable[[_Handler], _Handler]:
        """Register a handler for ticker price updates.

        Args:
            symbol: Trading pair symbol (e.g. ``"BTCUSDT"``) or ``"all"``
                    to receive updates for every symbol.

        Returns:
            Decorator that registers the async function as a handler.

        Example::

            @ws.on_ticker("BTCUSDT")
            async def handle(data: dict) -> None:
                print(data["price"])
        """
        channel = "ticker:all" if symbol.lower() == "all" else f"ticker:{symbol}"

        def decorator(fn: _Handler) -> _Handler:
            self._handlers[channel].append(fn)
            self._subscriptions.add(channel)
            return fn

        return decorator

    def on_candles(self, symbol: str, interval: str) -> Callable[[_Handler], _Handler]:
        """Register a handler for OHLCV candle updates.

        Args:
            symbol:   Trading pair symbol (e.g. ``"BTCUSDT"``).
            interval: Candle interval (e.g. ``"1m"``, ``"5m"``, ``"1h"``).

        Returns:
            Decorator that registers the async function as a handler.

        Example::

            @ws.on_candles("ETHUSDT", "1m")
            async def handle(data: dict) -> None:
                print(data["close"])
        """
        channel = f"candles:{symbol}:{interval}"

        def decorator(fn: _Handler) -> _Handler:
            self._handlers[channel].append(fn)
            self._subscriptions.add(channel)
            return fn

        return decorator

    def on_order_update(self) -> Callable[[_Handler], _Handler]:
        """Register a handler for order status change events.

        Returns:
            Decorator that registers the async function as a handler.

        Example::

            @ws.on_order_update()
            async def handle(data: dict) -> None:
                print(data["status"])
        """
        channel = "orders"

        def decorator(fn: _Handler) -> _Handler:
            self._handlers[channel].append(fn)
            self._subscriptions.add(channel)
            return fn

        return decorator

    def on_portfolio(self) -> Callable[[_Handler], _Handler]:
        """Register a handler for portfolio snapshot updates.

        Returns:
            Decorator that registers the async function as a handler.

        Example::

            @ws.on_portfolio()
            async def handle(data: dict) -> None:
                print(data["total_value"])
        """
        channel = "portfolio"

        def decorator(fn: _Handler) -> _Handler:
            self._handlers[channel].append(fn)
            self._subscriptions.add(channel)
            return fn

        return decorator

    # ------------------------------------------------------------------
    # Explicit subscription management
    # ------------------------------------------------------------------

    def subscribe(self, channel: str) -> None:
        """Add a channel to the subscription set.

        The channel will be subscribed on the next (re)connect if not already
        connected, or immediately if :meth:`connect` is active.

        Args:
            channel: Full channel name (e.g. ``"ticker:BTCUSDT"``,
                     ``"candles:ETHUSDT:1m"``, ``"orders"``, ``"portfolio"``).
        """
        self._subscriptions.add(channel)

    def unsubscribe(self, channel: str) -> None:
        """Remove a channel from the subscription set.

        Sends an unsubscribe message to the server if currently connected.

        Args:
            channel: Full channel name to remove.
        """
        self._subscriptions.discard(channel)
        if self._ws is not None:
            asyncio.ensure_future(self._send_action("unsubscribe", channel))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to the platform WebSocket and run the event loop.

        Blocks until :meth:`disconnect` is called or an unrecoverable error
        occurs.  Reconnects automatically on connection drops using
        exponential back-off (1 s → 2 s → 4 s … 60 s).

        Raises:
            AuthenticationError: If the server rejects the API key (1008 /
                                 4001 close code) — this is not retried.
            ConnectionError: On irrecoverable network failures.
        """
        self._running = True
        backoff = _BACKOFF_MIN

        while self._running:
            try:
                await self._run_session()
                # Clean disconnect (disconnect() was called).
                if not self._running:
                    break
                # Server closed cleanly but we didn't request it — reconnect.
                logger.info("WebSocket disconnected; reconnecting in %.1f s", backoff)
            except AuthenticationError:
                logger.error("Authentication rejected by server — stopping")
                self._running = False
                raise
            except (ConnectionClosed, WebSocketException, OSError) as exc:
                if not self._running:
                    break
                logger.warning(
                    "WebSocket error (%s); reconnecting in %.1f s", exc, backoff
                )
            except ConnectionError:
                if not self._running:
                    break
                logger.warning("Connection error; reconnecting in %.1f s", backoff)

            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)

        logger.debug("AgentExchangeWS connect loop exited")

    async def disconnect(self) -> None:
        """Gracefully close the WebSocket connection and stop reconnecting.

        Safe to call from any async context, including signal handlers.
        """
        self._running = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    # ------------------------------------------------------------------
    # Internal session management
    # ------------------------------------------------------------------

    async def _run_session(self) -> None:
        """Open one WebSocket session, subscribe to channels, and pump messages."""
        url = f"{self._base_url}{_WS_PATH}?api_key={self._api_key}"
        logger.debug("Connecting to %s", url)

        try:
            async with websockets.connect(url) as ws:
                self._ws = ws
                logger.info("WebSocket connected")

                # Subscribe to all registered channels.
                for channel in list(self._subscriptions):
                    await self._send_action("subscribe", channel)

                # Start heartbeat monitor task.
                heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))
                self._tasks = [heartbeat_task]

                try:
                    await self._message_loop(ws)
                finally:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
                    self._tasks.clear()

        except websockets.exceptions.InvalidStatus as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (401, 403, 1008):
                raise AuthenticationError(
                    "API key rejected by WebSocket server",
                    code="INVALID_API_KEY",
                    status_code=status or 401,
                ) from exc
            raise
        except OSError as exc:
            raise ConnectionError(
                f"Failed to connect to WebSocket: {exc}",
                code="CONNECTION_ERROR",
            ) from exc
        finally:
            self._ws = None

    async def _message_loop(self, ws: Any) -> None:
        """Receive and dispatch messages until the connection closes."""
        async for raw in ws:
            try:
                message: dict[str, Any] = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Received non-JSON WebSocket message: %.200s", raw)
                continue

            msg_type: str = message.get("type", "")

            if msg_type == "ping":
                # Server heartbeat — respond immediately.
                await self._send_raw(ws, {"type": "pong"})
                continue

            if msg_type == "error":
                logger.error(
                    "Server error on channel %s: %s",
                    message.get("channel", "unknown"),
                    message.get("message", ""),
                )
                continue

            await self._dispatch(message)

    async def _dispatch(self, message: dict[str, Any]) -> None:
        """Route an incoming server message to registered handlers.

        Matches on the ``type`` and ``channel`` fields in the message.
        Ticker messages carry ``symbol``; candle messages carry both
        ``symbol`` and ``interval``.
        """
        msg_type: str = message.get("type", "")
        channel: str | None = message.get("channel")

        # Resolve effective channel from message fields when not explicit.
        if channel is None:
            if msg_type == "ticker":
                symbol: str = message.get("symbol", "")
                channel = f"ticker:{symbol}"
            elif msg_type == "candle":
                symbol = message.get("symbol", "")
                interval: str = message.get("interval", "")
                channel = f"candles:{symbol}:{interval}"
            elif msg_type in ("order", "order_update"):
                channel = "orders"
            elif msg_type == "portfolio":
                channel = "portfolio"
            else:
                logger.debug("Unhandled message type: %s", msg_type)
                return

        handlers: list[_Handler] = []

        # Collect exact-channel handlers.
        handlers.extend(self._handlers.get(channel, []))

        # Ticker: also dispatch to wildcard "ticker:all" handlers.
        if channel.startswith("ticker:") and channel != "ticker:all":
            handlers.extend(self._handlers.get("ticker:all", []))

        if not handlers:
            logger.debug("No handlers for channel %s", channel)
            return

        for handler in handlers:
            try:
                await handler(message)
            except Exception as exc:
                logger.exception(
                    "Handler %s raised an exception for channel %s: %s",
                    getattr(handler, "__name__", handler),
                    channel,
                    exc,
                )

    async def _heartbeat_loop(self, ws: Any) -> None:
        """Monitor for server heartbeat pings and send pongs.

        The server sends ``{"type": "ping"}`` every ~30 seconds.  Pongs are
        sent directly in ``_message_loop`` upon receipt.  This task
        independently closes the connection if no message has arrived for
        ``_SERVER_PING_INTERVAL + _PONG_TIMEOUT`` seconds, guarding against
        silent connection drops.
        """
        idle_timeout = _SERVER_PING_INTERVAL + _PONG_TIMEOUT
        try:
            while True:
                await asyncio.sleep(idle_timeout)
                # If we're still here the connection is considered stale.
                logger.warning(
                    "No message received in %.0f s — closing stale connection",
                    idle_timeout,
                )
                await ws.close()
                return
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # Low-level send helpers
    # ------------------------------------------------------------------

    async def _send_action(self, action: str, channel: str) -> None:
        """Send a subscribe/unsubscribe control message."""
        if self._ws is None:
            return
        payload = {"action": action, "channel": channel}
        await self._send_raw(self._ws, payload)

    @staticmethod
    async def _send_raw(ws: Any, payload: dict[str, Any]) -> None:
        """Serialise *payload* to JSON and send it, swallowing closed-connection errors."""
        try:
            await ws.send(json.dumps(payload))
        except ConnectionClosed:
            pass
        except WebSocketException as exc:
            logger.debug("Could not send message: %s", exc)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "AgentExchangeWS":
        """Support ``async with AgentExchangeWS(...) as ws:``."""
        return self

    async def __aexit__(self, *_: Any) -> None:
        """Disconnect cleanly on context-manager exit."""
        await self.disconnect()

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        key_preview = self._api_key[:12] + "..." if len(self._api_key) > 12 else self._api_key
        return (
            f"AgentExchangeWS(api_key={key_preview!r}, "
            f"base_url={self._base_url!r}, "
            f"subscriptions={sorted(self._subscriptions)!r})"
        )


__all__ = ["AgentExchangeWS"]
