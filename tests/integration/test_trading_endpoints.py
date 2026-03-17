"""Integration tests for trading REST endpoints.

Covers every endpoint defined in Section 15.3 of the development plan:

- ``POST   /api/v1/trade/order``               — place market, limit, stop-loss, take-profit
- ``GET    /api/v1/trade/order/{order_id}``    — fetch single order by UUID
- ``GET    /api/v1/trade/orders``              — list orders with filters
- ``GET    /api/v1/trade/orders/open``         — list open (pending) orders
- ``DELETE /api/v1/trade/order/{order_id}``   — cancel a single pending order
- ``DELETE /api/v1/trade/orders/open``         — cancel all open orders
- ``GET    /api/v1/trade/history``             — paginated trade execution history

All external I/O (DB session, Redis, OrderEngine, RiskManager) is mocked so
tests run without real infrastructure.  ``app.dependency_overrides`` replaces
the full DI chain so no real DB or Redis connections are made.

Trading endpoints sit behind the ``AuthMiddleware``.  Tests authenticate via a
short-lived JWT signed with the test secret; ``AuthMiddleware``'s internal DB
calls are patched out so no real database connection is needed.

Run with::

    pytest tests/integration/test_trading_endpoints.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from src.accounts.auth import create_jwt
from src.config import Settings
from src.database.models import Account, Order, Trade
from src.order_engine.engine import OrderResult
from src.utils.exceptions import (
    InsufficientBalanceError,
    OrderNotCancellableError,
    OrderNotFoundError,
    PriceNotAvailableError,
)

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

_NOW = datetime(2026, 2, 24, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Shared helpers — data builders
# ---------------------------------------------------------------------------


def _make_order_mock(
    order_id: UUID | None = None,
    account_id: UUID | None = None,
    symbol: str = "BTCUSDT",
    side: str = "buy",
    order_type: str = "market",
    status: str = "filled",
    quantity: Decimal = Decimal("0.5"),
    price: Decimal | None = None,
    executed_price: Decimal | None = Decimal("64521.30"),
    executed_qty: Decimal | None = Decimal("0.5"),
    slippage_pct: Decimal | None = Decimal("0.006"),
    fee: Decimal | None = Decimal("32.26"),
    created_at: datetime | None = None,
    filled_at: datetime | None = None,
) -> MagicMock:
    """Build a mock ORM :class:`~src.database.models.Order` object."""
    order = MagicMock(spec=Order)
    order.id = order_id or uuid4()
    order.account_id = account_id or uuid4()
    order.symbol = symbol
    order.side = side
    order.type = order_type
    order.status = status
    order.quantity = quantity
    order.price = price
    order.executed_price = executed_price
    order.executed_qty = executed_qty
    order.slippage_pct = slippage_pct
    order.fee = fee
    order.created_at = created_at or _NOW
    order.filled_at = filled_at or (_NOW if status == "filled" else None)
    return order


def _make_trade_mock(
    trade_id: UUID | None = None,
    order_id: UUID | None = None,
    symbol: str = "BTCUSDT",
    side: str = "buy",
    quantity: Decimal = Decimal("0.5"),
    price: Decimal = Decimal("64521.30"),
    fee: Decimal = Decimal("32.26"),
    quote_amount: Decimal = Decimal("32294.85"),
    created_at: datetime | None = None,
) -> MagicMock:
    """Build a mock ORM :class:`~src.database.models.Trade` object."""
    trade = MagicMock(spec=Trade)
    trade.id = trade_id or uuid4()
    trade.order_id = order_id or uuid4()
    trade.symbol = symbol
    trade.side = side
    trade.quantity = quantity
    trade.price = price
    trade.fee = fee
    trade.quote_amount = quote_amount
    trade.created_at = created_at or _NOW
    return trade


def _make_order_result(
    order_id: UUID | None = None,
    status: str = "filled",
    executed_price: Decimal | None = Decimal("64521.30"),
    executed_quantity: Decimal | None = Decimal("0.5"),
    slippage_pct: Decimal | None = Decimal("0.006"),
    fee: Decimal | None = Decimal("32.26"),
) -> OrderResult:
    """Build an :class:`~src.order_engine.engine.OrderResult` for mock responses."""
    return OrderResult(
        order_id=order_id or uuid4(),
        status=status,
        executed_price=executed_price,
        executed_quantity=executed_quantity,
        slippage_pct=slippage_pct,
        fee=fee,
        timestamp=_NOW,
    )


# ---------------------------------------------------------------------------
# Auth helpers — trading endpoints sit behind the auth middleware
# ---------------------------------------------------------------------------


def _make_account_mock(account_id: UUID | None = None) -> MagicMock:
    """Build a mock :class:`~src.database.models.Account` for auth middleware."""
    account = MagicMock(spec=Account)
    account.id = account_id or uuid4()
    account.api_key = "ak_live_testkey"
    account.api_secret_hash = "$2b$12$fakehash"
    account.display_name = "TestBot"
    account.status = "active"
    account.starting_balance = Decimal("10000.00")
    return account


def _make_auth_context(
    account: MagicMock | None = None,
) -> tuple[dict[str, str], MagicMock, MagicMock]:
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
        account = _make_account_mock()

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
    client: TestClient,
    method: str,
    url: str,
    **kwargs,
):
    """Issue an authenticated HTTP request through the auth middleware.

    Patches ``AuthMiddleware``'s internal DB lookups so the JWT is accepted
    without a real database connection.  Also suppresses the auth middleware
    logger.

    Args:
        client: The ``TestClient`` instance.
        method: HTTP method (``"get"``, ``"post"``, ``"delete"``).
        url:    Request path.
        **kwargs: Extra kwargs forwarded to the client method (e.g. ``json``, ``headers``).

    Returns:
        The ``Response`` object.
    """
    headers, mock_repo, mock_session_factory = _make_auth_context()
    merged_headers = {**headers, **kwargs.pop("headers", {})}
    with (
        patch("src.api.middleware.auth.logger"),
        patch("src.api.middleware.auth.get_settings", return_value=_TEST_SETTINGS),
        patch("src.api.middleware.auth.AccountRepository", return_value=mock_repo),
        patch("src.database.session.get_session_factory", return_value=mock_session_factory),
    ):
        return getattr(client, method)(url, headers=merged_headers, **kwargs)


def _authed_get(client: TestClient, url: str, **kwargs):
    return _authed_request(client, "get", url, **kwargs)


def _authed_post(client: TestClient, url: str, **kwargs):
    return _authed_request(client, "post", url, **kwargs)


def _authed_delete(client: TestClient, url: str, **kwargs):
    return _authed_request(client, "delete", url, **kwargs)


# ---------------------------------------------------------------------------
# App + client factory
# ---------------------------------------------------------------------------


def _build_client(
    *,
    order_repo: AsyncMock | None = None,
    trade_repo: AsyncMock | None = None,
    order_engine: AsyncMock | None = None,
    risk_manager: AsyncMock | None = None,
) -> TestClient:
    """Create a ``TestClient`` with mocked trading service dependencies.

    All service layers (OrderEngine, RiskManager, repositories) are replaced
    with ``AsyncMock`` instances injected via ``app.dependency_overrides``.

    Args:
        order_repo:    Optional pre-configured ``AsyncMock`` for ``OrderRepository``.
        trade_repo:    Optional pre-configured ``AsyncMock`` for ``TradeRepository``.
        order_engine:  Optional pre-configured ``AsyncMock`` for ``OrderEngine``.
        risk_manager:  Optional pre-configured ``AsyncMock`` for ``RiskManager``.

    Returns:
        A ``TestClient`` wrapping the fully configured application.
    """
    from src.dependencies import (
        get_db_session,
        get_order_engine,
        get_order_repo,
        get_redis,
        get_risk_manager,
        get_settings,
        get_trade_repo,
    )

    if order_repo is None:
        order_repo = AsyncMock()
        order_repo.list_by_account = AsyncMock(return_value=[])
        order_repo.list_open_by_account = AsyncMock(return_value=[])
        order_repo.get_by_id = AsyncMock(side_effect=OrderNotFoundError("Not found."))

    if trade_repo is None:
        trade_repo = AsyncMock()
        trade_repo.list_by_account = AsyncMock(return_value=[])

    if risk_manager is None:
        risk_result = MagicMock()
        risk_result.approved = True
        risk_result.rejection_reason = None
        risk_manager = AsyncMock()
        risk_manager.validate_order = AsyncMock(return_value=risk_result)

    if order_engine is None:
        order_engine = AsyncMock()
        order_engine.place_order = AsyncMock(return_value=_make_order_result())
        order_engine.cancel_order = AsyncMock(return_value=None)
        order_engine.cancel_all_orders = AsyncMock(return_value=0)

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

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    _order_repo = order_repo
    _trade_repo = trade_repo
    _order_engine = order_engine
    _risk_manager = risk_manager

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

        async def _override_db():
            yield mock_session

        app.dependency_overrides[get_db_session] = _override_db

        async def _override_redis():
            yield mock_redis

        app.dependency_overrides[get_redis] = _override_redis

        async def _override_order_repo():
            return _order_repo

        app.dependency_overrides[get_order_repo] = _override_order_repo

        async def _override_trade_repo():
            return _trade_repo

        app.dependency_overrides[get_trade_repo] = _override_trade_repo

        async def _override_order_engine():
            return _order_engine

        app.dependency_overrides[get_order_engine] = _override_order_engine

        async def _override_risk_manager():
            return _risk_manager

        app.dependency_overrides[get_risk_manager] = _override_risk_manager

        return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_order_repo() -> AsyncMock:
    """A fresh ``AsyncMock`` standing in for ``OrderRepository``."""
    repo = AsyncMock()
    repo.list_by_account = AsyncMock(return_value=[])
    repo.list_open_by_account = AsyncMock(return_value=[])
    repo.get_by_id = AsyncMock(side_effect=OrderNotFoundError("Not found."))
    return repo


@pytest.fixture()
def mock_trade_repo() -> AsyncMock:
    """A fresh ``AsyncMock`` standing in for ``TradeRepository``."""
    repo = AsyncMock()
    repo.list_by_account = AsyncMock(return_value=[])
    return repo


@pytest.fixture()
def mock_risk_manager() -> AsyncMock:
    """A fresh ``AsyncMock`` standing in for ``RiskManager`` (pre-approved)."""
    risk_result = MagicMock()
    risk_result.approved = True
    risk_result.rejection_reason = None
    mgr = AsyncMock()
    mgr.validate_order = AsyncMock(return_value=risk_result)
    return mgr


@pytest.fixture()
def mock_order_engine() -> AsyncMock:
    """A fresh ``AsyncMock`` standing in for ``OrderEngine``."""
    engine = AsyncMock()
    engine.place_order = AsyncMock(return_value=_make_order_result())
    engine.cancel_order = AsyncMock(return_value=None)
    engine.cancel_all_orders = AsyncMock(return_value=0)
    return engine


# ===========================================================================
# POST /api/v1/trade/order — place order
# ===========================================================================


class TestPlaceOrder:
    """Tests for ``POST /api/v1/trade/order``."""

    # --- Market order happy path ---

    def test_market_buy_returns_201(self, mock_risk_manager: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """Valid market buy order → HTTP 201."""
        mock_order_engine.place_order = AsyncMock(return_value=_make_order_result(status="filled"))

        client = _build_client(order_engine=mock_order_engine, risk_manager=mock_risk_manager)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.5"},
        )

        assert resp.status_code == 201

    def test_market_sell_returns_201(self, mock_risk_manager: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """Valid market sell order → HTTP 201."""
        mock_order_engine.place_order = AsyncMock(return_value=_make_order_result(status="filled"))

        client = _build_client(order_engine=mock_order_engine, risk_manager=mock_risk_manager)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "ETHUSDT", "side": "sell", "type": "market", "quantity": "1.0"},
        )

        assert resp.status_code == 201

    def test_market_order_response_has_required_fields(
        self, mock_risk_manager: AsyncMock, mock_order_engine: AsyncMock
    ) -> None:
        """Filled market order response includes all expected fields."""
        result = _make_order_result(status="filled")
        mock_order_engine.place_order = AsyncMock(return_value=result)

        client = _build_client(order_engine=mock_order_engine, risk_manager=mock_risk_manager)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.5"},
        )

        assert resp.status_code == 201
        body = resp.json()
        for field in ("order_id", "status", "symbol", "side", "type"):
            assert field in body, f"Missing field: {field}"

    def test_market_order_status_is_filled(self, mock_risk_manager: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """Market order response has ``status='filled'``."""
        mock_order_engine.place_order = AsyncMock(return_value=_make_order_result(status="filled"))

        client = _build_client(order_engine=mock_order_engine, risk_manager=mock_risk_manager)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.5"},
        )

        assert resp.json()["status"] == "filled"

    def test_market_order_symbol_uppercased(self, mock_risk_manager: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """Symbol in response is always uppercase."""
        mock_order_engine.place_order = AsyncMock(return_value=_make_order_result(status="filled"))

        client = _build_client(order_engine=mock_order_engine, risk_manager=mock_risk_manager)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "btcusdt", "side": "buy", "type": "market", "quantity": "0.5"},
        )

        assert resp.json()["symbol"] == "BTCUSDT"

    def test_market_order_decimal_fields_are_strings(
        self, mock_risk_manager: AsyncMock, mock_order_engine: AsyncMock
    ) -> None:
        """Decimal fields in order response are serialized as strings."""
        mock_order_engine.place_order = AsyncMock(return_value=_make_order_result(status="filled"))

        client = _build_client(order_engine=mock_order_engine, risk_manager=mock_risk_manager)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.5"},
        )

        body = resp.json()
        for field in ("executed_price", "executed_quantity", "fee"):
            if body.get(field) is not None:
                assert isinstance(body[field], str), f"Field {field!r} is not a string"

    def test_market_order_order_id_is_uuid(self, mock_risk_manager: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """``order_id`` in response is a valid UUID string."""
        oid = uuid4()
        mock_order_engine.place_order = AsyncMock(return_value=_make_order_result(order_id=oid, status="filled"))

        client = _build_client(order_engine=mock_order_engine, risk_manager=mock_risk_manager)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.5"},
        )

        assert UUID(resp.json()["order_id"]) == oid

    # --- Limit order happy path ---

    def test_limit_buy_returns_201(self, mock_risk_manager: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """Valid limit buy order → HTTP 201 with ``status='pending'``."""
        mock_order_engine.place_order = AsyncMock(
            return_value=_make_order_result(
                status="pending",
                executed_price=None,
                executed_quantity=None,
                slippage_pct=None,
                fee=None,
            )
        )

        client = _build_client(order_engine=mock_order_engine, risk_manager=mock_risk_manager)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={
                "symbol": "BTCUSDT",
                "side": "buy",
                "type": "limit",
                "quantity": "0.5",
                "price": "63000.00",
            },
        )

        assert resp.status_code == 201
        assert resp.json()["status"] == "pending"

    def test_limit_sell_returns_201(self, mock_risk_manager: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """Valid limit sell order → HTTP 201 with ``status='pending'``."""
        mock_order_engine.place_order = AsyncMock(
            return_value=_make_order_result(
                status="pending",
                executed_price=None,
                executed_quantity=None,
                slippage_pct=None,
                fee=None,
            )
        )

        client = _build_client(order_engine=mock_order_engine, risk_manager=mock_risk_manager)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={
                "symbol": "ETHUSDT",
                "side": "sell",
                "type": "limit",
                "quantity": "2.0",
                "price": "3500.00",
            },
        )

        assert resp.status_code == 201
        assert resp.json()["status"] == "pending"

    def test_stop_loss_order_returns_201(self, mock_risk_manager: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """Valid stop-loss order → HTTP 201."""
        mock_order_engine.place_order = AsyncMock(
            return_value=_make_order_result(
                status="pending",
                executed_price=None,
                executed_quantity=None,
                slippage_pct=None,
                fee=None,
            )
        )

        client = _build_client(order_engine=mock_order_engine, risk_manager=mock_risk_manager)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={
                "symbol": "BTCUSDT",
                "side": "sell",
                "type": "stop_loss",
                "quantity": "0.1",
                "price": "60000.00",
            },
        )

        assert resp.status_code == 201

    def test_take_profit_order_returns_201(self, mock_risk_manager: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """Valid take-profit order → HTTP 201."""
        mock_order_engine.place_order = AsyncMock(
            return_value=_make_order_result(
                status="pending",
                executed_price=None,
                executed_quantity=None,
                slippage_pct=None,
                fee=None,
            )
        )

        client = _build_client(order_engine=mock_order_engine, risk_manager=mock_risk_manager)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={
                "symbol": "BTCUSDT",
                "side": "sell",
                "type": "take_profit",
                "quantity": "0.1",
                "price": "70000.00",
            },
        )

        assert resp.status_code == 201

    # --- Validation failures ---

    def test_missing_symbol_returns_422(self) -> None:
        """Missing ``symbol`` field → Pydantic validation error (HTTP 422)."""
        client = _build_client()
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"side": "buy", "type": "market", "quantity": "0.5"},
        )
        assert resp.status_code == 422

    def test_missing_side_returns_422(self) -> None:
        """Missing ``side`` field → HTTP 422."""
        client = _build_client()
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "type": "market", "quantity": "0.5"},
        )
        assert resp.status_code == 422

    def test_missing_type_returns_422(self) -> None:
        """Missing ``type`` field → HTTP 422."""
        client = _build_client()
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "quantity": "0.5"},
        )
        assert resp.status_code == 422

    def test_missing_quantity_returns_422(self) -> None:
        """Missing ``quantity`` field → HTTP 422."""
        client = _build_client()
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "market"},
        )
        assert resp.status_code == 422

    def test_zero_quantity_returns_422(self) -> None:
        """``quantity`` = 0 violates ``gt=0`` constraint → HTTP 422."""
        client = _build_client()
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0"},
        )
        assert resp.status_code == 422

    def test_negative_quantity_returns_422(self) -> None:
        """Negative ``quantity`` violates ``gt=0`` constraint → HTTP 422."""
        client = _build_client()
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "-1.0"},
        )
        assert resp.status_code == 422

    def test_invalid_side_returns_422(self) -> None:
        """Unknown ``side`` value → Pydantic Literal validation → HTTP 422."""
        client = _build_client()
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "long", "type": "market", "quantity": "0.5"},
        )
        assert resp.status_code == 422

    def test_invalid_type_returns_422(self) -> None:
        """Unknown ``type`` value → Pydantic Literal validation → HTTP 422."""
        client = _build_client()
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "oco", "quantity": "0.5"},
        )
        assert resp.status_code == 422

    def test_limit_order_without_price_returns_422(self) -> None:
        """Limit order without ``price`` fails model_validator → HTTP 422."""
        client = _build_client()
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "limit", "quantity": "0.5"},
        )
        assert resp.status_code == 422

    def test_market_order_with_price_returns_422(self) -> None:
        """Market order WITH ``price`` fails model_validator → HTTP 422."""
        client = _build_client()
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={
                "symbol": "BTCUSDT",
                "side": "buy",
                "type": "market",
                "quantity": "0.5",
                "price": "64000.00",
            },
        )
        assert resp.status_code == 422

    def test_stop_loss_without_price_returns_422(self) -> None:
        """Stop-loss order without ``price`` → HTTP 422."""
        client = _build_client()
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "sell", "type": "stop_loss", "quantity": "0.5"},
        )
        assert resp.status_code == 422

    def test_zero_price_returns_422(self) -> None:
        """``price`` = 0 violates ``gt=0`` constraint → HTTP 422."""
        client = _build_client()
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={
                "symbol": "BTCUSDT",
                "side": "buy",
                "type": "limit",
                "quantity": "0.5",
                "price": "0",
            },
        )
        assert resp.status_code == 422

    # --- Service-layer error handling ---

    def test_risk_rejected_order_returns_400(self, mock_order_engine: AsyncMock) -> None:
        """Risk manager rejects → HTTP 400 with ``ORDER_REJECTED`` code."""
        risk_result = MagicMock()
        risk_result.approved = False
        risk_result.rejection_reason = "Position size exceeds limit."
        risk_mgr = AsyncMock()
        risk_mgr.validate_order = AsyncMock(return_value=risk_result)

        client = _build_client(order_engine=mock_order_engine, risk_manager=risk_mgr)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.5"},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "ORDER_REJECTED"

    def test_insufficient_balance_returns_400(self, mock_risk_manager: AsyncMock) -> None:
        """Engine raises ``InsufficientBalanceError`` → HTTP 400."""
        engine = AsyncMock()
        engine.place_order = AsyncMock(side_effect=InsufficientBalanceError("Insufficient USDT balance."))

        client = _build_client(order_engine=engine, risk_manager=mock_risk_manager)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.5"},
        )

        assert resp.status_code == 400
        body = resp.json()
        assert body["error"]["code"] == "INSUFFICIENT_BALANCE"

    def test_price_not_available_returns_503(self, mock_risk_manager: AsyncMock) -> None:
        """Engine raises ``PriceNotAvailableError`` → HTTP 503."""
        engine = AsyncMock()
        engine.place_order = AsyncMock(side_effect=PriceNotAvailableError("BTCUSDT has no live price."))

        client = _build_client(order_engine=engine, risk_manager=mock_risk_manager)
        resp = _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.5"},
        )

        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["code"] == "PRICE_NOT_AVAILABLE"

    def test_unauthenticated_request_returns_401(self) -> None:
        """Request without credentials → HTTP 401 from auth middleware."""
        client = _build_client()
        resp = client.post(
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.5"},
        )
        assert resp.status_code == 401

    def test_risk_manager_called_before_engine(
        self, mock_risk_manager: AsyncMock, mock_order_engine: AsyncMock
    ) -> None:
        """The route calls risk validation before order execution."""
        mock_order_engine.place_order = AsyncMock(return_value=_make_order_result(status="filled"))

        client = _build_client(order_engine=mock_order_engine, risk_manager=mock_risk_manager)
        _authed_post(
            client,
            "/api/v1/trade/order",
            json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.5"},
        )

        mock_risk_manager.validate_order.assert_called_once()
        mock_order_engine.place_order.assert_called_once()


# ===========================================================================
# GET /api/v1/trade/order/{order_id}
# ===========================================================================


class TestGetOrder:
    """Tests for ``GET /api/v1/trade/order/{order_id}``."""

    def test_get_order_success_returns_200(self, mock_order_repo: AsyncMock) -> None:
        """Known order UUID → HTTP 200 with order detail."""
        order = _make_order_mock()
        mock_order_repo.get_by_id = AsyncMock(return_value=order)

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, f"/api/v1/trade/order/{order.id}")

        assert resp.status_code == 200

    def test_get_order_response_has_required_fields(self, mock_order_repo: AsyncMock) -> None:
        """Response includes all expected fields for a filled order."""
        order = _make_order_mock(status="filled")
        mock_order_repo.get_by_id = AsyncMock(return_value=order)

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, f"/api/v1/trade/order/{order.id}")

        body = resp.json()
        for field in (
            "order_id",
            "status",
            "symbol",
            "side",
            "type",
            "quantity",
            "created_at",
        ):
            assert field in body, f"Missing field: {field}"

    def test_get_order_decimal_fields_are_strings(self, mock_order_repo: AsyncMock) -> None:
        """All Decimal fields in order detail are serialized as strings."""
        order = _make_order_mock(status="filled")
        mock_order_repo.get_by_id = AsyncMock(return_value=order)

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, f"/api/v1/trade/order/{order.id}")

        body = resp.json()
        assert isinstance(body["quantity"], str)
        if body.get("executed_price") is not None:
            assert isinstance(body["executed_price"], str)
        if body.get("fee") is not None:
            assert isinstance(body["fee"], str)

    def test_get_order_not_found_returns_404(self, mock_order_repo: AsyncMock) -> None:
        """Unknown order UUID → ``OrderNotFoundError`` → HTTP 404."""
        mock_order_repo.get_by_id = AsyncMock(side_effect=OrderNotFoundError("Order not found."))

        unknown_id = uuid4()
        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, f"/api/v1/trade/order/{unknown_id}")

        assert resp.status_code == 404
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "ORDER_NOT_FOUND"

    def test_get_order_invalid_uuid_returns_422(self) -> None:
        """Non-UUID order_id path parameter → HTTP 422 from Pydantic."""
        client = _build_client()
        resp = _authed_get(client, "/api/v1/trade/order/not-a-uuid")
        assert resp.status_code == 422

    def test_get_order_correct_id_in_response(self, mock_order_repo: AsyncMock) -> None:
        """``order_id`` in response matches the queried UUID."""
        order = _make_order_mock()
        mock_order_repo.get_by_id = AsyncMock(return_value=order)

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, f"/api/v1/trade/order/{order.id}")

        assert UUID(resp.json()["order_id"]) == order.id

    def test_get_order_no_auth_returns_401(self) -> None:
        """Unauthenticated request → HTTP 401."""
        client = _build_client()
        resp = client.get(f"/api/v1/trade/order/{uuid4()}")
        assert resp.status_code == 401

    def test_get_pending_order_has_no_executed_price(self, mock_order_repo: AsyncMock) -> None:
        """Pending limit order has ``executed_price=null`` in response."""
        order = _make_order_mock(
            order_type="limit",
            status="pending",
            price=Decimal("63000.00"),
            executed_price=None,
            executed_qty=None,
            slippage_pct=None,
            fee=None,
            filled_at=None,
        )
        mock_order_repo.get_by_id = AsyncMock(return_value=order)

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, f"/api/v1/trade/order/{order.id}")

        body = resp.json()
        assert resp.status_code == 200
        assert body["status"] == "pending"
        assert body["executed_price"] is None


# ===========================================================================
# GET /api/v1/trade/orders — list orders
# ===========================================================================


class TestListOrders:
    """Tests for ``GET /api/v1/trade/orders``."""

    def test_list_orders_returns_200(self, mock_order_repo: AsyncMock) -> None:
        """Happy path: returns HTTP 200 with orders list."""
        mock_order_repo.list_by_account = AsyncMock(return_value=[_make_order_mock()])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders")

        assert resp.status_code == 200

    def test_list_orders_response_has_required_fields(self, mock_order_repo: AsyncMock) -> None:
        """Response body includes ``orders``, ``total``, ``limit``, ``offset``."""
        mock_order_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders")

        body = resp.json()
        for field in ("orders", "total", "limit", "offset"):
            assert field in body, f"Missing field: {field}"

    def test_list_orders_empty_returns_200(self, mock_order_repo: AsyncMock) -> None:
        """No orders → 200 with empty list and ``total=0``."""
        mock_order_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders")

        body = resp.json()
        assert body["orders"] == []
        assert body["total"] == 0

    def test_list_orders_total_matches_list_length(self, mock_order_repo: AsyncMock) -> None:
        """``total`` matches the count of returned ``orders``."""
        orders = [_make_order_mock() for _ in range(3)]
        mock_order_repo.list_by_account = AsyncMock(return_value=orders)

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders")

        body = resp.json()
        assert body["total"] == 3
        assert len(body["orders"]) == 3

    def test_list_orders_filter_by_status(self, mock_order_repo: AsyncMock) -> None:
        """``?status=filled`` query param is forwarded; response is 200."""
        mock_order_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders?status=filled")

        assert resp.status_code == 200
        mock_order_repo.list_by_account.assert_called_once()
        call_kwargs = mock_order_repo.list_by_account.call_args.kwargs
        assert call_kwargs.get("status") == "filled"

    def test_list_orders_filter_by_symbol(self, mock_order_repo: AsyncMock) -> None:
        """``?symbol=ETHUSDT`` query param is forwarded uppercase; response is 200."""
        mock_order_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders?symbol=ethusdt")

        assert resp.status_code == 200
        call_kwargs = mock_order_repo.list_by_account.call_args.kwargs
        assert call_kwargs.get("symbol") == "ETHUSDT"

    def test_list_orders_default_pagination(self, mock_order_repo: AsyncMock) -> None:
        """Default ``limit=100`` and ``offset=0`` are reflected in response."""
        mock_order_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders")

        body = resp.json()
        assert body["limit"] == 100
        assert body["offset"] == 0

    def test_list_orders_custom_pagination(self, mock_order_repo: AsyncMock) -> None:
        """Custom ``limit`` and ``offset`` are reflected in response."""
        mock_order_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders?limit=25&offset=50")

        body = resp.json()
        assert body["limit"] == 25
        assert body["offset"] == 50

    def test_list_orders_limit_too_high_returns_422(self, mock_order_repo: AsyncMock) -> None:
        """``limit`` > 500 violates Query constraint → HTTP 422."""
        mock_order_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders?limit=9999")

        assert resp.status_code == 422

    def test_list_orders_negative_offset_returns_422(self, mock_order_repo: AsyncMock) -> None:
        """Negative ``offset`` violates ``ge=0`` constraint → HTTP 422."""
        mock_order_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders?offset=-1")

        assert resp.status_code == 422

    def test_list_orders_no_auth_returns_401(self) -> None:
        """Unauthenticated request → HTTP 401."""
        client = _build_client()
        resp = client.get("/api/v1/trade/orders")
        assert resp.status_code == 401


# ===========================================================================
# GET /api/v1/trade/orders/open — list open orders
# ===========================================================================


class TestListOpenOrders:
    """Tests for ``GET /api/v1/trade/orders/open``."""

    def test_list_open_orders_returns_200(self, mock_order_repo: AsyncMock) -> None:
        """Happy path: returns HTTP 200."""
        pending = _make_order_mock(status="pending", order_type="limit", price=Decimal("63000.00"))
        mock_order_repo.list_open_by_account = AsyncMock(return_value=[pending])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders/open")

        assert resp.status_code == 200

    def test_list_open_orders_response_structure(self, mock_order_repo: AsyncMock) -> None:
        """Response includes ``orders``, ``total``, ``limit``, ``offset``."""
        mock_order_repo.list_open_by_account = AsyncMock(return_value=[])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders/open")

        body = resp.json()
        for field in ("orders", "total", "limit", "offset"):
            assert field in body, f"Missing field: {field}"

    def test_list_open_orders_only_pending_returned(self, mock_order_repo: AsyncMock) -> None:
        """Only pending/partially-filled orders are returned by the repo mock."""
        pending = _make_order_mock(
            status="pending",
            order_type="limit",
            price=Decimal("63000.00"),
            executed_price=None,
        )
        mock_order_repo.list_open_by_account = AsyncMock(return_value=[pending])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders/open")

        body = resp.json()
        assert body["total"] == 1
        assert body["orders"][0]["status"] == "pending"

    def test_list_open_orders_empty_returns_200(self, mock_order_repo: AsyncMock) -> None:
        """No open orders → 200 with empty list."""
        mock_order_repo.list_open_by_account = AsyncMock(return_value=[])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders/open")

        body = resp.json()
        assert body["orders"] == []
        assert body["total"] == 0

    def test_list_open_orders_limit_param(self, mock_order_repo: AsyncMock) -> None:
        """``?limit=10`` is accepted and reflected in response."""
        mock_order_repo.list_open_by_account = AsyncMock(return_value=[])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders/open?limit=10")

        assert resp.status_code == 200
        assert resp.json()["limit"] == 10

    def test_list_open_orders_limit_too_high_returns_422(self, mock_order_repo: AsyncMock) -> None:
        """``limit`` > 200 violates Query constraint → HTTP 422."""
        mock_order_repo.list_open_by_account = AsyncMock(return_value=[])

        client = _build_client(order_repo=mock_order_repo)
        resp = _authed_get(client, "/api/v1/trade/orders/open?limit=9999")

        assert resp.status_code == 422

    def test_list_open_orders_no_auth_returns_401(self) -> None:
        """Unauthenticated request → HTTP 401."""
        client = _build_client()
        resp = client.get("/api/v1/trade/orders/open")
        assert resp.status_code == 401


# ===========================================================================
# DELETE /api/v1/trade/order/{order_id} — cancel single order
# ===========================================================================


class TestCancelOrder:
    """Tests for ``DELETE /api/v1/trade/order/{order_id}``."""

    def test_cancel_order_returns_200(self, mock_order_repo: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """Pending order cancelled → HTTP 200."""
        order = _make_order_mock(
            order_type="limit",
            status="pending",
            price=Decimal("63000.00"),
            executed_price=None,
        )
        mock_order_repo.get_by_id = AsyncMock(return_value=order)
        mock_order_engine.cancel_order = AsyncMock(return_value=None)

        client = _build_client(order_repo=mock_order_repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, f"/api/v1/trade/order/{order.id}")

        assert resp.status_code == 200

    def test_cancel_order_response_has_required_fields(
        self, mock_order_repo: AsyncMock, mock_order_engine: AsyncMock
    ) -> None:
        """Response includes ``order_id``, ``status``, ``unlocked_amount``, ``cancelled_at``."""
        order = _make_order_mock(
            order_type="limit",
            status="pending",
            price=Decimal("63000.00"),
            executed_price=None,
        )
        mock_order_repo.get_by_id = AsyncMock(return_value=order)
        mock_order_engine.cancel_order = AsyncMock(return_value=None)

        client = _build_client(order_repo=mock_order_repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, f"/api/v1/trade/order/{order.id}")

        body = resp.json()
        for field in ("order_id", "status", "unlocked_amount", "cancelled_at"):
            assert field in body, f"Missing field: {field}"

    def test_cancel_order_status_is_cancelled(self, mock_order_repo: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """``status`` in response is always ``'cancelled'``."""
        order = _make_order_mock(
            order_type="limit",
            status="pending",
            price=Decimal("63000.00"),
            executed_price=None,
        )
        mock_order_repo.get_by_id = AsyncMock(return_value=order)
        mock_order_engine.cancel_order = AsyncMock(return_value=None)

        client = _build_client(order_repo=mock_order_repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, f"/api/v1/trade/order/{order.id}")

        assert resp.json()["status"] == "cancelled"

    def test_cancel_order_order_id_matches(self, mock_order_repo: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """``order_id`` in response matches the requested UUID."""
        order = _make_order_mock(
            order_type="limit",
            status="pending",
            price=Decimal("63000.00"),
            executed_price=None,
        )
        mock_order_repo.get_by_id = AsyncMock(return_value=order)
        mock_order_engine.cancel_order = AsyncMock(return_value=None)

        client = _build_client(order_repo=mock_order_repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, f"/api/v1/trade/order/{order.id}")

        assert UUID(resp.json()["order_id"]) == order.id

    def test_cancel_order_unlocked_amount_is_string(
        self, mock_order_repo: AsyncMock, mock_order_engine: AsyncMock
    ) -> None:
        """``unlocked_amount`` in response is a string (Decimal serialization)."""
        order = _make_order_mock(
            order_type="limit",
            status="pending",
            price=Decimal("63000.00"),
            executed_price=None,
        )
        mock_order_repo.get_by_id = AsyncMock(return_value=order)
        mock_order_engine.cancel_order = AsyncMock(return_value=None)

        client = _build_client(order_repo=mock_order_repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, f"/api/v1/trade/order/{order.id}")

        assert isinstance(resp.json()["unlocked_amount"], str)

    def test_cancel_order_buy_limit_unlocked_amount_nonzero(
        self, mock_order_repo: AsyncMock, mock_order_engine: AsyncMock
    ) -> None:
        """Buy limit cancel unlocks ``price * qty * (1 + fee_fraction)``."""
        qty = Decimal("0.5")
        price = Decimal("63000.00")
        order = _make_order_mock(
            order_type="limit",
            side="buy",
            status="pending",
            quantity=qty,
            price=price,
            executed_price=None,
        )
        mock_order_repo.get_by_id = AsyncMock(return_value=order)
        mock_order_engine.cancel_order = AsyncMock(return_value=None)

        client = _build_client(order_repo=mock_order_repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, f"/api/v1/trade/order/{order.id}")

        body = resp.json()
        unlocked = Decimal(body["unlocked_amount"])
        gross = qty * price
        expected = gross + gross * Decimal("0.001")
        assert unlocked == expected

    def test_cancel_order_sell_limit_unlocked_is_qty(
        self, mock_order_repo: AsyncMock, mock_order_engine: AsyncMock
    ) -> None:
        """Sell limit cancel unlocks the base-asset quantity."""
        qty = Decimal("1.5")
        order = _make_order_mock(
            order_type="limit",
            side="sell",
            status="pending",
            quantity=qty,
            price=Decimal("65000.00"),
            executed_price=None,
        )
        mock_order_repo.get_by_id = AsyncMock(return_value=order)
        mock_order_engine.cancel_order = AsyncMock(return_value=None)

        client = _build_client(order_repo=mock_order_repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, f"/api/v1/trade/order/{order.id}")

        assert Decimal(resp.json()["unlocked_amount"]) == qty

    def test_cancel_market_order_unlocked_is_zero(
        self, mock_order_repo: AsyncMock, mock_order_engine: AsyncMock
    ) -> None:
        """Cancelling a filled market order (price=None) → unlocked_amount='0'."""
        order = _make_order_mock(order_type="market", status="filled", price=None)
        mock_order_repo.get_by_id = AsyncMock(return_value=order)
        mock_order_engine.cancel_order = AsyncMock(return_value=None)

        client = _build_client(order_repo=mock_order_repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, f"/api/v1/trade/order/{order.id}")

        assert Decimal(resp.json()["unlocked_amount"]) == Decimal("0")

    def test_cancel_order_not_found_returns_404(self, mock_order_engine: AsyncMock) -> None:
        """Unknown order UUID → ``OrderNotFoundError`` → HTTP 404."""
        repo = AsyncMock()
        repo.get_by_id = AsyncMock(side_effect=OrderNotFoundError("Order not found."))

        client = _build_client(order_repo=repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, f"/api/v1/trade/order/{uuid4()}")

        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ORDER_NOT_FOUND"

    def test_cancel_non_cancellable_order_returns_400(self, mock_order_repo: AsyncMock) -> None:
        """Engine raises ``OrderNotCancellableError`` → HTTP 400 with ``ORDER_NOT_CANCELLABLE`` code."""
        order = _make_order_mock(status="filled")
        mock_order_repo.get_by_id = AsyncMock(return_value=order)

        engine = AsyncMock()
        engine.cancel_order = AsyncMock(side_effect=OrderNotCancellableError("Cannot cancel a filled order."))

        client = _build_client(order_repo=mock_order_repo, order_engine=engine)
        resp = _authed_delete(client, f"/api/v1/trade/order/{order.id}")

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "ORDER_NOT_CANCELLABLE"

    def test_cancel_order_invalid_uuid_returns_422(self) -> None:
        """Non-UUID path parameter → HTTP 422."""
        client = _build_client()
        resp = _authed_delete(client, "/api/v1/trade/order/not-a-uuid")
        assert resp.status_code == 422

    def test_cancel_order_no_auth_returns_401(self) -> None:
        """Unauthenticated request → HTTP 401."""
        client = _build_client()
        resp = client.delete(f"/api/v1/trade/order/{uuid4()}")
        assert resp.status_code == 401


# ===========================================================================
# DELETE /api/v1/trade/orders/open — cancel all open orders
# ===========================================================================


class TestCancelAllOrders:
    """Tests for ``DELETE /api/v1/trade/orders/open``."""

    def test_cancel_all_returns_200(self, mock_order_repo: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """No open orders → HTTP 200 with zero count."""
        mock_order_repo.list_open_by_account = AsyncMock(return_value=[])
        mock_order_engine.cancel_all_orders = AsyncMock(return_value=0)

        client = _build_client(order_repo=mock_order_repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, "/api/v1/trade/orders/open")

        assert resp.status_code == 200

    def test_cancel_all_response_has_required_fields(
        self, mock_order_repo: AsyncMock, mock_order_engine: AsyncMock
    ) -> None:
        """Response includes ``cancelled_count`` and ``total_unlocked``."""
        mock_order_repo.list_open_by_account = AsyncMock(return_value=[])
        mock_order_engine.cancel_all_orders = AsyncMock(return_value=0)

        client = _build_client(order_repo=mock_order_repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, "/api/v1/trade/orders/open")

        body = resp.json()
        assert "cancelled_count" in body
        assert "total_unlocked" in body

    def test_cancel_all_zero_open_orders(self, mock_order_repo: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """No open orders → ``cancelled_count=0``, ``total_unlocked='0'``."""
        mock_order_repo.list_open_by_account = AsyncMock(return_value=[])
        mock_order_engine.cancel_all_orders = AsyncMock(return_value=0)

        client = _build_client(order_repo=mock_order_repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, "/api/v1/trade/orders/open")

        body = resp.json()
        assert body["cancelled_count"] == 0
        assert Decimal(body["total_unlocked"]) == Decimal("0")

    def test_cancel_all_multiple_orders(self, mock_order_repo: AsyncMock, mock_order_engine: AsyncMock) -> None:
        """Three open limit orders → ``cancelled_count=3``, unlocked sums correctly."""
        qty = Decimal("0.5")
        price = Decimal("63000.00")
        orders = [
            _make_order_mock(
                order_type="limit",
                side="buy",
                status="pending",
                quantity=qty,
                price=price,
                executed_price=None,
            )
            for _ in range(3)
        ]
        mock_order_repo.list_open_by_account = AsyncMock(return_value=orders)
        mock_order_engine.cancel_all_orders = AsyncMock(return_value=3)

        client = _build_client(order_repo=mock_order_repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, "/api/v1/trade/orders/open")

        body = resp.json()
        assert body["cancelled_count"] == 3
        per_order_unlocked = qty * price + qty * price * Decimal("0.001")
        expected_total = per_order_unlocked * 3
        assert Decimal(body["total_unlocked"]) == expected_total

    def test_cancel_all_total_unlocked_is_string(
        self, mock_order_repo: AsyncMock, mock_order_engine: AsyncMock
    ) -> None:
        """``total_unlocked`` is serialized as a string."""
        mock_order_repo.list_open_by_account = AsyncMock(return_value=[])
        mock_order_engine.cancel_all_orders = AsyncMock(return_value=0)

        client = _build_client(order_repo=mock_order_repo, order_engine=mock_order_engine)
        resp = _authed_delete(client, "/api/v1/trade/orders/open")

        assert isinstance(resp.json()["total_unlocked"], str)

    def test_cancel_all_no_auth_returns_401(self) -> None:
        """Unauthenticated request → HTTP 401."""
        client = _build_client()
        resp = client.delete("/api/v1/trade/orders/open")
        assert resp.status_code == 401


# ===========================================================================
# GET /api/v1/trade/history — trade execution history
# ===========================================================================


class TestTradeHistory:
    """Tests for ``GET /api/v1/trade/history``."""

    def test_history_returns_200(self, mock_trade_repo: AsyncMock) -> None:
        """Happy path: returns HTTP 200 with trades list."""
        mock_trade_repo.list_by_account = AsyncMock(return_value=[_make_trade_mock()])

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history")

        assert resp.status_code == 200

    def test_history_response_has_required_fields(self, mock_trade_repo: AsyncMock) -> None:
        """Response body includes ``trades``, ``total``, ``limit``, ``offset``."""
        mock_trade_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history")

        body = resp.json()
        for field in ("trades", "total", "limit", "offset"):
            assert field in body, f"Missing field: {field}"

    def test_history_trade_item_has_required_fields(self, mock_trade_repo: AsyncMock) -> None:
        """Each trade item includes all expected fields."""
        trade = _make_trade_mock()
        mock_trade_repo.list_by_account = AsyncMock(return_value=[trade])

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history")

        item = resp.json()["trades"][0]
        for field in (
            "trade_id",
            "order_id",
            "symbol",
            "side",
            "quantity",
            "price",
            "fee",
            "total",
            "executed_at",
        ):
            assert field in item, f"Missing field: {field}"

    def test_history_decimal_fields_are_strings(self, mock_trade_repo: AsyncMock) -> None:
        """All Decimal fields in trade items are serialized as strings."""
        trade = _make_trade_mock()
        mock_trade_repo.list_by_account = AsyncMock(return_value=[trade])

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history")

        item = resp.json()["trades"][0]
        for field in ("quantity", "price", "fee", "total"):
            assert isinstance(item[field], str), f"Field {field!r} is not a string"

    def test_history_empty_returns_200(self, mock_trade_repo: AsyncMock) -> None:
        """No trade history → 200 with empty list and ``total=0``."""
        mock_trade_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history")

        body = resp.json()
        assert body["trades"] == []
        assert body["total"] == 0

    def test_history_total_matches_list_length(self, mock_trade_repo: AsyncMock) -> None:
        """``total`` equals the number of trades returned."""
        trades = [_make_trade_mock() for _ in range(4)]
        mock_trade_repo.list_by_account = AsyncMock(return_value=trades)

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history")

        body = resp.json()
        assert body["total"] == 4
        assert len(body["trades"]) == 4

    def test_history_filter_by_symbol(self, mock_trade_repo: AsyncMock) -> None:
        """``?symbol=BTCUSDT`` is forwarded to the repo (uppercased)."""
        mock_trade_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history?symbol=btcusdt")

        assert resp.status_code == 200
        call_kwargs = mock_trade_repo.list_by_account.call_args.kwargs
        assert call_kwargs.get("symbol") == "BTCUSDT"

    def test_history_filter_by_side_buy(self, mock_trade_repo: AsyncMock) -> None:
        """``?side=buy`` is forwarded to the repo."""
        mock_trade_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history?side=buy")

        assert resp.status_code == 200
        call_kwargs = mock_trade_repo.list_by_account.call_args.kwargs
        assert call_kwargs.get("side") == "buy"

    def test_history_filter_by_side_sell(self, mock_trade_repo: AsyncMock) -> None:
        """``?side=sell`` is forwarded to the repo."""
        mock_trade_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history?side=sell")

        assert resp.status_code == 200
        call_kwargs = mock_trade_repo.list_by_account.call_args.kwargs
        assert call_kwargs.get("side") == "sell"

    def test_history_default_limit_is_50(self, mock_trade_repo: AsyncMock) -> None:
        """Default ``limit=50`` is reflected in response."""
        mock_trade_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history")

        assert resp.json()["limit"] == 50

    def test_history_custom_limit(self, mock_trade_repo: AsyncMock) -> None:
        """Custom ``limit=20`` is accepted and reflected in response."""
        mock_trade_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history?limit=20")

        assert resp.json()["limit"] == 20

    def test_history_limit_too_high_returns_422(self, mock_trade_repo: AsyncMock) -> None:
        """``limit`` > 500 → HTTP 422."""
        mock_trade_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history?limit=9999")

        assert resp.status_code == 422

    def test_history_negative_offset_returns_422(self, mock_trade_repo: AsyncMock) -> None:
        """Negative ``offset`` → HTTP 422."""
        mock_trade_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history?offset=-5")

        assert resp.status_code == 422

    def test_history_pagination_offset(self, mock_trade_repo: AsyncMock) -> None:
        """Custom ``offset=100`` is reflected in response."""
        mock_trade_repo.list_by_account = AsyncMock(return_value=[])

        client = _build_client(trade_repo=mock_trade_repo)
        resp = _authed_get(client, "/api/v1/trade/history?offset=100")

        assert resp.json()["offset"] == 100

    def test_history_no_auth_returns_401(self) -> None:
        """Unauthenticated request → HTTP 401."""
        client = _build_client()
        resp = client.get("/api/v1/trade/history")
        assert resp.status_code == 401
