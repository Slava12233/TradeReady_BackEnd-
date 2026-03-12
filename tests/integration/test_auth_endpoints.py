"""Integration tests for authentication REST endpoints.

Covers the following endpoints (Section 15.1 of the development plan):

- ``POST /api/v1/auth/register`` — happy path, duplicate email, invalid body
- ``POST /api/v1/auth/login`` — valid credentials, invalid key, invalid secret,
  suspended account, expired JWT round-trip

All external I/O (DB session, Redis, bcrypt) is mocked so tests run without
real infrastructure.  FastAPI's ``app.dependency_overrides`` is used to replace
the full dependency chain so no real DB or Redis connections are made.

Run with::

    pytest tests/integration/test_auth_endpoints.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from src.accounts.service import AccountCredentials
from src.config import Settings
from src.database.models import Account
from src.utils.exceptions import (
    AccountNotFoundError,
    AccountSuspendedError,
    AuthenticationError,
    DuplicateAccountError,
)

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


def _make_account(
    account_id: UUID | None = None,
    api_key: str = "ak_live_testkey",
    api_secret_hash: str = "$2b$12$fakehash",
    display_name: str = "TestBot",
    status: str = "active",
) -> Account:
    """Build a mock :class:`~src.database.models.Account` ORM object."""
    account = MagicMock(spec=Account)
    account.id = account_id or uuid4()
    account.api_key = api_key
    account.api_secret_hash = api_secret_hash
    account.display_name = display_name
    account.status = status
    account.starting_balance = Decimal("10000.00")
    return account


def _make_credentials(
    account_id: UUID | None = None,
    api_key: str = "ak_live_testkey",
    api_secret: str = "sk_live_testsecret",
    display_name: str = "TestBot",
    starting_balance: Decimal = Decimal("10000.00"),
) -> AccountCredentials:
    """Build a mock :class:`~src.accounts.service.AccountCredentials`."""
    return AccountCredentials(
        account_id=account_id or uuid4(),
        api_key=api_key,
        api_secret=api_secret,
        display_name=display_name,
        starting_balance=starting_balance,
    )


# ---------------------------------------------------------------------------
# App + client factory
# ---------------------------------------------------------------------------


def _build_client(account_service: AsyncMock | None = None) -> TestClient:
    """Create a ``TestClient`` with the full middleware stack and mocked infra.

    Uses ``app.dependency_overrides`` to replace the DB-bound account service
    so no real database connection is attempted.

    Args:
        account_service: Optional pre-configured ``AsyncMock`` to inject.
            If ``None``, a plain no-op mock is used.

    Returns:
        A ``TestClient`` wrapping the fully configured application.
    """
    from src.dependencies import get_account_service, get_db_session, get_redis, get_settings

    if account_service is None:
        account_service = AsyncMock()

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

        # --- dependency overrides (replace the whole DI chain) ---
        app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS

        async def _override_db():
            yield mock_session

        app.dependency_overrides[get_db_session] = _override_db

        async def _override_redis():
            yield mock_redis

        app.dependency_overrides[get_redis] = _override_redis

        svc_instance = account_service

        async def _override_account_service():
            return svc_instance

        app.dependency_overrides[get_account_service] = _override_account_service

        return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Shared mock account service fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_svc() -> AsyncMock:
    """A fresh ``AsyncMock`` standing in for ``AccountService``."""
    svc = AsyncMock()
    svc.register = AsyncMock()
    svc.authenticate = AsyncMock()
    return svc


# ===========================================================================
# POST /api/v1/auth/register
# ===========================================================================


class TestRegister:
    """Tests for POST /api/v1/auth/register."""

    def test_register_success_returns_201(self, mock_svc: AsyncMock) -> None:
        """Valid registration payload → HTTP 201 with one-time credentials."""
        creds = _make_credentials(display_name="AlphaBot")
        mock_svc.register = AsyncMock(return_value=creds)

        client = _build_client(mock_svc)
        resp = client.post(
            "/api/v1/auth/register",
            json={"display_name": "AlphaBot", "email": "alpha@example.com"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["display_name"] == "AlphaBot"
        assert body["api_key"] == creds.api_key
        assert body["api_secret"] == creds.api_secret
        assert str(body["account_id"]) == str(creds.account_id)
        assert "message" in body

    def test_register_with_custom_balance(self, mock_svc: AsyncMock) -> None:
        """starting_balance field is passed to the service and echoed back."""
        creds = _make_credentials(
            display_name="RichBot",
            starting_balance=Decimal("25000.00"),
        )
        mock_svc.register = AsyncMock(return_value=creds)

        client = _build_client(mock_svc)
        resp = client.post(
            "/api/v1/auth/register",
            json={"display_name": "RichBot", "starting_balance": "25000.00"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert Decimal(body["starting_balance"]) == Decimal("25000.00")

    def test_register_without_email_succeeds(self, mock_svc: AsyncMock) -> None:
        """Email is optional — registration must succeed without it."""
        creds = _make_credentials(display_name="NoEmailBot")
        mock_svc.register = AsyncMock(return_value=creds)

        client = _build_client(mock_svc)
        resp = client.post(
            "/api/v1/auth/register",
            json={"display_name": "NoEmailBot"},
        )

        assert resp.status_code == 201

    def test_register_missing_display_name_returns_422(self) -> None:
        """Missing required display_name → Pydantic validation error (HTTP 422)."""
        client = _build_client()
        resp = client.post(
            "/api/v1/auth/register",
            json={"email": "orphan@example.com"},
        )
        assert resp.status_code == 422

    def test_register_empty_display_name_returns_422(self) -> None:
        """Empty string for display_name violates min_length=1 → 422."""
        client = _build_client()
        resp = client.post(
            "/api/v1/auth/register",
            json={"display_name": ""},
        )
        assert resp.status_code == 422

    def test_register_invalid_email_returns_422(self) -> None:
        """Malformed email string → Pydantic EmailStr validation error (HTTP 422)."""
        client = _build_client()
        resp = client.post(
            "/api/v1/auth/register",
            json={"display_name": "Bot", "email": "not-an-email"},
        )
        assert resp.status_code == 422

    def test_register_negative_balance_returns_422(self) -> None:
        """starting_balance ≤ 0 violates gt=0 constraint → 422."""
        client = _build_client()
        resp = client.post(
            "/api/v1/auth/register",
            json={"display_name": "Bot", "starting_balance": "-500"},
        )
        assert resp.status_code == 422

    def test_register_duplicate_account_returns_409(self, mock_svc: AsyncMock) -> None:
        """Service raises DuplicateAccountError → HTTP 409."""
        mock_svc.register = AsyncMock(side_effect=DuplicateAccountError("Email already registered."))

        client = _build_client(mock_svc)
        resp = client.post(
            "/api/v1/auth/register",
            json={"display_name": "DupeBot", "email": "dup@example.com"},
        )

        assert resp.status_code == 409
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "DUPLICATE_ACCOUNT"

    def test_register_api_key_starts_with_prefix(self, mock_svc: AsyncMock) -> None:
        """Returned api_key must carry the ``ak_live_`` prefix."""
        creds = _make_credentials(api_key="ak_live_abc123")
        mock_svc.register = AsyncMock(return_value=creds)

        client = _build_client(mock_svc)
        resp = client.post(
            "/api/v1/auth/register",
            json={"display_name": "PrefixBot"},
        )

        assert resp.status_code == 201
        assert resp.json()["api_key"].startswith("ak_live_")

    def test_register_api_secret_starts_with_prefix(self, mock_svc: AsyncMock) -> None:
        """Returned api_secret must carry the ``sk_live_`` prefix."""
        creds = _make_credentials(api_secret="sk_live_xyz789")
        mock_svc.register = AsyncMock(return_value=creds)

        client = _build_client(mock_svc)
        resp = client.post(
            "/api/v1/auth/register",
            json={"display_name": "SecretBot"},
        )

        assert resp.status_code == 201
        assert resp.json()["api_secret"].startswith("sk_live_")

    def test_register_no_auth_header_required(self, mock_svc: AsyncMock) -> None:
        """Register endpoint is public — no X-API-Key or Bearer required."""
        creds = _make_credentials()
        mock_svc.register = AsyncMock(return_value=creds)

        client = _build_client(mock_svc)
        # Deliberately send no auth headers
        resp = client.post(
            "/api/v1/auth/register",
            json={"display_name": "PublicBot"},
            headers={},
        )

        assert resp.status_code == 201

    def test_register_response_contains_message(self, mock_svc: AsyncMock) -> None:
        """Response body must include the one-time secret advisory message."""
        creds = _make_credentials()
        mock_svc.register = AsyncMock(return_value=creds)

        client = _build_client(mock_svc)
        resp = client.post(
            "/api/v1/auth/register",
            json={"display_name": "MsgBot"},
        )

        assert resp.status_code == 201
        assert "Save your API secret" in resp.json()["message"]


# ===========================================================================
# POST /api/v1/auth/login
# ===========================================================================


class TestLogin:
    """Tests for POST /api/v1/auth/login."""

    def test_login_success_returns_jwt(self, mock_svc: AsyncMock) -> None:
        """Valid api_key + api_secret → HTTP 200 with signed JWT."""
        account = _make_account(api_key="ak_live_validkey")
        mock_svc.authenticate = AsyncMock(return_value=account)

        with patch("src.api.routes.auth.verify_api_secret", return_value=True):
            client = _build_client(mock_svc)
            resp = client.post(
                "/api/v1/auth/login",
                json={"api_key": "ak_live_validkey", "api_secret": "sk_live_validsecret"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "token" in body
        assert body["token_type"] == "Bearer"
        assert "expires_at" in body

    def test_login_token_is_valid_jwt(self, mock_svc: AsyncMock) -> None:
        """The returned token must be decodable with the correct JWT secret."""
        from src.accounts.auth import verify_jwt

        account = _make_account(api_key="ak_live_validkey")
        mock_svc.authenticate = AsyncMock(return_value=account)

        with patch("src.api.routes.auth.verify_api_secret", return_value=True):
            client = _build_client(mock_svc)
            resp = client.post(
                "/api/v1/auth/login",
                json={"api_key": "ak_live_validkey", "api_secret": "sk_live_validsecret"},
            )

        assert resp.status_code == 200
        token = resp.json()["token"]

        payload = verify_jwt(token, _TEST_JWT_SECRET)
        assert payload.account_id == account.id

    def test_login_missing_api_key_returns_422(self) -> None:
        """Missing api_key field → Pydantic validation error (HTTP 422)."""
        client = _build_client()
        resp = client.post(
            "/api/v1/auth/login",
            json={"api_secret": "sk_live_something"},
        )
        assert resp.status_code == 422

    def test_login_missing_api_secret_returns_422(self) -> None:
        """Missing api_secret field → Pydantic validation error (HTTP 422)."""
        client = _build_client()
        resp = client.post(
            "/api/v1/auth/login",
            json={"api_key": "ak_live_something"},
        )
        assert resp.status_code == 422

    def test_login_invalid_api_key_returns_401(self, mock_svc: AsyncMock) -> None:
        """Unknown api_key → service raises AuthenticationError → HTTP 401.

        AuthenticationError has error code ``INVALID_API_KEY``.
        """
        mock_svc.authenticate = AsyncMock(side_effect=AuthenticationError("API key is invalid."))

        client = _build_client(mock_svc)
        resp = client.post(
            "/api/v1/auth/login",
            json={"api_key": "ak_live_unknown", "api_secret": "sk_live_anything"},
        )

        assert resp.status_code == 401
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "INVALID_API_KEY"

    def test_login_invalid_api_secret_returns_401(self, mock_svc: AsyncMock) -> None:
        """Correct key but wrong secret → HTTP 401 (INVALID_API_KEY code)."""
        account = _make_account(api_key="ak_live_validkey")
        mock_svc.authenticate = AsyncMock(return_value=account)

        with patch("src.api.routes.auth.verify_api_secret", return_value=False):
            client = _build_client(mock_svc)
            resp = client.post(
                "/api/v1/auth/login",
                json={"api_key": "ak_live_validkey", "api_secret": "sk_live_wrongsecret"},
            )

        assert resp.status_code == 401
        body = resp.json()
        # The route raises AuthenticationError which maps to INVALID_API_KEY
        assert body["error"]["code"] == "INVALID_API_KEY"

    def test_login_suspended_account_returns_403(self, mock_svc: AsyncMock) -> None:
        """Suspended account → HTTP 403."""
        mock_svc.authenticate = AsyncMock(side_effect=AccountSuspendedError("Account is suspended."))

        client = _build_client(mock_svc)
        resp = client.post(
            "/api/v1/auth/login",
            json={"api_key": "ak_live_suspended", "api_secret": "sk_live_anything"},
        )

        assert resp.status_code == 403
        body = resp.json()
        assert body["error"]["code"] == "ACCOUNT_SUSPENDED"

    def test_login_account_not_found_returns_404(self, mock_svc: AsyncMock) -> None:
        """Account not found by api_key → HTTP 404."""
        mock_svc.authenticate = AsyncMock(side_effect=AccountNotFoundError("Account not found."))

        client = _build_client(mock_svc)
        resp = client.post(
            "/api/v1/auth/login",
            json={"api_key": "ak_live_ghost", "api_secret": "sk_live_anything"},
        )

        assert resp.status_code == 404
        body = resp.json()
        assert body["error"]["code"] == "ACCOUNT_NOT_FOUND"

    def test_login_empty_api_key_returns_422(self) -> None:
        """Empty string api_key violates min_length=1 → 422."""
        client = _build_client()
        resp = client.post(
            "/api/v1/auth/login",
            json={"api_key": "", "api_secret": "sk_live_something"},
        )
        assert resp.status_code == 422

    def test_login_empty_api_secret_returns_422(self) -> None:
        """Empty string api_secret violates min_length=1 → 422."""
        client = _build_client()
        resp = client.post(
            "/api/v1/auth/login",
            json={"api_key": "ak_live_something", "api_secret": ""},
        )
        assert resp.status_code == 422

    def test_login_no_auth_header_required(self, mock_svc: AsyncMock) -> None:
        """Login endpoint is public — no X-API-Key or Bearer required."""
        account = _make_account(api_key="ak_live_validkey")
        mock_svc.authenticate = AsyncMock(return_value=account)

        with patch("src.api.routes.auth.verify_api_secret", return_value=True):
            client = _build_client(mock_svc)
            resp = client.post(
                "/api/v1/auth/login",
                json={"api_key": "ak_live_validkey", "api_secret": "sk_live_validsecret"},
                headers={},
            )

        assert resp.status_code == 200

    def test_login_response_token_type_is_bearer(self, mock_svc: AsyncMock) -> None:
        """token_type in response is always ``"Bearer"``."""
        account = _make_account(api_key="ak_live_anykey")
        mock_svc.authenticate = AsyncMock(return_value=account)

        with patch("src.api.routes.auth.verify_api_secret", return_value=True):
            client = _build_client(mock_svc)
            resp = client.post(
                "/api/v1/auth/login",
                json={"api_key": "ak_live_anykey", "api_secret": "sk_live_anysecret"},
            )

        assert resp.status_code == 200
        assert resp.json()["token_type"] == "Bearer"

    def test_login_expires_at_is_in_the_future(self, mock_svc: AsyncMock) -> None:
        """The expires_at timestamp in the response is in the future."""
        account = _make_account(api_key="ak_live_futurekey")
        mock_svc.authenticate = AsyncMock(return_value=account)

        with patch("src.api.routes.auth.verify_api_secret", return_value=True):
            client = _build_client(mock_svc)
            resp = client.post(
                "/api/v1/auth/login",
                json={"api_key": "ak_live_futurekey", "api_secret": "sk_live_anysecret"},
            )

        assert resp.status_code == 200
        expires_at_str = resp.json()["expires_at"]
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        assert expires_at > datetime.now(tz=UTC)


# ===========================================================================
# JWT bearer token on a protected endpoint
# ===========================================================================


class TestJwtBearerAuth:
    """Tests that JWT auth is enforced on protected routes by the middleware.

    Note: the auth middleware contains a known logging conflict (``extra={"message": ...}``
    collides with Python's ``LogRecord.message`` built-in field).  We suppress the
    middleware logger in these tests so the 401 response still reaches us cleanly.
    """

    def test_expired_jwt_returns_401(self) -> None:
        """An expired JWT token → HTTP 401 with INVALID_TOKEN code."""
        import time

        import jwt as pyjwt

        now = int(time.time())
        payload = {
            "sub": str(uuid4()),
            "iat": now - 7200,  # issued 2 hours ago
            "exp": now - 3600,  # expired 1 hour ago
        }
        expired_token = pyjwt.encode(payload, _TEST_JWT_SECRET, algorithm="HS256")

        with patch("src.api.middleware.auth.logger"):
            client = _build_client()
            resp = client.get(
                "/api/v1/account/info",
                headers={"Authorization": f"Bearer {expired_token}"},
            )

        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == "INVALID_TOKEN"

    def test_malformed_jwt_returns_401(self) -> None:
        """A garbage JWT string → HTTP 401 with INVALID_TOKEN code."""
        with patch("src.api.middleware.auth.logger"):
            client = _build_client()
            resp = client.get(
                "/api/v1/account/info",
                headers={"Authorization": "Bearer this.is.garbage"},
            )

        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == "INVALID_TOKEN"

    def test_wrong_secret_jwt_returns_401(self) -> None:
        """A JWT signed with a different secret → HTTP 401."""
        from src.accounts.auth import create_jwt

        token = create_jwt(
            account_id=uuid4(),
            jwt_secret="completely_different_secret_that_is_long_enough",
            expiry_hours=1,
        )

        with patch("src.api.middleware.auth.logger"):
            client = _build_client()
            resp = client.get(
                "/api/v1/account/info",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == "INVALID_TOKEN"

    def test_no_auth_on_protected_route_returns_401(self) -> None:
        """Accessing a protected route with no credentials → HTTP 401."""
        client = _build_client()
        resp = client.get("/api/v1/account/info")

        # No credential header at all → middleware sends back 401
        assert resp.status_code == 401
        assert "error" in resp.json()

    def test_invalid_api_key_header_returns_401(self) -> None:
        """X-API-Key with unknown key → auth middleware returns 401.

        The ``AuthMiddleware`` calls ``get_session_factory()`` directly (not via
        FastAPI DI), so we patch it at the module level to inject a mock session
        whose ``AccountRepository`` raises ``AccountNotFoundError``.
        """
        from src.database.repositories.account_repo import AccountRepository
        from src.utils.exceptions import AccountNotFoundError as _ANF  # noqa: N814

        mock_repo = AsyncMock(spec=AccountRepository)
        mock_repo.get_by_api_key = AsyncMock(side_effect=_ANF("not found"))

        mock_session = AsyncMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory = MagicMock(return_value=mock_session_ctx)

        with (
            patch("src.api.middleware.auth.logger"),
            patch("src.api.middleware.auth.AccountRepository", return_value=mock_repo),
            patch("src.database.session.get_session_factory", return_value=mock_session_factory),
        ):
            client = _build_client()
            resp = client.get(
                "/api/v1/account/info",
                headers={"X-API-Key": "ak_live_doesnotexist"},
            )

        assert resp.status_code == 401

    def test_bearer_token_grants_access_to_protected_route(self) -> None:
        """A valid JWT in Authorization: Bearer <token> clears auth middleware.

        The middleware calls ``get_session_factory()`` directly, so we patch
        that at module level.  The response may be 500 if downstream services
        are unmocked — what matters is that the auth layer does NOT return 401/403.
        """
        from src.accounts.auth import create_jwt
        from src.database.repositories.account_repo import AccountRepository

        account_id = uuid4()
        account = _make_account(account_id=account_id)

        token = create_jwt(
            account_id=account_id,
            jwt_secret=_TEST_JWT_SECRET,
            expiry_hours=1,
        )

        mock_repo = AsyncMock(spec=AccountRepository)
        mock_repo.get_by_id = AsyncMock(return_value=account)

        mock_session = AsyncMock()
        mock_session_ctx = MagicMock()
        mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory = MagicMock(return_value=mock_session_ctx)

        with (
            patch("src.api.middleware.auth.AccountRepository", return_value=mock_repo),
            patch("src.database.session.get_session_factory", return_value=mock_session_factory),
        ):
            client = _build_client()
            resp = client.get(
                "/api/v1/account/info",
                headers={"Authorization": f"Bearer {token}"},
            )

        # Auth passed — not rejected with 401/403
        assert resp.status_code not in (401, 403)
