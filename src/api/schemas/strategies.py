"""Pydantic v2 request/response schemas for strategy endpoints.

All ``Decimal`` fields serialise as strings to preserve full precision.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Base ─────────────────────────────────────────────────────────────────────


class _BaseSchema(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ── Requests ─────────────────────────────────────────────────────────────────


class CreateStrategyRequest(_BaseSchema):
    """Request to create a new strategy."""

    name: str = Field(..., min_length=1, max_length=200, description="Strategy name", examples=["BTC RSI Scalper"])
    description: str | None = Field(default=None, max_length=2000, description="Strategy description")
    definition: dict[str, Any] = Field(
        ...,
        description="Strategy definition JSON (pairs, timeframe, conditions, position sizing)",
        examples=[
            {
                "pairs": ["BTCUSDT"],
                "timeframe": "1h",
                "entry_conditions": {"rsi_below": 30},
                "exit_conditions": {"take_profit_pct": 5, "stop_loss_pct": 2},
                "position_size_pct": 10,
                "max_positions": 3,
            }
        ],
    )


class UpdateStrategyRequest(_BaseSchema):
    """Request to update strategy metadata."""

    name: str | None = Field(default=None, min_length=1, max_length=200, description="New strategy name")
    description: str | None = Field(default=None, max_length=2000, description="New description")


class CreateVersionRequest(_BaseSchema):
    """Request to create a new strategy version."""

    definition: dict[str, Any] = Field(..., description="Updated strategy definition JSON")
    change_notes: str | None = Field(default=None, max_length=2000, description="Description of changes")


class DeployRequest(_BaseSchema):
    """Request to deploy a strategy version."""

    version: int = Field(..., ge=1, description="Version number to deploy")


# ── Responses ────────────────────────────────────────────────────────────────


class StrategyResponse(_BaseSchema):
    """Summary response for a strategy."""

    strategy_id: str = Field(..., description="Strategy UUID")
    name: str = Field(..., description="Strategy name")
    description: str | None = Field(default=None, description="Strategy description")
    current_version: int = Field(..., description="Current version number")
    status: str = Field(..., description="Strategy status")
    deployed_at: datetime | None = Field(default=None, description="When deployed to live")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")


class StrategyDetailResponse(StrategyResponse):
    """Detailed response including current definition and latest test results."""

    current_definition: dict[str, Any] | None = Field(default=None, description="Current version's definition")
    latest_test_results: dict[str, Any] | None = Field(default=None, description="Latest completed test results")


class StrategyVersionResponse(_BaseSchema):
    """Response for a strategy version."""

    version_id: str = Field(..., description="Version UUID")
    strategy_id: str = Field(..., description="Strategy UUID")
    version: int = Field(..., description="Version number")
    definition: dict[str, Any] = Field(..., description="Strategy definition")
    change_notes: str | None = Field(default=None, description="Change notes")
    parent_version: int | None = Field(default=None, description="Parent version number")
    status: str = Field(..., description="Version status")
    created_at: datetime = Field(..., description="Creation timestamp")


class StrategyListResponse(_BaseSchema):
    """Paginated list of strategies."""

    strategies: list[StrategyResponse] = Field(default_factory=list)
    total: int = Field(default=0, description="Total count")
    limit: int = Field(default=50)
    offset: int = Field(default=0)


# ── Strategy Comparison ───────────────────────────────────────────────────────

#: Valid ranking metric keys for strategy comparison.
_VALID_RANKING_METRICS = frozenset(
    {
        "sharpe_ratio",
        "max_drawdown_pct",
        "win_rate",
        "roi_pct",
        "sortino_ratio",
        "profit_factor",
    }
)


class StrategyComparisonRequest(_BaseSchema):
    """Request body for ``POST /api/v1/strategies/compare``.

    Attributes:
        strategy_ids:   List of 2–10 strategy UUIDs to compare.
        ranking_metric: Metric used to rank strategies.  Defaults to
                        ``"sharpe_ratio"``.  Larger is better for all
                        supported metrics except ``max_drawdown_pct``
                        (where smaller magnitude is better).
    """

    strategy_ids: list[UUID] = Field(
        ...,
        min_length=2,
        max_length=10,
        description="List of 2–10 strategy UUIDs to rank and compare",
        examples=[["550e8400-e29b-41d4-a716-446655440000", "550e8400-e29b-41d4-a716-446655440001"]],
    )
    ranking_metric: str = Field(
        default="sharpe_ratio",
        description=(
            "Metric used to determine the winner. "
            f"Allowed values: {sorted(_VALID_RANKING_METRICS)}. "
            "For max_drawdown_pct, smaller magnitude wins; for all others, larger wins."
        ),
        examples=["sharpe_ratio"],
    )

    @field_validator("ranking_metric", mode="before")
    @classmethod
    def _validate_metric(cls, v: str) -> str:
        """Ensure ranking_metric is one of the supported values."""
        if v not in _VALID_RANKING_METRICS:
            raise ValueError(
                f"ranking_metric must be one of {sorted(_VALID_RANKING_METRICS)}; got '{v}'"
            )
        return v


class StrategyComparisonMetrics(_BaseSchema):
    """Extracted performance metrics for a single strategy in the comparison.

    All values are taken from the latest completed test run.  Fields are
    ``None`` when the test run did not produce that metric.
    """

    sharpe_ratio: float | None = Field(default=None, description="Annualised Sharpe Ratio")
    sortino_ratio: float | None = Field(default=None, description="Annualised Sortino Ratio")
    max_drawdown_pct: float | None = Field(default=None, description="Maximum drawdown percentage")
    win_rate: float | None = Field(default=None, description="Fraction of winning trades (0–1)")
    roi_pct: float | None = Field(default=None, description="Return on investment percentage")
    profit_factor: float | None = Field(default=None, description="Gross profit / gross loss")
    total_trades: int | None = Field(default=None, description="Total number of trades executed")


class StrategyDeflatedSharpeInfo(_BaseSchema):
    """DSR data embedded in a strategy comparison entry.

    Present only when ``deflated_sharpe`` data exists in the test run JSONB.
    """

    p_value: float = Field(..., description="DSR p-value: probability the strategy is NOT due to luck")
    is_significant: bool = Field(..., description="True when p_value > 0.95 (95% confidence)")
    observed_sharpe: float = Field(..., description="Annualised Sharpe Ratio observed in the test")
    deflated_sharpe: float = Field(..., description="DSR statistic after selection-bias correction")
    num_trials: int = Field(..., description="Number of strategy variants tested")


class StrategyComparisonEntry(_BaseSchema):
    """Single strategy entry in the comparison result, with rank and metrics.

    Attributes:
        strategy_id:    Strategy UUID.
        name:           Strategy name.
        version:        Current version number.
        status:         Strategy lifecycle status.
        rank:           1-based rank by the chosen ``ranking_metric``.
        metrics:        Extracted performance metrics from the latest test run.
        deflated_sharpe: DSR data when available in the test run results.
        has_test_results: ``False`` when no completed test run exists for this
                          strategy; metrics will be empty / None in that case.
    """

    strategy_id: str = Field(..., description="Strategy UUID")
    name: str = Field(..., description="Strategy name")
    version: int = Field(..., description="Current version number")
    status: str = Field(..., description="Strategy status")
    rank: int = Field(..., ge=1, description="1-based rank by the chosen ranking_metric")
    metrics: StrategyComparisonMetrics = Field(..., description="Extracted performance metrics")
    deflated_sharpe: StrategyDeflatedSharpeInfo | None = Field(
        default=None,
        description="Deflated Sharpe Ratio data (omitted when unavailable)",
    )
    has_test_results: bool = Field(..., description="Whether a completed test run was found")


class StrategyComparisonResponse(_BaseSchema):
    """Response for ``POST /api/v1/strategies/compare``.

    Attributes:
        strategies:     Ranked list of strategy comparison entries.
        winner_id:      UUID of the strategy ranked first.  ``None`` when all
                        strategies lack test results.
        ranking_metric: The metric used to determine the ranking.
        recommendation: Human-readable one-liner summarising the winner and
                        whether it passes the Deflated Sharpe test.
    """

    strategies: list[StrategyComparisonEntry] = Field(
        ...,
        description="Strategies ranked by the chosen metric (index 0 = best)",
    )
    winner_id: str | None = Field(
        default=None,
        description="UUID of the top-ranked strategy; None when no strategy has test results",
    )
    ranking_metric: str = Field(..., description="Metric used for ranking")
    recommendation: str = Field(..., description="One-line recommendation text")
