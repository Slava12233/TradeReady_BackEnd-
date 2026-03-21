"""Repository for AgentPermission operations.

All database access for :class:`~src.database.models.AgentPermission` rows goes
through :class:`AgentPermissionRepository`.

One row per agent enforced by the UNIQUE constraint on ``agent_id``.

Dependency direction:
    Services → AgentPermissionRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import AgentPermission
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class AgentPermissionNotFoundError(Exception):
    """Raised when agent permissions cannot be found."""

    def __init__(
        self,
        message: str = "Agent permission record not found.",
        *,
        agent_id: UUID | None = None,
    ) -> None:
        self.agent_id = agent_id
        super().__init__(message)


class AgentPermissionRepository:
    """Async repository for the ``agent_permissions`` table.

    There is at most one row per agent (UNIQUE constraint on ``agent_id``).
    Use :meth:`upsert` to create or replace the permission record atomically.

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

    async def upsert(
        self,
        agent_id: UUID,
        granted_by: UUID,
        *,
        role: str = "viewer",
        capabilities: dict[str, Any] | None = None,
    ) -> AgentPermission:
        """Insert or update the permission record for an agent.

        Uses PostgreSQL ``INSERT ... ON CONFLICT DO UPDATE`` to handle both
        the initial grant and subsequent updates atomically.

        Args:
            agent_id: The agent's UUID (used as the upsert conflict key).
            granted_by: The account UUID that is granting the permissions.
            role: Broad role string (``viewer``, ``paper_trader``,
                ``live_trader``, or ``admin``).
            capabilities: JSONB capability map.  Merged with ``{}`` if not
                supplied.

        Returns:
            The refreshed AgentPermission instance.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        caps = capabilities or {}
        try:
            stmt = (
                pg_insert(AgentPermission)
                .values(
                    agent_id=agent_id,
                    granted_by=granted_by,
                    role=role,
                    capabilities=caps,
                )
                .on_conflict_do_update(
                    index_elements=["agent_id"],
                    set_={
                        "role": role,
                        "capabilities": caps,
                        "granted_by": granted_by,
                        "updated_at": __import__("sqlalchemy", fromlist=["func"]).func.now(),
                    },
                )
                .returning(AgentPermission)
            )
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise DatabaseError("Upsert returned no row for agent permission.")
            await self._session.flush()
            logger.info(
                "agent_permission.upserted",
                agent_id=str(agent_id),
                role=role,
            )
            return row
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception("agent_permission.upsert.integrity_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError(f"Integrity error while upserting agent permission: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_permission.upsert.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to upsert agent permission.") from exc

    async def delete(self, agent_id: UUID) -> None:
        """Delete the permission record for an agent.

        Args:
            agent_id: The agent's UUID.

        Raises:
            AgentPermissionNotFoundError: If no permission record exists.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentPermission).where(AgentPermission.agent_id == agent_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentPermissionNotFoundError(agent_id=agent_id)
            await self._session.delete(row)
            await self._session.flush()
            logger.info("agent_permission.deleted", agent_id=str(agent_id))
        except AgentPermissionNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent_permission.delete.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to delete agent permission.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_agent(self, agent_id: UUID) -> AgentPermission:
        """Fetch the permission record for an agent.

        Args:
            agent_id: The agent's UUID.

        Returns:
            The matching AgentPermission instance.

        Raises:
            AgentPermissionNotFoundError: If no permission record exists for
                ``agent_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentPermission).where(AgentPermission.agent_id == agent_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise AgentPermissionNotFoundError(agent_id=agent_id)
            return row
        except AgentPermissionNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("agent_permission.get_by_agent.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to fetch agent permission.") from exc

    async def check_capability(
        self,
        agent_id: UUID,
        capability: str,
    ) -> bool:
        """Check whether an agent has a specific capability flag set to truthy.

        Returns ``False`` if the permission record does not exist, if the
        capability key is absent, or if the value is falsy.

        Args:
            agent_id: The agent's UUID.
            capability: Capability key to check in the ``capabilities`` JSONB
                map (e.g. ``"live_trading"``).

        Returns:
            ``True`` if the capability is explicitly set to a truthy value,
            ``False`` otherwise.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(AgentPermission.capabilities).where(AgentPermission.agent_id == agent_id)
            result = await self._session.execute(stmt)
            caps = result.scalar_one_or_none()
            if caps is None:
                return False
            return bool(caps.get(capability, False))
        except SQLAlchemyError as exc:
            logger.exception("agent_permission.check_capability.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to check agent capability.") from exc
