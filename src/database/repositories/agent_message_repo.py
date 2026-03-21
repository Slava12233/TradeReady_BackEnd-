"""Repository for AgentMessage CRUD operations.

All database access for :class:`~src.database.models.AgentMessage` rows goes
through :class:`AgentMessageRepository`.

Dependency direction:
    Services → AgentMessageRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import AgentMessage
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class AgentMessageNotFoundError(Exception):
    """Raised when an agent message cannot be found."""

    def __init__(
        self,
        message: str = "Agent message not found.",
        *,
        message_id: UUID | None = None,
    ) -> None:
        self.message_id = message_id
        super().__init__(message)


class AgentMessageRepository:
    """Async CRUD repository for the ``agent_messages`` table.

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

    async def create(self, agent_message: AgentMessage) -> AgentMessage:
        """Persist a new AgentMessage row and flush to obtain server defaults.

        Args:
            agent_message: A fully-populated (but not yet persisted) AgentMessage instance.

        Returns:
            The same ``agent_message`` instance with server-generated columns filled.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            self._session.add(agent_message)
            await self._session.flush()
            await self._session.refresh(agent_message)
            logger.info(
                "agent_message.created",
                message_id=str(agent_message.id),
                session_id=str(agent_message.session_id),
                role=agent_message.role,
            )
            return agent_message
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_message.create.integrity_error", error=str(exc))
            raise DatabaseError(f"Integrity error while creating agent message: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_message.create.db_error", error=str(exc))
            raise DatabaseError("Failed to create agent message.") from exc

    async def delete(self, message_id: UUID) -> None:
        """Permanently delete an agent message row.

        Args:
            message_id: The message's UUID.

        Raises:
            AgentMessageNotFoundError: If no message exists with ``message_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentMessage).where(AgentMessage.id == message_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentMessageNotFoundError(message_id=message_id)
            await self._session.delete(row)
            await self._session.flush()
            logger.info("agent_message.deleted", message_id=str(message_id))
        except AgentMessageNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_message.delete.db_error", message_id=str(message_id), error=str(exc))
            raise DatabaseError("Failed to delete agent message.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, message_id: UUID) -> AgentMessage:
        """Fetch a single agent message by its primary-key UUID.

        Args:
            message_id: The message's UUID primary key.

        Returns:
            The matching AgentMessage instance.

        Raises:
            AgentMessageNotFoundError: If no message with ``message_id`` exists.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentMessage).where(AgentMessage.id == message_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentMessageNotFoundError(message_id=message_id)
            return row
        except AgentMessageNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("agent_message.get_by_id.db_error", message_id=str(message_id), error=str(exc))
            raise DatabaseError("Failed to fetch agent message by ID.") from exc

    async def list_by_session(
        self,
        session_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AgentMessage]:
        """Return paginated messages for a session, ordered oldest-first.

        Oldest-first ordering preserves the natural chat conversation flow.

        Args:
            session_id: The parent session's UUID.
            limit: Maximum rows to return (default 100).
            offset: Rows to skip for pagination (default 0).

        Returns:
            A (possibly empty) sequence of AgentMessage instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentMessage)
                .where(AgentMessage.session_id == session_id)
                .order_by(AgentMessage.created_at.asc())
                .limit(limit)
                .offset(offset)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_message.list_by_session.db_error",
                session_id=str(session_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to list agent messages for session.") from exc

    async def count_by_session(self, session_id: UUID) -> int:
        """Return the total number of messages in a session.

        Args:
            session_id: The parent session's UUID.

        Returns:
            Message count (int).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(func.count())
                .select_from(AgentMessage)
                .where(AgentMessage.session_id == session_id)
            )
            result = await self._session.execute(stmt)
            return result.scalar_one()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_message.count_by_session.db_error",
                session_id=str(session_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to count agent messages for session.") from exc
