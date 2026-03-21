"""Repository for AgentObservation insert and time-range query operations.

All database access for :class:`~src.database.models.AgentObservation` rows
goes through :class:`AgentObservationRepository`.

``agent_observations`` is a **TimescaleDB hypertable** partitioned by ``time``
with 1-day chunks.  The composite primary key is ``(time, agent_id)``.
All queries should include the ``time`` or ``agent_id`` columns to leverage the
partition pruning index ``idx_agent_obs_agent_time``.

Dependency direction:
    Services → AgentObservationRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import AgentObservation
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class AgentObservationRepository:
    """Async insert + time-range query repository for ``agent_observations``.

    This table is a hypertable — write paths are ``insert``-only (no updates,
    no deletes by primary key) and read paths always include ``time`` bounds
    to exploit partition pruning.

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

    async def insert(self, observation: AgentObservation) -> AgentObservation:
        """Persist a single market observation snapshot.

        Args:
            observation: A fully-populated (but not yet persisted)
                AgentObservation instance.  ``time`` and ``agent_id`` together
                form the composite primary key.

        Returns:
            The same ``observation`` instance after flush.

        Raises:
            DatabaseError: On any SQLAlchemy / database error (including
                duplicate composite PK).
        """
        try:
            self._session.add(observation)
            await self._session.flush()
            logger.info(
                "agent_observation.inserted",
                agent_id=str(observation.agent_id),
                time=observation.time.isoformat(),
                regime=observation.regime,
            )
            return observation
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception(
                "agent_observation.insert.integrity_error",
                agent_id=str(observation.agent_id),
                error=str(exc),
            )
            raise DatabaseError(f"Integrity error while inserting agent observation: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "agent_observation.insert.db_error",
                agent_id=str(observation.agent_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to insert agent observation.") from exc

    async def insert_bulk(self, observations: list[AgentObservation]) -> int:
        """Persist multiple observation snapshots in a single flush.

        Args:
            observations: List of fully-populated (but not yet persisted)
                AgentObservation instances.

        Returns:
            Number of rows inserted.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        if not observations:
            return 0
        try:
            self._session.add_all(observations)
            await self._session.flush()
            count = len(observations)
            logger.info(
                "agent_observation.bulk_inserted",
                count=count,
                agent_id=str(observations[0].agent_id),
            )
            return count
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_observation.insert_bulk.integrity_error", error=str(exc))
            raise DatabaseError(f"Integrity error during bulk observation insert: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_observation.insert_bulk.db_error", error=str(exc))
            raise DatabaseError("Failed to bulk insert agent observations.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_range(
        self,
        agent_id: UUID,
        since: datetime,
        *,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> Sequence[AgentObservation]:
        """Return observations for an agent within a time range.

        Both ``since`` and ``until`` should be timezone-aware UTC datetimes
        so TimescaleDB partition pruning works correctly.

        Args:
            agent_id: The owning agent's UUID.
            since: Lower bound on ``time`` (inclusive).
            until: Upper bound on ``time`` (inclusive). Defaults to now if
                ``None``.
            limit: Maximum rows to return (default 1000).

        Returns:
            A (possibly empty) sequence of AgentObservation instances ordered
            by ``time`` ascending.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentObservation)
                .where(
                    AgentObservation.agent_id == agent_id,
                    AgentObservation.time >= since,
                )
                .order_by(AgentObservation.time.asc())
                .limit(limit)
            )
            if until is not None:
                stmt = stmt.where(AgentObservation.time <= until)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_observation.get_range.db_error",
                agent_id=str(agent_id),
                since=since.isoformat(),
                error=str(exc),
            )
            raise DatabaseError("Failed to query agent observations.") from exc

    async def get_latest(
        self,
        agent_id: UUID,
        *,
        limit: int = 1,
    ) -> Sequence[AgentObservation]:
        """Return the most recent observation(s) for an agent.

        Args:
            agent_id: The owning agent's UUID.
            limit: Number of most-recent rows to return (default 1).

        Returns:
            A (possibly empty) sequence of AgentObservation instances, newest
            first.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentObservation)
                .where(AgentObservation.agent_id == agent_id)
                .order_by(AgentObservation.time.desc())
                .limit(limit)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_observation.get_latest.db_error",
                agent_id=str(agent_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to fetch latest agent observation.") from exc

    async def get_by_decision(
        self,
        agent_id: UUID,
        decision_id: UUID,
    ) -> AgentObservation | None:
        """Return the observation linked to a specific decision.

        Args:
            agent_id: The owning agent's UUID (used for partition pruning).
            decision_id: The linked decision's UUID.

        Returns:
            The matching AgentObservation instance, or ``None`` if not found.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(AgentObservation)
                .where(
                    AgentObservation.agent_id == agent_id,
                    AgentObservation.decision_id == decision_id,
                )
                .limit(1)
            )
            result = await self._session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_observation.get_by_decision.db_error",
                agent_id=str(agent_id),
                decision_id=str(decision_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to fetch agent observation by decision.") from exc

    async def count_in_range(
        self,
        agent_id: UUID,
        since: datetime,
        until: datetime | None = None,
    ) -> int:
        """Count observations for an agent within a time window.

        Args:
            agent_id: The owning agent's UUID.
            since: Lower bound on ``time`` (inclusive).
            until: Upper bound on ``time`` (inclusive). Defaults to now if
                ``None``.

        Returns:
            Observation count (int).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            from sqlalchemy import func  # noqa: PLC0415

            stmt = (
                select(func.count())
                .select_from(AgentObservation)
                .where(
                    AgentObservation.agent_id == agent_id,
                    AgentObservation.time >= since,
                )
            )
            if until is not None:
                stmt = stmt.where(AgentObservation.time <= until)
            result = await self._session.execute(stmt)
            return result.scalar_one()
        except SQLAlchemyError as exc:
            logger.exception(
                "agent_observation.count_in_range.db_error",
                agent_id=str(agent_id),
                error=str(exc),
            )
            raise DatabaseError("Failed to count agent observations.") from exc
