"""CCXT-based WebSocket client for streaming trade ticks from any exchange.

Drop-in replacement for :class:`BinanceWebSocketClient` that uses the
:class:`~src.exchange.CCXTAdapter` for exchange-agnostic tick streaming.

The downstream pipeline (``PriceCache``, ``TickBuffer``, ``PriceBroadcaster``)
receives the same ``Tick`` namedtuples regardless of which exchange is the source.

Example::

    client = ExchangeWebSocketClient("binance")
    await client.initialize()
    async for tick in client.listen():
        print(tick.symbol, tick.price)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import structlog

from src.cache.types import Tick
from src.exchange.ccxt_adapter import CCXTAdapter
from src.exchange.types import ExchangeTick

log = structlog.get_logger(__name__)


class ExchangeWebSocketClient:
    """Exchange-agnostic WebSocket client powered by CCXT.

    Produces :class:`~src.cache.types.Tick` namedtuples identical to those
    from :class:`BinanceWebSocketClient`, so the downstream pipeline is unchanged.

    Args:
        exchange_id: CCXT exchange identifier (e.g. ``"binance"``, ``"okx"``).
        config: Optional CCXT config dict (``apiKey``, ``secret``, etc.).
        quote_asset: Filter markets by this quote asset (default ``"USDT"``).
    """

    def __init__(
        self,
        exchange_id: str = "binance",
        config: dict | None = None,
        quote_asset: str = "USDT",
    ) -> None:
        self._adapter = CCXTAdapter(exchange_id, config)
        self._quote_asset = quote_asset
        self._symbols: list[str] = []

    async def initialize(self) -> None:
        """Load markets and fetch all trading pair symbols."""
        await self._adapter.initialize()
        markets = await self._adapter.fetch_markets(self._quote_asset)
        self._symbols = sorted(m.symbol for m in markets)
        log.info(
            "Exchange WebSocket client initialized",
            exchange=self._adapter.exchange_id,
            pairs=len(self._symbols),
        )

    def get_all_pairs(self) -> list[str]:
        """Return the list of platform-format symbols."""
        return list(self._symbols)

    async def listen(self) -> AsyncGenerator[Tick, None]:
        """Async generator that yields :class:`Tick` namedtuples.

        Wraps :meth:`CCXTAdapter.watch_trades` and converts
        :class:`ExchangeTick` to the platform's :class:`Tick` format.

        Yields:
            :class:`Tick` namedtuples as trades arrive.
        """
        if not self._symbols:
            await self.initialize()

        if not self._adapter.has_websocket:
            log.warning(
                "Exchange does not support WebSocket — falling back to REST polling",
                exchange=self._adapter.exchange_id,
            )
            async for tick in self._rest_poll_fallback():
                yield tick
            return

        log.info(
            "Starting CCXT WebSocket trade stream",
            exchange=self._adapter.exchange_id,
            symbol_count=len(self._symbols),
        )

        async for exchange_tick in self._adapter.watch_trades(self._symbols):
            yield self._to_tick(exchange_tick)

    async def _rest_poll_fallback(self) -> AsyncGenerator[Tick, None]:
        """Poll trades via REST for exchanges without WebSocket support.

        Polls each symbol in round-robin fashion with a small delay.
        This is a last resort — WebSocket is always preferred.
        """
        seen_trade_ids: set[str] = set()

        while True:
            for symbol in self._symbols:
                try:
                    trades = await self._adapter.fetch_trades(symbol, limit=10)
                    for et in trades:
                        if et.trade_id not in seen_trade_ids:
                            seen_trade_ids.add(et.trade_id)
                            yield self._to_tick(et)
                            # Cap memory for seen IDs.
                            if len(seen_trade_ids) > 100_000:
                                seen_trade_ids.clear()
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "REST poll error",
                        exchange=self._adapter.exchange_id,
                        symbol=symbol,
                        error=str(exc),
                    )
                await asyncio.sleep(0.1)

    async def close(self) -> None:
        """Release all connections."""
        await self._adapter.close()

    @staticmethod
    def _to_tick(et: ExchangeTick) -> Tick:
        """Convert an :class:`ExchangeTick` to the platform :class:`Tick`."""
        # trade_id must be int for the Tick namedtuple (matches DB schema).
        # CCXT returns string IDs; convert safely.
        try:
            trade_id = int(et.trade_id)
        except (ValueError, TypeError):
            trade_id = hash(et.trade_id) & 0x7FFFFFFFFFFFFFFF  # positive int64

        return Tick(
            symbol=et.symbol,
            price=et.price,
            quantity=et.quantity,
            timestamp=et.timestamp,
            is_buyer_maker=et.is_buyer_maker,
            trade_id=trade_id,
        )
