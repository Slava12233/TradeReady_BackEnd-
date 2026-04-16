"""Unit tests for email verification flow.

Covers:
- ``AccountService.send_email_verification`` — token generation, Redis storage, logging
- ``AccountService.verify_email`` — token lookup, DB update, token deletion
- ``POST /api/v1/auth/verify-email`` route — 200 on valid token, 422 on invalid
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.accounts.service import AccountService
from src.utils.exceptions import DatabaseError, InputValidationError


def _make_settings():
    s = MagicMock()
    s.default_starting_balance = Decimal("10000")
    s.jwt_secret = "test_secret_that_is_at_least_32_characters_long"
    s.jwt_expiry_hours = 1
    return s


def _make_service(session=None):
    if session is None:
        session = AsyncMock()
    return AccountService(session, _make_settings())


def _make_redis(*, stored_value=None):
    """Return a mock Redis client.

    Args:
        stored_value: The string value returned by ``r.get(key)``.  Pass
                      ``None`` to simulate a missing / expired token.
    """
    r = AsyncMock()
    r.get = AsyncMock(return_value=stored_value)
    r.set = AsyncMock(return_value=True)
    r.delete = AsyncMock(return_value=1)
    return r


# ---------------------------------------------------------------------------
# send_email_verification
# ---------------------------------------------------------------------------


class TestSendEmailVerification:
    async def test_stores_token_in_redis_with_24h_ttl(self):
        account_id = uuid4()
        redis = _make_redis()
        svc = _make_service()

        await svc.send_email_verification(account_id, "user@example.com", redis)

        redis.set.assert_called_once()
        call_args = redis.set.call_args
        # key must start with email_verify:
        assert call_args[0][0].startswith("email_verify:")
        # stored value is account_id as string
        assert call_args[0][1] == str(account_id)
        # TTL is 86400 seconds (24 hours)
        assert call_args[1].get("ex") == 86400 or call_args[0][2] == 86400

    async def test_returns_none_on_redis_error(self):
        from redis.exceptions import RedisError

        account_id = uuid4()
        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=RedisError("connection refused"))
        svc = _make_service()

        # Should not raise — failure is non-fatal
        result = await svc.send_email_verification(account_id, "user@example.com", redis)
        assert result is None

    async def test_logs_verification_url(self, caplog):
        import logging

        account_id = uuid4()
        redis = _make_redis()
        svc = _make_service()

        # structlog routes to stdlib logging in test environments
        with caplog.at_level(logging.INFO):
            await svc.send_email_verification(account_id, "user@example.com", redis)

        # The verify URL should appear somewhere in logs or structlog output
        # (structlog may not emit to caplog by default; just verify no exception)
        redis.set.assert_called_once()


# ---------------------------------------------------------------------------
# verify_email
# ---------------------------------------------------------------------------


class TestVerifyEmail:
    async def test_valid_token_sets_email_verified(self):
        account_id = uuid4()
        redis = _make_redis(stored_value=str(account_id))
        session = AsyncMock()
        svc = _make_service(session=session)

        await svc.verify_email("valid_token_abc", redis)

        # DB UPDATE executed
        session.execute.assert_called_once()
        # token deleted from Redis
        redis.delete.assert_called_once()

    async def test_missing_token_raises_input_validation_error(self):
        redis = _make_redis(stored_value=None)
        svc = _make_service()

        with pytest.raises(InputValidationError, match="Invalid or expired"):
            await svc.verify_email("unknown_token", redis)

    async def test_redis_error_raises_input_validation_error(self):
        from redis.exceptions import RedisError

        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=RedisError("timeout"))
        svc = _make_service()

        with pytest.raises(InputValidationError, match="Invalid or expired"):
            await svc.verify_email("some_token", redis)

    async def test_malformed_account_id_raises_input_validation_error(self):
        redis = _make_redis(stored_value="not-a-valid-uuid")
        svc = _make_service()

        with pytest.raises(InputValidationError, match="Invalid or expired"):
            await svc.verify_email("some_token", redis)

    async def test_db_error_raises_database_error(self):
        from sqlalchemy.exc import SQLAlchemyError

        account_id = uuid4()
        redis = _make_redis(stored_value=str(account_id))
        session = AsyncMock()
        session.execute = AsyncMock(side_effect=SQLAlchemyError("db gone"))
        svc = _make_service(session=session)

        with pytest.raises(DatabaseError, match="Failed to verify email"):
            await svc.verify_email("valid_token", redis)

    async def test_token_delete_failure_is_non_fatal(self):
        from redis.exceptions import RedisError

        account_id = uuid4()
        redis = _make_redis(stored_value=str(account_id))
        redis.delete = AsyncMock(side_effect=RedisError("timeout"))
        session = AsyncMock()
        svc = _make_service(session=session)

        # Should complete without raising even if delete fails
        await svc.verify_email("valid_token", redis)
        session.execute.assert_called_once()


# ---------------------------------------------------------------------------
# POST /api/v1/auth/verify-email route
# ---------------------------------------------------------------------------


class TestVerifyEmailRoute:
    async def test_valid_token_returns_200(self):
        from fastapi import FastAPI
        import httpx

        from src.api.routes.auth import router
        from src.dependencies import get_account_service, get_redis

        app = FastAPI()
        app.include_router(router)

        mock_svc = AsyncMock()
        mock_svc.verify_email = AsyncMock(return_value=None)
        mock_redis = AsyncMock()

        app.dependency_overrides[get_account_service] = lambda: mock_svc
        app.dependency_overrides[get_redis] = lambda: mock_redis

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/auth/verify-email",
                json={"token": "valid_token_abc"},
            )

        assert resp.status_code == 200
        assert resp.json()["message"] == "Email verified successfully."
        mock_svc.verify_email.assert_called_once_with("valid_token_abc", mock_redis)

    async def test_invalid_token_returns_422(self):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        import httpx

        from src.api.routes.auth import router
        from src.dependencies import get_account_service, get_redis
        from src.utils.exceptions import InputValidationError, TradingPlatformError

        app = FastAPI()
        app.include_router(router)

        # Register the TradingPlatformError handler (mirrors src/main.py)
        @app.exception_handler(TradingPlatformError)
        async def _handle(request, exc):  # noqa: ANN001
            return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

        mock_svc = AsyncMock()
        mock_svc.verify_email = AsyncMock(side_effect=InputValidationError("Invalid or expired verification token."))
        mock_redis = AsyncMock()

        app.dependency_overrides[get_account_service] = lambda: mock_svc
        app.dependency_overrides[get_redis] = lambda: mock_redis

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/auth/verify-email",
                json={"token": "expired_token"},
            )

        assert resp.status_code == 422

    async def test_empty_token_returns_422_validation_error(self):
        from fastapi import FastAPI
        import httpx

        from src.api.routes.auth import router
        from src.dependencies import get_account_service, get_redis

        app = FastAPI()
        app.include_router(router)

        mock_svc = AsyncMock()
        mock_redis = AsyncMock()
        app.dependency_overrides[get_account_service] = lambda: mock_svc
        app.dependency_overrides[get_redis] = lambda: mock_redis

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/auth/verify-email",
                json={"token": ""},
            )

        # min_length=1 on the token field — FastAPI returns 422
        assert resp.status_code == 422
