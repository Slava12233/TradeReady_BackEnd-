"""Pydantic v2 request/response schemas for strategy test endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Base ─────────────────────────────────────────────────────────────────────


class _BaseSchema(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ── Requests ─────────────────────────────────────────────────────────────────


class DateRange(_BaseSchema):
    """Date range for test episodes."""

    start: datetime = Field(..., description="Start of historical data range")
    end: datetime = Field(..., description="End of historical data range")


class StartTestRequest(_BaseSchema):
    """Request to start a strategy test run."""

    version: int = Field(..., ge=1, description="Strategy version to test")
    episodes: int = Field(default=10, ge=1, le=100, description="Number of test episodes")
    date_range: DateRange = Field(..., description="Historical data range")
    randomize_dates: bool = Field(default=True, description="Randomize episode start dates")
    episode_duration_days: int = Field(default=30, ge=1, le=365, description="Duration of each episode in days")
    starting_balance: str = Field(default="10000", description="Starting balance per episode")


class CompareVersionsParams(_BaseSchema):
    """Query parameters for version comparison."""

    v1: int = Field(..., ge=1, description="First version to compare")
    v2: int = Field(..., ge=1, description="Second version to compare")


# ── Responses ────────────────────────────────────────────────────────────────


class TestRunResponse(_BaseSchema):
    """Response for a test run status."""

    test_run_id: str = Field(..., description="Test run UUID")
    status: str = Field(..., description="Test run status")
    episodes_total: int = Field(..., description="Total episodes")
    episodes_completed: int = Field(..., description="Completed episodes")
    progress_pct: float = Field(..., description="Progress percentage")
    version: int = Field(default=1, description="Strategy version being tested")
    created_at: datetime | None = Field(default=None, description="Creation timestamp")
    started_at: datetime | None = Field(default=None, description="Start timestamp")
    completed_at: datetime | None = Field(default=None, description="Completion timestamp")


class TestResultsResponse(TestRunResponse):
    """Response with full test results and recommendations."""

    results: dict[str, Any] | None = Field(default=None, description="Aggregated results")
    recommendations: list[str] | None = Field(default=None, description="Improvement recommendations")
    config: dict[str, Any] | None = Field(default=None, description="Test configuration")


class VersionMetrics(_BaseSchema):
    """Metrics for a single strategy version."""

    version: int = Field(..., description="Version number")
    avg_roi_pct: float | None = Field(default=None)
    avg_sharpe: float | None = Field(default=None)
    avg_max_drawdown_pct: float | None = Field(default=None)
    total_trades: int = Field(default=0)
    episodes_completed: int = Field(default=0)


class VersionComparisonResponse(_BaseSchema):
    """Response comparing two strategy versions."""

    v1: VersionMetrics = Field(..., description="First version metrics")
    v2: VersionMetrics = Field(..., description="Second version metrics")
    improvements: dict[str, float] = Field(
        default_factory=dict,
        description="Percentage improvements (positive = v2 better)",
    )
    verdict: str = Field(..., description="Summary verdict")
