"""Repository for AgentPerformance CRUD operations.

All database access for :class:`~src.database.models.AgentPerformance` rows
goes through :class:`AgentPerformanceRepository`.

Dependency direction:
    Services → AgentPerformanceRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import AgentPerformance
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class AgentPerformanceNotFoundError(Exception):
    """Raised when an agent performance record cannot be found."""

    def __init__(
        self,
        message: str = "Agent performance record not found.",
        *,
        performance_id: UUID | None = None,
    ) -> None:
        self.performance_id = performance_id
        super().__init__(message)


class AgentPerformanceRepository:
    """Async CRUD repository for the ``agent_performance`` table.

    Callers are responsible for committing the session; this repo
    does *not* call ``session.commit()``.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(self, performance: AgentPerformance) -> AgentPerformance:
        """Persist a new AgentPerformance row and flush to obtain server defaults.

        Args:
            performance: A fully-populated (but not yet persisted) AgentPerformance
                instance.

        Returns:
            The same ``performance`` instance with server-generated columns filled.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            self._session.add(performance)
            await self._session.flush()
            await self._session.refresh(performance)
            logger.info(
                "agent_performance.created",
                performance_id=str(performance.id),
                agent_id=str(performance.agent_id),
                strategy_name=performance.strategy_name,
                period=performance.period,
            )
            return performance
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_performance.create.integrity_error", error=str(exc))
            raise DatabaseError(f"Integrity error while creating agent performance: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_performance.create.db_error", error=str(exc))
            raise DatabaseError("Failed to create agent performance record.") from exc

    async def delete(self, performance_id: UUID) -> None:
        """Permanently delete an agent performance row.

        Args:
            performance_id: The performance record's UUID.

        Raises:
            AgentPerformanceNotFoundError: If no record exists with ``performance_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentPerformance).where(AgentPerformance.id == performance_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentPerformanceNotFoundError(performance_id=performance_id)
            await self._session.delete(row)
            await self._session.flush()
            logger.info("agent_performance.deleted", performance_id=str(performance_id))
        except AgentPerformanceNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "agent_performance.delete.db_error",
                performance_id=str(performance_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to delete agent performance record.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, performance_id: UUID) -> AgentPerformance:
        """Fetch a single performance record by its primary-key UUID.

        Args:
            performance_id: The performance record's UUID primary key.

        Returns:
            The matching AgentPerformance instance.

        Raises:
            AgentPerformanceNotFoundError: If no record with ``performance_id`` exists.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentPerformance).where(AgentPerformance.id == performance_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentPerformanceNotFoundError(performance_id=performance_id)
            return row
        except AgentPerformanceNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_performance.get_by_id.db_error",
                performance_id=str(performance_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to fetch agent performance by ID.") from exc

    async def list_by_agent(
        self,
        agent_id: UUID,
        *,
        period: str | None = None,
        strategy_name: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AgentPerformance]:
        """Return performance records for an agent, newest first.

        Args:
            agent_id: The owning agent's UUID.
            period: Optional filter by aggregation window (``daily``, ``weekly``,
                or ``monthly``).
            strategy_name: Optional filter by strategy label.
            since: Optional lower bound on ``period_start`` (inclusive).
            until: Optional upper bound on ``period_start`` (inclusive).
            limit: Maximum rows to return.
            offset: Rows to skip for pagination.

        Returns:
            A (possibly empty) sequence of AgentPerformance instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentPerformance)
                .where(AgentPerformance.agent_id == agent_id)
                .order_by(AgentPerformance.period_start.desc())
                .limit(limit)
                .offset(offset)
            )
            if period is not None:
                stmt = stmt.where(AgentPerformance.period == period)
            if strategy_name is not None:
                stmt = stmt.where(AgentPerformance.strategy_name == strategy_name)
            if since is not None:
                stmt = stmt.where(AgentPerformance.period_start >= since)
            if until is not None:
                stmt = stmt.where(AgentPerformance.period_start <= until)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("agent_performance.list_by_agent.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to list agent performance records.") from exc

    async def latest_per_strategy(
        self,
        agent_id: UUID,
        period: str,
    ) -> Sequence[AgentPerformance]:
        """Return the most recent performance record per strategy for a given period.

        Useful for building a strategy comparison dashboard where each strategy
        should be represented by its latest closed window.

        Args:
            agent_id: The owning agent's UUID.
            period: Aggregation window (``daily``, ``weekly``, or ``monthly``).

        Returns:
            A sequence of AgentPerformance instances, one per unique
            ``strategy_name``, each being the record with the most recent
            ``period_start``.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            from sqlalchemy import func  # noqa: PLC0415

            # Subquery: max period_start per strategy for this agent+period.
            sub = (
                select(
                    AgentPerformance.strategy_name,
                    func.max(AgentPerformance.period_start).label("max_start"),
                )
                .where(
                    AgentPerformance.agent_id == agent_id,
                    AgentPerformance.period == period,
                )
                .group_by(AgentPerformance.strategy_name)
                .subquery()
            )
            stmt = (
                select(AgentPerformance)
                .join(
                    sub,
                    (AgentPerformance.strategy_name == sub.c.strategy_name)
                    & (AgentPerformance.period_start == sub.c.max_start),
                )
                .where(
                    AgentPerformance.agent_id == agent_id,
                    AgentPerformance.period == period,
                )
                .order_by(AgentPerformance.strategy_name.asc())
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_performance.latest_per_strategy.db_error",
                agent_id=str(agent_id),
                period=period,
                error=str(exc),
            )
            raise DatabaseError("Failed to fetch latest performance per strategy.") from exc
