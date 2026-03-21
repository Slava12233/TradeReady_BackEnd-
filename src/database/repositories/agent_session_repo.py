"""Repository for AgentSession CRUD operations.

All database access for :class:`~src.database.models.AgentSession` rows goes
through :class:`AgentSessionRepository`.

Dependency direction:
    Services → AgentSessionRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import AgentSession
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class AgentSessionNotFoundError(Exception):
    """Raised when an agent session cannot be found."""

    def __init__(
        self,
        message: str = "Agent session not found.",
        *,
        session_id: UUID | None = None,
    ) -> None:
        self.session_id = session_id
        super().__init__(message)


class AgentSessionRepository:
    """Async CRUD repository for the ``agent_sessions`` table.

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

    async def create(self, agent_session: AgentSession) -> AgentSession:
        """Persist a new AgentSession row and flush to obtain server defaults.

        Args:
            agent_session: A fully-populated (but not yet persisted) AgentSession instance.

        Returns:
            The same ``agent_session`` instance with server-generated columns filled.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            self._session.add(agent_session)
            await self._session.flush()
            await self._session.refresh(agent_session)
            logger.info(
                "agent_session.created",
                session_id=str(agent_session.id),
                agent_id=str(agent_session.agent_id),
            )
            return agent_session
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_session.create.integrity_error", error=str(exc))
            raise DatabaseError(f"Integrity error while creating agent session: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_session.create.db_error", error=str(exc))
            raise DatabaseError("Failed to create agent session.") from exc

    async def update(self, session_id: UUID, **fields: object) -> AgentSession:
        """Update specific fields on an agent session.

        Args:
            session_id: The agent session's UUID.
            **fields: Column names and new values to update.

        Returns:
            The refreshed AgentSession instance.

        Raises:
            AgentSessionNotFoundError: If no session exists with ``session_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = update(AgentSession).where(AgentSession.id == session_id).values(**fields).returning(AgentSession)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentSessionNotFoundError(session_id=session_id)
            logger.info("agent_session.updated", session_id=str(session_id), fields=list(fields.keys()))
            return row
        except AgentSessionNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_session.update.db_error", session_id=str(session_id), error=str(exc))
            raise DatabaseError("Failed to update agent session.") from exc

    async def close(self, session_id: UUID, summary: str | None = None) -> AgentSession:
        """Close an agent session by setting ``is_active`` to ``False``.

        Also optionally records a summary and sets ``ended_at`` to now.

        Args:
            session_id: The agent session's UUID.
            summary: Optional LLM-generated summary of the conversation.

        Returns:
            The refreshed AgentSession instance.

        Raises:
            AgentSessionNotFoundError: If no session exists with ``session_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        from sqlalchemy import func  # noqa: PLC0415

        fields: dict[str, object] = {"is_active": False, "ended_at": func.now()}
        if summary is not None:
            fields["summary"] = summary
        return await self.update(session_id, **fields)

    async def delete(self, session_id: UUID) -> None:
        """Permanently delete an agent session row (cascades to messages).

        Args:
            session_id: The agent session's UUID.

        Raises:
            AgentSessionNotFoundError: If no session exists with ``session_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentSession).where(AgentSession.id == session_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentSessionNotFoundError(session_id=session_id)
            await self._session.delete(row)
            await self._session.flush()
            logger.info("agent_session.deleted", session_id=str(session_id))
        except AgentSessionNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_session.delete.db_error", session_id=str(session_id), error=str(exc))
            raise DatabaseError("Failed to delete agent session.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, session_id: UUID) -> AgentSession:
        """Fetch a single agent session by its primary-key UUID.

        Args:
            session_id: The session's UUID primary key.

        Returns:
            The matching AgentSession instance.

        Raises:
            AgentSessionNotFoundError: If no session with ``session_id`` exists.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentSession).where(AgentSession.id == session_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentSessionNotFoundError(session_id=session_id)
            return row
        except AgentSessionNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("agent_session.get_by_id.db_error", session_id=str(session_id), error=str(exc))
            raise DatabaseError("Failed to fetch agent session by ID.") from exc

    async def find_active(self, agent_id: UUID) -> AgentSession | None:
        """Return the currently active session for an agent, if any.

        An agent should have at most one active session at a time.

        Args:
            agent_id: The owning agent's UUID.

        Returns:
            The active AgentSession instance, or ``None`` if no active session
            exists.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentSession)
                .where(AgentSession.agent_id == agent_id, AgentSession.is_active.is_(True))
                .order_by(AgentSession.started_at.desc())
                .limit(1)
            )
            result = await self._session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as exc:
            logger.exception("agent_session.find_active.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to find active agent session.") from exc

    async def list_by_agent(
        self,
        agent_id: UUID,
        *,
        include_closed: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[AgentSession]:
        """Return sessions belonging to an agent, newest first.

        Args:
            agent_id: The owning agent's UUID.
            include_closed: If ``False``, only return active sessions.
            limit: Maximum rows to return.
            offset: Rows to skip for pagination.

        Returns:
            A (possibly empty) sequence of AgentSession instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentSession).where(AgentSession.agent_id == agent_id)
            if not include_closed:
                stmt = stmt.where(AgentSession.is_active.is_(True))
            stmt = stmt.order_by(AgentSession.started_at.desc()).limit(limit).offset(offset)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("agent_session.list_by_agent.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to list agent sessions.") from exc
