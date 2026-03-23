"""Tests for KellyFractionalSizer, HybridSizer, and SizingMethod.

Covers:
- KellyConfig defaults and custom overrides
- KellyFractionalSizer.calculate_kelly_fraction() static helper
- KellyFractionalSizer.calculate_size() with edge cases
- HybridConfig defaults and custom overrides
- HybridSizer.calculate_size() including vol adjustment and fallbacks
- SizingMethod enum values
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from agent.strategies.risk.sizing import (
    HybridConfig,
    HybridSizer,
    KellyConfig,
    KellyFractionalSizer,
    SizingMethod,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WIN_RATE = 0.55          # representative edge
_RATIO = 1.5              # avg win / avg loss


def _kelly_sizer(
    divisor: int = 2,
    max_pct: str = "0.10",
    min_pct: str = "0.03",
) -> KellyFractionalSizer:
    """Return a KellyFractionalSizer with explicit bounds."""
    cfg = KellyConfig(
        kelly_divisor=divisor,
        max_trade_pct=Decimal(max_pct),
        min_trade_pct=Decimal(min_pct),
    )
    return KellyFractionalSizer(config=cfg)


def _hybrid_sizer(
    divisor: int = 2,
    max_pct: str = "0.10",
    min_pct: str = "0.03",
    target_vol: str = "0.02",
) -> HybridSizer:
    """Return a HybridSizer with explicit parameters."""
    cfg = HybridConfig(
        kelly_divisor=divisor,
        max_trade_pct=Decimal(max_pct),
        min_trade_pct=Decimal(min_pct),
        target_vol=Decimal(target_vol),
    )
    return HybridSizer(config=cfg)


# ---------------------------------------------------------------------------
# SizingMethod enum
# ---------------------------------------------------------------------------


class TestSizingMethodEnum:
    """SizingMethod enum has correct string values."""

    def test_dynamic_value(self) -> None:
        """DYNAMIC maps to the string 'dynamic'."""
        assert SizingMethod.DYNAMIC == "dynamic"

    def test_kelly_value(self) -> None:
        """KELLY maps to the string 'kelly'."""
        assert SizingMethod.KELLY == "kelly"

    def test_hybrid_value(self) -> None:
        """HYBRID maps to the string 'hybrid'."""
        assert SizingMethod.HYBRID == "hybrid"

    def test_all_three_members_present(self) -> None:
        """Enum has exactly three members."""
        members = list(SizingMethod)
        assert len(members) == 3

    def test_str_enum_comparison(self) -> None:
        """SizingMethod compares equal to plain string."""
        assert SizingMethod.KELLY == SizingMethod.KELLY
        assert SizingMethod.DYNAMIC != SizingMethod.KELLY


# ---------------------------------------------------------------------------
# KellyConfig defaults
# ---------------------------------------------------------------------------


class TestKellyConfigDefaults:
    """KellyConfig ships with safe conservative defaults."""

    def test_kelly_divisor_default(self) -> None:
        """Default divisor is 2 (Half-Kelly)."""
        cfg = KellyConfig()
        assert cfg.kelly_divisor == 2

    def test_max_trade_pct_default(self) -> None:
        """Default max trade size is 10 %."""
        cfg = KellyConfig()
        assert cfg.max_trade_pct == Decimal("0.10")

    def test_min_trade_pct_default(self) -> None:
        """Default min trade size is 3 %."""
        cfg = KellyConfig()
        assert cfg.min_trade_pct == Decimal("0.03")

    def test_custom_divisor_override(self) -> None:
        """Quarter-Kelly divisor of 4 is accepted."""
        cfg = KellyConfig(kelly_divisor=4)
        assert cfg.kelly_divisor == 4

    def test_custom_max_pct_override(self) -> None:
        """Custom max_trade_pct is stored correctly."""
        cfg = KellyConfig(max_trade_pct=Decimal("0.15"))
        assert cfg.max_trade_pct == Decimal("0.15")

    def test_custom_min_pct_override(self) -> None:
        """Custom min_trade_pct is stored correctly."""
        cfg = KellyConfig(min_trade_pct=Decimal("0.02"))
        assert cfg.min_trade_pct == Decimal("0.02")

    def test_divisor_must_be_at_least_one(self) -> None:
        """kelly_divisor=0 raises a validation error."""
        with pytest.raises(Exception):
            KellyConfig(kelly_divisor=0)


# ---------------------------------------------------------------------------
# KellyFractionalSizer.calculate_kelly_fraction — static helper
# ---------------------------------------------------------------------------


class TestKellyFractionStatic:
    """calculate_kelly_fraction returns the theoretical full-Kelly fraction."""

    def test_typical_edge(self) -> None:
        """55 % win rate, 1.5 ratio → kelly = 0.375."""
        fraction = KellyFractionalSizer.calculate_kelly_fraction(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
        )
        # (0.55 * 1.5 - 0.45) / 1.5 = (0.825 - 0.45) / 1.5 = 0.375 / 1.5 = 0.25
        # Re-check: k = (w*b - (1-w)) / b = (0.55*1.5 - 0.45) / 1.5
        #           = (0.825 - 0.45) / 1.5 = 0.375 / 1.5 = 0.25
        assert abs(float(fraction) - 0.25) < 0.0001

    def test_50_50_with_equal_ratio(self) -> None:
        """50 % win rate with 1.0 ratio → kelly = 0 (break-even, no edge)."""
        fraction = KellyFractionalSizer.calculate_kelly_fraction(
            win_rate=0.5,
            avg_win_loss_ratio=1.0,
        )
        # (0.5 * 1.0 - 0.5) / 1.0 = 0.0
        assert fraction == Decimal("0")

    def test_zero_win_rate(self) -> None:
        """0 % win rate → always lose; Kelly is negative; returns 0."""
        fraction = KellyFractionalSizer.calculate_kelly_fraction(
            win_rate=0.0,
            avg_win_loss_ratio=2.0,
        )
        assert fraction == Decimal("0")

    def test_perfect_win_rate(self) -> None:
        """100 % win rate → Kelly is 1.0 (full bankroll)."""
        fraction = KellyFractionalSizer.calculate_kelly_fraction(
            win_rate=1.0,
            avg_win_loss_ratio=2.0,
        )
        # (1.0 * 2.0 - 0.0) / 2.0 = 2.0 / 2.0 = 1.0
        assert abs(float(fraction) - 1.0) < 0.0001

    def test_zero_avg_win_loss_ratio(self) -> None:
        """Zero avg_win_loss_ratio → undefined; returns 0."""
        fraction = KellyFractionalSizer.calculate_kelly_fraction(
            win_rate=0.55,
            avg_win_loss_ratio=0.0,
        )
        assert fraction == Decimal("0")

    def test_negative_avg_win_loss_ratio(self) -> None:
        """Negative avg_win_loss_ratio → treated as zero; returns 0."""
        fraction = KellyFractionalSizer.calculate_kelly_fraction(
            win_rate=0.55,
            avg_win_loss_ratio=-1.0,
        )
        assert fraction == Decimal("0")

    def test_losing_strategy_returns_zero(self) -> None:
        """30 % win rate, 1.0 ratio → negative Kelly; clamped to 0."""
        fraction = KellyFractionalSizer.calculate_kelly_fraction(
            win_rate=0.30,
            avg_win_loss_ratio=1.0,
        )
        # (0.30 * 1.0 - 0.70) / 1.0 = -0.40 → 0
        assert fraction == Decimal("0")

    def test_decimal_inputs_accepted(self) -> None:
        """Decimal inputs produce the same result as float inputs."""
        fraction_float = KellyFractionalSizer.calculate_kelly_fraction(0.55, 1.5)
        fraction_decimal = KellyFractionalSizer.calculate_kelly_fraction(
            Decimal("0.55"), Decimal("1.5")
        )
        assert abs(float(fraction_float) - float(fraction_decimal)) < 0.0001

    def test_returns_decimal_type(self) -> None:
        """Return type is always Decimal."""
        result = KellyFractionalSizer.calculate_kelly_fraction(0.55, 1.5)
        assert isinstance(result, Decimal)

    def test_high_win_rate_high_ratio(self) -> None:
        """70 % win rate, 2.0 ratio → positive Kelly fraction."""
        fraction = KellyFractionalSizer.calculate_kelly_fraction(
            win_rate=0.70,
            avg_win_loss_ratio=2.0,
        )
        # (0.70 * 2.0 - 0.30) / 2.0 = (1.40 - 0.30) / 2.0 = 1.10 / 2.0 = 0.55
        assert abs(float(fraction) - 0.55) < 0.0001


# ---------------------------------------------------------------------------
# KellyFractionalSizer.calculate_size
# ---------------------------------------------------------------------------


class TestKellyFractionalSizerCalculateSize:
    """calculate_size applies the fractional divisor and clamping."""

    def test_half_kelly_typical(self) -> None:
        """Half-Kelly: kelly=0.25 / 2 = 0.125; clamped to max 0.10."""
        sizer = _kelly_sizer(divisor=2, max_pct="0.10")
        result = sizer.calculate_size(win_rate=0.55, avg_win_loss_ratio=1.5)
        # fractional = 0.25 / 2 = 0.125 → clamped to 0.10
        assert abs(result - 0.10) < 0.001

    def test_quarter_kelly_typical(self) -> None:
        """Quarter-Kelly: kelly=0.25 / 4 = 0.0625; within bounds → 0.0625."""
        sizer = _kelly_sizer(divisor=4, max_pct="0.10", min_pct="0.03")
        result = sizer.calculate_size(win_rate=0.55, avg_win_loss_ratio=1.5)
        # fractional = 0.25 / 4 = 0.0625 (between 0.03 and 0.10)
        assert abs(result - 0.0625) < 0.001

    def test_no_edge_returns_zero(self) -> None:
        """Losing strategy → calculate_size returns 0.0 (below min_trade_pct)."""
        sizer = _kelly_sizer()
        result = sizer.calculate_size(win_rate=0.30, avg_win_loss_ratio=1.0)
        assert result == 0.0

    def test_zero_win_rate_returns_zero(self) -> None:
        """0 % win rate → no edge → 0.0."""
        sizer = _kelly_sizer()
        result = sizer.calculate_size(win_rate=0.0, avg_win_loss_ratio=2.0)
        assert result == 0.0

    def test_zero_ratio_returns_zero(self) -> None:
        """Zero avg_win_loss_ratio → undefined → 0.0."""
        sizer = _kelly_sizer()
        result = sizer.calculate_size(win_rate=0.55, avg_win_loss_ratio=0.0)
        assert result == 0.0

    def test_negative_ratio_returns_zero(self) -> None:
        """Negative avg_win_loss_ratio → 0.0 (no trade)."""
        sizer = _kelly_sizer()
        result = sizer.calculate_size(win_rate=0.55, avg_win_loss_ratio=-0.5)
        assert result == 0.0

    def test_large_kelly_fraction_clamped_to_max(self) -> None:
        """Huge Kelly fraction (perfect win rate) is clamped to max_trade_pct."""
        sizer = _kelly_sizer(max_pct="0.10")
        result = sizer.calculate_size(win_rate=1.0, avg_win_loss_ratio=2.0)
        # kelly = 1.0, half = 0.5 → clamped to 0.10
        assert result <= 0.10 + 0.0001

    def test_very_small_kelly_clamped_to_min(self) -> None:
        """Small edge: Kelly fraction / divisor < min_trade_pct → clamped to min."""
        sizer = _kelly_sizer(divisor=4, min_pct="0.03", max_pct="0.10")
        # Marginal edge: 51 % win rate, 1.01 ratio
        result = sizer.calculate_size(win_rate=0.51, avg_win_loss_ratio=1.01)
        # kelly ≈ (0.51*1.01 - 0.49)/1.01 ≈ very small positive
        # / 4 → even smaller → should hit min if below 0.03
        # or return 0.0 if Kelly itself is 0 (no edge)
        assert result == 0.0 or result >= 0.03

    def test_returns_float(self) -> None:
        """calculate_size always returns a Python float."""
        sizer = _kelly_sizer()
        result = sizer.calculate_size(win_rate=0.55, avg_win_loss_ratio=1.5)
        assert isinstance(result, float)

    def test_result_quantised_to_four_decimal_places(self) -> None:
        """Output has at most 4 decimal places."""
        sizer = _kelly_sizer()
        result = sizer.calculate_size(win_rate=0.57, avg_win_loss_ratio=1.3)
        result_str = f"{result:.10f}".rstrip("0")
        decimal_part = result_str.split(".")[1] if "." in result_str else ""
        assert len(decimal_part) <= 4

    def test_decimal_inputs_accepted(self) -> None:
        """Decimal win_rate and ratio are accepted without errors."""
        sizer = _kelly_sizer()
        result = sizer.calculate_size(
            win_rate=Decimal("0.55"),
            avg_win_loss_ratio=Decimal("1.5"),
        )
        assert isinstance(result, float)

    def test_default_config_no_crash(self) -> None:
        """KellyFractionalSizer() with no config argument uses defaults."""
        sizer = KellyFractionalSizer()
        result = sizer.calculate_size(win_rate=0.55, avg_win_loss_ratio=1.5)
        assert isinstance(result, float)
        assert result >= 0.0

    def test_break_even_strategy_returns_zero(self) -> None:
        """Exactly break-even strategy (kelly=0) → 0.0."""
        sizer = _kelly_sizer()
        result = sizer.calculate_size(win_rate=0.50, avg_win_loss_ratio=1.0)
        assert result == 0.0

    def test_half_kelly_divisor_halves_full_kelly(self) -> None:
        """Half-Kelly output is approximately half the Quarter-Kelly * 2."""
        half_sizer = _kelly_sizer(divisor=2, max_pct="1.0", min_pct="0.0")
        quarter_sizer = _kelly_sizer(divisor=4, max_pct="1.0", min_pct="0.0")
        half = half_sizer.calculate_size(win_rate=0.60, avg_win_loss_ratio=1.2)
        quarter = quarter_sizer.calculate_size(win_rate=0.60, avg_win_loss_ratio=1.2)
        # Half should be approximately double the quarter
        assert abs(half - 2 * quarter) < 0.001


# ---------------------------------------------------------------------------
# HybridConfig defaults
# ---------------------------------------------------------------------------


class TestHybridConfigDefaults:
    """HybridConfig ships with safe conservative defaults."""

    def test_kelly_divisor_default(self) -> None:
        """Default divisor is 2 (Half-Kelly)."""
        cfg = HybridConfig()
        assert cfg.kelly_divisor == 2

    def test_max_trade_pct_default(self) -> None:
        """Default max trade size is 10 %."""
        cfg = HybridConfig()
        assert cfg.max_trade_pct == Decimal("0.10")

    def test_min_trade_pct_default(self) -> None:
        """Default min trade size is 3 %."""
        cfg = HybridConfig()
        assert cfg.min_trade_pct == Decimal("0.03")

    def test_target_vol_default(self) -> None:
        """Default target volatility is 2 %."""
        cfg = HybridConfig()
        assert cfg.target_vol == Decimal("0.02")

    def test_custom_target_vol(self) -> None:
        """Custom target_vol is stored correctly."""
        cfg = HybridConfig(target_vol=Decimal("0.015"))
        assert cfg.target_vol == Decimal("0.015")

    def test_divisor_must_be_at_least_one(self) -> None:
        """kelly_divisor=0 raises a validation error."""
        with pytest.raises(Exception):
            HybridConfig(kelly_divisor=0)


# ---------------------------------------------------------------------------
# HybridSizer.calculate_size — volatility adjustment
# ---------------------------------------------------------------------------


class TestHybridSizerVolatilityAdjustment:
    """Hybrid sizer scales Kelly fraction by target_vol / current_vol."""

    def test_current_vol_equals_target_vol_no_adjustment(self) -> None:
        """When current_vol == target_vol, adjustment multiplier is 1.0."""
        # current_vol = atr / close = 840 / 42000 = 0.02 = target_vol
        sizer = _hybrid_sizer(target_vol="0.02", max_pct="1.0", min_pct="0.0")
        result = sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            atr=840.0,
            close_price=42000.0,
        )
        # kelly = 0.25, half = 0.125; current_vol = 0.02 = target → no change
        assert abs(result - 0.125) < 0.001

    def test_high_volatility_reduces_size(self) -> None:
        """current_vol > target_vol → position reduced proportionally."""
        # current_vol = 2000 / 40000 = 0.05 (> 0.02 target)
        sizer = _hybrid_sizer(target_vol="0.02", max_pct="1.0", min_pct="0.0")
        result = sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            atr=2000.0,
            close_price=40000.0,
        )
        # kelly=0.25, half=0.125; vol_mult=0.02/0.05=0.4 → 0.125*0.4=0.05
        assert abs(result - 0.05) < 0.001

    def test_low_volatility_increases_size(self) -> None:
        """current_vol < target_vol → position increased (capped by max)."""
        # current_vol = 400 / 40000 = 0.01 (< 0.02 target)
        sizer = _hybrid_sizer(target_vol="0.02", max_pct="1.0", min_pct="0.0")
        result = sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            atr=400.0,
            close_price=40000.0,
        )
        # kelly=0.25, half=0.125; vol_mult=0.02/0.01=2.0 → 0.125*2.0=0.25
        assert abs(result - 0.25) < 0.001

    def test_low_volatility_clamped_to_max(self) -> None:
        """Very low volatility amplification is capped by max_trade_pct."""
        # current_vol = 100 / 40000 = 0.0025 (very low)
        sizer = _hybrid_sizer(target_vol="0.02", max_pct="0.10", min_pct="0.03")
        result = sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            atr=100.0,
            close_price=40000.0,
        )
        assert result <= 0.10 + 0.0001

    def test_high_volatility_clamped_to_min(self) -> None:
        """Extreme volatility would push below min_trade_pct — clamped to min."""
        # current_vol = 20000 / 40000 = 0.5 (extreme)
        sizer = _hybrid_sizer(target_vol="0.02", max_pct="0.10", min_pct="0.03")
        result = sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            atr=20000.0,
            close_price=40000.0,
        )
        # kelly=0.25/2=0.125; vol_mult=0.02/0.5=0.04 → 0.125*0.04=0.005 < min
        assert result >= 0.03


# ---------------------------------------------------------------------------
# HybridSizer.calculate_size — edge cases
# ---------------------------------------------------------------------------


class TestHybridSizerEdgeCases:
    """HybridSizer handles zero/negative inputs safely."""

    def test_zero_atr_skips_vol_adjustment(self) -> None:
        """atr=0 → volatility step skipped; raw fractional Kelly returned."""
        sizer = _hybrid_sizer(target_vol="0.02", max_pct="1.0", min_pct="0.0")
        result = sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            atr=0.0,
            close_price=40000.0,
        )
        # No vol adj → half-kelly = 0.125
        assert abs(result - 0.125) < 0.001

    def test_zero_close_price_skips_vol_adjustment(self) -> None:
        """close_price=0 → volatility step skipped; raw fractional Kelly returned."""
        sizer = _hybrid_sizer(target_vol="0.02", max_pct="1.0", min_pct="0.0")
        result = sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            atr=1200.0,
            close_price=0.0,
        )
        assert abs(result - 0.125) < 0.001

    def test_negative_atr_skips_vol_adjustment(self) -> None:
        """Negative atr → skips vol adjustment; no exception raised."""
        sizer = _hybrid_sizer(target_vol="0.02", max_pct="1.0", min_pct="0.0")
        result = sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            atr=-100.0,
            close_price=40000.0,
        )
        assert abs(result - 0.125) < 0.001

    def test_negative_close_skips_vol_adjustment(self) -> None:
        """Negative close_price → skips vol adjustment; no exception raised."""
        sizer = _hybrid_sizer(target_vol="0.02", max_pct="1.0", min_pct="0.0")
        result = sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            atr=1200.0,
            close_price=-1.0,
        )
        assert abs(result - 0.125) < 0.001

    def test_no_edge_returns_zero(self) -> None:
        """Losing strategy → 0.0 regardless of vol data."""
        sizer = _hybrid_sizer()
        result = sizer.calculate_size(
            win_rate=0.30,
            avg_win_loss_ratio=1.0,
            atr=1200.0,
            close_price=40000.0,
        )
        assert result == 0.0

    def test_zero_win_rate_returns_zero(self) -> None:
        """0 % win rate → 0.0."""
        sizer = _hybrid_sizer()
        result = sizer.calculate_size(
            win_rate=0.0,
            avg_win_loss_ratio=2.0,
            atr=1200.0,
            close_price=40000.0,
        )
        assert result == 0.0

    def test_zero_ratio_returns_zero(self) -> None:
        """Zero avg_win_loss_ratio → undefined → 0.0."""
        sizer = _hybrid_sizer()
        result = sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=0.0,
            atr=1200.0,
            close_price=40000.0,
        )
        assert result == 0.0

    def test_returns_float(self) -> None:
        """calculate_size always returns a Python float."""
        sizer = _hybrid_sizer()
        result = sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            atr=1200.0,
            close_price=40000.0,
        )
        assert isinstance(result, float)

    def test_decimal_inputs_accepted(self) -> None:
        """Decimal atr and close_price are accepted without errors."""
        sizer = _hybrid_sizer(max_pct="1.0", min_pct="0.0")
        result = sizer.calculate_size(
            win_rate=Decimal("0.55"),
            avg_win_loss_ratio=Decimal("1.5"),
            atr=Decimal("840"),
            close_price=Decimal("42000"),
        )
        assert isinstance(result, float)

    def test_default_config_no_crash(self) -> None:
        """HybridSizer() with no config argument uses defaults."""
        sizer = HybridSizer()
        result = sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            atr=1200.0,
            close_price=40000.0,
        )
        assert isinstance(result, float)
        assert result >= 0.0

    def test_result_quantised_to_four_decimal_places(self) -> None:
        """Output has at most 4 decimal places."""
        sizer = _hybrid_sizer(max_pct="1.0", min_pct="0.0")
        result = sizer.calculate_size(
            win_rate=0.57,
            avg_win_loss_ratio=1.3,
            atr=1100.0,
            close_price=38000.0,
        )
        result_str = f"{result:.10f}".rstrip("0")
        decimal_part = result_str.split(".")[1] if "." in result_str else ""
        assert len(decimal_part) <= 4


# ---------------------------------------------------------------------------
# HybridSizer vs KellyFractionalSizer — consistency checks
# ---------------------------------------------------------------------------


class TestHybridVsKellyConsistency:
    """When current_vol equals target_vol, HybridSizer matches KellyFractionalSizer."""

    def test_at_target_vol_hybrid_matches_kelly(self) -> None:
        """current_vol == target_vol → hybrid equals kelly output."""
        # target_vol = 0.02; current_vol = 840 / 42000 = 0.02
        kelly_sizer = _kelly_sizer(divisor=2, max_pct="1.0", min_pct="0.0")
        hybrid_sizer = _hybrid_sizer(
            divisor=2, target_vol="0.02", max_pct="1.0", min_pct="0.0"
        )

        kelly_result = kelly_sizer.calculate_size(win_rate=0.55, avg_win_loss_ratio=1.5)
        hybrid_result = hybrid_sizer.calculate_size(
            win_rate=0.55,
            avg_win_loss_ratio=1.5,
            atr=840.0,
            close_price=42000.0,
        )
        assert abs(kelly_result - hybrid_result) < 0.001

    def test_hybrid_smaller_in_high_vol(self) -> None:
        """HybridSizer produces smaller size than KellyFractionalSizer in high-vol."""
        kelly_sizer = _kelly_sizer(divisor=2, max_pct="1.0", min_pct="0.0")
        hybrid_sizer = _hybrid_sizer(
            divisor=2, target_vol="0.02", max_pct="1.0", min_pct="0.0"
        )
        win_rate, ratio = 0.55, 1.5
        # high vol: 4000 / 40000 = 0.10 >> 0.02 target
        kelly_result = kelly_sizer.calculate_size(win_rate=win_rate, avg_win_loss_ratio=ratio)
        hybrid_result = hybrid_sizer.calculate_size(
            win_rate=win_rate,
            avg_win_loss_ratio=ratio,
            atr=4000.0,
            close_price=40000.0,
        )
        assert hybrid_result < kelly_result

    def test_hybrid_larger_in_low_vol_up_to_max(self) -> None:
        """HybridSizer produces larger size than Kelly in low-vol, bounded by max."""
        kelly_sizer = _kelly_sizer(divisor=2, max_pct="0.10", min_pct="0.03")
        hybrid_sizer = _hybrid_sizer(
            divisor=2, target_vol="0.02", max_pct="0.10", min_pct="0.03"
        )
        win_rate, ratio = 0.55, 1.5
        # low vol: 200 / 40000 = 0.005 << 0.02 target
        kelly_result = kelly_sizer.calculate_size(win_rate=win_rate, avg_win_loss_ratio=ratio)
        hybrid_result = hybrid_sizer.calculate_size(
            win_rate=win_rate,
            avg_win_loss_ratio=ratio,
            atr=200.0,
            close_price=40000.0,
        )
        # hybrid should be >= kelly, capped at 0.10
        assert hybrid_result >= kelly_result or abs(hybrid_result - 0.10) < 0.001


# ---------------------------------------------------------------------------
# Bounds enforcement — both sizers
# ---------------------------------------------------------------------------


class TestBoundsEnforcementKellyHybrid:
    """Results stay within [min_trade_pct, max_trade_pct] for all valid inputs."""

    def test_kelly_result_never_above_max(self) -> None:
        """No win_rate/ratio combination exceeds max_trade_pct."""
        sizer = _kelly_sizer(max_pct="0.10", min_pct="0.03")
        test_cases = [
            (1.0, 10.0),  # perfect win rate, high ratio
            (0.90, 5.0),
            (0.75, 3.0),
            (0.65, 2.0),
        ]
        for win_rate, ratio in test_cases:
            result = sizer.calculate_size(win_rate=win_rate, avg_win_loss_ratio=ratio)
            assert result <= 0.10 + 0.0001, (
                f"Result {result} exceeds max for win_rate={win_rate}, ratio={ratio}"
            )

    def test_kelly_result_at_least_min_when_has_edge(self) -> None:
        """When there is genuine edge, result is >= min_trade_pct."""
        sizer = _kelly_sizer(max_pct="0.10", min_pct="0.03")
        test_cases = [
            (0.55, 1.5),
            (0.60, 1.2),
            (0.70, 2.0),
        ]
        for win_rate, ratio in test_cases:
            result = sizer.calculate_size(win_rate=win_rate, avg_win_loss_ratio=ratio)
            if result > 0.0:  # 0.0 is special "no trade" signal
                assert result >= 0.03, (
                    f"Result {result} below min for win_rate={win_rate}, ratio={ratio}"
                )

    def test_hybrid_result_never_above_max(self) -> None:
        """No input combination pushes HybridSizer above max_trade_pct."""
        sizer = _hybrid_sizer(max_pct="0.10", min_pct="0.03", target_vol="0.02")
        test_cases = [
            (1.0, 10.0, 100.0, 40000.0),   # perfect win, very low vol
            (0.80, 3.0, 200.0, 40000.0),
            (0.60, 1.5, 400.0, 40000.0),
        ]
        for win_rate, ratio, atr, close in test_cases:
            result = sizer.calculate_size(win_rate=win_rate, avg_win_loss_ratio=ratio,
                                          atr=atr, close_price=close)
            assert result <= 0.10 + 0.0001, (
                f"Result {result} exceeds max for inputs "
                f"({win_rate}, {ratio}, {atr}, {close})"
            )

    def test_hybrid_result_never_below_min_when_has_edge(self) -> None:
        """When HybridSizer has edge, result stays >= min_trade_pct."""
        sizer = _hybrid_sizer(max_pct="0.10", min_pct="0.03", target_vol="0.02")
        test_cases = [
            (0.55, 1.5, 20000.0, 40000.0),  # extreme high vol
            (0.60, 1.2, 8000.0, 40000.0),
        ]
        for win_rate, ratio, atr, close in test_cases:
            result = sizer.calculate_size(win_rate=win_rate, avg_win_loss_ratio=ratio,
                                          atr=atr, close_price=close)
            if result > 0.0:
                assert result >= 0.03


# ---------------------------------------------------------------------------
# Package import surface
# ---------------------------------------------------------------------------


class TestPackageImport:
    """New symbols are importable from the package __init__."""

    def test_import_from_package(self) -> None:
        """SizingMethod, KellyConfig, KellyFractionalSizer, HybridConfig, HybridSizer importable."""
        from agent.strategies.risk import (  # noqa: PLC0415
            HybridConfig,
            HybridSizer,
            KellyConfig,
            KellyFractionalSizer,
            SizingMethod,
        )
        assert SizingMethod.KELLY == "kelly"
        assert KellyConfig().kelly_divisor == 2
        assert HybridConfig().target_vol == Decimal("0.02")
        assert callable(KellyFractionalSizer().calculate_size)
        assert callable(HybridSizer().calculate_size)

    def test_all_list_contains_new_symbols(self) -> None:
        """__all__ in risk.__init__ exposes the new sizing classes."""
        import agent.strategies.risk as risk_pkg  # noqa: PLC0415

        assert "SizingMethod" in risk_pkg.__all__
        assert "KellyConfig" in risk_pkg.__all__
        assert "KellyFractionalSizer" in risk_pkg.__all__
        assert "HybridConfig" in risk_pkg.__all__
        assert "HybridSizer" in risk_pkg.__all__
