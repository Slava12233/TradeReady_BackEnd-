"""Unit tests for src/agents/service.py — agent lifecycle."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.agents.service import AgentCredentials, AgentService
from src.database.repositories.agent_repo import AgentNotFoundError
from src.utils.exceptions import DatabaseError, PermissionDeniedError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings():
    """Return a mock Settings object with test defaults."""
    s = MagicMock()
    s.default_starting_balance = Decimal("10000")
    return s


def _make_agent(
    *,
    account_id=None,
    display_name="AlphaBot",
    starting_balance=Decimal("10000"),
    status="active",
    llm_model="gpt-4o",
    framework="langchain",
    strategy_tags=None,
    risk_profile=None,
    avatar_url=None,
    color=None,
):
    """Return a mock Agent row."""
    agent = MagicMock()
    agent.id = uuid4()
    agent.account_id = account_id or uuid4()
    agent.display_name = display_name
    agent.api_key = "ak_live_" + "x" * 64
    agent.api_key_hash = "$2b$12$fakehash"
    agent.starting_balance = starting_balance
    agent.llm_model = llm_model
    agent.framework = framework
    agent.strategy_tags = strategy_tags or ["momentum"]
    agent.risk_profile = risk_profile or {"max_position_pct": 0.1}
    agent.avatar_url = avatar_url
    agent.color = color
    agent.status = status
    return agent


def _make_service(session=None, settings=None):
    """Build an AgentService with mocked deps."""
    if session is None:
        session = AsyncMock()
    if settings is None:
        settings = _make_settings()
    return AgentService(session, settings)


def _fake_api_credentials():
    """Return a fake ApiCredentials for patching generate_api_credentials."""
    from src.accounts.auth import ApiCredentials

    return ApiCredentials(
        api_key="ak_live_" + "a" * 64,
        api_secret="sk_live_" + "b" * 64,
        api_key_hash="$2b$12$hash_key",
        api_secret_hash="$2b$12$hash_secret",
    )


# ---------------------------------------------------------------------------
# create_agent
# ---------------------------------------------------------------------------


class TestCreateAgent:
    @patch("src.agents.service.generate_avatar", return_value="data:image/svg+xml,<svg/>")
    @patch("src.agents.service.generate_color", return_value="#aabbcc")
    @patch("src.agents.service.generate_api_credentials")
    async def test_creates_agent_with_balance(self, mock_gen_creds, mock_color, mock_avatar):
        mock_gen_creds.return_value = _fake_api_credentials()
        session = AsyncMock()
        svc = _make_service(session=session)

        account_id = uuid4()
        agent_id = uuid4()

        async def _fake_create(agent):
            agent.id = agent_id
            agent.avatar_url = None
            agent.color = None
            return agent

        svc._agent_repo.create = AsyncMock(side_effect=_fake_create)
        svc._balance_repo.create = AsyncMock()

        result = await svc.create_agent(account_id, "AlphaBot")

        assert isinstance(result, AgentCredentials)
        assert result.api_key.startswith("ak_live_")
        assert result.display_name == "AlphaBot"
        assert result.starting_balance == Decimal("10000")
        assert result.agent_id == agent_id
        svc._agent_repo.create.assert_called_once()
        svc._balance_repo.create.assert_called_once()

        # Verify the USDT balance was created with the correct amount
        balance_arg = svc._balance_repo.create.call_args[0][0]
        assert balance_arg.account_id == account_id
        assert balance_arg.agent_id == agent_id
        assert balance_arg.asset == "USDT"
        assert balance_arg.available == Decimal("10000")
        assert balance_arg.locked == Decimal("0")

    @patch("src.agents.service.generate_avatar", return_value="data:image/svg+xml,<svg/>")
    @patch("src.agents.service.generate_color", return_value="#aabbcc")
    @patch("src.agents.service.generate_api_credentials")
    async def test_custom_starting_balance(self, mock_gen_creds, mock_color, mock_avatar):
        mock_gen_creds.return_value = _fake_api_credentials()
        svc = _make_service()

        async def _fake_create(agent):
            agent.id = uuid4()
            agent.avatar_url = None
            agent.color = None
            return agent

        svc._agent_repo.create = AsyncMock(side_effect=_fake_create)
        svc._balance_repo.create = AsyncMock()

        result = await svc.create_agent(uuid4(), "Bot", starting_balance=Decimal("50000"))

        assert result.starting_balance == Decimal("50000")
        balance_arg = svc._balance_repo.create.call_args[0][0]
        assert balance_arg.available == Decimal("50000")

    @patch("src.agents.service.generate_avatar", return_value="data:image/svg+xml,<svg/>")
    @patch("src.agents.service.generate_color", return_value="#aabbcc")
    @patch("src.agents.service.generate_api_credentials")
    async def test_db_error_raises_database_error(self, mock_gen_creds, mock_color, mock_avatar):
        from sqlalchemy.exc import SQLAlchemyError

        mock_gen_creds.return_value = _fake_api_credentials()
        session = AsyncMock()
        svc = _make_service(session=session)
        svc._agent_repo.create = AsyncMock(side_effect=SQLAlchemyError("fail"))

        with pytest.raises(DatabaseError, match="Failed to create agent"):
            await svc.create_agent(uuid4(), "FailBot")

        session.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# get_agent
# ---------------------------------------------------------------------------


class TestGetAgent:
    async def test_delegates_to_repo(self):
        agent = _make_agent()
        svc = _make_service()
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)

        result = await svc.get_agent(agent.id)
        assert result.id == agent.id
        svc._agent_repo.get_by_id.assert_called_once_with(agent.id)

    async def test_not_found_propagates(self):
        svc = _make_service()
        agent_id = uuid4()
        svc._agent_repo.get_by_id = AsyncMock(
            side_effect=AgentNotFoundError(agent_id=agent_id),
        )

        with pytest.raises(AgentNotFoundError):
            await svc.get_agent(agent_id)


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


class TestListAgents:
    async def test_returns_agents_for_account(self):
        account_id = uuid4()
        agents = [_make_agent(account_id=account_id), _make_agent(account_id=account_id)]
        svc = _make_service()
        svc._agent_repo.list_by_account = AsyncMock(return_value=agents)

        result = await svc.list_agents(account_id)

        assert len(result) == 2
        svc._agent_repo.list_by_account.assert_called_once_with(
            account_id,
            include_archived=False,
            limit=100,
            offset=0,
        )

    async def test_passes_filters_through(self):
        account_id = uuid4()
        svc = _make_service()
        svc._agent_repo.list_by_account = AsyncMock(return_value=[])

        await svc.list_agents(account_id, include_archived=True, limit=10, offset=5)

        svc._agent_repo.list_by_account.assert_called_once_with(
            account_id,
            include_archived=True,
            limit=10,
            offset=5,
        )

    async def test_empty_list(self):
        svc = _make_service()
        svc._agent_repo.list_by_account = AsyncMock(return_value=[])

        result = await svc.list_agents(uuid4())
        assert result == []


# ---------------------------------------------------------------------------
# update_agent
# ---------------------------------------------------------------------------


class TestUpdateAgent:
    async def test_updates_owned_agent(self):
        account_id = uuid4()
        agent = _make_agent(account_id=account_id)
        updated_agent = _make_agent(account_id=account_id, display_name="BetaBot")
        svc = _make_service()
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)
        svc._agent_repo.update = AsyncMock(return_value=updated_agent)

        result = await svc.update_agent(agent.id, account_id, display_name="BetaBot")

        assert result.display_name == "BetaBot"
        svc._agent_repo.update.assert_called_once_with(agent.id, display_name="BetaBot")

    async def test_wrong_owner_raises_permission_denied(self):
        agent = _make_agent()  # owned by a random account
        svc = _make_service()
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)

        different_account = uuid4()
        with pytest.raises(PermissionDeniedError, match="You do not own this agent"):
            await svc.update_agent(agent.id, different_account, display_name="Hacked")

    async def test_not_found_propagates(self):
        svc = _make_service()
        agent_id = uuid4()
        svc._agent_repo.get_by_id = AsyncMock(
            side_effect=AgentNotFoundError(agent_id=agent_id),
        )

        with pytest.raises(AgentNotFoundError):
            await svc.update_agent(agent_id, uuid4(), display_name="X")


# ---------------------------------------------------------------------------
# clone_agent
# ---------------------------------------------------------------------------


class TestCloneAgent:
    @patch("src.agents.service.generate_avatar", return_value="data:image/svg+xml,<svg/>")
    @patch("src.agents.service.generate_color", return_value="#aabbcc")
    @patch("src.agents.service.generate_api_credentials")
    async def test_clones_with_default_name(self, mock_gen_creds, mock_color, mock_avatar):
        mock_gen_creds.return_value = _fake_api_credentials()
        account_id = uuid4()
        source = _make_agent(
            account_id=account_id,
            display_name="OriginalBot",
            starting_balance=Decimal("5000"),
            llm_model="claude-opus-4-20250514",
            framework="custom",
            strategy_tags=["mean_reversion"],
            risk_profile={"max_drawdown": 0.15},
        )
        svc = _make_service()
        svc._agent_repo.get_by_id = AsyncMock(return_value=source)

        async def _fake_create(agent):
            agent.id = uuid4()
            agent.avatar_url = None
            agent.color = None
            return agent

        svc._agent_repo.create = AsyncMock(side_effect=_fake_create)
        svc._balance_repo.create = AsyncMock()

        result = await svc.clone_agent(source.id, account_id)

        assert result.display_name == "Copy of OriginalBot"
        assert result.starting_balance == Decimal("5000")

    @patch("src.agents.service.generate_avatar", return_value="data:image/svg+xml,<svg/>")
    @patch("src.agents.service.generate_color", return_value="#aabbcc")
    @patch("src.agents.service.generate_api_credentials")
    async def test_clones_with_custom_name(self, mock_gen_creds, mock_color, mock_avatar):
        mock_gen_creds.return_value = _fake_api_credentials()
        account_id = uuid4()
        source = _make_agent(account_id=account_id)
        svc = _make_service()
        svc._agent_repo.get_by_id = AsyncMock(return_value=source)

        async def _fake_create(agent):
            agent.id = uuid4()
            agent.avatar_url = None
            agent.color = None
            return agent

        svc._agent_repo.create = AsyncMock(side_effect=_fake_create)
        svc._balance_repo.create = AsyncMock()

        result = await svc.clone_agent(source.id, account_id, new_name="CloneV2")

        assert result.display_name == "CloneV2"

    async def test_clone_wrong_owner_raises(self):
        source = _make_agent()
        svc = _make_service()
        svc._agent_repo.get_by_id = AsyncMock(return_value=source)

        with pytest.raises(PermissionDeniedError, match="You do not own this agent"):
            await svc.clone_agent(source.id, uuid4())


# ---------------------------------------------------------------------------
# reset_agent
# ---------------------------------------------------------------------------


class TestResetAgent:
    async def test_resets_balances(self):
        account_id = uuid4()
        agent = _make_agent(account_id=account_id, starting_balance=Decimal("10000"))
        old_balances = [MagicMock(), MagicMock()]

        session = AsyncMock()
        svc = _make_service(session=session)
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)
        svc._balance_repo.get_all_by_agent = AsyncMock(return_value=old_balances)

        result = await svc.reset_agent(agent.id, account_id)

        assert result is agent
        # All old balances should be deleted
        assert session.delete.call_count == len(old_balances)
        # A fresh USDT balance should be added
        session.add.assert_called_once()
        balance_arg = session.add.call_args[0][0]
        assert balance_arg.asset == "USDT"
        assert balance_arg.available == Decimal("10000")
        assert balance_arg.locked == Decimal("0")
        assert balance_arg.agent_id == agent.id

    async def test_reset_wrong_owner_raises(self):
        agent = _make_agent()
        svc = _make_service()
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)

        with pytest.raises(PermissionDeniedError, match="You do not own this agent"):
            await svc.reset_agent(agent.id, uuid4())

    async def test_reset_db_error_raises(self):
        from sqlalchemy.exc import SQLAlchemyError

        account_id = uuid4()
        agent = _make_agent(account_id=account_id)
        session = AsyncMock()
        svc = _make_service(session=session)
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)
        svc._balance_repo.get_all_by_agent = AsyncMock(side_effect=SQLAlchemyError("fail"))

        with pytest.raises(DatabaseError, match="Failed to reset agent"):
            await svc.reset_agent(agent.id, account_id)

        session.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# archive_agent
# ---------------------------------------------------------------------------


class TestArchiveAgent:
    async def test_archives_owned_agent(self):
        account_id = uuid4()
        agent = _make_agent(account_id=account_id)
        archived = _make_agent(account_id=account_id, status="archived")
        svc = _make_service()
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)
        svc._agent_repo.archive = AsyncMock(return_value=archived)

        result = await svc.archive_agent(agent.id, account_id)

        assert result.status == "archived"
        svc._agent_repo.archive.assert_called_once_with(agent.id)

    async def test_archive_wrong_owner_raises(self):
        agent = _make_agent()
        svc = _make_service()
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)

        with pytest.raises(PermissionDeniedError, match="You do not own this agent"):
            await svc.archive_agent(agent.id, uuid4())


# ---------------------------------------------------------------------------
# delete_agent
# ---------------------------------------------------------------------------


class TestDeleteAgent:
    async def test_deletes_owned_agent(self):
        account_id = uuid4()
        agent = _make_agent(account_id=account_id)
        svc = _make_service()
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)
        svc._agent_repo.hard_delete = AsyncMock()

        await svc.delete_agent(agent.id, account_id)

        svc._agent_repo.hard_delete.assert_called_once_with(agent.id)

    async def test_delete_wrong_owner_raises(self):
        agent = _make_agent()
        svc = _make_service()
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)

        with pytest.raises(PermissionDeniedError, match="You do not own this agent"):
            await svc.delete_agent(agent.id, uuid4())

    async def test_delete_not_found_propagates(self):
        svc = _make_service()
        agent_id = uuid4()
        svc._agent_repo.get_by_id = AsyncMock(
            side_effect=AgentNotFoundError(agent_id=agent_id),
        )

        with pytest.raises(AgentNotFoundError):
            await svc.delete_agent(agent_id, uuid4())


# ---------------------------------------------------------------------------
# regenerate_api_key
# ---------------------------------------------------------------------------


class TestRegenerateApiKey:
    @patch("src.agents.service.generate_api_credentials")
    async def test_regenerates_key_for_owned_agent(self, mock_gen_creds):
        new_creds = _fake_api_credentials()
        mock_gen_creds.return_value = new_creds
        account_id = uuid4()
        agent = _make_agent(account_id=account_id)
        svc = _make_service()
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)
        svc._agent_repo.update = AsyncMock()

        result = await svc.regenerate_api_key(agent.id, account_id)

        assert result == new_creds.api_key
        assert result.startswith("ak_live_")
        svc._agent_repo.update.assert_called_once_with(
            agent.id,
            api_key=new_creds.api_key,
            api_key_hash=new_creds.api_key_hash,
        )

    async def test_regenerate_wrong_owner_raises(self):
        agent = _make_agent()
        svc = _make_service()
        svc._agent_repo.get_by_id = AsyncMock(return_value=agent)

        with pytest.raises(PermissionDeniedError, match="You do not own this agent"):
            await svc.regenerate_api_key(agent.id, uuid4())
