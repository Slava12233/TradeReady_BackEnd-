"""Test orchestrator — manages multi-episode strategy test runs.

Coordinates the creation, monitoring, and cancellation of strategy tests
that run multiple backtest episodes and aggregate results.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from src.database.repositories.strategy_repo import StrategyRepository
from src.strategies.service import StrategyService

logger = structlog.get_logger(__name__)


class TestOrchestrator:
    """Orchestrates multi-episode strategy test runs.

    Args:
        strategy_repo: Repository for strategy and test run DB access.
        strategy_service: Service for strategy ownership checks.
    """

    def __init__(
        self,
        strategy_repo: StrategyRepository,
        strategy_service: StrategyService,
    ) -> None:
        self._repo = strategy_repo
        self._service = strategy_service

    async def start_test(
        self,
        account_id: UUID,
        strategy_id: UUID,
        version: int,
        config: dict[str, Any],
    ) -> UUID:
        """Create a test run and queue it for execution.

        Args:
            account_id: Owner account.
            strategy_id: Strategy to test.
            version: Version number to test.
            config: Test configuration (episodes, date_range, etc.).

        Returns:
            The test_run_id UUID.
        """
        # Ownership check
        await self._service.get_strategy(account_id, strategy_id)

        # Validate version exists
        ver = await self._repo.get_version(strategy_id, version)
        if ver is None:
            from src.utils.exceptions import StrategyNotFoundError  # noqa: PLC0415

            raise StrategyNotFoundError(
                message=f"Version {version} not found.",
                strategy_id=strategy_id,
            )

        episodes_total = config.get("episodes", 10)

        # Inject account_id into config for Celery tasks
        config["account_id"] = str(account_id)

        test_run = await self._repo.create_test_run(
            strategy_id=strategy_id,
            version=version,
            config=config,
            episodes_total=episodes_total,
        )

        # Update strategy status to testing
        await self._repo.update(strategy_id, status="testing")

        # Dispatch Celery tasks for each episode
        definition = ver.definition
        from src.tasks.strategy_tasks import aggregate_test_results, run_strategy_episode  # noqa: PLC0415

        backtest_config = {
            "start_time": config["date_range"]["start"],
            "end_time": config["date_range"]["end"],
            "starting_balance": config.get("starting_balance", "10000"),
            "candle_interval": config.get("candle_interval", 60),
            "account_id": str(account_id),
        }

        for ep in range(1, episodes_total + 1):
            run_strategy_episode.delay(
                str(test_run.id), ep, definition, backtest_config,
            )

        # Schedule aggregation after all episodes (fire-and-forget; episodes
        # call increment_completed and the aggregation task checks completion)
        aggregate_test_results.apply_async(
            args=[str(test_run.id), definition],
            countdown=episodes_total * 60,  # rough estimate: 1min per episode
        )

        logger.info(
            "test.started",
            test_run_id=str(test_run.id),
            strategy_id=str(strategy_id),
            version=version,
            episodes=episodes_total,
        )

        return test_run.id

    async def get_progress(self, test_run_id: UUID) -> dict[str, Any]:
        """Get the current progress of a test run.

        Args:
            test_run_id: Test run to query.

        Returns:
            Progress dict with episodes_completed, total, progress_pct, status.
        """
        test_run = await self._repo.get_test_run(test_run_id)
        if test_run is None:
            return {"error": "Test run not found"}

        total = test_run.episodes_total
        completed = test_run.episodes_completed
        progress_pct = round(completed / total * 100, 1) if total > 0 else 0

        result: dict[str, Any] = {
            "test_run_id": str(test_run.id),
            "status": test_run.status,
            "episodes_total": total,
            "episodes_completed": completed,
            "progress_pct": progress_pct,
        }

        if test_run.results is not None:
            result["results"] = test_run.results
        if test_run.recommendations is not None:
            result["recommendations"] = test_run.recommendations

        return result

    async def cancel_test(self, test_run_id: UUID) -> None:
        """Cancel a running or queued test run.

        Args:
            test_run_id: Test run to cancel.
        """
        test_run = await self._repo.get_test_run(test_run_id)
        if test_run is None:
            return

        if test_run.status in ("completed", "cancelled", "failed"):
            return

        await self._repo.update_test_run_status(test_run_id, "cancelled")
        logger.info("test.cancelled", test_run_id=str(test_run_id))
