"""Integration tests for POST /api/v1/backtest/{session_id}/step/batch/fast.

Covers:
- Endpoint returns correct response shape (all BatchStepFastResponse fields)
- 404 error on invalid / non-active session_id
- 422 validation error when steps <= 0
- Batch completes session correctly (is_complete + steps_executed)
- include_intermediate_trades flag is forwarded to engine
- Auth required (401 without credentials)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from src.config import Settings
from src.database.models import Account

pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Test settings
# ---------------------------------------------------------------------------

_TEST_JWT_SECRET = "test_secret_that_is_at_least_32_characters_long_for_hs256"

_TEST_SETTINGS = Settings(
    jwt_secret=_TEST_JWT_SECRET,
    database_url="postgresql+asyncpg://test:test@localhost:5432/test",
    redis_url="redis://localhost:6379/15",
    jwt_expiry_hours=1,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account(
    account_id=None,
    api_key: str = "ak_live_testkey",
) -> Account:
    """Build a mock Account ORM object."""
    account = MagicMock(spec=Account)
    account.id = account_id or uuid4()
    account.api_key = api_key
    account.display_name = "TestBot"
    account.status = "active"
    account.starting_balance = Decimal("10000.00")
    return account


def _mock_redis() -> AsyncMock:
    """Create a fully mocked Redis client with pipeline support."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    redis.ttl = AsyncMock(return_value=60)
    redis.hget = AsyncMock(return_value=None)
    redis.hset = AsyncMock(return_value=1)
    mock_pipe = AsyncMock()
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)
    mock_pipe.incr = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 60])
    redis.pipeline = MagicMock(return_value=mock_pipe)
    return redis


def _make_batch_fast_engine_result(
    steps_executed: int = 5,
    is_complete: bool = False,
    step: int = 5,
    total_steps: int = 100,
):
    """Build a mock BatchStepResult that the engine would return."""
    from src.backtesting.sandbox import PortfolioSummary

    portfolio = PortfolioSummary(
        total_equity=Decimal("10050.00"),
        available_cash=Decimal("9000.00"),
        position_value=Decimal("1050.00"),
        unrealized_pnl=Decimal("50.00"),
        realized_pnl=Decimal("0.00"),
        positions=[],
    )
    from src.backtesting.engine import BatchStepResult

    return BatchStepResult(
        virtual_time=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
        step=step,
        total_steps=total_steps,
        progress_pct=Decimal("5.00"),
        prices={"BTCUSDT": Decimal("50000")},
        orders_filled=[],
        portfolio=portfolio,
        is_complete=is_complete,
        remaining_steps=max(0, total_steps - step),
        steps_executed=steps_executed,
    )


def _build_client(
    mock_engine: AsyncMock | None = None,
    mock_account: Account | None = None,
) -> TestClient:
    """Create a TestClient with mocked infra and a mock BacktestEngine."""
    from src.api.middleware.auth import get_current_account
    from src.dependencies import get_backtest_engine, get_db_session, get_redis, get_settings

    if mock_account is None:
        mock_account = _make_account()
    if mock_engine is None:
        mock_engine = MagicMock()

    redis = _mock_redis()
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    patchers = [
        patch("src.database.session.init_db", new_callable=AsyncMock),
        patch("src.database.session.close_db", new_callable=AsyncMock),
        patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock, return_value=redis),
        patch("src.api.websocket.handlers.start_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.handlers.stop_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.manager.ConnectionManager.disconnect_all", new_callable=AsyncMock),
        patch(
            "src.api.middleware.auth._authenticate_request",
            new_callable=AsyncMock,
            return_value=(mock_account, None),
        ),
    ]
    for p in patchers:
        p.start()

    from src.main import create_app

    app = create_app()

    app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS

    async def _override_db():
        yield mock_session

    app.dependency_overrides[get_db_session] = _override_db

    async def _override_redis():
        yield redis

    app.dependency_overrides[get_redis] = _override_redis
    app.dependency_overrides[get_current_account] = lambda: mock_account
    app.dependency_overrides[get_backtest_engine] = lambda: mock_engine

    client = TestClient(app, raise_server_exceptions=False)

    # Stop lifespan patches (already ran); keep auth patch alive for request time.
    for p in patchers[:6]:
        p.stop()
    client._auth_patcher = patchers[6]  # type: ignore[attr-defined]

    return client


def _build_client_no_auth() -> TestClient:
    """Create a TestClient WITHOUT auth — middleware returns (None, None)."""
    from src.dependencies import get_db_session, get_redis, get_settings

    redis = _mock_redis()
    mock_session = AsyncMock()

    patchers = [
        patch("src.database.session.init_db", new_callable=AsyncMock),
        patch("src.database.session.close_db", new_callable=AsyncMock),
        patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock, return_value=redis),
        patch("src.api.websocket.handlers.start_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.handlers.stop_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.manager.ConnectionManager.disconnect_all", new_callable=AsyncMock),
        patch(
            "src.api.middleware.auth._authenticate_request",
            new_callable=AsyncMock,
            return_value=(None, None),
        ),
    ]
    for p in patchers:
        p.start()

    from src.main import create_app

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS

    async def _override_db():
        yield mock_session

    app.dependency_overrides[get_db_session] = _override_db

    async def _override_redis():
        yield redis

    app.dependency_overrides[get_redis] = _override_redis

    client = TestClient(app, raise_server_exceptions=False)
    for p in patchers[:6]:
        p.stop()
    client._auth_patcher = patchers[6]  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------------------
# Tests: response shape
# ---------------------------------------------------------------------------


class TestBatchStepFastResponseShape:
    """Verify the endpoint returns BatchStepFastResponse with all required fields."""

    def test_response_contains_all_fields(self):
        """Happy path: all BatchStepFastResponse fields are present."""
        session_id = str(uuid4())
        mock_engine = MagicMock()
        mock_engine.step_batch_fast = AsyncMock(
            return_value=_make_batch_fast_engine_result(steps_executed=5)
        )

        with _build_client(mock_engine=mock_engine) as client:
            resp = client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": 5},
            )

        assert resp.status_code == 200
        data = resp.json()

        required_fields = {
            "virtual_time",
            "step",
            "total_steps",
            "progress_pct",
            "prices",
            "orders_filled",
            "portfolio",
            "is_complete",
            "remaining_steps",
            "steps_executed",
        }
        assert required_fields.issubset(data.keys()), (
            f"Missing fields: {required_fields - data.keys()}"
        )

    def test_steps_executed_matches_engine_result(self):
        """steps_executed in the response matches what the engine returned."""
        session_id = str(uuid4())
        mock_engine = MagicMock()
        mock_engine.step_batch_fast = AsyncMock(
            return_value=_make_batch_fast_engine_result(steps_executed=7)
        )

        with _build_client(mock_engine=mock_engine) as client:
            resp = client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": 7},
            )

        assert resp.status_code == 200
        assert resp.json()["steps_executed"] == 7

    def test_is_complete_false_mid_session(self):
        """is_complete is False when the engine reports the session is ongoing."""
        session_id = str(uuid4())
        mock_engine = MagicMock()
        mock_engine.step_batch_fast = AsyncMock(
            return_value=_make_batch_fast_engine_result(is_complete=False)
        )

        with _build_client(mock_engine=mock_engine) as client:
            resp = client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": 5},
            )

        assert resp.status_code == 200
        assert resp.json()["is_complete"] is False

    def test_prices_serialized_as_string_dict(self):
        """prices dict values are strings (Decimal serialized to str)."""
        session_id = str(uuid4())
        mock_engine = MagicMock()
        mock_engine.step_batch_fast = AsyncMock(
            return_value=_make_batch_fast_engine_result()
        )

        with _build_client(mock_engine=mock_engine) as client:
            resp = client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": 5},
            )

        assert resp.status_code == 200
        prices = resp.json()["prices"]
        assert isinstance(prices, dict)
        for v in prices.values():
            assert isinstance(v, str), f"Expected str price value, got {type(v)}"

    def test_portfolio_is_dict(self):
        """portfolio field is a dict."""
        session_id = str(uuid4())
        mock_engine = MagicMock()
        mock_engine.step_batch_fast = AsyncMock(
            return_value=_make_batch_fast_engine_result()
        )

        with _build_client(mock_engine=mock_engine) as client:
            resp = client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": 5},
            )

        assert resp.status_code == 200
        assert isinstance(resp.json()["portfolio"], dict)

    def test_engine_called_with_include_intermediate_trades_false_by_default(self):
        """include_intermediate_trades defaults to False and is forwarded to engine."""
        session_id = str(uuid4())
        mock_engine = MagicMock()
        mock_engine.step_batch_fast = AsyncMock(
            return_value=_make_batch_fast_engine_result()
        )

        with _build_client(mock_engine=mock_engine) as client:
            client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": 10},
            )

        mock_engine.step_batch_fast.assert_awaited_once()
        _, kwargs = mock_engine.step_batch_fast.call_args
        assert kwargs.get("include_intermediate_trades") is False

    def test_engine_called_with_include_intermediate_trades_true_when_set(self):
        """include_intermediate_trades=True is forwarded to engine."""
        session_id = str(uuid4())
        mock_engine = MagicMock()
        mock_engine.step_batch_fast = AsyncMock(
            return_value=_make_batch_fast_engine_result()
        )

        with _build_client(mock_engine=mock_engine) as client:
            client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": 10, "include_intermediate_trades": True},
            )

        mock_engine.step_batch_fast.assert_awaited_once()
        _, kwargs = mock_engine.step_batch_fast.call_args
        assert kwargs.get("include_intermediate_trades") is True


# ---------------------------------------------------------------------------
# Tests: session completion
# ---------------------------------------------------------------------------


class TestBatchStepFastCompletion:
    """Behaviour when the engine reports the session has fully completed."""

    def test_is_complete_true_returned_when_engine_completes(self):
        """is_complete=True in response when engine exhausted all steps."""
        session_id = str(uuid4())
        mock_engine = MagicMock()
        mock_engine.step_batch_fast = AsyncMock(
            return_value=_make_batch_fast_engine_result(
                steps_executed=10, is_complete=True, step=100, total_steps=100
            )
        )

        with _build_client(mock_engine=mock_engine) as client:
            resp = client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": 10000},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_complete"] is True
        assert data["remaining_steps"] == 0

    def test_steps_executed_reflects_actual_steps_when_session_ends_early(self):
        """steps_executed can be less than requested when session completes mid-batch."""
        session_id = str(uuid4())
        mock_engine = MagicMock()
        # Engine ran only 3 steps before completing
        mock_engine.step_batch_fast = AsyncMock(
            return_value=_make_batch_fast_engine_result(
                steps_executed=3, is_complete=True, step=100, total_steps=100
            )
        )

        with _build_client(mock_engine=mock_engine) as client:
            resp = client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": 1000},
            )

        assert resp.status_code == 200
        assert resp.json()["steps_executed"] == 3


# ---------------------------------------------------------------------------
# Tests: error cases
# ---------------------------------------------------------------------------


class TestBatchStepFastErrors:
    """Error handling: invalid session, validation failures, auth."""

    def test_returns_404_for_inactive_session(self):
        """BacktestNotFoundError from engine maps to 404."""
        from src.utils.exceptions import BacktestNotFoundError

        session_id = str(uuid4())
        mock_engine = MagicMock()
        mock_engine.step_batch_fast = AsyncMock(
            side_effect=BacktestNotFoundError(
                f"Backtest session '{session_id}' is not active."
            )
        )
        mock_engine._get_active = MagicMock(
            side_effect=BacktestNotFoundError(
                f"Backtest session '{session_id}' is not active."
            )
        )

        # Also need to mock _raise_if_terminal to avoid a second DB query
        with patch(
            "src.api.routes.backtest._raise_if_terminal",
            new_callable=AsyncMock,
        ):
            with _build_client(mock_engine=mock_engine) as client:
                resp = client.post(
                    f"/api/v1/backtest/{session_id}/step/batch/fast",
                    json={"steps": 5},
                )

        assert resp.status_code == 404

    def test_returns_422_for_steps_zero(self):
        """steps=0 fails Pydantic validation (ge=1) and returns 422."""
        session_id = str(uuid4())
        mock_engine = MagicMock()

        with _build_client(mock_engine=mock_engine) as client:
            resp = client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": 0},
            )

        assert resp.status_code == 422

    def test_returns_422_for_negative_steps(self):
        """Negative steps fail Pydantic validation and return 422."""
        session_id = str(uuid4())
        mock_engine = MagicMock()

        with _build_client(mock_engine=mock_engine) as client:
            resp = client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": -10},
            )

        assert resp.status_code == 422

    def test_returns_422_when_steps_missing(self):
        """Missing required 'steps' field returns 422."""
        session_id = str(uuid4())
        mock_engine = MagicMock()

        with _build_client(mock_engine=mock_engine) as client:
            resp = client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={},
            )

        assert resp.status_code == 422

    def test_returns_422_for_steps_exceeding_max(self):
        """steps > 100000 (schema max) returns 422."""
        session_id = str(uuid4())
        mock_engine = MagicMock()

        with _build_client(mock_engine=mock_engine) as client:
            resp = client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": 100001},
            )

        assert resp.status_code == 422

    def test_returns_409_for_already_completed_session(self):
        """BacktestInvalidStateError from engine maps to 409."""
        from src.utils.exceptions import BacktestInvalidStateError

        session_id = str(uuid4())
        mock_engine = MagicMock()
        mock_engine.step_batch_fast = AsyncMock(
            side_effect=BacktestInvalidStateError(
                "Backtest has already completed all steps.",
                current_status="complete",
            )
        )

        with _build_client(mock_engine=mock_engine) as client:
            resp = client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": 5},
            )

        # BacktestInvalidStateError -> HTTP 409 Conflict
        assert resp.status_code == 409

    def test_requires_authentication(self):
        """No auth header returns 401."""
        session_id = str(uuid4())

        with _build_client_no_auth() as client:
            resp = client.post(
                f"/api/v1/backtest/{session_id}/step/batch/fast",
                json={"steps": 5},
            )

        assert resp.status_code == 401

    def test_error_response_has_error_envelope(self):
        """Error responses follow the standard {'error': {'code': ..., 'message': ...}} shape."""
        from src.utils.exceptions import BacktestNotFoundError

        session_id = str(uuid4())
        mock_engine = MagicMock()
        mock_engine.step_batch_fast = AsyncMock(
            side_effect=BacktestNotFoundError(
                f"Backtest session '{session_id}' is not active."
            )
        )

        with patch(
            "src.api.routes.backtest._raise_if_terminal",
            new_callable=AsyncMock,
        ):
            with _build_client(mock_engine=mock_engine) as client:
                resp = client.post(
                    f"/api/v1/backtest/{session_id}/step/batch/fast",
                    json={"steps": 5},
                )

        assert resp.status_code == 404
        body = resp.json()
        assert "error" in body
        assert "code" in body["error"]
        assert "message" in body["error"]

    def test_invalid_uuid_session_id_returns_422(self):
        """A non-UUID session_id path parameter must return 422 (FastAPI path validation).

        Prior to the session_id: UUID fix, the route used session_id: str which
        allowed any string through and would raise a 500 deep in the engine.
        Now the UUID type annotation causes FastAPI to validate the path param
        before the handler runs.
        """
        mock_engine = MagicMock()

        with _build_client(mock_engine=mock_engine) as client:
            resp = client.post(
                "/api/v1/backtest/not-a-valid-uuid/step/batch/fast",
                json={"steps": 5},
            )

        # FastAPI raises 422 for path params that fail type coercion
        assert resp.status_code == 422

    def test_valid_uuid_session_id_passes_path_validation(self):
        """A properly formatted UUID is accepted by path validation and reaches the engine."""
        from src.utils.exceptions import BacktestNotFoundError

        session_id = str(uuid4())
        mock_engine = MagicMock()
        mock_engine.step_batch_fast = AsyncMock(
            side_effect=BacktestNotFoundError(f"Session {session_id} not found.")
        )

        with patch(
            "src.api.routes.backtest._raise_if_terminal",
            new_callable=AsyncMock,
        ):
            with _build_client(mock_engine=mock_engine) as client:
                resp = client.post(
                    f"/api/v1/backtest/{session_id}/step/batch/fast",
                    json={"steps": 3},
                )

        # 404 means it passed UUID validation and reached the engine handler
        assert resp.status_code == 404
