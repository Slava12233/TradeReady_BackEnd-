"""Repository for AgentLearning CRUD operations.

All database access for :class:`~src.database.models.AgentLearning` rows goes
through :class:`AgentLearningRepository`.

Dependency direction:
    Services → AgentLearningRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import AgentLearning
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class AgentLearningNotFoundError(Exception):
    """Raised when an agent learning record cannot be found."""

    def __init__(
        self,
        message: str = "Agent learning not found.",
        *,
        learning_id: UUID | None = None,
    ) -> None:
        self.learning_id = learning_id
        super().__init__(message)


class AgentLearningRepository:
    """Async CRUD repository for the ``agent_learnings`` table.

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

    async def create(self, learning: AgentLearning) -> AgentLearning:
        """Persist a new AgentLearning row and flush to obtain server defaults.

        Args:
            learning: A fully-populated (but not yet persisted) AgentLearning instance.

        Returns:
            The same ``learning`` instance with server-generated columns filled.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            self._session.add(learning)
            await self._session.flush()
            await self._session.refresh(learning)
            logger.info(
                "agent_learning.created",
                learning_id=str(learning.id),
                agent_id=str(learning.agent_id),
                memory_type=learning.memory_type,
            )
            return learning
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_learning.create.integrity_error", error=str(exc))
            raise DatabaseError(f"Integrity error while creating agent learning: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_learning.create.db_error", error=str(exc))
            raise DatabaseError("Failed to create agent learning.") from exc

    async def reinforce(self, learning_id: UUID) -> AgentLearning:
        """Increment ``times_reinforced`` and update ``last_accessed_at``.

        Called when the system encounters evidence that reinforces an existing
        learning, rather than creating a duplicate.

        Args:
            learning_id: The learning record's UUID.

        Returns:
            The refreshed AgentLearning instance.

        Raises:
            AgentLearningNotFoundError: If no learning exists with ``learning_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                update(AgentLearning)
                .where(AgentLearning.id == learning_id)
                .values(
                    times_reinforced=AgentLearning.times_reinforced + 1,
                    last_accessed_at=func.now(),
                )
                .returning(AgentLearning)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentLearningNotFoundError(learning_id=learning_id)
            logger.info("agent_learning.reinforced", learning_id=str(learning_id))
            return row
        except AgentLearningNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_learning.reinforce.db_error", learning_id=str(learning_id), error=str(exc))
            raise DatabaseError("Failed to reinforce agent learning.") from exc

    async def touch(self, learning_id: UUID) -> None:
        """Update ``last_accessed_at`` to now without changing other fields.

        Called when a learning is retrieved and served to the agent so that
        relevance scoring can account for access recency.

        Args:
            learning_id: The learning record's UUID.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                update(AgentLearning)
                .where(AgentLearning.id == learning_id)
                .values(last_accessed_at=func.now())
            )
            await self._session.execute(stmt)
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_learning.touch.db_error", learning_id=str(learning_id), error=str(exc))
            raise DatabaseError("Failed to touch agent learning.") from exc

    async def delete(self, learning_id: UUID) -> None:
        """Permanently delete an agent learning row.

        Args:
            learning_id: The learning's UUID.

        Raises:
            AgentLearningNotFoundError: If no learning exists with ``learning_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentLearning).where(AgentLearning.id == learning_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentLearningNotFoundError(learning_id=learning_id)
            await self._session.delete(row)
            await self._session.flush()
            logger.info("agent_learning.deleted", learning_id=str(learning_id))
        except AgentLearningNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_learning.delete.db_error", learning_id=str(learning_id), error=str(exc))
            raise DatabaseError("Failed to delete agent learning.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, learning_id: UUID) -> AgentLearning:
        """Fetch a single agent learning by its primary-key UUID.

        Args:
            learning_id: The learning's UUID primary key.

        Returns:
            The matching AgentLearning instance.

        Raises:
            AgentLearningNotFoundError: If no learning with ``learning_id`` exists.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentLearning).where(AgentLearning.id == learning_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentLearningNotFoundError(learning_id=learning_id)
            return row
        except AgentLearningNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("agent_learning.get_by_id.db_error", learning_id=str(learning_id), error=str(exc))
            raise DatabaseError("Failed to fetch agent learning by ID.") from exc

    async def search_by_type(
        self,
        agent_id: UUID,
        memory_type: str,
        *,
        exclude_expired: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[AgentLearning]:
        """Return learnings filtered by memory type.

        Args:
            agent_id: The owning agent's UUID.
            memory_type: One of ``episodic``, ``semantic``, or ``procedural``.
            exclude_expired: If ``True`` (default), exclude rows where
                ``expires_at`` is in the past.
            limit: Maximum rows to return.
            offset: Rows to skip for pagination.

        Returns:
            A (possibly empty) sequence of AgentLearning instances, ordered by
            ``times_reinforced`` descending then ``created_at`` descending.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentLearning)
                .where(
                    AgentLearning.agent_id == agent_id,
                    AgentLearning.memory_type == memory_type,
                )
                .order_by(AgentLearning.times_reinforced.desc(), AgentLearning.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if exclude_expired:
                stmt = stmt.where(
                    (AgentLearning.expires_at.is_(None)) | (AgentLearning.expires_at > func.now())
                )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("agent_learning.search_by_type.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to search agent learnings by type.") from exc

    async def search(
        self,
        agent_id: UUID,
        keyword: str,
        *,
        memory_type: str | None = None,
        exclude_expired: bool = True,
        limit: int = 20,
    ) -> Sequence[AgentLearning]:
        """Search learnings by keyword with recency and reinforcement scoring.

        Performs a case-insensitive substring match on the ``content`` column
        then ranks results by a composite score of::

            score = times_reinforced + recency_weight

        where ``recency_weight`` gives learnings accessed in the last 7 days
        a +5 boost and learnings accessed in the last 30 days a +2 boost.

        Since TimescaleDB/PostgreSQL does not support dynamic expression
        ordering by CASE on Numeric aggregates natively without a subquery,
        the scoring is done as a Python-side sort after fetching a larger
        candidate set (``limit * 5``) to keep SQL simple and avoid full-text
        indexing dependencies.

        Args:
            agent_id: The owning agent's UUID.
            keyword: Substring to match against the ``content`` column
                (case-insensitive).
            memory_type: Optional filter by memory type.
            exclude_expired: If ``True`` (default), exclude expired learnings.
            limit: Maximum rows to return after scoring.

        Returns:
            A sequence of up to ``limit`` AgentLearning instances ranked by
            relevance (keyword match + recency + reinforcement score).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            # Fetch a wider candidate pool so scoring can reorder them.
            candidate_limit = limit * 5
            stmt = (
                select(AgentLearning)
                .where(
                    AgentLearning.agent_id == agent_id,
                    AgentLearning.content.ilike(f"%{keyword}%"),
                )
                .order_by(AgentLearning.times_reinforced.desc(), AgentLearning.created_at.desc())
                .limit(candidate_limit)
            )
            if memory_type is not None:
                stmt = stmt.where(AgentLearning.memory_type == memory_type)
            if exclude_expired:
                stmt = stmt.where(
                    (AgentLearning.expires_at.is_(None)) | (AgentLearning.expires_at > func.now())
                )
            result = await self._session.execute(stmt)
            candidates = result.scalars().all()

            # Python-side scoring: reinforcement count + recency boost.

            now = datetime.now(tz=UTC)
            seven_days_ago = now.timestamp() - 7 * 86400
            thirty_days_ago = now.timestamp() - 30 * 86400

            def _score(row: AgentLearning) -> float:
                score: float = float(row.times_reinforced)
                if row.last_accessed_at is not None:
                    accessed_ts = row.last_accessed_at.timestamp()
                    if accessed_ts >= seven_days_ago:
                        score += 5.0
                    elif accessed_ts >= thirty_days_ago:
                        score += 2.0
                return score

            ranked = sorted(candidates, key=_score, reverse=True)
            return ranked[:limit]
        except SQLAlchemyError as exc:
            logger.exception("agent_learning.search.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to search agent learnings.") from exc

    async def prune_expired(self, agent_id: UUID) -> int:
        """Delete all expired learning records for an agent.

        Args:
            agent_id: The owning agent's UUID.

        Returns:
            Number of rows deleted.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            from sqlalchemy import delete  # noqa: PLC0415

            stmt = (
                delete(AgentLearning)
                .where(
                    AgentLearning.agent_id == agent_id,
                    AgentLearning.expires_at.is_not(None),
                    AgentLearning.expires_at <= func.now(),
                )
                .returning(AgentLearning.id)
            )
            result = await self._session.execute(stmt)
            deleted_count = len(result.scalars().all())
            await self._session.flush()
            logger.info("agent_learning.pruned_expired", agent_id=str(agent_id), deleted=deleted_count)
            return deleted_count
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_learning.prune_expired.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to prune expired agent learnings.") from exc
