"""Repository for AgentFeedback CRUD operations.

All database access for :class:`~src.database.models.AgentFeedback` rows goes
through :class:`AgentFeedbackRepository`.

Dependency direction:
    Services → AgentFeedbackRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import AgentFeedback
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class AgentFeedbackNotFoundError(Exception):
    """Raised when an agent feedback item cannot be found."""

    def __init__(
        self,
        message: str = "Agent feedback not found.",
        *,
        feedback_id: UUID | None = None,
    ) -> None:
        self.feedback_id = feedback_id
        super().__init__(message)


class AgentFeedbackRepository:
    """Async CRUD repository for the ``agent_feedback`` table.

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

    async def create(self, feedback: AgentFeedback) -> AgentFeedback:
        """Persist a new AgentFeedback row and flush to obtain server defaults.

        Args:
            feedback: A fully-populated (but not yet persisted) AgentFeedback instance.

        Returns:
            The same ``feedback`` instance with server-generated columns filled.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            self._session.add(feedback)
            await self._session.flush()
            await self._session.refresh(feedback)
            logger.info(
                "agent_feedback.created",
                feedback_id=str(feedback.id),
                agent_id=str(feedback.agent_id),
                category=feedback.category,
                priority=feedback.priority,
            )
            return feedback
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_feedback.create.integrity_error", error=str(exc))
            raise DatabaseError(f"Integrity error while creating agent feedback: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_feedback.create.db_error", error=str(exc))
            raise DatabaseError("Failed to create agent feedback.") from exc

    async def update_status(
        self,
        feedback_id: UUID,
        status: str,
        *,
        resolution_notes: str | None = None,
        resolved_at: datetime | None = None,
    ) -> AgentFeedback:
        """Transition a feedback item to a new status.

        Args:
            feedback_id: The feedback item's UUID.
            status: New status value (``acknowledged``, ``in_progress``,
                ``resolved``, or ``wont_fix``).
            resolution_notes: Optional operator notes explaining the resolution.
            resolved_at: UTC timestamp of resolution; should be provided when
                ``status`` is ``resolved`` or ``wont_fix``.

        Returns:
            The refreshed AgentFeedback instance.

        Raises:
            AgentFeedbackNotFoundError: If no feedback exists with ``feedback_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            values: dict[str, object] = {"status": status}
            if resolution_notes is not None:
                values["resolution_notes"] = resolution_notes
            if resolved_at is not None:
                values["resolved_at"] = resolved_at
            stmt = (
                update(AgentFeedback).where(AgentFeedback.id == feedback_id).values(**values).returning(AgentFeedback)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentFeedbackNotFoundError(feedback_id=feedback_id)
            logger.info(
                "agent_feedback.status_updated",
                feedback_id=str(feedback_id),
                new_status=status,
            )
            return row
        except AgentFeedbackNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_feedback.update_status.db_error", feedback_id=str(feedback_id), error=str(exc))
            raise DatabaseError("Failed to update agent feedback status.") from exc

    async def delete(self, feedback_id: UUID) -> None:
        """Permanently delete a feedback row.

        Args:
            feedback_id: The feedback item's UUID.

        Raises:
            AgentFeedbackNotFoundError: If no feedback exists with ``feedback_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentFeedback).where(AgentFeedback.id == feedback_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentFeedbackNotFoundError(feedback_id=feedback_id)
            await self._session.delete(row)
            await self._session.flush()
            logger.info("agent_feedback.deleted", feedback_id=str(feedback_id))
        except AgentFeedbackNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_feedback.delete.db_error", feedback_id=str(feedback_id), error=str(exc))
            raise DatabaseError("Failed to delete agent feedback.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, feedback_id: UUID) -> AgentFeedback:
        """Fetch a single feedback item by its primary-key UUID.

        Args:
            feedback_id: The feedback item's UUID primary key.

        Returns:
            The matching AgentFeedback instance.

        Raises:
            AgentFeedbackNotFoundError: If no feedback with ``feedback_id`` exists.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentFeedback).where(AgentFeedback.id == feedback_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentFeedbackNotFoundError(feedback_id=feedback_id)
            return row
        except AgentFeedbackNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("agent_feedback.get_by_id.db_error", feedback_id=str(feedback_id), error=str(exc))
            raise DatabaseError("Failed to fetch agent feedback by ID.") from exc

    async def list_by_status(
        self,
        status: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AgentFeedback]:
        """Return feedback items with a given status, newest first.

        Used by human operators to triage the feedback queue.

        Args:
            status: Status filter (``new``, ``acknowledged``, ``in_progress``,
                ``resolved``, or ``wont_fix``).
            limit: Maximum rows to return.
            offset: Rows to skip for pagination.

        Returns:
            A (possibly empty) sequence of AgentFeedback instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentFeedback)
                .where(AgentFeedback.status == status)
                .order_by(AgentFeedback.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("agent_feedback.list_by_status.db_error", status=status, error=str(exc))
            raise DatabaseError("Failed to list agent feedback by status.") from exc

    async def list_by_category(
        self,
        category: str,
        *,
        agent_id: UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AgentFeedback]:
        """Return feedback items in a given category, newest first.

        Args:
            category: Category filter (``missing_data``, ``missing_tool``,
                ``performance_issue``, ``bug``, or ``feature_request``).
            agent_id: Optional scope to a specific agent.
            limit: Maximum rows to return.
            offset: Rows to skip for pagination.

        Returns:
            A (possibly empty) sequence of AgentFeedback instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentFeedback)
                .where(AgentFeedback.category == category)
                .order_by(AgentFeedback.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if agent_id is not None:
                stmt = stmt.where(AgentFeedback.agent_id == agent_id)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("agent_feedback.list_by_category.db_error", category=category, error=str(exc))
            raise DatabaseError("Failed to list agent feedback by category.") from exc

    async def list_by_agent(
        self,
        agent_id: UUID,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[AgentFeedback]:
        """Return feedback submitted by a specific agent.

        Args:
            agent_id: The owning agent's UUID.
            status: Optional status filter.
            limit: Maximum rows to return.
            offset: Rows to skip for pagination.

        Returns:
            A (possibly empty) sequence of AgentFeedback instances, newest first.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentFeedback)
                .where(AgentFeedback.agent_id == agent_id)
                .order_by(AgentFeedback.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if status is not None:
                stmt = stmt.where(AgentFeedback.status == status)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("agent_feedback.list_by_agent.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to list agent feedback by agent.") from exc
