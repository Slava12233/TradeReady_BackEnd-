"""Pydantic v2 request/response schemas for strategy endpoints.

All ``Decimal`` fields serialise as strings to preserve full precision.
"""

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


class CreateStrategyRequest(_BaseSchema):
    """Request to create a new strategy."""

    name: str = Field(..., min_length=1, max_length=200, description="Strategy name", examples=["BTC RSI Scalper"])
    description: str | None = Field(default=None, max_length=2000, description="Strategy description")
    definition: dict[str, Any] = Field(
        ...,
        description="Strategy definition JSON (pairs, timeframe, conditions, position sizing)",
        examples=[{
            "pairs": ["BTCUSDT"],
            "timeframe": "1h",
            "entry_conditions": {"rsi_below": 30},
            "exit_conditions": {"take_profit_pct": 5, "stop_loss_pct": 2},
            "position_size_pct": 10,
            "max_positions": 3,
        }],
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
