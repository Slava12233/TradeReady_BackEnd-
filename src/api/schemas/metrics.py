"""Pydantic v2 request/response schemas for metrics endpoints.

Covers the following REST endpoints:
- ``POST /api/v1/metrics/deflated-sharpe`` — Deflated Sharpe Ratio (DSR)

Reference:
    Bailey, D. H., & Lopez de Prado, M. (2014).
    "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest
    Overfitting, and Non-Normality."
    Journal of Portfolio Management, 40(5), 94–107.

Example::

    from src.api.schemas.metrics import DeflatedSharpeRequest, DeflatedSharpeResponse

    req = DeflatedSharpeRequest(
        returns=[0.001, -0.002, 0.003] * 5,  # 15 observations
        num_trials=50,
        annualization_factor=252,
    )
    # response mirrors DeflatedSharpeResult fields
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared config base  (duplicated per file — project convention)
# ---------------------------------------------------------------------------


class _BaseSchema(BaseModel):
    """Base schema with shared Pydantic v2 configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# Deflated Sharpe Ratio — POST /api/v1/metrics/deflated-sharpe
# ---------------------------------------------------------------------------


class DeflatedSharpeRequest(_BaseSchema):
    """Request body for ``POST /api/v1/metrics/deflated-sharpe``.

    Attributes:
        returns:              Per-period return observations (not percentages).
                              Must contain at least 10 values.
        num_trials:           Number of strategy variants tested before selecting
                              this one.  Drives the multiple-testing correction.
        annualization_factor: Periods per year for annualising the Sharpe Ratio.
                              252 for daily, 52 for weekly, 12 for monthly.
    """

    returns: list[float] = Field(
        ...,
        min_length=10,
        description=(
            "Per-period return observations (e.g. daily returns as decimals, not "
            "percentages).  Requires at least 10 observations."
        ),
        examples=[[0.001, -0.002, 0.003, 0.001, -0.001, 0.002, 0.0, -0.003, 0.004, 0.001]],
    )
    num_trials: int = Field(
        ...,
        ge=1,
        description=(
            "Number of strategy variants tested before selecting this one.  "
            "The higher the value, the harder the significance test becomes "
            "due to multiple-testing correction."
        ),
        examples=[100],
    )
    annualization_factor: int = Field(
        default=252,
        ge=1,
        description=(
            "Number of return periods per year.  "
            "Use 252 for daily, 52 for weekly, 12 for monthly returns."
        ),
        examples=[252],
    )


class DeflatedSharpeResponse(_BaseSchema):
    """Response body for ``POST /api/v1/metrics/deflated-sharpe`` (HTTP 200).

    All ratio fields are ``float`` because DSR is a statistical metric —
    it does not represent monetary value and does not require ``Decimal``
    serialisation.

    Attributes:
        observed_sharpe:      Annualised Sharpe Ratio of the supplied return series.
        expected_max_sharpe:  Expected maximum Sharpe across ``num_trials`` independent
                              trials under the null hypothesis (no skill).
        deflated_sharpe:      DSR statistic: (SR_obs − E[max SR]) / √Var(SR_hat).
        p_value:              Φ(DSR) — probability the strategy is NOT due to chance.
        is_significant:       ``True`` when ``p_value > 0.95`` (95% confidence).
        num_trials:           Number of strategy variants used for the correction.
        num_returns:          Number of return observations supplied.
        skewness:             Third standardised moment of the return series.
        kurtosis:             Fourth standardised moment (excess kurtosis).
    """

    observed_sharpe: float = Field(
        ...,
        description="Annualised Sharpe Ratio of the supplied return series (risk-free rate = 0).",
        examples=[1.42],
    )
    expected_max_sharpe: float = Field(
        ...,
        description=(
            "Expected maximum Sharpe Ratio across num_trials independent strategies "
            "under the null hypothesis.  This is the hurdle the observed SR must clear."
        ),
        examples=[2.51],
    )
    deflated_sharpe: float = Field(
        ...,
        description=(
            "DSR statistic: (SR_observed − E[max SR]) / √Var(SR_hat).  "
            "Positive values indicate the observed SR exceeds the expected maximum."
        ),
        examples=[-1.08],
    )
    p_value: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Φ(DSR) — standard normal CDF applied to the DSR statistic.  "
            "Represents the probability that the strategy is NOT due to random chance.  "
            "Values > 0.95 are conventionally considered significant."
        ),
        examples=[0.14],
    )
    is_significant: bool = Field(
        ...,
        description=(
            "True when p_value > 0.95 (95% confidence that the strategy is not "
            "a product of selection bias or overfitting)."
        ),
        examples=[False],
    )
    num_trials: int = Field(
        ...,
        ge=1,
        description="Number of strategy variants used for the multiple-testing correction.",
        examples=[100],
    )
    num_returns: int = Field(
        ...,
        ge=10,
        description="Number of return observations supplied.",
        examples=[252],
    )
    skewness: float = Field(
        ...,
        description="Third standardised moment of the return series.",
        examples=[-0.23],
    )
    kurtosis: float = Field(
        ...,
        description="Fourth standardised moment of the return series (excess kurtosis, normal = 0).",
        examples=[1.04],
    )
