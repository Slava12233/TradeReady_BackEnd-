"""Repository for AgentJournal CRUD operations.

All database access for :class:`~src.database.models.AgentJournal` rows goes
through :class:`AgentJournalRepository`.

Dependency direction:
    Services → AgentJournalRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import AgentJournal
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class AgentJournalNotFoundError(Exception):
    """Raised when an agent journal entry cannot be found."""

    def __init__(
        self,
        message: str = "Agent journal entry not found.",
        *,
        entry_id: UUID | None = None,
    ) -> None:
        self.entry_id = entry_id
        super().__init__(message)


class AgentJournalRepository:
    """Async CRUD repository for the ``agent_journal`` table.

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

    async def create(self, entry: AgentJournal) -> AgentJournal:
        """Persist a new AgentJournal row and flush to obtain server defaults.

        Args:
            entry: A fully-populated (but not yet persisted) AgentJournal instance.

        Returns:
            The same ``entry`` instance with server-generated columns filled.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            self._session.add(entry)
            await self._session.flush()
            await self._session.refresh(entry)
            logger.info(
                "agent_journal.created",
                entry_id=str(entry.id),
                agent_id=str(entry.agent_id),
                entry_type=entry.entry_type,
            )
            return entry
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_journal.create.integrity_error", error=str(exc))
            raise DatabaseError(f"Integrity error while creating journal entry: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_journal.create.db_error", error=str(exc))
            raise DatabaseError("Failed to create agent journal entry.") from exc

    async def delete(self, entry_id: UUID) -> None:
        """Permanently delete a journal entry row.

        Args:
            entry_id: The journal entry's UUID.

        Raises:
            AgentJournalNotFoundError: If no entry exists with ``entry_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentJournal).where(AgentJournal.id == entry_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentJournalNotFoundError(entry_id=entry_id)
            await self._session.delete(row)
            await self._session.flush()
            logger.info("agent_journal.deleted", entry_id=str(entry_id))
        except AgentJournalNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_journal.delete.db_error", entry_id=str(entry_id), error=str(exc))
            raise DatabaseError("Failed to delete agent journal entry.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, entry_id: UUID) -> AgentJournal:
        """Fetch a single journal entry by its primary-key UUID.

        Args:
            entry_id: The entry's UUID primary key.

        Returns:
            The matching AgentJournal instance.

        Raises:
            AgentJournalNotFoundError: If no entry with ``entry_id`` exists.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentJournal).where(AgentJournal.id == entry_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentJournalNotFoundError(entry_id=entry_id)
            return row
        except AgentJournalNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("agent_journal.get_by_id.db_error", entry_id=str(entry_id), error=str(exc))
            raise DatabaseError("Failed to fetch agent journal entry by ID.") from exc

    async def list_by_agent(
        self,
        agent_id: UUID,
        *,
        entry_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[AgentJournal]:
        """Return journal entries for an agent, newest first.

        Args:
            agent_id: The owning agent's UUID.
            entry_type: Optional filter by entry type (``reflection``, ``insight``,
                ``mistake``, ``improvement``, ``daily_review``, ``weekly_review``).
            limit: Maximum rows to return.
            offset: Rows to skip for pagination.

        Returns:
            A (possibly empty) sequence of AgentJournal instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentJournal)
                .where(AgentJournal.agent_id == agent_id)
                .order_by(AgentJournal.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if entry_type is not None:
                stmt = stmt.where(AgentJournal.entry_type == entry_type)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("agent_journal.list_by_agent.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to list agent journal entries.") from exc

    async def search_by_tags(
        self,
        agent_id: UUID,
        tags: list[str],
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[AgentJournal]:
        """Return journal entries that contain any of the given tags.

        Uses the PostgreSQL ``@>`` (contains) JSONB operator to check whether
        the ``tags`` array column contains at least one of the provided tags.
        The query ORs across all supplied tag values.

        Args:
            agent_id: The owning agent's UUID.
            tags: List of tag strings to search for.
            limit: Maximum rows to return.
            offset: Rows to skip for pagination.

        Returns:
            A (possibly empty) sequence of AgentJournal instances, newest first.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        if not tags:
            return []
        try:
            from sqlalchemy import cast, or_  # noqa: PLC0415
            from sqlalchemy.dialects.postgresql import JSONB  # noqa: PLC0415

            # Build an OR clause: tags @> '["tag1"]' OR tags @> '["tag2"]' ...
            tag_filters = [
                AgentJournal.tags.op("@>")(cast([tag], JSONB))
                for tag in tags
            ]
            stmt = (
                select(AgentJournal)
                .where(
                    AgentJournal.agent_id == agent_id,
                    AgentJournal.tags.is_not(None),
                    or_(*tag_filters),
                )
                .order_by(AgentJournal.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("agent_journal.search_by_tags.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to search agent journal entries by tags.") from exc
