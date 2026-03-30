"""Repository for AgentAuditLog CRUD and query operations.

All database access for :class:`~src.database.models.AgentAuditLog` rows
goes through :class:`AgentAuditLogRepository`.

Dependency direction:
    Services → AgentAuditLogRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import AgentAuditLog
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class AgentAuditLogRepository:
    """Async CRUD and query repository for the ``agent_audit_log`` table.

    Callers are responsible for committing the session; this repository
    does *not* call ``session.commit()``.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(self, entry: AgentAuditLog) -> AgentAuditLog:
        """Persist a single audit log entry and flush to obtain server defaults.

        Args:
            entry: A fully-populated (but not yet persisted) AgentAuditLog
                instance.

        Returns:
            The same ``entry`` instance with server-generated columns filled
            (``id``, ``created_at``).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            self._session.add(entry)
            await self._session.flush()
            await self._session.refresh(entry)
            logger.debug(
                "agent_audit_log.created",
                entry_id=str(entry.id),
                agent_id=str(entry.agent_id),
                action=entry.action,
                outcome=entry.outcome,
            )
            return entry
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_audit_log.create.integrity_error", error=str(exc))
            raise DatabaseError(f"Integrity error while creating audit log entry: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_audit_log.create.db_error", error=str(exc))
            raise DatabaseError("Failed to create audit log entry.") from exc

    async def bulk_create(self, entries: list[AgentAuditLog]) -> int:
        """Bulk-insert a list of AgentAuditLog rows.

        Uses ``session.add_all()`` for efficiency.  The caller is responsible
        for committing.  Server-generated ``id`` and ``created_at`` values are
        *not* refreshed back onto the instances — use :meth:`create` when you
        need them.

        Args:
            entries: A list of AgentAuditLog instances to persist.  May be
                empty, in which case the method returns ``0`` immediately.

        Returns:
            The number of rows inserted.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        if not entries:
            return 0
        try:
            self._session.add_all(entries)
            await self._session.flush()
            count = len(entries)
            logger.info(
                "agent_audit_log.bulk_created",
                count=count,
                agent_id=str(entries[0].agent_id),
            )
            return count
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_audit_log.bulk_create.integrity_error", error=str(exc))
            raise DatabaseError(
                f"Integrity error during bulk create of audit log entries: {exc}"
            ) from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_audit_log.bulk_create.db_error", error=str(exc))
            raise DatabaseError("Failed to bulk-create audit log entries.") from exc

    async def prune_old(self, agent_id: UUID, older_than: datetime) -> int:
        """Delete audit log entries older than a given timestamp for an agent.

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
                delete(AgentAuditLog)
                .where(
                    AgentAuditLog.agent_id == agent_id,
                    AgentAuditLog.created_at < older_than,
                )
                .returning(AgentAuditLog.id)
            )
            result = await self._session.execute(stmt)
            deleted_count = len(result.scalars().all())
            await self._session.flush()
            logger.info(
                "agent_audit_log.pruned",
                agent_id=str(agent_id),
                older_than=older_than.isoformat(),
                deleted=deleted_count,
            )
            return deleted_count
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "agent_audit_log.prune_old.db_error",
                agent_id=str(agent_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to prune old audit log entries.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_recent(
        self,
        agent_id: UUID,
        limit: int = 100,
        outcome: str | None = None,
    ) -> Sequence[AgentAuditLog]:
        """Return the most recent audit log entries for an agent, newest first.

        Args:
            agent_id: The owning agent's UUID.
            limit: Maximum number of rows to return (default 100).
            outcome: Optional filter — ``"allow"``, ``"deny"``, or ``None`` for
                all outcomes.

        Returns:
            A (possibly empty) sequence of AgentAuditLog instances ordered by
            ``created_at`` descending.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentAuditLog).where(AgentAuditLog.agent_id == agent_id)
            if outcome is not None:
                stmt = stmt.where(AgentAuditLog.outcome == outcome)
            stmt = stmt.order_by(AgentAuditLog.created_at.desc()).limit(limit)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_audit_log.get_recent.db_error",
                agent_id=str(agent_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to fetch recent audit log entries.") from exc

    async def get_range(
        self,
        agent_id: UUID,
        since: datetime,
        until: datetime | None = None,
        outcome: str | None = None,
        limit: int = 500,
    ) -> Sequence[AgentAuditLog]:
        """Return audit log entries for an agent within a time range.

        Args:
            agent_id: The owning agent's UUID.
            since: Inclusive lower bound on ``created_at`` (UTC).
            until: Exclusive upper bound on ``created_at`` (UTC).  If
                ``None``, no upper bound is applied.
            outcome: Optional filter — ``"allow"``, ``"deny"``, or ``None``
                for all outcomes.
            limit: Maximum rows to return (default 500).

        Returns:
            A (possibly empty) sequence of AgentAuditLog instances ordered by
            ``created_at`` ascending (chronological order).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentAuditLog).where(
                AgentAuditLog.agent_id == agent_id,
                AgentAuditLog.created_at >= since,
            )
            if until is not None:
                stmt = stmt.where(AgentAuditLog.created_at < until)
            if outcome is not None:
                stmt = stmt.where(AgentAuditLog.outcome == outcome)
            stmt = stmt.order_by(AgentAuditLog.created_at.asc()).limit(limit)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_audit_log.get_range.db_error",
                agent_id=str(agent_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to fetch audit log entries in range.") from exc

    async def get_outcome_counts(
        self,
        agent_id: UUID,
        since: datetime,
        until: datetime | None = None,
    ) -> dict[str, int]:
        """Return per-outcome event counts for an agent over a time window.

        Args:
            agent_id: The owning agent's UUID.
            since: Inclusive lower bound on ``created_at`` (UTC).
            until: Exclusive upper bound on ``created_at`` (UTC).  Defaults
                to no upper bound.

        Returns:
            A dict with keys ``"allow"`` and ``"deny"`` mapping to their
            respective row counts in the requested window::

                {"allow": 142, "deny": 7}

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(
                    AgentAuditLog.outcome,
                    func.count(AgentAuditLog.id).label("cnt"),
                )
                .where(
                    AgentAuditLog.agent_id == agent_id,
                    AgentAuditLog.created_at >= since,
                )
                .group_by(AgentAuditLog.outcome)
            )
            if until is not None:
                stmt = stmt.where(AgentAuditLog.created_at < until)

            result = await self._session.execute(stmt)
            counts: dict[str, int] = {"allow": 0, "deny": 0}
            for row in result.all():
                counts[row.outcome] = row.cnt
            return counts
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_audit_log.get_outcome_counts.db_error",
                agent_id=str(agent_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to compute audit log outcome counts.") from exc
