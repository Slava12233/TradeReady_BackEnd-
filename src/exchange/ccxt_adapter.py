"""CCXT-based implementation of :class:`ExchangeAdapter`.

Wraps ``ccxt.async_support`` for REST operations and ``ccxt.pro`` for
WebSocket streaming.  All CCXT imports and calls are confined to this file
— no other module in the platform should import ``ccxt`` directly.

Usage::

    adapter = CCXTAdapter("binance")
    await adapter.initialize()
    candles = await adapter.fetch_ohlcv("BTCUSDT", "1h", limit=100)
    await adapter.close()
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import structlog

from src.exchange.adapter import ExchangeAdapter
from src.exchange.symbol_mapper import SymbolMapper
from src.exchange.types import ExchangeCandle, ExchangeMarket, ExchangeTick

log = structlog.get_logger(__name__)


class CCXTAdapter(ExchangeAdapter):
    """Multi-exchange adapter powered by CCXT.

    Args:
        exchange_id: CCXT exchange identifier (e.g. ``"binance"``, ``"okx"``,
            ``"bybit"``, ``"coinbase"``, ``"hyperliquid"``).
        config: Optional CCXT exchange config dict (``apiKey``, ``secret``,
            ``sandbox``, etc.).
    """

    def __init__(self, exchange_id: str, config: dict[str, Any] | None = None) -> None:
        self._exchange_id = exchange_id.lower()
        self._config = config or {}

        # Disable the optional CCXT builder fee.
        self._config.setdefault("options", {})
        self._config["options"]["defaultType"] = self._config["options"].get("defaultType", "spot")

        self._mapper = SymbolMapper()

        # Lazy-initialized exchange instances.
        self._rest_exchange: Any = None
        self._ws_exchange: Any = None
        self._initialized = False

    async def initialize(self) -> None:
        """Load markets and build symbol mappings.

        Must be called once before using any fetch/watch methods.
        """
        if self._initialized:
            return

        self._rest_exchange = self._create_rest_exchange()
        await self._rest_exchange.load_markets()
        self._mapper.load_markets(self._rest_exchange.markets)
        self._initialized = True

        log.info(
            "CCXT adapter initialized",
            exchange=self._exchange_id,
            markets=len(self._rest_exchange.markets),
        )

    def _create_rest_exchange(self) -> Any:  # noqa: ANN401
        """Create a CCXT async REST exchange instance."""
        import ccxt.async_support as ccxt  # noqa: PLC0415

        exchange_class = getattr(ccxt, self._exchange_id, None)
        if exchange_class is None:
            msg = f"Unsupported exchange: {self._exchange_id}"
            raise ValueError(msg)

        config = {**self._config, "enableRateLimit": True}
        exchange = exchange_class(config)
        # Disable builder fee.
        exchange.options["builderFee"] = False
        return exchange

    def _create_ws_exchange(self) -> Any:  # noqa: ANN401
        """Create a CCXT Pro WebSocket exchange instance."""
        import ccxt.pro as ccxtpro  # noqa: PLC0415

        exchange_class = getattr(ccxtpro, self._exchange_id, None)
        if exchange_class is None:
            msg = f"Exchange {self._exchange_id} does not support WebSocket via CCXT Pro"
            raise ValueError(msg)

        config = {**self._config, "enableRateLimit": True}
        exchange = exchange_class(config)
        exchange.options["builderFee"] = False
        return exchange

    def _ensure_initialized(self) -> None:
        """Raise if :meth:`initialize` hasn't been called."""
        if not self._initialized:
            msg = "CCXTAdapter.initialize() must be called before use"
            raise RuntimeError(msg)

    # ── Market data (REST) ─────────────────────────────────────────────────

    async def fetch_markets(self, quote_asset: str = "USDT") -> list[ExchangeMarket]:
        """Fetch all active trading pairs filtered by quote asset."""
        self._ensure_initialized()

        markets: list[ExchangeMarket] = []
        quote_upper = quote_asset.upper()

        for _ccxt_sym, info in self._rest_exchange.markets.items():
            if info.get("quote", "").upper() != quote_upper:
                continue
            if not info.get("active", True):
                continue
            # Only include spot markets — swap/futures symbols cannot be mixed
            # with spot in CCXT's watch_trades_for_symbols().
            if info.get("type", "spot") != "spot":
                continue

            limits = info.get("limits", {})
            amount_limits = limits.get("amount", {})
            cost_limits = limits.get("cost", {})

            markets.append(
                ExchangeMarket(
                    symbol=self._mapper.from_ccxt(info["symbol"]),
                    base_asset=info.get("base", ""),
                    quote_asset=info.get("quote", ""),
                    status="active" if info.get("active", True) else "inactive",
                    min_qty=Decimal(str(amount_limits["min"])) if amount_limits.get("min") else None,
                    max_qty=Decimal(str(amount_limits["max"])) if amount_limits.get("max") else None,
                    step_size=Decimal(str(info.get("precision", {}).get("amount", "")))
                    if info.get("precision", {}).get("amount") is not None
                    else None,
                    min_notional=Decimal(str(cost_limits["min"])) if cost_limits.get("min") else None,
                    exchange=self._exchange_id,
                )
            )

        log.info(
            "Fetched markets",
            exchange=self._exchange_id,
            quote=quote_upper,
            count=len(markets),
        )
        return markets

    async def fetch_ticker(self, symbol: str) -> dict:  # type: ignore[type-arg]
        """Fetch 24-hour rolling stats for a single symbol."""
        self._ensure_initialized()

        ccxt_symbol = self._mapper.to_ccxt(symbol)
        raw = await self._rest_exchange.fetch_ticker(ccxt_symbol)

        return {
            "open": Decimal(str(raw.get("open", 0))) if raw.get("open") is not None else Decimal("0"),
            "high": Decimal(str(raw.get("high", 0))) if raw.get("high") is not None else Decimal("0"),
            "low": Decimal(str(raw.get("low", 0))) if raw.get("low") is not None else Decimal("0"),
            "close": Decimal(str(raw.get("close", 0))) if raw.get("close") is not None else Decimal("0"),
            "volume": Decimal(str(raw.get("baseVolume", 0))) if raw.get("baseVolume") is not None else Decimal("0"),
            "change_pct": Decimal(str(raw.get("percentage", 0))) if raw.get("percentage") is not None else Decimal("0"),
            "last_update": datetime.fromtimestamp(raw["timestamp"] / 1000, tz=UTC)
            if raw.get("timestamp")
            else datetime.now(tz=UTC),
        }

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1h",
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[ExchangeCandle]:
        """Fetch historical OHLCV candles."""
        self._ensure_initialized()

        ccxt_symbol = self._mapper.to_ccxt(symbol)
        since_ms = int(since.timestamp() * 1000) if since else None

        raw = await self._rest_exchange.fetch_ohlcv(
            ccxt_symbol,
            timeframe=timeframe,
            since=since_ms,
            limit=limit,
        )

        candles: list[ExchangeCandle] = []
        for row in raw:
            # CCXT OHLCV format: [timestamp_ms, open, high, low, close, volume]
            candles.append(
                ExchangeCandle(
                    timestamp=datetime.fromtimestamp(row[0] / 1000, tz=UTC),
                    open=Decimal(str(row[1])),
                    high=Decimal(str(row[2])),
                    low=Decimal(str(row[3])),
                    close=Decimal(str(row[4])),
                    volume=Decimal(str(row[5])),
                    trade_count=0,  # CCXT doesn't include trade count in OHLCV
                    exchange=self._exchange_id,
                )
            )

        return candles

    async def fetch_order_book(self, symbol: str, limit: int = 20) -> dict:  # type: ignore[type-arg]
        """Fetch current order book depth."""
        self._ensure_initialized()

        ccxt_symbol = self._mapper.to_ccxt(symbol)
        raw = await self._rest_exchange.fetch_order_book(ccxt_symbol, limit=limit)

        return {
            "bids": [[Decimal(str(p)), Decimal(str(q))] for p, q in raw.get("bids", [])],
            "asks": [[Decimal(str(p)), Decimal(str(q))] for p, q in raw.get("asks", [])],
        }

    async def fetch_trades(self, symbol: str, limit: int = 50) -> list[ExchangeTick]:
        """Fetch recent public trades."""
        self._ensure_initialized()

        ccxt_symbol = self._mapper.to_ccxt(symbol)
        raw = await self._rest_exchange.fetch_trades(ccxt_symbol, limit=limit)

        ticks: list[ExchangeTick] = []
        for trade in raw:
            ticks.append(
                ExchangeTick(
                    symbol=symbol.upper(),
                    price=Decimal(str(trade["price"])),
                    quantity=Decimal(str(trade["amount"])),
                    timestamp=datetime.fromtimestamp(trade["timestamp"] / 1000, tz=UTC)
                    if trade.get("timestamp")
                    else datetime.now(tz=UTC),
                    is_buyer_maker=trade.get("side", "").lower() != "buy",
                    trade_id=str(trade.get("id", "")),
                    exchange=self._exchange_id,
                )
            )

        return ticks

    # ── Real-time streaming (WebSocket) ────────────────────────────────────

    # Maximum symbols per ``watch_trades_for_symbols`` call.  Binance caps
    # this at 200; other exchanges may differ but 200 is a safe default.
    _WS_BATCH_SIZE = 200

    async def watch_trades(self, symbols: list[str]) -> AsyncGenerator[ExchangeTick, None]:
        """Stream real-time trades for the given symbols via CCXT Pro.

        When the symbol count exceeds :attr:`_WS_BATCH_SIZE`, multiple
        ``watch_trades_for_symbols`` calls run concurrently in background
        tasks and feed a shared :class:`asyncio.Queue`.
        """
        self._ensure_initialized()

        if self._ws_exchange is None:
            self._ws_exchange = self._create_ws_exchange()
            await self._ws_exchange.load_markets()

        ccxt_symbols = [self._mapper.to_ccxt(s) for s in symbols]

        log.info(
            "Starting WebSocket trade stream",
            exchange=self._exchange_id,
            symbol_count=len(ccxt_symbols),
        )

        if not hasattr(self._ws_exchange, "watch_trades_for_symbols"):
            # Fallback for exchanges without multi-symbol watch.
            async for tick in self._watch_trades_roundrobin(ccxt_symbols):
                yield tick
            return

        # Split into batches of _WS_BATCH_SIZE
        batches = [ccxt_symbols[i : i + self._WS_BATCH_SIZE] for i in range(0, len(ccxt_symbols), self._WS_BATCH_SIZE)]

        if len(batches) == 1:
            # Single batch — no need for queue overhead
            async for tick in self._watch_single_batch(batches[0]):
                yield tick
            return

        # Multiple batches — fan out to concurrent tasks via a shared queue
        queue: asyncio.Queue[ExchangeTick | None] = asyncio.Queue(maxsize=50_000)
        tasks = [asyncio.create_task(self._batch_watcher(batch, queue, idx)) for idx, batch in enumerate(batches)]

        log.info(
            "Multi-batch WebSocket stream started",
            exchange=self._exchange_id,
            batches=len(batches),
            symbols_per_batch=self._WS_BATCH_SIZE,
        )

        try:
            while True:
                item: ExchangeTick | None = await queue.get()
                if item is None:
                    break
                yield item
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _watch_single_batch(self, ccxt_symbols: list[str]) -> AsyncGenerator[ExchangeTick, None]:
        """Watch a single batch of symbols."""
        try:
            while True:
                trades = await self._ws_exchange.watch_trades_for_symbols(ccxt_symbols)
                for trade in trades:
                    yield self._parse_ws_trade(trade)
        except Exception as exc:
            log.error("WebSocket trade stream error", exchange=self._exchange_id, error=str(exc))
            raise

    async def _batch_watcher(
        self,
        ccxt_symbols: list[str],
        queue: asyncio.Queue[ExchangeTick | None],
        batch_idx: int,
    ) -> None:
        """Background task that watches one batch and pushes ticks to the queue."""
        try:
            while True:
                trades = await self._ws_exchange.watch_trades_for_symbols(ccxt_symbols)
                for trade in trades:
                    await queue.put(self._parse_ws_trade(trade))
        except asyncio.CancelledError:
            return
        except Exception as exc:
            log.error(
                "Batch watcher error",
                exchange=self._exchange_id,
                batch=batch_idx,
                error=str(exc),
            )
            await queue.put(None)  # signal termination

    async def _watch_trades_roundrobin(self, ccxt_symbols: list[str]) -> AsyncGenerator[ExchangeTick, None]:
        """Fallback: round-robin per-symbol watch_trades."""
        try:
            while True:
                for ccxt_sym in ccxt_symbols:
                    batch = await self._ws_exchange.watch_trades(ccxt_sym)
                    for trade in batch:
                        yield self._parse_ws_trade(trade)
        except Exception as exc:
            log.error("WebSocket trade stream error", exchange=self._exchange_id, error=str(exc))
            raise

    def _parse_ws_trade(self, trade: dict) -> ExchangeTick:  # type: ignore[type-arg]
        """Convert a raw CCXT WS trade dict to an :class:`ExchangeTick`."""
        platform_symbol = self._mapper.from_ccxt(trade.get("symbol", ""))
        return ExchangeTick(
            symbol=platform_symbol,
            price=Decimal(str(trade["price"])),
            quantity=Decimal(str(trade["amount"])),
            timestamp=datetime.fromtimestamp(trade["timestamp"] / 1000, tz=UTC)
            if trade.get("timestamp")
            else datetime.now(tz=UTC),
            is_buyer_maker=trade.get("side", "").lower() != "buy",
            trade_id=str(trade.get("id", "")),
            exchange=self._exchange_id,
        )

    # ── Trading (Phase 8) ──────────────────────────────────────────────────

    async def create_order(
        self,
        symbol: str,
        order_type: str,
        side: str,
        amount: Decimal,
        price: Decimal | None = None,
    ) -> dict:  # type: ignore[type-arg]
        """Place an order on the exchange."""
        self._ensure_initialized()

        ccxt_symbol = self._mapper.to_ccxt(symbol)
        result = await self._rest_exchange.create_order(
            ccxt_symbol,
            order_type,
            side,
            float(amount),
            float(price) if price is not None else None,
        )
        return result  # type: ignore[no-any-return]

    async def cancel_order(self, order_id: str, symbol: str) -> dict:  # type: ignore[type-arg]
        """Cancel an open order."""
        self._ensure_initialized()

        ccxt_symbol = self._mapper.to_ccxt(symbol)
        result = await self._rest_exchange.cancel_order(order_id, ccxt_symbol)
        return result  # type: ignore[no-any-return]

    async def fetch_balance(self) -> dict[str, Decimal]:
        """Fetch account balances."""
        self._ensure_initialized()

        raw = await self._rest_exchange.fetch_balance()
        balances: dict[str, Decimal] = {}
        for asset, info in raw.get("free", {}).items():
            if info and Decimal(str(info)) > Decimal("0"):
                balances[asset.upper()] = Decimal(str(info))
        return balances

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Release all connections and resources."""
        if self._rest_exchange is not None:
            await self._rest_exchange.close()
            self._rest_exchange = None

        if self._ws_exchange is not None:
            await self._ws_exchange.close()
            self._ws_exchange = None

        self._initialized = False
        log.info("CCXT adapter closed", exchange=self._exchange_id)

    # ── Metadata ───────────────────────────────────────────────────────────

    @property
    def exchange_id(self) -> str:
        """Short identifier for this exchange."""
        return self._exchange_id

    @property
    def has_websocket(self) -> bool:
        """Whether this exchange supports WebSocket streaming via CCXT Pro."""
        try:
            import ccxt.pro as ccxtpro  # noqa: PLC0415

            return hasattr(ccxtpro, self._exchange_id)
        except ImportError:
            return False

    @property
    def mapper(self) -> SymbolMapper:
        """Access the symbol mapper for external use."""
        return self._mapper
