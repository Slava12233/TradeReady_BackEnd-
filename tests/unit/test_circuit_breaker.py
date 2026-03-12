"""Unit tests for src/risk/circuit_breaker.py — daily PnL circuit breaker."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.risk.circuit_breaker import CircuitBreaker
from src.utils.exceptions import CacheError


def _make_redis(*, hget_value=None, scan_keys=None):
    """Return a mock Redis client with pipeline support."""
    redis = AsyncMock()
    redis.hget = AsyncMock(return_value=hget_value)
    redis.delete = AsyncMock()

    # Pipeline mock
    pipe = MagicMock()
    pipe.hincrbyfloat = MagicMock()
    pipe.hset = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(return_value=["0", True])
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=False)
    redis.pipeline = MagicMock(return_value=pipe)
    redis._pipe = pipe  # expose for test assertions

    # SCAN mock
    if scan_keys is None:
        scan_keys = []
    redis.scan = AsyncMock(return_value=(0, scan_keys))

    return redis


# ---------------------------------------------------------------------------
# is_tripped
# ---------------------------------------------------------------------------


class TestIsTripped:
    async def test_returns_false_when_no_key(self):
        redis = _make_redis(hget_value=None)
        cb = CircuitBreaker(redis=redis)
        assert await cb.is_tripped(uuid4()) is False

    async def test_returns_true_when_tripped(self):
        redis = _make_redis(hget_value=b"1")
        cb = CircuitBreaker(redis=redis)
        assert await cb.is_tripped(uuid4()) is True

    async def test_returns_false_when_zero(self):
        redis = _make_redis(hget_value=b"0")
        cb = CircuitBreaker(redis=redis)
        assert await cb.is_tripped(uuid4()) is False

    async def test_redis_error_raises_cache_error(self):
        redis = _make_redis()
        redis.hget = AsyncMock(side_effect=ConnectionError("down"))
        cb = CircuitBreaker(redis=redis)
        with pytest.raises(CacheError):
            await cb.is_tripped(uuid4())


# ---------------------------------------------------------------------------
# record_trade_pnl
# ---------------------------------------------------------------------------


class TestRecordTradePnl:
    async def test_positive_pnl_does_not_trip(self):
        redis = _make_redis()
        redis._pipe.execute = AsyncMock(return_value=["500.00", True])
        cb = CircuitBreaker(redis=redis)
        aid = uuid4()

        await cb.record_trade_pnl(
            aid,
            Decimal("500"),
            starting_balance=Decimal("10000"),
            daily_loss_limit_pct=Decimal("20"),
        )

        # Pipeline was used but hset for tripping should NOT have been called
        redis.hget.assert_not_called()  # is_tripped not called internally

    async def test_small_loss_does_not_trip(self):
        redis = _make_redis()
        # Daily PnL = -100, threshold = 10000 * 20 / 100 = 2000
        redis._pipe.execute = AsyncMock(return_value=["-100.00", True])
        cb = CircuitBreaker(redis=redis)

        await cb.record_trade_pnl(
            uuid4(),
            Decimal("-100"),
            starting_balance=Decimal("10000"),
            daily_loss_limit_pct=Decimal("20"),
        )

        # Should NOT have called _trip (no second pipeline call for hset tripped)
        assert redis.pipeline.call_count == 1  # only the record pipeline

    async def test_exceeding_threshold_trips(self):
        redis = _make_redis()
        # Daily PnL = -2500, threshold = 10000 * 20 / 100 = 2000
        redis._pipe.execute = AsyncMock(return_value=["-2500.00", True])
        cb = CircuitBreaker(redis=redis)

        await cb.record_trade_pnl(
            uuid4(),
            Decimal("-2500"),
            starting_balance=Decimal("10000"),
            daily_loss_limit_pct=Decimal("20"),
        )

        # A second pipeline call should have been made to set tripped=1
        assert redis.pipeline.call_count == 2

    async def test_uses_pipeline(self):
        redis = _make_redis()
        redis._pipe.execute = AsyncMock(return_value=["0", True])
        cb = CircuitBreaker(redis=redis)

        await cb.record_trade_pnl(
            uuid4(),
            Decimal("10"),
            starting_balance=Decimal("10000"),
            daily_loss_limit_pct=Decimal("20"),
        )

        redis._pipe.hincrbyfloat.assert_called_once()
        redis._pipe.expire.assert_called_once()


# ---------------------------------------------------------------------------
# get_daily_pnl
# ---------------------------------------------------------------------------


class TestGetDailyPnl:
    async def test_returns_zero_when_no_key(self):
        redis = _make_redis(hget_value=None)
        cb = CircuitBreaker(redis=redis)
        assert await cb.get_daily_pnl(uuid4()) == Decimal("0")

    async def test_returns_value(self):
        redis = _make_redis(hget_value="-350.50000000")
        cb = CircuitBreaker(redis=redis)
        result = await cb.get_daily_pnl(uuid4())
        assert result == Decimal("-350.50000000")


# ---------------------------------------------------------------------------
# reset_all
# ---------------------------------------------------------------------------


class TestResetAll:
    async def test_deletes_matching_keys(self):
        keys = [b"circuit_breaker:abc", b"circuit_breaker:def"]
        redis = _make_redis(scan_keys=keys)
        cb = CircuitBreaker(redis=redis)

        await cb.reset_all()

        redis.delete.assert_called_once_with(*keys)

    async def test_no_keys(self):
        redis = _make_redis(scan_keys=[])
        cb = CircuitBreaker(redis=redis)

        await cb.reset_all()

        redis.delete.assert_not_called()
