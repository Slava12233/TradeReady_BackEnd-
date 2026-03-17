"""Integration tests for market data REST endpoints.

Covers every endpoint defined in Section 15.2 of the development plan:

- ``GET /api/v1/market/pairs``              — list all / filter by status
- ``GET /api/v1/market/price/{symbol}``     — single price from Redis cache
- ``GET /api/v1/market/prices``             — all prices / filtered subset
- ``GET /api/v1/market/ticker/{symbol}``    — 24h rolling ticker stats
- ``GET /api/v1/market/candles/{symbol}``   — OHLCV from TimescaleDB aggregates
- ``GET /api/v1/market/trades/{symbol}``    — recent public trades
- ``GET /api/v1/market/orderbook/{symbol}`` — simulated order book snapshot

All external I/O (DB session, Redis / PriceCache) is mocked so tests run
without real infrastructure.  ``app.dependency_overrides`` replaces the full
DI chain so no real DB or Redis connections are made.

Market endpoints sit behind the ``AuthMiddleware``.  Tests authenticate via a
short-lived JWT signed with the test secret; ``AuthMiddleware``'s internal DB
calls are patched out so no real database connection is needed.

Run with::

    pytest tests/integration/test_market_endpoints.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

import pytest

from src.accounts.auth import create_jwt
from src.cache.price_cache import TickerData
from src.config import Settings
from src.database.models import Account

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

# Fixed reference datetime for deterministic assertions.
_NOW = datetime(2026, 2, 24, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Shared helpers — data builders
# ---------------------------------------------------------------------------


def _make_trading_pair_row(
    symbol: str = "BTCUSDT",
    base: str = "BTC",
    quote: str = "USDT",
    status: str = "active",
) -> MagicMock:
    """Build a mock ORM ``TradingPair`` object."""
    pair = MagicMock()
    pair.symbol = symbol
    pair.base_asset = base
    pair.quote_asset = quote
    pair.status = status
    pair.min_qty = Decimal("0.00001")
    pair.step_size = Decimal("0.00001")
    pair.min_notional = Decimal("10.00")
    return pair


def _make_tick_row(
    symbol: str = "BTCUSDT",
    price: Decimal = Decimal("64521.30"),
    quantity: Decimal = Decimal("0.012"),
    trade_id: int = 123456789,
    is_buyer_maker: bool = False,
) -> MagicMock:
    """Build a mock ORM ``Tick`` (ticks table) object."""
    tick = MagicMock()
    tick.symbol = symbol
    tick.price = price
    tick.quantity = quantity
    tick.trade_id = trade_id
    tick.is_buyer_maker = is_buyer_maker
    tick.time = _NOW
    return tick


def _make_ticker_data(
    symbol: str = "BTCUSDT",
    open_: Decimal = Decimal("63800.00"),
    high: Decimal = Decimal("65200.00"),
    low: Decimal = Decimal("63500.00"),
    close: Decimal = Decimal("64521.30"),
    volume: Decimal = Decimal("24531.456"),
    change_pct: Decimal = Decimal("1.13"),
) -> TickerData:
    """Build a ``TickerData`` instance for use as a cache mock return value."""
    return TickerData(
        symbol=symbol,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        change_pct=change_pct,
        last_update=_NOW,
    )


def _make_candle_row(
    bucket: datetime | None = None,
    open_: float = 64200.0,
    high: float = 64600.0,
    low: float = 64100.0,
    close: float = 64521.30,
    volume: float = 1234.567,
    trade_count: int = 456,
) -> MagicMock:
    """Build a mock row returned by the raw candles SQL query."""
    row = MagicMock()
    row.bucket = bucket or _NOW
    row.open = open_
    row.high = high
    row.low = low
    row.close = close
    row.volume = volume
    row.trade_count = trade_count
    return row


# ---------------------------------------------------------------------------
# Auth helpers — market endpoints sit behind the auth middleware
# ---------------------------------------------------------------------------


def _make_account_mock(account_id=None) -> MagicMock:
    """Build a mock :class:`~src.database.models.Account` for auth middleware."""
    account = MagicMock(spec=Account)
    account.id = account_id or uuid4()
    account.api_key = "ak_live_testkey"
    account.api_secret_hash = "$2b$12$fakehash"
    account.display_name = "TestBot"
    account.status = "active"
    account.starting_balance = Decimal("10000.00")
    return account


def _make_auth_context() -> tuple[dict[str, str], MagicMock, MagicMock]:
    """Return ``(headers, mock_repo, mock_session_factory)`` for auth middleware patching.

    Creates a valid short-lived JWT signed with ``_TEST_SETTINGS.jwt_secret`` and
    builds the mock infrastructure that ``AuthMiddleware`` uses to resolve the
    account from the database.

    Returns:
        A tuple of (HTTP headers dict, mock AccountRepository, mock session factory).
    """
    account_id = uuid4()
    account = _make_account_mock(account_id=account_id)

    token = create_jwt(
        account_id=account_id,
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


def _authed_get(client: TestClient, url: str, **kwargs):
    """Issue a GET request through the auth middleware using a fresh valid JWT.

    Patches ``AuthMiddleware``'s internal DB lookups so the JWT is accepted
    without a real database connection.  Also suppresses the auth middleware
    logger to avoid the ``extra={"message": ...}`` LogRecord conflict that
    causes a ``KeyError`` in structlog-based logging.

    Args:
        client: The ``TestClient`` instance.
        url:    Request path (with optional query string).
        **kwargs: Extra kwargs forwarded to ``client.get`` (e.g. ``headers``).

    Returns:
        The ``Response`` object.
    """
    headers, mock_repo, mock_session_factory = _make_auth_context()
    # Merge any caller-supplied headers (caller headers take precedence).
    merged_headers = {**headers, **kwargs.pop("headers", {})}
    with (
        patch("src.api.middleware.auth.logger"),
        patch("src.api.middleware.auth.get_settings", return_value=_TEST_SETTINGS),
        patch("src.api.middleware.auth.AccountRepository", return_value=mock_repo),
        patch("src.database.session.get_session_factory", return_value=mock_session_factory),
    ):
        return client.get(url, headers=merged_headers, **kwargs)


# ---------------------------------------------------------------------------
# App + client factory
# ---------------------------------------------------------------------------


def _build_client(
    *,
    db_session: AsyncMock | None = None,
    price_cache: AsyncMock | None = None,
) -> TestClient:
    """Create a ``TestClient`` with mocked DB session and PriceCache.

    The ``db_session`` mock is injected via the ``get_db_session`` override so
    individual tests can configure ``execute`` return values.  The
    ``price_cache`` mock is injected via ``get_price_cache``.

    Args:
        db_session:   Optional pre-configured ``AsyncMock`` for the DB session.
        price_cache:  Optional pre-configured ``AsyncMock`` for PriceCache.

    Returns:
        A ``TestClient`` wrapping the fully configured application.
    """
    from src.dependencies import (
        get_db_session,
        get_price_cache,
        get_redis,
        get_settings,
    )

    if db_session is None:
        db_session = AsyncMock()

    if price_cache is None:
        price_cache = AsyncMock()
        price_cache.get_price = AsyncMock(return_value=None)
        price_cache.get_all_prices = AsyncMock(return_value={})
        price_cache.get_ticker = AsyncMock(return_value=None)
        price_cache._redis = AsyncMock()
        price_cache._redis.hget = AsyncMock(return_value=None)

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

    _db = db_session
    _cache = price_cache

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
            yield _db

        app.dependency_overrides[get_db_session] = _override_db

        async def _override_redis():
            yield mock_redis

        app.dependency_overrides[get_redis] = _override_redis

        async def _override_price_cache():
            return _cache

        app.dependency_overrides[get_price_cache] = _override_price_cache

        return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Shared helper — mock DB with a known symbol that passes validation
# ---------------------------------------------------------------------------


def _make_db_with_symbol(symbol: str = "BTCUSDT") -> AsyncMock:
    """Return a mock DB session that reports *symbol* as a valid trading pair.

    ``scalar_one_or_none`` returns the symbol string (symbol validation passes),
    while ``fetchall`` and ``scalars().all()`` return empty results by default.
    """
    db = AsyncMock()

    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none = MagicMock(return_value=symbol)
    scalar_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
    scalar_result.fetchall = MagicMock(return_value=[])

    db.execute = AsyncMock(return_value=scalar_result)
    return db


# ===========================================================================
# GET /api/v1/market/pairs
# ===========================================================================


class TestListPairs:
    """Tests for ``GET /api/v1/market/pairs``."""

    def test_pairs_returns_200(self) -> None:
        """Happy path: returns HTTP 200 with pairs list and total count."""
        db = AsyncMock()
        pair_mock = _make_trading_pair_row()

        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[pair_mock])))
        db.execute = AsyncMock(return_value=result)

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/pairs")

        assert resp.status_code == 200
        body = resp.json()
        assert "pairs" in body
        assert "total" in body

    def test_pairs_returns_list_of_pairs(self) -> None:
        """Response body ``pairs`` is a list and count matches."""
        db = AsyncMock()
        pairs = [
            _make_trading_pair_row("BTCUSDT", "BTC", "USDT"),
            _make_trading_pair_row("ETHUSDT", "ETH", "USDT"),
        ]
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=pairs)))
        db.execute = AsyncMock(return_value=result)

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/pairs")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["pairs"]) == 2

    def test_pairs_item_has_required_fields(self) -> None:
        """Each pair item exposes all expected fields."""
        db = AsyncMock()
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[_make_trading_pair_row()])))
        db.execute = AsyncMock(return_value=result)

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/pairs")

        assert resp.status_code == 200
        pair = resp.json()["pairs"][0]
        for field in (
            "symbol",
            "base_asset",
            "quote_asset",
            "status",
            "min_qty",
            "step_size",
            "min_notional",
        ):
            assert field in pair, f"Missing field: {field}"

    def test_pairs_filter_by_status_active(self) -> None:
        """``?status=active`` query param is accepted; response is 200."""
        db = AsyncMock()
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.execute = AsyncMock(return_value=result)

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/pairs?status=active")

        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    def test_pairs_empty_list_is_valid_response(self) -> None:
        """Empty trading-pairs table → 200 with empty list and total=0."""
        db = AsyncMock()
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.execute = AsyncMock(return_value=result)

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/pairs")

        assert resp.status_code == 200
        body = resp.json()
        assert body["pairs"] == []
        assert body["total"] == 0

    def test_pairs_decimal_fields_serialized_as_strings(self) -> None:
        """``min_qty``, ``step_size``, and ``min_notional`` are JSON strings."""
        db = AsyncMock()
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[_make_trading_pair_row()])))
        db.execute = AsyncMock(return_value=result)

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/pairs")

        pair = resp.json()["pairs"][0]
        assert isinstance(pair["min_qty"], str)
        assert isinstance(pair["step_size"], str)
        assert isinstance(pair["min_notional"], str)

    def test_pairs_no_auth_returns_401(self) -> None:
        """Requesting without credentials → HTTP 401 from auth middleware."""
        db = AsyncMock()
        result = MagicMock()
        result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        db.execute = AsyncMock(return_value=result)

        client = _build_client(db_session=db)
        resp = client.get("/api/v1/market/pairs")

        assert resp.status_code == 401


# ===========================================================================
# GET /api/v1/market/price/{symbol}
# ===========================================================================


class TestGetPrice:
    """Tests for ``GET /api/v1/market/price/{symbol}``."""

    def test_price_success_returns_200(self) -> None:
        """Known symbol with price in cache → HTTP 200."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=Decimal("64521.30"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=_NOW.isoformat())

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/price/BTCUSDT")

        assert resp.status_code == 200

    def test_price_response_has_required_fields(self) -> None:
        """Response includes ``symbol``, ``price``, and ``timestamp``."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=Decimal("64521.30"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=_NOW.isoformat())

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/price/BTCUSDT")

        body = resp.json()
        assert body["symbol"] == "BTCUSDT"
        assert "price" in body
        assert "timestamp" in body

    def test_price_serialized_as_string(self) -> None:
        """``price`` field in the response is a string (not a float)."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=Decimal("64521.30000000"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/price/BTCUSDT")

        assert isinstance(resp.json()["price"], str)

    def test_price_symbol_uppercased_automatically(self) -> None:
        """Lowercase symbol in the URL is normalised to uppercase."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=Decimal("64521.30"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/price/btcusdt")

        assert resp.status_code == 200
        assert resp.json()["symbol"] == "BTCUSDT"

    def test_price_unknown_symbol_returns_400(self) -> None:
        """Unknown symbol → ``InvalidSymbolError`` → HTTP 400."""
        db = AsyncMock()
        validate_result = MagicMock()
        validate_result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=validate_result)

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/price/FAKECOIN")

        assert resp.status_code == 400
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "INVALID_SYMBOL"

    def test_price_not_in_cache_returns_503(self) -> None:
        """Valid symbol but price absent from Redis → HTTP 503."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=None)
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/price/BTCUSDT")

        assert resp.status_code == 503
        body = resp.json()
        assert body["error"]["code"] == "PRICE_NOT_AVAILABLE"

    def test_price_timestamp_falls_back_to_utc_now(self) -> None:
        """When ``prices:meta`` has no entry, timestamp is still a valid ISO string."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=Decimal("100.00"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/price/BTCUSDT")

        assert resp.status_code == 200
        ts = resp.json()["timestamp"]
        datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ===========================================================================
# GET /api/v1/market/prices
# ===========================================================================


class TestGetPrices:
    """Tests for ``GET /api/v1/market/prices``."""

    def test_prices_returns_200(self) -> None:
        """Happy path: endpoint returns 200."""
        cache = AsyncMock()
        cache.get_all_prices = AsyncMock(return_value={"BTCUSDT": Decimal("64521.30")})

        client = _build_client(price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/prices")

        assert resp.status_code == 200

    def test_prices_response_has_required_fields(self) -> None:
        """Response includes ``prices``, ``timestamp``, and ``count``."""
        cache = AsyncMock()
        cache.get_all_prices = AsyncMock(return_value={"BTCUSDT": Decimal("64521.30")})

        client = _build_client(price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/prices")

        body = resp.json()
        assert "prices" in body
        assert "timestamp" in body
        assert "count" in body

    def test_prices_count_matches_map_length(self) -> None:
        """``count`` equals the number of entries in ``prices`` dict."""
        cache = AsyncMock()
        cache.get_all_prices = AsyncMock(
            return_value={
                "BTCUSDT": Decimal("64521.30"),
                "ETHUSDT": Decimal("3421.50"),
                "SOLUSDT": Decimal("142.75"),
            }
        )

        client = _build_client(price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/prices")

        body = resp.json()
        assert body["count"] == 3
        assert len(body["prices"]) == 3

    def test_prices_values_are_strings(self) -> None:
        """All values in the ``prices`` dict must be strings."""
        cache = AsyncMock()
        cache.get_all_prices = AsyncMock(return_value={"BTCUSDT": Decimal("64521.30")})

        client = _build_client(price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/prices")

        for value in resp.json()["prices"].values():
            assert isinstance(value, str)

    def test_prices_filter_by_symbols(self) -> None:
        """``?symbols=BTCUSDT,ETHUSDT`` filters the result set."""
        cache = AsyncMock()
        cache.get_all_prices = AsyncMock(
            return_value={
                "BTCUSDT": Decimal("64521.30"),
                "ETHUSDT": Decimal("3421.50"),
                "SOLUSDT": Decimal("142.75"),
            }
        )

        client = _build_client(price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/prices?symbols=BTCUSDT,ETHUSDT")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert "BTCUSDT" in body["prices"]
        assert "ETHUSDT" in body["prices"]
        assert "SOLUSDT" not in body["prices"]

    def test_prices_filter_single_symbol(self) -> None:
        """Single symbol filter returns only that symbol."""
        cache = AsyncMock()
        cache.get_all_prices = AsyncMock(
            return_value={
                "BTCUSDT": Decimal("64521.30"),
                "ETHUSDT": Decimal("3421.50"),
            }
        )

        client = _build_client(price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/prices?symbols=ETHUSDT")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert "ETHUSDT" in body["prices"]

    def test_prices_filter_unknown_symbol_returns_empty(self) -> None:
        """Filtering for an unknown symbol → 200 with empty prices dict."""
        cache = AsyncMock()
        cache.get_all_prices = AsyncMock(return_value={"BTCUSDT": Decimal("64521.30")})

        client = _build_client(price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/prices?symbols=FAKECOIN")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["prices"] == {}

    def test_prices_empty_cache_returns_200(self) -> None:
        """Empty cache → 200 with ``count=0`` and empty ``prices`` dict."""
        cache = AsyncMock()
        cache.get_all_prices = AsyncMock(return_value={})

        client = _build_client(price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/prices")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 0
        assert body["prices"] == {}

    def test_prices_no_auth_returns_401(self) -> None:
        """Requesting without credentials → HTTP 401."""
        cache = AsyncMock()
        cache.get_all_prices = AsyncMock(return_value={})

        client = _build_client(price_cache=cache)
        resp = client.get("/api/v1/market/prices")

        assert resp.status_code == 401


# ===========================================================================
# GET /api/v1/market/ticker/{symbol}
# ===========================================================================


class TestGetTicker:
    """Tests for ``GET /api/v1/market/ticker/{symbol}``."""

    def test_ticker_success_returns_200(self) -> None:
        """Known symbol with ticker in cache → HTTP 200."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_ticker = AsyncMock(return_value=_make_ticker_data())
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/ticker/BTCUSDT")

        assert resp.status_code == 200

    def test_ticker_response_has_required_fields(self) -> None:
        """Response includes all 24h stat fields per Section 15.2."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_ticker = AsyncMock(return_value=_make_ticker_data())
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/ticker/BTCUSDT")

        body = resp.json()
        required = (
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "change",
            "change_pct",
            "trade_count",
            "timestamp",
        )
        for field in required:
            assert field in body, f"Missing field: {field}"

    def test_ticker_symbol_correct_in_response(self) -> None:
        """Symbol in response matches the queried symbol (uppercased)."""
        db = _make_db_with_symbol("ETHUSDT")

        cache = AsyncMock()
        cache.get_ticker = AsyncMock(return_value=_make_ticker_data(symbol="ETHUSDT"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/ticker/ethusdt")

        assert resp.status_code == 200
        assert resp.json()["symbol"] == "ETHUSDT"

    def test_ticker_decimal_fields_are_strings(self) -> None:
        """All price/volume decimal fields are serialised as strings."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_ticker = AsyncMock(return_value=_make_ticker_data())
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/ticker/BTCUSDT")

        body = resp.json()
        for field in ("open", "high", "low", "close", "volume", "quote_volume", "change", "change_pct"):
            assert isinstance(body[field], str), f"Field {field!r} is not a string"

    def test_ticker_change_computed_correctly(self) -> None:
        """``change`` equals ``close - open`` (computed in the route handler)."""
        db = _make_db_with_symbol("BTCUSDT")

        ticker = _make_ticker_data(
            open_=Decimal("60000.00"),
            close=Decimal("64521.30"),
        )
        cache = AsyncMock()
        cache.get_ticker = AsyncMock(return_value=ticker)
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/ticker/BTCUSDT")

        expected_change = Decimal("64521.30") - Decimal("60000.00")
        assert Decimal(resp.json()["change"]) == expected_change

    def test_ticker_unknown_symbol_returns_400(self) -> None:
        """Unknown symbol → ``InvalidSymbolError`` → HTTP 400."""
        db = AsyncMock()
        validate_result = MagicMock()
        validate_result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=validate_result)

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/ticker/FAKECOIN")

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_SYMBOL"

    def test_ticker_not_in_cache_returns_503(self) -> None:
        """Valid symbol but no ticker in Redis → HTTP 503."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_ticker = AsyncMock(return_value=None)
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/ticker/BTCUSDT")

        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "PRICE_NOT_AVAILABLE"


# ===========================================================================
# GET /api/v1/market/candles/{symbol}
# ===========================================================================


class TestGetCandles:
    """Tests for ``GET /api/v1/market/candles/{symbol}``."""

    def _db_with_candles(self, symbol: str = "BTCUSDT", rows: list | None = None) -> AsyncMock:
        """Return a mock DB session that validates *symbol* then returns candle *rows*."""
        db = AsyncMock()
        rows = rows or []

        validate_result = MagicMock()
        validate_result.scalar_one_or_none = MagicMock(return_value=symbol)

        candle_result = MagicMock()
        candle_result.fetchall = MagicMock(return_value=rows)

        db.execute = AsyncMock(side_effect=[validate_result, candle_result])
        return db

    def test_candles_success_returns_200(self) -> None:
        """Known symbol with 1h interval → HTTP 200."""
        db = self._db_with_candles(rows=[_make_candle_row()])

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/candles/BTCUSDT?interval=1h")

        assert resp.status_code == 200

    def test_candles_response_has_required_fields(self) -> None:
        """Response includes ``symbol``, ``interval``, ``candles``, and ``count``."""
        db = self._db_with_candles(rows=[_make_candle_row()])

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/candles/BTCUSDT?interval=1h")

        body = resp.json()
        for field in ("symbol", "interval", "candles", "count"):
            assert field in body, f"Missing field: {field}"

    def test_candles_all_intervals_accepted(self) -> None:
        """All four valid intervals (1m, 5m, 1h, 1d) return HTTP 200."""
        for interval in ("1m", "5m", "1h", "1d"):
            db = self._db_with_candles(rows=[])
            client = _build_client(db_session=db)
            resp = _authed_get(client, f"/api/v1/market/candles/BTCUSDT?interval={interval}")
            assert resp.status_code == 200, f"interval={interval} should return 200"

    def test_candles_invalid_interval_returns_400(self) -> None:
        """Unsupported interval string → HTTP 400 with ``INVALID_SYMBOL`` code."""
        db = self._db_with_candles(rows=[])
        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/candles/BTCUSDT?interval=4h")

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_SYMBOL"

    def test_candles_unknown_symbol_returns_400(self) -> None:
        """Unknown symbol → HTTP 400."""
        db = AsyncMock()
        validate_result = MagicMock()
        validate_result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=validate_result)

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/candles/FAKECOIN")

        assert resp.status_code == 400

    def test_candles_count_matches_rows(self) -> None:
        """``count`` equals the number of candle objects returned."""
        rows = [_make_candle_row(), _make_candle_row(), _make_candle_row()]
        db = self._db_with_candles(rows=rows)

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/candles/BTCUSDT?interval=1h&limit=3")

        body = resp.json()
        assert body["count"] == 3
        assert len(body["candles"]) == 3

    def test_candles_empty_result_returns_200(self) -> None:
        """No candles available → 200 with empty list and count=0."""
        db = self._db_with_candles(rows=[])

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/candles/BTCUSDT?interval=1d")

        assert resp.status_code == 200
        body = resp.json()
        assert body["candles"] == []
        assert body["count"] == 0

    def test_candles_decimal_fields_are_strings(self) -> None:
        """OHLCV price/volume fields in each candle are serialised as strings."""
        db = self._db_with_candles(rows=[_make_candle_row()])

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/candles/BTCUSDT?interval=1h")

        candle = resp.json()["candles"][0]
        for field in ("open", "high", "low", "close", "volume"):
            assert isinstance(candle[field], str), f"Field {field!r} is not a string"

    def test_candles_limit_query_param_accepted(self) -> None:
        """``limit`` query param in valid range (1–1000) is accepted → 200."""
        db = self._db_with_candles(rows=[])
        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/candles/BTCUSDT?interval=1h&limit=50")
        assert resp.status_code == 200

    def test_candles_limit_too_high_returns_422(self) -> None:
        """``limit`` > 1000 violates the Query constraint → HTTP 422."""
        db = self._db_with_candles(rows=[])
        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/candles/BTCUSDT?interval=1h&limit=9999")
        assert resp.status_code == 422

    def test_candles_interval_in_response_matches_request(self) -> None:
        """``interval`` field in the response matches the requested interval."""
        db = self._db_with_candles(rows=[])
        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/candles/BTCUSDT?interval=5m")
        assert resp.json()["interval"] == "5m"


# ===========================================================================
# GET /api/v1/market/trades/{symbol}
# ===========================================================================


class TestGetTrades:
    """Tests for ``GET /api/v1/market/trades/{symbol}``."""

    def _db_with_ticks(self, symbol: str = "BTCUSDT", ticks: list | None = None) -> AsyncMock:
        """Return a mock DB session that validates *symbol* then returns *ticks*."""
        db = AsyncMock()
        ticks = ticks or []

        validate_result = MagicMock()
        validate_result.scalar_one_or_none = MagicMock(return_value=symbol)

        ticks_result = MagicMock()
        ticks_result.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=ticks)))

        db.execute = AsyncMock(side_effect=[validate_result, ticks_result])
        return db

    def test_trades_success_returns_200(self) -> None:
        """Known symbol → HTTP 200."""
        db = self._db_with_ticks(ticks=[_make_tick_row()])

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/trades/BTCUSDT")

        assert resp.status_code == 200

    def test_trades_response_has_required_fields(self) -> None:
        """Response includes ``symbol`` and ``trades``."""
        db = self._db_with_ticks(ticks=[_make_tick_row()])

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/trades/BTCUSDT")

        body = resp.json()
        assert "symbol" in body
        assert "trades" in body

    def test_trades_item_has_required_fields(self) -> None:
        """Each trade item includes all expected fields."""
        db = self._db_with_ticks(ticks=[_make_tick_row()])

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/trades/BTCUSDT")

        trade = resp.json()["trades"][0]
        for field in ("trade_id", "price", "quantity", "time", "is_buyer_maker"):
            assert field in trade, f"Missing field: {field}"

    def test_trades_decimal_fields_are_strings(self) -> None:
        """``price`` and ``quantity`` in each trade are serialised as strings."""
        db = self._db_with_ticks(ticks=[_make_tick_row()])

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/trades/BTCUSDT")

        trade = resp.json()["trades"][0]
        assert isinstance(trade["price"], str)
        assert isinstance(trade["quantity"], str)

    def test_trades_empty_history_returns_200(self) -> None:
        """No tick history → 200 with empty trades list."""
        db = self._db_with_ticks(ticks=[])

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/trades/BTCUSDT")

        assert resp.status_code == 200
        assert resp.json()["trades"] == []

    def test_trades_unknown_symbol_returns_400(self) -> None:
        """Unknown symbol → HTTP 400."""
        db = AsyncMock()
        validate_result = MagicMock()
        validate_result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=validate_result)

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/trades/FAKECOIN")

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_SYMBOL"

    def test_trades_limit_accepted(self) -> None:
        """``?limit=50`` in valid range → 200."""
        db = self._db_with_ticks(ticks=[])
        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/trades/BTCUSDT?limit=50")
        assert resp.status_code == 200

    def test_trades_limit_too_high_returns_422(self) -> None:
        """``limit`` > 500 → Pydantic Query constraint → HTTP 422."""
        db = self._db_with_ticks(ticks=[])
        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/trades/BTCUSDT?limit=9999")
        assert resp.status_code == 422

    def test_trades_symbol_in_response_is_uppercased(self) -> None:
        """``symbol`` field in response is always uppercase."""
        db = self._db_with_ticks(symbol="ETHUSDT", ticks=[])
        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/trades/ethusdt")
        assert resp.json()["symbol"] == "ETHUSDT"

    def test_trades_multiple_ticks_returned(self) -> None:
        """Multiple tick rows are all returned in the trades list."""
        ticks = [_make_tick_row(trade_id=i) for i in range(1, 6)]
        db = self._db_with_ticks(ticks=ticks)
        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/trades/BTCUSDT")
        assert len(resp.json()["trades"]) == 5


# ===========================================================================
# GET /api/v1/market/orderbook/{symbol}
# ===========================================================================


class TestGetOrderbook:
    """Tests for ``GET /api/v1/market/orderbook/{symbol}``."""

    def test_orderbook_success_returns_200(self) -> None:
        """Known symbol with price in cache → HTTP 200."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=Decimal("64521.30"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/orderbook/BTCUSDT")

        assert resp.status_code == 200

    def test_orderbook_response_has_required_fields(self) -> None:
        """Response includes ``symbol``, ``bids``, ``asks``, and ``timestamp``."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=Decimal("64521.30"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/orderbook/BTCUSDT")

        body = resp.json()
        for field in ("symbol", "bids", "asks", "timestamp"):
            assert field in body, f"Missing field: {field}"

    def test_orderbook_default_depth_is_10(self) -> None:
        """Default depth=10 → 10 bid levels and 10 ask levels."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=Decimal("64521.30"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/orderbook/BTCUSDT")

        body = resp.json()
        assert len(body["bids"]) == 10
        assert len(body["asks"]) == 10

    def test_orderbook_depth_5_returns_5_levels(self) -> None:
        """``?depth=5`` → 5 bid/ask levels each."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=Decimal("64521.30"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/orderbook/BTCUSDT?depth=5")

        body = resp.json()
        assert len(body["bids"]) == 5
        assert len(body["asks"]) == 5

    def test_orderbook_depth_20_returns_20_levels(self) -> None:
        """``?depth=20`` → 20 bid/ask levels each."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=Decimal("64521.30"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/orderbook/BTCUSDT?depth=20")

        body = resp.json()
        assert len(body["bids"]) == 20
        assert len(body["asks"]) == 20

    def test_orderbook_invalid_depth_returns_400(self) -> None:
        """Unsupported depth value → ``InvalidSymbolError`` → HTTP 400."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=Decimal("64521.30"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/orderbook/BTCUSDT?depth=7")

        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "INVALID_SYMBOL"

    def test_orderbook_unknown_symbol_returns_400(self) -> None:
        """Unknown symbol → HTTP 400."""
        db = AsyncMock()
        validate_result = MagicMock()
        validate_result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=validate_result)

        client = _build_client(db_session=db)
        resp = _authed_get(client, "/api/v1/market/orderbook/FAKECOIN")

        assert resp.status_code == 400

    def test_orderbook_no_price_returns_503(self) -> None:
        """Valid symbol but no price in Redis → HTTP 503."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=None)
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/orderbook/BTCUSDT")

        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "PRICE_NOT_AVAILABLE"

    def test_orderbook_bids_ordered_highest_first(self) -> None:
        """Bids list is ordered from highest to lowest price."""
        db = _make_db_with_symbol("BTCUSDT")
        mid = Decimal("64521.30")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=mid)
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/orderbook/BTCUSDT?depth=5")

        bids = resp.json()["bids"]
        bid_prices = [Decimal(b[0]) for b in bids]
        assert bid_prices == sorted(bid_prices, reverse=True)

    def test_orderbook_asks_ordered_lowest_first(self) -> None:
        """Asks list is ordered from lowest to highest price."""
        db = _make_db_with_symbol("BTCUSDT")
        mid = Decimal("64521.30")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=mid)
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/orderbook/BTCUSDT?depth=5")

        asks = resp.json()["asks"]
        ask_prices = [Decimal(a[0]) for a in asks]
        assert ask_prices == sorted(ask_prices)

    def test_orderbook_bids_below_mid_price(self) -> None:
        """All bid prices are strictly below the mid-price."""
        db = _make_db_with_symbol("BTCUSDT")
        mid = Decimal("64521.30")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=mid)
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/orderbook/BTCUSDT?depth=5")

        for bid in resp.json()["bids"]:
            assert Decimal(bid[0]) < mid

    def test_orderbook_asks_above_mid_price(self) -> None:
        """All ask prices are strictly above the mid-price."""
        db = _make_db_with_symbol("BTCUSDT")
        mid = Decimal("64521.30")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=mid)
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/orderbook/BTCUSDT?depth=5")

        for ask in resp.json()["asks"]:
            assert Decimal(ask[0]) > mid

    def test_orderbook_level_is_two_element_list(self) -> None:
        """Each bid/ask entry is a [price, qty] two-element list of strings."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=Decimal("64521.30"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/orderbook/BTCUSDT?depth=5")

        body = resp.json()
        for side in ("bids", "asks"):
            for level in body[side]:
                assert isinstance(level, list)
                assert len(level) == 2
                assert all(isinstance(v, str) for v in level)

    def test_orderbook_symbol_uppercased_in_response(self) -> None:
        """``symbol`` field in response is uppercase regardless of URL case."""
        db = _make_db_with_symbol("BTCUSDT")

        cache = AsyncMock()
        cache.get_price = AsyncMock(return_value=Decimal("64521.30"))
        cache._redis = AsyncMock()
        cache._redis.hget = AsyncMock(return_value=None)

        client = _build_client(db_session=db, price_cache=cache)
        resp = _authed_get(client, "/api/v1/market/orderbook/btcusdt")

        assert resp.json()["symbol"] == "BTCUSDT"
