"""Repository for AgentStrategySignal CRUD and attribution operations.

All database access for :class:`~src.database.models.AgentStrategySignal` rows
goes through :class:`AgentStrategySignalRepository`.

Dependency direction:
    Services → AgentStrategySignalRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import AgentStrategySignal
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class AgentStrategySignalRepository:
    """Async CRUD and analytics repository for the ``agent_strategy_signals`` table.

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

    async def create(self, signal: AgentStrategySignal) -> AgentStrategySignal:
        """Persist a new AgentStrategySignal row and flush to obtain server defaults.

        Args:
            signal: A fully-populated (but not yet persisted) AgentStrategySignal
                instance.

        Returns:
            The same ``signal`` instance with server-generated columns filled
            (``id``, ``created_at``).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            self._session.add(signal)
            await self._session.flush()
            await self._session.refresh(signal)
            logger.info(
                "agent_strategy_signal.created",
                signal_id=str(signal.id),
                agent_id=str(signal.agent_id),
                strategy_name=signal.strategy_name,
                symbol=signal.symbol,
                action=signal.action,
            )
            return signal
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_strategy_signal.create.integrity_error", error=str(exc))
            raise DatabaseError(
                f"Integrity error while creating agent strategy signal: {exc}"
            ) from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_strategy_signal.create.db_error", error=str(exc))
            raise DatabaseError("Failed to create agent strategy signal.") from exc

    async def bulk_create(self, signals: list[AgentStrategySignal]) -> int:
        """Bulk-insert a list of AgentStrategySignal rows.

        Uses ``session.add_all()`` for efficiency.  The caller is responsible
        for committing.  Server-generated ``id`` and ``created_at`` values are
        *not* refreshed back onto the instances — use :meth:`create` when you
        need them.

        Args:
            signals: A list of AgentStrategySignal instances to persist.  May
                be empty, in which case the method returns 0 immediately.

        Returns:
            The number of rows inserted.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        if not signals:
            return 0
        try:
            self._session.add_all(signals)
            await self._session.flush()
            count = len(signals)
            logger.info(
                "agent_strategy_signal.bulk_created",
                count=count,
                agent_id=str(signals[0].agent_id),
            )
            return count
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_strategy_signal.bulk_create.integrity_error", error=str(exc))
            raise DatabaseError(
                f"Integrity error during bulk create of agent strategy signals: {exc}"
            ) from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_strategy_signal.bulk_create.db_error", error=str(exc))
            raise DatabaseError("Failed to bulk-create agent strategy signals.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_trace(self, trace_id: str) -> Sequence[AgentStrategySignal]:
        """Return all strategy signals that belong to a specific trace.

        Signals from multiple strategies within the same decision cycle share
        the same ``trace_id``.  Results are ordered by ``created_at``
        ascending so callers can observe the order signals were generated.

        Args:
            trace_id: The hex trace identifier grouping related signals.

        Returns:
            A (possibly empty) sequence of AgentStrategySignal instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentStrategySignal)
                .where(AgentStrategySignal.trace_id == trace_id)
                .order_by(AgentStrategySignal.created_at.asc())
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_strategy_signal.get_by_trace.db_error",
                trace_id=trace_id,
                error=str(exc),
            )
            raise DatabaseError("Failed to fetch agent strategy signals by trace.") from exc

    async def get_by_strategy(
        self,
        agent_id: UUID,
        strategy_name: str,
        limit: int = 100,
    ) -> Sequence[AgentStrategySignal]:
        """Return recent signals from a specific strategy for an agent.

        Args:
            agent_id: The owning agent's UUID.
            strategy_name: Name of the strategy component (e.g. ``"ppo_rl"``,
                ``"genetic"``).
            limit: Maximum number of rows to return (default 100).

        Returns:
            A (possibly empty) sequence of AgentStrategySignal instances
            ordered by ``created_at`` descending (most recent first).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentStrategySignal)
                .where(
                    AgentStrategySignal.agent_id == agent_id,
                    AgentStrategySignal.strategy_name == strategy_name,
                )
                .order_by(AgentStrategySignal.created_at.desc())
                .limit(limit)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_strategy_signal.get_by_strategy.db_error",
                agent_id=str(agent_id),
                strategy_name=strategy_name,
                error=str(exc),
            )
            raise DatabaseError("Failed to fetch agent strategy signals by strategy.") from exc

    async def get_attribution(
        self,
        agent_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, object]]:
        """Return per-strategy attribution stats over a time window.

        Aggregates signals by ``strategy_name`` and returns, for each strategy,
        the total signal count and average confidence (where recorded).  This
        supports the ensemble monitoring dashboard.

        Each entry in the returned list is a dict with the shape::

            {
                "strategy_name":    str,
                "signal_count":     int,
                "avg_confidence":   Decimal | None,
            }

        Results are ordered by ``signal_count`` descending so the most active
        strategy appears first.

        Args:
            agent_id: The owning agent's UUID.
            start: Inclusive lower bound on ``created_at`` (UTC).
            end: Exclusive upper bound on ``created_at`` (UTC).

        Returns:
            A list of attribution dicts, one per distinct strategy_name seen in
            the window.  Empty list if no signals exist in the window.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(
                    AgentStrategySignal.strategy_name,
                    func.count(AgentStrategySignal.id).label("signal_count"),
                    func.avg(AgentStrategySignal.confidence).label("avg_confidence"),
                )
                .where(
                    AgentStrategySignal.agent_id == agent_id,
                    AgentStrategySignal.created_at >= start,
                    AgentStrategySignal.created_at < end,
                )
                .group_by(AgentStrategySignal.strategy_name)
                .order_by(func.count(AgentStrategySignal.id).desc())
            )
            result = await self._session.execute(stmt)
            rows = result.all()
            return [
                {
                    "strategy_name": row.strategy_name,
                    "signal_count": row.signal_count,
                    "avg_confidence": (
                        Decimal(str(row.avg_confidence))
                        if row.avg_confidence is not None
                        else None
                    ),
                }
                for row in rows
            ]
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_strategy_signal.get_attribution.db_error",
                agent_id=str(agent_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to compute agent strategy signal attribution.") from exc
