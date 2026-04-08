"""Pydantic v2 request/response schemas for backtesting endpoints.

All ``Decimal`` fields serialise as strings to preserve full precision.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import re
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

# ── Base ─────────────────────────────────────────────────────────────────────


class _BaseSchema(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ── Requests ─────────────────────────────────────────────────────────────────


_VALID_INTERVALS = {60, 300, 3600, 86400}
_PAIR_PATTERN = re.compile(r"^[A-Z]{2,10}USDT$")


class BacktestCreateRequest(_BaseSchema):
    """Request to create a new backtest session."""

    start_time: datetime
    end_time: datetime
    starting_balance: Decimal = Field(ge=Decimal("1"), le=Decimal("10000000"))
    candle_interval: int = Field(default=60, ge=60)
    pairs: list[str] | None = None
    strategy_label: str = Field(default="default", max_length=100)
    agent_id: str | None = Field(
        default=None,
        description="Agent ID. If omitted, uses the agent from the authenticated API key.",
    )
    exchange: str = Field(
        default="binance",
        max_length=20,
        pattern=r"^[a-z][a-z0-9_]{0,19}$",
        description="Exchange to use for historical data (e.g. binance, okx, bybit).",
        examples=["binance", "okx", "bybit"],
    )
    fee_rate: Decimal | None = Field(
        default=None,
        ge=Decimal("0"),
        le=Decimal("0.1"),
        description=(
            "Trading fee rate as a fraction (e.g. 0.001 = 0.1%). "
            "Defaults to 0.001 when omitted."
        ),
        examples=[None, 0.001, 0.0005],
    )

    @model_validator(mode="after")
    def validate_date_range(self) -> Self:
        """end_time must be after start_time."""
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self

    @field_validator("candle_interval")
    @classmethod
    def validate_interval(cls, v: int) -> int:
        if v not in _VALID_INTERVALS:
            raise ValueError(f"candle_interval must be one of {sorted(_VALID_INTERVALS)}")
        return v

    @field_validator("pairs")
    @classmethod
    def validate_pairs(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        invalid = [p for p in v if not _PAIR_PATTERN.match(p)]
        if invalid:
            raise ValueError(f"Invalid trading pairs: {invalid}. Must match [A-Z]{{2,10}}USDT")
        return v

    @field_serializer("starting_balance")
    def _ser_balance(self, v: Decimal) -> str:
        return str(v)

    @field_serializer("fee_rate")
    def _ser_fee_rate(self, v: Decimal | None) -> str | None:  # noqa: PLR6301
        return str(v) if v is not None else None


class BacktestStepBatchRequest(_BaseSchema):
    """Request to advance N steps."""

    steps: int = Field(ge=1, le=10000)


class BacktestStepBatchFastRequest(_BaseSchema):
    """Request to advance N steps using the optimized fast-batch path.

    The fast-batch path defers per-step overhead (snapshots, portfolio
    computation, DB progress writes) to the end of the batch, making it
    suitable for RL training loops that issue thousands of sequential calls.
    """

    steps: int = Field(
        ge=1,
        le=100000,
        description="Number of candle steps to advance in this batch.",
        examples=[500, 1000],
    )
    include_intermediate_trades: bool = Field(
        default=False,
        description=(
            "When true, all order fills from every step in the batch are "
            "included in orders_filled. When false (default), only fills from "
            "the final step are returned, reducing response payload size."
        ),
        examples=[False],
    )


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
    agent_id: str | None = None


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


class BatchStepFastResponse(_BaseSchema):
    """Response from the optimized fast-batch step endpoint.

    Mirrors :class:`StepResponse` but adds ``steps_executed`` so the caller
    knows how many candles were actually advanced (may be less than requested
    if the simulation reached its end during the batch).
    """

    virtual_time: datetime
    step: int
    total_steps: int
    progress_pct: str
    prices: dict[str, str]
    orders_filled: list[dict[str, Any]]
    portfolio: dict[str, Any]
    is_complete: bool
    remaining_steps: int
    steps_executed: int


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
    agent_id: str | None = None
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
