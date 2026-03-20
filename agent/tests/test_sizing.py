"""Tests for agent/strategies/risk/sizing.py — DynamicSizer, SizerConfig."""

from __future__ import annotations

from decimal import Decimal

from agent.strategies.risk.sizing import DynamicSizer, SizerConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sizer(
    max_single_position: str = "0.10",
    min_single_position: str = "0.01",
) -> DynamicSizer:
    """Return a DynamicSizer with explicit bounds for deterministic tests."""
    cfg = SizerConfig(
        max_single_position=Decimal(max_single_position),
        min_single_position=Decimal(min_single_position),
    )
    return DynamicSizer(config=cfg)


# ---------------------------------------------------------------------------
# SizerConfig defaults
# ---------------------------------------------------------------------------


class TestSizerConfigDefaults:
    """SizerConfig ships with sensible conservative defaults."""

    def test_max_single_position_default(self) -> None:
        """Default max single position is 10 %."""
        cfg = SizerConfig()
        assert cfg.max_single_position == Decimal("0.10")

    def test_min_single_position_default(self) -> None:
        """Default min single position is 1 %."""
        cfg = SizerConfig()
        assert cfg.min_single_position == Decimal("0.01")

    def test_custom_bounds(self) -> None:
        """Custom bounds are stored correctly."""
        cfg = SizerConfig(max_single_position=Decimal("0.15"), min_single_position=Decimal("0.02"))
        assert cfg.max_single_position == Decimal("0.15")
        assert cfg.min_single_position == Decimal("0.02")


# ---------------------------------------------------------------------------
# Volatility adjustment
# ---------------------------------------------------------------------------


class TestVolatilityAdjustment:
    """Sizes shrink when atr > avg_atr and grow when atr < avg_atr."""

    def test_high_volatility_reduces_size(self) -> None:
        """atr=200 is twice avg_atr=100 → size halved (before clamping)."""
        sizer = _make_sizer(max_single_position="0.20")
        result = sizer.calculate_size(
            base_size_pct=0.10,
            atr=200,
            avg_atr=100,
            drawdown_pct=0.0,
        )
        # vol_multiplier = 100/200 = 0.5 → 0.10 * 0.5 = 0.05 (no drawdown adjustment)
        assert abs(result - 0.05) < 0.001

    def test_low_volatility_increases_size(self) -> None:
        """atr=50 is half avg_atr=100 → size doubled, clamped to max."""
        sizer = _make_sizer(max_single_position="0.20")
        result = sizer.calculate_size(
            base_size_pct=0.05,
            atr=50,
            avg_atr=100,
            drawdown_pct=0.0,
        )
        # vol_multiplier = 100/50 = 2.0 → 0.05 * 2.0 = 0.10 (within 20 % max)
        assert abs(result - 0.10) < 0.001

    def test_equal_atr_gives_neutral_adjustment(self) -> None:
        """atr == avg_atr → vol_multiplier is 1.0 (no change to base size)."""
        sizer = _make_sizer()
        result = sizer.calculate_size(
            base_size_pct=0.08,
            atr=100,
            avg_atr=100,
            drawdown_pct=0.0,
        )
        # 0.08 * 1.0 = 0.08 (no drawdown)
        assert abs(result - 0.08) < 0.001

    def test_high_volatility_cannot_push_below_minimum(self) -> None:
        """Extreme volatility (atr 100× avg) is clamped to min_single_position."""
        sizer = _make_sizer(min_single_position="0.01")
        result = sizer.calculate_size(
            base_size_pct=0.10,
            atr=10000,
            avg_atr=100,
            drawdown_pct=0.0,
        )
        # Unclamped: 0.10 * (100/10000) = 0.001 — below minimum
        assert result >= 0.01

    def test_low_volatility_capped_at_max_single_position(self) -> None:
        """Very low atr → size is clamped to max_single_position."""
        sizer = _make_sizer(max_single_position="0.10")
        result = sizer.calculate_size(
            base_size_pct=0.10,
            atr=1,        # atr near zero → multiplier huge
            avg_atr=100,
            drawdown_pct=0.0,
        )
        assert result <= 0.10 + 0.0001


# ---------------------------------------------------------------------------
# Drawdown adjustment
# ---------------------------------------------------------------------------


class TestDrawdownAdjustment:
    """Drawdown linearly reduces size; high drawdown floors at minimum."""

    def test_zero_drawdown_no_adjustment(self) -> None:
        """0 % drawdown → drawdown multiplier is 1.0 (no change)."""
        sizer = _make_sizer()
        result = sizer.calculate_size(
            base_size_pct=0.08,
            atr=100,
            avg_atr=100,
            drawdown_pct=0.0,
        )
        assert abs(result - 0.08) < 0.001

    def test_25_percent_drawdown_halves_size(self) -> None:
        """25 % drawdown → multiplier = 1 - 0.25*2 = 0.5 (size halved)."""
        sizer = _make_sizer(max_single_position="0.20")
        result = sizer.calculate_size(
            base_size_pct=0.10,
            atr=100,
            avg_atr=100,
            drawdown_pct=0.25,
        )
        # 0.10 * 0.5 = 0.05
        assert abs(result - 0.05) < 0.001

    def test_high_drawdown_floors_at_minimum(self) -> None:
        """50 % drawdown → multiplier 0.0 before clamp → clamped to min."""
        sizer = _make_sizer(min_single_position="0.01")
        result = sizer.calculate_size(
            base_size_pct=0.10,
            atr=100,
            avg_atr=100,
            drawdown_pct=0.50,
        )
        assert result >= 0.01

    def test_drawdown_above_50_still_clamped(self) -> None:
        """Drawdown > 50 % would give negative multiplier; result is still >= min."""
        sizer = _make_sizer(min_single_position="0.01")
        result = sizer.calculate_size(
            base_size_pct=0.10,
            atr=100,
            avg_atr=100,
            drawdown_pct=0.75,
        )
        assert result >= 0.01

    def test_negative_drawdown_treated_as_zero(self) -> None:
        """Negative drawdown_pct is treated as 0 (no adjustment applied)."""
        sizer = _make_sizer()
        result_negative = sizer.calculate_size(0.08, atr=100, avg_atr=100, drawdown_pct=-0.05)
        result_zero = sizer.calculate_size(0.08, atr=100, avg_atr=100, drawdown_pct=0.0)
        assert abs(result_negative - result_zero) < 0.0001

    def test_small_drawdown_proportional_reduction(self) -> None:
        """10 % drawdown → multiplier = 1 - 0.10*2 = 0.8 → size × 0.8."""
        sizer = _make_sizer(max_single_position="0.20")
        result = sizer.calculate_size(
            base_size_pct=0.10,
            atr=100,
            avg_atr=100,
            drawdown_pct=0.10,
        )
        # 0.10 * 0.8 = 0.08
        assert abs(result - 0.08) < 0.001


# ---------------------------------------------------------------------------
# Combined volatility + drawdown
# ---------------------------------------------------------------------------


class TestCombinedAdjustments:
    """Volatility and drawdown multipliers are both applied in sequence."""

    def test_high_vol_and_high_drawdown_both_reduce(self) -> None:
        """atr=200 (×0.5) and 10 % drawdown (×0.8): 0.10 * 0.5 * 0.8 = 0.04."""
        sizer = _make_sizer(max_single_position="0.20")
        result = sizer.calculate_size(
            base_size_pct=0.10,
            atr=200,
            avg_atr=100,
            drawdown_pct=0.10,
        )
        # vol: 0.10 * 0.5 = 0.05; drawdown: 0.05 * 0.8 = 0.04
        assert abs(result - 0.04) < 0.001

    def test_low_vol_partially_offsets_drawdown(self) -> None:
        """atr=50 (×2.0) and 25 % drawdown (×0.5): 0.05 * 2.0 * 0.5 = 0.05."""
        sizer = _make_sizer(max_single_position="0.20")
        result = sizer.calculate_size(
            base_size_pct=0.05,
            atr=50,
            avg_atr=100,
            drawdown_pct=0.25,
        )
        # vol: 0.05 * 2.0 = 0.10; drawdown: 0.10 * 0.5 = 0.05
        assert abs(result - 0.05) < 0.001


# ---------------------------------------------------------------------------
# Bounds enforcement
# ---------------------------------------------------------------------------


class TestBoundsEnforcement:
    """Result is always within [min_single_position, max_single_position]."""

    def test_result_never_below_minimum(self) -> None:
        """No combination of inputs produces a result below min_single_position."""
        sizer = _make_sizer(min_single_position="0.01", max_single_position="0.10")
        test_cases = [
            (0.01, 10000, 1, 0.99),
            (0.001, 200, 100, 0.50),
            (0.10, 100, 1, 0.90),
        ]
        for base, atr, avg_atr, drawdown in test_cases:
            result = sizer.calculate_size(base, atr=atr, avg_atr=avg_atr, drawdown_pct=drawdown)
            assert result >= 0.01, f"Result {result} below min for inputs ({base}, {atr}, {avg_atr}, {drawdown})"

    def test_result_never_above_maximum(self) -> None:
        """No combination of inputs produces a result above max_single_position."""
        sizer = _make_sizer(min_single_position="0.01", max_single_position="0.10")
        test_cases = [
            (0.10, 1, 10000, 0.0),
            (0.50, 50, 100, 0.0),
            (1.0, 100, 200, 0.0),
        ]
        for base, atr, avg_atr, drawdown in test_cases:
            result = sizer.calculate_size(base, atr=atr, avg_atr=avg_atr, drawdown_pct=drawdown)
            msg = f"Result {result} above max for inputs ({base}, {atr}, {avg_atr}, {drawdown})"
            assert result <= 0.10 + 0.0001, msg

    def test_result_quantised_to_four_decimal_places(self) -> None:
        """Output is quantised to 4 decimal places (0.0001 resolution)."""
        sizer = _make_sizer()
        result = sizer.calculate_size(
            base_size_pct=0.07,
            atr=133,
            avg_atr=100,
            drawdown_pct=0.03,
        )
        # Check no more than 4 decimal places
        result_str = f"{result:.10f}".rstrip("0")
        decimal_part = result_str.split(".")[1] if "." in result_str else ""
        assert len(decimal_part) <= 4

    def test_result_is_float(self) -> None:
        """calculate_size always returns a Python float."""
        sizer = _make_sizer()
        result = sizer.calculate_size(0.05, atr=100, avg_atr=100, drawdown_pct=0.0)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# Zero / negative ATR safety
# ---------------------------------------------------------------------------


class TestAtrEdgeCases:
    """Zero or negative ATR values are handled safely without errors."""

    def test_zero_atr_skips_volatility_adjustment(self) -> None:
        """atr=0 → volatility step is skipped; drawdown step still applies."""
        sizer = _make_sizer()
        result = sizer.calculate_size(
            base_size_pct=0.08,
            atr=0,
            avg_atr=100,
            drawdown_pct=0.0,
        )
        # No vol adjustment (atr=0 is non-positive); drawdown=0 → result = 0.08
        assert abs(result - 0.08) < 0.001

    def test_zero_avg_atr_skips_volatility_adjustment(self) -> None:
        """avg_atr=0 → volatility step is skipped."""
        sizer = _make_sizer()
        result = sizer.calculate_size(
            base_size_pct=0.08,
            atr=100,
            avg_atr=0,
            drawdown_pct=0.0,
        )
        assert abs(result - 0.08) < 0.001

    def test_negative_atr_skips_volatility_adjustment(self) -> None:
        """Negative atr → volatility step skipped; no exception raised."""
        sizer = _make_sizer()
        result = sizer.calculate_size(
            base_size_pct=0.08,
            atr=-50,
            avg_atr=100,
            drawdown_pct=0.0,
        )
        assert abs(result - 0.08) < 0.001

    def test_both_atr_zero_no_crash(self) -> None:
        """Both atr and avg_atr = 0 → no division by zero; safe result returned."""
        sizer = _make_sizer()
        result = sizer.calculate_size(0.05, atr=0, avg_atr=0, drawdown_pct=0.0)
        assert 0.01 <= result <= 0.10

    def test_decimal_atr_inputs_accepted(self) -> None:
        """ATR values may be passed as Decimal objects."""
        sizer = _make_sizer(max_single_position="0.20")
        result = sizer.calculate_size(
            base_size_pct=Decimal("0.10"),
            atr=Decimal("200"),
            avg_atr=Decimal("100"),
            drawdown_pct=Decimal("0"),
        )
        # Same logic as float: 0.10 * 0.5 = 0.05
        assert abs(result - 0.05) < 0.001

    def test_default_sizer_no_config_argument(self) -> None:
        """DynamicSizer() with no config uses SizerConfig defaults."""
        sizer = DynamicSizer()
        result = sizer.calculate_size(0.05, atr=100, avg_atr=100, drawdown_pct=0.0)
        # Default max is 0.10 and min is 0.01; 0.05 should be returned unchanged
        assert abs(result - 0.05) < 0.001
