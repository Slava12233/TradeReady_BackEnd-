"""Pydantic v2 request/response schemas for analytics endpoints.

Covers the following REST endpoints (Section 15.5):
- ``GET  /api/v1/analytics/performance``
- ``GET  /api/v1/analytics/portfolio/history``
- ``GET  /api/v1/analytics/leaderboard``

All ``Decimal`` price/ratio/PnL fields serialise as strings to preserve full
8-decimal precision without floating-point rounding.

Example::

    from src.api.schemas.analytics import (
        PerformanceResponse,
        PortfolioHistoryResponse,
        SnapshotItem,
        LeaderboardResponse,
        LeaderboardEntry,
    )

    perf = PerformanceResponse(
        period="30d",
        sharpe_ratio=Decimal("1.85"),
        sortino_ratio=Decimal("2.31"),
        max_drawdown_pct=Decimal("8.5"),
        max_drawdown_duration_days=3,
        win_rate=Decimal("65.71"),
        profit_factor=Decimal("2.10"),
        avg_win=Decimal("156.30"),
        avg_loss=Decimal("-74.50"),
        total_trades=35,
        avg_trades_per_day=Decimal("1.17"),
        best_trade=Decimal("523.00"),
        worst_trade=Decimal("-210.00"),
        current_streak=3,
    )
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


# ---------------------------------------------------------------------------
# Shared config base
# ---------------------------------------------------------------------------


class _BaseSchema(BaseModel):
    """Base schema with shared Pydantic v2 configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# Shared type aliases
# ---------------------------------------------------------------------------

AnalyticsPeriod = Literal["1d", "7d", "30d", "90d", "all"]
SnapshotInterval = Literal["1m", "1h", "1d"]


# ---------------------------------------------------------------------------
# Performance — GET /analytics/performance
# ---------------------------------------------------------------------------


class PerformanceResponse(_BaseSchema):
    """Response body for ``GET /api/v1/analytics/performance`` (HTTP 200).

    Contains all statistical performance metrics computed by
    ``PerformanceMetrics.calculate()`` for the requested period.

    Attributes:
        period:                    Time window used for the calculation.
        sharpe_ratio:              Annualised Sharpe ratio (risk-adjusted return).
        sortino_ratio:             Annualised Sortino ratio (downside-risk adjusted).
        max_drawdown_pct:          Maximum peak-to-trough equity decline as a %.
        max_drawdown_duration_days: Number of snapshots spanning the max drawdown.
        win_rate:                  Percentage of closed trades that were profitable.
        profit_factor:             Gross profit divided by gross loss (> 1 is good).
        avg_win:                   Average profit per winning trade in USDT.
        avg_loss:                  Average loss per losing trade in USDT (negative).
        total_trades:              Total number of closed trades in the period.
        avg_trades_per_day:        Average closed trades per calendar day.
        best_trade:                Largest single winning trade in USDT.
        worst_trade:               Largest single losing trade in USDT (negative).
        current_streak:            Consecutive wins (positive) or losses (negative).
    """

    period: AnalyticsPeriod = Field(
        ...,
        description="Time window used for performance calculation.",
        examples=["30d"],
    )
    sharpe_ratio: Decimal = Field(
        ...,
        description="Annualised Sharpe ratio (risk-adjusted return over risk-free rate).",
        examples=["1.85"],
    )
    sortino_ratio: Decimal = Field(
        ...,
        description="Annualised Sortino ratio using downside standard deviation only.",
        examples=["2.31"],
    )
    max_drawdown_pct: Decimal = Field(
        ...,
        ge=Decimal("0"),
        description="Maximum peak-to-trough equity decline expressed as a percentage.",
        examples=["8.5"],
    )
    max_drawdown_duration_days: int = Field(
        ...,
        ge=0,
        description="Number of snapshot periods spanning the maximum drawdown.",
        examples=[3],
    )
    win_rate: Decimal = Field(
        ...,
        ge=Decimal("0"),
        le=Decimal("100"),
        description="Percentage of closed trades that produced a positive realised PnL.",
        examples=["65.71"],
    )
    profit_factor: Decimal = Field(
        ...,
        ge=Decimal("0"),
        description="Gross profit divided by gross loss (values > 1 indicate net profitability).",
        examples=["2.10"],
    )
    avg_win: Decimal = Field(
        ...,
        description="Average profit per winning trade in USDT.",
        examples=["156.30"],
    )
    avg_loss: Decimal = Field(
        ...,
        description="Average loss per losing trade in USDT (typically negative).",
        examples=["-74.50"],
    )
    total_trades: int = Field(
        ...,
        ge=0,
        description="Total number of closed (filled) trades in the period.",
        examples=[35],
    )
    avg_trades_per_day: Decimal = Field(
        ...,
        ge=Decimal("0"),
        description="Average number of closed trades per calendar day in the period.",
        examples=["1.17"],
    )
    best_trade: Decimal = Field(
        ...,
        description="Realised PnL of the single most profitable trade in USDT.",
        examples=["523.00"],
    )
    worst_trade: Decimal = Field(
        ...,
        description="Realised PnL of the single worst trade in USDT (typically negative).",
        examples=["-210.00"],
    )
    current_streak: int = Field(
        ...,
        description=(
            "Consecutive winning (positive) or losing (negative) trades "
            "ending with the most recent closed trade."
        ),
        examples=[3],
    )

    @field_serializer(
        "sharpe_ratio",
        "sortino_ratio",
        "max_drawdown_pct",
        "win_rate",
        "profit_factor",
        "avg_win",
        "avg_loss",
        "avg_trades_per_day",
        "best_trade",
        "worst_trade",
    )
    def _serialize_decimal(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


# ---------------------------------------------------------------------------
# Portfolio history — GET /analytics/portfolio/history
# ---------------------------------------------------------------------------


class SnapshotItem(_BaseSchema):
    """A single portfolio snapshot data point in ``PortfolioHistoryResponse``.

    Attributes:
        time:           UTC timestamp of this snapshot.
        total_equity:   Total portfolio value in USDT at this point in time.
        unrealized_pnl: Unrealised P&L from open positions at snapshot time.
        realized_pnl:   Cumulative realised P&L from closed trades at snapshot time.
    """

    time: datetime = Field(
        ...,
        description="UTC timestamp of this portfolio snapshot.",
        examples=["2026-02-23T14:00:00Z"],
    )
    total_equity: Decimal = Field(
        ...,
        description="Total portfolio value in USDT at this point in time.",
        examples=["12300.50"],
    )
    unrealized_pnl: Decimal = Field(
        ...,
        description="Unrealised P&L from open positions at snapshot time in USDT.",
        examples=["600.20"],
    )
    realized_pnl: Decimal = Field(
        ...,
        description="Cumulative realised P&L from closed trades at snapshot time in USDT.",
        examples=["1200.30"],
    )

    @field_serializer("total_equity", "unrealized_pnl", "realized_pnl")
    def _serialize_decimal(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class PortfolioHistoryResponse(_BaseSchema):
    """Response body for ``GET /api/v1/analytics/portfolio/history`` (HTTP 200).

    Returns a time-ordered list of portfolio equity snapshots suitable for
    charting, filtered by interval and optional time bounds.

    Attributes:
        account_id: UUID of the account the history belongs to.
        interval:   Snapshot resolution used for this response.
        snapshots:  Time-ordered list of equity data points (oldest first).
    """

    account_id: UUID = Field(
        ...,
        description="UUID of the account this history belongs to.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    interval: SnapshotInterval = Field(
        ...,
        description="Snapshot resolution / aggregation interval.",
        examples=["1h"],
    )
    snapshots: list[SnapshotItem] = Field(
        default_factory=list,
        description="Time-ordered portfolio equity data points (oldest first).",
    )


# ---------------------------------------------------------------------------
# Leaderboard — GET /analytics/leaderboard
# ---------------------------------------------------------------------------


class LeaderboardEntry(_BaseSchema):
    """A single agent entry in the cross-account performance leaderboard.

    Attributes:
        rank:         Position in the leaderboard (1 = best).
        account_id:   UUID of the ranked account.
        display_name: Human-readable name of the agent / bot.
        roi_pct:      Return on investment as a percentage vs starting balance.
        sharpe_ratio: Annualised Sharpe ratio for the leaderboard period.
        total_trades: Total closed trades in the period.
        win_rate:     Percentage of winning trades in the period.
    """

    rank: int = Field(
        ...,
        ge=1,
        description="Leaderboard position (1 = highest performer).",
        examples=[1],
    )
    account_id: UUID = Field(
        ...,
        description="UUID of the ranked account.",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    display_name: str = Field(
        ...,
        min_length=1,
        description="Human-readable name for the agent / bot.",
        examples=["AlphaBot"],
    )
    roi_pct: Decimal = Field(
        ...,
        description="Return on investment as a percentage vs session starting balance.",
        examples=["24.5"],
    )
    sharpe_ratio: Decimal = Field(
        ...,
        description="Annualised Sharpe ratio computed over the leaderboard period.",
        examples=["2.10"],
    )
    total_trades: int = Field(
        ...,
        ge=0,
        description="Total closed trades recorded within the leaderboard period.",
        examples=[156],
    )
    win_rate: Decimal = Field(
        ...,
        ge=Decimal("0"),
        le=Decimal("100"),
        description="Percentage of closed trades that were profitable.",
        examples=["68.2"],
    )

    @field_serializer("roi_pct", "sharpe_ratio", "win_rate")
    def _serialize_decimal(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class LeaderboardResponse(_BaseSchema):
    """Response body for ``GET /api/v1/analytics/leaderboard`` (HTTP 200).

    Cross-account performance rankings sorted by ROI for the requested period.
    Only active accounts with at least one closed trade in the period appear.

    Attributes:
        period:   Time window used to calculate rankings.
        rankings: Ordered list of leaderboard entries (rank 1 first).
    """

    period: AnalyticsPeriod = Field(
        ...,
        description="Time window used to calculate the leaderboard rankings.",
        examples=["30d"],
    )
    rankings: list[LeaderboardEntry] = Field(
        default_factory=list,
        description="Ordered leaderboard entries, rank 1 first.",
    )
