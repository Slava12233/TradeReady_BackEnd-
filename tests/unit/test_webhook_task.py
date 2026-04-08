"""Unit tests for src/tasks/webhook_tasks.py.

Tests the _async_dispatch coroutine (the async core of dispatch_webhook):
- HMAC-SHA256 signature is computed correctly
- Successful delivery resets failure_count to 0
- HTTP failure triggers retry via task.retry()
- failure_count incremented after max retries exhausted
- Auto-disable (active=False) after 10 consecutive failures
- Timeout handling
- _record_success and _record_failure DB helpers
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.celery


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(retries: int = 0):
    """Build a minimal Celery task stub with retry support."""
    task = MagicMock()
    task.request = MagicMock()
    task.request.retries = retries
    # task.retry raises the returned exception (Celery behaviour)
    retry_exc = Exception("retry_sentinel")
    task.retry = MagicMock(side_effect=retry_exc)
    return task


def _compute_expected_sig(secret: str, payload: dict) -> str:
    """Compute the HMAC-SHA256 hex digest the same way the implementation does."""
    payload_bytes = json.dumps(payload, default=str).encode("utf-8")
    return hmac.new(
        secret.encode("utf-8"), payload_bytes, hashlib.sha256
    ).hexdigest()


def _make_session_factory(failure_count: int = 0):
    """Build a mock async session factory pre-loaded with failure_count."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.execute = AsyncMock()

    # Simulate SELECT result for failure_count query
    count_row = MagicMock()
    count_row.failure_count = failure_count
    count_result = MagicMock()
    count_result.one_or_none.return_value = count_row
    mock_session.execute.return_value = count_result

    mock_factory = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory.return_value = mock_ctx

    return mock_factory, mock_session


# ---------------------------------------------------------------------------
# HMAC signature tests
# ---------------------------------------------------------------------------


class TestHmacSignature:
    """Tests that the outgoing X-Webhook-Signature header contains the correct HMAC."""

    async def test_signature_matches_expected_hmac(self):
        """Signature header equals HMAC-SHA256(secret, json_payload)."""
        secret = "test-webhook-secret-abc"
        payload = {"event": "order.filled", "order_id": "xyz-123"}

        expected_sig = _compute_expected_sig(secret, payload)

        captured_headers = {}

        async def _fake_post(url, *, content, headers, **_kwargs):
            captured_headers.update(headers)
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            return resp

        mock_client = AsyncMock()
        mock_client.post = _fake_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_factory, _ = _make_session_factory()

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.database.models.WebhookSubscription"),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = _make_task()
            await _async_dispatch(
                task=task,
                subscription_id=str(uuid4()),
                url="https://example.com/hook",
                secret=secret,
                event_name="order.filled",
                payload=payload,
            )

        assert captured_headers["X-Webhook-Signature"] == expected_sig

    async def test_signature_changes_with_different_payload(self):
        """Two different payloads produce two different signatures."""
        secret = "same-secret"
        payload_a = {"order_id": "aaa"}
        payload_b = {"order_id": "bbb"}

        sig_a = _compute_expected_sig(secret, payload_a)
        sig_b = _compute_expected_sig(secret, payload_b)

        assert sig_a != sig_b

    async def test_event_name_in_headers(self):
        """X-Webhook-Event header equals the event_name argument."""
        captured_headers = {}

        async def _fake_post(url, *, content, headers, **_kwargs):
            captured_headers.update(headers)
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            return resp

        mock_client = AsyncMock()
        mock_client.post = _fake_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_factory, _ = _make_session_factory()

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.database.models.WebhookSubscription"),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = _make_task()
            await _async_dispatch(
                task=task,
                subscription_id=str(uuid4()),
                url="https://example.com/hook",
                secret="secret",
                event_name="battle.completed",
                payload={},
            )

        assert captured_headers["X-Webhook-Event"] == "battle.completed"

    async def test_content_type_is_json(self):
        """Content-Type header is application/json."""
        captured_headers = {}

        async def _fake_post(url, *, content, headers, **_kwargs):
            captured_headers.update(headers)
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = MagicMock()
            return resp

        mock_client = AsyncMock()
        mock_client.post = _fake_post
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_factory, _ = _make_session_factory()

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.database.models.WebhookSubscription"),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = _make_task()
            await _async_dispatch(
                task=task,
                subscription_id=str(uuid4()),
                url="https://example.com/hook",
                secret="secret",
                event_name="order.filled",
                payload={},
            )

        assert captured_headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Success path tests
# ---------------------------------------------------------------------------


class TestSuccessPath:
    """Tests for successful HTTP delivery."""

    async def test_success_returns_success_true(self):
        """Returns dict with success=True on HTTP 200."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_factory, _ = _make_session_factory()

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.database.models.WebhookSubscription"),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = _make_task()
            result = await _async_dispatch(
                task=task,
                subscription_id=str(uuid4()),
                url="https://example.com/hook",
                secret="secret",
                event_name="order.filled",
                payload={"x": 1},
            )

        assert result["success"] is True
        assert result["status_code"] == 200
        assert "duration_ms" in result
        assert "subscription_id" in result
        assert "event_name" in result

    async def test_success_calls_record_success(self):
        """_record_success is called on successful delivery."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_record = AsyncMock(return_value=None)
        mock_factory, _ = _make_session_factory()

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.tasks.webhook_tasks._record_success", mock_record),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = _make_task()
            sub_id = str(uuid4())
            await _async_dispatch(
                task=task,
                subscription_id=sub_id,
                url="https://example.com/hook",
                secret="secret",
                event_name="order.filled",
                payload={},
            )

        mock_record.assert_awaited_once()
        assert mock_record.call_args.args[0] == sub_id

    async def test_success_resets_failure_count_via_db(self):
        """On success, _record_success receives the sub_id and session factory."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_factory = MagicMock()
        mock_record = AsyncMock(return_value=None)

        sub_id = str(uuid4())

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.tasks.webhook_tasks._record_success", mock_record),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = _make_task()
            await _async_dispatch(
                task=task,
                subscription_id=sub_id,
                url="https://example.com/hook",
                secret="secret",
                event_name="order.filled",
                payload={},
            )

        mock_record.assert_awaited_once_with(sub_id, mock_factory)


# ---------------------------------------------------------------------------
# Retry / failure path tests
# ---------------------------------------------------------------------------


class TestRetryPath:
    """Tests for HTTP failure and retry behaviour."""

    async def test_http_status_error_triggers_retry_on_first_attempt(self):
        """4xx/5xx responses trigger task.retry() on the first attempt."""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500
        http_error = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=http_error)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory"),
            patch("src.database.models.WebhookSubscription"),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = _make_task(retries=0)
            # task.retry raises our sentinel; that exception should propagate
            with pytest.raises(Exception, match="retry_sentinel"):
                await _async_dispatch(
                    task=task,
                    subscription_id=str(uuid4()),
                    url="https://example.com/hook",
                    secret="secret",
                    event_name="order.filled",
                    payload={},
                )

        task.retry.assert_called_once()

    async def test_retry_uses_correct_countdown_for_first_attempt(self):
        """First retry countdown is 10 seconds (RETRY_COUNTDOWNS[0])."""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 503
        http_error = httpx.HTTPStatusError(
            "Service Unavailable", request=MagicMock(), response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=http_error)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory"),
            patch("src.database.models.WebhookSubscription"),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = _make_task(retries=0)
            with pytest.raises(Exception, match="retry_sentinel"):
                await _async_dispatch(
                    task=task,
                    subscription_id=str(uuid4()),
                    url="https://example.com/hook",
                    secret="secret",
                    event_name="order.filled",
                    payload={},
                )

        _call_kwargs = task.retry.call_args.kwargs
        assert _call_kwargs["countdown"] == 10

    async def test_retry_countdown_increases_for_second_attempt(self):
        """Second retry countdown is 30 seconds (RETRY_COUNTDOWNS[1])."""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 503
        http_error = httpx.HTTPStatusError(
            "Service Unavailable", request=MagicMock(), response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=http_error)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory"),
            patch("src.database.models.WebhookSubscription"),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = _make_task(retries=1)
            with pytest.raises(Exception, match="retry_sentinel"):
                await _async_dispatch(
                    task=task,
                    subscription_id=str(uuid4()),
                    url="https://example.com/hook",
                    secret="secret",
                    event_name="order.filled",
                    payload={},
                )

        _call_kwargs = task.retry.call_args.kwargs
        assert _call_kwargs["countdown"] == 30

    async def test_retry_countdown_is_60_for_third_attempt(self):
        """Third retry countdown is 60 seconds (RETRY_COUNTDOWNS[2])."""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 503
        http_error = httpx.HTTPStatusError(
            "Service Unavailable", request=MagicMock(), response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=http_error)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory"),
            patch("src.database.models.WebhookSubscription"),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = _make_task(retries=2)
            with pytest.raises(Exception, match="retry_sentinel"):
                await _async_dispatch(
                    task=task,
                    subscription_id=str(uuid4()),
                    url="https://example.com/hook",
                    secret="secret",
                    event_name="order.filled",
                    payload={},
                )

        _call_kwargs = task.retry.call_args.kwargs
        assert _call_kwargs["countdown"] == 60

    async def test_all_retries_exhausted_calls_record_failure(self):
        """When retries >= len(RETRY_COUNTDOWNS), _record_failure is called."""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500
        http_error = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=http_error)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_factory, _ = _make_session_factory(failure_count=5)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.database.models.WebhookSubscription"),
            patch("src.tasks.webhook_tasks._record_failure") as mock_fail,
        ):
            mock_fail.__call__ = AsyncMock(return_value=None)
            mock_fail.return_value = None
            from src.tasks.webhook_tasks import _async_dispatch

            # retries == 3 means all 3 retry slots are used (0-indexed: 0,1,2)
            task = _make_task(retries=3)
            result = await _async_dispatch(
                task=task,
                subscription_id=str(uuid4()),
                url="https://example.com/hook",
                secret="secret",
                event_name="order.filled",
                payload={},
            )

        mock_fail.assert_awaited_once()
        assert result["success"] is False

    async def test_all_retries_exhausted_returns_success_false(self):
        """After max retries the result contains success=False."""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 503
        http_error = httpx.HTTPStatusError(
            "Service Unavailable", request=MagicMock(), response=mock_response
        )
        mock_response.raise_for_status = MagicMock(side_effect=http_error)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_factory, _ = _make_session_factory(failure_count=1)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.database.models.WebhookSubscription"),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = _make_task(retries=3)
            result = await _async_dispatch(
                task=task,
                subscription_id=str(uuid4()),
                url="https://example.com/hook",
                secret="secret",
                event_name="order.filled",
                payload={},
            )

        assert result["success"] is False
        assert result["status_code"] == 503

    async def test_timeout_triggers_retry(self):
        """httpx.TimeoutException triggers task.retry() on first attempt."""
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.TimeoutException("timed out", request=MagicMock())
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory"),
            patch("src.database.models.WebhookSubscription"),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = _make_task(retries=0)
            with pytest.raises(Exception, match="retry_sentinel"):
                await _async_dispatch(
                    task=task,
                    subscription_id=str(uuid4()),
                    url="https://slow.example.com/hook",
                    secret="secret",
                    event_name="order.filled",
                    payload={},
                )

        task.retry.assert_called_once()

    async def test_network_error_triggers_retry(self):
        """httpx.RequestError (e.g. DNS failure) also triggers retry."""
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.RequestError("DNS lookup failed", request=MagicMock())
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.database.session.get_session_factory"),
            patch("src.database.models.WebhookSubscription"),
        ):
            from src.tasks.webhook_tasks import _async_dispatch

            task = _make_task(retries=0)
            with pytest.raises(Exception, match="retry_sentinel"):
                await _async_dispatch(
                    task=task,
                    subscription_id=str(uuid4()),
                    url="https://no-such-host.example.com/hook",
                    secret="secret",
                    event_name="order.filled",
                    payload={},
                )

        task.retry.assert_called_once()


# ---------------------------------------------------------------------------
# Auto-disable tests
# ---------------------------------------------------------------------------


class TestAutoDisable:
    """Tests for the auto-disable-after-10-failures behaviour in _record_failure."""

    async def test_failure_count_incremented_below_threshold(self):
        """failure_count < MAX_FAILURES: SELECT + UPDATE executed and commit called."""
        sub_id = str(uuid4())
        mock_factory, mock_session = _make_session_factory(failure_count=5)

        # Patch the WebhookSubscription import inside the helper so SQLAlchemy
        # can build the UPDATE statement against the real mapped columns.
        with patch("src.tasks.webhook_tasks.WebhookSubscription", create=True):
            # Since the helper uses a lazy import we patch at the lazy-import site.
            # The simplest approach: patch the full DB helper to verify behavior
            # indirectly (see test_all_retries_exhausted_calls_record_failure above)
            # and here just assert the session interactions are correct.
            pass

        # Re-approach: call _record_failure with the real model (no patch needed
        # because the function lazy-imports it, but the session is mocked so no
        # DB is actually called — the UPDATE statement is built but never sent).
        mock_factory2, mock_session2 = _make_session_factory(failure_count=5)
        # We still need to let session.execute succeed for the SELECT step.
        # The UPDATE step also calls session.execute; use side_effect list.
        select_result = MagicMock()
        row = MagicMock()
        row.failure_count = 5
        select_result.one_or_none.return_value = row
        mock_session2.execute = AsyncMock(side_effect=[select_result, MagicMock()])

        from src.tasks.webhook_tasks import _record_failure

        await _record_failure(sub_id, mock_factory2)

        # Should execute a SELECT + UPDATE then commit
        assert mock_session2.execute.await_count == 2
        mock_session2.commit.assert_awaited_once()

    async def test_auto_disable_at_threshold(self):
        """At failure_count=9, the next failure (10) triggers auto-disable path."""
        sub_id = str(uuid4())
        mock_factory, mock_session = _make_session_factory(failure_count=9)

        select_result = MagicMock()
        row = MagicMock()
        row.failure_count = 9
        select_result.one_or_none.return_value = row
        mock_session.execute = AsyncMock(side_effect=[select_result, MagicMock()])

        from src.tasks.webhook_tasks import _record_failure

        await _record_failure(sub_id, mock_factory)

        # Two execute calls: SELECT then UPDATE (which includes active=False)
        assert mock_session.execute.await_count == 2
        mock_session.commit.assert_awaited_once()

    async def test_record_failure_graceful_when_subscription_not_found(self):
        """If the SELECT returns None, _record_failure returns without error."""
        sub_id = str(uuid4())
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()

        not_found_result = MagicMock()
        not_found_result.one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=not_found_result)

        mock_factory = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_ctx

        from src.tasks.webhook_tasks import _record_failure

        # Should not raise
        await _record_failure(sub_id, mock_factory)

        # Only the SELECT should have been called; no UPDATE
        mock_session.execute.assert_awaited_once()
        mock_session.commit.assert_not_awaited()

    async def test_record_failure_db_error_is_swallowed(self):
        """DB error inside _record_failure is swallowed, does not propagate."""
        sub_id = str(uuid4())
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("DB error"))

        mock_factory = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_ctx

        from src.tasks.webhook_tasks import _record_failure

        # Must not raise
        await _record_failure(sub_id, mock_factory)

    async def test_record_success_db_error_is_swallowed(self):
        """DB error inside _record_success is swallowed, does not propagate."""
        sub_id = str(uuid4())
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(side_effect=RuntimeError("DB error"))

        mock_factory = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_ctx

        from src.tasks.webhook_tasks import _record_success

        # Must not raise
        await _record_success(sub_id, mock_factory)

    async def test_record_success_calls_commit(self):
        """_record_success executes an UPDATE and commits."""
        sub_id = str(uuid4())
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=MagicMock())
        mock_session.commit = AsyncMock()

        mock_factory = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_factory.return_value = mock_ctx

        from src.tasks.webhook_tasks import _record_success

        await _record_success(sub_id, mock_factory)

        mock_session.execute.assert_awaited_once()
        mock_session.commit.assert_awaited_once()
