"""Price Cache — Redis-backed current price and ticker storage.

Redis data structures managed by this module:

1. Hash ``prices``
   - Field per pair → current price as string
   - ``HSET prices BTCUSDT 64521.30``
   - ``HGET prices BTCUSDT`` → ``"64521.30"``
   - ``HGETALL prices`` → ``{"BTCUSDT": "64521.30", ...}``

2. Hash ``prices:meta``
   - Field per pair → ISO-8601 last-update timestamp
   - Used to detect stale pairs (no update for >60 s → alert)

3. Hash ``ticker:{symbol}``
   - Fields: ``open``, ``high``, ``low``, ``close``,
     ``volume``, ``change_pct``, ``last_update``
   - Updated every tick; open is preserved for the trading session

Example::

    cache = PriceCache(redis_client.get_client())
    await cache.set_price("BTCUSDT", Decimal("64521.30"), datetime.now(UTC))
    price = await cache.get_price("BTCUSDT")
    ticker = await cache.get_ticker("BTCUSDT")
    stale = await cache.get_stale_pairs(threshold_seconds=60)
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import NamedTuple

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_KEY_PRICES = "prices"
_KEY_PRICES_META = "prices:meta"
_KEY_TICKER_PREFIX = "ticker:"


# ---------------------------------------------------------------------------
# Lightweight data containers
# ---------------------------------------------------------------------------


class Tick(NamedTuple):
    """Single trade tick received from Binance WebSocket.

    This namedtuple is the canonical in-flight data carrier shared between
    the price ingestion service, the tick buffer, the broadcaster, and this
    cache module.
    """

    symbol: str
    price: Decimal
    quantity: Decimal
    timestamp: datetime
    is_buyer_maker: bool
    trade_id: int


@dataclass(slots=True)
class TickerData:
    """24-hour rolling statistics for a single trading pair.

    All monetary fields use ``Decimal`` for exact arithmetic.
    ``change_pct`` is the percentage change from the session open.
    """

    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    change_pct: Decimal
    last_update: datetime


# ---------------------------------------------------------------------------
# PriceCache
# ---------------------------------------------------------------------------


class PriceCache:
    """High-performance Redis-backed price and ticker store.

    Args:
        redis: An already-connected ``redis.asyncio.Redis`` instance obtained
               from :class:`~src.cache.redis_client.RedisClient`.

    Example::

        cache = PriceCache(redis_client.get_client())
        await cache.set_price("BTCUSDT", Decimal("64521.30"), datetime.now(UTC))
    """

    def __init__(self, redis: aioredis.Redis) -> None:  # type: ignore[type-arg]
        self._redis = redis

    # ── Price operations ──────────────────────────────────────────────────────

    async def set_price(
        self,
        symbol: str,
        price: Decimal,
        timestamp: datetime,
    ) -> None:
        """Store the current price and its timestamp for *symbol*.

        Uses a single pipeline to write both ``prices`` and ``prices:meta``
        atomically from the caller's perspective.

        Args:
            symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.
            price: Current trade price.
            timestamp: UTC timestamp of the trade.
        """
        ts_str = timestamp.astimezone(UTC).isoformat()
        async with self._redis.pipeline(transaction=False) as pipe:
            pipe.hset(_KEY_PRICES, symbol, str(price))
            pipe.hset(_KEY_PRICES_META, symbol, ts_str)
            await pipe.execute()

    async def get_price(self, symbol: str) -> Decimal | None:
        """Return the latest price for *symbol*, or ``None`` if not cached.

        Args:
            symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.

        Returns:
            Current price as ``Decimal``, or ``None`` if the symbol is unknown.
        """
        raw: str | None = await self._redis.hget(_KEY_PRICES, symbol)
        if raw is None:
            return None
        return Decimal(raw)

    async def get_all_prices(self) -> dict[str, Decimal]:
        """Return a snapshot of all current prices.

        Returns:
            Mapping of symbol → price for every pair in the cache.
        """
        raw: dict[str, str] = await self._redis.hgetall(_KEY_PRICES)
        return {symbol: Decimal(price_str) for symbol, price_str in raw.items()}

    # ── Ticker operations ─────────────────────────────────────────────────────

    async def update_ticker(self, tick: Tick) -> None:
        """Update the rolling 24-hour ticker for the symbol in *tick*.

        On the **first** tick for a symbol the open price is initialised.
        Subsequent ticks update high / low / close / volume and recalculate
        ``change_pct`` relative to the stored open.

        Args:
            tick: A :class:`Tick` namedtuple from the ingestion service.
        """
        key = f"{_KEY_TICKER_PREFIX}{tick.symbol}"
        ts_str = tick.timestamp.astimezone(UTC).isoformat()

        existing: dict[str, str] = await self._redis.hgetall(key)

        if not existing:
            # First tick — initialise all fields
            fields: dict[str, str] = {
                "open": str(tick.price),
                "high": str(tick.price),
                "low": str(tick.price),
                "close": str(tick.price),
                "volume": str(tick.quantity),
                "change_pct": "0",
                "last_update": ts_str,
            }
        else:
            open_price = Decimal(existing["open"])
            high = max(Decimal(existing["high"]), tick.price)
            low = min(Decimal(existing["low"]), tick.price)
            volume = Decimal(existing["volume"]) + tick.quantity
            change_pct = (
                ((tick.price - open_price) / open_price * Decimal("100"))
                if open_price
                else Decimal("0")
            )
            fields = {
                "high": str(high),
                "low": str(low),
                "close": str(tick.price),
                "volume": str(volume),
                "change_pct": str(change_pct),
                "last_update": ts_str,
            }

        await self._redis.hset(key, mapping=fields)

    async def get_ticker(self, symbol: str) -> TickerData | None:
        """Return the 24-hour rolling ticker for *symbol*.

        Args:
            symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.

        Returns:
            :class:`TickerData` if the symbol exists in cache, else ``None``.
        """
        key = f"{_KEY_TICKER_PREFIX}{symbol}"
        raw: dict[str, str] = await self._redis.hgetall(key)
        if not raw:
            return None
        return TickerData(
            symbol=symbol,
            open=Decimal(raw["open"]),
            high=Decimal(raw["high"]),
            low=Decimal(raw["low"]),
            close=Decimal(raw["close"]),
            volume=Decimal(raw["volume"]),
            change_pct=Decimal(raw["change_pct"]),
            last_update=datetime.fromisoformat(raw["last_update"]),
        )

    # ── Staleness detection ───────────────────────────────────────────────────

    async def get_stale_pairs(self, threshold_seconds: int = 60) -> list[str]:
        """Return symbols whose last price update is older than *threshold_seconds*.

        Reads all timestamp entries from ``prices:meta`` and compares them
        against the current UTC time.

        Args:
            threshold_seconds: Age in seconds beyond which a pair is considered
                stale.  Defaults to 60.

        Returns:
            List of symbol strings with no recent update, sorted alphabetically.
        """
        now = datetime.now(UTC)
        meta: dict[str, str] = await self._redis.hgetall(_KEY_PRICES_META)

        stale: list[str] = []
        for symbol, ts_str in meta.items():
            try:
                last_update = datetime.fromisoformat(ts_str)
                age = (now - last_update).total_seconds()
                if age > threshold_seconds:
                    stale.append(symbol)
            except (ValueError, OverflowError):
                logger.warning("Corrupt timestamp for %s in prices:meta: %r", symbol, ts_str)
                stale.append(symbol)

        stale.sort()
        return stale
