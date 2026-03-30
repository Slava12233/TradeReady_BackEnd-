"""Repository for AgentApiCall CRUD and analytics operations.

All database access for :class:`~src.database.models.AgentApiCall` rows goes
through :class:`AgentApiCallRepository`.

Dependency direction:
    Services → AgentApiCallRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import AgentApiCall
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class AgentApiCallRepository:
    """Async CRUD and analytics repository for the ``agent_api_calls`` table.

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

    async def create(self, api_call: AgentApiCall) -> AgentApiCall:
        """Persist a new AgentApiCall row and flush to obtain server defaults.

        Args:
            api_call: A fully-populated (but not yet persisted) AgentApiCall
                instance.

        Returns:
            The same ``api_call`` instance with server-generated columns filled
            (``id``, ``created_at``).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            self._session.add(api_call)
            await self._session.flush()
            await self._session.refresh(api_call)
            logger.info(
                "agent_api_call.created",
                call_id=str(api_call.id),
                agent_id=str(api_call.agent_id),
                channel=api_call.channel,
                endpoint=api_call.endpoint,
            )
            return api_call
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_api_call.create.integrity_error", error=str(exc))
            raise DatabaseError(f"Integrity error while creating agent API call: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_api_call.create.db_error", error=str(exc))
            raise DatabaseError("Failed to create agent API call.") from exc

    async def bulk_create(self, api_calls: list[AgentApiCall]) -> int:
        """Bulk-insert a list of AgentApiCall rows.

        Uses ``session.add_all()`` for efficiency.  The caller is responsible
        for committing.  Server-generated ``id`` and ``created_at`` values are
        *not* refreshed back onto the instances — use :meth:`create` when you
        need them.

        Args:
            api_calls: A list of AgentApiCall instances to persist.  May be
                empty, in which case the method returns 0 immediately.

        Returns:
            The number of rows inserted.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        if not api_calls:
            return 0
        try:
            self._session.add_all(api_calls)
            await self._session.flush()
            count = len(api_calls)
            logger.info(
                "agent_api_call.bulk_created",
                count=count,
                agent_id=str(api_calls[0].agent_id),
            )
            return count
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_api_call.bulk_create.integrity_error", error=str(exc))
            raise DatabaseError(f"Integrity error during bulk create of agent API calls: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_api_call.bulk_create.db_error", error=str(exc))
            raise DatabaseError("Failed to bulk-create agent API calls.") from exc

    async def prune_old(self, agent_id: UUID, older_than: datetime) -> int:
        """Delete API call records older than a given timestamp for an agent.

        Args:
            agent_id: The owning agent's UUID.
            older_than: UTC datetime threshold — rows with ``created_at``
                strictly before this value are deleted.

        Returns:
            Number of rows deleted.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                delete(AgentApiCall)
                .where(
                    AgentApiCall.agent_id == agent_id,
                    AgentApiCall.created_at < older_than,
                )
                .returning(AgentApiCall.id)
            )
            result = await self._session.execute(stmt)
            deleted_count = len(result.scalars().all())
            await self._session.flush()
            logger.info(
                "agent_api_call.pruned",
                agent_id=str(agent_id),
                older_than=older_than.isoformat(),
                deleted=deleted_count,
            )
            return deleted_count
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "agent_api_call.prune_old.db_error",
                agent_id=str(agent_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to prune old agent API calls.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_trace(
        self,
        agent_id: UUID,
        trace_id: str,
    ) -> Sequence[AgentApiCall]:
        """Return all API calls that belong to a specific trace.

        Args:
            agent_id: The owning agent's UUID — used to scope the query and
                leverage the composite index on ``(agent_id, trace_id)``.
            trace_id: The hex trace identifier grouping related calls.

        Returns:
            A (possibly empty) sequence of AgentApiCall instances ordered by
            ``created_at`` ascending (call order within the trace).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentApiCall)
                .where(
                    AgentApiCall.agent_id == agent_id,
                    AgentApiCall.trace_id == trace_id,
                )
                .order_by(AgentApiCall.created_at.asc())
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_api_call.get_by_trace.db_error",
                agent_id=str(agent_id),
                trace_id=trace_id,
                error=str(exc),
            )
            raise DatabaseError("Failed to fetch agent API calls by trace.") from exc

    async def get_recent(
        self,
        agent_id: UUID,
        limit: int = 100,
    ) -> Sequence[AgentApiCall]:
        """Return the most recent API calls for an agent, newest first.

        Args:
            agent_id: The owning agent's UUID.
            limit: Maximum number of rows to return (default 100).

        Returns:
            A (possibly empty) sequence of AgentApiCall instances ordered by
            ``created_at`` descending.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentApiCall)
                .where(AgentApiCall.agent_id == agent_id)
                .order_by(AgentApiCall.created_at.desc())
                .limit(limit)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_api_call.get_recent.db_error",
                agent_id=str(agent_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to fetch recent agent API calls.") from exc

    async def get_stats(
        self,
        agent_id: UUID,
        start: datetime,
        end: datetime,
    ) -> dict[str, object]:
        """Return aggregated call statistics for an agent over a time window.

        Executes a single aggregate query covering the requested time range and
        returns a dict with::

            {
                "total_calls":   int,
                "avg_latency_ms": Decimal | None,
                "error_rate":    float,          # fraction in [0, 1]
                "by_endpoint":   {endpoint: count, ...},
            }

        The ``by_endpoint`` breakdown lists every distinct ``endpoint`` value
        seen in the window together with its call count, ordered by count
        descending.

        Args:
            agent_id: The owning agent's UUID.
            start: Inclusive lower bound on ``created_at`` (UTC).
            end: Exclusive upper bound on ``created_at`` (UTC).

        Returns:
            A dict containing the aggregated statistics described above.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            # --- overall aggregates ---
            agg_stmt = select(
                func.count(AgentApiCall.id).label("total_calls"),
                func.avg(AgentApiCall.latency_ms).label("avg_latency_ms"),
                func.count(AgentApiCall.error).filter(AgentApiCall.error.is_not(None)).label("error_count"),
            ).where(
                AgentApiCall.agent_id == agent_id,
                AgentApiCall.created_at >= start,
                AgentApiCall.created_at < end,
            )
            agg_result = await self._session.execute(agg_stmt)
            agg_row = agg_result.one()

            total_calls: int = agg_row.total_calls or 0
            avg_latency_ms: Decimal | None = (
                Decimal(str(agg_row.avg_latency_ms)) if agg_row.avg_latency_ms is not None else None
            )
            error_count: int = agg_row.error_count or 0
            error_rate: float = (error_count / total_calls) if total_calls > 0 else 0.0

            # --- per-endpoint breakdown ---
            by_endpoint_stmt = (
                select(
                    AgentApiCall.endpoint,
                    func.count(AgentApiCall.id).label("call_count"),
                )
                .where(
                    AgentApiCall.agent_id == agent_id,
                    AgentApiCall.created_at >= start,
                    AgentApiCall.created_at < end,
                )
                .group_by(AgentApiCall.endpoint)
                .order_by(func.count(AgentApiCall.id).desc())
            )
            by_endpoint_result = await self._session.execute(by_endpoint_stmt)
            by_endpoint: dict[str, int] = {row.endpoint: row.call_count for row in by_endpoint_result.all()}

            return {
                "total_calls": total_calls,
                "avg_latency_ms": avg_latency_ms,
                "error_rate": error_rate,
                "by_endpoint": by_endpoint,
            }
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_api_call.get_stats.db_error",
                agent_id=str(agent_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to compute agent API call stats.") from exc
