"""Integration tests for all 6 webhook REST endpoints.

Covers:
- Full CRUD lifecycle: create → list → get → update → delete
- Secret only in create response (not in list/get/update)
- Auth required on all endpoints
- POST /{id}/test endpoint works
- Invalid events rejected (422)
- URL validation (max_length)
- Ownership / 404 / permission checks

Uses a mocked DB session and mocked auth. No Docker required.

Run with::

    pytest tests/integration/test_webhooks_api.py -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from src.config import Settings
from src.database.models import Account, WebhookSubscription
import src.database.session  # noqa: F401 — ensures submodule is importable by patch()

pytestmark = pytest.mark.slow

# ---------------------------------------------------------------------------
# Test settings
# ---------------------------------------------------------------------------

_TEST_SETTINGS = Settings(
    jwt_secret="test_secret_that_is_at_least_32_characters_long_for_hs256",
    database_url="postgresql+asyncpg://test:test@localhost:5432/test",
    redis_url="redis://localhost:6379/15",
    jwt_expiry_hours=1,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account(account_id: UUID | None = None) -> MagicMock:
    """Build a mock Account ORM object."""
    account = MagicMock(spec=Account)
    account.id = account_id or uuid4()
    account.api_key = "ak_live_testkey"
    account.display_name = "TestBot"
    account.status = "active"
    return account


def _make_webhook_sub(
    account_id: UUID,
    sub_id: UUID | None = None,
    url: str = "https://example.com/hook",
    events: list | None = None,
    description: str | None = "Test webhook",
    active: bool = True,
    failure_count: int = 0,
    secret: str = "super-secret-value",
) -> MagicMock:
    """Build a mock WebhookSubscription ORM object."""
    sub = MagicMock(spec=WebhookSubscription)
    sub.id = sub_id or uuid4()
    sub.account_id = account_id
    sub.url = url
    sub.events = events or ["backtest.completed"]
    sub.description = description
    sub.active = active
    sub.failure_count = failure_count
    sub.secret = secret
    sub.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    sub.updated_at = datetime(2026, 1, 1, tzinfo=UTC)
    sub.last_triggered_at = None
    return sub


def _mock_redis() -> AsyncMock:
    """Fully mocked Redis with pipeline support for rate-limit middleware."""
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


def _build_client(
    mock_account: MagicMock | None = None,
    mock_session: AsyncMock | None = None,
) -> TestClient:
    """Create a TestClient with mocked infrastructure.

    Patches lifespan hooks and auth middleware so tests run without real
    DB/Redis/Celery.
    """
    from src.api.middleware.auth import get_current_account
    from src.dependencies import get_db_session, get_redis, get_settings

    if mock_account is None:
        mock_account = _make_account()

    if mock_session is None:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.delete = AsyncMock()
        mock_session.execute = AsyncMock()
        # db.scalar() is used for per-account webhook limit check (returns count integer)
        mock_session.scalar = AsyncMock(return_value=0)

    redis = _mock_redis()

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

    client = TestClient(app, raise_server_exceptions=False)

    # Stop lifespan-only patches; keep auth patch alive for request handling
    for p in patchers[:6]:
        p.stop()
    client._auth_patcher = patchers[6]  # type: ignore[attr-defined]

    return client


def _build_client_no_auth() -> TestClient:
    """Create a TestClient where auth returns (None, None) — simulates missing auth."""
    from src.dependencies import get_db_session, get_redis, get_settings

    redis = _mock_redis()
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
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


def _wire_db_get(mock_session: AsyncMock, obj) -> None:
    """Wire mock_session.execute to return `obj` via scalars().first()."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = obj
    mock_session.execute = AsyncMock(return_value=mock_result)


def _wire_db_list(mock_session: AsyncMock, items: list, total: int = 0) -> None:
    """Wire mock_session.execute to return different results for list vs count queries.

    First call → scalars().all() returns items.
    Second call → scalar_one() returns total.
    """
    list_result = MagicMock()
    list_result.scalars.return_value.all.return_value = items

    count_result = MagicMock()
    count_result.scalar_one.return_value = total if total else len(items)

    mock_session.execute = AsyncMock(side_effect=[list_result, count_result])


# ---------------------------------------------------------------------------
# POST /api/v1/webhooks — create
# ---------------------------------------------------------------------------


class TestCreateWebhook:
    """Tests for POST /api/v1/webhooks."""

    def test_create_webhook_returns_201_with_secret(self):
        """Creating a webhook returns 201 and includes the one-time secret."""
        account = _make_account()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        # db.scalar() is used for per-account webhook limit check; return 0 = under limit
        mock_session.scalar = AsyncMock(return_value=0)

        # After flush() the ORM object has id and timestamps set
        def _after_flush():
            sub = mock_session.add.call_args.args[0]
            sub.id = uuid4()
            sub.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            sub.updated_at = datetime(2026, 1, 1, tzinfo=UTC)

        mock_session.flush = AsyncMock(side_effect=lambda: _after_flush())

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/hook",
                "events": ["backtest.completed"],
                "description": "My webhook",
            },
        )
        client._auth_patcher.stop()

        assert response.status_code == 201
        data = response.json()
        assert "secret" in data
        assert len(data["secret"]) > 0
        assert data["url"] == "https://example.com/hook"
        assert "backtest.completed" in data["events"]
        assert data["active"] is True

    def test_create_webhook_calls_db_add_and_commit(self):
        """DB add() and commit() are called during creation."""
        account = _make_account()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock(side_effect=lambda: None)
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        # db.scalar() is used for per-account webhook limit check; return 0 = under limit
        mock_session.scalar = AsyncMock(return_value=0)

        def _set_sub_id():
            sub = mock_session.add.call_args.args[0]
            sub.id = uuid4()
            sub.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            sub.updated_at = datetime(2026, 1, 1, tzinfo=UTC)

        mock_session.flush = AsyncMock(side_effect=lambda: _set_sub_id())

        client = _build_client(mock_account=account, mock_session=mock_session)
        client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/hook",
                "events": ["battle.completed"],
            },
        )
        client._auth_patcher.stop()

        mock_session.add.assert_called_once()
        mock_session.commit.assert_awaited_once()

    def test_create_webhook_rejects_unsupported_event(self):
        """Events not in SUPPORTED_EVENTS are rejected with 422."""
        client = _build_client()
        response = client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/hook",
                "events": ["fake.event", "another.bad.one"],
            },
        )
        client._auth_patcher.stop()

        assert response.status_code == 422

    def test_create_webhook_rejects_empty_events_list(self):
        """An empty events list is rejected with 422 (min_length=1)."""
        client = _build_client()
        response = client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/hook",
                "events": [],
            },
        )
        client._auth_patcher.stop()

        assert response.status_code == 422

    def test_create_webhook_url_too_long_rejected(self):
        """A URL exceeding 2048 characters is rejected with 422."""
        client = _build_client()
        long_url = "https://example.com/" + "x" * 2040
        response = client.post(
            "/api/v1/webhooks",
            json={
                "url": long_url,
                "events": ["backtest.completed"],
            },
        )
        client._auth_patcher.stop()

        assert response.status_code == 422

    def test_create_webhook_auth_required(self):
        """Unauthenticated request to POST /api/v1/webhooks returns 401."""
        client = _build_client_no_auth()
        response = client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/hook",
                "events": ["backtest.completed"],
            },
        )
        client._auth_patcher.stop()

        assert response.status_code == 401

    def test_create_webhook_rejected_when_limit_reached(self):
        """Creating a 26th webhook is rejected with 422 when account is at the 25-sub limit."""
        account = _make_account()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        # Simulate account already having 25 subscriptions — the limit
        mock_session.scalar = AsyncMock(return_value=25)

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/hook",
                "events": ["backtest.completed"],
            },
        )
        client._auth_patcher.stop()

        # InputValidationError maps to 422 in the global exception handler
        assert response.status_code == 422
        body = response.json()
        assert "error" in body
        assert "limit" in body["error"]["message"].lower() or "maximum" in body["error"]["message"].lower()

    def test_create_webhook_succeeds_at_limit_minus_one(self):
        """Creating a webhook when the account has 24 subscriptions succeeds."""
        account = _make_account()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        # 24 = one below the 25-subscription limit
        mock_session.scalar = AsyncMock(return_value=24)

        def _set_sub_id():
            sub = mock_session.add.call_args.args[0]
            sub.id = uuid4()
            sub.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            sub.updated_at = datetime(2026, 1, 1, tzinfo=UTC)

        mock_session.flush = AsyncMock(side_effect=lambda: _set_sub_id())

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/hook",
                "events": ["backtest.completed"],
            },
        )
        client._auth_patcher.stop()

        assert response.status_code == 201

    def test_create_webhook_accepts_multiple_valid_events(self):
        """Multiple valid events are accepted."""
        account = _make_account()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        def _set_sub_id():
            sub = mock_session.add.call_args.args[0]
            sub.id = uuid4()
            sub.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            sub.updated_at = datetime(2026, 1, 1, tzinfo=UTC)

        mock_session.flush = AsyncMock(side_effect=lambda: _set_sub_id())
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        # db.scalar() is used for per-account webhook limit check; return 0 = under limit
        mock_session.scalar = AsyncMock(return_value=0)

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/hook",
                "events": ["backtest.completed", "battle.completed", "strategy.deployed"],
            },
        )
        client._auth_patcher.stop()

        assert response.status_code == 201
        data = response.json()
        assert len(data["events"]) == 3


# ---------------------------------------------------------------------------
# GET /api/v1/webhooks — list
# ---------------------------------------------------------------------------


class TestListWebhooks:
    """Tests for GET /api/v1/webhooks."""

    def test_list_returns_200_with_webhooks(self):
        """List returns 200 with webhooks array and total count."""
        account = _make_account()
        subs = [
            _make_webhook_sub(account_id=account.id),
            _make_webhook_sub(account_id=account.id),
        ]
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        _wire_db_list(mock_session, subs, total=2)

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.get("/api/v1/webhooks")
        client._auth_patcher.stop()

        assert response.status_code == 200
        data = response.json()
        assert "webhooks" in data
        assert "total" in data
        assert data["total"] == 2
        assert len(data["webhooks"]) == 2

    def test_list_does_not_include_secret(self):
        """The list response schema never exposes the secret field."""
        account = _make_account()
        subs = [_make_webhook_sub(account_id=account.id, secret="should-not-appear")]
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        _wire_db_list(mock_session, subs, total=1)

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.get("/api/v1/webhooks")
        client._auth_patcher.stop()

        assert response.status_code == 200
        webhooks = response.json()["webhooks"]
        assert len(webhooks) == 1
        assert "secret" not in webhooks[0]

    def test_list_empty_when_no_subscriptions(self):
        """Returns empty list and total=0 when no subscriptions exist."""
        account = _make_account()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        _wire_db_list(mock_session, [], total=0)

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.get("/api/v1/webhooks")
        client._auth_patcher.stop()

        assert response.status_code == 200
        assert response.json() == {"webhooks": [], "total": 0}

    def test_list_auth_required(self):
        """GET /api/v1/webhooks returns 401 without auth."""
        client = _build_client_no_auth()
        response = client.get("/api/v1/webhooks")
        client._auth_patcher.stop()

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/v1/webhooks/{webhook_id} — get detail
# ---------------------------------------------------------------------------


class TestGetWebhook:
    """Tests for GET /api/v1/webhooks/{webhook_id}."""

    def test_get_returns_200_with_webhook_detail(self):
        """GET /{id} returns 200 with webhook detail (no secret)."""
        account = _make_account()
        sub = _make_webhook_sub(account_id=account.id)
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        _wire_db_get(mock_session, sub)

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.get(f"/api/v1/webhooks/{sub.id}")
        client._auth_patcher.stop()

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(sub.id)
        assert data["url"] == sub.url
        assert "secret" not in data
        assert "failure_count" in data

    def test_get_returns_404_when_not_found(self):
        """GET /{id} returns 404 when subscription does not exist."""
        account = _make_account()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        _wire_db_get(mock_session, None)  # not found

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.get(f"/api/v1/webhooks/{uuid4()}")
        client._auth_patcher.stop()

        assert response.status_code == 404

    def test_get_returns_403_when_wrong_account(self):
        """GET /{id} returns 403 when subscription belongs to a different account."""
        account = _make_account()
        other_account_id = uuid4()
        sub = _make_webhook_sub(account_id=other_account_id)  # owned by someone else
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        _wire_db_get(mock_session, sub)

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.get(f"/api/v1/webhooks/{sub.id}")
        client._auth_patcher.stop()

        assert response.status_code == 403

    def test_get_auth_required(self):
        """GET /{id} returns 401 without auth."""
        client = _build_client_no_auth()
        response = client.get(f"/api/v1/webhooks/{uuid4()}")
        client._auth_patcher.stop()

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# PUT /api/v1/webhooks/{webhook_id} — update
# ---------------------------------------------------------------------------


class TestUpdateWebhook:
    """Tests for PUT /api/v1/webhooks/{webhook_id}."""

    def test_update_url_returns_200(self):
        """PUT /{id} with new URL returns 200 and updated resource."""
        account = _make_account()
        sub = _make_webhook_sub(account_id=account.id)
        updated_sub = _make_webhook_sub(
            account_id=account.id,
            sub_id=sub.id,
            url="https://example.com/new-hook",
        )

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        # First execute: SELECT (returns sub), second execute: UPDATE RETURNING (returns updated_sub)
        get_result = MagicMock()
        get_result.scalars.return_value.first.return_value = sub

        update_result = MagicMock()
        update_result.scalars.return_value.first.return_value = updated_sub

        mock_session.execute = AsyncMock(side_effect=[get_result, update_result])

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.put(
            f"/api/v1/webhooks/{sub.id}",
            json={"url": "https://example.com/new-hook"},
        )
        client._auth_patcher.stop()

        assert response.status_code == 200
        assert "secret" not in response.json()

    def test_update_does_not_expose_secret(self):
        """PUT /{id} response never contains the secret field."""
        account = _make_account()
        sub = _make_webhook_sub(account_id=account.id, secret="should-not-appear")

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        get_result = MagicMock()
        get_result.scalars.return_value.first.return_value = sub

        update_result = MagicMock()
        update_result.scalars.return_value.first.return_value = sub

        mock_session.execute = AsyncMock(side_effect=[get_result, update_result])

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.put(
            f"/api/v1/webhooks/{sub.id}",
            json={"active": False},
        )
        client._auth_patcher.stop()

        assert "secret" not in response.json()

    def test_update_returns_404_when_not_found(self):
        """PUT /{id} returns 404 when subscription does not exist."""
        account = _make_account()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        _wire_db_get(mock_session, None)

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.put(
            f"/api/v1/webhooks/{uuid4()}",
            json={"active": False},
        )
        client._auth_patcher.stop()

        assert response.status_code == 404

    def test_update_rejects_invalid_events(self):
        """PUT /{id} with unsupported events returns 422."""
        client = _build_client()
        response = client.put(
            f"/api/v1/webhooks/{uuid4()}",
            json={"events": ["not.a.real.event"]},
        )
        client._auth_patcher.stop()

        assert response.status_code == 422

    def test_update_auth_required(self):
        """PUT /{id} returns 401 without auth."""
        client = _build_client_no_auth()
        response = client.put(
            f"/api/v1/webhooks/{uuid4()}",
            json={"active": False},
        )
        client._auth_patcher.stop()

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /api/v1/webhooks/{webhook_id}
# ---------------------------------------------------------------------------


class TestDeleteWebhook:
    """Tests for DELETE /api/v1/webhooks/{webhook_id}."""

    def test_delete_returns_204(self):
        """DELETE /{id} returns 204 No Content on success."""
        account = _make_account()
        sub = _make_webhook_sub(account_id=account.id)

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.delete = AsyncMock()
        _wire_db_get(mock_session, sub)

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.delete(f"/api/v1/webhooks/{sub.id}")
        client._auth_patcher.stop()

        assert response.status_code == 204

    def test_delete_calls_session_delete_and_commit(self):
        """DELETE calls session.delete() and session.commit()."""
        account = _make_account()
        sub = _make_webhook_sub(account_id=account.id)

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.delete = AsyncMock()
        _wire_db_get(mock_session, sub)

        client = _build_client(mock_account=account, mock_session=mock_session)
        client.delete(f"/api/v1/webhooks/{sub.id}")
        client._auth_patcher.stop()

        mock_session.delete.assert_awaited_once_with(sub)
        mock_session.commit.assert_awaited_once()

    def test_delete_returns_404_when_not_found(self):
        """DELETE /{id} returns 404 when subscription does not exist."""
        account = _make_account()
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.delete = AsyncMock()
        _wire_db_get(mock_session, None)

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.delete(f"/api/v1/webhooks/{uuid4()}")
        client._auth_patcher.stop()

        assert response.status_code == 404

    def test_delete_returns_403_for_wrong_account(self):
        """DELETE /{id} returns 403 when subscription belongs to another account."""
        account = _make_account()
        sub = _make_webhook_sub(account_id=uuid4())  # owned by someone else

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.delete = AsyncMock()
        _wire_db_get(mock_session, sub)

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.delete(f"/api/v1/webhooks/{sub.id}")
        client._auth_patcher.stop()

        assert response.status_code == 403

    def test_delete_auth_required(self):
        """DELETE /{id} returns 401 without auth."""
        client = _build_client_no_auth()
        response = client.delete(f"/api/v1/webhooks/{uuid4()}")
        client._auth_patcher.stop()

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/v1/webhooks/{webhook_id}/test
# ---------------------------------------------------------------------------


class TestTestWebhookEndpoint:
    """Tests for POST /api/v1/webhooks/{webhook_id}/test."""

    def test_test_endpoint_returns_200_with_enqueued(self):
        """POST /{id}/test returns 200 with enqueued=1 and webhook_id."""
        account = _make_account()
        sub = _make_webhook_sub(account_id=account.id)

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        _wire_db_get(mock_session, sub)

        mock_task = MagicMock()
        mock_task.delay = MagicMock()

        client = _build_client(mock_account=account, mock_session=mock_session)

        with patch("src.tasks.webhook_tasks.dispatch_webhook", mock_task):
            response = client.post(f"/api/v1/webhooks/{sub.id}/test")

        client._auth_patcher.stop()

        assert response.status_code == 200
        data = response.json()
        assert data["enqueued"] == 1
        assert data["webhook_id"] == str(sub.id)

    def test_test_endpoint_enqueues_task_with_correct_args(self):
        """POST /{id}/test calls dispatch_webhook.delay with the correct arguments."""
        account = _make_account()
        sub = _make_webhook_sub(
            account_id=account.id,
            url="https://example.com/hook",
            secret="test-secret",
        )

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        _wire_db_get(mock_session, sub)

        mock_task = MagicMock()
        mock_task.delay = MagicMock()

        client = _build_client(mock_account=account, mock_session=mock_session)

        with patch("src.tasks.webhook_tasks.dispatch_webhook", mock_task):
            client.post(f"/api/v1/webhooks/{sub.id}/test")

        client._auth_patcher.stop()

        mock_task.delay.assert_called_once()
        call_kwargs = mock_task.delay.call_args.kwargs
        assert call_kwargs["subscription_id"] == str(sub.id)
        assert call_kwargs["url"] == sub.url
        assert call_kwargs["secret"] == sub.secret
        assert call_kwargs["event_name"] == "webhook.test"

    def test_test_endpoint_returns_404_when_not_found(self):
        """POST /{id}/test returns 404 when subscription does not exist."""
        account = _make_account()

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        _wire_db_get(mock_session, None)

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.post(f"/api/v1/webhooks/{uuid4()}/test")
        client._auth_patcher.stop()

        assert response.status_code == 404

    def test_test_endpoint_returns_403_for_wrong_account(self):
        """POST /{id}/test returns 403 when subscription belongs to another account."""
        account = _make_account()
        sub = _make_webhook_sub(account_id=uuid4())  # owned by another account

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        _wire_db_get(mock_session, sub)

        client = _build_client(mock_account=account, mock_session=mock_session)
        response = client.post(f"/api/v1/webhooks/{sub.id}/test")
        client._auth_patcher.stop()

        assert response.status_code == 403

    def test_test_endpoint_auth_required(self):
        """POST /{id}/test returns 401 without auth."""
        client = _build_client_no_auth()
        response = client.post(f"/api/v1/webhooks/{uuid4()}/test")
        client._auth_patcher.stop()

        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Full CRUD lifecycle test
# ---------------------------------------------------------------------------


class TestCrudLifecycle:
    """Smoke-tests the full create → list → get → update → delete lifecycle."""

    def test_create_then_list_lifecycle(self):
        """Create a webhook and verify it appears in the list."""
        account = _make_account()

        # Step 1: Create
        create_session = AsyncMock()
        create_session.add = MagicMock()

        new_sub_id = uuid4()

        def _flush_side_effect():
            obj = create_session.add.call_args.args[0]
            obj.id = new_sub_id
            obj.created_at = datetime(2026, 1, 1, tzinfo=UTC)
            obj.updated_at = datetime(2026, 1, 1, tzinfo=UTC)

        create_session.flush = AsyncMock(side_effect=lambda: _flush_side_effect())
        create_session.commit = AsyncMock()
        create_session.rollback = AsyncMock()
        # db.scalar() is used for per-account webhook limit check; return 0 = under limit
        create_session.scalar = AsyncMock(return_value=0)

        create_client = _build_client(mock_account=account, mock_session=create_session)
        create_resp = create_client.post(
            "/api/v1/webhooks",
            json={
                "url": "https://example.com/hook",
                "events": ["backtest.completed"],
                "description": "lifecycle test",
            },
        )
        create_client._auth_patcher.stop()

        assert create_resp.status_code == 201
        created = create_resp.json()
        assert "secret" in created

        # Step 2: List — verify secret is absent
        list_sub = _make_webhook_sub(account_id=account.id, sub_id=new_sub_id)
        list_session = AsyncMock()
        list_session.add = MagicMock()
        list_session.flush = AsyncMock()
        list_session.commit = AsyncMock()
        list_session.rollback = AsyncMock()
        _wire_db_list(list_session, [list_sub], total=1)

        list_client = _build_client(mock_account=account, mock_session=list_session)
        list_resp = list_client.get("/api/v1/webhooks")
        list_client._auth_patcher.stop()

        assert list_resp.status_code == 200
        assert list_resp.json()["total"] == 1
        assert "secret" not in list_resp.json()["webhooks"][0]

    def test_schema_secret_present_only_in_create(self):
        """Verify the WebhookCreateResponse schema contains secret, WebhookResponse does not."""
        from src.api.schemas.webhooks import WebhookCreateResponse, WebhookResponse

        create_fields = set(WebhookCreateResponse.model_fields.keys())
        response_fields = set(WebhookResponse.model_fields.keys())

        assert "secret" in create_fields
        assert "secret" not in response_fields
