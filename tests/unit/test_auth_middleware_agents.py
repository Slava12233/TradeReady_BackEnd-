"""Unit tests for auth middleware agent support.

Tests the agent-aware authentication flow in ``src.api.middleware.auth``:
- ``_resolve_account_from_api_key`` — tries agents table first, falls back to legacy accounts
- ``get_current_agent`` — resolves agent from request.state or X-Agent-Id header
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.api.middleware.auth import (
    _resolve_account_from_api_key,
    get_current_agent,
)
from src.database.repositories.agent_repo import AgentNotFoundError
from src.utils.exceptions import (
    AccountNotFoundError,
    AccountSuspendedError,
    AuthenticationError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account(
    *,
    account_id: UUID | None = None,
    status: str = "active",
) -> MagicMock:
    """Build a mock Account ORM object."""
    account = MagicMock()
    account.id = account_id or uuid4()
    account.status = status
    account.api_key = f"ak_live_account_{account.id.hex[:8]}"
    return account


def _make_agent(
    *,
    agent_id: UUID | None = None,
    account_id: UUID | None = None,
    status: str = "active",
) -> MagicMock:
    """Build a mock Agent ORM object."""
    agent = MagicMock()
    agent.id = agent_id or uuid4()
    agent.account_id = account_id or uuid4()
    agent.status = status
    agent.api_key = f"ak_live_agent_{agent.id.hex[:8]}"
    return agent


def _make_request(
    *,
    headers: dict[str, str] | None = None,
    state_account: MagicMock | None = None,
    state_agent: MagicMock | None = None,
    has_agent_state: bool = True,
) -> MagicMock:
    """Build a mock FastAPI Request with configurable headers and state."""
    request = MagicMock()
    request.headers = headers or {}

    # Simulate request.state attribute access via getattr
    state = MagicMock()
    if has_agent_state:
        state.agent = state_agent
    else:
        # Simulate missing attribute — getattr(request.state, "agent", None)
        # returns None via the default
        del state.agent

    state.account = state_account
    request.state = state
    return request


# ---------------------------------------------------------------------------
# _resolve_account_from_api_key — agent found → returns (account, agent)
# ---------------------------------------------------------------------------


class TestResolveAccountFromApiKeyAgentFound:
    """When the API key belongs to an agent, return (owning_account, agent)."""

    async def test_returns_account_and_agent(self):
        account = _make_account()
        agent = _make_agent(account_id=account.id)

        account_repo = AsyncMock()
        account_repo.get_by_id = AsyncMock(return_value=account)

        agent_repo = AsyncMock()
        agent_repo.get_by_api_key = AsyncMock(return_value=agent)

        result = await _resolve_account_from_api_key(agent.api_key, account_repo, agent_repo)

        assert result == (account, agent)
        agent_repo.get_by_api_key.assert_awaited_once_with(agent.api_key)
        account_repo.get_by_id.assert_awaited_once_with(agent.account_id)
        # Legacy fallback should NOT be called
        account_repo.get_by_api_key.assert_not_awaited()


# ---------------------------------------------------------------------------
# _resolve_account_from_api_key — agent not found → legacy fallback
# ---------------------------------------------------------------------------


class TestResolveAccountFromApiKeyLegacyFallback:
    """When no agent matches, fall through to legacy account lookup."""

    async def test_falls_through_to_account(self):
        account = _make_account()

        account_repo = AsyncMock()
        account_repo.get_by_api_key = AsyncMock(return_value=account)

        agent_repo = AsyncMock()
        agent_repo.get_by_api_key = AsyncMock(side_effect=AgentNotFoundError())

        result = await _resolve_account_from_api_key(account.api_key, account_repo, agent_repo)

        assert result == (account, None)
        agent_repo.get_by_api_key.assert_awaited_once_with(account.api_key)
        account_repo.get_by_api_key.assert_awaited_once_with(account.api_key)

    async def test_falls_through_when_no_agent_repo(self):
        """When agent_repo is None (e.g. older code path), skip agent lookup."""
        account = _make_account()

        account_repo = AsyncMock()
        account_repo.get_by_api_key = AsyncMock(return_value=account)

        result = await _resolve_account_from_api_key(account.api_key, account_repo, agent_repo=None)

        assert result == (account, None)
        account_repo.get_by_api_key.assert_awaited_once_with(account.api_key)

    async def test_raises_auth_error_when_neither_found(self):
        """Neither agent nor account matches → AuthenticationError."""
        account_repo = AsyncMock()
        account_repo.get_by_api_key = AsyncMock(side_effect=AccountNotFoundError("No account found."))

        agent_repo = AsyncMock()
        agent_repo.get_by_api_key = AsyncMock(side_effect=AgentNotFoundError())

        with pytest.raises(AuthenticationError, match="Invalid API key"):
            await _resolve_account_from_api_key("ak_live_bogus", account_repo, agent_repo)


# ---------------------------------------------------------------------------
# _resolve_account_from_api_key — archived agent
# ---------------------------------------------------------------------------


class TestResolveAccountFromApiKeyArchivedAgent:
    """An archived agent's key should be rejected even though it exists."""

    async def test_archived_agent_raises_auth_error(self):
        account = _make_account()
        agent = _make_agent(account_id=account.id, status="archived")

        account_repo = AsyncMock()
        account_repo.get_by_id = AsyncMock(return_value=account)

        agent_repo = AsyncMock()
        agent_repo.get_by_api_key = AsyncMock(return_value=agent)

        with pytest.raises(AuthenticationError, match="archived"):
            await _resolve_account_from_api_key(agent.api_key, account_repo, agent_repo)


# ---------------------------------------------------------------------------
# _resolve_account_from_api_key — suspended account via agent
# ---------------------------------------------------------------------------


class TestResolveAccountFromApiKeySuspendedAccount:
    """Agent key resolves, but the owning account is suspended."""

    async def test_suspended_account_via_agent_raises(self):
        account = _make_account(status="suspended")
        agent = _make_agent(account_id=account.id)

        account_repo = AsyncMock()
        account_repo.get_by_id = AsyncMock(return_value=account)

        agent_repo = AsyncMock()
        agent_repo.get_by_api_key = AsyncMock(return_value=agent)

        with pytest.raises(AccountSuspendedError):
            await _resolve_account_from_api_key(agent.api_key, account_repo, agent_repo)

    async def test_suspended_account_legacy_raises(self):
        """Legacy path: account key found but account is suspended."""
        account = _make_account(status="suspended")

        account_repo = AsyncMock()
        account_repo.get_by_api_key = AsyncMock(return_value=account)

        agent_repo = AsyncMock()
        agent_repo.get_by_api_key = AsyncMock(side_effect=AgentNotFoundError())

        with pytest.raises(AccountSuspendedError):
            await _resolve_account_from_api_key(account.api_key, account_repo, agent_repo)


# ---------------------------------------------------------------------------
# _resolve_account_from_api_key — agent's owning account deleted
# ---------------------------------------------------------------------------


class TestResolveAccountFromApiKeyOrphanAgent:
    """Agent exists but its owning account has been deleted."""

    async def test_orphan_agent_raises_auth_error(self):
        agent = _make_agent()

        account_repo = AsyncMock()
        account_repo.get_by_id = AsyncMock(side_effect=AccountNotFoundError("Account not found."))

        agent_repo = AsyncMock()
        agent_repo.get_by_api_key = AsyncMock(return_value=agent)

        with pytest.raises(AuthenticationError, match="owning account"):
            await _resolve_account_from_api_key(agent.api_key, account_repo, agent_repo)


# ---------------------------------------------------------------------------
# get_current_agent — returns agent from request.state
# ---------------------------------------------------------------------------


class TestGetCurrentAgentFromState:
    """Agent already resolved by middleware and stored on request.state."""

    async def test_returns_agent_from_state(self):
        agent = _make_agent()
        request = _make_request(state_agent=agent)

        result = await get_current_agent(request)

        assert result is agent

    async def test_returns_none_when_state_agent_is_none(self):
        """No agent context (legacy API-key auth) → None."""
        request = _make_request(state_agent=None, headers={})

        result = await get_current_agent(request)

        assert result is None


# ---------------------------------------------------------------------------
# get_current_agent — resolves from X-Agent-Id header (JWT auth path)
# ---------------------------------------------------------------------------


class TestGetCurrentAgentFromHeader:
    """JWT auth sets no request.state.agent; resolve via X-Agent-Id header."""

    async def test_resolves_agent_from_header(self):
        agent = _make_agent()
        agent_id = agent.id

        # request.state.agent is None (JWT auth), but X-Agent-Id header present
        request = _make_request(
            state_agent=None,
            headers={"X-Agent-Id": str(agent_id)},
        )

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        # session_factory() returns mock_session (context manager)
        mock_session_factory = MagicMock(return_value=mock_session)
        # get_session_factory() returns session_factory
        mock_get_session_factory = MagicMock(return_value=mock_session_factory)

        mock_agent_repo_instance = AsyncMock()
        mock_agent_repo_instance.get_by_id = AsyncMock(return_value=agent)

        with (
            patch(
                "src.database.session.get_session_factory",
                mock_get_session_factory,
            ),
            patch(
                "src.api.middleware.auth.AgentRepository",
                return_value=mock_agent_repo_instance,
            ),
        ):
            result = await get_current_agent(request)

        assert result is agent
        mock_agent_repo_instance.get_by_id.assert_awaited_once_with(agent_id)

    async def test_returns_none_for_invalid_uuid_header(self):
        """Malformed X-Agent-Id header → return None, not an error."""
        request = _make_request(
            state_agent=None,
            headers={"X-Agent-Id": "not-a-uuid"},
        )

        result = await get_current_agent(request)

        assert result is None

    async def test_returns_none_when_agent_not_found_by_id(self):
        """Valid UUID in header but no matching agent row → None."""
        bogus_id = uuid4()
        request = _make_request(
            state_agent=None,
            headers={"X-Agent-Id": str(bogus_id)},
        )

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_factory = MagicMock(return_value=mock_session)

        mock_agent_repo_instance = AsyncMock()
        mock_agent_repo_instance.get_by_id = AsyncMock(side_effect=AgentNotFoundError(agent_id=bogus_id))

        mock_get_session_factory = MagicMock(return_value=mock_session_factory)

        with (
            patch(
                "src.database.session.get_session_factory",
                mock_get_session_factory,
            ),
            patch(
                "src.api.middleware.auth.AgentRepository",
                return_value=mock_agent_repo_instance,
            ),
        ):
            result = await get_current_agent(request)

        assert result is None

    async def test_returns_none_when_no_header(self):
        """No X-Agent-Id header and no state.agent → None."""
        request = _make_request(state_agent=None, headers={})

        result = await get_current_agent(request)

        assert result is None
