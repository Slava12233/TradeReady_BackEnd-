"""Integration tests for account REST endpoints.

Covers every endpoint defined in ``src/api/routes/account.py``:

- ``GET  /api/v1/account/info``       — account details, session, risk profile
- ``GET  /api/v1/account/balance``    — per-asset balances + total equity
- ``GET  /api/v1/account/positions``  — open positions with unrealised PnL
- ``GET  /api/v1/account/portfolio``  — full portfolio snapshot
- ``GET  /api/v1/account/pnl``        — PnL breakdown with period
- ``PUT  /api/v1/account/risk-profile`` — update risk limits
- ``POST /api/v1/account/reset``      — reset account (destructive)

All external I/O (DB session, Redis, services) is mocked so tests run without
real infrastructure.  ``app.dependency_overrides`` replaces the full DI chain.

The ``AuthMiddleware`` is bypassed by issuing a valid JWT and patching the
middleware's internal DB lookups.

Run with::

    pytest tests/integration/test_account_endpoints.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from src.accounts.auth import create_jwt
from src.config import Settings
from src.database.models import Account, TradingSession
import src.database.session  # noqa: F401 — ensures submodule is importable by patch()

pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Test settings — no real infra
# ---------------------------------------------------------------------------

_TEST_SETTINGS = Settings(
    jwt_secret="test_secret_that_is_at_least_32_characters_long_for_hs256",
    database_url="postgresql+asyncpg://test:test@localhost:5432/test",
    redis_url="redis://localhost:6379/15",
    jwt_expiry_hours=1,
)


# ---------------------------------------------------------------------------
# Shared helpers — data builders
# ---------------------------------------------------------------------------


def _make_account(
    account_id=None,
    display_name="TestBot",
    status="active",
):
    """Build a mock :class:`~src.database.models.Account` object."""
    account = MagicMock(spec=Account)
    account.id = account_id or uuid4()
    account.display_name = display_name
    account.status = status
    account.starting_balance = Decimal("10000.00")
    account.risk_profile = {
        "max_position_size_pct": 25,
        "daily_loss_limit_pct": 20,
        "max_open_orders": 50,
    }
    account.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    return account


def _make_balance(asset="USDT", available="10000", locked="0"):
    """Build a mock balance row."""
    b = MagicMock()
    b.asset = asset
    b.available = Decimal(available)
    b.locked = Decimal(locked)
    return b


def _make_portfolio_summary():
    """Build a mock :class:`PortfolioSummary` for tracker responses."""
    s = MagicMock()
    s.total_equity = Decimal("12458.30")
    s.available_cash = Decimal("6741.50")
    s.locked_cash = Decimal("1500")
    s.total_position_value = Decimal("4216.80")
    s.unrealized_pnl = Decimal("660.65")
    s.realized_pnl = Decimal("1241.30")
    s.total_pnl = Decimal("1901.95")
    s.roi_pct = Decimal("24.58")
    s.starting_balance = Decimal("10000")
    s.positions = []
    return s


def _make_pnl():
    """Build a mock PnL breakdown for tracker responses."""
    p = MagicMock()
    p.realized_pnl = Decimal("1241.30")
    p.unrealized_pnl = Decimal("660.65")
    p.total_pnl = Decimal("1901.95")
    return p


def _make_session(account_id):
    """Build a mock :class:`~src.database.models.TradingSession`."""
    s = MagicMock(spec=TradingSession)
    s.id = uuid4()
    s.account_id = account_id
    s.status = "active"
    s.started_at = datetime(2026, 1, 1, tzinfo=UTC)
    s.starting_balance = Decimal("10000")
    return s


# ---------------------------------------------------------------------------
# Auth helpers — account endpoints sit behind the auth middleware
# ---------------------------------------------------------------------------


def _make_auth_context(
    account=None,
):
    """Return ``(headers, mock_repo, mock_session_factory)`` for auth middleware patching.

    Creates a valid short-lived JWT signed with ``_TEST_SETTINGS.jwt_secret`` and
    builds the mock infrastructure that ``AuthMiddleware`` uses to resolve the
    account from the database.

    Args:
        account: Optional pre-built account mock.  If ``None``, one is created.

    Returns:
        A tuple of (HTTP headers dict, mock AccountRepository, mock session factory).
    """
    if account is None:
        account = _make_account()

    token = create_jwt(
        account_id=account.id,
        jwt_secret=_TEST_SETTINGS.jwt_secret,
        expiry_hours=1,
    )

    mock_repo = AsyncMock()
    mock_repo.get_by_id = AsyncMock(return_value=account)

    mock_session = AsyncMock()
    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session_factory = MagicMock(return_value=mock_session_ctx)

    return {"Authorization": f"Bearer {token}"}, mock_repo, mock_session_factory


def _authed_request(
    client,
    method,
    url,
    account=None,
    **kwargs,
):
    """Issue an authenticated HTTP request through the auth middleware.

    Patches ``AuthMiddleware``'s internal DB lookups so the JWT is accepted
    without a real database connection.

    Args:
        client:  The ``TestClient`` instance.
        method:  HTTP method (``"get"``, ``"post"``, ``"put"``, ``"delete"``).
        url:     Request path.
        account: Optional pre-built account mock for auth context.
        **kwargs: Extra kwargs forwarded to the client method (e.g. ``json``, ``headers``).

    Returns:
        The ``Response`` object.
    """
    headers, mock_repo, mock_session_factory = _make_auth_context(account)
    merged_headers = {**headers, **kwargs.pop("headers", {})}
    with (
        patch("src.api.middleware.auth.logger"),
        patch("src.api.middleware.auth.get_settings", return_value=_TEST_SETTINGS),
        patch("src.api.middleware.auth.AccountRepository", return_value=mock_repo),
        patch("src.database.session.get_session_factory", return_value=mock_session_factory),
    ):
        return getattr(client, method)(url, headers=merged_headers, **kwargs)


# ---------------------------------------------------------------------------
# App + client factory
# ---------------------------------------------------------------------------


def _build_client(
    mock_account=None,
    balance_manager=None,
    tracker=None,
    account_service=None,
    trade_repo=None,
    account_repo=None,
    agent_repo=None,
    mock_db_session=None,
) -> TestClient:
    """Create a ``TestClient`` with mocked account service dependencies.

    Uses ``app.dependency_overrides`` so no real database, Redis, or external
    services are required.

    Args:
        mock_account:    Pre-built mock Account (used for auth context, not DI override).
        balance_manager: Pre-configured ``AsyncMock`` for ``BalanceManager``.
        tracker:         Pre-configured ``AsyncMock`` for ``PortfolioTracker``.
        account_service: Pre-configured ``AsyncMock`` for ``AccountService``.
        trade_repo:      Pre-configured ``AsyncMock`` for ``TradeRepository``.
        account_repo:    Pre-configured ``AsyncMock`` for ``AccountRepository``.
        agent_repo:      Pre-configured ``AsyncMock`` for ``AgentRepository``.
        mock_db_session: Pre-configured ``AsyncMock`` for the DB session.

    Returns:
        A ``TestClient`` wrapping the fully configured application.
    """
    from src.api.middleware.auth import get_current_agent
    from src.dependencies import (
        get_account_repo,
        get_account_service,
        get_agent_repo,
        get_balance_manager,
        get_db_session,
        get_portfolio_tracker,
        get_redis,
        get_settings,
        get_trade_repo,
    )

    # Standard mock Redis
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

    # Standard mock DB session
    if mock_db_session is None:
        mock_db_session = AsyncMock()
        mock_db_session.commit = AsyncMock()
        mock_db_session.rollback = AsyncMock()

    with (
        patch("src.database.session.init_db", new_callable=AsyncMock),
        patch("src.database.session.close_db", new_callable=AsyncMock),
        patch(
            "src.cache.redis_client.get_redis_client",
            new_callable=AsyncMock,
            return_value=mock_redis,
        ),
        patch("src.api.websocket.handlers.start_redis_bridge", new_callable=AsyncMock),
        patch("src.api.websocket.handlers.stop_redis_bridge", new_callable=AsyncMock),
        patch(
            "src.api.websocket.manager.ConnectionManager.disconnect_all",
            new_callable=AsyncMock,
        ),
    ):
        from src.main import create_app

        app = create_app()

        app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS

        _mock_db_session = mock_db_session

        async def _override_db():
            yield _mock_db_session

        app.dependency_overrides[get_db_session] = _override_db

        async def _override_redis():
            yield mock_redis

        app.dependency_overrides[get_redis] = _override_redis

        # Agent context override — no agent for these tests
        app.dependency_overrides[get_current_agent] = lambda: None

        # Service overrides
        if balance_manager is not None:
            _bm = balance_manager

            async def _override_bm():
                return _bm

            app.dependency_overrides[get_balance_manager] = _override_bm

        if tracker is not None:
            _tracker = tracker

            async def _override_tracker():
                return _tracker

            app.dependency_overrides[get_portfolio_tracker] = _override_tracker

        if account_service is not None:
            _as = account_service

            async def _override_as():
                return _as

            app.dependency_overrides[get_account_service] = _override_as

        if trade_repo is not None:
            _tr = trade_repo

            async def _override_tr():
                return _tr

            app.dependency_overrides[get_trade_repo] = _override_tr

        if account_repo is not None:
            _ar = account_repo

            async def _override_ar():
                return _ar

            app.dependency_overrides[get_account_repo] = _override_ar

        if agent_repo is not None:
            _agr = agent_repo

            async def _override_agr():
                return _agr

            app.dependency_overrides[get_agent_repo] = _override_agr

        return TestClient(app, raise_server_exceptions=False)


# ===========================================================================
# GET /api/v1/account/info
# ===========================================================================


class TestAccountInfo:
    """Tests for ``GET /api/v1/account/info``."""

    def test_get_account_info(self) -> None:
        """GET /account/info returns 200 with account details, session, and risk profile."""
        account = _make_account()
        mock_trading_session = _make_session(account.id)

        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        # Mock the db.execute() call inside _get_active_session
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_trading_session)
        mock_db.execute = AsyncMock(return_value=mock_result)

        client = _build_client(mock_account=account, mock_db_session=mock_db)
        resp = _authed_request(client, "get", "/api/v1/account/info", account=account)

        assert resp.status_code == 200
        data = resp.json()
        assert data["account_id"] == str(account.id)
        assert data["display_name"] == "TestBot"
        assert data["status"] == "active"
        assert data["starting_balance"] == "10000.00"
        assert "current_session" in data
        assert data["current_session"]["session_id"] == str(mock_trading_session.id)
        assert "risk_profile" in data
        assert data["risk_profile"]["max_position_size_pct"] == 25
        assert data["risk_profile"]["daily_loss_limit_pct"] == 20
        assert data["risk_profile"]["max_open_orders"] == 50

    def test_get_account_info_requires_auth(self) -> None:
        """GET /account/info without auth returns 401."""
        client = _build_client()
        resp = client.get("/api/v1/account/info")

        assert resp.status_code == 401


# ===========================================================================
# GET /api/v1/account/balance
# ===========================================================================


class TestBalance:
    """Tests for ``GET /api/v1/account/balance``."""

    def test_get_balance(self) -> None:
        """GET /account/balance returns 200 with per-asset balances and total equity."""
        account = _make_account()

        mock_bm = AsyncMock()
        mock_bm.get_all_balances = AsyncMock(
            return_value=[
                _make_balance("USDT", "6741.50", "1500"),
                _make_balance("BTC", "0.50000000", "0"),
            ],
        )

        mock_tracker = AsyncMock()
        mock_tracker.get_portfolio = AsyncMock(return_value=_make_portfolio_summary())

        client = _build_client(
            mock_account=account,
            balance_manager=mock_bm,
            tracker=mock_tracker,
        )
        resp = _authed_request(client, "get", "/api/v1/account/balance", account=account)

        assert resp.status_code == 200
        data = resp.json()
        assert "balances" in data
        assert len(data["balances"]) >= 2
        assert data["total_equity_usdt"] == "12458.30"

        usdt_balance = next(b for b in data["balances"] if b["asset"] == "USDT")
        assert usdt_balance["available"] == "6741.50"
        assert usdt_balance["locked"] == "1500"

    def test_get_balance_requires_auth(self) -> None:
        """GET /account/balance without auth returns 401."""
        client = _build_client()
        resp = client.get("/api/v1/account/balance")

        assert resp.status_code == 401


# ===========================================================================
# GET /api/v1/account/positions
# ===========================================================================


class TestPositions:
    """Tests for ``GET /api/v1/account/positions``."""

    def test_get_positions(self) -> None:
        """GET /account/positions returns 200 with position list."""
        account = _make_account()

        mock_position = MagicMock()
        mock_position.symbol = "BTCUSDT"
        mock_position.asset = "BTC"
        mock_position.quantity = Decimal("0.50000000")
        mock_position.avg_entry_price = Decimal("63200.00")
        mock_position.current_price = Decimal("64521.30")
        mock_position.market_value = Decimal("32260.65")
        mock_position.unrealized_pnl = Decimal("660.65")
        mock_position.unrealized_pnl_pct = Decimal("2.09")

        mock_tracker = AsyncMock()
        mock_tracker.get_positions = AsyncMock(return_value=[mock_position])

        client = _build_client(mock_account=account, tracker=mock_tracker)
        resp = _authed_request(client, "get", "/api/v1/account/positions", account=account)

        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data
        assert len(data["positions"]) == 1
        assert data["positions"][0]["symbol"] == "BTCUSDT"
        assert data["positions"][0]["unrealized_pnl"] == "660.65"
        assert data["total_unrealized_pnl"] == "660.65"

    def test_get_positions_empty(self) -> None:
        """GET /account/positions with no open positions returns empty list, not error."""
        account = _make_account()

        mock_tracker = AsyncMock()
        mock_tracker.get_positions = AsyncMock(return_value=[])

        client = _build_client(mock_account=account, tracker=mock_tracker)
        resp = _authed_request(client, "get", "/api/v1/account/positions", account=account)

        assert resp.status_code == 200
        data = resp.json()
        assert data["positions"] == []
        assert data["total_unrealized_pnl"] == "0"


# ===========================================================================
# GET /api/v1/account/portfolio
# ===========================================================================


class TestPortfolio:
    """Tests for ``GET /api/v1/account/portfolio``."""

    def test_get_portfolio(self) -> None:
        """GET /account/portfolio returns 200 with full portfolio snapshot."""
        account = _make_account()

        mock_tracker = AsyncMock()
        mock_tracker.get_portfolio = AsyncMock(return_value=_make_portfolio_summary())

        client = _build_client(mock_account=account, tracker=mock_tracker)
        resp = _authed_request(client, "get", "/api/v1/account/portfolio", account=account)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_equity"] == "12458.30"
        assert data["available_cash"] == "6741.50"
        assert data["locked_cash"] == "1500"
        assert data["total_position_value"] == "4216.80"
        assert data["unrealized_pnl"] == "660.65"
        assert data["realized_pnl"] == "1241.30"
        assert data["total_pnl"] == "1901.95"
        assert data["roi_pct"] == "24.58"
        assert data["starting_balance"] == "10000"
        assert "positions" in data
        assert "timestamp" in data


# ===========================================================================
# GET /api/v1/account/pnl
# ===========================================================================


class TestPnL:
    """Tests for ``GET /api/v1/account/pnl``."""

    def test_get_pnl(self) -> None:
        """GET /account/pnl returns 200 with PnL breakdown aggregated in SQL."""
        account = _make_account()

        mock_tracker = AsyncMock()
        mock_tracker.get_pnl = AsyncMock(return_value=_make_pnl())

        mock_trade_repo = AsyncMock()
        # get_pnl_stats_by_period returns (fees_paid, wins, losses, breakeven)
        mock_trade_repo.get_pnl_stats_by_period = AsyncMock(return_value=(Decimal("18.80"), 1, 1, 0))

        client = _build_client(
            mock_account=account,
            tracker=mock_tracker,
            trade_repo=mock_trade_repo,
        )
        resp = _authed_request(client, "get", "/api/v1/account/pnl", account=account)

        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "all"
        assert data["realized_pnl"] == "1241.30"
        assert data["unrealized_pnl"] == "660.65"
        assert data["total_pnl"] == "1901.95"
        assert data["winning_trades"] == 1
        assert data["losing_trades"] == 1
        assert Decimal(data["fees_paid"]) == Decimal("18.80")

        # Verify the repo method was called (with no since= for "all" period)
        mock_trade_repo.get_pnl_stats_by_period.assert_called_once()
        call_kwargs = mock_trade_repo.get_pnl_stats_by_period.call_args
        assert call_kwargs.kwargs.get("since") is None

    def test_get_pnl_by_period_uses_time_based_filter(self) -> None:
        """GET /account/pnl?period=7d passes a time-based ``since`` cutoff, not a row limit."""
        account = _make_account()

        mock_tracker = AsyncMock()
        mock_tracker.get_pnl = AsyncMock(return_value=_make_pnl())

        mock_trade_repo = AsyncMock()
        mock_trade_repo.get_pnl_stats_by_period = AsyncMock(return_value=(Decimal("0"), 0, 0, 0))

        client = _build_client(
            mock_account=account,
            tracker=mock_tracker,
            trade_repo=mock_trade_repo,
        )
        resp = _authed_request(client, "get", "/api/v1/account/pnl?period=7d", account=account)

        assert resp.status_code == 200
        data = resp.json()
        assert data["period"] == "7d"
        assert data["winning_trades"] == 0
        assert data["losing_trades"] == 0
        assert data["win_rate"] == "0"

        # Verify get_pnl_stats_by_period was called with a non-None ``since``
        # datetime (time-based filter), not list_by_account with a row limit.
        mock_trade_repo.get_pnl_stats_by_period.assert_called_once()
        call_kwargs = mock_trade_repo.get_pnl_stats_by_period.call_args
        since = call_kwargs.kwargs.get("since")
        assert since is not None, "Expected a time-based 'since' cutoff for period='7d'"
        assert isinstance(since, datetime)

    def test_get_pnl_period_all_sends_no_since(self) -> None:
        """GET /account/pnl?period=all passes since=None (no time lower bound)."""
        account = _make_account()

        mock_tracker = AsyncMock()
        mock_tracker.get_pnl = AsyncMock(return_value=_make_pnl())

        mock_trade_repo = AsyncMock()
        mock_trade_repo.get_pnl_stats_by_period = AsyncMock(return_value=(Decimal("5.00"), 3, 1, 1))

        client = _build_client(
            mock_account=account,
            tracker=mock_tracker,
            trade_repo=mock_trade_repo,
        )
        resp = _authed_request(client, "get", "/api/v1/account/pnl?period=all", account=account)

        assert resp.status_code == 200
        call_kwargs = mock_trade_repo.get_pnl_stats_by_period.call_args
        assert call_kwargs.kwargs.get("since") is None


# ===========================================================================
# PUT /api/v1/account/risk-profile
# ===========================================================================


class TestRiskProfile:
    """Tests for ``PUT /api/v1/account/risk-profile``."""

    def test_update_risk_profile(self) -> None:
        """PUT /account/risk-profile returns 200 with updated profile."""
        account = _make_account()

        mock_account_repo = AsyncMock()
        mock_account_repo.update_risk_profile = AsyncMock(return_value=None)

        mock_agent_repo = AsyncMock()

        client = _build_client(
            mock_account=account,
            account_repo=mock_account_repo,
            agent_repo=mock_agent_repo,
        )
        resp = _authed_request(
            client,
            "put",
            "/api/v1/account/risk-profile",
            account=account,
            json={
                "max_position_size_pct": 30,
                "daily_loss_limit_pct": 15,
                "max_open_orders": 100,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["max_position_size_pct"] == 30
        assert data["daily_loss_limit_pct"] == 15
        assert data["max_open_orders"] == 100

        # Verify the repo was called to persist the update
        mock_account_repo.update_risk_profile.assert_called_once()


# ===========================================================================
# POST /api/v1/account/reset
# ===========================================================================


class TestReset:
    """Tests for ``POST /api/v1/account/reset``."""

    def test_reset_account(self) -> None:
        """POST /account/reset with confirm=true returns 200 with session summaries."""
        account = _make_account()

        # Mock tracker for pre-reset equity snapshot
        mock_tracker = AsyncMock()
        mock_tracker.get_portfolio = AsyncMock(return_value=_make_portfolio_summary())

        # Mock the new session returned by account_service.reset_account()
        new_session = MagicMock()
        new_session.id = uuid4()
        new_session.starting_balance = Decimal("10000.00")
        new_session.started_at = datetime(2026, 3, 17, tzinfo=UTC)

        mock_as = AsyncMock()
        mock_as.reset_account = AsyncMock(return_value=new_session)

        # Mock DB session for _get_active_session query
        mock_trading_session = _make_session(account.id)
        mock_db = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=mock_trading_session)
        mock_db.execute = AsyncMock(return_value=mock_result)

        client = _build_client(
            mock_account=account,
            tracker=mock_tracker,
            account_service=mock_as,
            mock_db_session=mock_db,
        )
        resp = _authed_request(
            client,
            "post",
            "/api/v1/account/reset",
            account=account,
            json={"confirm": True},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["message"] == "Account reset successful"
        assert "previous_session" in data
        assert data["previous_session"]["ending_equity"] == "12458.30"
        assert "new_session" in data
        assert data["new_session"]["session_id"] == str(new_session.id)
        assert data["new_session"]["starting_balance"] == "10000.00"

        # Verify the service was called
        mock_as.reset_account.assert_called_once_with(account.id)
