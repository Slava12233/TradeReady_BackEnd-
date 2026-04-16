"""Integration tests for agent management REST endpoints.

Covers all endpoints in ``src/api/routes/agents.py``:

- ``POST   /api/v1/agents``                          — create agent
- ``GET    /api/v1/agents``                           — list agents
- ``GET    /api/v1/agents/overview``                  — agent overview
- ``GET    /api/v1/agents/{id}``                      — get agent detail
- ``PUT    /api/v1/agents/{id}``                      — update agent
- ``POST   /api/v1/agents/{id}/clone``                — clone agent
- ``POST   /api/v1/agents/{id}/reset``                — reset agent
- ``POST   /api/v1/agents/{id}/archive``              — archive (soft delete)
- ``DELETE /api/v1/agents/{id}``                      — permanent delete
- ``POST   /api/v1/agents/{id}/regenerate-key``       — regenerate API key
- ``GET    /api/v1/agents/{id}/skill.md``             — download skill file

All external I/O (DB session, Redis) is mocked so tests run without real
infrastructure.  FastAPI's ``app.dependency_overrides`` is used to replace
the full dependency chain.

Run with::

    pytest tests/integration/test_agent_endpoints.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from src.agents.service import AgentCredentials
from src.config import Settings
from src.database.models import Account, Agent
from src.database.repositories.agent_repo import AgentNotFoundError
import src.database.session  # noqa: F401 — ensures submodule is importable by patch()
from src.utils.exceptions import PermissionDeniedError

pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Test settings — no real infra
# ---------------------------------------------------------------------------

_TEST_SETTINGS = Settings(
    jwt_secret="test_secret_that_is_at_least_32_characters_long_for_hs256",
    database_url="postgresql+asyncpg://test:test@localhost:5432/test",
    redis_url="redis://localhost:6379/15",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account(account_id=None):
    """Build a mock Account ORM object."""
    account = MagicMock(spec=Account)
    account.id = account_id or uuid4()
    account.api_key = "ak_live_testaccount"
    account.display_name = "TestAccount"
    account.status = "active"
    account.starting_balance = Decimal("10000.00")
    return account


def _make_agent(account_id, agent_id=None, display_name="TestAgent", status="active"):
    """Build a mock Agent ORM object."""
    agent = MagicMock(spec=Agent)
    agent.id = agent_id or uuid4()
    agent.account_id = account_id
    agent.display_name = display_name
    agent.api_key = "ak_live_testkey123456"
    agent.starting_balance = Decimal("10000.00")
    agent.llm_model = "gpt-4"
    agent.framework = "custom"
    agent.strategy_tags = ["momentum"]
    agent.risk_profile = {"max_position_size_pct": 25}
    agent.avatar_url = None
    agent.color = "#FF0000"
    agent.status = status
    agent.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    agent.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    return agent


# ---------------------------------------------------------------------------
# App + client factory
# ---------------------------------------------------------------------------


def _mock_redis() -> AsyncMock:
    """Create a fully mocked Redis client with pipeline support."""
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock(return_value=True)
    mock_redis.ttl = AsyncMock(return_value=60)
    mock_redis.hget = AsyncMock(return_value=None)
    mock_redis.hset = AsyncMock(return_value=1)
    mock_pipe = AsyncMock()
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)
    mock_pipe.incr = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 60])
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)
    return mock_redis


def _build_client(
    agent_service=None,
    account=None,
    *,
    skip_auth_override: bool = False,
) -> TestClient:
    """Create a ``TestClient`` with the full middleware stack and mocked infra.

    Patches ``_authenticate_request`` in the auth middleware so requests are
    authenticated without hitting any DB.  The patch stays active for the
    lifetime of the returned client (using ``patch.start()``).

    Args:
        agent_service: Optional pre-configured ``AsyncMock`` for AgentService.
        account: Optional mock Account for the auth override. If ``None`` and
            ``skip_auth_override`` is False, a default mock account is created.
        skip_auth_override: If True, do NOT override auth, so requests without
            credentials will be rejected by the middleware (401).

    Returns:
        A ``TestClient`` wrapping the fully configured application.
    """
    from src.api.middleware.auth import get_current_account
    from src.dependencies import get_agent_service, get_db_session, get_redis, get_settings

    if agent_service is None:
        agent_service = AsyncMock()

    mock_account = account if account is not None else _make_account()

    redis = _mock_redis()
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    # Start all patches — they must remain active during client requests.
    # The auth middleware calls _authenticate_request at *request time*,
    # not at app-creation time, so we use patch.start() instead of a
    # context manager.
    patchers = [
        patch("src.database.session.init_db", new_callable=AsyncMock),
        patch("src.database.session.close_db", new_callable=AsyncMock),
        patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock, return_value=redis),
        patch("src.api.websocket.handlers.start_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.handlers.stop_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.manager.ConnectionManager.disconnect_all", new_callable=AsyncMock),
    ]

    if not skip_auth_override:
        patchers.append(
            patch(
                "src.api.middleware.auth._authenticate_request",
                new_callable=AsyncMock,
                return_value=(mock_account, None),
            ),
        )
    else:
        # For no-auth tests, patch _authenticate_request to return (None, None)
        # so the middleware sends 401.
        patchers.append(
            patch(
                "src.api.middleware.auth._authenticate_request",
                new_callable=AsyncMock,
                return_value=(None, None),
            ),
        )

    for p in patchers:
        p.start()

    from src.main import create_app

    app = create_app()

    # --- dependency overrides ---
    app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS

    async def _override_db():
        yield mock_session

    app.dependency_overrides[get_db_session] = _override_db

    async def _override_redis():
        yield redis

    app.dependency_overrides[get_redis] = _override_redis

    svc_instance = agent_service

    async def _override_agent_service():
        return svc_instance

    app.dependency_overrides[get_agent_service] = _override_agent_service

    if not skip_auth_override:
        app.dependency_overrides[get_current_account] = lambda: mock_account

    client = TestClient(app, raise_server_exceptions=False)

    # Stop lifespan-only patches (indices 0-5); keep auth patch (index 6) alive
    # for the duration of client requests.
    for p in patchers[:6]:
        p.stop()

    # Attach cleanup to the client so callers can stop the auth patch.
    client._cleanup = lambda: patchers[6].stop()  # type: ignore[attr-defined]

    return client


@pytest.fixture(autouse=True)
def _cleanup_auth_patch():
    """Ensure the auth middleware patch is stopped after every test."""
    yield
    # Best-effort cleanup: stop any lingering _authenticate_request patch
    try:
        patch.stopall()
    except RuntimeError:
        pass


# ===========================================================================
# POST /api/v1/agents — create agent
# ===========================================================================


class TestCreateAgent:
    """Tests for POST /api/v1/agents."""

    def test_create_agent_returns_201(self) -> None:
        """Valid creation payload returns 201 with credentials."""
        mock_svc = AsyncMock()
        creds = AgentCredentials(
            agent_id=uuid4(),
            api_key="ak_live_newagentkey",
            display_name="AlphaBot",
            starting_balance=Decimal("10000.00"),
        )
        mock_svc.create_agent = AsyncMock(return_value=creds)

        client = _build_client(mock_svc)
        resp = client.post(
            "/api/v1/agents",
            json={"display_name": "AlphaBot"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["display_name"] == "AlphaBot"
        assert body["api_key"] == "ak_live_newagentkey"
        assert str(body["agent_id"]) == str(creds.agent_id)
        assert "message" in body

    def test_create_agent_with_custom_balance(self) -> None:
        """Custom starting_balance is echoed back in the response."""
        mock_svc = AsyncMock()
        creds = AgentCredentials(
            agent_id=uuid4(),
            api_key="ak_live_richbot",
            display_name="RichBot",
            starting_balance=Decimal("50000.00"),
        )
        mock_svc.create_agent = AsyncMock(return_value=creds)

        client = _build_client(mock_svc)
        resp = client.post(
            "/api/v1/agents",
            json={"display_name": "RichBot", "starting_balance": "50000.00"},
        )

        assert resp.status_code == 201
        assert Decimal(resp.json()["starting_balance"]) == Decimal("50000.00")

    def test_create_agent_requires_jwt_auth(self) -> None:
        """Without auth override, requests return 401."""
        client = _build_client(skip_auth_override=True)
        resp = client.post(
            "/api/v1/agents",
            json={"display_name": "NoAuth"},
        )

        assert resp.status_code == 401

    def test_create_agent_missing_display_name_returns_422(self) -> None:
        """Missing display_name field triggers Pydantic validation error."""
        client = _build_client()
        resp = client.post(
            "/api/v1/agents",
            json={"starting_balance": "10000.00"},
        )

        assert resp.status_code == 422

    def test_create_agent_empty_display_name_returns_422(self) -> None:
        """Empty display_name violates min_length=1."""
        client = _build_client()
        resp = client.post(
            "/api/v1/agents",
            json={"display_name": ""},
        )

        assert resp.status_code == 422

    def test_create_agent_negative_balance_returns_422(self) -> None:
        """Negative starting_balance violates gt=0."""
        client = _build_client()
        resp = client.post(
            "/api/v1/agents",
            json={"display_name": "Bot", "starting_balance": "-100"},
        )

        assert resp.status_code == 422

    def test_create_agent_with_all_fields(self) -> None:
        """All optional fields are accepted."""
        mock_svc = AsyncMock()
        creds = AgentCredentials(
            agent_id=uuid4(),
            api_key="ak_live_fullbot",
            display_name="FullBot",
            starting_balance=Decimal("10000.00"),
        )
        mock_svc.create_agent = AsyncMock(return_value=creds)

        client = _build_client(mock_svc)
        resp = client.post(
            "/api/v1/agents",
            json={
                "display_name": "FullBot",
                "starting_balance": "10000.00",
                "llm_model": "gpt-4",
                "framework": "langchain",
                "strategy_tags": ["momentum", "mean-reversion"],
                "risk_profile": {"max_position_size_pct": 30},
                "color": "#FF5733",
            },
        )

        assert resp.status_code == 201
        assert resp.json()["display_name"] == "FullBot"


# ===========================================================================
# GET /api/v1/agents — list agents
# ===========================================================================


class TestListAgents:
    """Tests for GET /api/v1/agents."""

    def test_list_agents_returns_agents(self) -> None:
        """List endpoint returns agents for the account."""
        account = _make_account()
        mock_svc = AsyncMock()
        agents = [
            _make_agent(account.id, display_name="Bot1"),
            _make_agent(account.id, display_name="Bot2"),
        ]
        mock_svc.list_agents = AsyncMock(return_value=agents)

        client = _build_client(mock_svc, account)
        resp = client.get("/api/v1/agents")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["agents"]) == 2

    def test_list_agents_returns_empty_list(self) -> None:
        """Empty agent list returns an empty array, not an error."""
        mock_svc = AsyncMock()
        mock_svc.list_agents = AsyncMock(return_value=[])

        client = _build_client(mock_svc)
        resp = client.get("/api/v1/agents")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["agents"] == []

    def test_list_agents_with_query_params(self) -> None:
        """Query parameters (include_archived, limit, offset) are accepted."""
        mock_svc = AsyncMock()
        mock_svc.list_agents = AsyncMock(return_value=[])

        client = _build_client(mock_svc)
        resp = client.get("/api/v1/agents?include_archived=true&limit=10&offset=5")

        assert resp.status_code == 200


# ===========================================================================
# GET /api/v1/agents/overview — agent overview
# ===========================================================================


class TestAgentOverview:
    """Tests for GET /api/v1/agents/overview."""

    def test_overview_returns_agents(self) -> None:
        """Overview endpoint returns list of agents."""
        account = _make_account()
        mock_svc = AsyncMock()
        agents = [_make_agent(account.id, display_name="OverviewBot")]
        mock_svc.list_agents = AsyncMock(return_value=agents)

        client = _build_client(mock_svc, account)
        resp = client.get("/api/v1/agents/overview")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["agents"]) == 1
        assert body["agents"][0]["display_name"] == "OverviewBot"

    def test_overview_empty(self) -> None:
        """Overview with no agents returns empty list."""
        mock_svc = AsyncMock()
        mock_svc.list_agents = AsyncMock(return_value=[])

        client = _build_client(mock_svc)
        resp = client.get("/api/v1/agents/overview")

        assert resp.status_code == 200
        assert resp.json()["agents"] == []


# ===========================================================================
# GET /api/v1/agents/{id} — get agent detail
# ===========================================================================


class TestGetAgent:
    """Tests for GET /api/v1/agents/{id}."""

    def test_get_agent_returns_agent(self) -> None:
        """Valid agent ID owned by the account returns agent detail."""
        account = _make_account()
        agent = _make_agent(account.id, display_name="DetailBot")
        mock_svc = AsyncMock()
        mock_svc.get_agent = AsyncMock(return_value=agent)

        client = _build_client(mock_svc, account)
        resp = client.get(f"/api/v1/agents/{agent.id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["display_name"] == "DetailBot"
        assert body["status"] == "active"
        assert str(body["id"]) == str(agent.id)

    def test_get_agent_not_found_returns_500(self) -> None:
        """Nonexistent agent ID causes AgentNotFoundError which is not a
        TradingPlatformError, so it falls through to the 500 catch-all."""
        mock_svc = AsyncMock()
        agent_id = uuid4()
        mock_svc.get_agent = AsyncMock(
            side_effect=AgentNotFoundError("Agent not found.", agent_id=agent_id),
        )

        client = _build_client(mock_svc)
        resp = client.get(f"/api/v1/agents/{agent_id}")

        assert resp.status_code == 500
        body = resp.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"

    def test_get_agent_wrong_account_returns_403(self) -> None:
        """Agent owned by a different account returns 403."""
        account = _make_account()
        other_account_id = uuid4()
        agent = _make_agent(other_account_id, display_name="OtherBot")
        mock_svc = AsyncMock()
        mock_svc.get_agent = AsyncMock(return_value=agent)

        client = _build_client(mock_svc, account)
        resp = client.get(f"/api/v1/agents/{agent.id}")

        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "PERMISSION_DENIED"

    def test_get_agent_response_shape(self) -> None:
        """Response includes all expected fields from AgentResponse."""
        account = _make_account()
        agent = _make_agent(account.id)
        mock_svc = AsyncMock()
        mock_svc.get_agent = AsyncMock(return_value=agent)

        client = _build_client(mock_svc, account)
        resp = client.get(f"/api/v1/agents/{agent.id}")

        assert resp.status_code == 200
        body = resp.json()
        expected_keys = {
            "id",
            "account_id",
            "display_name",
            "api_key_preview",
            "starting_balance",
            "llm_model",
            "framework",
            "strategy_tags",
            "risk_profile",
            "avatar_url",
            "color",
            "status",
            "created_at",
            "updated_at",
        }
        assert expected_keys.issubset(set(body.keys()))


# ===========================================================================
# PUT /api/v1/agents/{id} — update agent
# ===========================================================================


class TestUpdateAgent:
    """Tests for PUT /api/v1/agents/{id}."""

    def test_update_agent_returns_updated(self) -> None:
        """Update endpoint returns the updated agent."""
        account = _make_account()
        agent = _make_agent(account.id, display_name="UpdatedBot")
        mock_svc = AsyncMock()
        mock_svc.update_agent = AsyncMock(return_value=agent)

        client = _build_client(mock_svc, account)
        resp = client.put(
            f"/api/v1/agents/{agent.id}",
            json={"display_name": "UpdatedBot"},
        )

        assert resp.status_code == 200
        assert resp.json()["display_name"] == "UpdatedBot"

    def test_update_agent_partial_fields(self) -> None:
        """Partial update (only some fields) is accepted."""
        account = _make_account()
        agent = _make_agent(account.id)
        agent.llm_model = "claude-opus-4-20250514"
        mock_svc = AsyncMock()
        mock_svc.update_agent = AsyncMock(return_value=agent)

        client = _build_client(mock_svc, account)
        resp = client.put(
            f"/api/v1/agents/{agent.id}",
            json={"llm_model": "claude-opus-4-20250514"},
        )

        assert resp.status_code == 200

    def test_update_agent_empty_body_accepted(self) -> None:
        """An empty update body is valid (no fields to change)."""
        account = _make_account()
        agent = _make_agent(account.id)
        mock_svc = AsyncMock()
        mock_svc.update_agent = AsyncMock(return_value=agent)

        client = _build_client(mock_svc, account)
        resp = client.put(
            f"/api/v1/agents/{agent.id}",
            json={},
        )

        assert resp.status_code == 200


# ===========================================================================
# POST /api/v1/agents/{id}/clone — clone agent
# ===========================================================================


class TestCloneAgent:
    """Tests for POST /api/v1/agents/{id}/clone."""

    def test_clone_agent_returns_201(self) -> None:
        """Cloning an agent returns 201 with new credentials."""
        mock_svc = AsyncMock()
        creds = AgentCredentials(
            agent_id=uuid4(),
            api_key="ak_live_clonedkey",
            display_name="Copy of TestAgent",
            starting_balance=Decimal("10000.00"),
        )
        mock_svc.clone_agent = AsyncMock(return_value=creds)

        agent_id = uuid4()
        client = _build_client(mock_svc)
        resp = client.post(f"/api/v1/agents/{agent_id}/clone")

        assert resp.status_code == 201
        body = resp.json()
        assert body["api_key"] == "ak_live_clonedkey"
        assert body["display_name"] == "Copy of TestAgent"

    def test_clone_agent_with_new_name(self) -> None:
        """Clone with a custom name via query parameter."""
        mock_svc = AsyncMock()
        creds = AgentCredentials(
            agent_id=uuid4(),
            api_key="ak_live_namedclone",
            display_name="CustomClone",
            starting_balance=Decimal("10000.00"),
        )
        mock_svc.clone_agent = AsyncMock(return_value=creds)

        agent_id = uuid4()
        client = _build_client(mock_svc)
        resp = client.post(f"/api/v1/agents/{agent_id}/clone?new_name=CustomClone")

        assert resp.status_code == 201
        assert resp.json()["display_name"] == "CustomClone"


# ===========================================================================
# POST /api/v1/agents/{id}/reset — reset agent
# ===========================================================================


class TestResetAgent:
    """Tests for POST /api/v1/agents/{id}/reset."""

    def test_reset_agent_returns_agent(self) -> None:
        """Resetting an agent returns the refreshed agent."""
        account = _make_account()
        agent = _make_agent(account.id, display_name="ResetBot")
        mock_svc = AsyncMock()
        mock_svc.reset_agent = AsyncMock(return_value=agent)

        client = _build_client(mock_svc, account)
        resp = client.post(f"/api/v1/agents/{agent.id}/reset")

        assert resp.status_code == 200
        assert resp.json()["display_name"] == "ResetBot"


# ===========================================================================
# POST /api/v1/agents/{id}/archive — archive agent
# ===========================================================================


class TestArchiveAgent:
    """Tests for POST /api/v1/agents/{id}/archive."""

    def test_archive_agent_returns_agent(self) -> None:
        """Archiving an agent returns the agent with updated status."""
        account = _make_account()
        agent = _make_agent(account.id, status="archived")
        mock_svc = AsyncMock()
        mock_svc.archive_agent = AsyncMock(return_value=agent)

        client = _build_client(mock_svc, account)
        resp = client.post(f"/api/v1/agents/{agent.id}/archive")

        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"


# ===========================================================================
# DELETE /api/v1/agents/{id} — permanent delete
# ===========================================================================


class TestDeleteAgent:
    """Tests for DELETE /api/v1/agents/{id}."""

    def test_delete_agent_returns_204(self) -> None:
        """Permanent delete returns 204 No Content."""
        mock_svc = AsyncMock()
        mock_svc.delete_agent = AsyncMock(return_value=None)

        agent_id = uuid4()
        client = _build_client(mock_svc)
        resp = client.delete(f"/api/v1/agents/{agent_id}")

        assert resp.status_code == 204
        assert resp.content == b""

    def test_delete_agent_permission_denied(self) -> None:
        """Deleting an agent you don't own raises PermissionDeniedError."""
        mock_svc = AsyncMock()
        mock_svc.delete_agent = AsyncMock(
            side_effect=PermissionDeniedError("You do not own this agent."),
        )

        agent_id = uuid4()
        client = _build_client(mock_svc)
        resp = client.delete(f"/api/v1/agents/{agent_id}")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "PERMISSION_DENIED"


# ===========================================================================
# POST /api/v1/agents/{id}/regenerate-key — regenerate API key
# ===========================================================================


class TestRegenerateKey:
    """Tests for POST /api/v1/agents/{id}/regenerate-key."""

    def test_regenerate_key_returns_new_key(self) -> None:
        """Regenerating the API key returns the new plaintext key."""
        mock_svc = AsyncMock()
        mock_svc.regenerate_api_key = AsyncMock(return_value="ak_live_brandnewkey")

        agent_id = uuid4()
        client = _build_client(mock_svc)
        resp = client.post(f"/api/v1/agents/{agent_id}/regenerate-key")

        assert resp.status_code == 200
        body = resp.json()
        assert body["api_key"] == "ak_live_brandnewkey"
        assert str(body["agent_id"]) == str(agent_id)

    def test_regenerate_key_contains_message(self) -> None:
        """Response includes an advisory message about saving the key."""
        mock_svc = AsyncMock()
        mock_svc.regenerate_api_key = AsyncMock(return_value="ak_live_msgkey")

        agent_id = uuid4()
        client = _build_client(mock_svc)
        resp = client.post(f"/api/v1/agents/{agent_id}/regenerate-key")

        assert resp.status_code == 200
        assert "message" in resp.json()


# ===========================================================================
# GET /api/v1/agents/{id}/skill.md — download agent skill file
# ===========================================================================


class TestGetSkillMd:
    """Tests for GET /api/v1/agents/{id}/skill.md."""

    def test_skill_md_returns_text_markdown(self) -> None:
        """Skill file endpoint returns text/markdown content."""
        account = _make_account()
        agent = _make_agent(account.id, display_name="SkillBot")
        mock_svc = AsyncMock()
        mock_svc.get_agent = AsyncMock(return_value=agent)

        client = _build_client(mock_svc, account)
        resp = client.get(f"/api/v1/agents/{agent.id}/skill.md")

        assert resp.status_code == 200
        assert "text/markdown" in resp.headers.get("content-type", "")

    def test_skill_md_contains_agent_header(self) -> None:
        """Skill file contains the agent's name and ID in the header."""
        account = _make_account()
        agent = _make_agent(account.id, display_name="HeaderBot")
        mock_svc = AsyncMock()
        mock_svc.get_agent = AsyncMock(return_value=agent)

        client = _build_client(mock_svc, account)
        resp = client.get(f"/api/v1/agents/{agent.id}/skill.md")

        assert resp.status_code == 200
        content = resp.text
        assert "HeaderBot" in content
        assert str(agent.id) in content

    def test_skill_md_wrong_account_returns_403(self) -> None:
        """Downloading skill.md for an agent you don't own returns 403."""
        account = _make_account()
        other_account_id = uuid4()
        agent = _make_agent(other_account_id, display_name="OtherSkill")
        mock_svc = AsyncMock()
        mock_svc.get_agent = AsyncMock(return_value=agent)

        client = _build_client(mock_svc, account)
        resp = client.get(f"/api/v1/agents/{agent.id}/skill.md")

        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "PERMISSION_DENIED"
