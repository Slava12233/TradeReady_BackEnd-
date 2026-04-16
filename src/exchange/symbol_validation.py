"""Cached symbol validation helper.

Provides :func:`is_valid_symbol_cached` which checks whether a trading-pair
symbol is valid by first consulting a Redis set (``valid_symbols``) and only
falling back to a TimescaleDB query when the cache is empty or on a Redis
error.

Redis data structure
--------------------
``valid_symbols``  — Redis Set
    Members are uppercase platform symbols, e.g. ``"BTCUSDT"``.
    Populated on the first cache miss; expires after :data:`_CACHE_TTL_SECONDS`.

Cache strategy
--------------
1. ``SISMEMBER valid_symbols <symbol>`` — O(1) hit check.
2. If the set is empty (``SCARD == 0``), load all symbols from DB and populate
   the set with ``SADD`` + ``EXPIRE``.  This is a "load-on-first-miss" pattern
   so the first call after a cold start (or after TTL expiry) pays the DB cost.
3. After population, re-check membership — return ``True`` only if the symbol
   is in the newly loaded set.
4. On any :class:`redis.exceptions.RedisError`, fall back transparently to a
   single-row DB query so the endpoint keeps working even if Redis is down.

Thread/concurrency safety
--------------------------
Multiple concurrent requests can all hit the "cache empty" branch at startup
and all call ``SADD`` with the full symbol set.  Redis ``SADD`` is idempotent
for existing members, so this is safe — it results in a brief burst of DB
queries during cold-start only.
"""

from __future__ import annotations

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import TradingPair

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CACHE_KEY = "valid_symbols"
"""Redis key for the set of valid trading-pair symbols."""

_CACHE_TTL_SECONDS = 300
"""Time-to-live for the ``valid_symbols`` set — 5 minutes."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def is_valid_symbol_cached(
    symbol: str,
    redis: Redis,  # type: ignore[type-arg]
    db: AsyncSession,
) -> bool:
    """Return ``True`` if *symbol* is a known trading pair, using Redis cache.

    Checks the ``valid_symbols`` Redis set first (O(1)).  On a complete cache
    miss (set does not exist) loads the full symbol list from the DB and
    populates Redis for subsequent requests.  Falls back to a single-row DB
    query on any Redis error so the endpoint never fails due to a Redis outage.

    Args:
        symbol: Uppercase trading-pair symbol, e.g. ``"BTCUSDT"``.
        redis:  Async Redis client from the shared connection pool.
        db:     Async SQLAlchemy session (used for DB fallback).

    Returns:
        ``True`` if the symbol exists in ``trading_pairs``; ``False`` otherwise.

    Example::

        valid = await is_valid_symbol_cached("BTCUSDT", redis, db)
        if not valid:
            raise InvalidSymbolError(symbol=symbol)
    """
    try:
        # ── Fast path: check Redis set membership ──────────────────────────
        is_member: bool = bool(await redis.sismember(_CACHE_KEY, symbol))
        if is_member:
            logger.debug("symbol_validation.cache_hit", symbol=symbol)
            return True

        # ── Check whether the set exists at all ────────────────────────────
        cache_size: int = await redis.scard(_CACHE_KEY)
        if cache_size > 0:
            # Cache is populated but symbol is not in it → invalid symbol.
            logger.debug(
                "symbol_validation.cache_miss_not_found",
                symbol=symbol,
                cache_size=cache_size,
            )
            return False

        # ── Cache empty — populate from DB then re-check ───────────────────
        logger.debug("symbol_validation.cache_populate", symbol=symbol)
        symbols = await _load_symbols_from_db(db)

        if not symbols:
            # Empty DB edge case — treat as not found (should never happen).
            return False

        await redis.sadd(_CACHE_KEY, *symbols)  # type: ignore[misc]
        await redis.expire(_CACHE_KEY, _CACHE_TTL_SECONDS)

        found = symbol in symbols
        logger.debug(
            "symbol_validation.cache_populated",
            symbol=symbol,
            total=len(symbols),
            found=found,
        )
        return found

    except RedisError as exc:
        # ── Redis unavailable — fall back to DB query ──────────────────────
        logger.warning(
            "symbol_validation.redis_error_fallback",
            symbol=symbol,
            error=str(exc),
        )
        return await _check_symbol_db(symbol, db)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _load_symbols_from_db(db: AsyncSession) -> list[str]:
    """Return all symbol strings from the ``trading_pairs`` table.

    Args:
        db: Async SQLAlchemy session.

    Returns:
        List of uppercase symbol strings, e.g. ``["BTCUSDT", "ETHUSDT", ...]``.
    """
    result = await db.execute(select(TradingPair.symbol))
    return list(result.scalars().all())


async def _check_symbol_db(symbol: str, db: AsyncSession) -> bool:
    """Return ``True`` if *symbol* exists in ``trading_pairs`` (single-row query).

    Used as a Redis-error fallback so we never fail open or closed without
    checking the authoritative source.

    Args:
        symbol: Uppercase trading-pair symbol.
        db:     Async SQLAlchemy session.

    Returns:
        ``True`` if found; ``False`` otherwise.
    """
    result = await db.execute(select(TradingPair.symbol).where(TradingPair.symbol == symbol).limit(1))
    return result.scalar_one_or_none() is not None
