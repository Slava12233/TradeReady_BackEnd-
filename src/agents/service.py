"""Agent service — creation, management, and lifecycle operations.

Coordinates :class:`AgentRepository` and :class:`BalanceRepository` to
implement agent lifecycle operations as single atomic transactions.

Example::

    async with session_factory() as session:
        svc = AgentService(session, settings)
        creds = await svc.create_agent(account_id, "AlphaBot")
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.accounts.auth import generate_api_credentials
from src.agents.avatar_generator import generate_avatar, generate_color
from src.config import Settings
from src.database.models import Agent, Balance
from src.database.repositories.agent_repo import AgentRepository
from src.database.repositories.balance_repo import BalanceRepository
from src.utils.exceptions import DatabaseError, PermissionDeniedError

log = structlog.get_logger(__name__)

_STARTING_ASSET = "USDT"


@dataclass(frozen=True, slots=True)
class AgentCredentials:
    """Credentials returned exactly once on successful agent creation.

    Attributes:
        agent_id:         The newly-created agent's UUID.
        api_key:          Plaintext API key (``ak_live_`` prefix).
        display_name:     The agent's display name.
        starting_balance: USDT balance credited at creation.
    """

    agent_id: UUID
    api_key: str
    display_name: str
    starting_balance: Decimal


class AgentService:
    """Business-logic layer for agent management.

    Args:
        session:  An open AsyncSession. Caller is responsible for committing.
        settings: Application Settings.
    """

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._agent_repo = AgentRepository(session)
        self._balance_repo = BalanceRepository(session)

    async def create_agent(
        self,
        account_id: UUID,
        display_name: str,
        *,
        starting_balance: Decimal | None = None,
        llm_model: str | None = None,
        framework: str | None = None,
        strategy_tags: list[str] | None = None,
        risk_profile: dict[str, object] | None = None,
        color: str | None = None,
    ) -> AgentCredentials:
        """Create a new trading agent with an initial USDT balance.

        Steps performed inside one transaction:
        1. Generate a fresh API key (bcrypt-hashed).
        2. Persist the Agent row.
        3. Create the initial USDT Balance row scoped to the agent.

        Args:
            account_id:       Owning account UUID.
            display_name:     Human-readable name.
            starting_balance: USDT balance to credit (defaults to settings).
            llm_model:        Optional LLM model name.
            framework:        Optional agent framework.
            strategy_tags:    Optional list of strategy tags.
            risk_profile:     Optional risk profile overrides.
            color:            Optional hex color code.

        Returns:
            AgentCredentials with the plaintext API key (shown once).
        """
        balance_amount = starting_balance or self._settings.default_starting_balance

        loop = asyncio.get_event_loop()
        creds = await loop.run_in_executor(None, generate_api_credentials)

        try:
            agent = Agent(
                account_id=account_id,
                display_name=display_name,
                api_key=creds.api_key,
                api_key_hash=creds.api_key_hash,
                starting_balance=balance_amount,
                llm_model=llm_model,
                framework=framework,
                strategy_tags=strategy_tags or [],
                risk_profile=risk_profile or {},
                color=color,
                status="active",
            )

            agent = await self._agent_repo.create(agent)

            # Generate avatar and color if not provided
            if agent.avatar_url is None:
                agent.avatar_url = generate_avatar(agent.id)
            if agent.color is None:
                agent.color = generate_color(agent.id)
            await self._session.flush()

            # Create initial USDT balance scoped to the agent
            usdt_balance = Balance(
                account_id=account_id,
                agent_id=agent.id,
                asset=_STARTING_ASSET,
                available=balance_amount,
                locked=Decimal("0"),
            )
            await self._balance_repo.create(usdt_balance)

        except SQLAlchemyError as exc:
            await self._session.rollback()
            log.exception("agent.create.db_error", account_id=str(account_id), error=str(exc))
            raise DatabaseError("Failed to create agent.") from exc

        log.info(
            "agent.created",
            agent_id=str(agent.id),
            account_id=str(account_id),
            display_name=display_name,
            starting_balance=str(balance_amount),
        )

        return AgentCredentials(
            agent_id=agent.id,
            api_key=creds.api_key,
            display_name=display_name,
            starting_balance=balance_amount,
        )

    async def get_agent(self, agent_id: UUID) -> Agent:
        """Fetch an agent by its UUID.

        Raises:
            AgentNotFoundError: If no agent exists.
        """
        return await self._agent_repo.get_by_id(agent_id)

    async def list_agents(
        self,
        account_id: UUID,
        *,
        include_archived: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Agent]:
        """Return agents owned by an account."""
        return await self._agent_repo.list_by_account(
            account_id,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
        )

    async def update_agent(
        self,
        agent_id: UUID,
        account_id: UUID,
        **fields: object,
    ) -> Agent:
        """Update agent fields after verifying ownership.

        Args:
            agent_id: The agent's UUID.
            account_id: The requesting account's UUID (ownership check).
            **fields: Column names and new values.

        Returns:
            The updated Agent instance.
        """
        agent = await self._agent_repo.get_by_id(agent_id)
        if agent.account_id != account_id:
            raise PermissionDeniedError("You do not own this agent.")
        return await self._agent_repo.update(agent_id, **fields)

    async def clone_agent(
        self,
        agent_id: UUID,
        account_id: UUID,
        *,
        new_name: str | None = None,
    ) -> AgentCredentials:
        """Clone an agent's configuration into a new agent.

        Args:
            agent_id: The source agent's UUID.
            account_id: The requesting account's UUID.
            new_name: Optional name for the clone (defaults to "Copy of <original>").

        Returns:
            AgentCredentials for the newly created clone.
        """
        source = await self._agent_repo.get_by_id(agent_id)
        if source.account_id != account_id:
            raise PermissionDeniedError("You do not own this agent.")

        name = new_name or f"Copy of {source.display_name}"
        return await self.create_agent(
            account_id=account_id,
            display_name=name,
            starting_balance=Decimal(str(source.starting_balance)),
            llm_model=source.llm_model,
            framework=source.framework,
            strategy_tags=list(source.strategy_tags) if source.strategy_tags else [],
            risk_profile=dict(source.risk_profile) if source.risk_profile else {},
        )

    async def reset_agent(self, agent_id: UUID, account_id: UUID) -> Agent:
        """Reset an agent: wipe balances, re-credit starting balance.

        Args:
            agent_id: The agent's UUID.
            account_id: The requesting account's UUID.

        Returns:
            The refreshed Agent instance.
        """
        agent = await self._agent_repo.get_by_id(agent_id)
        if agent.account_id != account_id:
            raise PermissionDeniedError("You do not own this agent.")

        try:
            # Wipe all balances for this agent
            balances = await self._balance_repo.get_all_by_agent(agent_id)
            for bal in balances:
                await self._session.delete(bal)
            await self._session.flush()

            # Re-credit starting balance
            starting = Decimal(str(agent.starting_balance))
            fresh_balance = Balance(
                account_id=account_id,
                agent_id=agent_id,
                asset=_STARTING_ASSET,
                available=starting,
                locked=Decimal("0"),
            )
            self._session.add(fresh_balance)
            await self._session.flush()

            log.info("agent.reset", agent_id=str(agent_id), starting_balance=str(starting))
            return agent

        except SQLAlchemyError as exc:
            await self._session.rollback()
            log.exception("agent.reset.db_error", agent_id=str(agent_id), error=str(exc))
            raise DatabaseError("Failed to reset agent.") from exc

    async def archive_agent(self, agent_id: UUID, account_id: UUID) -> Agent:
        """Archive an agent (soft delete).

        Args:
            agent_id: The agent's UUID.
            account_id: The requesting account's UUID.
        """
        agent = await self._agent_repo.get_by_id(agent_id)
        if agent.account_id != account_id:
            raise PermissionDeniedError("You do not own this agent.")
        return await self._agent_repo.archive(agent_id)

    async def delete_agent(self, agent_id: UUID, account_id: UUID) -> None:
        """Permanently delete an agent.

        Args:
            agent_id: The agent's UUID.
            account_id: The requesting account's UUID.
        """
        agent = await self._agent_repo.get_by_id(agent_id)
        if agent.account_id != account_id:
            raise PermissionDeniedError("You do not own this agent.")
        await self._agent_repo.hard_delete(agent_id)

    async def regenerate_api_key(self, agent_id: UUID, account_id: UUID) -> str:
        """Generate a new API key for an agent and return the plaintext key.

        Args:
            agent_id: The agent's UUID.
            account_id: The requesting account's UUID.

        Returns:
            The new plaintext API key (shown once).
        """
        agent = await self._agent_repo.get_by_id(agent_id)
        if agent.account_id != account_id:
            raise PermissionDeniedError("You do not own this agent.")

        loop = asyncio.get_event_loop()
        creds = await loop.run_in_executor(None, generate_api_credentials)

        await self._agent_repo.update(
            agent_id,
            api_key=creds.api_key,
            api_key_hash=creds.api_key_hash,
        )

        log.info("agent.api_key_regenerated", agent_id=str(agent_id))
        return creds.api_key
