"""Repository for AgentDecision CRUD operations.

All database access for :class:`~src.database.models.AgentDecision` rows goes
through :class:`AgentDecisionRepository`.

Dependency direction:
    Services → AgentDecisionRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import AgentDecision
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class AgentDecisionNotFoundError(Exception):
    """Raised when an agent decision cannot be found."""

    def __init__(
        self,
        message: str = "Agent decision not found.",
        *,
        decision_id: UUID | None = None,
    ) -> None:
        self.decision_id = decision_id
        super().__init__(message)


class AgentDecisionRepository:
    """Async CRUD repository for the ``agent_decisions`` table.

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

    async def create(self, decision: AgentDecision) -> AgentDecision:
        """Persist a new AgentDecision row and flush to obtain server defaults.

        Args:
            decision: A fully-populated (but not yet persisted) AgentDecision instance.

        Returns:
            The same ``decision`` instance with server-generated columns filled.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            self._session.add(decision)
            await self._session.flush()
            await self._session.refresh(decision)
            logger.info(
                "agent_decision.created",
                decision_id=str(decision.id),
                agent_id=str(decision.agent_id),
                decision_type=decision.decision_type,
                direction=decision.direction,
            )
            return decision
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_decision.create.integrity_error", error=str(exc))
            raise DatabaseError(f"Integrity error while creating agent decision: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_decision.create.db_error", error=str(exc))
            raise DatabaseError("Failed to create agent decision.") from exc

    async def update_outcome(
        self,
        decision_id: UUID,
        *,
        outcome_pnl: Decimal,
        outcome_recorded_at: datetime,
    ) -> AgentDecision:
        """Write back the realised outcome of a decision once the order settles.

        Args:
            decision_id: The decision's UUID.
            outcome_pnl: Realised PnL in USDT for the linked order.
            outcome_recorded_at: UTC timestamp when the outcome was recorded.

        Returns:
            The refreshed AgentDecision instance.

        Raises:
            AgentDecisionNotFoundError: If no decision exists with ``decision_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                update(AgentDecision)
                .where(AgentDecision.id == decision_id)
                .values(outcome_pnl=outcome_pnl, outcome_recorded_at=outcome_recorded_at)
                .returning(AgentDecision)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentDecisionNotFoundError(decision_id=decision_id)
            logger.info(
                "agent_decision.outcome_updated",
                decision_id=str(decision_id),
                outcome_pnl=str(outcome_pnl),
            )
            return row
        except AgentDecisionNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_decision.update_outcome.db_error", decision_id=str(decision_id), error=str(exc))
            raise DatabaseError("Failed to update agent decision outcome.") from exc

    async def delete(self, decision_id: UUID) -> None:
        """Permanently delete an agent decision row.

        Args:
            decision_id: The decision's UUID.

        Raises:
            AgentDecisionNotFoundError: If no decision exists with ``decision_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentDecision).where(AgentDecision.id == decision_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentDecisionNotFoundError(decision_id=decision_id)
            await self._session.delete(row)
            await self._session.flush()
            logger.info("agent_decision.deleted", decision_id=str(decision_id))
        except AgentDecisionNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_decision.delete.db_error", decision_id=str(decision_id), error=str(exc))
            raise DatabaseError("Failed to delete agent decision.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, decision_id: UUID) -> AgentDecision:
        """Fetch a single agent decision by its primary-key UUID.

        Args:
            decision_id: The decision's UUID primary key.

        Returns:
            The matching AgentDecision instance.

        Raises:
            AgentDecisionNotFoundError: If no decision with ``decision_id`` exists.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentDecision).where(AgentDecision.id == decision_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentDecisionNotFoundError(decision_id=decision_id)
            return row
        except AgentDecisionNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("agent_decision.get_by_id.db_error", decision_id=str(decision_id), error=str(exc))
            raise DatabaseError("Failed to fetch agent decision by ID.") from exc

    async def list_by_agent(
        self,
        agent_id: UUID,
        *,
        decision_type: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AgentDecision]:
        """Return decisions for an agent, newest first.

        Args:
            agent_id: The owning agent's UUID.
            decision_type: Optional filter by decision type (``trade``, ``hold``,
                ``exit``, ``rebalance``).
            symbol: Optional filter by trading symbol.
            limit: Maximum rows to return.
            offset: Rows to skip for pagination.

        Returns:
            A (possibly empty) sequence of AgentDecision instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentDecision)
                .where(AgentDecision.agent_id == agent_id)
                .order_by(AgentDecision.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if decision_type is not None:
                stmt = stmt.where(AgentDecision.decision_type == decision_type)
            if symbol is not None:
                stmt = stmt.where(AgentDecision.symbol == symbol)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("agent_decision.list_by_agent.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to list agent decisions.") from exc

    async def get_by_trace(
        self,
        agent_id: UUID,
        trace_id: str,
    ) -> AgentDecision | None:
        """Return the decision belonging to a specific trace for an agent.

        Args:
            agent_id: The owning agent's UUID — scopes the query so one agent
                cannot read another agent's decisions.
            trace_id: The hex trace identifier assigned to the decision cycle.

        Returns:
            The matching :class:`AgentDecision` instance, or ``None`` if no
            decision with the given ``trace_id`` exists for this agent.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentDecision)
                .where(
                    AgentDecision.agent_id == agent_id,
                    AgentDecision.trace_id == trace_id,
                )
                .limit(1)
            )
            result = await self._session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_decision.get_by_trace.db_error",
                agent_id=str(agent_id),
                trace_id=trace_id,
                error=str(exc),
            )
            raise DatabaseError("Failed to fetch agent decision by trace.") from exc

    async def analyze(
        self,
        agent_id: UUID,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        min_confidence: Decimal | None = None,
        direction: str | None = None,
        pnl_outcome: str | None = None,
        limit: int = 200,
    ) -> Sequence[AgentDecision]:
        """Return decisions matching analysis filters for an agent.

        All parameters are optional filters that narrow the result set.
        Results are ordered newest-first.

        Args:
            agent_id: The owning agent's UUID.
            start: Inclusive lower bound on ``created_at`` (UTC). ``None``
                means no lower bound.
            end: Exclusive upper bound on ``created_at`` (UTC). ``None``
                means no upper bound.
            min_confidence: When provided, only decisions with
                ``confidence >= min_confidence`` are returned.
            direction: When provided, only decisions with this ``direction``
                value are returned (e.g. ``"buy"``, ``"sell"``, ``"hold"``).
            pnl_outcome: One of ``"positive"``, ``"negative"``, or ``"all"``
                (default ``"all"``). Filters decisions by the sign of
                ``outcome_pnl``; ``"positive"`` requires ``outcome_pnl > 0``,
                ``"negative"`` requires ``outcome_pnl < 0``.
            limit: Maximum rows to return (default 200, hard cap in the
                route handler).

        Returns:
            A (possibly empty) sequence of :class:`AgentDecision` instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        from sqlalchemy import and_  # noqa: PLC0415

        try:
            conditions = [AgentDecision.agent_id == agent_id]
            if start is not None:
                conditions.append(AgentDecision.created_at >= start)
            if end is not None:
                conditions.append(AgentDecision.created_at < end)
            if min_confidence is not None:
                conditions.append(AgentDecision.confidence >= min_confidence)
            if direction is not None:
                conditions.append(AgentDecision.direction == direction)
            if pnl_outcome == "positive":
                conditions.append(AgentDecision.outcome_pnl > 0)
            elif pnl_outcome == "negative":
                conditions.append(AgentDecision.outcome_pnl < 0)

            stmt = (
                select(AgentDecision)
                .where(and_(*conditions))
                .order_by(AgentDecision.created_at.desc())
                .limit(limit)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_decision.analyze.db_error",
                agent_id=str(agent_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to analyze agent decisions.") from exc

    async def find_unresolved(
        self,
        agent_id: UUID,
        *,
        limit: int = 100,
    ) -> Sequence[AgentDecision]:
        """Return decisions that have no outcome recorded yet.

        Unresolved decisions are those where ``outcome_recorded_at`` is NULL —
        i.e., the linked order has not yet settled.

        Args:
            agent_id: The owning agent's UUID.
            limit: Maximum rows to return.

        Returns:
            A (possibly empty) sequence of unresolved AgentDecision instances,
            oldest first (so the system can process them in order).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentDecision)
                .where(
                    AgentDecision.agent_id == agent_id,
                    AgentDecision.outcome_recorded_at.is_(None),
                    AgentDecision.order_id.is_not(None),
                )
                .order_by(AgentDecision.created_at.asc())
                .limit(limit)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("agent_decision.find_unresolved.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to find unresolved agent decisions.") from exc
