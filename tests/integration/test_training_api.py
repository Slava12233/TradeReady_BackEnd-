"""Integration tests for training API endpoints.

Tests: register run, report episodes, complete, list, learning curve.
Uses sync TestClient with mocked infrastructure.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from starlette.testclient import TestClient

from src.config import Settings
import src.database.session  # noqa: F401 — ensures submodule is importable by patch()

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
    a.display_name = "Test"
    a.email = "test@test.com"
    return a


def _make_run(run_id=None, status="running", episodes=0, account_id=None):
    r = MagicMock()
    r.id = run_id or uuid4()
    r.account_id = account_id or uuid4()
    r.status = status
    r.episodes_completed = episodes
    r.episodes_total = None
    r.config = {"lr": 0.001}
    r.started_at = "2026-03-18T00:00:00+00:00"
    r.completed_at = None
    r.aggregate_stats = None
    r.learning_curve = None
    return r


@contextlib.contextmanager
def _build_client(mock_account=None, training_service=None):
    if mock_account is None:
        mock_account = _make_account()
    if training_service is None:
        training_service = AsyncMock()

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

        from src.dependencies import get_settings, get_training_run_service  # noqa: PLC0415

        app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS
        app.dependency_overrides[get_training_run_service] = lambda: training_service

        client = TestClient(app, raise_server_exceptions=False)
        yield client


def test_register_run():
    """POST /api/v1/training/runs registers a new run."""
    run_id = uuid4()
    svc = AsyncMock()
    run = _make_run(run_id=run_id)
    svc.register_run.return_value = run

    with _build_client(training_service=svc) as client:
        response = client.post(
            "/api/v1/training/runs",
            json={"run_id": str(run_id), "config": {"lr": 0.001}},
        )

    assert response.status_code == 201
    assert response.json()["status"] == "running"


def test_report_episode():
    """POST /api/v1/training/runs/{id}/episodes reports an episode."""
    account = _make_account()
    run_id = uuid4()
    svc = AsyncMock()
    ep = MagicMock()
    svc.record_episode.return_value = ep
    run = _make_run(run_id=run_id, episodes=1, account_id=account.id)
    svc.get_run.return_value = run

    with _build_client(mock_account=account, training_service=svc) as client:
        response = client.post(
            f"/api/v1/training/runs/{run_id}/episodes",
            json={"episode_number": 1, "roi_pct": 5.5, "reward_sum": 100},
        )

    assert response.status_code == 200
    assert response.json()["episodes_completed"] == 1


def test_complete_run():
    """POST /api/v1/training/runs/{id}/complete marks run done."""
    account = _make_account()
    run_id = uuid4()
    svc = AsyncMock()
    run = _make_run(run_id=run_id, status="completed", account_id=account.id)
    svc.get_run.return_value = run
    svc.complete_run.return_value = run

    with _build_client(mock_account=account, training_service=svc) as client:
        response = client.post(f"/api/v1/training/runs/{run_id}/complete")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_list_runs():
    """GET /api/v1/training/runs lists runs."""
    svc = AsyncMock()
    svc.list_runs.return_value = [_make_run(), _make_run()]

    with _build_client(training_service=svc) as client:
        response = client.get("/api/v1/training/runs")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_learning_curve():
    """GET /api/v1/training/runs/{id}/learning-curve returns curve data."""
    run_id = uuid4()
    svc = AsyncMock()
    svc.get_learning_curve.return_value = {
        "episode_numbers": [1, 2, 3],
        "raw_values": [1.0, 2.0, 3.0],
        "smoothed_values": [1.0, 1.5, 2.0],
        "metric": "roi_pct",
        "window": 2,
    }

    with _build_client(training_service=svc) as client:
        response = client.get(f"/api/v1/training/runs/{run_id}/learning-curve?metric=roi_pct&window=2")

    assert response.status_code == 200
    data = response.json()
    assert len(data["raw_values"]) == 3
    assert data["metric"] == "roi_pct"


def test_compare_runs():
    """GET /api/v1/training/compare returns comparison data."""
    id1, id2 = uuid4(), uuid4()
    svc = AsyncMock()
    svc.compare_runs.return_value = [
        {"run_id": str(id1), "status": "completed", "episodes_completed": 100, "aggregate_stats": {"avg_roi_pct": 5}},
        {"run_id": str(id2), "status": "completed", "episodes_completed": 50, "aggregate_stats": {"avg_roi_pct": 3}},
    ]

    with _build_client(training_service=svc) as client:
        response = client.get(f"/api/v1/training/compare?run_ids={id1},{id2}")

    assert response.status_code == 200
    assert len(response.json()["runs"]) == 2
