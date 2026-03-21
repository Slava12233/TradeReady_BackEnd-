"""Repository for AgentBudget operations.

All database access for :class:`~src.database.models.AgentBudget` rows goes
through :class:`AgentBudgetRepository`.

One row per agent enforced by the UNIQUE constraint on ``agent_id``.
Counter increments use atomic ``UPDATE ... SET col = col + delta`` to prevent
race conditions from concurrent order submissions.

Dependency direction:
    Services → AgentBudgetRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import AgentBudget
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class AgentBudgetNotFoundError(Exception):
    """Raised when an agent budget record cannot be found."""

    def __init__(
        self,
        message: str = "Agent budget not found.",
        *,
        agent_id: UUID | None = None,
    ) -> None:
        self.agent_id = agent_id
        super().__init__(message)


class AgentBudgetRepository:
    """Async repository for the ``agent_budgets`` table.

    There is at most one row per agent (UNIQUE constraint on ``agent_id``).
    Use :meth:`upsert` to create or replace the budget record atomically.

    Counter increments (:meth:`increment_trades_today`,
    :meth:`increment_exposure_today`, :meth:`increment_loss_today`) are
    done via atomic ``UPDATE col = col + delta`` statements so that
    concurrent order submissions cannot overwrite each other.

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

    async def upsert(self, budget: AgentBudget) -> AgentBudget:
        """Insert or update the budget limits for an agent.

        Uses PostgreSQL ``INSERT ... ON CONFLICT DO UPDATE`` to atomically
        create or replace the limits (not counters — counters are managed
        separately via the increment methods).

        Args:
            budget: A fully-populated AgentBudget instance containing the
                desired limit values.  Counter fields (``trades_today``,
                ``exposure_today``, ``loss_today``) on the input object are
                ignored on update — only the limit columns are replaced.

        Returns:
            The refreshed AgentBudget instance.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                pg_insert(AgentBudget)
                .values(
                    agent_id=budget.agent_id,
                    max_trades_per_day=budget.max_trades_per_day,
                    max_exposure_pct=budget.max_exposure_pct,
                    max_daily_loss_pct=budget.max_daily_loss_pct,
                    max_position_size_pct=budget.max_position_size_pct,
                )
                .on_conflict_do_update(
                    index_elements=["agent_id"],
                    set_={
                        "max_trades_per_day": budget.max_trades_per_day,
                        "max_exposure_pct": budget.max_exposure_pct,
                        "max_daily_loss_pct": budget.max_daily_loss_pct,
                        "max_position_size_pct": budget.max_position_size_pct,
                    },
                )
                .returning(AgentBudget)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise DatabaseError("Upsert returned no row for agent budget.")
            await self._session.flush()
            logger.info("agent_budget.upserted", agent_id=str(budget.agent_id))
            return row
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_budget.upsert.integrity_error", agent_id=str(budget.agent_id), error=str(exc))
            raise DatabaseError(f"Integrity error while upserting agent budget: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_budget.upsert.db_error", agent_id=str(budget.agent_id), error=str(exc))
            raise DatabaseError("Failed to upsert agent budget.") from exc

    async def increment_trades_today(self, agent_id: UUID, delta: int = 1) -> AgentBudget:
        """Atomically increment ``trades_today`` by ``delta``.

        The increment is done in a single ``UPDATE col = col + delta``
        statement to prevent lost-update races under concurrent order
        submissions.

        Args:
            agent_id: The agent's UUID.
            delta: Amount to add (default 1).  May be negative to undo.

        Returns:
            The refreshed AgentBudget instance.

        Raises:
            AgentBudgetNotFoundError: If no budget record exists for ``agent_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        from sqlalchemy import update  # noqa: PLC0415

        try:
            stmt = (
                update(AgentBudget)
                .where(AgentBudget.agent_id == agent_id)
                .values(trades_today=AgentBudget.trades_today + delta)
                .returning(AgentBudget)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentBudgetNotFoundError(agent_id=agent_id)
            logger.info("agent_budget.trades_today.incremented", agent_id=str(agent_id), delta=delta)
            return row
        except AgentBudgetNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_budget.increment_trades_today.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to increment trades_today.") from exc

    async def increment_exposure_today(self, agent_id: UUID, delta: Decimal) -> AgentBudget:
        """Atomically increment ``exposure_today`` by ``delta`` USDT.

        Args:
            agent_id: The agent's UUID.
            delta: Amount in USDT to add.  May be negative when a position closes.

        Returns:
            The refreshed AgentBudget instance.

        Raises:
            AgentBudgetNotFoundError: If no budget record exists for ``agent_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        from sqlalchemy import update  # noqa: PLC0415

        try:
            stmt = (
                update(AgentBudget)
                .where(AgentBudget.agent_id == agent_id)
                .values(exposure_today=AgentBudget.exposure_today + delta)
                .returning(AgentBudget)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentBudgetNotFoundError(agent_id=agent_id)
            logger.info("agent_budget.exposure_today.incremented", agent_id=str(agent_id), delta=str(delta))
            return row
        except AgentBudgetNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_budget.increment_exposure_today.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to increment exposure_today.") from exc

    async def increment_loss_today(self, agent_id: UUID, delta: Decimal) -> AgentBudget:
        """Atomically increment ``loss_today`` by ``delta`` USDT.

        Args:
            agent_id: The agent's UUID.
            delta: Realised loss amount in USDT (positive means more loss,
                negative means a gain reduces accumulated loss).

        Returns:
            The refreshed AgentBudget instance.

        Raises:
            AgentBudgetNotFoundError: If no budget record exists for ``agent_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        from sqlalchemy import update  # noqa: PLC0415

        try:
            stmt = (
                update(AgentBudget)
                .where(AgentBudget.agent_id == agent_id)
                .values(loss_today=AgentBudget.loss_today + delta)
                .returning(AgentBudget)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentBudgetNotFoundError(agent_id=agent_id)
            logger.info("agent_budget.loss_today.incremented", agent_id=str(agent_id), delta=str(delta))
            return row
        except AgentBudgetNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_budget.increment_loss_today.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to increment loss_today.") from exc

    async def reset_daily(self, agent_id: UUID) -> AgentBudget:
        """Reset daily counters to zero and update ``last_reset_at``.

        Called by the Celery beat task at midnight UTC to start each trading day
        with fresh counters.

        Args:
            agent_id: The agent's UUID.

        Returns:
            The refreshed AgentBudget instance.

        Raises:
            AgentBudgetNotFoundError: If no budget record exists for ``agent_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        from sqlalchemy import func, update  # noqa: PLC0415

        try:
            stmt = (
                update(AgentBudget)
                .where(AgentBudget.agent_id == agent_id)
                .values(
                    trades_today=0,
                    exposure_today=Decimal("0"),
                    loss_today=Decimal("0"),
                    last_reset_at=func.now(),
                )
                .returning(AgentBudget)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentBudgetNotFoundError(agent_id=agent_id)
            await self._session.flush()
            logger.info("agent_budget.daily_reset", agent_id=str(agent_id))
            return row
        except AgentBudgetNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_budget.reset_daily.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to reset agent daily budget.") from exc

    async def delete(self, agent_id: UUID) -> None:
        """Delete the budget record for an agent.

        Args:
            agent_id: The agent's UUID.

        Raises:
            AgentBudgetNotFoundError: If no budget record exists.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentBudget).where(AgentBudget.agent_id == agent_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentBudgetNotFoundError(agent_id=agent_id)
            await self._session.delete(row)
            await self._session.flush()
            logger.info("agent_budget.deleted", agent_id=str(agent_id))
        except AgentBudgetNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_budget.delete.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to delete agent budget.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_agent(self, agent_id: UUID) -> AgentBudget:
        """Fetch the budget record for an agent.

        Args:
            agent_id: The agent's UUID.

        Returns:
            The matching AgentBudget instance.

        Raises:
            AgentBudgetNotFoundError: If no budget record exists for ``agent_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentBudget).where(AgentBudget.agent_id == agent_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentBudgetNotFoundError(agent_id=agent_id)
            return row
        except AgentBudgetNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("agent_budget.get_by_agent.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to fetch agent budget.") from exc
