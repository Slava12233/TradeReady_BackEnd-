"""Unit tests for :mod:`src.exchange.symbol_validation`.

Test coverage:
- Cache hit: ``sismember`` returns truthy → no DB query, returns True.
- Cache populated but symbol absent: ``scard > 0`` and ``sismember`` False → returns False without DB query.
- Cache empty (cold start): populates Redis set from DB, returns True for known symbol.
- Cache empty (cold start): returns False for unknown symbol even after DB load.
- Empty DB edge case: ``trading_pairs`` table is empty → returns False.
- Redis error on ``sismember``: falls back to single-row DB query, returns True.
- Redis error on ``sismember``: falls back to single-row DB query, returns False for unknown.
- Redis SADD called with all symbols on first population.
- EXPIRE called with correct TTL after SADD.
- Cache populated for second symbol in same set without re-hitting DB.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from redis.exceptions import RedisError

from src.exchange.symbol_validation import (
    _CACHE_KEY,
    _CACHE_TTL_SECONDS,
    _check_symbol_db,
    _load_symbols_from_db,
    is_valid_symbol_cached,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_redis() -> AsyncMock:
    """Return a minimal mock Redis client with set-operation methods wired."""
    redis = AsyncMock()
    redis.sismember = AsyncMock(return_value=False)
    redis.scard = AsyncMock(return_value=0)
    redis.sadd = AsyncMock(return_value=600)
    redis.expire = AsyncMock(return_value=True)
    return redis


@pytest.fixture()
def mock_db() -> AsyncMock:
    """Return a mock AsyncSession with ``execute`` pre-wired."""
    db = AsyncMock()
    return db


def _make_scalars_result(values: list[str]) -> MagicMock:
    """Build a mock SQLAlchemy execute result whose scalars().all() returns *values*."""
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = values
    result_mock = MagicMock()
    result_mock.scalars.return_value = scalars_mock
    return result_mock


def _make_scalar_one_or_none_result(value: str | None) -> MagicMock:
    """Build a mock result for ``scalar_one_or_none()`` returning *value*."""
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = value
    return result_mock


# ---------------------------------------------------------------------------
# Cache hit
# ---------------------------------------------------------------------------


async def test_cache_hit_returns_true_without_db(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """When sismember returns truthy the function returns True immediately."""
    mock_redis.sismember.return_value = True

    result = await is_valid_symbol_cached("BTCUSDT", mock_redis, mock_db)

    assert result is True
    mock_redis.sismember.assert_awaited_once_with(_CACHE_KEY, "BTCUSDT")
    mock_redis.scard.assert_not_awaited()
    mock_db.execute.assert_not_awaited()


async def test_cache_hit_does_not_call_sadd(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """A cache hit never triggers a DB populate cycle."""
    mock_redis.sismember.return_value = 1  # truthy int, as redis-py may return

    result = await is_valid_symbol_cached("ETHUSDT", mock_redis, mock_db)

    assert result is True
    mock_redis.sadd.assert_not_awaited()
    mock_redis.expire.assert_not_awaited()


# ---------------------------------------------------------------------------
# Cache populated, symbol absent (miss)
# ---------------------------------------------------------------------------


async def test_cache_populated_symbol_absent_returns_false(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """When the cache set exists but the symbol is not a member, return False."""
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 500  # cache is populated

    result = await is_valid_symbol_cached("XYZUSDT", mock_redis, mock_db)

    assert result is False
    mock_db.execute.assert_not_awaited()  # no DB query needed
    mock_redis.sadd.assert_not_awaited()


# ---------------------------------------------------------------------------
# Cold start — cache empty
# ---------------------------------------------------------------------------


async def test_cold_start_populates_cache_and_returns_true(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """On cold start, symbols are loaded from DB and written to Redis."""
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 0  # cache is empty
    mock_db.execute.return_value = _make_scalars_result(["BTCUSDT", "ETHUSDT", "BNBUSDT"])

    result = await is_valid_symbol_cached("BTCUSDT", mock_redis, mock_db)

    assert result is True
    mock_redis.sadd.assert_awaited_once()
    sadd_args = mock_redis.sadd.await_args  # positional: (key, *members)
    assert sadd_args.args[0] == _CACHE_KEY
    assert "BTCUSDT" in sadd_args.args
    assert "ETHUSDT" in sadd_args.args


async def test_cold_start_sets_correct_ttl(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """EXPIRE is called with _CACHE_TTL_SECONDS after populating the set."""
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 0
    mock_db.execute.return_value = _make_scalars_result(["BTCUSDT"])

    await is_valid_symbol_cached("BTCUSDT", mock_redis, mock_db)

    mock_redis.expire.assert_awaited_once_with(_CACHE_KEY, _CACHE_TTL_SECONDS)
    assert _CACHE_TTL_SECONDS == 300


async def test_cold_start_unknown_symbol_returns_false(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """After DB population, a symbol that is not in trading_pairs returns False."""
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 0
    mock_db.execute.return_value = _make_scalars_result(["BTCUSDT", "ETHUSDT"])

    result = await is_valid_symbol_cached("XYZUSDT", mock_redis, mock_db)

    assert result is False
    mock_redis.sadd.assert_awaited_once()  # still populated


async def test_cold_start_empty_db_returns_false(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """When trading_pairs is empty, return False without writing to Redis."""
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 0
    mock_db.execute.return_value = _make_scalars_result([])  # empty table

    result = await is_valid_symbol_cached("BTCUSDT", mock_redis, mock_db)

    assert result is False
    mock_redis.sadd.assert_not_awaited()
    mock_redis.expire.assert_not_awaited()


# ---------------------------------------------------------------------------
# Redis error fallback
# ---------------------------------------------------------------------------


async def test_redis_error_on_sismember_falls_back_to_db_found(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """On RedisError, fall back to single-row DB query and return True if found."""
    mock_redis.sismember.side_effect = RedisError("connection refused")
    mock_db.execute.return_value = _make_scalar_one_or_none_result("BTCUSDT")

    result = await is_valid_symbol_cached("BTCUSDT", mock_redis, mock_db)

    assert result is True
    mock_db.execute.assert_awaited_once()


async def test_redis_error_on_sismember_falls_back_to_db_not_found(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """On RedisError, fall back to single-row DB query and return False if not found."""
    mock_redis.sismember.side_effect = RedisError("timeout")
    mock_db.execute.return_value = _make_scalar_one_or_none_result(None)

    result = await is_valid_symbol_cached("XYZUSDT", mock_redis, mock_db)

    assert result is False
    mock_db.execute.assert_awaited_once()


async def test_redis_error_on_scard_falls_back_to_db(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """RedisError raised during scard also triggers DB fallback."""
    mock_redis.sismember.return_value = False
    mock_redis.scard.side_effect = RedisError("redis down")
    mock_db.execute.return_value = _make_scalar_one_or_none_result("ETHUSDT")

    result = await is_valid_symbol_cached("ETHUSDT", mock_redis, mock_db)

    assert result is True
    mock_db.execute.assert_awaited_once()


async def test_redis_error_on_sadd_falls_back_to_db(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """RedisError during the SADD populate step falls back to DB query."""
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 0
    # First DB call (load all symbols) and second DB call (single-row fallback)
    mock_db.execute.side_effect = [
        _make_scalars_result(["BTCUSDT"]),  # _load_symbols_from_db
    ]
    mock_redis.sadd.side_effect = RedisError("write error")
    # After sadd fails, _check_symbol_db is called
    mock_db.execute.side_effect = [
        _make_scalars_result(["BTCUSDT"]),
        _make_scalar_one_or_none_result("BTCUSDT"),
    ]

    result = await is_valid_symbol_cached("BTCUSDT", mock_redis, mock_db)

    assert result is True


# ---------------------------------------------------------------------------
# Cache key and TTL constants
# ---------------------------------------------------------------------------


def test_cache_key_value() -> None:
    """The Redis key string is stable and predictable."""
    assert _CACHE_KEY == "valid_symbols"


def test_cache_ttl_is_five_minutes() -> None:
    """TTL is exactly 300 seconds (5 minutes)."""
    assert _CACHE_TTL_SECONDS == 300


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


async def test_load_symbols_from_db_returns_list(mock_db: AsyncMock) -> None:
    """_load_symbols_from_db returns a list of symbol strings."""
    mock_db.execute.return_value = _make_scalars_result(["BTCUSDT", "ETHUSDT"])

    result = await _load_symbols_from_db(mock_db)

    assert result == ["BTCUSDT", "ETHUSDT"]
    assert isinstance(result, list)


async def test_load_symbols_from_db_empty(mock_db: AsyncMock) -> None:
    """_load_symbols_from_db handles an empty table correctly."""
    mock_db.execute.return_value = _make_scalars_result([])

    result = await _load_symbols_from_db(mock_db)

    assert result == []


async def test_check_symbol_db_found(mock_db: AsyncMock) -> None:
    """_check_symbol_db returns True when the symbol exists."""
    mock_db.execute.return_value = _make_scalar_one_or_none_result("BTCUSDT")

    result = await _check_symbol_db("BTCUSDT", mock_db)

    assert result is True


async def test_check_symbol_db_not_found(mock_db: AsyncMock) -> None:
    """_check_symbol_db returns False when the symbol does not exist."""
    mock_db.execute.return_value = _make_scalar_one_or_none_result(None)

    result = await _check_symbol_db("XYZUSDT", mock_db)

    assert result is False


# ---------------------------------------------------------------------------
# DB query count assertions
# ---------------------------------------------------------------------------


async def test_cache_hit_issues_zero_db_queries(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """A cache hit must not touch the database at all."""
    mock_redis.sismember.return_value = True

    await is_valid_symbol_cached("BTCUSDT", mock_redis, mock_db)

    mock_db.execute.assert_not_awaited()


async def test_cache_populated_miss_issues_zero_db_queries(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """When the set is populated and symbol is absent, no DB query is issued."""
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 600

    await is_valid_symbol_cached("XYZUSDT", mock_redis, mock_db)

    mock_db.execute.assert_not_awaited()


async def test_cold_start_issues_exactly_one_db_query(mock_redis: AsyncMock, mock_db: AsyncMock) -> None:
    """Cold start issues exactly one DB query to load the full symbol list."""
    mock_redis.sismember.return_value = False
    mock_redis.scard.return_value = 0
    mock_db.execute.return_value = _make_scalars_result(["BTCUSDT", "ETHUSDT"])

    await is_valid_symbol_cached("BTCUSDT", mock_redis, mock_db)

    assert mock_db.execute.await_count == 1
