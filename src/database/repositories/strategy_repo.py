"""Repository for Strategy CRUD operations.

All database access for strategies, strategy versions, strategy test runs,
and strategy test episodes goes through :class:`StrategyRepository`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import (
    Strategy,
    StrategyTestEpisode,
    StrategyTestRun,
    StrategyVersion,
)
from src.utils.exceptions import DatabaseError, StrategyNotFoundError

logger = structlog.get_logger(__name__)


class StrategyRepository:
    """Async CRUD repository for strategy tables.

    Callers are responsible for committing the session.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Strategy CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        account_id: UUID,
        name: str,
        description: str | None,
        definition: dict[str, Any],
    ) -> Strategy:
        """Create a new strategy with its first version."""
        try:
            strategy = Strategy(
                account_id=account_id,
                name=name,
                description=description,
                status="draft",
                current_version=1,
            )
            self._session.add(strategy)
            await self._session.flush()
            await self._session.refresh(strategy)

            # Create initial version
            version = StrategyVersion(
                strategy_id=strategy.id,
                version=1,
                definition=definition,
                change_notes="Initial version",
                status="draft",
            )
            self._session.add(version)
            await self._session.flush()

            logger.info("strategy.created", strategy_id=str(strategy.id), account_id=str(account_id))
            return strategy
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("strategy.create.db_error", error=str(exc))
            raise DatabaseError("Failed to create strategy.") from exc

    async def get_by_id(self, strategy_id: UUID) -> Strategy:
        """Fetch a strategy by ID."""
        try:
            stmt = select(Strategy).where(Strategy.id == strategy_id)
            result = await self._session.execute(stmt)
            strategy = result.scalars().first()
            if strategy is None:
                raise StrategyNotFoundError(strategy_id=strategy_id)
            return strategy
        except StrategyNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("strategy.get.db_error", strategy_id=str(strategy_id), error=str(exc))
            raise DatabaseError("Failed to fetch strategy.") from exc

    async def list_by_account(
        self,
        account_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[Strategy], int]:
        """List strategies for an account with optional status filter.

        Returns:
            Tuple of (strategies, total_count).
        """
        try:
            base = select(Strategy).where(Strategy.account_id == account_id)
            if status is not None:
                base = base.where(Strategy.status == status)

            # Count
            count_stmt = select(func.count()).select_from(base.subquery())
            count_result = await self._session.execute(count_stmt)
            total = count_result.scalar_one()

            # Fetch
            stmt = base.order_by(Strategy.created_at.desc()).limit(limit).offset(offset)
            result = await self._session.execute(stmt)
            return result.scalars().all(), total
        except SQLAlchemyError as exc:
            logger.exception("strategy.list.db_error", account_id=str(account_id), error=str(exc))
            raise DatabaseError("Failed to list strategies.") from exc

    async def update(self, strategy_id: UUID, **kwargs: object) -> Strategy:
        """Update specific fields on a strategy."""
        try:
            strategy = await self.get_by_id(strategy_id)
            for key, value in kwargs.items():
                setattr(strategy, key, value)
            from src.utils.helpers import utc_now  # noqa: PLC0415

            strategy.updated_at = utc_now()
            await self._session.flush()
            await self._session.refresh(strategy)
            logger.info("strategy.updated", strategy_id=str(strategy_id), fields=list(kwargs.keys()))
            return strategy
        except StrategyNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("strategy.update.db_error", strategy_id=str(strategy_id), error=str(exc))
            raise DatabaseError("Failed to update strategy.") from exc

    async def archive(self, strategy_id: UUID) -> Strategy:
        """Soft-delete a strategy by setting status to 'archived'."""
        return await self.update(strategy_id, status="archived")

    # ------------------------------------------------------------------
    # Version operations
    # ------------------------------------------------------------------

    async def create_version(
        self,
        strategy_id: UUID,
        version_num: int,
        definition: dict[str, Any],
        change_notes: str | None = None,
        parent_version: int | None = None,
    ) -> StrategyVersion:
        """Create a new version for a strategy."""
        try:
            version = StrategyVersion(
                strategy_id=strategy_id,
                version=version_num,
                definition=definition,
                change_notes=change_notes,
                parent_version=parent_version,
                status="draft",
            )
            self._session.add(version)
            await self._session.flush()
            await self._session.refresh(version)
            logger.info("strategy.version_created", strategy_id=str(strategy_id), version=version_num)
            return version
        except IntegrityError as exc:
            await self._session.rollback()
            raise DatabaseError(f"Version {version_num} already exists for this strategy.") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("strategy.create_version.db_error", error=str(exc))
            raise DatabaseError("Failed to create strategy version.") from exc

    async def get_version(self, strategy_id: UUID, version: int) -> StrategyVersion | None:
        """Get a specific version of a strategy."""
        try:
            stmt = select(StrategyVersion).where(
                StrategyVersion.strategy_id == strategy_id,
                StrategyVersion.version == version,
            )
            result = await self._session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as exc:
            logger.exception("strategy.get_version.db_error", error=str(exc))
            raise DatabaseError("Failed to fetch strategy version.") from exc

    async def list_versions(self, strategy_id: UUID) -> Sequence[StrategyVersion]:
        """List all versions for a strategy, ordered by version number desc."""
        try:
            stmt = (
                select(StrategyVersion)
                .where(StrategyVersion.strategy_id == strategy_id)
                .order_by(StrategyVersion.version.desc())
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("strategy.list_versions.db_error", error=str(exc))
            raise DatabaseError("Failed to list strategy versions.") from exc

    async def get_max_version(self, strategy_id: UUID) -> int:
        """Get the highest version number for a strategy."""
        try:
            stmt = select(func.max(StrategyVersion.version)).where(
                StrategyVersion.strategy_id == strategy_id,
            )
            result = await self._session.execute(stmt)
            max_v = result.scalar_one_or_none()
            return max_v or 0
        except SQLAlchemyError as exc:
            logger.exception("strategy.get_max_version.db_error", error=str(exc))
            raise DatabaseError("Failed to get max version.") from exc

    async def update_version_status(self, strategy_id: UUID, version: int, status: str) -> StrategyVersion | None:
        """Update the status of a strategy version."""
        try:
            ver = await self.get_version(strategy_id, version)
            if ver is None:
                return None
            ver.status = status  # type: ignore[assignment]
            await self._session.flush()
            await self._session.refresh(ver)
            return ver
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("strategy.update_version_status.db_error", error=str(exc))
            raise DatabaseError("Failed to update version status.") from exc

    # ------------------------------------------------------------------
    # Deploy/Undeploy
    # ------------------------------------------------------------------

    async def deploy(self, strategy_id: UUID, version: int) -> Strategy:
        """Mark a strategy as deployed with the given version."""
        from src.utils.helpers import utc_now  # noqa: PLC0415

        strategy = await self.get_by_id(strategy_id)
        strategy.status = "deployed"  # type: ignore[assignment]
        strategy.current_version = version
        strategy.deployed_at = utc_now()
        strategy.updated_at = utc_now()
        await self._session.flush()
        await self._session.refresh(strategy)
        logger.info("strategy.deployed", strategy_id=str(strategy_id), version=version)
        return strategy

    async def undeploy(self, strategy_id: UUID) -> Strategy:
        """Remove deployed status from a strategy."""
        from src.utils.helpers import utc_now  # noqa: PLC0415

        strategy = await self.get_by_id(strategy_id)
        strategy.status = "validated"  # type: ignore[assignment]
        strategy.deployed_at = None
        strategy.updated_at = utc_now()
        await self._session.flush()
        await self._session.refresh(strategy)
        logger.info("strategy.undeployed", strategy_id=str(strategy_id))
        return strategy

    # ------------------------------------------------------------------
    # Test run operations
    # ------------------------------------------------------------------

    async def create_test_run(
        self,
        strategy_id: UUID,
        version: int,
        config: dict[str, Any],
        episodes_total: int,
    ) -> StrategyTestRun:
        """Create a new test run record."""
        try:
            test_run = StrategyTestRun(
                strategy_id=strategy_id,
                version=version,
                config=config,
                episodes_total=episodes_total,
                episodes_completed=0,
                status="queued",
            )
            self._session.add(test_run)
            await self._session.flush()
            await self._session.refresh(test_run)
            logger.info("strategy.test_run_created", test_run_id=str(test_run.id))
            return test_run
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("strategy.create_test_run.db_error", error=str(exc))
            raise DatabaseError("Failed to create test run.") from exc

    async def get_test_run(self, test_run_id: UUID) -> StrategyTestRun | None:
        """Get a test run by ID."""
        try:
            stmt = select(StrategyTestRun).where(StrategyTestRun.id == test_run_id)
            result = await self._session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as exc:
            logger.exception("strategy.get_test_run.db_error", error=str(exc))
            raise DatabaseError("Failed to fetch test run.") from exc

    async def list_test_runs(
        self,
        strategy_id: UUID,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[StrategyTestRun]:
        """List test runs for a strategy."""
        try:
            stmt = (
                select(StrategyTestRun)
                .where(StrategyTestRun.strategy_id == strategy_id)
                .order_by(StrategyTestRun.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("strategy.list_test_runs.db_error", error=str(exc))
            raise DatabaseError("Failed to list test runs.") from exc

    async def increment_completed(self, test_run_id: UUID) -> None:
        """Atomically increment episodes_completed on a test run."""
        try:
            stmt = (
                update(StrategyTestRun)
                .where(StrategyTestRun.id == test_run_id)
                .values(episodes_completed=StrategyTestRun.episodes_completed + 1)
            )
            await self._session.execute(stmt)
            await self._session.flush()
        except SQLAlchemyError as exc:
            logger.exception("strategy.increment_completed.db_error", error=str(exc))
            raise DatabaseError("Failed to increment completed episodes.") from exc

    async def save_episode(
        self,
        test_run_id: UUID,
        episode_number: int,
        backtest_session_id: UUID | None,
        metrics: dict[str, Any] | None,
    ) -> StrategyTestEpisode:
        """Save a single test episode result."""
        try:
            episode = StrategyTestEpisode(
                test_run_id=test_run_id,
                episode_number=episode_number,
                backtest_session_id=backtest_session_id,
                metrics=metrics,
            )
            self._session.add(episode)
            await self._session.flush()
            await self._session.refresh(episode)
            return episode
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("strategy.save_episode.db_error", error=str(exc))
            raise DatabaseError("Failed to save test episode.") from exc

    async def save_results(
        self,
        test_run_id: UUID,
        results: dict[str, Any],
        recommendations: list[str] | None,
    ) -> StrategyTestRun | None:
        """Save aggregated results and recommendations to a test run."""
        try:
            from src.utils.helpers import utc_now  # noqa: PLC0415

            test_run = await self.get_test_run(test_run_id)
            if test_run is None:
                return None
            test_run.results = results  # type: ignore[assignment]
            test_run.recommendations = recommendations  # type: ignore[assignment]
            test_run.status = "completed"  # type: ignore[assignment]
            test_run.completed_at = utc_now()
            await self._session.flush()
            await self._session.refresh(test_run)
            return test_run
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("strategy.save_results.db_error", error=str(exc))
            raise DatabaseError("Failed to save test results.") from exc

    async def update_test_run_status(self, test_run_id: UUID, status: str) -> None:
        """Update the status of a test run."""
        try:
            stmt = (
                update(StrategyTestRun)
                .where(StrategyTestRun.id == test_run_id)
                .values(status=status)
            )
            await self._session.execute(stmt)
            await self._session.flush()
        except SQLAlchemyError as exc:
            logger.exception("strategy.update_test_run_status.db_error", error=str(exc))
            raise DatabaseError("Failed to update test run status.") from exc

    async def get_latest_results(self, strategy_id: UUID) -> StrategyTestRun | None:
        """Get the latest completed test run for a strategy."""
        try:
            stmt = (
                select(StrategyTestRun)
                .where(
                    StrategyTestRun.strategy_id == strategy_id,
                    StrategyTestRun.status == "completed",
                )
                .order_by(StrategyTestRun.completed_at.desc())
                .limit(1)
            )
            result = await self._session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as exc:
            logger.exception("strategy.get_latest_results.db_error", error=str(exc))
            raise DatabaseError("Failed to fetch latest test results.") from exc
