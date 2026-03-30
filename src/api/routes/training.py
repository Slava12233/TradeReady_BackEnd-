"""Training observation routes for the AI Agent Crypto Trading Platform.

Implements 7 training endpoints:

- ``POST /api/v1/training/runs``                        — register new run
- ``POST /api/v1/training/runs/{run_id}/episodes``      — report episode
- ``POST /api/v1/training/runs/{run_id}/complete``       — mark run complete
- ``GET  /api/v1/training/runs``                         — list all runs
- ``GET  /api/v1/training/runs/{run_id}``                — full detail
- ``GET  /api/v1/training/runs/{run_id}/learning-curve`` — learning curve data
- ``GET  /api/v1/training/compare``                      — compare runs

All endpoints require authentication.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Query, status

from src.api.middleware.auth import CurrentAccountDep
from src.api.schemas.training import (
    LearningCurveResponse,
    RegisterRunRequest,
    ReportEpisodeRequest,
    RunMetrics,
    TrainingComparisonResponse,
    TrainingRunDetailResponse,
    TrainingRunResponse,
)
from src.dependencies import TrainingRunServiceDep
from src.utils.exceptions import DatabaseError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/training", tags=["training"])


# ---------------------------------------------------------------------------
# Registration & episode reporting (called by Gym wrapper)
# ---------------------------------------------------------------------------


@router.post("/runs", response_model=TrainingRunResponse, status_code=status.HTTP_201_CREATED)
async def register_run(
    body: RegisterRunRequest,
    account: CurrentAccountDep,
    service: TrainingRunServiceDep,
) -> TrainingRunResponse:
    """Register a new training run."""
    strategy_id = UUID(body.strategy_id) if body.strategy_id else None
    run = await service.register_run(
        account_id=account.id,
        run_id=UUID(body.run_id),
        config=body.config,
        strategy_id=strategy_id,
    )
    return TrainingRunResponse(
        run_id=str(run.id),
        status=run.status,
        config=run.config,
        episodes_total=run.episodes_total,
        episodes_completed=run.episodes_completed,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


@router.post("/runs/{run_id}/episodes", response_model=TrainingRunResponse)
async def report_episode(
    run_id: UUID,
    body: ReportEpisodeRequest,
    account: CurrentAccountDep,
    service: TrainingRunServiceDep,
) -> TrainingRunResponse:
    """Report a completed training episode."""
    metrics = {
        k: v
        for k, v in {
            "roi_pct": body.roi_pct,
            "sharpe_ratio": body.sharpe_ratio,
            "max_drawdown_pct": body.max_drawdown_pct,
            "total_trades": body.total_trades,
            "reward_sum": body.reward_sum,
        }.items()
        if v is not None
    }

    session_id = UUID(body.session_id) if body.session_id else None
    await service.record_episode(
        run_id=run_id,
        episode_number=body.episode_number,
        session_id=session_id,
        metrics=metrics,
    )

    # Return updated run status
    run = await service.get_run(run_id)
    if run is None:
        from src.utils.exceptions import TrainingRunNotFoundError  # noqa: PLC0415

        raise TrainingRunNotFoundError(run_id=run_id)
    if run.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError()

    return TrainingRunResponse(
        run_id=str(run.id),
        status=run.status,
        config=run.config,
        episodes_total=run.episodes_total,
        episodes_completed=run.episodes_completed,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


@router.post("/runs/{run_id}/complete", response_model=TrainingRunResponse)
async def complete_run(
    run_id: UUID,
    account: CurrentAccountDep,
    service: TrainingRunServiceDep,
) -> TrainingRunResponse:
    """Mark a training run as complete."""
    # Verify run exists and is owned by account
    existing = await service.get_run(run_id)
    if existing is None:
        from src.utils.exceptions import TrainingRunNotFoundError  # noqa: PLC0415

        raise TrainingRunNotFoundError(run_id=run_id)
    if existing.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError()

    run = await service.complete_run(run_id)
    if run is None:
        from src.utils.exceptions import TrainingRunNotFoundError  # noqa: PLC0415

        raise TrainingRunNotFoundError(run_id=run_id)

    return TrainingRunResponse(
        run_id=str(run.id),
        status=run.status,
        config=run.config,
        episodes_total=run.episodes_total,
        episodes_completed=run.episodes_completed,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )


# ---------------------------------------------------------------------------
# Query endpoints (UI / dashboard)
# ---------------------------------------------------------------------------


@router.get("/runs", response_model=list[TrainingRunResponse])
async def list_runs(
    account: CurrentAccountDep,
    service: TrainingRunServiceDep,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[TrainingRunResponse]:
    """List all training runs for the authenticated account."""
    runs = await service.list_runs(account.id, status=status_filter, limit=limit, offset=offset)
    return [
        TrainingRunResponse(
            run_id=str(r.id),
            status=r.status,
            config=r.config,
            episodes_total=r.episodes_total,
            episodes_completed=r.episodes_completed,
            started_at=r.started_at,
            completed_at=r.completed_at,
        )
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=TrainingRunDetailResponse)
async def get_run_detail(
    run_id: UUID,
    account: CurrentAccountDep,
    service: TrainingRunServiceDep,
) -> TrainingRunDetailResponse:
    """Get full training run detail with learning curve and episodes."""
    run = await service.get_run(run_id)
    if run is None:
        from src.utils.exceptions import TrainingRunNotFoundError  # noqa: PLC0415

        raise TrainingRunNotFoundError(run_id=run_id)
    if run.account_id != account.id:
        from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

        raise PermissionDeniedError()

    # Get episodes
    episodes_data = []
    try:
        episodes = await service.get_episodes(run_id)
        episodes_data = [
            {
                "episode_number": ep.episode_number,
                "metrics": ep.metrics,
                "created_at": ep.created_at.isoformat() if ep.created_at else None,
            }
            for ep in episodes
        ]
    except DatabaseError:
        logger.warning("training.get_episodes.failed", run_id=str(run_id))  # type: ignore[call-arg]

    return TrainingRunDetailResponse(
        run_id=str(run.id),
        status=run.status,
        config=run.config,
        episodes_total=run.episodes_total,
        episodes_completed=run.episodes_completed,
        started_at=run.started_at,
        completed_at=run.completed_at,
        learning_curve=run.learning_curve,
        aggregate_stats=run.aggregate_stats,
        episodes=episodes_data,
    )


@router.get("/runs/{run_id}/learning-curve", response_model=LearningCurveResponse)
async def get_learning_curve(
    run_id: UUID,
    account: CurrentAccountDep,
    service: TrainingRunServiceDep,
    metric: str = Query(default="roi_pct", description="Metric to plot"),
    window: int = Query(default=10, ge=1, le=100, description="Smoothing window"),
) -> LearningCurveResponse:
    """Get learning curve data with optional smoothing."""
    data = await service.get_learning_curve(run_id, metric=metric, window=window)
    return LearningCurveResponse(**data)


@router.get("/compare", response_model=TrainingComparisonResponse)
async def compare_runs(
    account: CurrentAccountDep,
    service: TrainingRunServiceDep,
    run_ids: str = Query(..., description="Comma-separated run UUIDs"),
) -> TrainingComparisonResponse:
    """Compare multiple training runs."""
    ids = [UUID(rid.strip()) for rid in run_ids.split(",") if rid.strip()]
    comparisons = await service.compare_runs(ids)
    return TrainingComparisonResponse(
        runs=[RunMetrics(**c) for c in comparisons],
    )
