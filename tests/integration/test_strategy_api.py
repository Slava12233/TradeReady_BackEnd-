"""Integration tests for the Strategy CRUD API.

Tests: full CRUD lifecycle through REST, owner isolation, version creation,
deploy/undeploy.

Uses sync TestClient with mocked infrastructure (no Docker needed).
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from src.config import Settings

# ---------------------------------------------------------------------------
# Test settings & factories
# ---------------------------------------------------------------------------

_TEST_JWT_SECRET = "test_secret_that_is_at_least_32_chars_long!!"

_TEST_SETTINGS = Settings(
    database_url="postgresql+asyncpg://test:test@localhost:5432/test",
    redis_url="redis://localhost:6379/0",
    jwt_secret=_TEST_JWT_SECRET,
    jwt_expiry_hours=1,
    default_starting_balance=10000.0,
    trading_fee_pct=0.001,
    default_slippage_factor=0.1,
)

VALID_DEFINITION = {
    "pairs": ["BTCUSDT"],
    "timeframe": "1h",
    "entry_conditions": {"rsi_below": 30},
    "exit_conditions": {"take_profit_pct": 5, "stop_loss_pct": 2},
    "position_size_pct": 10,
    "max_positions": 3,
}


def _make_account(account_id=None):
    """Create a mock Account ORM object."""
    a = MagicMock()
    a.id = account_id or uuid4()
    a.status = "active"
    a.display_name = "Test Account"
    a.email = "test@test.com"
    a.api_key_hash = "dummy"
    return a


def _make_strategy(account_id=None, strategy_id=None, status="draft", current_version=1, name="Test Strategy"):
    """Create a mock Strategy ORM object."""
    s = MagicMock()
    s.id = strategy_id or uuid4()
    s.account_id = account_id or uuid4()
    s.name = name
    s.description = None
    s.current_version = current_version
    s.status = status
    s.deployed_at = None
    s.created_at = "2026-03-18T00:00:00+00:00"
    s.updated_at = "2026-03-18T00:00:00+00:00"
    return s


def _make_version(strategy_id=None, version=1, definition=None, status="draft"):
    """Create a mock StrategyVersion ORM object."""
    v = MagicMock()
    v.id = uuid4()
    v.strategy_id = strategy_id or uuid4()
    v.version = version
    v.definition = definition or VALID_DEFINITION
    v.change_notes = None
    v.parent_version = None
    v.status = status
    v.created_at = "2026-03-18T00:00:00+00:00"
    return v


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _build_client(mock_account=None, strategy_service=None):
    """Build a TestClient with mocked auth and strategy service."""
    if mock_account is None:
        mock_account = _make_account()
    if strategy_service is None:
        strategy_service = AsyncMock()

    with (
        patch("src.database.session.init_db", new_callable=AsyncMock),
        patch("src.database.session.close_db", new_callable=AsyncMock),
        patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock),
        patch("src.api.websocket.handlers.start_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.handlers.stop_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.manager.ConnectionManager.disconnect_all", new_callable=AsyncMock),
        patch(
            "src.api.middleware.auth._authenticate_request",
            new_callable=AsyncMock,
            return_value=(mock_account, None),
        ),
    ):
        from src.main import create_app  # noqa: PLC0415

        app = create_app()

        from src.dependencies import get_settings, get_strategy_service  # noqa: PLC0415

        app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS
        app.dependency_overrides[get_strategy_service] = lambda: strategy_service

        client = TestClient(app, raise_server_exceptions=False)
        yield client, mock_account, strategy_service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_strategy():
    """POST /api/v1/strategies creates a strategy and returns 201."""
    account = _make_account()
    strategy = _make_strategy(account_id=account.id)
    svc = AsyncMock()
    svc.create_strategy.return_value = strategy

    with _build_client(mock_account=account, strategy_service=svc) as (client, _, _):
        response = client.post(
            "/api/v1/strategies",
            json={"name": "Test Strategy", "description": "A test", "definition": VALID_DEFINITION},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Strategy"
    assert data["status"] == "draft"


def test_list_strategies():
    """GET /api/v1/strategies returns a paginated list."""
    account = _make_account()
    strategy = _make_strategy(account_id=account.id)
    svc = AsyncMock()
    svc.list_strategies.return_value = ([strategy], 1)

    with _build_client(mock_account=account, strategy_service=svc) as (client, _, _):
        response = client.get("/api/v1/strategies")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert len(data["strategies"]) == 1


def test_get_strategy_detail():
    """GET /api/v1/strategies/{id} returns detail with definition."""
    account = _make_account()
    strategy_id = uuid4()
    strategy = _make_strategy(account_id=account.id, strategy_id=strategy_id)
    version = _make_version(strategy_id=strategy_id, version=1)
    svc = AsyncMock()
    svc.get_strategy.return_value = strategy
    svc.get_version.return_value = version
    svc.get_latest_test_results.return_value = None

    with _build_client(mock_account=account, strategy_service=svc) as (client, _, _):
        response = client.get(f"/api/v1/strategies/{strategy_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["current_definition"] is not None


def test_update_strategy():
    """PUT /api/v1/strategies/{id} updates metadata."""
    account = _make_account()
    strategy_id = uuid4()
    updated = _make_strategy(account_id=account.id, strategy_id=strategy_id, name="Updated Name")
    svc = AsyncMock()
    svc.update_strategy.return_value = updated

    with _build_client(mock_account=account, strategy_service=svc) as (client, _, _):
        response = client.put(
            f"/api/v1/strategies/{strategy_id}",
            json={"name": "Updated Name"},
        )

    assert response.status_code == 200
    assert response.json()["name"] == "Updated Name"


def test_archive_strategy():
    """DELETE /api/v1/strategies/{id} archives the strategy."""
    account = _make_account()
    strategy_id = uuid4()
    archived = _make_strategy(account_id=account.id, strategy_id=strategy_id, status="archived")
    svc = AsyncMock()
    svc.archive_strategy.return_value = archived

    with _build_client(mock_account=account, strategy_service=svc) as (client, _, _):
        response = client.delete(f"/api/v1/strategies/{strategy_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "archived"


def test_create_version():
    """POST /api/v1/strategies/{id}/versions creates a new version."""
    account = _make_account()
    strategy_id = uuid4()
    version = _make_version(strategy_id=strategy_id, version=2)
    version.change_notes = "Tightened RSI"
    version.parent_version = 1
    svc = AsyncMock()
    svc.create_version.return_value = version

    with _build_client(mock_account=account, strategy_service=svc) as (client, _, _):
        response = client.post(
            f"/api/v1/strategies/{strategy_id}/versions",
            json={"definition": VALID_DEFINITION, "change_notes": "Tightened RSI"},
        )

    assert response.status_code == 201
    assert response.json()["version"] == 2


def test_deploy_and_undeploy():
    """POST deploy and undeploy endpoints work correctly."""
    account = _make_account()
    strategy_id = uuid4()

    # Deploy
    deployed = _make_strategy(account_id=account.id, strategy_id=strategy_id, status="deployed")
    deployed.deployed_at = "2026-03-18T00:00:00+00:00"
    svc = AsyncMock()
    svc.deploy.return_value = deployed

    with _build_client(mock_account=account, strategy_service=svc) as (client, _, _):
        response = client.post(
            f"/api/v1/strategies/{strategy_id}/deploy",
            json={"version": 1},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "deployed"

    # Undeploy
    undeployed = _make_strategy(account_id=account.id, strategy_id=strategy_id, status="validated")
    svc2 = AsyncMock()
    svc2.undeploy.return_value = undeployed

    with _build_client(mock_account=account, strategy_service=svc2) as (client2, _, _):
        response2 = client2.post(f"/api/v1/strategies/{strategy_id}/undeploy")

    assert response2.status_code == 200
    assert response2.json()["status"] == "validated"


def test_owner_isolation():
    """Accessing another account's strategy returns 403."""
    account = _make_account()
    strategy_id = uuid4()
    svc = AsyncMock()

    from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

    svc.get_strategy.side_effect = PermissionDeniedError("You do not own this strategy.")

    with _build_client(mock_account=account, strategy_service=svc) as (client, _, _):
        response = client.get(f"/api/v1/strategies/{strategy_id}")

    assert response.status_code == 403
