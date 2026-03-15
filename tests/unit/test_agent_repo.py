"""Unit tests for src.database.repositories.agent_repo.AgentRepository.

Tests cover:
- create() — persist new agent, IntegrityError (duplicate API key), generic DB error
- get_by_id() — found, not found (AgentNotFoundError), DB error
- get_by_api_key() — found, not found (AgentNotFoundError), DB error
- list_by_account() — default (excludes archived), include_archived, empty result, DB error
- update() — success, agent not found, DB error
- archive() — delegates to update with status="archived"
- hard_delete() — success, agent not found, DB error
- count_by_account() — returns count, DB error
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.models import Agent
from src.database.repositories.agent_repo import (
    AgentNotFoundError,
    AgentRepository,
)
from src.utils.exceptions import DatabaseError

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_agent(
    *,
    agent_id=None,
    account_id=None,
    display_name: str = "TestAgent",
    api_key: str = "ak_live_" + "x" * 64,
    status: str = "active",
) -> MagicMock:
    """Build a mock Agent ORM object."""
    agent = MagicMock(spec=Agent)
    agent.id = agent_id or uuid4()
    agent.account_id = account_id or uuid4()
    agent.display_name = display_name
    agent.api_key = api_key
    agent.api_key_hash = "$2b$12$fakehash"
    agent.starting_balance = Decimal("10000")
    agent.llm_model = "gpt-4o"
    agent.framework = "langchain"
    agent.strategy_tags = []
    agent.risk_profile = {}
    agent.avatar_url = None
    agent.color = "#FF5733"
    agent.status = status
    agent.created_at = datetime(2024, 6, 1, tzinfo=UTC)
    agent.updated_at = datetime(2024, 6, 1, tzinfo=UTC)
    return agent


def _make_session(
    *,
    execute_result=None,
    scalar_one_result=None,
) -> AsyncMock:
    """Return a mock AsyncSession.

    ``execute_result`` should be the object returned by ``result.scalars().first()``
    or ``result.scalars().all()`` depending on the test.
    """
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.rollback = AsyncMock()

    # Build the result chain: session.execute() → result → .scalars() → .first()/.all()
    mock_scalars = MagicMock()
    mock_scalars.first = MagicMock(return_value=execute_result)
    mock_scalars.all = MagicMock(return_value=execute_result if isinstance(execute_result, list) else [])

    mock_result = MagicMock()
    mock_result.scalars = MagicMock(return_value=mock_scalars)
    mock_result.scalar_one = MagicMock(return_value=scalar_one_result)

    session.execute = AsyncMock(return_value=mock_result)
    return session


def _make_repo(session: AsyncMock | None = None) -> tuple[AgentRepository, AsyncMock]:
    """Create an AgentRepository with a mocked session."""
    if session is None:
        session = _make_session()
    return AgentRepository(session), session


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------


class TestCreate:
    async def test_create_success(self):
        """create() adds the agent, flushes, refreshes, and returns it."""
        agent = _make_agent()
        session = _make_session()
        repo = AgentRepository(session)

        result = await repo.create(agent)

        session.add.assert_called_once_with(agent)
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(agent)
        assert result is agent

    async def test_create_duplicate_api_key_raises_database_error(self):
        """create() raises DatabaseError when api_key violates unique constraint."""
        agent = _make_agent()
        session = _make_session()
        repo = AgentRepository(session)

        orig = Exception("api_key")
        exc = IntegrityError("INSERT", {}, orig)
        session.flush.side_effect = exc

        with pytest.raises(DatabaseError, match="API key already exists"):
            await repo.create(agent)

        session.rollback.assert_awaited_once()

    async def test_create_integrity_error_other(self):
        """create() raises DatabaseError on non-api_key IntegrityError."""
        agent = _make_agent()
        session = _make_session()
        repo = AgentRepository(session)

        orig = Exception("some_other_constraint")
        exc = IntegrityError("INSERT", {}, orig)
        session.flush.side_effect = exc

        with pytest.raises(DatabaseError, match="Integrity error"):
            await repo.create(agent)

        session.rollback.assert_awaited_once()

    async def test_create_generic_db_error(self):
        """create() raises DatabaseError on SQLAlchemyError."""
        agent = _make_agent()
        session = _make_session()
        repo = AgentRepository(session)

        session.flush.side_effect = SQLAlchemyError("connection lost")

        with pytest.raises(DatabaseError, match="Failed to create agent"):
            await repo.create(agent)

        session.rollback.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_by_id()
# ---------------------------------------------------------------------------


class TestGetById:
    async def test_get_by_id_found(self):
        """get_by_id() returns the agent when it exists."""
        agent = _make_agent()
        session = _make_session(execute_result=agent)
        repo = AgentRepository(session)

        result = await repo.get_by_id(agent.id)

        assert result is agent
        session.execute.assert_awaited_once()

    async def test_get_by_id_not_found(self):
        """get_by_id() raises AgentNotFoundError when no match."""
        session = _make_session(execute_result=None)
        repo = AgentRepository(session)

        with pytest.raises(AgentNotFoundError):
            await repo.get_by_id(uuid4())

    async def test_get_by_id_db_error(self):
        """get_by_id() raises DatabaseError on SQLAlchemyError."""
        session = _make_session()
        session.execute.side_effect = SQLAlchemyError("timeout")
        repo = AgentRepository(session)

        with pytest.raises(DatabaseError, match="Failed to fetch agent by ID"):
            await repo.get_by_id(uuid4())


# ---------------------------------------------------------------------------
# get_by_api_key()
# ---------------------------------------------------------------------------


class TestGetByApiKey:
    async def test_get_by_api_key_found(self):
        """get_by_api_key() returns the agent when api_key matches."""
        agent = _make_agent()
        session = _make_session(execute_result=agent)
        repo = AgentRepository(session)

        result = await repo.get_by_api_key(agent.api_key)

        assert result is agent

    async def test_get_by_api_key_not_found(self):
        """get_by_api_key() raises AgentNotFoundError when no match."""
        session = _make_session(execute_result=None)
        repo = AgentRepository(session)

        with pytest.raises(AgentNotFoundError, match="No agent found"):
            await repo.get_by_api_key("ak_live_nonexistent")

    async def test_get_by_api_key_db_error(self):
        """get_by_api_key() raises DatabaseError on SQLAlchemyError."""
        session = _make_session()
        session.execute.side_effect = SQLAlchemyError("timeout")
        repo = AgentRepository(session)

        with pytest.raises(DatabaseError, match="Failed to fetch agent by API key"):
            await repo.get_by_api_key("ak_live_test")


# ---------------------------------------------------------------------------
# list_by_account()
# ---------------------------------------------------------------------------


class TestListByAccount:
    async def test_list_by_account_returns_agents(self):
        """list_by_account() returns a sequence of agents."""
        agents = [_make_agent(display_name="A1"), _make_agent(display_name="A2")]
        session = _make_session(execute_result=agents)
        repo = AgentRepository(session)

        result = await repo.list_by_account(uuid4())

        assert result == agents

    async def test_list_by_account_empty(self):
        """list_by_account() returns an empty list when no agents exist."""
        session = _make_session(execute_result=[])
        repo = AgentRepository(session)

        result = await repo.list_by_account(uuid4())

        assert result == []

    async def test_list_by_account_include_archived(self):
        """list_by_account(include_archived=True) does not filter out archived."""
        agents = [_make_agent(status="archived")]
        session = _make_session(execute_result=agents)
        repo = AgentRepository(session)

        result = await repo.list_by_account(uuid4(), include_archived=True)

        assert len(result) == 1

    async def test_list_by_account_db_error(self):
        """list_by_account() raises DatabaseError on SQLAlchemyError."""
        session = _make_session()
        session.execute.side_effect = SQLAlchemyError("timeout")
        repo = AgentRepository(session)

        with pytest.raises(DatabaseError, match="Failed to list agents"):
            await repo.list_by_account(uuid4())


# ---------------------------------------------------------------------------
# update()
# ---------------------------------------------------------------------------


class TestUpdate:
    async def test_update_success(self):
        """update() sets fields and returns the refreshed agent."""
        agent = _make_agent()
        session = _make_session(execute_result=agent)
        repo = AgentRepository(session)

        result = await repo.update(agent.id, display_name="NewName", llm_model="claude-opus-4-20250514")

        assert result is agent
        # Verify setattr was called on the mock agent
        assert agent.display_name == "NewName"
        assert agent.llm_model == "claude-opus-4-20250514"
        session.flush.assert_awaited_once()
        session.refresh.assert_awaited_once_with(agent)

    async def test_update_not_found(self):
        """update() raises AgentNotFoundError when agent does not exist."""
        session = _make_session(execute_result=None)
        repo = AgentRepository(session)

        with pytest.raises(AgentNotFoundError):
            await repo.update(uuid4(), display_name="Nope")

    async def test_update_db_error(self):
        """update() raises DatabaseError on SQLAlchemyError during flush."""
        agent = _make_agent()
        session = _make_session(execute_result=agent)
        repo = AgentRepository(session)

        # flush succeeds on first call (from update), but we need the error on flush
        session.flush.side_effect = SQLAlchemyError("write failed")

        with pytest.raises(DatabaseError, match="Failed to update agent"):
            await repo.update(agent.id, display_name="Fail")

        session.rollback.assert_awaited_once()


# ---------------------------------------------------------------------------
# archive()
# ---------------------------------------------------------------------------


class TestArchive:
    async def test_archive_delegates_to_update(self):
        """archive() calls update with status='archived'."""
        agent = _make_agent()
        session = _make_session(execute_result=agent)
        repo = AgentRepository(session)

        result = await repo.archive(agent.id)

        assert result is agent
        assert agent.status == "archived"

    async def test_archive_not_found(self):
        """archive() raises AgentNotFoundError when agent does not exist."""
        session = _make_session(execute_result=None)
        repo = AgentRepository(session)

        with pytest.raises(AgentNotFoundError):
            await repo.archive(uuid4())


# ---------------------------------------------------------------------------
# hard_delete()
# ---------------------------------------------------------------------------


class TestHardDelete:
    async def test_hard_delete_success(self):
        """hard_delete() deletes the agent and flushes."""
        agent = _make_agent()
        session = _make_session(execute_result=agent)
        repo = AgentRepository(session)

        await repo.hard_delete(agent.id)

        session.delete.assert_awaited_once_with(agent)
        session.flush.assert_awaited_once()

    async def test_hard_delete_not_found(self):
        """hard_delete() raises AgentNotFoundError when agent does not exist."""
        session = _make_session(execute_result=None)
        repo = AgentRepository(session)

        with pytest.raises(AgentNotFoundError):
            await repo.hard_delete(uuid4())

    async def test_hard_delete_db_error(self):
        """hard_delete() raises DatabaseError on SQLAlchemyError."""
        agent = _make_agent()
        session = _make_session(execute_result=agent)
        repo = AgentRepository(session)

        session.delete.side_effect = SQLAlchemyError("FK violation")

        with pytest.raises(DatabaseError, match="Failed to delete agent"):
            await repo.hard_delete(agent.id)

        session.rollback.assert_awaited_once()


# ---------------------------------------------------------------------------
# count_by_account()
# ---------------------------------------------------------------------------


class TestCountByAccount:
    async def test_count_by_account_returns_count(self):
        """count_by_account() returns the integer count."""
        session = _make_session(scalar_one_result=5)
        repo = AgentRepository(session)

        result = await repo.count_by_account(uuid4())

        assert result == 5

    async def test_count_by_account_zero(self):
        """count_by_account() returns 0 when no agents exist."""
        session = _make_session(scalar_one_result=0)
        repo = AgentRepository(session)

        result = await repo.count_by_account(uuid4())

        assert result == 0

    async def test_count_by_account_db_error(self):
        """count_by_account() raises DatabaseError on SQLAlchemyError."""
        session = _make_session()
        session.execute.side_effect = SQLAlchemyError("timeout")
        repo = AgentRepository(session)

        with pytest.raises(DatabaseError, match="Failed to count agents"):
            await repo.count_by_account(uuid4())
