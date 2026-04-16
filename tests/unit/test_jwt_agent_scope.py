"""Regression tests for JWT agent scope bypass (P0 security fix).

Verifies that the ``get_current_agent`` dependency enforces ownership when
resolving an agent from the ``X-Agent-Id`` header during JWT authentication.

Security scenario: Account A holds a valid JWT.  If Account A sends
``X-Agent-Id: <agent_belonging_to_account_B>``, the platform must raise
``PermissionDeniedError`` (HTTP 403) — NOT silently hand back the foreign
agent object.

The API key auth path is also exercised to confirm it remains unchanged.
"""

from __future__ import annotations

try:
    import src.database.session  # noqa: F401  # register submodule for mock.patch resolution
except ImportError:
    pass  # asyncpg not available on Windows — CI has it

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.api.middleware.auth import (
    _resolve_account_from_api_key,
    get_current_agent,
)
from src.database.repositories.agent_repo import AgentNotFoundError
from src.utils.exceptions import PermissionDeniedError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account(*, account_id=None, status: str = "active") -> MagicMock:
    """Build a minimal mock Account ORM object."""
    acct = MagicMock()
    acct.id = account_id or uuid4()
    acct.status = status
    acct.api_key = f"ak_live_acct_{acct.id.hex[:8]}"
    return acct


def _make_agent(*, agent_id=None, account_id=None, status: str = "active") -> MagicMock:
    """Build a minimal mock Agent ORM object."""
    ag = MagicMock()
    ag.id = agent_id or uuid4()
    ag.account_id = account_id or uuid4()
    ag.status = status
    ag.api_key = f"ak_live_agent_{ag.id.hex[:8]}"
    return ag


def _make_request(
    *,
    headers: dict[str, str] | None = None,
    state_account: MagicMock | None = None,
    state_agent: MagicMock | None = None,
    has_agent_attr: bool = True,
) -> MagicMock:
    """Build a mock FastAPI Request with configurable headers and state."""
    request = MagicMock()
    request.headers = headers or {}

    state = MagicMock()
    if has_agent_attr:
        state.agent = state_agent
    else:
        del state.agent

    state.account = state_account
    request.state = state
    return request


def _make_session_factory_patch(agent: MagicMock) -> tuple[MagicMock, MagicMock]:
    """Build mock session factory and AgentRepository for patching.

    Returns:
        (mock_get_session_factory, mock_agent_repo_instance)
    """
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_session_factory = MagicMock(return_value=mock_session)
    mock_get_session_factory = MagicMock(return_value=mock_session_factory)

    mock_agent_repo = AsyncMock()
    mock_agent_repo.get_by_id = AsyncMock(return_value=agent)

    return mock_get_session_factory, mock_agent_repo


# ---------------------------------------------------------------------------
# JWT path: cross-account agent rejection (the core security regression test)
# ---------------------------------------------------------------------------


class TestJwtAgentOwnershipEnforcement:
    """A JWT holder must not be able to access an agent owned by a different account."""

    async def test_cross_account_agent_raises_403(self):
        """Account A's JWT + Account B's agent ID → PermissionDeniedError."""
        account_a = _make_account()
        account_b = _make_account()  # different account
        agent_of_b = _make_agent(account_id=account_b.id)

        request = _make_request(
            state_account=account_a,  # authenticated as Account A
            state_agent=None,  # JWT auth: middleware sets no agent
            headers={"X-Agent-Id": str(agent_of_b.id)},  # but header points to B's agent
        )

        mock_get_session_factory, mock_agent_repo = _make_session_factory_patch(agent_of_b)

        with (
            patch(
                "src.database.session.get_session_factory",
                mock_get_session_factory,
            ),
            patch(
                "src.api.middleware.auth.AgentRepository",
                return_value=mock_agent_repo,
            ),
        ):
            with pytest.raises(PermissionDeniedError, match="does not belong to this account"):
                await get_current_agent(request)

    async def test_cross_account_agent_error_code_is_permission_denied(self):
        """The raised error must carry the PERMISSION_DENIED code for correct HTTP 403 serialisation."""
        account_a = _make_account()
        account_b = _make_account()
        agent_of_b = _make_agent(account_id=account_b.id)

        request = _make_request(
            state_account=account_a,
            state_agent=None,
            headers={"X-Agent-Id": str(agent_of_b.id)},
        )

        mock_get_session_factory, mock_agent_repo = _make_session_factory_patch(agent_of_b)

        with (
            patch("src.database.session.get_session_factory", mock_get_session_factory),
            patch("src.api.middleware.auth.AgentRepository", return_value=mock_agent_repo),
        ):
            with pytest.raises(PermissionDeniedError) as exc_info:
                await get_current_agent(request)

        assert exc_info.value.http_status == 403
        assert exc_info.value.code == "PERMISSION_DENIED"

    async def test_own_agent_is_allowed(self):
        """Account A's JWT + Account A's own agent → agent returned without error."""
        account_a = _make_account()
        agent_of_a = _make_agent(account_id=account_a.id)

        request = _make_request(
            state_account=account_a,
            state_agent=None,
            headers={"X-Agent-Id": str(agent_of_a.id)},
        )

        mock_get_session_factory, mock_agent_repo = _make_session_factory_patch(agent_of_a)

        with (
            patch("src.database.session.get_session_factory", mock_get_session_factory),
            patch("src.api.middleware.auth.AgentRepository", return_value=mock_agent_repo),
        ):
            result = await get_current_agent(request)

        assert result is agent_of_a
        mock_agent_repo.get_by_id.assert_awaited_once_with(agent_of_a.id)

    async def test_nonexistent_agent_returns_none_not_error(self):
        """X-Agent-Id that references no existing agent row → None (not 403)."""
        account_a = _make_account()
        bogus_agent_id = uuid4()

        request = _make_request(
            state_account=account_a,
            state_agent=None,
            headers={"X-Agent-Id": str(bogus_agent_id)},
        )

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory = MagicMock(return_value=mock_session)
        mock_get_session_factory = MagicMock(return_value=mock_session_factory)

        mock_agent_repo = AsyncMock()
        mock_agent_repo.get_by_id = AsyncMock(side_effect=AgentNotFoundError(agent_id=bogus_agent_id))

        with (
            patch("src.database.session.get_session_factory", mock_get_session_factory),
            patch("src.api.middleware.auth.AgentRepository", return_value=mock_agent_repo),
        ):
            result = await get_current_agent(request)

        assert result is None

    async def test_no_account_on_request_state_skips_ownership_check(self):
        """If request.state.account is absent (middleware bypassed), ownership
        check is skipped and the agent is returned as-is.

        This is the test/fallback path where ``AuthMiddleware`` was not mounted.
        The ownership check only fires when an authenticated account is present.
        """
        some_agent = _make_agent()

        # request.state.account is None → no account context to enforce against
        request = _make_request(
            state_account=None,
            state_agent=None,
            headers={"X-Agent-Id": str(some_agent.id)},
        )

        mock_get_session_factory, mock_agent_repo = _make_session_factory_patch(some_agent)

        with (
            patch("src.database.session.get_session_factory", mock_get_session_factory),
            patch("src.api.middleware.auth.AgentRepository", return_value=mock_agent_repo),
        ):
            result = await get_current_agent(request)

        assert result is some_agent


# ---------------------------------------------------------------------------
# JWT path: header format edge cases
# ---------------------------------------------------------------------------


class TestJwtAgentHeaderEdgeCases:
    """Edge cases for X-Agent-Id header parsing in the JWT path."""

    async def test_invalid_uuid_header_returns_none(self):
        """Malformed UUID in X-Agent-Id → None (not an error)."""
        account = _make_account()
        request = _make_request(
            state_account=account,
            state_agent=None,
            headers={"X-Agent-Id": "not-a-valid-uuid"},
        )

        result = await get_current_agent(request)

        assert result is None

    async def test_no_header_returns_none(self):
        """No X-Agent-Id header and no state.agent → None."""
        account = _make_account()
        request = _make_request(state_account=account, state_agent=None, headers={})

        result = await get_current_agent(request)

        assert result is None

    async def test_empty_header_returns_none(self):
        """Empty (whitespace-only) X-Agent-Id header → None."""
        account = _make_account()
        request = _make_request(
            state_account=account,
            state_agent=None,
            headers={"X-Agent-Id": "   "},
        )

        result = await get_current_agent(request)

        assert result is None


# ---------------------------------------------------------------------------
# JWT path: agent already on request.state (already-resolved agent)
# ---------------------------------------------------------------------------


class TestJwtAgentFromState:
    """When AuthMiddleware already set request.state.agent, return it immediately."""

    async def test_returns_agent_from_state_without_db_lookup(self):
        """If state.agent is set, skip the ownership check and DB query entirely."""
        account = _make_account()
        agent = _make_agent(account_id=account.id)

        request = _make_request(state_account=account, state_agent=agent)

        result = await get_current_agent(request)

        assert result is agent

    async def test_returns_none_when_state_agent_is_none_and_no_header(self):
        """Legacy API-key auth with no agent context → None."""
        account = _make_account()
        request = _make_request(state_account=account, state_agent=None, headers={})

        result = await get_current_agent(request)

        assert result is None


# ---------------------------------------------------------------------------
# API key path: ownership check does NOT apply (verify it remains unchanged)
# ---------------------------------------------------------------------------


class TestApiKeyAuthPathUnchanged:
    """The API-key auth path sets state.agent in the middleware itself and is
    unaffected by the JWT ownership fix.

    _resolve_account_from_api_key already verifies the relationship between the
    API key, agent, and owning account.  These tests confirm that code path
    still works correctly after the JWT fix.
    """

    async def test_api_key_returns_correct_account_and_agent(self):
        """API key belonging to an agent → (owning_account, agent) tuple."""
        account = _make_account()
        agent = _make_agent(account_id=account.id)

        account_repo = AsyncMock()
        account_repo.get_by_id = AsyncMock(return_value=account)

        agent_repo = AsyncMock()
        agent_repo.get_by_api_key = AsyncMock(return_value=agent)

        result = await _resolve_account_from_api_key(agent.api_key, account_repo, agent_repo)

        assert result == (account, agent)

    async def test_api_key_agent_already_on_state_is_returned_directly(self):
        """When state.agent is pre-populated by the middleware (API-key path),
        get_current_agent returns it without a DB round-trip."""
        account = _make_account()
        agent = _make_agent(account_id=account.id)

        # Simulate what AuthMiddleware does for API-key auth:
        # sets both state.account AND state.agent before the route handler runs.
        request = _make_request(state_account=account, state_agent=agent)

        result = await get_current_agent(request)

        assert result is agent
