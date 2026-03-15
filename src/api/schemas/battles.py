"""Pydantic v2 request/response schemas for battle endpoints.

Covers all battle management, participant, live, results, and replay endpoints.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class _BaseSchema(BaseModel):
    """Base schema with shared Pydantic v2 configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# Create / Update
# ---------------------------------------------------------------------------


class BattleCreate(_BaseSchema):
    """Request body for ``POST /api/v1/battles``."""

    name: str = Field(..., min_length=1, max_length=200, description="Battle name.")
    preset: str | None = Field(default=None, max_length=50, description="Preset key.")
    config: dict[str, object] | None = Field(
        default=None,
        description="Custom config overrides (duration, pairs, wallet_mode, starting_balance).",
    )
    ranking_metric: str = Field(
        default="roi_pct",
        description="Metric to rank participants: roi_pct, total_pnl, sharpe_ratio, win_rate, profit_factor.",
    )


class BattleUpdate(_BaseSchema):
    """Request body for ``PUT /api/v1/battles/{battle_id}`` (draft only)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, object] | None = Field(default=None)
    ranking_metric: str | None = Field(default=None)


class AddParticipantRequest(_BaseSchema):
    """Request body for ``POST /api/v1/battles/{battle_id}/participants``."""

    agent_id: UUID = Field(..., description="Agent UUID to add to the battle.")


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class BattleParticipantResponse(_BaseSchema):
    """Response schema for a battle participant."""

    id: UUID
    battle_id: UUID
    agent_id: UUID
    snapshot_balance: Decimal | None = None
    final_equity: Decimal | None = None
    final_rank: int | None = None
    status: str
    joined_at: datetime

    @field_serializer("snapshot_balance", "final_equity")
    def _serialize_decimal(self, value: Decimal | None) -> str | None:  # noqa: PLR6301
        return str(value) if value is not None else None


class BattleResponse(_BaseSchema):
    """Response schema for a single battle."""

    id: UUID
    account_id: UUID
    name: str
    status: str
    config: dict[str, object]
    preset: str | None = None
    ranking_metric: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime
    participant_count: int = 0
    participants: list[BattleParticipantResponse] | None = None


class BattleListResponse(_BaseSchema):
    """Response for ``GET /api/v1/battles``."""

    battles: list[BattleResponse]
    total: int


class BattleLiveResponse(_BaseSchema):
    """Response for ``GET /api/v1/battles/{battle_id}/live``."""

    battle_id: UUID
    status: str
    timestamp: datetime
    participants: list[dict[str, object]]


class BattleResultsResponse(_BaseSchema):
    """Response for ``GET /api/v1/battles/{battle_id}/results``."""

    battle_id: UUID
    name: str
    ranking_metric: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    participants: list[dict[str, object]]


class BattleReplayResponse(_BaseSchema):
    """Response for ``GET /api/v1/battles/{battle_id}/replay``."""

    battle_id: UUID
    snapshots: list[dict[str, object]]
    total: int


class BattlePresetResponse(_BaseSchema):
    """Response for preset listing."""

    key: str
    name: str
    description: str
    duration_type: str
    duration_seconds: int | None = None
    starting_balance: str
    allowed_pairs: list[str] | None = None
    best_for: str
