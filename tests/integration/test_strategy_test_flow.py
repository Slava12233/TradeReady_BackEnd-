"""Integration test: strategy test flow through REST API.

Tests: create strategy → trigger test → list tests → get results.
Uses sync TestClient with mocked infrastructure.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from starlette.testclient import TestClient

from src.config import Settings

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


def _make_account():
    a = MagicMock()
    a.id = uuid4()
    a.status = "active"
    a.display_name = "Test Account"
    a.email = "test@test.com"
    return a


@contextlib.contextmanager
def _build_client(mock_account=None, strategy_service=None, orchestrator=None):
    if mock_account is None:
        mock_account = _make_account()
    if strategy_service is None:
        strategy_service = AsyncMock()
    if orchestrator is None:
        orchestrator = AsyncMock()

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

        from src.dependencies import (  # noqa: PLC0415
            get_settings,
            get_strategy_service,
            get_test_orchestrator,
        )

        app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS
        app.dependency_overrides[get_strategy_service] = lambda: strategy_service
        app.dependency_overrides[get_test_orchestrator] = lambda: orchestrator

        client = TestClient(app, raise_server_exceptions=False)
        yield client, mock_account, strategy_service, orchestrator


def test_start_test_run():
    """POST /api/v1/strategies/{id}/test triggers a test run."""
    strategy_id = uuid4()
    test_run_id = uuid4()
    orchestrator = AsyncMock()
    orchestrator.start_test.return_value = test_run_id
    orchestrator.get_progress.return_value = {
        "test_run_id": str(test_run_id),
        "status": "queued",
        "episodes_total": 10,
        "episodes_completed": 0,
        "progress_pct": 0,
    }

    with _build_client(orchestrator=orchestrator) as (client, _, _, _):
        response = client.post(
            f"/api/v1/strategies/{strategy_id}/test",
            json={
                "version": 1,
                "episodes": 10,
                "date_range": {"start": "2025-01-01T00:00:00Z", "end": "2025-03-01T00:00:00Z"},
            },
        )

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "queued"
    assert data["episodes_total"] == 10


def test_list_test_runs():
    """GET /api/v1/strategies/{id}/tests lists test runs."""
    strategy_id = uuid4()
    svc = AsyncMock()
    strategy = MagicMock()
    strategy.account_id = uuid4()
    svc.get_strategy.return_value = strategy

    test_run = MagicMock()
    test_run.id = uuid4()
    test_run.status = "completed"
    test_run.episodes_total = 10
    test_run.episodes_completed = 10
    test_run.version = 1
    test_run.created_at = "2026-03-18T00:00:00Z"
    test_run.started_at = "2026-03-18T00:01:00Z"
    test_run.completed_at = "2026-03-18T00:10:00Z"
    svc.list_test_runs.return_value = [test_run]

    with _build_client(strategy_service=svc) as (client, _, _, _):
        response = client.get(f"/api/v1/strategies/{strategy_id}/tests")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "completed"


def test_get_test_results():
    """GET /api/v1/strategies/{id}/tests/{test_id} returns results."""
    strategy_id = uuid4()
    test_id = uuid4()
    svc = AsyncMock()
    strategy = MagicMock()
    strategy.account_id = uuid4()
    svc.get_strategy.return_value = strategy

    test_run = MagicMock()
    test_run.id = test_id
    test_run.status = "completed"
    test_run.episodes_total = 10
    test_run.episodes_completed = 10
    test_run.version = 1
    test_run.created_at = "2026-03-18T00:00:00Z"
    test_run.started_at = None
    test_run.completed_at = None
    test_run.results = {"avg_roi_pct": 5.5}
    test_run.recommendations = ["Consider widening TP"]
    test_run.config = {"episodes": 10}
    svc.get_test_run.return_value = test_run

    with _build_client(strategy_service=svc) as (client, _, _, _):
        response = client.get(f"/api/v1/strategies/{strategy_id}/tests/{test_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["results"]["avg_roi_pct"] == 5.5
    assert len(data["recommendations"]) == 1


def test_cancel_test():
    """POST cancel endpoint cancels a test run."""
    strategy_id = uuid4()
    test_id = uuid4()
    svc = AsyncMock()
    strategy = MagicMock()
    strategy.account_id = uuid4()
    svc.get_strategy.return_value = strategy

    orchestrator = AsyncMock()
    orchestrator.get_progress.return_value = {
        "status": "cancelled",
        "episodes_total": 10,
        "episodes_completed": 3,
        "progress_pct": 30,
    }

    with _build_client(strategy_service=svc, orchestrator=orchestrator) as (client, _, _, _):
        response = client.post(f"/api/v1/strategies/{strategy_id}/tests/{test_id}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_compare_versions():
    """GET compare-versions returns comparison between two versions."""
    strategy_id = uuid4()
    svc = AsyncMock()
    strategy = MagicMock()
    strategy.account_id = uuid4()
    svc.get_strategy.return_value = strategy

    tr1 = MagicMock()
    tr1.version = 1
    tr1.status = "completed"
    tr1.results = {
        "avg_roi_pct": 3.0,
        "avg_sharpe": 0.8,
        "avg_max_drawdown_pct": 5.0,
        "total_trades": 100,
        "episodes_completed": 10,
    }
    tr2 = MagicMock()
    tr2.version = 2
    tr2.status = "completed"
    tr2.results = {
        "avg_roi_pct": 7.0,
        "avg_sharpe": 1.2,
        "avg_max_drawdown_pct": 4.0,
        "total_trades": 80,
        "episodes_completed": 10,
    }

    svc.list_test_runs.return_value = [tr1, tr2]

    with _build_client(strategy_service=svc) as (client, _, _, _):
        response = client.get(f"/api/v1/strategies/{strategy_id}/compare-versions?v1=1&v2=2")

    assert response.status_code == 200
    data = response.json()
    assert data["improvements"]["roi_pct"] == 4.0
    assert "improves" in data["verdict"].lower()
