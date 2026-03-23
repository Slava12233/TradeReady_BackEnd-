"""Targeted labeler tests for agent/strategies/regime/labeler.py.

These tests complement the broad test_regime.py suite with focused
rule-level assertions:

- ADX > ADX_TREND_THRESHOLD fires TRENDING (highest priority)
- ATR > 2x median fires HIGH_VOLATILITY (when not trending)
- ATR < 0.5x median fires LOW_VOLATILITY (when not trending)
- Both indicators below thresholds → MEAN_REVERTING
- All four RegimeTypes are individually producible
- Low-volatility candles produce LOW_VOLATILITY labels
- Labeler constants have the expected values (acceptance criteria)
- volume_ratio feature is computed and behaves correctly

No existing tests in test_regime.py cover:
- The LOW_VOLATILITY label in isolation
- Direct constant-value assertions for ADX_TREND_THRESHOLD,
  HIGH_VOLATILITY_MULTIPLIER, LOW_VOLATILITY_MULTIPLIER
- Explicit verification that all four types appear in the same dataset
- volume_ratio indicator helper and feature inclusion
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from agent.strategies.regime.labeler import (
    ADX_TREND_THRESHOLD,
    HIGH_VOLATILITY_MULTIPLIER,
    LOW_VOLATILITY_MULTIPLIER,
    RegimeType,
    _adx_series,
    _atr_series,
    _volume_ratio_series,
    generate_training_data,
    label_candles,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_candles(
    n: int,
    base_close: float = 100.0,
    noise_std: float = 0.5,
    trend: float = 0.0,
    high_offset: float = 1.0,
    low_offset: float = 1.0,
    seed: int = 0,
) -> list[dict]:
    rng = np.random.default_rng(seed)
    candles = []
    close = base_close
    for _ in range(n):
        close = max(close + trend + rng.normal(0, noise_std), 0.01)
        candles.append(
            {
                "open": close,
                "high": close + high_offset,
                "low": max(close - low_offset, 0.01),
                "close": close,
                "volume": 1000.0,
            }
        )
    return candles


def _make_candles_with_varying_volume(n: int, seed: int = 0) -> list[dict]:
    """Generate OHLCV candles where the second half has 10x the volume of the first half.

    This creates a clear contrast between low-volume and high-volume periods
    so that volume_ratio values are clearly above 1.0 in the second half.
    """
    rng = np.random.default_rng(seed)
    candles = []
    close = 100.0
    for i in range(n):
        close = max(close + float(rng.normal(0, 0.5)), 0.01)
        # First half: low volume; second half: high volume.
        vol = 500.0 if i < n // 2 else 5000.0
        candles.append(
            {
                "open": close,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": vol,
            }
        )
    return candles


# ---------------------------------------------------------------------------
# Labeler constant values (acceptance criteria)
# ---------------------------------------------------------------------------


class TestLabelerConstants:
    """Verify the threshold constants match the documented acceptance criteria."""

    def test_adx_trend_threshold_is_25(self) -> None:
        """ADX > 25 should produce TRENDING — constant must equal 25.0."""
        assert ADX_TREND_THRESHOLD == 25.0

    def test_high_volatility_multiplier_is_2(self) -> None:
        """ATR > 2x median ratio must fire HIGH_VOLATILITY — multiplier must be 2.0."""
        assert HIGH_VOLATILITY_MULTIPLIER == 2.0

    def test_low_volatility_multiplier_is_half(self) -> None:
        """ATR < 0.5x median ratio must fire LOW_VOLATILITY — multiplier must be 0.5."""
        assert LOW_VOLATILITY_MULTIPLIER == 0.5


# ---------------------------------------------------------------------------
# Rule: ADX > 25 → TRENDING
# ---------------------------------------------------------------------------


class TestTrendingRule:
    """Tests that ADX above the threshold produces TRENDING labels."""

    def test_strong_persistent_trend_produces_trending_labels(self) -> None:
        """A strong, sustained uptrend should eventually produce TRENDING labels."""
        # Large trend increment and tight spread pushes ADX well above 25.
        candles = _make_candles(300, trend=3.0, noise_std=0.05, high_offset=3.5, low_offset=0.5, seed=10)
        labels = label_candles(candles, window=14)
        trending_count = sum(1 for lbl in labels if lbl == RegimeType.TRENDING)
        assert trending_count > 0, "Expected TRENDING labels for strongly trending candles"

    def test_trending_labels_are_regime_type(self) -> None:
        """Every label returned for trending data is a proper RegimeType instance."""
        candles = _make_candles(300, trend=3.0, noise_std=0.05, high_offset=3.5, low_offset=0.5, seed=11)
        labels = label_candles(candles, window=14)
        for lbl in labels:
            assert isinstance(lbl, RegimeType)

    def test_adx_series_exceeds_25_for_strong_trend(self) -> None:
        """The ADX indicator itself exceeds 25 on a clearly trending sequence."""
        candles = _make_candles(300, trend=3.0, noise_std=0.05, high_offset=3.5, low_offset=0.5, seed=12)
        closes = np.array([c["close"] for c in candles])
        highs = np.array([c["high"] for c in candles])
        lows = np.array([c["low"] for c in candles])
        adx = _adx_series(highs, lows, closes, period=14)
        valid_adx = adx[~np.isnan(adx)]
        # At least some computed ADX values should exceed the trend threshold.
        assert np.any(valid_adx > ADX_TREND_THRESHOLD), (
            f"Expected ADX > {ADX_TREND_THRESHOLD} for trending candles, "
            f"max ADX = {np.max(valid_adx):.2f}"
        )

    def test_trending_priority_over_high_volatility(self) -> None:
        """TRENDING takes priority over HIGH_VOLATILITY when both conditions hold.

        We verify this indirectly: a strongly trending sequence produces
        TRENDING labels even when individual candle ranges are wide.
        """
        candles = _make_candles(
            300,
            trend=3.0,
            noise_std=0.05,
            high_offset=10.0,  # large spread would normally suggest high volatility
            low_offset=10.0,
            seed=13,
        )
        labels = label_candles(candles, window=14)
        # Should still contain TRENDING labels despite large spreads.
        assert RegimeType.TRENDING in set(labels)


# ---------------------------------------------------------------------------
# Rule: ATR > 2x median → HIGH_VOLATILITY
# ---------------------------------------------------------------------------


class TestHighVolatilityRule:
    """Tests that extreme ATR produces HIGH_VOLATILITY labels."""

    def test_extreme_high_low_spread_produces_high_volatility(self) -> None:
        """Very wide candle ranges produce HIGH_VOLATILITY labels."""
        candles = _make_candles(200, noise_std=5.0, high_offset=15.0, low_offset=15.0, seed=20)
        labels = label_candles(candles, window=14)
        hv_count = sum(1 for lbl in labels if lbl == RegimeType.HIGH_VOLATILITY)
        assert hv_count > 0, "Expected HIGH_VOLATILITY labels for extreme-spread candles"

    def test_high_volatility_in_composite_dataset(self) -> None:
        """In a composite (quiet + volatile + trending) dataset, HIGH_VOLATILITY labels appear.

        The threshold for HIGH_VOLATILITY is >2x the dataset-wide median ATR/close
        ratio. A pure high-volatility segment alone does not trigger the label because
        there is no contrasting quiet segment to push the median down. A composite
        dataset provides the necessary contrast.
        """
        quiet = _make_candles(200, noise_std=0.001, high_offset=0.001, low_offset=0.001, seed=20)
        volatile = _make_candles(200, trend=0.0, noise_std=5.0, high_offset=15.0, low_offset=15.0, seed=21)
        candles = quiet + volatile
        labels = label_candles(candles, window=14)
        hv_count = sum(1 for lbl in labels if lbl == RegimeType.HIGH_VOLATILITY)
        assert hv_count > 0, (
            "Expected HIGH_VOLATILITY labels when a volatile segment follows a quiet segment"
        )

    def test_atr_exceeds_2x_median_in_contrast_dataset(self) -> None:
        """ATR/close ratios in a volatile segment exceed 2x the median when contrasted with quiet data."""
        quiet = _make_candles(150, noise_std=0.001, high_offset=0.001, low_offset=0.001, seed=22)
        volatile = _make_candles(150, trend=0.0, noise_std=5.0, high_offset=15.0, low_offset=15.0, seed=23)
        candles = quiet + volatile
        closes = np.array([c["close"] for c in candles])
        highs = np.array([c["high"] for c in candles])
        lows = np.array([c["low"] for c in candles])
        atr = _atr_series(highs, lows, closes, period=14)
        valid_mask = ~np.isnan(atr) & (closes > 0)
        ratios = atr[valid_mask] / closes[valid_mask]
        median_ratio = float(np.median(ratios))
        assert np.any(ratios > HIGH_VOLATILITY_MULTIPLIER * median_ratio), (
            "Expected some ATR/close ratios to exceed 2x the median when "
            "mixing quiet and volatile candle segments"
        )


# ---------------------------------------------------------------------------
# Rule: ATR < 0.5x median → LOW_VOLATILITY
# ---------------------------------------------------------------------------


class TestLowVolatilityRule:
    """Tests that very tight ATR produces LOW_VOLATILITY labels."""

    def test_flat_tight_candles_produce_low_volatility_in_contrast_dataset(self) -> None:
        """Very tight candles produce LOW_VOLATILITY labels when preceded by noisy data.

        The LOW_VOLATILITY threshold fires when ATR/close < 0.5x the dataset-wide
        median. A purely tight dataset has a low median, so nothing falls below 0.5x.
        Preceding the tight segment with noisy data raises the median so that the
        quiet segment produces LOW_VOLATILITY labels.
        """
        noisy = _make_candles(200, noise_std=3.0, high_offset=5.0, low_offset=5.0, seed=30)
        quiet = _make_candles(200, noise_std=0.001, high_offset=0.001, low_offset=0.001, seed=31)
        candles = noisy + quiet
        labels = label_candles(candles, window=14)
        lv_count = sum(1 for lbl in labels if lbl == RegimeType.LOW_VOLATILITY)
        assert lv_count > 0, "Expected LOW_VOLATILITY labels when quiet segment follows noisy segment"

    def test_low_volatility_label_is_regime_type(self) -> None:
        """LOW_VOLATILITY labels are proper RegimeType instances."""
        candles = _make_candles(300, noise_std=0.001, high_offset=0.001, low_offset=0.001, seed=31)
        labels = label_candles(candles, window=14)
        for lbl in labels:
            assert isinstance(lbl, RegimeType)

    def test_atr_below_half_median_for_quiet_candles(self) -> None:
        """The ATR/close ratio falls below 0.5x the median for quiet candles."""
        # Generate two segments: a noisy period (to push the median up) followed
        # by an extremely quiet period (where some ratios will fall below 0.5x
        # the combined-dataset median).
        noisy = _make_candles(150, noise_std=2.0, high_offset=3.0, low_offset=3.0, seed=32)
        quiet = _make_candles(150, noise_std=0.001, high_offset=0.001, low_offset=0.001, seed=33)
        candles = noisy + quiet
        closes = np.array([c["close"] for c in candles])
        highs = np.array([c["high"] for c in candles])
        lows = np.array([c["low"] for c in candles])
        atr = _atr_series(highs, lows, closes, period=14)
        valid_mask = ~np.isnan(atr) & (closes > 0)
        ratios = atr[valid_mask] / closes[valid_mask]
        median_ratio = float(np.median(ratios))
        assert np.any(ratios < LOW_VOLATILITY_MULTIPLIER * median_ratio), (
            "Expected some ATR/close ratios to fall below 0.5x the median "
            "when mixing noisy and quiet candle segments"
        )


# ---------------------------------------------------------------------------
# Rule: Both indicators below thresholds → MEAN_REVERTING
# ---------------------------------------------------------------------------


class TestMeanRevertingRule:
    """Tests that moderate data falls through to MEAN_REVERTING."""

    def test_moderate_data_produces_mean_reverting(self) -> None:
        """Data without extreme trend or volatility should yield MEAN_REVERTING labels."""
        candles = _make_candles(200, trend=0.0, noise_std=0.5, high_offset=1.0, low_offset=1.0, seed=40)
        labels = label_candles(candles, window=14)
        mr_count = sum(1 for lbl in labels if lbl == RegimeType.MEAN_REVERTING)
        assert mr_count > 0, "Expected MEAN_REVERTING labels for moderate data"

    def test_insufficient_data_returns_all_mean_reverting(self) -> None:
        """When window is too large for the input, all labels default to MEAN_REVERTING."""
        candles = _make_candles(3)
        labels = label_candles(candles, window=14)
        assert all(lbl == RegimeType.MEAN_REVERTING for lbl in labels)

    def test_mean_reverting_is_default_for_new_data(self) -> None:
        """The first few candles (before warm-up completes) are MEAN_REVERTING."""
        candles = _make_candles(100, seed=41)
        labels = label_candles(candles, window=14)
        # Candles before warm-up must not be TRENDING or volatility-labeled.
        # The exact warm-up period is window + 1 for ADX, so at least index 0
        # should be MEAN_REVERTING.
        assert labels[0] == RegimeType.MEAN_REVERTING


# ---------------------------------------------------------------------------
# All four regime types can be produced
# ---------------------------------------------------------------------------


class TestAllFourRegimeTypes:
    """Verify each of the four RegimeTypes is independently producible."""

    def test_trending_is_producible(self) -> None:
        candles = _make_candles(300, trend=3.0, noise_std=0.05, high_offset=3.5, low_offset=0.5, seed=50)
        labels = label_candles(candles, window=14)
        assert RegimeType.TRENDING in set(labels), "TRENDING label not produced"

    def test_high_volatility_is_producible(self) -> None:
        # Need a contrast between quiet and volatile segments so ATR/close ratios
        # in the volatile segment exceed 2x the dataset median.
        quiet = _make_candles(200, noise_std=0.001, high_offset=0.001, low_offset=0.001, seed=51)
        volatile = _make_candles(200, trend=0.0, noise_std=5.0, high_offset=15.0, low_offset=15.0, seed=52)
        candles = quiet + volatile
        labels = label_candles(candles, window=14)
        assert RegimeType.HIGH_VOLATILITY in set(labels), "HIGH_VOLATILITY label not produced"

    def test_low_volatility_is_producible(self) -> None:
        # Need noisy data first to raise the median, then quiet data falls below 0.5x median.
        noisy = _make_candles(200, noise_std=3.0, high_offset=5.0, low_offset=5.0, seed=53)
        quiet = _make_candles(200, noise_std=0.001, high_offset=0.001, low_offset=0.001, seed=54)
        candles = noisy + quiet
        labels = label_candles(candles, window=14)
        assert RegimeType.LOW_VOLATILITY in set(labels), "LOW_VOLATILITY label not produced"

    def test_mean_reverting_is_producible(self) -> None:
        candles = _make_candles(100, trend=0.0, noise_std=0.5, high_offset=1.0, low_offset=1.0, seed=53)
        labels = label_candles(candles, window=14)
        assert RegimeType.MEAN_REVERTING in set(labels), "MEAN_REVERTING label not produced"

    def test_all_four_present_in_composite_dataset(self) -> None:
        """A composite dataset spanning all regime types produces all four labels."""
        trending = _make_candles(
            300, trend=3.0, noise_std=0.05, high_offset=3.5, low_offset=0.5, seed=60
        )
        high_vol = _make_candles(
            200, trend=0.0, noise_std=5.0, high_offset=15.0, low_offset=15.0, seed=61
        )
        low_vol = _make_candles(
            300, noise_std=0.001, high_offset=0.001, low_offset=0.001, seed=62
        )
        moderate = _make_candles(
            200, trend=0.0, noise_std=0.5, high_offset=1.0, low_offset=1.0, seed=63
        )
        composite = trending + high_vol + low_vol + moderate

        labels = label_candles(composite, window=14)
        label_set = set(labels)

        missing = [r for r in RegimeType if r not in label_set]
        assert not missing, (
            f"Composite dataset did not produce these regime types: "
            f"{[r.value for r in missing]}"
        )

    def test_determinism_across_all_four_regime_types(self) -> None:
        """Identical composite input always produces identical output (fixed seed)."""
        trending = _make_candles(300, trend=3.0, noise_std=0.05, high_offset=3.5, low_offset=0.5, seed=70)
        high_vol = _make_candles(200, trend=0.0, noise_std=5.0, high_offset=15.0, low_offset=15.0, seed=71)
        low_vol = _make_candles(300, noise_std=0.001, high_offset=0.001, low_offset=0.001, seed=72)
        moderate = _make_candles(200, trend=0.0, noise_std=0.5, high_offset=1.0, low_offset=1.0, seed=73)
        composite = trending + high_vol + low_vol + moderate

        labels_a = label_candles(composite, window=14)
        labels_b = label_candles(composite, window=14)
        assert labels_a == labels_b, "label_candles is not deterministic for the same input"


# ---------------------------------------------------------------------------
# volume_ratio feature — _volume_ratio_series and generate_training_data
# ---------------------------------------------------------------------------


class TestVolumeRatioSeries:
    """Unit tests for the _volume_ratio_series helper (feature 6)."""

    def test_returns_nan_before_warmup(self) -> None:
        """Positions before period-1 must all be NaN (SMA not yet computable)."""
        volumes = np.ones(25, dtype=np.float64)
        result = _volume_ratio_series(volumes, period=20)
        # Positions 0..18 have insufficient history; position 19 is the first valid.
        assert np.all(np.isnan(result[:19]))
        assert not np.isnan(result[19])

    def test_uniform_volume_produces_ratio_of_one(self) -> None:
        """When all volumes are equal, volume_ratio must be exactly 1.0 everywhere."""
        volumes = np.full(100, 1000.0)
        result = _volume_ratio_series(volumes, period=20)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert np.allclose(valid, 1.0), f"Expected all 1.0, got min={valid.min():.4f} max={valid.max():.4f}"

    def test_doubled_volume_produces_ratio_above_one(self) -> None:
        """A candle with 2x the average volume produces volume_ratio > 1."""
        # 20 candles at volume=100, then one spike to 200.
        volumes = np.array([100.0] * 20 + [200.0] + [100.0] * 10)
        result = _volume_ratio_series(volumes, period=20)
        # Index 20 is the spike: SMA(20) at index 20 includes positions 1..20.
        # SMA = (19*100 + 200) / 20 = 105. ratio = 200 / 105 ≈ 1.905 > 1.
        assert result[20] > 1.0, f"Expected volume_ratio > 1 at spike, got {result[20]:.4f}"

    def test_halved_volume_produces_ratio_below_one(self) -> None:
        """A candle with half the average volume produces volume_ratio < 1."""
        volumes = np.array([100.0] * 20 + [50.0] + [100.0] * 10)
        result = _volume_ratio_series(volumes, period=20)
        # At index 20: SMA(20) = (19*100 + 50)/20 = 97.5; ratio = 50/97.5 ≈ 0.513 < 1.
        assert result[20] < 1.0, f"Expected volume_ratio < 1 for halved volume, got {result[20]:.4f}"

    def test_zero_volume_window_returns_nan(self) -> None:
        """A window of all-zero volumes must return NaN to avoid division by zero."""
        volumes = np.zeros(30, dtype=np.float64)
        result = _volume_ratio_series(volumes, period=20)
        # All-zero SMA → all NaN.
        assert np.all(np.isnan(result[19:]))

    def test_length_matches_input(self) -> None:
        """Output length must equal input length regardless of period."""
        for n in (20, 50, 100):
            volumes = np.ones(n) * 500.0
            result = _volume_ratio_series(volumes, period=20)
            assert len(result) == n, f"Expected length {n}, got {len(result)}"

    def test_deterministic(self) -> None:
        """Same input always produces identical output."""
        volumes = np.array([float(i + 1) * 100 for i in range(50)])
        r1 = _volume_ratio_series(volumes, period=20)
        r2 = _volume_ratio_series(volumes, period=20)
        np.testing.assert_array_equal(r1, r2)

    def test_high_volume_spike_ratio_exceeds_one_in_contrast_dataset(self) -> None:
        """In a low-then-high-volume dataset, the second half has volume_ratio > 1."""
        candles = _make_candles_with_varying_volume(n=200, seed=5)
        volumes = np.array([c["volume"] for c in candles])
        result = _volume_ratio_series(volumes, period=20)
        # The second 100 candles (indices 100..199) should mostly have ratio > 1
        # since average volume in the first half was 500 and second half is 5000.
        valid_second_half = result[100:][~np.isnan(result[100:])]
        assert len(valid_second_half) > 0
        assert np.mean(valid_second_half) > 1.0, (
            "Expected volume_ratio > 1 in high-volume half of dataset"
        )

    def test_first_valid_position_is_period_minus_one(self) -> None:
        """The first non-NaN position must be at index period-1."""
        period = 20
        volumes = np.ones(50, dtype=np.float64) * 1000.0
        result = _volume_ratio_series(volumes, period=period)
        assert np.isnan(result[period - 2])
        assert not np.isnan(result[period - 1])


class TestVolumeRatioInGenerateTrainingData:
    """Tests that volume_ratio is present and correct in generate_training_data output."""

    def _make_dataset_candles(self, n: int = 500, seed: int = 0) -> list[dict]:
        rng = np.random.default_rng(seed)
        candles = []
        close = 50000.0
        for _ in range(n):
            close = max(close + float(rng.normal(0, 50.0)), 1.0)
            candles.append(
                {
                    "open": close,
                    "high": close + abs(float(rng.normal(0, 25.0))),
                    "low": close - abs(float(rng.normal(0, 25.0))),
                    "close": close,
                    "volume": float(rng.integers(500, 5000)),
                }
            )
        return candles

    def test_volume_ratio_column_present(self) -> None:
        """generate_training_data must include a 'volume_ratio' column."""
        candles = self._make_dataset_candles(500)
        features, _ = generate_training_data(candles, window=20)
        assert "volume_ratio" in features.columns, (
            f"Expected 'volume_ratio' in features; columns={list(features.columns)}"
        )

    def test_volume_ratio_no_nan_after_dropna(self) -> None:
        """After NaN dropping, no NaN values remain in volume_ratio."""
        candles = self._make_dataset_candles(500)
        features, _ = generate_training_data(candles, window=20)
        assert not features["volume_ratio"].isnull().any(), (
            "volume_ratio column contains NaN after generate_training_data NaN-drop"
        )

    def test_volume_ratio_is_positive(self) -> None:
        """All volume_ratio values must be strictly positive (ratio of positive volumes)."""
        candles = self._make_dataset_candles(500)
        features, _ = generate_training_data(candles, window=20)
        assert (features["volume_ratio"] > 0).all(), (
            "Expected all volume_ratio values > 0"
        )

    def test_uniform_volume_candles_have_ratio_one(self) -> None:
        """When all candles have the same volume, volume_ratio == 1.0 everywhere."""
        candles = []
        close = 100.0
        for i in range(200):
            close = max(close + 0.01 * i, 0.01)  # mild uptrend
            candles.append(
                {
                    "open": close,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "close": close,
                    "volume": 1000.0,  # uniform volume
                }
            )
        features, _ = generate_training_data(candles, window=14)
        ratio = features["volume_ratio"]
        assert np.allclose(ratio.values, 1.0, atol=1e-9), (
            f"Expected volume_ratio == 1.0 for uniform volume candles; "
            f"got min={ratio.min():.6f} max={ratio.max():.6f}"
        )

    def test_feature_count_is_six(self) -> None:
        """generate_training_data must produce exactly 6 feature columns."""
        candles = self._make_dataset_candles(500)
        features, _ = generate_training_data(candles, window=20)
        assert len(features.columns) == 6, (
            f"Expected 6 features, got {len(features.columns)}: {list(features.columns)}"
        )

    def test_candles_without_volume_key_produce_nan_volume_ratio(self) -> None:
        """Candles lacking a 'volume' key default to 0 volume.

        A window of all-zero volumes yields NaN volume_ratio, so those rows
        are dropped by the NaN-filter in generate_training_data.  When only a
        small subset of rows are non-NaN they still form a valid feature set.
        """
        # Use candles that are missing the volume key entirely.
        candles = [
            {"close": float(i + 100), "high": float(i + 101), "low": float(i + 99)}
            for i in range(300)
        ]
        # This should either raise (no valid rows) or return features with no NaN.
        try:
            features, _ = generate_training_data(candles, window=14)
            # If it succeeds, volume_ratio must not contain NaN.
            assert not features["volume_ratio"].isnull().any()
        except ValueError as exc:
            # Acceptable: all rows dropped because all volumes are zero → NaN ratio.
            assert "No valid rows" in str(exc)

    def test_volume_ratio_increases_with_volume_spike(self) -> None:
        """Candles with volume spikes produce volume_ratio > 1 at those positions.

        We verify this by building a dataset where the second half has 10x the
        volume, which should drive volume_ratio significantly above 1.0 for
        the high-volume candles.
        """
        candles = _make_candles_with_varying_volume(n=300, seed=7)
        features, _ = generate_training_data(candles, window=14)

        # The mean volume_ratio should be well above 1 because the second half
        # (volume=5000) will dominate the rolling window and produce ratios >> 1.
        mean_ratio = features["volume_ratio"].mean()
        assert mean_ratio > 1.0, (
            f"Expected mean volume_ratio > 1 with volume spike candles, "
            f"got {mean_ratio:.4f}"
        )

    def test_volume_ratio_column_order(self) -> None:
        """volume_ratio must be the last (6th) column in the features DataFrame."""
        candles = self._make_dataset_candles(500)
        features, _ = generate_training_data(candles, window=20)
        assert features.columns[-1] == "volume_ratio", (
            f"Expected 'volume_ratio' as last column; got {list(features.columns)}"
        )
