"""Repository for Training Run CRUD operations.

All database access for :class:`~src.database.models.TrainingRun` and
:class:`~src.database.models.TrainingEpisode` goes through
:class:`TrainingRunRepository`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import TrainingEpisode, TrainingRun
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class TrainingRunNotFoundError(Exception):
    """Raised when a training run cannot be found."""

    def __init__(self, message: str = "Training run not found.", *, run_id: UUID | None = None) -> None:
        self.run_id = run_id
        super().__init__(message)


class TrainingRunRepository:
    """Async CRUD repository for training run tables.

    Callers are responsible for committing the session.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Training Run CRUD
    # ------------------------------------------------------------------

    async def create_run(
        self,
        run_id: UUID,
        account_id: UUID,
        config: dict[str, Any] | None = None,
        strategy_id: UUID | None = None,
    ) -> TrainingRun:
        """Create a new training run."""
        try:
            run = TrainingRun(
                id=run_id,
                account_id=account_id,
                strategy_id=strategy_id,
                config=config,
                status="running",
                episodes_completed=0,
            )
            self._session.add(run)
            await self._session.flush()
            await self._session.refresh(run)
            logger.info("training.run_created", run_id=str(run_id))
            return run
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("training.create_run.db_error", error=str(exc))
            raise DatabaseError("Failed to create training run.") from exc

    async def get_run(self, run_id: UUID) -> TrainingRun | None:
        """Get a training run by ID."""
        try:
            stmt = select(TrainingRun).where(TrainingRun.id == run_id)
            result = await self._session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as exc:
            logger.exception("training.get_run.db_error", error=str(exc))
            raise DatabaseError("Failed to fetch training run.") from exc

    async def list_runs(
        self,
        account_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[TrainingRun]:
        """List training runs for an account."""
        try:
            stmt = select(TrainingRun).where(TrainingRun.account_id == account_id)
            if status is not None:
                stmt = stmt.where(TrainingRun.status == status)
            stmt = stmt.order_by(TrainingRun.started_at.desc()).limit(limit).offset(offset)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("training.list_runs.db_error", error=str(exc))
            raise DatabaseError("Failed to list training runs.") from exc

    async def add_episode(
        self,
        run_id: UUID,
        episode_number: int,
        session_id: UUID | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> TrainingEpisode:
        """Add an episode result to a training run."""
        try:
            episode = TrainingEpisode(
                training_run_id=run_id,
                episode_number=episode_number,
                backtest_session_id=session_id,
                metrics=metrics,
            )
            self._session.add(episode)
            await self._session.flush()
            await self._session.refresh(episode)

            # Increment episodes_completed
            await self._session.execute(
                update(TrainingRun)
                .where(TrainingRun.id == run_id)
                .values(episodes_completed=TrainingRun.episodes_completed + 1)
            )
            await self._session.flush()
            return episode
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("training.add_episode.db_error", error=str(exc))
            raise DatabaseError("Failed to add training episode.") from exc

    async def complete_run(
        self,
        run_id: UUID,
        aggregate_stats: dict[str, Any] | None = None,
        learning_curve: dict[str, Any] | None = None,
    ) -> TrainingRun | None:
        """Mark a training run as complete with aggregate stats."""
        try:
            from src.utils.helpers import utc_now  # noqa: PLC0415

            run = await self.get_run(run_id)
            if run is None:
                return None
            run.status = "completed"  # type: ignore[assignment]
            run.completed_at = utc_now()
            run.aggregate_stats = aggregate_stats  # type: ignore[assignment]
            run.learning_curve = learning_curve  # type: ignore[assignment]
            await self._session.flush()
            await self._session.refresh(run)
            logger.info("training.run_completed", run_id=str(run_id))
            return run
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("training.complete_run.db_error", error=str(exc))
            raise DatabaseError("Failed to complete training run.") from exc

    async def get_episodes(
        self,
        run_id: UUID,
        *,
        limit: int = 1000,
        offset: int = 0,
    ) -> Sequence[TrainingEpisode]:
        """Get episodes for a training run."""
        try:
            stmt = (
                select(TrainingEpisode)
                .where(TrainingEpisode.training_run_id == run_id)
                .order_by(TrainingEpisode.episode_number)
                .limit(limit)
                .offset(offset)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("training.get_episodes.db_error", error=str(exc))
            raise DatabaseError("Failed to get training episodes.") from exc

    async def get_runs_by_ids(self, run_ids: list[UUID]) -> Sequence[TrainingRun]:
        """Get multiple training runs by their IDs."""
        try:
            stmt = select(TrainingRun).where(TrainingRun.id.in_(run_ids))
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("training.get_runs_by_ids.db_error", error=str(exc))
            raise DatabaseError("Failed to fetch training runs.") from exc
