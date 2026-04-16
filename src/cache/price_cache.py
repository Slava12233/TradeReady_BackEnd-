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

from datetime import UTC, datetime
from decimal import Decimal

import redis.asyncio as aioredis
from redis.exceptions import RedisError
import structlog

from src.cache.types import Tick, TickerData

logger = structlog.get_logger(__name__)

_KEY_PRICES = "prices"
_KEY_PRICES_META = "prices:meta"
_KEY_TICKER_PREFIX = "ticker:"

# ---------------------------------------------------------------------------
# Lua script for atomic ticker update (C2-1)
# ---------------------------------------------------------------------------
# Replaces the HGETALL → compute → HSET read-modify-write pattern with a
# single atomic Lua script executed inside Redis.  This eliminates the TOCTOU
# race where two concurrent coroutines processing ticks for the same symbol
# could both read stale state and overwrite each other's high/low/volume.
#
# KEYS[1] = "ticker:{symbol}"
# ARGV[1] = price string (e.g. "64521.30000000")
# ARGV[2] = quantity string
# ARGV[3] = ISO-8601 timestamp string
_UPDATE_TICKER_LUA = """
local key = KEYS[1]
local price_str = ARGV[1]
local qty_str   = ARGV[2]
local ts_str    = ARGV[3]

local existing = redis.call('HGETALL', key)

if #existing == 0 then
    redis.call('HSET', key,
        'open',        price_str,
        'high',        price_str,
        'low',         price_str,
        'close',       price_str,
        'volume',      qty_str,
        'change_pct',  '0',
        'last_update', ts_str
    )
else
    local fields = {}
    for i = 1, #existing, 2 do
        fields[existing[i]] = existing[i + 1]
    end

    local price      = tonumber(price_str)
    local open_price = tonumber(fields['open'])
    local high       = tonumber(fields['high'])
    local low        = tonumber(fields['low'])
    local volume     = tonumber(fields['volume'])

    if price > high then high = price end
    if price < low  then low  = price end
    volume = volume + tonumber(qty_str)

    local change_pct = 0
    if open_price ~= 0 then
        change_pct = (price - open_price) / open_price * 100
    end

    redis.call('HSET', key,
        'high',        string.format('%.8f', high),
        'low',         string.format('%.8f', low),
        'close',       price_str,
        'volume',      string.format('%.8f', volume),
        'change_pct',  string.format('%.8f', change_pct),
        'last_update', ts_str
    )
end
return 1
"""


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
        # Register the Lua script once per instance.  redis-py uses EVALSHA on
        # subsequent calls, falling back to EVAL only if the script was evicted.
        self._update_ticker_lua = self._redis.register_script(_UPDATE_TICKER_LUA)

    # ── Price operations ──────────────────────────────────────────────────────

    async def set_price(
        self,
        symbol: str,
        price: Decimal,
        timestamp: datetime,
    ) -> None:
        """Store the current price and its timestamp for *symbol*.

        Uses a single pipeline to batch ``prices`` and ``prices:meta`` writes
        in one TCP round-trip.  The two HSET commands are pipelined but not
        wrapped in MULTI/EXEC, so they are **not** transactionally atomic —
        a reader may briefly observe a new price before the corresponding
        timestamp lands in ``prices:meta`` (C2-6).

        Args:
            symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.
            price: Current trade price.
            timestamp: UTC timestamp of the trade.
        """
        ts_str = timestamp.astimezone(UTC).isoformat()
        try:
            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.hset(_KEY_PRICES, symbol, str(price))
                pipe.hset(_KEY_PRICES_META, symbol, ts_str)
                await pipe.execute()
        except RedisError as exc:
            logger.error("set_price_failed", symbol=symbol, error=str(exc))

    async def get_price(self, symbol: str) -> Decimal | None:
        """Return the latest price for *symbol*, or ``None`` if not cached.

        Args:
            symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.

        Returns:
            Current price as ``Decimal``, or ``None`` if the symbol is unknown
            or Redis is unavailable.
        """
        try:
            raw: str | None = await self._redis.hget(_KEY_PRICES, symbol)
            if raw is None:
                return None
            return Decimal(raw)
        except RedisError as exc:
            logger.error("get_price_failed", symbol=symbol, error=str(exc))
            return None

    async def get_all_prices(self) -> dict[str, Decimal]:
        """Return a snapshot of all current prices.

        Returns:
            Mapping of symbol → price for every pair in the cache, or an
            empty dict if Redis is unavailable.
        """
        try:
            raw: dict[str, str] = await self._redis.hgetall(_KEY_PRICES)
            return {sym: Decimal(p) for sym, p in raw.items()}
        except RedisError as exc:
            logger.error("get_all_prices_failed", error=str(exc))
            return {}

    # ── Ticker operations ─────────────────────────────────────────────────────

    async def update_ticker(self, tick: Tick) -> None:
        """Update the rolling 24-hour ticker for the symbol in *tick*.

        Executes a Lua script atomically inside Redis, eliminating the
        TOCTOU race that existed with the previous HGETALL → compute → HSET
        pattern (C2-1).  On the **first** tick for a symbol the open price is
        initialised; subsequent ticks update high / low / close / volume and
        recalculate ``change_pct`` relative to the stored open.

        Args:
            tick: A :class:`~src.cache.types.Tick` namedtuple from the
                ingestion service.
        """
        key = f"{_KEY_TICKER_PREFIX}{tick.symbol}"
        ts_str = tick.timestamp.astimezone(UTC).isoformat()
        try:
            await self._update_ticker_lua(
                keys=[key],
                args=[str(tick.price), str(tick.quantity), ts_str],
            )
        except RedisError as exc:
            logger.error("update_ticker_failed", symbol=tick.symbol, error=str(exc))

    async def get_ticker(self, symbol: str) -> TickerData | None:
        """Return the 24-hour rolling ticker for *symbol*.

        Args:
            symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.

        Returns:
            :class:`~src.cache.types.TickerData` if the symbol exists in
            cache, else ``None``.  Also returns ``None`` if any expected hash
            field is missing (partial write / eviction) or Redis is
            unavailable (C2-4).
        """
        key = f"{_KEY_TICKER_PREFIX}{symbol}"
        try:
            raw: dict[str, str] = await self._redis.hgetall(key)
            if not raw:
                return None
            try:
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
            except (KeyError, ValueError, OverflowError) as exc:
                logger.warning(
                    "get_ticker_partial_hash",
                    symbol=symbol,
                    error=str(exc),
                )
                return None
        except RedisError as exc:
            logger.error("get_ticker_failed", symbol=symbol, error=str(exc))
            return None

    # ── Staleness detection ───────────────────────────────────────────────────

    async def get_stale_pairs(self, threshold_seconds: int = 60) -> list[str] | None:
        """Return symbols whose last price update is older than *threshold_seconds*.

        Reads all timestamp entries from ``prices:meta`` and compares them
        against the current UTC time.

        Args:
            threshold_seconds: Age in seconds beyond which a pair is considered
                stale.  Defaults to 60.

        Returns:
            List of symbol strings with no recent update, sorted alphabetically.
            Returns ``None`` on Redis errors (fail-closed: callers must treat
            ``None`` as "staleness unknown / assume degraded").

        .. versionchanged:: 2026-04-15
           Changed from fail-open (empty list) to fail-closed (``None``) on
           Redis errors.  Returning ``[]`` falsely implied all pairs were
           fresh when Redis was unavailable.
        """
        try:
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
                    logger.warning(
                        "corrupt_timestamp",
                        symbol=symbol,
                        ts_str=ts_str,
                    )
                    stale.append(symbol)

            stale.sort()
            return stale
        except RedisError as exc:
            logger.warning(
                "staleness_check_degraded",
                error=str(exc),
                detail="Redis unavailable — staleness unknown, assuming degraded",
            )
            return None

    async def get_price_timestamp(self, symbol: str) -> datetime | None:
        """Return the last-update timestamp for *symbol* from ``prices:meta``.

        Provides a public accessor for the price metadata hash, avoiding
        direct ``_redis`` access from outside the cache module.

        Args:
            symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.

        Returns:
            ``datetime`` in UTC when metadata exists, or ``None`` when the
            symbol is not in the cache or Redis is unavailable.
        """
        try:
            raw: str | None = await self._redis.hget(_KEY_PRICES_META, symbol)
            if raw is None:
                return None
            return datetime.fromisoformat(raw)
        except (ValueError, OverflowError):
            logger.warning(
                "get_price_timestamp.corrupt_timestamp",
                symbol=symbol,
            )
            return None
        except RedisError as exc:
            logger.error(
                "get_price_timestamp.redis_error",
                symbol=symbol,
                error=str(exc),
            )
            return None

    async def get_all_price_timestamps(self) -> dict[str, str]:
        """Return all raw price metadata timestamps from ``prices:meta``.

        Provides a public accessor for the full ``prices:meta`` hash,
        avoiding direct ``_redis`` access from outside the cache module.

        Returns:
            Mapping of symbol → ISO-8601 timestamp string for all cached
            pairs.  Returns an empty dict on Redis errors.
        """
        try:
            result: dict[str, str] = await self._redis.hgetall(_KEY_PRICES_META)
            return result
        except RedisError as exc:
            logger.error("get_all_price_timestamps.redis_error", error=str(exc))
            return {}
