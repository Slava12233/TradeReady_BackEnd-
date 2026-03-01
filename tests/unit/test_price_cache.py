"""Unit tests for :class:`~src.cache.price_cache.PriceCache`.

Test coverage:
- set_price writes to ``prices`` and ``prices:meta`` hashes.
- get_price returns Decimal or None for missing symbol.
- get_all_prices returns full mapping as Decimals.
- update_ticker initialises fields on first tick.
- update_ticker updates high/low/close/volume/change_pct on subsequent ticks.
- get_ticker returns TickerData or None.
- get_stale_pairs returns symbols whose last update is older than threshold.
- Corrupt timestamp in prices:meta is treated as stale.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.cache.price_cache import PriceCache, Tick, TickerData
from tests.conftest import make_tick


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cache(redis: AsyncMock) -> PriceCache:
    return PriceCache(redis)


# ---------------------------------------------------------------------------
# set_price
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_price_writes_price_and_meta(mock_redis: AsyncMock) -> None:
    """set_price should HSET both 'prices' and 'prices:meta' in a pipeline."""
    cache = _cache(mock_redis)
    ts = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)

    await cache.set_price("BTCUSDT", Decimal("64521.30"), ts)

    pipe = mock_redis.pipeline.return_value.__aenter__.return_value
    pipe.hset.assert_any_call("prices", "BTCUSDT", "64521.30")
    pipe.hset.assert_any_call("prices:meta", "BTCUSDT", ts.isoformat())
    pipe.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_price_converts_timestamp_to_utc(mock_redis: AsyncMock) -> None:
    """Timestamp stored in prices:meta must be UTC ISO-8601."""
    cache = _cache(mock_redis)
    ts = datetime(2024, 6, 15, 10, 30, 0, tzinfo=UTC)

    await cache.set_price("ETHUSDT", Decimal("3400.00"), ts)

    pipe = mock_redis.pipeline.return_value.__aenter__.return_value
    # Verify the meta entry contains a valid ISO timestamp
    calls = [str(c) for c in pipe.hset.call_args_list]
    assert any("prices:meta" in c for c in calls)


# ---------------------------------------------------------------------------
# get_price
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_price_returns_decimal(mock_redis: AsyncMock) -> None:
    """get_price should parse the Redis string and return a Decimal."""
    mock_redis.hget.return_value = "64521.30"
    cache = _cache(mock_redis)

    price = await cache.get_price("BTCUSDT")

    assert price == Decimal("64521.30")
    mock_redis.hget.assert_awaited_once_with("prices", "BTCUSDT")


@pytest.mark.asyncio
async def test_get_price_returns_none_when_missing(mock_redis: AsyncMock) -> None:
    """get_price should return None when the symbol is not in Redis."""
    mock_redis.hget.return_value = None
    cache = _cache(mock_redis)

    price = await cache.get_price("UNKNOWNUSDT")

    assert price is None


@pytest.mark.asyncio
async def test_get_price_precision_preserved(mock_redis: AsyncMock) -> None:
    """Decimal precision must survive a round-trip through the string cache."""
    mock_redis.hget.return_value = "0.00012345"
    cache = _cache(mock_redis)

    price = await cache.get_price("SHIBUSDT")

    assert price == Decimal("0.00012345")


# ---------------------------------------------------------------------------
# get_all_prices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_all_prices_returns_mapping(mock_redis: AsyncMock) -> None:
    """get_all_prices should deserialise all fields into a Decimal mapping."""
    mock_redis.hgetall.return_value = {
        "BTCUSDT": "64521.30",
        "ETHUSDT": "3400.00",
        "BNBUSDT": "400.50",
    }
    cache = _cache(mock_redis)

    prices = await cache.get_all_prices()

    assert prices == {
        "BTCUSDT": Decimal("64521.30"),
        "ETHUSDT": Decimal("3400.00"),
        "BNBUSDT": Decimal("400.50"),
    }


@pytest.mark.asyncio
async def test_get_all_prices_empty(mock_redis: AsyncMock) -> None:
    """get_all_prices should return an empty dict when Redis has no entries."""
    mock_redis.hgetall.return_value = {}
    cache = _cache(mock_redis)

    prices = await cache.get_all_prices()

    assert prices == {}


# ---------------------------------------------------------------------------
# update_ticker — first tick
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_ticker_first_tick_initialises_all_fields(mock_redis: AsyncMock) -> None:
    """First tick for a symbol should set open=high=low=close=price, volume=qty, change_pct=0."""
    mock_redis.hgetall.return_value = {}  # no existing ticker
    cache = _cache(mock_redis)
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    tick = make_tick("BTCUSDT", "64000.00", "0.01", ts, False, 1)

    await cache.update_ticker(tick)

    mock_redis.hset.assert_awaited_once()
    call_args = mock_redis.hset.call_args
    mapping = call_args.kwargs.get("mapping") or call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs["mapping"]
    assert mapping["open"] == "64000.00"
    assert mapping["high"] == "64000.00"
    assert mapping["low"] == "64000.00"
    assert mapping["close"] == "64000.00"
    assert mapping["volume"] == "0.01"
    assert mapping["change_pct"] == "0"


# ---------------------------------------------------------------------------
# update_ticker — subsequent ticks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_ticker_updates_high(mock_redis: AsyncMock) -> None:
    """Subsequent tick with a higher price should raise the 'high' field."""
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    mock_redis.hgetall.return_value = {
        "open": "64000.00",
        "high": "64000.00",
        "low": "64000.00",
        "close": "64000.00",
        "volume": "0.10",
        "change_pct": "0",
        "last_update": ts.isoformat(),
    }
    cache = _cache(mock_redis)
    tick = make_tick("BTCUSDT", "65000.00", "0.05", ts, False, 2)

    await cache.update_ticker(tick)

    call_args = mock_redis.hset.call_args
    mapping = call_args.kwargs.get("mapping") or call_args.kwargs["mapping"]
    assert mapping["high"] == "65000.00"
    assert mapping["close"] == "65000.00"


@pytest.mark.asyncio
async def test_update_ticker_updates_low(mock_redis: AsyncMock) -> None:
    """Subsequent tick with a lower price should drop the 'low' field."""
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    mock_redis.hgetall.return_value = {
        "open": "64000.00",
        "high": "64000.00",
        "low": "64000.00",
        "close": "64000.00",
        "volume": "0.10",
        "change_pct": "0",
        "last_update": ts.isoformat(),
    }
    cache = _cache(mock_redis)
    tick = make_tick("BTCUSDT", "63000.00", "0.05", ts, True, 3)

    await cache.update_ticker(tick)

    call_args = mock_redis.hset.call_args
    mapping = call_args.kwargs.get("mapping") or call_args.kwargs["mapping"]
    assert mapping["low"] == "63000.00"


@pytest.mark.asyncio
async def test_update_ticker_accumulates_volume(mock_redis: AsyncMock) -> None:
    """Volume should accumulate across subsequent ticks."""
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    mock_redis.hgetall.return_value = {
        "open": "64000.00",
        "high": "64000.00",
        "low": "64000.00",
        "close": "64000.00",
        "volume": "1.00",
        "change_pct": "0",
        "last_update": ts.isoformat(),
    }
    cache = _cache(mock_redis)
    tick = make_tick("BTCUSDT", "64500.00", "0.50", ts, False, 4)

    await cache.update_ticker(tick)

    call_args = mock_redis.hset.call_args
    mapping = call_args.kwargs.get("mapping") or call_args.kwargs["mapping"]
    assert Decimal(mapping["volume"]) == Decimal("1.50")


@pytest.mark.asyncio
async def test_update_ticker_calculates_change_pct(mock_redis: AsyncMock) -> None:
    """change_pct must reflect (close - open) / open * 100."""
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    mock_redis.hgetall.return_value = {
        "open": "100.00",
        "high": "100.00",
        "low": "100.00",
        "close": "100.00",
        "volume": "1.00",
        "change_pct": "0",
        "last_update": ts.isoformat(),
    }
    cache = _cache(mock_redis)
    tick = make_tick("TESTUSDT", "110.00", "0.10", ts, False, 5)

    await cache.update_ticker(tick)

    call_args = mock_redis.hset.call_args
    mapping = call_args.kwargs.get("mapping") or call_args.kwargs["mapping"]
    assert Decimal(mapping["change_pct"]) == Decimal("10.00")


@pytest.mark.asyncio
async def test_update_ticker_does_not_overwrite_open(mock_redis: AsyncMock) -> None:
    """The 'open' field must not appear in the update mapping (preserved from init)."""
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    mock_redis.hgetall.return_value = {
        "open": "64000.00",
        "high": "64000.00",
        "low": "64000.00",
        "close": "64000.00",
        "volume": "1.00",
        "change_pct": "0",
        "last_update": ts.isoformat(),
    }
    cache = _cache(mock_redis)
    tick = make_tick("BTCUSDT", "65000.00", "0.10", ts, False, 6)

    await cache.update_ticker(tick)

    call_args = mock_redis.hset.call_args
    mapping = call_args.kwargs.get("mapping") or call_args.kwargs["mapping"]
    assert "open" not in mapping


# ---------------------------------------------------------------------------
# get_ticker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_ticker_returns_ticker_data(mock_redis: AsyncMock) -> None:
    """get_ticker should deserialise Redis hash into a TickerData dataclass."""
    ts = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
    mock_redis.hgetall.return_value = {
        "open": "64000.00",
        "high": "65000.00",
        "low": "63000.00",
        "close": "64800.00",
        "volume": "500.00",
        "change_pct": "1.25",
        "last_update": ts.isoformat(),
    }
    cache = _cache(mock_redis)

    ticker = await cache.get_ticker("BTCUSDT")

    assert ticker is not None
    assert isinstance(ticker, TickerData)
    assert ticker.symbol == "BTCUSDT"
    assert ticker.open == Decimal("64000.00")
    assert ticker.high == Decimal("65000.00")
    assert ticker.low == Decimal("63000.00")
    assert ticker.close == Decimal("64800.00")
    assert ticker.volume == Decimal("500.00")
    assert ticker.change_pct == Decimal("1.25")


@pytest.mark.asyncio
async def test_get_ticker_returns_none_when_missing(mock_redis: AsyncMock) -> None:
    """get_ticker should return None when no ticker exists for the symbol."""
    mock_redis.hgetall.return_value = {}
    cache = _cache(mock_redis)

    ticker = await cache.get_ticker("UNKNOWNUSDT")

    assert ticker is None


# ---------------------------------------------------------------------------
# get_stale_pairs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_stale_pairs_returns_old_symbols(mock_redis: AsyncMock) -> None:
    """Symbols whose timestamp is older than threshold_seconds are stale."""
    now = datetime.now(UTC)
    old_ts = (now - timedelta(seconds=120)).isoformat()
    fresh_ts = (now - timedelta(seconds=10)).isoformat()
    mock_redis.hgetall.return_value = {
        "BTCUSDT": old_ts,
        "ETHUSDT": fresh_ts,
        "ADAUSDT": old_ts,
    }
    cache = _cache(mock_redis)

    stale = await cache.get_stale_pairs(threshold_seconds=60)

    assert "BTCUSDT" in stale
    assert "ADAUSDT" in stale
    assert "ETHUSDT" not in stale


@pytest.mark.asyncio
async def test_get_stale_pairs_returns_empty_when_all_fresh(mock_redis: AsyncMock) -> None:
    """No stale pairs should be returned when all timestamps are recent."""
    now = datetime.now(UTC)
    fresh_ts = (now - timedelta(seconds=5)).isoformat()
    mock_redis.hgetall.return_value = {
        "BTCUSDT": fresh_ts,
        "ETHUSDT": fresh_ts,
    }
    cache = _cache(mock_redis)

    stale = await cache.get_stale_pairs(threshold_seconds=60)

    assert stale == []


@pytest.mark.asyncio
async def test_get_stale_pairs_empty_cache(mock_redis: AsyncMock) -> None:
    """Empty prices:meta should return an empty list."""
    mock_redis.hgetall.return_value = {}
    cache = _cache(mock_redis)

    stale = await cache.get_stale_pairs()

    assert stale == []


@pytest.mark.asyncio
async def test_get_stale_pairs_corrupt_timestamp_treated_as_stale(mock_redis: AsyncMock) -> None:
    """A corrupt timestamp in prices:meta must be treated as stale."""
    mock_redis.hgetall.return_value = {
        "BTCUSDT": "not-a-valid-timestamp",
    }
    cache = _cache(mock_redis)

    stale = await cache.get_stale_pairs(threshold_seconds=60)

    assert "BTCUSDT" in stale


@pytest.mark.asyncio
async def test_get_stale_pairs_result_is_sorted(mock_redis: AsyncMock) -> None:
    """Stale pairs list must be sorted alphabetically."""
    now = datetime.now(UTC)
    old_ts = (now - timedelta(seconds=120)).isoformat()
    mock_redis.hgetall.return_value = {
        "ZETAUSDT": old_ts,
        "ADAUSDT": old_ts,
        "BTCUSDT": old_ts,
    }
    cache = _cache(mock_redis)

    stale = await cache.get_stale_pairs(threshold_seconds=60)

    assert stale == sorted(stale)


@pytest.mark.asyncio
async def test_get_stale_pairs_custom_threshold(mock_redis: AsyncMock) -> None:
    """Custom threshold_seconds should be respected."""
    now = datetime.now(UTC)
    slightly_old_ts = (now - timedelta(seconds=45)).isoformat()
    mock_redis.hgetall.return_value = {"BTCUSDT": slightly_old_ts}
    cache = _cache(mock_redis)

    # 45s old is NOT stale at threshold=60
    stale_60 = await cache.get_stale_pairs(threshold_seconds=60)
    assert "BTCUSDT" not in stale_60

    # But IS stale at threshold=30
    stale_30 = await cache.get_stale_pairs(threshold_seconds=30)
    assert "BTCUSDT" in stale_30
