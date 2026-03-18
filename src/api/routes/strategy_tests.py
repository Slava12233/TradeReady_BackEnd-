"""Strategy test routes for the AI Agent Crypto Trading Platform.

Implements 6 strategy test endpoints:

- ``POST /api/v1/strategies/{strategy_id}/test``                — trigger test run
- ``GET  /api/v1/strategies/{strategy_id}/tests``               — list test runs
- ``GET  /api/v1/strategies/{strategy_id}/tests/{test_id}``     — get test status + results
- ``POST /api/v1/strategies/{strategy_id}/tests/{test_id}/cancel`` — cancel test
- ``GET  /api/v1/strategies/{strategy_id}/test-results``        — latest results
- ``GET  /api/v1/strategies/{strategy_id}/compare-versions``    — compare v1 vs v2

All endpoints require authentication.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Query, status

from src.api.middleware.auth import CurrentAccountDep
from src.api.schemas.strategy_tests import (
    StartTestRequest,
    TestResultsResponse,
    TestRunResponse,
    VersionComparisonResponse,
    VersionMetrics,
)
from src.dependencies import StrategyServiceDep, TestOrchestratorDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/strategies", tags=["strategy-tests"])


# ---------------------------------------------------------------------------
# Test run endpoints
# ---------------------------------------------------------------------------


@router.post("/{strategy_id}/test", response_model=TestRunResponse, status_code=status.HTTP_201_CREATED)
async def start_test(
    strategy_id: UUID,
    body: StartTestRequest,
    account: CurrentAccountDep,
    orchestrator: TestOrchestratorDep,
) -> TestRunResponse:
    """Trigger a new strategy test run."""
    config = {
        "episodes": body.episodes,
        "date_range": {
            "start": body.date_range.start.isoformat(),
            "end": body.date_range.end.isoformat(),
        },
        "randomize_dates": body.randomize_dates,
        "episode_duration_days": body.episode_duration_days,
        "starting_balance": body.starting_balance,
    }

    test_run_id = await orchestrator.start_test(
        account_id=account.id,
        strategy_id=strategy_id,
        version=body.version,
        config=config,
    )

    progress = await orchestrator.get_progress(test_run_id)
    return TestRunResponse(
        test_run_id=str(test_run_id),
        status=progress.get("status", "queued"),
        episodes_total=progress.get("episodes_total", body.episodes),
        episodes_completed=progress.get("episodes_completed", 0),
        progress_pct=progress.get("progress_pct", 0),
        version=body.version,
    )


@router.get("/{strategy_id}/tests", response_model=list[TestRunResponse])
async def list_tests(
    strategy_id: UUID,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
) -> list[TestRunResponse]:
    """List test runs for a strategy."""
    test_runs = await service.list_test_runs(account.id, strategy_id)

    return [
        TestRunResponse(
            test_run_id=str(tr.id),
            status=tr.status,
            episodes_total=tr.episodes_total,
            episodes_completed=tr.episodes_completed,
            progress_pct=round(tr.episodes_completed / tr.episodes_total * 100, 1) if tr.episodes_total > 0 else 0,
            version=tr.version,
            created_at=tr.created_at,
            started_at=tr.started_at,
            completed_at=tr.completed_at,
        )
        for tr in test_runs
    ]


@router.get("/{strategy_id}/tests/{test_id}", response_model=TestResultsResponse)
async def get_test(
    strategy_id: UUID,
    test_id: UUID,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
) -> TestResultsResponse:
    """Get test run status and results."""
    test_run = await service.get_test_run(account.id, strategy_id, test_id)

    total = test_run.episodes_total
    completed = test_run.episodes_completed

    return TestResultsResponse(
        test_run_id=str(test_run.id),
        status=test_run.status,
        episodes_total=total,
        episodes_completed=completed,
        progress_pct=round(completed / total * 100, 1) if total > 0 else 0,
        version=test_run.version,
        created_at=test_run.created_at,
        started_at=test_run.started_at,
        completed_at=test_run.completed_at,
        results=test_run.results,
        recommendations=test_run.recommendations,
        config=test_run.config,
    )


@router.post("/{strategy_id}/tests/{test_id}/cancel", response_model=TestRunResponse)
async def cancel_test(
    strategy_id: UUID,
    test_id: UUID,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
    orchestrator: TestOrchestratorDep,
) -> TestRunResponse:
    """Cancel a running or queued test run."""
    await service.get_strategy(account.id, strategy_id)  # ownership check
    await orchestrator.cancel_test(test_id)
    progress = await orchestrator.get_progress(test_id)
    return TestRunResponse(
        test_run_id=str(test_id),
        status=progress.get("status", "cancelled"),
        episodes_total=progress.get("episodes_total", 0),
        episodes_completed=progress.get("episodes_completed", 0),
        progress_pct=progress.get("progress_pct", 0),
    )


@router.get("/{strategy_id}/test-results", response_model=TestResultsResponse)
async def get_latest_results(
    strategy_id: UUID,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
) -> TestResultsResponse:
    """Get the latest completed test results for a strategy."""
    test_run = await service.get_latest_completed_test(account.id, strategy_id)

    total = test_run.episodes_total
    completed = test_run.episodes_completed

    return TestResultsResponse(
        test_run_id=str(test_run.id),
        status=test_run.status,
        episodes_total=total,
        episodes_completed=completed,
        progress_pct=round(completed / total * 100, 1) if total > 0 else 0,
        version=test_run.version,
        created_at=test_run.created_at,
        started_at=test_run.started_at,
        completed_at=test_run.completed_at,
        results=test_run.results,
        recommendations=test_run.recommendations,
        config=test_run.config,
    )


@router.get("/{strategy_id}/compare-versions", response_model=VersionComparisonResponse)
async def compare_versions(
    strategy_id: UUID,
    account: CurrentAccountDep,
    service: StrategyServiceDep,
    v1: int = Query(..., ge=1, description="First version"),
    v2: int = Query(..., ge=1, description="Second version"),
) -> VersionComparisonResponse:
    """Compare test results between two strategy versions."""
    # Get latest test results for each version (ownership checked inside)
    test_runs = await service.list_test_runs(account.id, strategy_id, limit=100)

    v1_results: dict | None = None
    v2_results: dict | None = None

    for tr in test_runs:
        if tr.version == v1 and tr.status == "completed" and tr.results:
            v1_results = tr.results
            break
    for tr in test_runs:
        if tr.version == v2 and tr.status == "completed" and tr.results:
            v2_results = tr.results
            break

    v1_metrics = VersionMetrics(
        version=v1,
        avg_roi_pct=v1_results.get("avg_roi_pct") if v1_results else None,
        avg_sharpe=v1_results.get("avg_sharpe") if v1_results else None,
        avg_max_drawdown_pct=v1_results.get("avg_max_drawdown_pct") if v1_results else None,
        total_trades=v1_results.get("total_trades", 0) if v1_results else 0,
        episodes_completed=v1_results.get("episodes_completed", 0) if v1_results else 0,
    )

    v2_metrics = VersionMetrics(
        version=v2,
        avg_roi_pct=v2_results.get("avg_roi_pct") if v2_results else None,
        avg_sharpe=v2_results.get("avg_sharpe") if v2_results else None,
        avg_max_drawdown_pct=v2_results.get("avg_max_drawdown_pct") if v2_results else None,
        total_trades=v2_results.get("total_trades", 0) if v2_results else 0,
        episodes_completed=v2_results.get("episodes_completed", 0) if v2_results else 0,
    )

    # Calculate improvements
    improvements: dict[str, float] = {}
    if v1_metrics.avg_roi_pct is not None and v2_metrics.avg_roi_pct is not None:
        improvements["roi_pct"] = round(v2_metrics.avg_roi_pct - v1_metrics.avg_roi_pct, 4)
    if v1_metrics.avg_sharpe is not None and v2_metrics.avg_sharpe is not None:
        improvements["sharpe"] = round(v2_metrics.avg_sharpe - v1_metrics.avg_sharpe, 4)

    # Verdict
    roi_better = improvements.get("roi_pct", 0) > 0
    sharpe_better = improvements.get("sharpe", 0) > 0
    if roi_better and sharpe_better:
        verdict = f"Version {v2} improves on version {v1} across both ROI and Sharpe ratio."
    elif roi_better:
        verdict = f"Version {v2} has better ROI but worse risk-adjusted returns than version {v1}."
    elif sharpe_better:
        verdict = f"Version {v2} has better risk-adjusted returns but lower ROI than version {v1}."
    else:
        verdict = f"Version {v1} outperforms version {v2} on both metrics."

    if not v1_results and not v2_results:
        verdict = "No completed test results available for either version."
    elif not v1_results:
        verdict = f"No completed test results for version {v1}. Cannot compare."
    elif not v2_results:
        verdict = f"No completed test results for version {v2}. Cannot compare."

    return VersionComparisonResponse(
        v1=v1_metrics,
        v2=v2_metrics,
        improvements=improvements,
        verdict=verdict,
    )
