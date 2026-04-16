"""Integration tests for the Redis sliding-window rate limiter middleware.

Covers the behaviour defined in Phase 3 Step 8 of the development plan:

- **Three tiers**: general (600/min), orders (100/min), market_data (1200/min)
- **Exceeded limit** → HTTP 429 with ``RATE_LIMIT_EXCEEDED`` error code
- **Rate-limit headers** present on every guarded response
- **Retry-After** header present on every 429 response
- **Public paths** bypass the limiter entirely
- **Unauthenticated requests** bypass the limiter (handled by auth middleware)
- **Redis errors** fail open (request allowed through)
- **Counter increments** per-account, per-group, per-minute-bucket
- **Window resets** — counter advances and remaining decrements correctly

Middleware execution order: ``LoggingMiddleware → AuthMiddleware →
RateLimitMiddleware → route``.  Auth runs before the rate limiter so that
``request.state.account`` is already populated when the rate limit check fires.
All external I/O (DB session, Redis) is mocked so tests run without real
infrastructure.

Run with::

    pytest tests/integration/test_rate_limiting.py -v
"""

from __future__ import annotations

from decimal import Decimal
import time
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from src.accounts.auth import create_jwt
from src.config import Settings
from src.database.models import Account
import src.database.session  # noqa: F401 — ensures submodule is importable by patch()

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

# Rate-limit tier limits (must match src/api/middleware/rate_limit.py _TIERS)
_LIMIT_ORDERS = 100
_LIMIT_MARKET_DATA = 1200
_LIMIT_GENERAL = 600

# ---------------------------------------------------------------------------
# Helpers — account and auth
# ---------------------------------------------------------------------------


def _make_account(api_key: str = "ak_live_testkey") -> MagicMock:
    """Build a mock :class:`~src.database.models.Account` ORM object."""
    account = MagicMock(spec=Account)
    account.id = uuid4()
    account.api_key = api_key
    account.api_secret_hash = "$2b$12$fakehash"
    account.display_name = "RateLimitBot"
    account.status = "active"
    account.starting_balance = Decimal("10000.00")
    return account


def _make_redis_mock(incr_value: int = 1) -> AsyncMock:
    """Build a Redis ``AsyncMock`` that returns *incr_value* from ``incr()``.

    Args:
        incr_value: The integer counter value that ``redis.incr()`` should
            return.  Set to ``limit + 1`` to trigger a 429 response.

    Returns:
        A configured ``AsyncMock`` mimicking a Redis client.
    """
    mock = AsyncMock()
    mock.incr = AsyncMock(return_value=incr_value)
    mock.expire = AsyncMock(return_value=True)
    mock.get = AsyncMock(return_value=None)
    mock.hget = AsyncMock(return_value=None)
    mock.hset = AsyncMock(return_value=1)
    mock.ttl = AsyncMock(return_value=60)

    mock_pipe = AsyncMock()
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)
    mock_pipe.incr = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[incr_value, 60])
    mock.pipeline = MagicMock(return_value=mock_pipe)
    return mock


def _build_client(mock_redis: AsyncMock | None = None) -> TestClient:
    """Create a ``TestClient`` with the full middleware stack and a mock Redis.

    Injects *mock_redis* into both ``app.state.redis`` (used by
    ``RateLimitMiddleware``) and FastAPI's DI system.

    Args:
        mock_redis: Optional pre-configured ``AsyncMock`` to use as the Redis
            client.  If ``None``, a default mock that never blocks is used.

    Returns:
        A ``TestClient`` wrapping the fully configured application.
    """
    from src.dependencies import get_db_session, get_redis, get_settings

    if mock_redis is None:
        mock_redis = _make_redis_mock(incr_value=1)

    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

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

        app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS

        async def _override_db():
            yield mock_session

        app.dependency_overrides[get_db_session] = _override_db

        async def _override_redis():
            yield mock_redis

        app.dependency_overrides[get_redis] = _override_redis

        # Inject the mock Redis into app state so RateLimitMiddleware can
        # access it via request.app.state.redis
        app.state.redis = mock_redis

        return TestClient(app, raise_server_exceptions=False)


def _auth_context_patches(account: MagicMock) -> tuple[AsyncMock, MagicMock, list]:
    """Build auth middleware patches that resolve *account* without a real DB.

    ``AuthMiddleware`` directly calls ``get_session_factory()`` and
    ``AccountRepository``, bypassing FastAPI's DI system, so we patch at the
    module level.

    Args:
        account: The mock account object to return from the repository.

    Returns:
        Tuple of ``(mock_repo, mock_session_factory, list_of_patch_objects)``.
    """
    mock_repo = AsyncMock()
    mock_repo.get_by_id = AsyncMock(return_value=account)
    mock_repo.get_by_api_key = AsyncMock(return_value=account)

    mock_session = AsyncMock()
    mock_session_ctx = MagicMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session_factory = MagicMock(return_value=mock_session_ctx)

    patches = [
        patch("src.api.middleware.auth.logger"),
        patch("src.api.middleware.auth.get_settings", return_value=_TEST_SETTINGS),
        patch("src.api.middleware.auth.AccountRepository", return_value=mock_repo),
        patch("src.database.session.get_session_factory", return_value=mock_session_factory),
    ]
    return mock_repo, mock_session_factory, patches


def _bearer_headers(account: MagicMock) -> dict[str, str]:
    """Return ``Authorization: Bearer <token>`` headers for *account*."""
    token = create_jwt(
        account_id=account.id,
        jwt_secret=_TEST_SETTINGS.jwt_secret,
        expiry_hours=1,
    )
    return {"Authorization": f"Bearer {token}"}


def _do_authed_get(
    client: TestClient,
    path: str,
    account: MagicMock | None = None,
    extra_headers: dict[str, str] | None = None,
) -> object:
    """Issue an authenticated GET through the full middleware stack.

    Args:
        client:        The ``TestClient`` wrapping the app.
        path:          Request path.
        account:       Mock account for auth middleware.  Created if ``None``.
        extra_headers: Additional headers to merge into the auth headers.

    Returns:
        The ``Response`` object from the test client.
    """
    if account is None:
        account = _make_account()
    _, _, auth_patches = _auth_context_patches(account)
    headers = {**_bearer_headers(account), **(extra_headers or {})}
    with (
        auth_patches[0],
        auth_patches[1],
        auth_patches[2],
        auth_patches[3],
    ):
        return client.get(path, headers=headers)


# ===========================================================================
# Unit tests for _resolve_tier and _is_public_path helpers
# ===========================================================================


class TestResolveTier:
    """Unit tests for the ``_resolve_tier()`` helper in the middleware module."""

    def test_trade_path_resolves_to_orders_tier(self) -> None:
        """``/api/v1/trade/`` maps to the ``orders`` tier (limit 100/min)."""
        from src.api.middleware.rate_limit import _resolve_tier

        group, limit = _resolve_tier("/api/v1/trade/order")
        assert group == "orders"
        assert limit == _LIMIT_ORDERS

    def test_market_path_resolves_to_market_data_tier(self) -> None:
        """``/api/v1/market/`` maps to the ``market_data`` tier (limit 1200/min)."""
        from src.api.middleware.rate_limit import _resolve_tier

        group, limit = _resolve_tier("/api/v1/market/price/BTCUSDT")
        assert group == "market_data"
        assert limit == _LIMIT_MARKET_DATA

    def test_account_path_resolves_to_general_tier(self) -> None:
        """``/api/v1/account/`` maps to the ``general`` tier (limit 600/min)."""
        from src.api.middleware.rate_limit import _resolve_tier

        group, limit = _resolve_tier("/api/v1/account/info")
        assert group == "general"
        assert limit == _LIMIT_GENERAL

    def test_analytics_path_resolves_to_general_tier(self) -> None:
        """``/api/v1/analytics/`` maps to the ``general`` tier."""
        from src.api.middleware.rate_limit import _resolve_tier

        group, limit = _resolve_tier("/api/v1/analytics/performance")
        assert group == "general"
        assert limit == _LIMIT_GENERAL

    def test_unknown_path_resolves_to_general_tier(self) -> None:
        """Any unmatched path falls back to the ``general`` tier."""
        from src.api.middleware.rate_limit import _resolve_tier

        group, limit = _resolve_tier("/api/v2/something")
        assert group == "general"
        assert limit == _LIMIT_GENERAL

    def test_orders_path_prefix_matched_before_general(self) -> None:
        """``/api/v1/trade/orders/open`` must hit the orders tier, not general."""
        from src.api.middleware.rate_limit import _resolve_tier

        group, limit = _resolve_tier("/api/v1/trade/orders/open")
        assert group == "orders"
        assert limit == _LIMIT_ORDERS


# ===========================================================================
# Unit tests for _is_public_path helper
# ===========================================================================


class TestIsPublicPath:
    """Unit tests for the ``_is_public_path()`` helper."""

    def test_register_not_in_public_bypass(self) -> None:
        """Auth paths now use IP-based rate limiting; they are NOT in the public bypass list.

        The rate-limit middleware routes auth endpoints through ``_enforce_auth_rate_limit``
        instead of the public bypass. ``_is_public_path`` correctly returns False for them.
        """
        from src.api.middleware.rate_limit import _is_public_path

        assert _is_public_path("/api/v1/auth/register") is False

    def test_login_not_in_public_bypass(self) -> None:
        """Auth paths use IP-based rate limiting; ``_is_public_path`` returns False."""
        from src.api.middleware.rate_limit import _is_public_path

        assert _is_public_path("/api/v1/auth/login") is False

    def test_health_is_public(self) -> None:
        from src.api.middleware.rate_limit import _is_public_path

        assert _is_public_path("/health") is True

    def test_docs_is_public(self) -> None:
        from src.api.middleware.rate_limit import _is_public_path

        assert _is_public_path("/docs") is True

    def test_redoc_is_public(self) -> None:
        from src.api.middleware.rate_limit import _is_public_path

        assert _is_public_path("/redoc") is True

    def test_openapi_json_is_public(self) -> None:
        from src.api.middleware.rate_limit import _is_public_path

        assert _is_public_path("/openapi.json") is True

    def test_metrics_is_public(self) -> None:
        from src.api.middleware.rate_limit import _is_public_path

        assert _is_public_path("/metrics") is True

    def test_trade_path_is_not_public(self) -> None:
        from src.api.middleware.rate_limit import _is_public_path

        assert _is_public_path("/api/v1/trade/order") is False

    def test_account_path_is_not_public(self) -> None:
        from src.api.middleware.rate_limit import _is_public_path

        assert _is_public_path("/api/v1/account/info") is False


# ===========================================================================
# Unit tests for _redis_key helper
# ===========================================================================


class TestRedisKey:
    """Unit tests for ``_redis_key()`` helper."""

    def test_key_format(self) -> None:
        """Redis key must follow ``rate_limit:{api_key}:{group}:{bucket}`` pattern."""
        from src.api.middleware.rate_limit import _redis_key

        key = _redis_key("ak_live_abc123", "orders", 28123456)
        assert key == "rate_limit:ak_live_abc123:orders:28123456"

    def test_key_unique_per_group(self) -> None:
        """Same api_key + bucket but different groups must produce different keys."""
        from src.api.middleware.rate_limit import _redis_key

        k1 = _redis_key("ak_live_abc123", "orders", 100)
        k2 = _redis_key("ak_live_abc123", "general", 100)
        assert k1 != k2

    def test_key_unique_per_minute_bucket(self) -> None:
        """Same api_key + group but different minute buckets → different keys."""
        from src.api.middleware.rate_limit import _redis_key

        k1 = _redis_key("ak_live_abc123", "orders", 100)
        k2 = _redis_key("ak_live_abc123", "orders", 101)
        assert k1 != k2


# ===========================================================================
# Middleware integration: 429 when limit is exceeded
# ===========================================================================


class TestRateLimitExceeded:
    """Rate limit is exceeded → 429 with proper error body and headers.

    These tests work by setting ``redis.incr()`` to return ``limit + 1``.
    Because ``AuthMiddleware`` runs before ``RateLimitMiddleware`` (outermost
    to innermost execution order after the middleware ordering fix), the account
    is on ``request.state`` when the rate limiter fires.
    """

    def _over_limit_resp(self, path: str, limit: int) -> object:
        """Issue an authenticated request to *path* with Redis counter at limit + 1."""
        account = _make_account()
        mock_redis = _make_redis_mock(incr_value=limit + 1)
        client = _build_client(mock_redis)
        return _do_authed_get(client, path, account)

    def test_exceed_general_limit_returns_429(self) -> None:
        """Exceeding the general limit (600/min) returns HTTP 429."""
        resp = self._over_limit_resp("/api/v1/account/info", _LIMIT_GENERAL)
        assert resp.status_code == 429

    def test_exceed_orders_limit_returns_429(self) -> None:
        """Exceeding the orders limit (100/min) returns HTTP 429."""
        resp = self._over_limit_resp("/api/v1/trade/orders", _LIMIT_ORDERS)
        assert resp.status_code == 429

    def test_exceed_market_data_limit_returns_429(self) -> None:
        """Exceeding the market_data limit (1200/min) returns HTTP 429."""
        resp = self._over_limit_resp("/api/v1/market/prices", _LIMIT_MARKET_DATA)
        assert resp.status_code == 429

    def test_429_error_code_is_rate_limit_exceeded(self) -> None:
        """HTTP 429 body contains ``RATE_LIMIT_EXCEEDED`` error code."""
        resp = self._over_limit_resp("/api/v1/account/info", _LIMIT_GENERAL)
        assert resp.status_code == 429
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"

    def test_429_error_body_has_message(self) -> None:
        """HTTP 429 body contains a human-readable ``message`` field."""
        resp = self._over_limit_resp("/api/v1/account/info", _LIMIT_GENERAL)
        body = resp.json()
        assert "message" in body["error"]
        assert len(body["error"]["message"]) > 0

    def test_429_error_details_contain_limit(self) -> None:
        """429 ``details`` payload includes the ``limit`` that was exceeded."""
        resp = self._over_limit_resp("/api/v1/account/info", _LIMIT_GENERAL)
        body = resp.json()
        details = body["error"].get("details", {})
        assert "limit" in details
        assert details["limit"] == _LIMIT_GENERAL

    def test_429_error_details_contain_window_seconds(self) -> None:
        """429 ``details`` payload includes ``window_seconds`` (60)."""
        resp = self._over_limit_resp("/api/v1/account/info", _LIMIT_GENERAL)
        body = resp.json()
        details = body["error"].get("details", {})
        assert "window_seconds" in details
        assert details["window_seconds"] == 60

    def test_429_includes_retry_after_header(self) -> None:
        """HTTP 429 response must carry a ``Retry-After`` header."""
        resp = self._over_limit_resp("/api/v1/account/info", _LIMIT_GENERAL)
        assert resp.status_code == 429
        assert "retry-after" in resp.headers

    def test_429_retry_after_is_non_negative_integer(self) -> None:
        """``Retry-After`` header value must be a non-negative integer."""
        resp = self._over_limit_resp("/api/v1/account/info", _LIMIT_GENERAL)
        retry_after = int(resp.headers["retry-after"])
        assert retry_after >= 0

    def test_429_includes_rate_limit_headers(self) -> None:
        """``X-RateLimit-*`` headers are also present on 429 responses."""
        resp = self._over_limit_resp("/api/v1/account/info", _LIMIT_GENERAL)
        assert resp.status_code == 429
        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers
        assert "x-ratelimit-reset" in resp.headers

    def test_429_remaining_is_zero_when_exceeded(self) -> None:
        """``X-RateLimit-Remaining`` should be 0 when the limit is exceeded."""
        resp = self._over_limit_resp("/api/v1/account/info", _LIMIT_GENERAL)
        assert resp.status_code == 429
        assert resp.headers["x-ratelimit-remaining"] == "0"

    def test_orders_429_limit_header_shows_orders_limit(self) -> None:
        """On a 429 for the orders tier, ``X-RateLimit-Limit`` is 100."""
        resp = self._over_limit_resp("/api/v1/trade/orders", _LIMIT_ORDERS)
        assert resp.status_code == 429
        assert resp.headers["x-ratelimit-limit"] == str(_LIMIT_ORDERS)

    def test_market_data_429_limit_header_shows_market_limit(self) -> None:
        """On a 429 for the market_data tier, ``X-RateLimit-Limit`` is 1200."""
        resp = self._over_limit_resp("/api/v1/market/prices", _LIMIT_MARKET_DATA)
        assert resp.status_code == 429
        assert resp.headers["x-ratelimit-limit"] == str(_LIMIT_MARKET_DATA)

    def test_analytics_429_limit_header_shows_general_limit(self) -> None:
        """On a 429 for the analytics tier, ``X-RateLimit-Limit`` is 600."""
        resp = self._over_limit_resp("/api/v1/analytics/performance", _LIMIT_GENERAL)
        assert resp.status_code == 429
        assert resp.headers["x-ratelimit-limit"] == str(_LIMIT_GENERAL)


# ===========================================================================
# Middleware integration: rate-limit headers on normal (non-429) responses
# ===========================================================================


class TestRateLimitHeaders:
    """Rate-limit response headers are injected on every guarded request.

    Uses market-data endpoints whose route logic is simple enough that the
    route completes without needing extensive DI setup.
    """

    def _normal_resp(self, incr_value: int = 5) -> object:
        """Issue a request that does NOT exceed the market_data limit."""
        account = _make_account()
        mock_redis = _make_redis_mock(incr_value=incr_value)

        # Market endpoints also need a price cache mock for some routes
        mock_redis.hget = AsyncMock(return_value=None)
        mock_redis.hgetall = AsyncMock(return_value={})
        mock_redis.hset = AsyncMock(return_value=1)

        client = _build_client(mock_redis)
        return _do_authed_get(client, "/api/v1/market/prices", account)

    def test_x_ratelimit_limit_header_present(self) -> None:
        """``X-RateLimit-Limit`` header must be present on authenticated responses."""
        resp = self._normal_resp()
        # Rate limit headers may appear on 200 OR on error responses
        # but the 429 test class covers the 429 case; here we just verify
        # the header is injected somewhere in the flow.
        # The market prices endpoint returns 200/503; in either case the header
        # should be present after the middleware injects it.
        assert "x-ratelimit-limit" in resp.headers or resp.status_code == 429

    def test_all_three_ratelimit_headers_present_on_market_route(self) -> None:
        """All three ``X-RateLimit-*`` headers appear on a market-data request."""
        account = _make_account()
        mock_redis = _make_redis_mock(incr_value=5)
        mock_redis.hgetall = AsyncMock(return_value={})
        client = _build_client(mock_redis)
        resp = _do_authed_get(client, "/api/v1/market/prices", account)

        assert "x-ratelimit-limit" in resp.headers
        assert "x-ratelimit-remaining" in resp.headers
        assert "x-ratelimit-reset" in resp.headers

    def test_x_ratelimit_limit_value_matches_market_data_tier(self) -> None:
        """``X-RateLimit-Limit`` for a market route must equal 1200."""
        account = _make_account()
        mock_redis = _make_redis_mock(incr_value=1)
        mock_redis.hgetall = AsyncMock(return_value={})
        client = _build_client(mock_redis)
        resp = _do_authed_get(client, "/api/v1/market/prices", account)

        assert resp.headers["x-ratelimit-limit"] == str(_LIMIT_MARKET_DATA)

    def test_x_ratelimit_remaining_decrements_with_count(self) -> None:
        """``X-RateLimit-Remaining`` equals ``limit - current_count``."""
        count = 10
        account = _make_account()
        mock_redis = _make_redis_mock(incr_value=count)
        mock_redis.hgetall = AsyncMock(return_value={})
        client = _build_client(mock_redis)
        resp = _do_authed_get(client, "/api/v1/market/prices", account)

        expected_remaining = _LIMIT_MARKET_DATA - count
        assert resp.headers["x-ratelimit-remaining"] == str(expected_remaining)

    def test_x_ratelimit_reset_is_integer_unix_timestamp(self) -> None:
        """``X-RateLimit-Reset`` must be a parseable integer Unix timestamp."""
        account = _make_account()
        mock_redis = _make_redis_mock(incr_value=1)
        mock_redis.hgetall = AsyncMock(return_value={})
        client = _build_client(mock_redis)

        before_ts = int(time.time())
        resp = _do_authed_get(client, "/api/v1/market/prices", account)

        reset_ts = int(resp.headers["x-ratelimit-reset"])
        # Reset timestamp should be within the next 60 seconds
        assert reset_ts >= before_ts
        assert reset_ts <= before_ts + 60 + 5  # +5s buffer for slow CI

    def test_general_tier_limit_header_value(self) -> None:
        """``X-RateLimit-Limit`` for a general-tier 429 equals 600."""
        account = _make_account()
        # Use over-limit to guarantee the header shows the general tier value
        mock_redis = _make_redis_mock(incr_value=_LIMIT_GENERAL + 1)
        client = _build_client(mock_redis)
        resp = _do_authed_get(client, "/api/v1/analytics/performance", account)

        assert resp.status_code == 429
        assert resp.headers["x-ratelimit-limit"] == str(_LIMIT_GENERAL)


# ===========================================================================
# Public-path bypass — no rate limiting on auth/health/docs/metrics
# ===========================================================================


class TestPublicPathBypass:
    """Public paths bypass the rate limiter entirely."""

    def _hit_public(self, path: str, method: str = "get") -> object:
        """Hit a public endpoint with an over-limit Redis counter.

        If rate limiting were applied the response would be 429; since the path
        is public it should pass through to the route handler.
        """
        mock_redis = _make_redis_mock(incr_value=999_999)
        client = _build_client(mock_redis)
        return getattr(client, method)(path)

    def test_register_ip_rate_limited(self) -> None:
        """POST /api/v1/auth/register uses IP-based rate limiting (3/min) not account-based.

        With a very high Redis counter the IP-based limiter returns 429 — confirming
        the auth path is rate-limited by IP rather than being completely exempt.
        """
        mock_redis = _make_redis_mock(incr_value=999_999)
        client = _build_client(mock_redis)
        resp = client.post("/api/v1/auth/register", json={})
        # Auth paths now use IP-based rate limiting (3/min for register);
        # a very high counter triggers 429 from the IP-based enforcer.
        assert resp.status_code == 429

    def test_login_ip_rate_limited(self) -> None:
        """POST /api/v1/auth/login uses IP-based rate limiting (5/min) not account-based.

        With a very high Redis counter the IP-based limiter returns 429 — confirming
        the auth path is rate-limited by IP rather than being completely exempt.
        """
        mock_redis = _make_redis_mock(incr_value=999_999)
        client = _build_client(mock_redis)
        resp = client.post("/api/v1/auth/login", json={})
        # Auth paths now use IP-based rate limiting (5/min for login);
        # a very high counter triggers 429 from the IP-based enforcer.
        assert resp.status_code == 429

    def test_register_low_count_not_rate_limited(self) -> None:
        """POST /api/v1/auth/register is NOT rate-limited when the counter is within the 3/min limit."""
        mock_redis = _make_redis_mock(incr_value=1)
        client = _build_client(mock_redis)
        resp = client.post("/api/v1/auth/register", json={})
        # 1 request well within the 3/min register limit — not 429.
        assert resp.status_code != 429

    def test_login_low_count_not_rate_limited(self) -> None:
        """POST /api/v1/auth/login is NOT rate-limited when the counter is within the 5/min limit."""
        mock_redis = _make_redis_mock(incr_value=1)
        client = _build_client(mock_redis)
        resp = client.post("/api/v1/auth/login", json={})
        # 1 request well within the 5/min login limit — not 429.
        assert resp.status_code != 429

    def test_health_not_rate_limited(self) -> None:
        """GET /health is exempt from rate limiting."""
        resp = self._hit_public("/health")
        assert resp.status_code != 429

    def test_docs_not_rate_limited(self) -> None:
        """GET /docs is exempt from rate limiting."""
        resp = self._hit_public("/docs")
        assert resp.status_code != 429

    def test_openapi_json_not_rate_limited(self) -> None:
        """GET /openapi.json is exempt from rate limiting."""
        resp = self._hit_public("/openapi.json")
        assert resp.status_code != 429

    def test_metrics_not_rate_limited(self) -> None:
        """GET /metrics is exempt from rate limiting."""
        resp = self._hit_public("/metrics")
        assert resp.status_code != 429

    def test_public_path_incr_not_called(self) -> None:
        """``redis.incr()`` must NOT be called for public-path requests."""
        mock_redis = _make_redis_mock(incr_value=1)
        client = _build_client(mock_redis)
        client.get("/health")
        mock_redis.incr.assert_not_called()


# ===========================================================================
# Unauthenticated requests bypass the limiter
# ===========================================================================


class TestUnauthenticatedBypass:
    """Unauthenticated requests are not rate-limited (auth middleware handles them)."""

    def test_unauthenticated_request_not_429(self) -> None:
        """A request with no credentials is rejected by auth (401), not rate limiter (429)."""
        mock_redis = _make_redis_mock(incr_value=999_999)
        client = _build_client(mock_redis)

        with patch("src.api.middleware.auth.logger"):
            resp = client.get("/api/v1/account/info")

        assert resp.status_code == 401
        assert resp.status_code != 429

    def test_unauthenticated_incr_not_called(self) -> None:
        """``redis.incr()`` must NOT be called when no account is on request.state.

        Since ``AuthMiddleware`` runs BEFORE ``RateLimitMiddleware``, an
        unauthenticated request triggers a 401 from auth and the rate-limit
        middleware sees ``account = None`` (or the request never reaches it).
        """
        mock_redis = _make_redis_mock(incr_value=1)
        client = _build_client(mock_redis)

        with patch("src.api.middleware.auth.logger"):
            client.get("/api/v1/account/info")

        mock_redis.incr.assert_not_called()


# ===========================================================================
# Redis fail-open: Redis errors do not block requests
# ===========================================================================


class TestRedisFailOpen:
    """A Redis error must not block requests (fail-open policy)."""

    def test_redis_error_allows_request_through(self) -> None:
        """When ``redis.incr()`` raises an exception the request is allowed through."""
        mock_redis = _make_redis_mock()
        mock_redis.incr = AsyncMock(side_effect=Exception("Redis connection refused"))
        mock_redis.hgetall = AsyncMock(return_value={})

        account = _make_account()
        client = _build_client(mock_redis)
        resp = _do_authed_get(client, "/api/v1/market/prices", account)

        # Must NOT be 429 — Redis errors fail open
        assert resp.status_code != 429

    def test_no_redis_on_app_state_allows_request_through(self) -> None:
        """If ``app.state.redis`` is not set the middleware skips rate-limiting."""
        account = _make_account()
        mock_redis = _make_redis_mock(incr_value=1)
        mock_redis.hgetall = AsyncMock(return_value={})
        client = _build_client(mock_redis)

        # Remove Redis from app state to simulate missing Redis
        del client.app.state.redis  # type: ignore[attr-defined]

        resp = _do_authed_get(client, "/api/v1/market/prices", account)

        assert resp.status_code != 429


# ===========================================================================
# Counter behaviour: TTL is set on first request, not subsequent ones
# ===========================================================================


class TestCounterTtl:
    """``redis.expire()`` is only called on the first request in a window."""

    def _run_one_request(self, incr_value: int) -> AsyncMock:
        """Run one authenticated request and return the mock Redis object."""
        account = _make_account()
        mock_redis = _make_redis_mock(incr_value=incr_value)
        mock_redis.hgetall = AsyncMock(return_value={})
        client = _build_client(mock_redis)
        _do_authed_get(client, "/api/v1/market/prices", account)
        return mock_redis

    def test_expire_called_when_incr_returns_one(self) -> None:
        """``redis.expire()`` is called exactly once when ``incr`` returns 1 (new key)."""
        mock_redis = self._run_one_request(incr_value=1)
        mock_redis.expire.assert_called_once()

    def test_expire_not_called_when_incr_returns_more_than_one(self) -> None:
        """``redis.expire()`` is NOT called when ``incr`` returns > 1 (existing key)."""
        mock_redis = self._run_one_request(incr_value=5)
        mock_redis.expire.assert_not_called()

    def test_expire_ttl_is_two_windows(self) -> None:
        """The TTL passed to ``redis.expire()`` must be 2× the window (120 seconds)."""
        mock_redis = self._run_one_request(incr_value=1)
        args = mock_redis.expire.call_args
        # expire(key, ttl_seconds) — ttl is the second positional arg
        ttl_arg = args[0][1] if args[0] else args[1].get("time", args[1].get("seconds"))
        assert ttl_arg == 120  # 2 * 60 seconds

    def test_incr_is_called_once_per_request(self) -> None:
        """``redis.incr()`` is called exactly once for each authenticated request."""
        mock_redis = self._run_one_request(incr_value=3)
        mock_redis.incr.assert_called_once()


# ===========================================================================
# Different accounts have independent counters
# ===========================================================================


class TestPerAccountIsolation:
    """Rate-limit counters are scoped to individual accounts (per api_key)."""

    def test_different_accounts_get_independent_keys(self) -> None:
        """Two accounts produce different Redis keys for the same endpoint."""
        from src.api.middleware.rate_limit import _redis_key

        key_a = _redis_key("ak_live_accountA", "general", 100)
        key_b = _redis_key("ak_live_accountB", "general", 100)
        assert key_a != key_b

    def test_over_limit_account_does_not_block_other_account(self) -> None:
        """Account A being rate-limited must not affect Account B.

        Each account uses a separate client instance with its own mock Redis
        counter so the counters are truly independent.
        """
        # Account A — over limit
        account_a = _make_account(api_key="ak_live_accountA")
        redis_a = _make_redis_mock(incr_value=_LIMIT_GENERAL + 1)
        client_a = _build_client(redis_a)

        # Account B — well within limit
        account_b = _make_account(api_key="ak_live_accountB")
        redis_b = _make_redis_mock(incr_value=1)
        redis_b.hgetall = AsyncMock(return_value={})
        client_b = _build_client(redis_b)

        resp_a = _do_authed_get(client_a, "/api/v1/account/info", account_a)
        resp_b = _do_authed_get(client_b, "/api/v1/market/prices", account_b)

        assert resp_a.status_code == 429
        assert resp_b.status_code != 429

    def test_redis_incr_key_contains_api_key(self) -> None:
        """The Redis key used for rate limiting embeds the account's api_key."""
        from src.api.middleware.rate_limit import _redis_key

        # Verify the key format embeds the api_key so per-account isolation is guaranteed
        key = _redis_key("ak_live_accountX", "general", 999)
        assert "ak_live_accountX" in key
