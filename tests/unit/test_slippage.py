"""Unit tests for src.order_engine.slippage.SlippageCalculator.

Tests cover:
- Small / medium / large order slippage scaling
- Buy vs. sell direction (buy pushes price up, sell pushes price down)
- Fee calculation (0.1 % of order value)
- Zero-volume ticker fallback (uses _MIN_SLIPPAGE_FRACTION)
- Missing ticker fallback
- Invalid side raises ValueError
- Zero reference price raises PriceNotAvailableError
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.cache.price_cache import PriceCache
from src.order_engine.slippage import SlippageCalculator, SlippageResult
from src.utils.exceptions import PriceNotAvailableError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ticker(volume: str) -> MagicMock:
    """Return a mock TickerData with the given 24h base-asset volume."""
    ticker = MagicMock()
    ticker.volume = Decimal(volume)
    return ticker


def _make_price_cache(ticker) -> AsyncMock:
    """Return a mock PriceCache that returns *ticker* for any symbol."""
    cache = AsyncMock(spec=PriceCache)
    cache.get_ticker = AsyncMock(return_value=ticker)
    return cache


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def settings_defaults() -> dict:
    return {
        "default_slippage_factor": Decimal("0.1"),
    }


# ---------------------------------------------------------------------------
# Basic construction and result shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calculate_returns_slippage_result():
    """calculate() always returns a SlippageResult dataclass."""
    ticker = _make_ticker("1000")
    cache = _make_price_cache(ticker)
    calc = SlippageCalculator(cache, default_factor=Decimal("0.1"))

    result = await calc.calculate("BTCUSDT", "buy", Decimal("0.01"), Decimal("60000"))

    assert isinstance(result, SlippageResult)
    assert result.execution_price > Decimal("0")
    assert result.slippage_amount >= Decimal("0")
    assert result.slippage_pct >= Decimal("0")
    assert result.fee >= Decimal("0")


# ---------------------------------------------------------------------------
# Buy vs. sell direction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_buy_increases_execution_price():
    """Buying pushes execution_price above the reference price."""
    ticker = _make_ticker("1000")
    cache = _make_price_cache(ticker)
    calc = SlippageCalculator(cache, default_factor=Decimal("0.1"))

    ref = Decimal("60000")
    result = await calc.calculate("BTCUSDT", "buy", Decimal("1"), ref)

    assert result.execution_price > ref


@pytest.mark.asyncio
async def test_sell_decreases_execution_price():
    """Selling pushes execution_price below the reference price."""
    ticker = _make_ticker("1000")
    cache = _make_price_cache(ticker)
    calc = SlippageCalculator(cache, default_factor=Decimal("0.1"))

    ref = Decimal("60000")
    result = await calc.calculate("BTCUSDT", "sell", Decimal("1"), ref)

    assert result.execution_price < ref


# ---------------------------------------------------------------------------
# Slippage scales with order size
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_large_order_has_more_slippage_than_small_order():
    """Slippage fraction increases with order size (proportional model)."""
    # 24h volume of 10_000 BTC at $60k = $600M daily volume
    ticker = _make_ticker("10000")
    cache = _make_price_cache(ticker)
    calc = SlippageCalculator(cache, default_factor=Decimal("0.1"))

    ref = Decimal("60000")
    small = await calc.calculate("BTCUSDT", "buy", Decimal("0.001"), ref)
    large = await calc.calculate("BTCUSDT", "buy", Decimal("100"), ref)

    assert large.slippage_pct > small.slippage_pct


@pytest.mark.asyncio
async def test_small_order_slippage_is_near_minimum():
    """A tiny order should produce slippage at or near _MIN_SLIPPAGE_FRACTION (0.01 %)."""
    ticker = _make_ticker("1000000")  # very liquid pair
    cache = _make_price_cache(ticker)
    calc = SlippageCalculator(cache, default_factor=Decimal("0.1"))

    ref = Decimal("60000")
    # 0.0001 BTC ≈ $6 — negligible vs 1M BTC daily volume
    result = await calc.calculate("BTCUSDT", "buy", Decimal("0.0001"), ref)

    # slippage_pct should be very small (≤ 0.02 %)
    assert result.slippage_pct <= Decimal("0.02")


# ---------------------------------------------------------------------------
# Fee calculation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fee_is_0_1_pct_of_order_value():
    """Fee must equal 0.1 % of (quantity × reference_price)."""
    ticker = _make_ticker("10000")
    cache = _make_price_cache(ticker)
    calc = SlippageCalculator(cache, default_factor=Decimal("0.1"))

    qty = Decimal("2")
    ref = Decimal("50000")
    result = await calc.calculate("BTCUSDT", "buy", qty, ref)

    expected_fee = (qty * ref * Decimal("0.001")).quantize(Decimal("0.00000001"))
    assert result.fee == expected_fee


# ---------------------------------------------------------------------------
# Zero-volume fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_volume_uses_minimum_slippage():
    """When ticker volume is 0, falls back to minimum slippage fraction."""
    ticker = _make_ticker("0")
    cache = _make_price_cache(ticker)
    calc = SlippageCalculator(cache, default_factor=Decimal("0.1"))

    ref = Decimal("60000")
    result = await calc.calculate("BTCUSDT", "buy", Decimal("1"), ref)

    # With minimum slippage fraction (0.0001), slippage_pct = 0.01 %
    assert result.slippage_pct == Decimal("0.010000")


@pytest.mark.asyncio
async def test_missing_ticker_uses_minimum_slippage():
    """When get_ticker returns None, falls back to minimum slippage."""
    cache = AsyncMock(spec=PriceCache)
    cache.get_ticker = AsyncMock(return_value=None)
    calc = SlippageCalculator(cache, default_factor=Decimal("0.1"))

    ref = Decimal("60000")
    result = await calc.calculate("BTCUSDT", "buy", Decimal("1"), ref)

    # Minimum slippage fraction 0.01 %
    assert result.slippage_pct == Decimal("0.010000")


# ---------------------------------------------------------------------------
# Edge cases and error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_side_raises_value_error():
    """An unrecognised side raises ValueError immediately."""
    cache = AsyncMock(spec=PriceCache)
    calc = SlippageCalculator(cache)

    with pytest.raises(ValueError, match="Invalid order side"):
        await calc.calculate("BTCUSDT", "short", Decimal("1"), Decimal("60000"))


@pytest.mark.asyncio
async def test_zero_reference_price_raises():
    """Zero reference price raises PriceNotAvailableError."""
    cache = AsyncMock(spec=PriceCache)
    calc = SlippageCalculator(cache)

    with pytest.raises(PriceNotAvailableError):
        await calc.calculate("BTCUSDT", "buy", Decimal("1"), Decimal("0"))


@pytest.mark.asyncio
async def test_negative_reference_price_raises():
    """Negative reference price raises PriceNotAvailableError."""
    cache = AsyncMock(spec=PriceCache)
    calc = SlippageCalculator(cache)

    with pytest.raises(PriceNotAvailableError):
        await calc.calculate("BTCUSDT", "buy", Decimal("1"), Decimal("-100"))


@pytest.mark.asyncio
async def test_slippage_amount_equals_abs_price_diff():
    """slippage_amount == abs(execution_price - reference_price)."""
    ticker = _make_ticker("1000")
    cache = _make_price_cache(ticker)
    calc = SlippageCalculator(cache, default_factor=Decimal("0.1"))

    ref = Decimal("60000")
    result = await calc.calculate("BTCUSDT", "buy", Decimal("1"), ref)

    expected_amount = abs(result.execution_price - ref).quantize(Decimal("0.00000001"))
    assert result.slippage_amount == expected_amount


@pytest.mark.asyncio
async def test_case_insensitive_side():
    """Side is treated case-insensitively ('BUY' == 'buy')."""
    ticker = _make_ticker("1000")
    cache = _make_price_cache(ticker)
    calc = SlippageCalculator(cache, default_factor=Decimal("0.1"))

    ref = Decimal("60000")
    lower = await calc.calculate("BTCUSDT", "buy", Decimal("1"), ref)
    upper = await calc.calculate("BTCUSDT", "BUY", Decimal("1"), ref)

    assert lower.execution_price == upper.execution_price


@pytest.mark.asyncio
async def test_custom_slippage_factor():
    """A higher default_factor should produce higher slippage."""
    ticker = _make_ticker("1000")
    cache = _make_price_cache(ticker)

    low_factor = SlippageCalculator(cache, default_factor=Decimal("0.1"))
    high_factor = SlippageCalculator(cache, default_factor=Decimal("1.0"))

    ref = Decimal("60000")
    low_result = await low_factor.calculate("BTCUSDT", "buy", Decimal("5"), ref)
    high_result = await high_factor.calculate("BTCUSDT", "buy", Decimal("5"), ref)

    assert high_result.slippage_pct > low_result.slippage_pct
