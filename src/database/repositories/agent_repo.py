"""Repository for Agent CRUD operations.

All database access for :class:`~src.database.models.Agent` rows goes
through :class:`AgentRepository`.

Dependency direction:
    Services → AgentRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import Agent
from src.utils.exceptions import (
    DatabaseError,
)

logger = structlog.get_logger(__name__)


class AgentNotFoundError(Exception):
    """Raised when an agent cannot be found."""

    def __init__(self, message: str = "Agent not found.", *, agent_id: UUID | None = None) -> None:
        self.agent_id = agent_id
        super().__init__(message)


class AgentRepository:
    """Async CRUD repository for the ``agents`` table.

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

    async def create(self, agent: Agent) -> Agent:
        """Persist a new Agent row and flush to obtain server defaults.

        Args:
            agent: A fully-populated (but not yet persisted) Agent instance.

        Returns:
            The same ``agent`` instance with server-generated columns filled.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            self._session.add(agent)
            await self._session.flush()
            await self._session.refresh(agent)
            logger.info(
                "agent.created",
                agent_id=str(agent.id),
                account_id=str(agent.account_id),
                display_name=agent.display_name,
            )
            return agent
        except IntegrityError as exc:
            await self._session.rollback()
            constraint = str(exc.orig) if exc.orig else ""
            if "api_key" in constraint:
                raise DatabaseError("An agent with the given API key already exists.") from exc
            raise DatabaseError(f"Integrity error while creating agent: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent.create.db_error", error=str(exc))
            raise DatabaseError("Failed to create agent.") from exc

    async def update(self, agent_id: UUID, **fields: object) -> Agent:
        """Update specific fields on an agent.

        Args:
            agent_id: The agent's UUID.
            **fields: Column names and new values to update.

        Returns:
            The refreshed Agent instance.

        Raises:
            AgentNotFoundError: If no agent exists with ``agent_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(Agent).where(Agent.id == agent_id)
            result = await self._session.execute(stmt)
            agent = result.scalars().first()
            if agent is None:
                raise AgentNotFoundError(agent_id=agent_id)
            for key, value in fields.items():
                setattr(agent, key, value)
            await self._session.flush()
            await self._session.refresh(agent)
            logger.info("agent.updated", agent_id=str(agent_id), fields=list(fields.keys()))
            return agent
        except AgentNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent.update.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to update agent.") from exc

    async def archive(self, agent_id: UUID) -> Agent:
        """Set the agent's status to ``archived``.

        Args:
            agent_id: The agent's UUID.

        Returns:
            The refreshed Agent instance.

        Raises:
            AgentNotFoundError: If no agent exists with ``agent_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        return await self.update(agent_id, status="archived")

    async def hard_delete(self, agent_id: UUID) -> None:
        """Permanently delete an agent row.

        Args:
            agent_id: The agent's UUID.

        Raises:
            AgentNotFoundError: If no agent exists with ``agent_id``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(Agent).where(Agent.id == agent_id)
            result = await self._session.execute(stmt)
            agent = result.scalars().first()
            if agent is None:
                raise AgentNotFoundError(agent_id=agent_id)
            await self._session.delete(agent)
            await self._session.flush()
            logger.info("agent.deleted", agent_id=str(agent_id))
        except AgentNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception("agent.delete.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to delete agent.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, agent_id: UUID) -> Agent:
        """Fetch a single agent by its primary-key UUID.

        Args:
            agent_id: The agent's UUID primary key.

        Returns:
            The matching Agent instance.

        Raises:
            AgentNotFoundError: If no agent with ``agent_id`` exists.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(Agent).where(Agent.id == agent_id)
            result = await self._session.execute(stmt)
            agent = result.scalars().first()
            if agent is None:
                raise AgentNotFoundError(agent_id=agent_id)
            return agent
        except AgentNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("agent.get_by_id.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to fetch agent by ID.") from exc

    async def get_by_api_key(self, api_key: str) -> Agent:
        """Fetch a single agent by its plaintext API key.

        Args:
            api_key: The plaintext API key (``ak_live_`` prefix expected).

        Returns:
            The matching Agent instance.

        Raises:
            AgentNotFoundError: If no agent owns ``api_key``.
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(Agent).where(Agent.api_key == api_key)
            result = await self._session.execute(stmt)
            agent = result.scalars().first()
            if agent is None:
                raise AgentNotFoundError("No agent found for the provided API key.")
            return agent
        except AgentNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("agent.get_by_api_key.db_error", error=str(exc))
            raise DatabaseError("Failed to fetch agent by API key.") from exc

    async def list_by_account(
        self,
        account_id: UUID,
        *,
        include_archived: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Agent]:
        """Return agents belonging to an account.

        Args:
            account_id: The owning account's UUID.
            include_archived: If True, include archived agents.
            limit: Maximum rows to return.
            offset: Rows to skip for pagination.

        Returns:
            A (possibly empty) sequence of Agent instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(Agent).where(Agent.account_id == account_id)
            if not include_archived:
                stmt = stmt.where(Agent.status != "archived")
            stmt = stmt.order_by(Agent.created_at.asc()).limit(limit).offset(offset)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("agent.list_by_account.db_error", account_id=str(account_id), error=str(exc))
            raise DatabaseError("Failed to list agents by account.") from exc

    async def count_by_account(self, account_id: UUID) -> int:
        """Return the number of non-archived agents for an account.

        Args:
            account_id: The owning account's UUID.

        Returns:
            Agent count (int).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = (
                select(func.count())
                .select_from(Agent)
                .where(Agent.account_id == account_id, Agent.status != "archived")
            )
            result = await self._session.execute(stmt)
            return result.scalar_one()
        except SQLAlchemyError as exc:
            logger.exception("agent.count_by_account.db_error", account_id=str(account_id), error=str(exc))
            raise DatabaseError("Failed to count agents.") from exc
