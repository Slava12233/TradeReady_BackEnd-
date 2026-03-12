"""Pydantic v2 request/response schemas for backtesting endpoints.

All ``Decimal`` fields serialise as strings to preserve full precision.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

# ── Base ─────────────────────────────────────────────────────────────────────


class _BaseSchema(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ── Requests ─────────────────────────────────────────────────────────────────


class BacktestCreateRequest(_BaseSchema):
    """Request to create a new backtest session."""

    start_time: datetime
    end_time: datetime
    starting_balance: Decimal = Field(ge=Decimal("1"))
    candle_interval: int = Field(default=60, ge=60)
    pairs: list[str] | None = None
    strategy_label: str = Field(default="default", max_length=100)

    @field_serializer("starting_balance")
    def _ser_balance(self, v: Decimal) -> str:
        return str(v)


class BacktestStepBatchRequest(_BaseSchema):
    """Request to advance N steps."""

    steps: int = Field(ge=1, le=10000)


class BacktestOrderRequest(_BaseSchema):
    """Request to place an order inside a backtest sandbox."""

    symbol: str = Field(max_length=20)
    side: Literal["buy", "sell"]
    type: Literal["market", "limit", "stop_loss", "take_profit"] = "market"
    quantity: Decimal = Field(gt=Decimal("0"))
    price: Decimal | None = None

    @field_serializer("quantity", "price")
    def _ser_decimal(self, v: Decimal | None) -> str | None:
        return str(v) if v is not None else None


class ModeSwitchRequest(_BaseSchema):
    """Request to switch account mode."""

    mode: Literal["live", "backtest"]
    strategy_label: str | None = None


# ── Responses ────────────────────────────────────────────────────────────────


class BacktestCreateResponse(_BaseSchema):
    """Response after creating a backtest session."""

    session_id: str
    status: str
    total_steps: int
    estimated_pairs: int


class StepResponse(_BaseSchema):
    """Response after advancing one or more steps."""

    virtual_time: datetime
    step: int
    total_steps: int
    progress_pct: str
    prices: dict[str, str]
    orders_filled: list[dict[str, Any]]
    portfolio: dict[str, Any]
    is_complete: bool
    remaining_steps: int


class BacktestResultsResponse(_BaseSchema):
    """Full results of a completed backtest."""

    session_id: str
    status: str
    config: dict[str, Any]
    summary: dict[str, Any]
    metrics: dict[str, Any] | None
    by_pair: list[dict[str, Any]]


class EquityCurveResponse(_BaseSchema):
    """Equity curve data points."""

    interval: int
    snapshots: list[dict[str, str]]


class BacktestListResponse(_BaseSchema):
    """List of backtest sessions."""

    backtests: list[BacktestListItem]
    total: int = 0


class BacktestListItem(_BaseSchema):
    """Summary of a single backtest session."""

    session_id: str
    strategy_label: str
    start_time: datetime
    end_time: datetime
    status: str
    candle_interval: int | None = None
    starting_balance: str | None = None
    pairs: list[str] | None = None
    progress_pct: float = 0.0
    current_step: int = 0
    total_steps: int = 0
    virtual_clock: datetime | None = None
    final_equity: str | None = None
    total_pnl: str | None = None
    roi_pct: str | None = None
    total_trades: int = 0
    total_fees: str | None = None
    sharpe_ratio: str | None = None
    max_drawdown_pct: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_real_sec: float | None = None


class BacktestCompareResponse(_BaseSchema):
    """Side-by-side comparison of multiple backtests."""

    comparisons: list[dict[str, Any]]
    best_by_roi: str | None
    best_by_sharpe: str | None
    best_by_drawdown: str | None
    recommendation: str | None


class BacktestBestResponse(_BaseSchema):
    """Best backtest session by a given metric."""

    session_id: str
    strategy_label: str
    metric: str
    value: str


class AccountModeResponse(_BaseSchema):
    """Current account operating mode."""

    mode: str
    active_strategy_label: str | None
    active_backtests: int
    total_backtests_completed: int


class DataRangeResponse(_BaseSchema):
    """Available historical data range."""

    earliest: datetime
    latest: datetime
    total_pairs: int
    intervals_available: list[str]
    data_gaps: list[dict[str, Any]]
