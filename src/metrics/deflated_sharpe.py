"""Deflated Sharpe Ratio implementation (Bailey & Lopez de Prado, 2014).

Computes the Deflated Sharpe Ratio (DSR), which corrects the observed Sharpe
Ratio for multiple-testing bias.  When a strategy researcher tests N variants,
the best-looking one is likely over-fitted.  DSR asks: *given that N strategies
were tried, is the best Sharpe still significant?*

Reference:
    Bailey, D. H., & Lopez de Prado, M. (2014).
    "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest
    Overfitting, and Non-Normality."
    Journal of Portfolio Management, 40(5), 94–107.

Usage::

    from src.metrics.deflated_sharpe import compute_deflated_sharpe

    result = compute_deflated_sharpe(
        returns=[0.001, -0.002, 0.003, ...],  # period returns (not %)
        num_trials=100,
        annualization_factor=252,
    )
    print(result.is_significant)   # True if DSR p-value > 0.95
    print(result.deflated_sharpe)  # The DSR statistic
"""

from __future__ import annotations

from dataclasses import dataclass
import math

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Euler-Mascheroni constant (γ), accurate to 10 decimal places.
_GAMMA_EULER: float = 0.5772156649

#: Minimum number of return observations required for a valid calculation.
MIN_RETURNS: int = 10


# ---------------------------------------------------------------------------
# Pure-Python normal CDF  (Abramowitz & Stegun, §26.2.17)
# ---------------------------------------------------------------------------


def _normal_cdf(x: float) -> float:
    """Compute the standard normal CDF Φ(x) via Abramowitz & Stegun rational approximation.

    Implements the A&S formula 26.2.17 which gives a maximum absolute error
    of 7.5 × 10⁻⁸.  No external libraries (scipy, numpy) are required.

    Args:
        x: The point at which to evaluate Φ(x).

    Returns:
        Probability P(Z ≤ x) where Z ~ N(0, 1), in the range [0, 1].

    Example::

        >>> abs(_normal_cdf(0.0) - 0.5) < 1e-7
        True
        >>> abs(_normal_cdf(1.96) - 0.975) < 1e-4
        True
    """
    # Coefficients for the A&S rational approximation
    p = 0.2316419
    b1 = 0.319381530
    b2 = -0.356563782
    b3 = 1.781477937
    b4 = -1.821255978
    b5 = 1.330274429

    sign = 1.0 if x >= 0.0 else -1.0
    x_abs = abs(x)

    # Standard normal PDF at x_abs
    pdf = math.exp(-0.5 * x_abs * x_abs) / math.sqrt(2.0 * math.pi)

    t = 1.0 / (1.0 + p * x_abs)
    poly = t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))

    cdf_pos = 1.0 - pdf * poly

    if sign >= 0:
        return cdf_pos
    return 1.0 - cdf_pos


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeflatedSharpeResult:
    """Full result of a Deflated Sharpe Ratio computation.

    All ratio fields are plain ``float`` values because DSR is a statistical
    computation — the monetary/decimal precision rules do not apply here.

    Attributes:
        observed_sharpe:      Annualised Sharpe Ratio of the observed return series.
        expected_max_sharpe:  Expected maximum Sharpe across ``num_trials`` independent
                              trials under the null (no skill).
        deflated_sharpe:      DSR statistic: (SR_obs − E[max SR]) / √Var(SR_hat).
        p_value:              Φ(DSR) — probability the strategy is NOT due to luck.
        is_significant:       ``True`` when ``p_value > 0.95`` (95% confidence).
        num_trials:           Number of strategy variants tested (selection bias factor).
        num_returns:          Number of return observations supplied.
        skewness:             Third standardised moment of the return series.
        kurtosis:             Fourth standardised moment of the return series (excess).
    """

    observed_sharpe: float
    expected_max_sharpe: float
    deflated_sharpe: float
    p_value: float
    is_significant: bool
    num_trials: int
    num_returns: int
    skewness: float
    kurtosis: float


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_deflated_sharpe(
    returns: list[float],
    num_trials: int,
    annualization_factor: int = 252,
) -> DeflatedSharpeResult:
    """Compute the Deflated Sharpe Ratio for a strategy's return series.

    Implements the Bailey & Lopez de Prado (2014) formula in four steps:

    1. Compute the annualised Sharpe Ratio (SR) of the observed returns.
    2. Estimate the expected maximum SR across ``num_trials`` independent
       strategies under the null hypothesis of zero skill::

           E[max(SR)] ≈ √(2·ln N) · (1 − γ/(2·ln N)) + γ/√(2·ln N)

       where N = ``num_trials`` and γ is the Euler-Mascheroni constant.

    3. Estimate the variance of the Sharpe estimator corrected for non-normality
       (skewness γ₃ and excess kurtosis κ)::

           Var(SR_hat) = (1/T) · (1 − γ₃·SR + ((κ−1)/4)·SR²)

       where T = ``num_returns``.  If this is non-positive the variance is
       floored at a small epsilon to avoid division by zero.

    4. Compute DSR = (SR_obs − E[max SR]) / √Var(SR_hat) and p-value = Φ(DSR).

    Args:
        returns:              List of per-period returns (not percentages).  Requires
                              at least :data:`MIN_RETURNS` (10) observations.
        num_trials:           Number of strategy variants tested before selecting this
                              one.  Must be ≥ 1.  The higher this is, the harder the
                              significance test becomes.
        annualization_factor: Number of return periods per year.  Use 252 for daily
                              returns, 52 for weekly, 12 for monthly.  Defaults to 252.

    Returns:
        A :class:`DeflatedSharpeResult` dataclass with all intermediate values.

    Raises:
        ValueError: If ``len(returns) < 10`` or ``num_trials < 1``.

    Example::

        >>> import random; random.seed(42)
        >>> r = [random.gauss(0.001, 0.01) for _ in range(252)]
        >>> result = compute_deflated_sharpe(r, num_trials=1)
        >>> 0.0 <= result.p_value <= 1.0
        True
    """
    t = len(returns)
    if t < MIN_RETURNS:
        raise ValueError(
            f"At least {MIN_RETURNS} return observations are required; got {t}."
        )
    if num_trials < 1:
        raise ValueError(f"num_trials must be >= 1; got {num_trials}.")

    # ------------------------------------------------------------------
    # Step 1: Descriptive statistics of the return series
    # ------------------------------------------------------------------
    mean = sum(returns) / t
    variance = sum((r - mean) ** 2 for r in returns) / t  # population variance

    if variance == 0.0:
        # Degenerate case: all returns identical → SR undefined, set to 0
        std_dev = 0.0
        skewness = 0.0
        kurtosis = 0.0
        observed_sharpe = 0.0
    else:
        std_dev = math.sqrt(variance)
        skewness = sum((r - mean) ** 3 for r in returns) / (t * std_dev**3)
        kurtosis = sum((r - mean) ** 4 for r in returns) / (t * std_dev**4) - 3.0

        # Annualised Sharpe Ratio (assuming risk-free rate = 0)
        sr_periodic = mean / std_dev
        observed_sharpe = sr_periodic * math.sqrt(float(annualization_factor))

    # ------------------------------------------------------------------
    # Step 2: Expected maximum Sharpe Ratio across num_trials tests
    # ------------------------------------------------------------------
    # Formula (Bailey & Lopez de Prado 2014, eq. 3):
    #   E[max(SR)] ≈ √(2·ln N) · (1 − γ/(2·ln N)) + γ/√(2·ln N)
    #
    # When N = 1, ln(1) = 0, so we fall back to E[max SR] = 0 (no selection bias).
    if num_trials == 1:
        expected_max_sharpe = 0.0
    else:
        ln_n = math.log(float(num_trials))
        sqrt_2_ln_n = math.sqrt(2.0 * ln_n)
        expected_max_sharpe = (
            sqrt_2_ln_n * (1.0 - _GAMMA_EULER / (2.0 * ln_n))
            + _GAMMA_EULER / sqrt_2_ln_n
        )

    # ------------------------------------------------------------------
    # Step 3: Variance of the Sharpe estimator (non-normality correction)
    # ------------------------------------------------------------------
    # Formula (Bailey & Lopez de Prado 2014, eq. 8):
    #   Var(SR_hat) = (1/T) · (1 − γ₃·SR + ((κ−1)/4)·SR²)
    #
    # Note: γ₃ = skewness, κ = excess kurtosis (already subtracted 3 above).
    # The term ((κ−1)/4)·SR² uses excess kurtosis directly.
    sr_for_var = observed_sharpe  # use annualised SR consistently
    var_sr = (1.0 / t) * (
        1.0
        - skewness * sr_for_var
        + ((kurtosis - 1.0) / 4.0) * sr_for_var**2
    )

    # Floor variance at a tiny epsilon to avoid sqrt of negative or zero
    var_floor = 1e-12
    if var_sr <= 0.0:
        var_sr = var_floor

    std_sr = math.sqrt(var_sr)

    # ------------------------------------------------------------------
    # Step 4: DSR statistic and p-value
    # ------------------------------------------------------------------
    deflated_sharpe = (observed_sharpe - expected_max_sharpe) / std_sr
    p_value = _normal_cdf(deflated_sharpe)
    is_significant = p_value > 0.95  # noqa: PLR2004

    return DeflatedSharpeResult(
        observed_sharpe=observed_sharpe,
        expected_max_sharpe=expected_max_sharpe,
        deflated_sharpe=deflated_sharpe,
        p_value=p_value,
        is_significant=is_significant,
        num_trials=num_trials,
        num_returns=t,
        skewness=skewness,
        kurtosis=kurtosis,
    )
