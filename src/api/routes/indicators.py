"""Market indicators routes for the AI Agent Crypto Trading Platform.

Exposes the :class:`~src.strategies.indicators.IndicatorEngine` via REST so
that external agents can consume pre-computed technical indicators without
re-implementing them.

Endpoints:

- ``GET /api/v1/market/indicators/available`` — static list of supported indicators
- ``GET /api/v1/market/indicators/{symbol}``   — computed indicator values for a symbol

Both endpoints are **public** (no authentication required) and fall under the
``/api/v1/market/*`` prefix, which is already whitelisted in ``AuthMiddleware``.

Caching strategy:
    Computed results are stored in Redis with a 30-second TTL.  The cache key
    is ``indicators:{symbol}:{indicator_hash}`` where ``indicator_hash`` is a
    stable hex digest of the sorted requested indicator names.  Different
    indicator subsets therefore use separate cache entries.

Example::

    GET /api/v1/market/indicators/BTCUSDT
    → {
        "symbol": "BTCUSDT",
        "timestamp": "2026-04-07T12:00:00Z",
        "candles_used": 200,
        "indicators": {"rsi_14": 54.32, "sma_20": 64300.12, ...}
      }

    GET /api/v1/market/indicators/BTCUSDT?indicators=rsi_14,sma_20
    GET /api/v1/market/indicators/BTCUSDT?lookback=100

    GET /api/v1/market/indicators/available
    → {"indicators": ["adx_14", "atr_14", ...]}
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import logging
import re
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import text

from src.api.schemas.indicators import AvailableIndicatorsResponse, IndicatorResponse
from src.dependencies import DbSessionDep, RedisDep
from src.utils.exceptions import InvalidSymbolError, ServiceUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/market", tags=["market"])

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Regex for valid symbol format: 2-10 uppercase letters followed by USDT.
_SYMBOL_RE = re.compile(r"^[A-Z]{2,10}USDT$")

# Redis TTL for cached indicator results (seconds).
_CACHE_TTL_SECONDS = 30

# Mapping from the public API names (task spec) to the keys returned by
# IndicatorEngine.compute().  The engine uses "adx" / "atr" / "bb_middle" /
# "current_price" internally; we re-label them to the agreed API names.
_ENGINE_KEY_MAP: dict[str, str] = {
    "rsi_14": "rsi_14",
    "macd_line": "macd_line",
    "macd_signal": "macd_signal",
    "macd_hist": "macd_hist",
    "sma_20": "sma_20",
    "sma_50": "sma_50",
    "ema_12": "ema_12",
    "ema_26": "ema_26",
    "bb_upper": "bb_upper",
    "bb_mid": "bb_middle",   # engine returns "bb_middle"
    "bb_lower": "bb_lower",
    "adx_14": "adx",         # engine returns "adx"
    "atr_14": "atr",          # engine returns "atr"
    "volume_ma_20": "volume_ma_20",
    "price": "current_price", # engine returns "current_price"
}

# Supported public indicator names (sorted for stable display).
_ALL_INDICATORS: list[str] = sorted(_ENGINE_KEY_MAP.keys())

# Lookback bounds for the query parameter.
_LOOKBACK_MIN = 14
_LOOKBACK_MAX = 500
_LOOKBACK_DEFAULT = 200


# ---------------------------------------------------------------------------
# GET /api/v1/market/indicators/available
# ---------------------------------------------------------------------------


@router.get(
    "/indicators/available",
    response_model=AvailableIndicatorsResponse,
    summary="List all supported indicators",
    description=(
        "Returns the complete static list of indicator names that "
        "``GET /api/v1/market/indicators/{symbol}`` can compute."
    ),
)
async def list_available_indicators() -> AvailableIndicatorsResponse:
    """Return the static list of all indicator names supported by the engine.

    No database or Redis access is needed; the list is derived from the
    :data:`_ENGINE_KEY_MAP` constant.

    Returns:
        :class:`~src.api.schemas.indicators.AvailableIndicatorsResponse` with
        an alphabetically sorted list of indicator names.

    Example::

        GET /api/v1/market/indicators/available
        → {"indicators": ["adx_14", "atr_14", "bb_lower", ...]}
    """
    return AvailableIndicatorsResponse(indicators=_ALL_INDICATORS)


# ---------------------------------------------------------------------------
# GET /api/v1/market/indicators/{symbol}
# ---------------------------------------------------------------------------


@router.get(
    "/indicators/{symbol}",
    response_model=IndicatorResponse,
    summary="Get computed technical indicators for a trading pair",
    description=(
        "Computes technical indicators from the most recent 1-minute candles "
        "stored in TimescaleDB. Results are cached in Redis for 30 seconds. "
        "Use the ``indicators`` query parameter to filter to a subset of the "
        "available indicators."
    ),
)
async def get_indicators(
    symbol: str,
    db: DbSessionDep,
    redis: RedisDep,
    indicators: Annotated[
        str | None,
        Query(
            description=(
                "Comma-separated list of indicator names to return. "
                "Omit to return all supported indicators. "
                "Example: ``rsi_14,sma_20,macd_line``."
            ),
            examples=["rsi_14,sma_20,macd_line"],
        ),
    ] = None,
    lookback: Annotated[
        int,
        Query(
            ge=_LOOKBACK_MIN,
            le=_LOOKBACK_MAX,
            description=(
                f"Number of 1-minute candles to use for computation "
                f"({_LOOKBACK_MIN}–{_LOOKBACK_MAX}, default {_LOOKBACK_DEFAULT})."
            ),
            examples=[200],
        ),
    ] = _LOOKBACK_DEFAULT,
) -> IndicatorResponse:
    """Compute technical indicators for *symbol* from recent 1-minute candles.

    Implementation flow:

    1. Validate the symbol format (``^[A-Z]{2,10}USDT$``).
    2. Resolve and validate the requested indicator names against the supported
       list; raises HTTP 400 on unknown names.
    3. Check Redis for a cached result (key ``indicators:{symbol}:{hash}``,
       TTL 30 s).
    4. On cache miss: query the last *lookback* 1-minute candles from
       ``candles_1m`` in TimescaleDB.
    5. Feed candles into a fresh :class:`~src.strategies.indicators.IndicatorEngine`
       instance via :meth:`~src.strategies.indicators.IndicatorEngine.update`.
    6. Call :meth:`~src.strategies.indicators.IndicatorEngine.compute` and remap
       internal engine keys to the public API names.
    7. Filter to the requested indicators.
    8. Store the result in Redis and return the response.

    Args:
        symbol:     Uppercase trading pair symbol, e.g. ``"BTCUSDT"``.
        db:         Injected async database session.
        redis:      Injected async Redis client.
        indicators: Optional comma-separated indicator filter.
        lookback:   Number of 1-minute candles to use (14–500, default 200).

    Returns:
        :class:`~src.api.schemas.indicators.IndicatorResponse`.

    Raises:
        :exc:`~src.utils.exceptions.InvalidSymbolError`:
            Symbol format is invalid (HTTP 400).
        :exc:`~src.utils.exceptions.ServiceUnavailableError`:
            No candle data is available for the symbol (HTTP 503).

    Example::

        GET /api/v1/market/indicators/BTCUSDT
        GET /api/v1/market/indicators/BTCUSDT?indicators=rsi_14,sma_20&lookback=100
    """
    # ── 1. Validate symbol format ─────────────────────────────────────────────
    symbol = symbol.upper()
    if not _SYMBOL_RE.match(symbol):
        raise InvalidSymbolError(
            f"Symbol '{symbol}' is not valid. Expected format: 2-10 uppercase letters followed by USDT."
        )

    # ── 2. Resolve requested indicator names ──────────────────────────────────
    requested_names = _resolve_indicator_names(indicators)

    # ── 3. Build cache key and check Redis ────────────────────────────────────
    cache_key = _build_cache_key(symbol, requested_names)
    cached = await _get_cached(redis, cache_key)
    if cached is not None:
        logger.debug(
            "market.indicators.cache_hit",
            extra={"symbol": symbol, "key": cache_key},
        )
        return cached

    # ── 4. Query 1-minute candles from TimescaleDB ────────────────────────────
    rows = await _fetch_candles(db, symbol, lookback)

    if not rows:
        raise ServiceUnavailableError(
            details={
                "reason": f"No 1-minute candle data available for {symbol}. "
                "The price ingestion service may not have data for this pair yet."
            }
        )

    # ── 5. Feed candles into a fresh IndicatorEngine ─────────────────────────
    from src.strategies.indicators import IndicatorEngine  # noqa: PLC0415

    engine = IndicatorEngine(max_history=lookback)
    # Rows come back oldest-first (see ORDER BY ASC in _fetch_candles).
    for row in rows:
        engine.update(
            symbol,
            {
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
            },
        )

    # ── 6. Compute and remap indicator keys ───────────────────────────────────
    raw = engine.compute(symbol)
    indicator_values = _remap_and_filter(raw, requested_names)

    # ── 7. Build response ─────────────────────────────────────────────────────
    now = datetime.now(UTC)
    response = IndicatorResponse(
        symbol=symbol,
        timestamp=now,
        candles_used=len(rows),
        indicators=indicator_values,
    )

    # ── 8. Cache result ───────────────────────────────────────────────────────
    await _set_cached(redis, cache_key, response)

    logger.debug(
        "market.indicators.computed",
        extra={
            "symbol": symbol,
            "candles_used": len(rows),
            "indicators_returned": len(indicator_values),
        },
    )

    return response


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_indicator_names(indicators_param: str | None) -> list[str]:
    """Parse and validate the ``indicators`` query parameter.

    Args:
        indicators_param: Raw comma-separated string from the query, or ``None``
                          to select all supported indicators.

    Returns:
        Sorted list of valid indicator names to compute.

    Raises:
        :exc:`~src.utils.exceptions.InvalidSymbolError`:
            One or more requested indicator names are not supported.
    """
    if indicators_param is None:
        return list(_ALL_INDICATORS)

    requested = [name.strip() for name in indicators_param.split(",") if name.strip()]
    unknown = [name for name in requested if name not in _ENGINE_KEY_MAP]
    if unknown:
        raise InvalidSymbolError(
            f"Unknown indicator(s): {', '.join(sorted(unknown))}. "
            f"Supported: {', '.join(_ALL_INDICATORS)}."
        )
    # Return in sorted order to produce a stable cache key.
    return sorted(set(requested))


def _build_cache_key(symbol: str, indicator_names: list[str]) -> str:
    """Build a stable Redis cache key for the indicator result.

    The key encodes the symbol and a short hash of the sorted indicator names
    so that different subsets of indicators use separate cache entries.

    Args:
        symbol:          Uppercase symbol string.
        indicator_names: Sorted list of requested indicator names.

    Returns:
        Redis key string in the form ``indicators:{symbol}:{8-char hash}``.
    """
    names_str = ",".join(indicator_names)
    indicator_hash = hashlib.md5(names_str.encode(), usedforsecurity=False).hexdigest()[:8]  # noqa: S324
    return f"indicators:{symbol}:{indicator_hash}"


async def _get_cached(redis: object, cache_key: str) -> IndicatorResponse | None:
    """Attempt to retrieve a cached :class:`IndicatorResponse` from Redis.

    Args:
        redis:     Async Redis client (injected via ``RedisDep``).
        cache_key: The Redis key to look up.

    Returns:
        Deserialised :class:`IndicatorResponse` if a valid cache entry exists,
        otherwise ``None``.
    """
    import redis.asyncio as aioredis  # noqa: PLC0415

    try:
        raw: str | None = await redis.get(cache_key)  # type: ignore[union-attr]
        if raw is None:
            return None
        data = json.loads(raw)
        return IndicatorResponse.model_validate(data)
    except (aioredis.RedisError, json.JSONDecodeError, Exception) as exc:
        logger.warning(
            "market.indicators.cache_read_error",
            extra={"key": cache_key, "error": str(exc)},
        )
        return None


async def _set_cached(redis: object, cache_key: str, response: IndicatorResponse) -> None:
    """Serialise and store an :class:`IndicatorResponse` in Redis.

    Failures are logged and swallowed so that a Redis outage does not break
    the endpoint (fail-open strategy).

    Args:
        redis:     Async Redis client.
        cache_key: The Redis key to write.
        response:  The response to cache.
    """
    import redis.asyncio as aioredis  # noqa: PLC0415

    try:
        payload = response.model_dump(mode="json")
        await redis.setex(cache_key, _CACHE_TTL_SECONDS, json.dumps(payload))  # type: ignore[union-attr]
    except (aioredis.RedisError, Exception) as exc:
        logger.warning(
            "market.indicators.cache_write_error",
            extra={"key": cache_key, "error": str(exc)},
        )


async def _fetch_candles(db: object, symbol: str, lookback: int) -> list[object]:
    """Query the last *lookback* 1-minute candles for *symbol* from TimescaleDB.

    Uses the ``candles_1m`` continuous-aggregate view, ordered oldest-first so
    the :class:`~src.strategies.indicators.IndicatorEngine` receives bars in
    chronological sequence.

    Args:
        db:       Async SQLAlchemy session.
        symbol:   Uppercase symbol string.
        lookback: Maximum number of candles to fetch.

    Returns:
        List of row objects with ``high``, ``low``, ``close``, ``volume`` fields,
        ordered oldest-first. May be empty if no data exists for the symbol.
    """
    from sqlalchemy.exc import SQLAlchemyError  # noqa: PLC0415

    try:
        # Fetch DESC for LIMIT efficiency, then reverse for chronological order.
        raw_sql = text(
            "SELECT bucket, open, high, low, close, volume "
            "FROM candles_1m "
            "WHERE symbol = :symbol "
            "ORDER BY bucket DESC "
            "LIMIT :limit"
        )
        result = await db.execute(raw_sql, {"symbol": symbol, "limit": lookback})  # type: ignore[union-attr]
        rows = result.fetchall()
        # Reverse to get oldest-first chronological order.
        return list(reversed(rows))
    except SQLAlchemyError as exc:
        logger.error(
            "market.indicators.db_error",
            extra={"symbol": symbol, "error": str(exc)},
        )
        return []


def _remap_and_filter(
    raw: dict[str, float | None],
    requested_names: list[str],
) -> dict[str, float]:
    """Remap internal engine keys to public API names and filter to requested set.

    Indicator values that are ``None`` (insufficient data for the period) are
    excluded from the output dict.

    Args:
        raw:             Raw dict from :meth:`IndicatorEngine.compute`.
        requested_names: Sorted list of public API indicator names to include.

    Returns:
        Dict mapping public indicator name → computed float value.
        Entries with ``None`` values are omitted.
    """
    result: dict[str, float] = {}
    for public_name in requested_names:
        engine_key = _ENGINE_KEY_MAP[public_name]
        value = raw.get(engine_key)
        if value is not None:
            result[public_name] = float(value)
    return result
