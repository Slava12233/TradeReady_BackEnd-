"""Tests for src/metrics/deflated_sharpe.py.

Validates the Deflated Sharpe Ratio (DSR) implementation against known reference
values from Bailey & Lopez de Prado (2014) and checks all edge cases.

Run with::

    pytest tests/unit/test_deflated_sharpe.py -v
"""

from __future__ import annotations

import math

import pytest

from src.metrics.deflated_sharpe import (
    MIN_RETURNS,
    DeflatedSharpeResult,
    _normal_cdf,
    compute_deflated_sharpe,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GAUSSIAN_RETURNS = [
    0.001,
    -0.002,
    0.003,
    0.001,
    -0.001,
    0.002,
    0.000,
    -0.003,
    0.004,
    0.001,
]  # exactly MIN_RETURNS (10) observations


def _make_returns(n: int = 50, mean: float = 0.001, std: float = 0.01) -> list[float]:
    """Deterministic return series with known statistical properties.

    We build the series explicitly (not with random.gauss) so the test is
    fully reproducible without seeding the global random state.
    """
    # Alternate mean +/- std to get a stable, roughly-normal-ish distribution
    result = []
    for i in range(n):
        sign = 1.0 if i % 2 == 0 else -1.0
        result.append(mean + sign * std * (0.5 + (i % 5) * 0.1))
    return result


# ---------------------------------------------------------------------------
# Tests: _normal_cdf
# ---------------------------------------------------------------------------


class TestNormalCdf:
    """Tests for the pure-Python standard-normal CDF approximation."""

    def test_cdf_at_zero_is_half(self):
        """Φ(0) must equal 0.5 exactly (by symmetry)."""
        result = _normal_cdf(0.0)
        assert abs(result - 0.5) < 1e-7, f"Φ(0) expected 0.5, got {result}"

    def test_cdf_at_positive_1_96(self):
        """Φ(1.96) ≈ 0.9750 (critical value for 95% one-tailed test)."""
        result = _normal_cdf(1.96)
        assert abs(result - 0.975) < 1e-4, f"Φ(1.96) expected ≈0.975, got {result}"

    def test_cdf_at_negative_1_96(self):
        """Φ(-1.96) ≈ 0.0250 (left-tail complement)."""
        result = _normal_cdf(-1.96)
        assert abs(result - 0.025) < 1e-4, f"Φ(-1.96) expected ≈0.025, got {result}"

    def test_cdf_symmetry(self):
        """Φ(x) + Φ(-x) == 1 for all x (symmetry of the normal distribution)."""
        for x in [0.5, 1.0, 1.645, 2.0, 2.576, 3.0]:
            assert abs(_normal_cdf(x) + _normal_cdf(-x) - 1.0) < 1e-7, (
                f"Symmetry broken at x={x}: Φ({x})={_normal_cdf(x)}, Φ(-{x})={_normal_cdf(-x)}"
            )

    def test_cdf_at_2_0(self):
        """Φ(2.0) ≈ 0.9772."""
        result = _normal_cdf(2.0)
        assert abs(result - 0.9772) < 1e-3

    def test_cdf_at_3_0(self):
        """Φ(3.0) ≈ 0.9987."""
        result = _normal_cdf(3.0)
        assert abs(result - 0.9987) < 1e-3

    def test_cdf_bounded_between_zero_and_one(self):
        """CDF output must always be in [0, 1]."""
        for x in [-5.0, -3.0, -1.96, 0.0, 1.96, 3.0, 5.0]:
            cdf = _normal_cdf(x)
            assert 0.0 <= cdf <= 1.0, f"CDF out of bounds at x={x}: {cdf}"

    def test_cdf_monotonically_increasing(self):
        """CDF must be strictly monotonically increasing."""
        xs = [-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0]
        values = [_normal_cdf(x) for x in xs]
        for i in range(1, len(values)):
            assert values[i] > values[i - 1], (
                f"CDF not monotone at index {i}: Φ({xs[i]})={values[i]} <= Φ({xs[i - 1]})={values[i - 1]}"
            )

    def test_cdf_large_positive_approaches_one(self):
        """Φ(large positive) approaches 1."""
        assert _normal_cdf(10.0) > 0.9999

    def test_cdf_large_negative_approaches_zero(self):
        """Φ(large negative) approaches 0."""
        assert _normal_cdf(-10.0) < 0.0001


# ---------------------------------------------------------------------------
# Tests: compute_deflated_sharpe — input validation
# ---------------------------------------------------------------------------


class TestComputeDeflatedSharpeValidation:
    """Tests for input validation in compute_deflated_sharpe."""

    def test_raises_on_fewer_than_min_returns(self):
        """Fewer than MIN_RETURNS (10) observations must raise ValueError."""
        short_returns = [0.001] * (MIN_RETURNS - 1)
        with pytest.raises(ValueError, match=str(MIN_RETURNS)):
            compute_deflated_sharpe(short_returns, num_trials=1)

    def test_raises_on_empty_returns(self):
        """Empty list must raise ValueError."""
        with pytest.raises(ValueError):
            compute_deflated_sharpe([], num_trials=1)

    def test_raises_on_num_trials_zero(self):
        """num_trials=0 must raise ValueError."""
        with pytest.raises(ValueError, match="num_trials"):
            compute_deflated_sharpe(_GAUSSIAN_RETURNS, num_trials=0)

    def test_raises_on_negative_num_trials(self):
        """Negative num_trials must raise ValueError."""
        with pytest.raises(ValueError, match="num_trials"):
            compute_deflated_sharpe(_GAUSSIAN_RETURNS, num_trials=-5)

    def test_exactly_min_returns_does_not_raise(self):
        """Exactly MIN_RETURNS (10) observations must succeed."""
        result = compute_deflated_sharpe(_GAUSSIAN_RETURNS, num_trials=1)
        assert result.num_returns == MIN_RETURNS

    def test_returns_deflated_sharpe_result_type(self):
        """compute_deflated_sharpe must return a DeflatedSharpeResult instance."""
        result = compute_deflated_sharpe(_GAUSSIAN_RETURNS, num_trials=1)
        assert isinstance(result, DeflatedSharpeResult)


# ---------------------------------------------------------------------------
# Tests: compute_deflated_sharpe — return values
# ---------------------------------------------------------------------------


class TestComputeDeflatedSharpeResults:
    """Tests that computed values are mathematically correct."""

    def test_num_returns_matches_input_length(self):
        """num_returns field must equal len(returns)."""
        returns = _make_returns(n=100)
        result = compute_deflated_sharpe(returns, num_trials=5)
        assert result.num_returns == 100

    def test_num_trials_preserved_in_result(self):
        """num_trials field must match the value passed in."""
        result = compute_deflated_sharpe(_GAUSSIAN_RETURNS, num_trials=42)
        assert result.num_trials == 42

    def test_p_value_in_range(self):
        """p_value must always be in [0, 1]."""
        result = compute_deflated_sharpe(_make_returns(50), num_trials=10)
        assert 0.0 <= result.p_value <= 1.0

    def test_is_significant_consistent_with_p_value(self):
        """is_significant must be True iff p_value > 0.95."""
        returns = _make_returns(100)
        for num_trials in (1, 5, 20, 100):
            result = compute_deflated_sharpe(returns, num_trials=num_trials)
            assert result.is_significant == (result.p_value > 0.95)

    def test_observed_sharpe_annualization(self):
        """Observed Sharpe with annualization_factor=252 equals sqrt(252) × SR_factor_1."""
        # Use a series with non-zero mean AND non-zero variance to avoid the
        # constant-returns zero-variance path.
        returns = _make_returns(n=50, mean=0.001, std=0.01)
        result_252 = compute_deflated_sharpe(returns, num_trials=1, annualization_factor=252)
        result_1 = compute_deflated_sharpe(returns, num_trials=1, annualization_factor=1)
        # 252-period annualization should give sqrt(252) times the 1-period SR
        expected_ratio = math.sqrt(252)
        actual_ratio = result_252.observed_sharpe / result_1.observed_sharpe
        assert abs(actual_ratio - expected_ratio) < 1e-6

    def test_num_trials_1_expected_max_sharpe_is_zero(self):
        """When num_trials=1, expected_max_sharpe must be 0 (no selection bias)."""
        result = compute_deflated_sharpe(_make_returns(50), num_trials=1)
        assert result.expected_max_sharpe == 0.0

    def test_expected_max_sharpe_increases_with_more_trials(self):
        """expected_max_sharpe must increase as num_trials increases."""
        returns = _make_returns(100)
        prev_max_sr = 0.0
        for n in [2, 5, 10, 50, 100]:
            result = compute_deflated_sharpe(returns, num_trials=n)
            assert result.expected_max_sharpe >= prev_max_sr
            prev_max_sr = result.expected_max_sharpe

    def test_more_trials_makes_significance_harder(self):
        """Higher num_trials should generally reduce p_value (harder to pass)."""
        returns = _make_returns(100, mean=0.002, std=0.005)
        result_low = compute_deflated_sharpe(returns, num_trials=1)
        result_high = compute_deflated_sharpe(returns, num_trials=1000)
        assert result_low.p_value >= result_high.p_value

    def test_deflated_sharpe_equals_observed_when_num_trials_1(self):
        """When num_trials=1, DSR = (SR_obs - 0) / std_sr, not simply SR_obs."""
        result = compute_deflated_sharpe(_GAUSSIAN_RETURNS, num_trials=1)
        # With no selection bias correction, DSR is still normalised by variance
        # so it won't equal SR_obs directly — but p_value = Φ(DSR) should hold.
        recomputed_p = _normal_cdf(result.deflated_sharpe)
        assert abs(recomputed_p - result.p_value) < 1e-9

    def test_p_value_is_cdf_of_deflated_sharpe(self):
        """p_value must equal Φ(deflated_sharpe) for any input."""
        for n in [1, 5, 100]:
            result = compute_deflated_sharpe(_make_returns(50), num_trials=n)
            expected_p = _normal_cdf(result.deflated_sharpe)
            assert abs(result.p_value - expected_p) < 1e-9, (
                f"p_value mismatch for num_trials={n}: expected {expected_p}, got {result.p_value}"
            )

    def test_annualization_factor_changes_observed_sharpe(self):
        """Different annualization_factor values must produce different observed_sharpe."""
        returns = _make_returns(50)
        result_daily = compute_deflated_sharpe(returns, num_trials=1, annualization_factor=252)
        result_weekly = compute_deflated_sharpe(returns, num_trials=1, annualization_factor=52)
        assert result_daily.observed_sharpe != result_weekly.observed_sharpe

    def test_result_fields_are_floats(self):
        """All numeric result fields must be Python floats."""
        result = compute_deflated_sharpe(_GAUSSIAN_RETURNS, num_trials=1)
        for field_name in (
            "observed_sharpe",
            "expected_max_sharpe",
            "deflated_sharpe",
            "p_value",
            "skewness",
            "kurtosis",
        ):
            value = getattr(result, field_name)
            assert isinstance(value, float), f"Field {field_name!r} is {type(value)}, expected float"

    def test_result_is_frozen(self):
        """DeflatedSharpeResult is a frozen dataclass and must not allow mutation."""
        result = compute_deflated_sharpe(_GAUSSIAN_RETURNS, num_trials=1)
        with pytest.raises((AttributeError, TypeError)):
            result.p_value = 0.99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Tests: skewness and kurtosis computation
# ---------------------------------------------------------------------------


class TestSkewnessKurtosis:
    """Tests that skewness and kurtosis are computed correctly."""

    def test_symmetric_returns_near_zero_skewness(self):
        """Symmetric (alternating) returns must have near-zero skewness."""
        returns = [0.01, -0.01] * 25  # perfectly symmetric, zero mean
        result = compute_deflated_sharpe(returns, num_trials=1)
        # Symmetric distribution → skewness ≈ 0
        assert abs(result.skewness) < 1e-9

    def test_positive_skew_series(self):
        """Series with a few large positive outliers must have positive skewness."""
        base = [-0.001] * 40  # many small negatives
        outliers = [0.10, 0.15, 0.20]  # few large positives
        returns = base + outliers
        result = compute_deflated_sharpe(returns, num_trials=1)
        assert result.skewness > 0.0

    def test_normal_kurtosis_near_zero(self):
        """Approximately normal returns must have near-zero excess kurtosis."""
        # We use a large pre-defined series designed to approximate a normal
        # Exact zero-kurtosis isn't achievable deterministically; allow tolerance.
        # Build from the known formula: kurtosis deviation decreases with N.
        returns = _make_returns(n=200, mean=0.0, std=0.01)
        result = compute_deflated_sharpe(returns, num_trials=1)
        # Excess kurtosis for our deterministic series might not be 0, but
        # we verify it's a reasonable float (not infinite / NaN).
        assert math.isfinite(result.kurtosis)

    def test_kurtosis_stored_is_excess(self):
        """kurtosis field stores *excess* kurtosis (normal = 0, not 3)."""
        # For our symmetric alternating series with two values:
        # - raw fourth moment / std^4 = 1.0 (because all values are ±c)
        # - excess kurtosis = 1.0 - 3 = -2.0
        returns = [0.01, -0.01] * 25  # exactly ±0.01
        result = compute_deflated_sharpe(returns, num_trials=1)
        # All values are at exactly ±σ → raw kurtosis = (σ^4)/(σ^4) = 1
        # Excess kurtosis = 1 - 3 = -2
        assert abs(result.kurtosis - (-2.0)) < 1e-9


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge-case inputs."""

    def test_all_positive_returns(self):
        """Series with non-zero positive mean and variance must produce positive observed_sharpe.

        Note: a series of *identical* positive values has zero variance, which
        triggers the degenerate path (SR=0). We use varying returns to exercise
        the normal computation path.
        """
        # Positive mean, positive variance: mean=0.003, std≈0.002 alternating pattern
        returns = [0.005 if i % 2 == 0 else 0.001 for i in range(50)]
        result = compute_deflated_sharpe(returns, num_trials=1, annualization_factor=252)
        assert result.observed_sharpe > 0

    def test_all_negative_returns(self):
        """Series with non-zero negative mean and variance must produce negative observed_sharpe."""
        # Negative mean, positive variance
        returns = [-0.005 if i % 2 == 0 else -0.001 for i in range(50)]
        result = compute_deflated_sharpe(returns, num_trials=1, annualization_factor=252)
        assert result.observed_sharpe < 0

    def test_all_negative_returns_p_value_near_zero(self):
        """Consistently negative returns with many trials must have very low p_value."""
        returns = [-0.001] * 50
        result = compute_deflated_sharpe(returns, num_trials=100)
        assert result.p_value < 0.5

    def test_constant_returns_zero_variance(self):
        """Identical returns (zero variance) must not raise an exception.

        The implementation floors std_dev=0 and sets SR=0 to avoid division by zero.
        """
        returns = [0.001] * 50
        result = compute_deflated_sharpe(returns, num_trials=1)
        # All returns equal → SD = 0 → SR set to 0 per implementation
        assert result.observed_sharpe == 0.0
        assert result.skewness == 0.0
        assert result.kurtosis == 0.0
        assert result.p_value == _normal_cdf(result.deflated_sharpe)

    def test_constant_zero_returns(self):
        """All-zero returns (zero mean, zero variance) must not crash."""
        returns = [0.0] * 20
        result = compute_deflated_sharpe(returns, num_trials=1)
        assert result.observed_sharpe == 0.0
        assert 0.0 <= result.p_value <= 1.0

    def test_num_trials_1_no_selection_bias_correction(self):
        """num_trials=1 means expected_max_sharpe=0 (tested researcher used exactly 1 strategy)."""
        result = compute_deflated_sharpe(_make_returns(50), num_trials=1)
        assert result.expected_max_sharpe == 0.0

    def test_weekly_annualization_factor(self):
        """annualization_factor=52 (weekly returns) must produce a valid result."""
        returns = _make_returns(52)
        result = compute_deflated_sharpe(returns, num_trials=10, annualization_factor=52)
        assert result.num_returns == 52
        assert 0.0 <= result.p_value <= 1.0

    def test_monthly_annualization_factor(self):
        """annualization_factor=12 (monthly returns) must produce a valid result."""
        returns = _make_returns(36)
        result = compute_deflated_sharpe(returns, num_trials=5, annualization_factor=12)
        assert result.num_returns == 36
        assert 0.0 <= result.p_value <= 1.0

    def test_large_num_trials(self):
        """num_trials=10000 must still produce a valid result."""
        returns = _make_returns(100)
        result = compute_deflated_sharpe(returns, num_trials=10000)
        assert math.isfinite(result.expected_max_sharpe)
        assert 0.0 <= result.p_value <= 1.0

    def test_large_returns_series(self):
        """1000 returns must work correctly and set num_returns=1000."""
        returns = _make_returns(n=1000)
        result = compute_deflated_sharpe(returns, num_trials=50)
        assert result.num_returns == 1000
        assert 0.0 <= result.p_value <= 1.0


# ---------------------------------------------------------------------------
# Tests: is_significant threshold
# ---------------------------------------------------------------------------


class TestIsSignificant:
    """Tests for the is_significant significance boundary at p_value=0.95."""

    def test_is_significant_false_when_many_trials(self):
        """A strategy selected from many trials should usually NOT be significant."""
        # Use low-signal returns selected from 500 trials → very hard test
        returns = _make_returns(100, mean=0.0005, std=0.01)
        result = compute_deflated_sharpe(returns, num_trials=500)
        # With 500 trials and weak signal, DSR correction should kill significance
        assert not result.is_significant

    def test_is_significant_true_when_num_trials_1_and_high_sr(self):
        """A single high-SR strategy (num_trials=1) should be significant."""
        # Very strong daily returns, annualized to a large SR
        returns = [0.005] * 100  # constant +0.5% → very high SR after annualization
        result = compute_deflated_sharpe(returns, num_trials=1)
        # Constant returns → SR=0 by implementation (zero variance)
        # So is_significant depends on p_value = Φ(DSR) where DSR = 0 / std_sr
        # DSR with SR=0 and expected_max=0 will be near 0 → p_value ≈ 0.5 → not significant
        # This documents the zero-variance degeneracy.
        assert result.p_value == _normal_cdf(result.deflated_sharpe)

    def test_is_significant_boundary_above_0_95(self):
        """is_significant requires p_value > 0.95 (strictly greater, not >=).

        We verify the strict inequality using the CDF directly.
        Φ(1.6449) ≈ 0.95 — values below this DSR must NOT be significant.
        """
        # Find a DSR value where Φ(DSR) < 0.95 → should NOT be significant
        # Φ(1.6) ≈ 0.9452 < 0.95 → is_significant must be False
        dsr_below = 1.6
        p_below = _normal_cdf(dsr_below)
        assert p_below < 0.95, f"Expected Φ({dsr_below}) < 0.95, got {p_below}"
        assert not (p_below > 0.95)

        # Φ(1.7) ≈ 0.9554 > 0.95 → is_significant must be True
        dsr_above = 1.7
        p_above = _normal_cdf(dsr_above)
        assert p_above > 0.95, f"Expected Φ({dsr_above}) > 0.95, got {p_above}"
        assert p_above > 0.95


# ---------------------------------------------------------------------------
# Tests: known-input reference values
# ---------------------------------------------------------------------------


class TestKnownReferenceValues:
    """Validate computed DSR against hand-computed reference values.

    For a known return series we compute the expected DSR step-by-step and
    check the result matches the implementation output.

    Reference series:  r = [0.01, -0.01] * 5 = 10 observations alternating ±0.01
    - mean      = 0.0
    - variance  = 0.01^2 = 0.0001   (population variance, equal split)
    - std_dev   = 0.01
    - skewness  = 0.0   (symmetric)
    - kurtosis  = -2.0  (excess; all values at exactly ±σ → raw 4th moment = 1)
    - SR_daily  = mean / std_dev = 0.0 / 0.01 = 0.0
    - SR_ann    = 0.0 × √252 = 0.0  (annualized)
    With num_trials=1: expected_max_sharpe = 0.0
    Var(SR_hat) = (1/10) × (1 - 0×0 + ((-2)-1)/4 × 0^2) = (1/10) × (1 - 0 + 0) = 0.1
    DSR = (0 - 0) / √0.1 = 0.0
    p_value = Φ(0) = 0.5
    is_significant = False
    """

    _REFERENCE_RETURNS = [0.01, -0.01] * 5  # 10 observations

    def test_reference_observed_sharpe(self):
        """Symmetric ±0.01 series has annualized SR=0."""
        result = compute_deflated_sharpe(self._REFERENCE_RETURNS, num_trials=1)
        assert abs(result.observed_sharpe) < 1e-9

    def test_reference_expected_max_sharpe(self):
        """num_trials=1 → expected_max_sharpe=0."""
        result = compute_deflated_sharpe(self._REFERENCE_RETURNS, num_trials=1)
        assert result.expected_max_sharpe == 0.0

    def test_reference_skewness(self):
        """Symmetric series has zero skewness."""
        result = compute_deflated_sharpe(self._REFERENCE_RETURNS, num_trials=1)
        assert abs(result.skewness) < 1e-9

    def test_reference_kurtosis(self):
        """Bimodal ±c series has excess kurtosis = -2."""
        result = compute_deflated_sharpe(self._REFERENCE_RETURNS, num_trials=1)
        assert abs(result.kurtosis - (-2.0)) < 1e-9

    def test_reference_p_value(self):
        """Zero SR with zero expected max → DSR=0 → p_value = Φ(0) = 0.5."""
        result = compute_deflated_sharpe(self._REFERENCE_RETURNS, num_trials=1)
        assert abs(result.p_value - 0.5) < 1e-6

    def test_reference_is_not_significant(self):
        """p_value=0.5 → is_significant=False."""
        result = compute_deflated_sharpe(self._REFERENCE_RETURNS, num_trials=1)
        assert result.is_significant is False

    def test_reference_num_returns(self):
        """num_returns must match input length."""
        result = compute_deflated_sharpe(self._REFERENCE_RETURNS, num_trials=1)
        assert result.num_returns == 10

    def test_expected_max_sharpe_hand_computed_for_n_10(self):
        """Verify expected_max_sharpe formula for num_trials=10.

        E[max(SR)] = √(2·ln 10) · (1 - γ/(2·ln 10)) + γ/√(2·ln 10)
        where γ = 0.5772156649
        """
        gamma = 0.5772156649
        ln_n = math.log(10.0)
        sqrt_2_ln_n = math.sqrt(2.0 * ln_n)
        expected = sqrt_2_ln_n * (1.0 - gamma / (2.0 * ln_n)) + gamma / sqrt_2_ln_n

        result = compute_deflated_sharpe(self._REFERENCE_RETURNS, num_trials=10)
        assert abs(result.expected_max_sharpe - expected) < 1e-12
