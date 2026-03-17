"""Integration tests for analytics REST endpoints.

Covers the following endpoints (Section 15.5):

- ``GET /api/v1/analytics/performance``       — trading performance metrics
- ``GET /api/v1/analytics/portfolio/history`` — historical portfolio equity snapshots
- ``GET /api/v1/analytics/leaderboard``       — cross-account performance rankings

All external I/O (DB session, Redis, services) is mocked so tests run without
real infrastructure.  FastAPI's ``app.dependency_overrides`` is used to replace
the full dependency chain so no real DB or Redis connections are made.

Run with::

    pytest tests/integration/test_analytics_endpoints.py -v
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
# Test settings — no real infra
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


def _make_account(account_id=None, display_name="TestBot", status="active"):
    """Build a mock :class:`~src.database.models.Account` ORM object."""
    account = MagicMock(spec=Account)
    account.id = account_id or uuid4()
    account.api_key = "ak_live_testkey"
    account.api_secret_hash = "$2b$12$fakehash"
    account.display_name = display_name
    account.status = status
    account.starting_balance = Decimal("10000.00")
    account.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    return account


def _make_metrics(period="all", total_trades=10):
    """Build a mock Metrics object matching PerformanceMetrics.calculate() return."""
    m = MagicMock()
    m.period = period
    m.sharpe_ratio = 1.85
    m.sortino_ratio = 2.31
    m.max_drawdown = 8.5
    m.max_drawdown_duration = 3
    m.win_rate = 65.71
    m.profit_factor = 2.10
    m.avg_win = Decimal("156.30")
    m.avg_loss = Decimal("-74.50")
    m.total_trades = total_trades
    m.avg_trades_per_day = 1.17
    m.best_trade = Decimal("523.00")
    m.worst_trade = Decimal("-210.00")
    m.current_streak = 3
    return m


def _make_snapshot(equity="10500"):
    """Build a mock Snapshot object matching SnapshotService.get_snapshot_history() items."""
    s = MagicMock()
    s.created_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    s.total_equity = Decimal(equity)
    s.unrealized_pnl = Decimal("100")
    s.realized_pnl = Decimal("400")
    return s


# ---------------------------------------------------------------------------
# App + client factory
# ---------------------------------------------------------------------------


def _build_client(mock_account=None, metrics_svc=None, snapshot_svc=None):
    """Create a ``TestClient`` with the full middleware stack and mocked infra.

    The ``AuthMiddleware`` runs as Starlette middleware *before* FastAPI DI, so
    we patch ``_authenticate_request`` at the module level to inject the mock
    account into ``request.state``.  When ``mock_account`` is ``None``, the
    patch is not applied, causing the middleware to return 401.

    Args:
        mock_account: Optional pre-configured mock account for auth. If ``None``,
            the ``_authenticate_request`` patch is NOT applied, causing 401.
        metrics_svc: Optional ``AsyncMock`` for ``PerformanceMetrics`` service.
        snapshot_svc: Optional ``AsyncMock`` for ``SnapshotService``.

    Returns:
        A tuple of ``(TestClient, cleanup_fn)``.  The caller MUST invoke
        ``cleanup_fn()`` after the test to stop the auth patcher and avoid
        leaking mock state between tests.
    """
    from src.api.middleware.auth import get_current_account, get_current_agent
    from src.dependencies import (
        get_db_session,
        get_performance_metrics,
        get_redis,
        get_settings,
        get_snapshot_service,
    )

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock(return_value=True)
    mock_redis.ttl = AsyncMock(return_value=60)
    mock_redis.hget = AsyncMock(return_value=None)
    mock_redis.hset = AsyncMock(return_value=1)

    # Pipeline mock — used by RateLimitMiddleware
    mock_pipe = AsyncMock()
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)
    mock_pipe.incr = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 60])
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.flush = AsyncMock()

    # Mock db.execute for leaderboard (returns empty result by default)
    mock_result = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all = MagicMock(return_value=[])
    mock_result.scalars = MagicMock(return_value=mock_scalars)
    mock_session.execute = AsyncMock(return_value=mock_result)

    # When mock_account is provided, patch _authenticate_request so the
    # AuthMiddleware sets request.state without hitting a real database.
    # This patch must remain active for the lifetime of the TestClient.
    auth_patcher = None
    if mock_account is not None:
        async def _fake_authenticate(_request):
            return mock_account, None

        auth_patcher = patch(
            "src.api.middleware.auth._authenticate_request",
            side_effect=_fake_authenticate,
        )
        auth_patcher.start()

    def _cleanup():
        if auth_patcher is not None:
            auth_patcher.stop()

    with (
        patch("src.database.session.init_db", new_callable=AsyncMock),
        patch("src.database.session.close_db", new_callable=AsyncMock),
        patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock, return_value=mock_redis),
        patch("src.api.websocket.handlers.start_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.handlers.stop_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.manager.ConnectionManager.disconnect_all", new_callable=AsyncMock),
    ):
        from src.main import create_app

        app = create_app()

        # --- dependency overrides ---
        app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS

        async def _override_db():
            yield mock_session

        app.dependency_overrides[get_db_session] = _override_db

        async def _override_redis():
            yield mock_redis

        app.dependency_overrides[get_redis] = _override_redis

        if mock_account is not None:
            app.dependency_overrides[get_current_account] = lambda: mock_account

        # No agent context for analytics tests
        app.dependency_overrides[get_current_agent] = lambda: None

        if metrics_svc is not None:
            async def _override_metrics():
                return metrics_svc

            app.dependency_overrides[get_performance_metrics] = _override_metrics

        if snapshot_svc is not None:
            async def _override_snapshot():
                return snapshot_svc

            app.dependency_overrides[get_snapshot_service] = _override_snapshot

        return TestClient(app, raise_server_exceptions=False), _cleanup


# ===========================================================================
# GET /api/v1/analytics/performance
# ===========================================================================


class TestPerformance:
    """Tests for GET /api/v1/analytics/performance."""

    def test_get_performance_all_time(self) -> None:
        """Default period (all) returns full performance metrics with HTTP 200."""
        account = _make_account()
        metrics_svc = AsyncMock()
        metrics_svc.calculate = AsyncMock(return_value=_make_metrics(period="all"))

        client, cleanup = _build_client(mock_account=account, metrics_svc=metrics_svc)
        try:
            resp = client.get("/api/v1/analytics/performance")

            assert resp.status_code == 200
            body = resp.json()
            assert body["period"] == "all"
            assert body["total_trades"] == 10
            assert Decimal(body["sharpe_ratio"]) == Decimal("1.85")
            assert Decimal(body["sortino_ratio"]) == Decimal("2.31")
            assert Decimal(body["max_drawdown_pct"]) == Decimal("8.5")
            assert body["max_drawdown_duration_days"] == 3
            assert Decimal(body["win_rate"]) == Decimal("65.71")
            assert Decimal(body["profit_factor"]) == Decimal("2.1")
            assert Decimal(body["avg_win"]) == Decimal("156.30")
            assert Decimal(body["avg_loss"]) == Decimal("-74.50")
            assert Decimal(body["avg_trades_per_day"]) == Decimal("1.17")
            assert Decimal(body["best_trade"]) == Decimal("523.00")
            assert Decimal(body["worst_trade"]) == Decimal("-210.00")
            assert body["current_streak"] == 3
        finally:
            cleanup()

    def test_get_performance_by_period(self) -> None:
        """Passing ?period=7d forwards the period to the metrics service."""
        account = _make_account()
        metrics_svc = AsyncMock()
        metrics_svc.calculate = AsyncMock(return_value=_make_metrics(period="7d"))

        client, cleanup = _build_client(mock_account=account, metrics_svc=metrics_svc)
        try:
            resp = client.get("/api/v1/analytics/performance?period=7d")

            assert resp.status_code == 200
            body = resp.json()
            assert body["period"] == "7d"

            # Verify the service was called with the correct period
            metrics_svc.calculate.assert_called_once_with(
                account.id, period="7d", agent_id=None,
            )
        finally:
            cleanup()

    def test_get_performance_no_trades(self) -> None:
        """An account with zero trades returns zeroed metrics, not an error."""
        account = _make_account()
        zero_metrics = _make_metrics(period="all", total_trades=0)
        zero_metrics.sharpe_ratio = 0.0
        zero_metrics.sortino_ratio = 0.0
        zero_metrics.max_drawdown = 0.0
        zero_metrics.max_drawdown_duration = 0
        zero_metrics.win_rate = 0.0
        zero_metrics.profit_factor = 0.0
        zero_metrics.avg_win = Decimal("0")
        zero_metrics.avg_loss = Decimal("0")
        zero_metrics.avg_trades_per_day = 0.0
        zero_metrics.best_trade = Decimal("0")
        zero_metrics.worst_trade = Decimal("0")
        zero_metrics.current_streak = 0

        metrics_svc = AsyncMock()
        metrics_svc.calculate = AsyncMock(return_value=zero_metrics)

        client, cleanup = _build_client(mock_account=account, metrics_svc=metrics_svc)
        try:
            resp = client.get("/api/v1/analytics/performance")

            assert resp.status_code == 200
            body = resp.json()
            assert body["total_trades"] == 0
            assert Decimal(body["sharpe_ratio"]) == Decimal("0")
            assert Decimal(body["win_rate"]) == Decimal("0")
        finally:
            cleanup()

    def test_get_performance_requires_auth(self) -> None:
        """Accessing performance without authentication returns HTTP 401."""
        # No mock_account -> _authenticate_request is NOT patched -> middleware returns 401
        client, cleanup = _build_client(mock_account=None)
        try:
            resp = client.get("/api/v1/analytics/performance")
            assert resp.status_code == 401
        finally:
            cleanup()


# ===========================================================================
# GET /api/v1/analytics/portfolio/history
# ===========================================================================


class TestPortfolioHistory:
    """Tests for GET /api/v1/analytics/portfolio/history."""

    def test_get_portfolio_history(self) -> None:
        """Default params return a time series of equity snapshots with HTTP 200."""
        account = _make_account()
        snapshot_svc = AsyncMock()
        snapshots = [_make_snapshot("10500"), _make_snapshot("10800")]
        snapshot_svc.get_snapshot_history = AsyncMock(return_value=snapshots)

        client, cleanup = _build_client(mock_account=account, snapshot_svc=snapshot_svc)
        try:
            resp = client.get("/api/v1/analytics/portfolio/history")

            assert resp.status_code == 200
            body = resp.json()
            assert body["account_id"] == str(account.id)
            assert body["interval"] == "1h"
            assert len(body["snapshots"]) == 2
            # Verify structure of each snapshot item
            snap = body["snapshots"][0]
            assert "time" in snap
            assert "total_equity" in snap
            assert "unrealized_pnl" in snap
            assert "realized_pnl" in snap
        finally:
            cleanup()

    def test_get_portfolio_history_intervals(self) -> None:
        """Passing ?interval=1d maps to 'daily' snapshot_type in the service call."""
        account = _make_account()
        snapshot_svc = AsyncMock()
        snapshot_svc.get_snapshot_history = AsyncMock(return_value=[_make_snapshot()])

        client, cleanup = _build_client(mock_account=account, snapshot_svc=snapshot_svc)
        try:
            resp = client.get("/api/v1/analytics/portfolio/history?interval=1d")

            assert resp.status_code == 200
            body = resp.json()
            assert body["interval"] == "1d"

            # Verify the service was called with 'daily' snapshot_type
            snapshot_svc.get_snapshot_history.assert_called_once_with(
                account.id,
                snapshot_type="daily",
                limit=100,
                agent_id=None,
            )
        finally:
            cleanup()


# ===========================================================================
# GET /api/v1/analytics/leaderboard
# ===========================================================================


class TestLeaderboard:
    """Tests for GET /api/v1/analytics/leaderboard."""

    def test_get_leaderboard(self) -> None:
        """Leaderboard returns HTTP 200 with empty rankings (mock DB has no accounts)."""
        account = _make_account(display_name="AuthUser")

        client, cleanup = _build_client(mock_account=account)
        try:
            # The leaderboard imports PerformanceMetrics lazily inside the handler,
            # so we patch it at its source module.
            with patch("src.portfolio.metrics.PerformanceMetrics") as mock_perf_cls:
                mock_perf = AsyncMock()
                mock_perf.calculate = AsyncMock(return_value=_make_metrics(period="30d", total_trades=5))
                mock_perf_cls.return_value = mock_perf

                resp = client.get("/api/v1/analytics/leaderboard")

            assert resp.status_code == 200
            body = resp.json()
            assert body["period"] == "30d"
            assert "rankings" in body
            # Mock session.execute returns empty list by default, so rankings is empty
            assert isinstance(body["rankings"], list)
        finally:
            cleanup()

    def test_get_leaderboard_by_period(self) -> None:
        """Passing ?period=30d is accepted and echoed in the response."""
        account = _make_account()

        client, cleanup = _build_client(mock_account=account)
        try:
            with patch("src.portfolio.metrics.PerformanceMetrics") as mock_perf_cls:
                mock_perf = AsyncMock()
                mock_perf.calculate = AsyncMock(return_value=_make_metrics(period="30d", total_trades=0))
                mock_perf_cls.return_value = mock_perf

                resp = client.get("/api/v1/analytics/leaderboard?period=30d")

            assert resp.status_code == 200
            body = resp.json()
            assert body["period"] == "30d"
            assert isinstance(body["rankings"], list)
        finally:
            cleanup()
