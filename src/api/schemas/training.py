"""Pydantic v2 request/response schemas for training endpoints."""

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


class RegisterRunRequest(_BaseSchema):
    """Request to register a new training run."""

    run_id: str = Field(..., description="Client-provided UUID for the training run")
    config: dict[str, Any] | None = Field(default=None, description="Training configuration")
    strategy_id: str | None = Field(default=None, description="Optional linked strategy UUID")


class ReportEpisodeRequest(_BaseSchema):
    """Request to report a completed training episode."""

    episode_number: int = Field(..., ge=1, description="Sequential episode number")
    session_id: str | None = Field(default=None, description="Optional backtest session UUID")
    roi_pct: float | None = Field(default=None, description="Episode ROI percentage")
    sharpe_ratio: float | None = Field(default=None, description="Episode Sharpe ratio")
    max_drawdown_pct: float | None = Field(default=None, description="Episode max drawdown %")
    total_trades: int | None = Field(default=None, description="Total trades in episode")
    reward_sum: float | None = Field(default=None, description="Total reward accumulated")


# ── Responses ────────────────────────────────────────────────────────────────


class TrainingRunResponse(_BaseSchema):
    """Summary response for a training run."""

    run_id: str = Field(..., description="Training run UUID")
    status: str = Field(..., description="Run status")
    config: dict[str, Any] | None = Field(default=None)
    episodes_total: int | None = Field(default=None)
    episodes_completed: int = Field(default=0)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)


class TrainingRunDetailResponse(TrainingRunResponse):
    """Detailed response with learning curve and episodes."""

    learning_curve: dict[str, Any] | None = Field(default=None)
    aggregate_stats: dict[str, Any] | None = Field(default=None)
    episodes: list[dict[str, Any]] = Field(default_factory=list)


class LearningCurveResponse(_BaseSchema):
    """Learning curve data for charting."""

    episode_numbers: list[int] = Field(default_factory=list)
    raw_values: list[float] = Field(default_factory=list)
    smoothed_values: list[float] = Field(default_factory=list)
    metric: str = Field(default="roi_pct")
    window: int = Field(default=10)


class RunMetrics(_BaseSchema):
    """Metrics for a single training run in comparison."""

    run_id: str
    status: str
    episodes_completed: int = 0
    aggregate_stats: dict[str, Any] | None = None
    started_at: str | None = None
    completed_at: str | None = None


class TrainingComparisonResponse(_BaseSchema):
    """Response comparing multiple training runs."""

    runs: list[RunMetrics] = Field(default_factory=list)
