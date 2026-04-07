"""Battle management routes for the AI Agent Crypto Trading Platform.

Implements all 20 battle endpoints:

- ``POST   /api/v1/battles``                                  — create battle
- ``GET    /api/v1/battles``                                   — list battles
- ``GET    /api/v1/battles/presets``                            — list presets
- ``GET    /api/v1/battles/{battle_id}``                       — get battle
- ``PUT    /api/v1/battles/{battle_id}``                       — update battle
- ``DELETE /api/v1/battles/{battle_id}``                       — delete/cancel
- ``POST   /api/v1/battles/{battle_id}/participants``          — add agent
- ``DELETE /api/v1/battles/{battle_id}/participants/{agent_id}``— remove agent
- ``POST   /api/v1/battles/{battle_id}/start``                 — start battle
- ``POST   /api/v1/battles/{battle_id}/pause/{agent_id}``      — pause agent
- ``POST   /api/v1/battles/{battle_id}/resume/{agent_id}``     — resume agent
- ``POST   /api/v1/battles/{battle_id}/stop``                  — stop battle
- ``GET    /api/v1/battles/{battle_id}/live``                  — live snapshot
- ``GET    /api/v1/battles/{battle_id}/results``               — final results
- ``GET    /api/v1/battles/{battle_id}/replay``                — replay data (GET)
- ``POST   /api/v1/battles/{battle_id}/step``                  — step historical battle
- ``POST   /api/v1/battles/{battle_id}/step/batch``            — batch step historical battle
- ``POST   /api/v1/battles/{battle_id}/trade/order``           — place order (historical)
- ``GET    /api/v1/battles/{battle_id}/market/prices``         — prices at virtual time
- ``POST   /api/v1/battles/{battle_id}/replay``                — create replay from battle

All endpoints require JWT authentication (web UI).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import logging
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from src.api.middleware.auth import CurrentAccountDep
from src.api.schemas.battles import (
    AddParticipantRequest,
    BattleCreate,
    BattleListResponse,
    BattleLiveParticipantSchema,
    BattleLiveResponse,
    BattleParticipantResponse,
    BattlePresetResponse,
    BattleReplayRequest,
    BattleReplayResponse,
    BattleResponse,
    BattleResultsResponse,
    BattleUpdate,
    HistoricalOrderRequest,
    HistoricalPricesResponse,
    HistoricalStepRequest,
    HistoricalStepResponse,
)
from src.battles.presets import list_presets
from src.database.models import Battle, BattleParticipant
from src.dependencies import BattleServiceDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/battles", tags=["battles"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _participant_to_response(p: BattleParticipant) -> BattleParticipantResponse:
    """Convert an ORM BattleParticipant to a response schema."""
    return BattleParticipantResponse(
        id=p.id,
        battle_id=p.battle_id,
        agent_id=p.agent_id,
        snapshot_balance=p.snapshot_balance,
        final_equity=p.final_equity,
        final_rank=p.final_rank,
        status=p.status,
        joined_at=p.joined_at,
    )


def _battle_to_response(battle: Battle, *, include_participants: bool = False) -> BattleResponse:
    """Convert an ORM Battle to a response schema."""
    from sqlalchemy import inspect as sa_inspect  # noqa: PLC0415
    from sqlalchemy.exc import NoInspectionAvailable  # noqa: PLC0415

    participants: list[BattleParticipantResponse] | None = []
    participant_count = 0
    # Check if participants are already loaded (avoid lazy load in async context
    # which causes MissingGreenlet error).  When the object is not a real ORM
    # instance (e.g. a MagicMock in tests), sa_inspect raises
    # NoInspectionAvailable — in that case we fall back to direct attribute access.
    try:
        state = sa_inspect(battle)
        participants_loaded = "participants" not in state.unloaded
    except NoInspectionAvailable:
        participants_loaded = True  # non-ORM object: treat attrs as accessible

    if participants_loaded and battle.participants is not None:
        participant_count = len(battle.participants)
        participants = [_participant_to_response(p) for p in battle.participants]

    battle_mode = getattr(battle, "battle_mode", "live")
    backtest_cfg = getattr(battle, "backtest_config", None)

    return BattleResponse(
        id=battle.id,
        account_id=battle.account_id,
        name=battle.name,
        status=battle.status,
        config=dict(battle.config) if battle.config else {},
        preset=battle.preset,
        ranking_metric=battle.ranking_metric,
        started_at=battle.started_at,
        ended_at=battle.ended_at,
        created_at=battle.created_at,
        participant_count=participant_count,
        participants=participants,
        battle_mode=battle_mode,
        backtest_config=dict(backtest_cfg) if backtest_cfg else None,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/battles — create battle
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=BattleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create battle",
)
async def create_battle(
    body: BattleCreate,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> BattleResponse:
    """Create a new battle in draft status."""
    battle = await battle_service.create_battle(
        account_id=account.id,
        name=body.name,
        preset=body.preset,
        config=body.config,
        ranking_metric=body.ranking_metric,
        battle_mode=body.battle_mode,
        backtest_config=body.backtest_config.model_dump(mode="json") if body.backtest_config else None,
    )
    return _battle_to_response(battle)


# ---------------------------------------------------------------------------
# GET /api/v1/battles — list battles
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=BattleListResponse,
    status_code=status.HTTP_200_OK,
    summary="List battles",
)
async def list_battles(
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
    battle_status: str | None = Query(default=None, alias="status", description="Filter by status."),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> BattleListResponse:
    """List battles for the authenticated account."""
    battles = await battle_service.list_battles(account.id, status=battle_status, limit=limit, offset=offset)
    return BattleListResponse(
        battles=[_battle_to_response(b) for b in battles],
        total=len(battles),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/battles/presets — list available presets
# ---------------------------------------------------------------------------


@router.get(
    "/presets",
    response_model=list[BattlePresetResponse],
    status_code=status.HTTP_200_OK,
    summary="List battle presets",
)
async def get_presets() -> list[BattlePresetResponse]:
    """Return all available battle preset configurations."""
    presets = list_presets()
    return [BattlePresetResponse(**p) for p in presets]  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# GET /api/v1/battles/{battle_id} — get battle
# ---------------------------------------------------------------------------


@router.get(
    "/{battle_id}",
    response_model=BattleResponse,
    status_code=status.HTTP_200_OK,
    summary="Get battle",
)
async def get_battle(
    battle_id: UUID,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> BattleResponse:
    """Get a specific battle with participants."""
    battle = await battle_service.get_battle(battle_id)
    if battle.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError("You do not own this battle.")
    return _battle_to_response(battle, include_participants=True)


# ---------------------------------------------------------------------------
# PUT /api/v1/battles/{battle_id} — update battle (draft only)
# ---------------------------------------------------------------------------


@router.put(
    "/{battle_id}",
    response_model=BattleResponse,
    status_code=status.HTTP_200_OK,
    summary="Update battle",
)
async def update_battle(
    battle_id: UUID,
    body: BattleUpdate,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> BattleResponse:
    """Update a battle's configuration (draft only)."""
    update_data = body.model_dump(exclude_unset=True)
    battle = await battle_service.update_battle(battle_id, account.id, **update_data)
    return _battle_to_response(battle)


# ---------------------------------------------------------------------------
# DELETE /api/v1/battles/{battle_id} — delete/cancel
# ---------------------------------------------------------------------------


@router.delete(
    "/{battle_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete or cancel battle",
    response_class=Response,
)
async def delete_battle(
    battle_id: UUID,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> Response:
    """Delete a draft/pending battle or cancel an active one."""
    await battle_service.delete_battle(battle_id, account.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# POST /api/v1/battles/{battle_id}/participants — add agent
# ---------------------------------------------------------------------------


@router.post(
    "/{battle_id}/participants",
    response_model=BattleParticipantResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add participant",
)
async def add_participant(
    battle_id: UUID,
    body: AddParticipantRequest,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> BattleParticipantResponse:
    """Add an agent to a battle."""
    participant = await battle_service.add_participant(battle_id, body.agent_id, account.id)
    return _participant_to_response(participant)


# ---------------------------------------------------------------------------
# DELETE /api/v1/battles/{battle_id}/participants/{agent_id}
# ---------------------------------------------------------------------------


@router.delete(
    "/{battle_id}/participants/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove participant",
    response_class=Response,
)
async def remove_participant(
    battle_id: UUID,
    agent_id: UUID,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> Response:
    """Remove an agent from a battle (draft/pending only)."""
    await battle_service.remove_participant(battle_id, agent_id, account.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# POST /api/v1/battles/{battle_id}/start — start battle
# ---------------------------------------------------------------------------


@router.post(
    "/{battle_id}/start",
    response_model=BattleResponse,
    status_code=status.HTTP_200_OK,
    summary="Start battle",
)
async def start_battle(
    battle_id: UUID,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> BattleResponse:
    """Start a battle — lock config, snapshot wallets, begin."""
    battle = await battle_service.start_battle(battle_id, account.id)
    return _battle_to_response(battle, include_participants=True)


# ---------------------------------------------------------------------------
# POST /api/v1/battles/{battle_id}/pause/{agent_id}
# ---------------------------------------------------------------------------


@router.post(
    "/{battle_id}/pause/{agent_id}",
    response_model=BattleParticipantResponse,
    status_code=status.HTTP_200_OK,
    summary="Pause agent",
)
async def pause_agent(
    battle_id: UUID,
    agent_id: UUID,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> BattleParticipantResponse:
    """Pause an individual agent in an active battle."""
    participant = await battle_service.pause_agent(battle_id, agent_id, account.id)
    return _participant_to_response(participant)


# ---------------------------------------------------------------------------
# POST /api/v1/battles/{battle_id}/resume/{agent_id}
# ---------------------------------------------------------------------------


@router.post(
    "/{battle_id}/resume/{agent_id}",
    response_model=BattleParticipantResponse,
    status_code=status.HTTP_200_OK,
    summary="Resume agent",
)
async def resume_agent(
    battle_id: UUID,
    agent_id: UUID,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> BattleParticipantResponse:
    """Resume a paused agent in an active battle."""
    participant = await battle_service.resume_agent(battle_id, agent_id, account.id)
    return _participant_to_response(participant)


# ---------------------------------------------------------------------------
# POST /api/v1/battles/{battle_id}/stop — stop battle
# ---------------------------------------------------------------------------


@router.post(
    "/{battle_id}/stop",
    response_model=BattleResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop battle",
)
async def stop_battle(
    battle_id: UUID,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> BattleResponse:
    """Stop a battle — calculate final rankings and complete."""
    battle = await battle_service.stop_battle(battle_id, account.id)
    return _battle_to_response(battle, include_participants=True)


# ---------------------------------------------------------------------------
# GET /api/v1/battles/{battle_id}/live — live snapshot
# ---------------------------------------------------------------------------


@router.get(
    "/{battle_id}/live",
    response_model=BattleLiveResponse,
    status_code=status.HTTP_200_OK,
    summary="Live snapshot",
)
async def get_live_snapshot(
    battle_id: UUID,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> BattleLiveResponse:
    """Get live metrics for all participants in an active battle."""
    battle = await battle_service.get_battle(battle_id)
    if battle.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError("You do not own this battle.")

    elapsed: float | None = None
    remaining: float | None = None
    if battle.started_at:
        now = datetime.now(UTC)
        started = battle.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        elapsed_td = now - started
        elapsed = elapsed_td.total_seconds() / 60.0
        duration_minutes = battle.config.get("duration_minutes") if battle.config else None
        if duration_minutes:
            try:
                dur = float(duration_minutes)
            except (TypeError, ValueError):
                dur = 0.0
            if dur > 0:
                remaining = max(0.0, dur - elapsed)

    raw_participants = await battle_service.get_live_snapshot(battle_id)
    participants = [BattleLiveParticipantSchema.model_validate(p) for p in raw_participants]
    return BattleLiveResponse(
        battle_id=battle_id,
        status=battle.status,
        elapsed_minutes=elapsed,
        remaining_minutes=remaining,
        participants=participants,
        updated_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/battles/{battle_id}/results — final results
# ---------------------------------------------------------------------------


@router.get(
    "/{battle_id}/results",
    response_model=BattleResultsResponse,
    status_code=status.HTTP_200_OK,
    summary="Battle results",
)
async def get_results(
    battle_id: UUID,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> BattleResultsResponse:
    """Get final results for a completed battle."""
    battle = await battle_service.get_battle(battle_id)
    if battle.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError("You do not own this battle.")

    results = await battle_service.get_results(battle_id)
    return BattleResultsResponse(**results)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# GET /api/v1/battles/{battle_id}/replay — replay data
# ---------------------------------------------------------------------------


@router.get(
    "/{battle_id}/replay",
    response_model=BattleReplayResponse,
    status_code=status.HTTP_200_OK,
    summary="Battle replay",
)
async def get_replay(
    battle_id: UUID,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
    limit: int = Query(default=10000, ge=1, le=100000),
    offset: int = Query(default=0, ge=0),
) -> BattleReplayResponse:
    """Get time-series snapshots for battle replay."""
    battle = await battle_service.get_battle(battle_id)
    if battle.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError("You do not own this battle.")

    snapshots = await battle_service.get_replay_data(battle_id, limit=limit, offset=offset)
    return BattleReplayResponse(
        battle_id=battle_id,
        snapshots=[
            {
                "agent_id": str(s.agent_id),
                "timestamp": s.timestamp.isoformat(),
                "equity": str(s.equity),
                "unrealized_pnl": str(s.unrealized_pnl) if s.unrealized_pnl else "0",
                "realized_pnl": str(s.realized_pnl) if s.realized_pnl else "0",
                "trade_count": s.trade_count or 0,
                "open_positions": s.open_positions or 0,
            }
            for s in snapshots
        ],
        total=len(snapshots),
    )


# ---------------------------------------------------------------------------
# POST /api/v1/battles/{battle_id}/step — advance historical battle
# ---------------------------------------------------------------------------


@router.post(
    "/{battle_id}/step",
    response_model=HistoricalStepResponse,
    status_code=status.HTTP_200_OK,
    summary="Step historical battle",
)
async def step_historical_battle(
    battle_id: UUID,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> HistoricalStepResponse:
    """Advance a historical battle by one step."""
    battle = await battle_service.get_battle(battle_id)
    if battle.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError("You do not own this battle.")
    if getattr(battle, "battle_mode", "live") != "historical":
        from src.utils.exceptions import BattleInvalidStateError  # noqa: PLC0415

        raise BattleInvalidStateError("Step is only available for historical battles.")

    result = await battle_service.step_historical(battle_id)
    return HistoricalStepResponse(
        battle_id=battle_id,
        virtual_time=result.virtual_time,  # type: ignore[attr-defined]
        step=result.step,  # type: ignore[attr-defined]
        total_steps=result.total_steps,  # type: ignore[attr-defined]
        progress_pct=str(result.progress_pct),  # type: ignore[attr-defined]
        is_complete=result.is_complete,  # type: ignore[attr-defined]
        prices={k: str(v) for k, v in result.prices.items()},  # type: ignore[attr-defined]
        participants=[
            {
                "agent_id": s.agent_id,
                "equity": str(s.equity),
                "pnl": str(s.pnl),
                "trade_count": s.trade_count,
            }
            for s in result.agent_states.values()  # type: ignore[attr-defined]
        ],
    )


# ---------------------------------------------------------------------------
# POST /api/v1/battles/{battle_id}/step/batch — advance N steps
# ---------------------------------------------------------------------------


@router.post(
    "/{battle_id}/step/batch",
    response_model=HistoricalStepResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch step historical battle",
)
async def step_batch_historical_battle(
    battle_id: UUID,
    body: HistoricalStepRequest,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> HistoricalStepResponse:
    """Advance a historical battle by N steps."""
    battle = await battle_service.get_battle(battle_id)
    if battle.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError("You do not own this battle.")
    if getattr(battle, "battle_mode", "live") != "historical":
        from src.utils.exceptions import BattleInvalidStateError  # noqa: PLC0415

        raise BattleInvalidStateError("Step is only available for historical battles.")

    result = await battle_service.step_historical_batch(battle_id, body.steps)
    return HistoricalStepResponse(
        battle_id=battle_id,
        virtual_time=result.virtual_time,  # type: ignore[attr-defined]
        step=result.step,  # type: ignore[attr-defined]
        total_steps=result.total_steps,  # type: ignore[attr-defined]
        progress_pct=str(result.progress_pct),  # type: ignore[attr-defined]
        is_complete=result.is_complete,  # type: ignore[attr-defined]
        prices={k: str(v) for k, v in result.prices.items()},  # type: ignore[attr-defined]
        participants=[
            {
                "agent_id": s.agent_id,
                "equity": str(s.equity),
                "pnl": str(s.pnl),
                "trade_count": s.trade_count,
            }
            for s in result.agent_states.values()  # type: ignore[attr-defined]
        ],
    )


# ---------------------------------------------------------------------------
# POST /api/v1/battles/{battle_id}/trade/order — place order (historical)
# ---------------------------------------------------------------------------


@router.post(
    "/{battle_id}/trade/order",
    status_code=status.HTTP_200_OK,
    summary="Place order in historical battle",
)
async def place_historical_order(
    battle_id: UUID,
    body: HistoricalOrderRequest,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> dict[str, object]:
    """Place an order for an agent in a historical battle."""
    battle = await battle_service.get_battle(battle_id)
    if battle.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError("You do not own this battle.")
    if getattr(battle, "battle_mode", "live") != "historical":
        from src.utils.exceptions import BattleInvalidStateError  # noqa: PLC0415

        raise BattleInvalidStateError("Order placement is only available for historical battles.")

    result = await battle_service.place_historical_order(
        battle_id=battle_id,
        agent_id=body.agent_id,
        symbol=body.symbol,
        side=body.side,
        order_type=body.order_type,
        quantity=Decimal(body.quantity),
        price=Decimal(body.price) if body.price else None,
    )
    return {
        "order_id": result.order_id,  # type: ignore[attr-defined]
        "status": result.status,  # type: ignore[attr-defined]
        "executed_price": str(result.executed_price) if result.executed_price else None,  # type: ignore[attr-defined]
        "executed_qty": str(result.executed_qty) if result.executed_qty else None,  # type: ignore[attr-defined]
        "fee": str(result.fee) if result.fee else None,  # type: ignore[attr-defined]
    }


# ---------------------------------------------------------------------------
# GET /api/v1/battles/{battle_id}/market/prices — prices at virtual_time
# ---------------------------------------------------------------------------


@router.get(
    "/{battle_id}/market/prices",
    response_model=HistoricalPricesResponse,
    status_code=status.HTTP_200_OK,
    summary="Historical battle prices",
)
async def get_historical_prices(
    battle_id: UUID,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> HistoricalPricesResponse:
    """Get current prices at the virtual time of a historical battle."""
    battle = await battle_service.get_battle(battle_id)
    if battle.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError("You do not own this battle.")
    if getattr(battle, "battle_mode", "live") != "historical":
        from src.utils.exceptions import BattleInvalidStateError  # noqa: PLC0415

        raise BattleInvalidStateError("Market prices are only available for historical battles.")

    prices, virtual_time = await battle_service.get_historical_prices(battle_id)
    return HistoricalPricesResponse(
        battle_id=battle_id,
        virtual_time=virtual_time,
        prices={k: str(v) for k, v in prices.items()},
    )


# ---------------------------------------------------------------------------
# POST /api/v1/battles/{battle_id}/replay — create replay from battle
# ---------------------------------------------------------------------------


@router.post(
    "/{battle_id}/replay",
    response_model=BattleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Replay battle",
)
async def replay_battle(
    battle_id: UUID,
    body: BattleReplayRequest,
    account: CurrentAccountDep,
    battle_service: BattleServiceDep,
) -> BattleResponse:
    """Create a new historical battle draft from a completed battle's config."""
    battle = await battle_service.replay_battle(
        battle_id,
        account.id,
        override_config=body.override_config,
        override_agents=body.agent_ids,
    )
    return _battle_to_response(battle, include_participants=True)
