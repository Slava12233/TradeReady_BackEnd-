"""Unit tests for src/webhooks/dispatcher.py.

Tests the fire_event() function:
- Fires tasks to matching subscriptions only
- Skips inactive subscriptions
- Skips subscriptions not matching the event name
- Returns count of tasks enqueued
- Handles DB errors gracefully (never raises)

Strategy: We do NOT patch the real WebhookSubscription ORM model because the
dispatcher uses its column attributes to build a SELECT statement.  Instead we
mock db.execute() to return pre-built subscription objects, and patch only
dispatch_webhook so no Celery broker is needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sub(
    sub_id=None,
    url="https://example.com/hook",
    secret="mysecret",
    active=True,
    events=None,
    account_id=None,
):
    """Build a plain-object mock of a WebhookSubscription row."""
    sub = MagicMock()
    sub.id = sub_id or uuid4()
    sub.url = url
    sub.secret = secret
    sub.active = active
    sub.events = events or ["order.filled"]
    sub.account_id = account_id or uuid4()
    return sub


def _make_db_with_subscriptions(subscriptions):
    """Build a mock AsyncSession whose execute() returns the given subscriptions."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = subscriptions
    mock_db.execute = AsyncMock(return_value=mock_result)
    return mock_db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFireEvent:
    """Tests for fire_event()."""

    async def test_enqueues_task_for_matching_subscription(self):
        """fire_event returns 1 when a single matching subscription is found."""
        account_id = uuid4()
        sub = _make_sub(account_id=account_id)
        mock_db = _make_db_with_subscriptions([sub])

        mock_task = MagicMock()
        mock_task.delay = MagicMock()

        with patch("src.tasks.webhook_tasks.dispatch_webhook", mock_task):
            from src.webhooks.dispatcher import fire_event

            count = await fire_event(
                account_id=account_id,
                event_name="order.filled",
                payload={"order_id": "abc"},
                db=mock_db,
            )

        assert count == 1
        mock_task.delay.assert_called_once_with(
            subscription_id=str(sub.id),
            url=sub.url,
            event_name="order.filled",
            payload={"order_id": "abc"},
        )

    async def test_enqueues_one_task_per_matching_subscription(self):
        """Multiple matching subscriptions each get their own task."""
        account_id = uuid4()
        subs = [_make_sub(account_id=account_id) for _ in range(3)]
        mock_db = _make_db_with_subscriptions(subs)

        mock_task = MagicMock()
        mock_task.delay = MagicMock()

        with patch("src.tasks.webhook_tasks.dispatch_webhook", mock_task):
            from src.webhooks.dispatcher import fire_event

            count = await fire_event(
                account_id=account_id,
                event_name="order.filled",
                payload={},
                db=mock_db,
            )

        assert count == 3
        assert mock_task.delay.call_count == 3

    async def test_returns_zero_when_no_subscriptions(self):
        """Returns 0 when the DB query yields no subscriptions."""
        mock_db = _make_db_with_subscriptions([])

        with patch("src.tasks.webhook_tasks.dispatch_webhook") as mock_task:
            from src.webhooks.dispatcher import fire_event

            count = await fire_event(
                account_id=uuid4(),
                event_name="order.filled",
                payload={},
                db=mock_db,
            )

        assert count == 0
        mock_task.delay.assert_not_called()

    async def test_db_error_returns_zero_and_does_not_raise(self):
        """DB query failure is swallowed — returns 0, never raises."""
        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(side_effect=RuntimeError("DB connection lost"))

        with patch("src.tasks.webhook_tasks.dispatch_webhook") as mock_task:
            from src.webhooks.dispatcher import fire_event

            # Must not raise
            count = await fire_event(
                account_id=uuid4(),
                event_name="order.filled",
                payload={},
                db=mock_db,
            )

        assert count == 0
        mock_task.delay.assert_not_called()

    async def test_enqueue_error_skips_subscription_but_continues(self):
        """If task.delay raises for one subscription, others are still enqueued."""
        account_id = uuid4()
        sub1 = _make_sub(account_id=account_id)
        sub2 = _make_sub(account_id=account_id)
        mock_db = _make_db_with_subscriptions([sub1, sub2])

        mock_task = MagicMock()
        # First call raises, second succeeds
        mock_task.delay = MagicMock(
            side_effect=[RuntimeError("Celery broker down"), None]
        )

        with patch("src.tasks.webhook_tasks.dispatch_webhook", mock_task):
            from src.webhooks.dispatcher import fire_event

            count = await fire_event(
                account_id=account_id,
                event_name="order.filled",
                payload={},
                db=mock_db,
            )

        # Only the second sub was successfully enqueued
        assert count == 1
        assert mock_task.delay.call_count == 2

    async def test_passes_correct_payload_to_task(self):
        """The exact payload dict is forwarded to dispatch_webhook.delay."""
        account_id = uuid4()
        sub = _make_sub(account_id=account_id)
        mock_db = _make_db_with_subscriptions([sub])

        payload = {"backtest_id": "sess-123", "status": "completed", "roi": 0.15}
        mock_task = MagicMock()
        mock_task.delay = MagicMock()

        with patch("src.tasks.webhook_tasks.dispatch_webhook", mock_task):
            from src.webhooks.dispatcher import fire_event

            await fire_event(
                account_id=account_id,
                event_name="backtest.completed",
                payload=payload,
                db=mock_db,
            )

        _kwargs = mock_task.delay.call_args.kwargs
        assert _kwargs["payload"] == payload
        assert _kwargs["event_name"] == "backtest.completed"

    async def test_queries_db_with_execute(self):
        """execute() is called once (the JSONB-filtered SELECT)."""
        account_id = uuid4()
        mock_db = _make_db_with_subscriptions([])

        with patch("src.tasks.webhook_tasks.dispatch_webhook"):
            from src.webhooks.dispatcher import fire_event

            await fire_event(
                account_id=account_id,
                event_name="order.filled",
                payload={},
                db=mock_db,
            )

        mock_db.execute.assert_awaited_once()

    async def test_enqueue_error_does_not_raise(self):
        """Even if every enqueue fails, fire_event returns 0 without raising."""
        account_id = uuid4()
        subs = [_make_sub(account_id=account_id) for _ in range(2)]
        mock_db = _make_db_with_subscriptions(subs)

        mock_task = MagicMock()
        mock_task.delay = MagicMock(side_effect=RuntimeError("broker down"))

        with patch("src.tasks.webhook_tasks.dispatch_webhook", mock_task):
            from src.webhooks.dispatcher import fire_event

            # Must not raise
            count = await fire_event(
                account_id=account_id,
                event_name="order.filled",
                payload={},
                db=mock_db,
            )

        assert count == 0


# ---------------------------------------------------------------------------
# SSRF protection tests — validate_webhook_url()
# ---------------------------------------------------------------------------


class TestValidateWebhookUrl:
    """Tests for validate_webhook_url() SSRF protection.

    These tests exercise the function directly without any network calls for
    the blocked cases.  The happy-path test uses socket.getaddrinfo patching
    to avoid a live DNS dependency.
    """

    def test_http_scheme_rejected(self):
        """Plain http:// URLs are rejected — HTTPS is required."""
        from src.webhooks.dispatcher import validate_webhook_url

        with pytest.raises(ValueError, match="https"):
            validate_webhook_url("http://example.com/hook")

    def test_non_https_scheme_rejected(self):
        """Non-http schemes (ftp, ws) are also rejected."""
        from src.webhooks.dispatcher import validate_webhook_url

        with pytest.raises(ValueError, match="https"):
            validate_webhook_url("ftp://example.com/hook")

    def test_bare_ip_literal_rejected(self):
        """A URL using a bare IPv4 literal must be rejected."""
        from src.webhooks.dispatcher import validate_webhook_url

        with pytest.raises(ValueError, match="bare IP"):
            validate_webhook_url("https://93.184.216.34/hook")

    def test_localhost_hostname_rejected(self):
        """https://localhost/hook resolves to 127.0.0.1 and must be blocked."""
        import socket
        from unittest.mock import patch as local_patch

        from src.webhooks.dispatcher import validate_webhook_url

        # Patch getaddrinfo so localhost always resolves to 127.0.0.1 regardless
        # of the OS hosts file (avoids environment-specific behaviour).
        fake_addr = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]
        with local_patch("socket.getaddrinfo", return_value=fake_addr):
            with pytest.raises(ValueError, match="blocked"):
                validate_webhook_url("https://localhost/hook")

    def test_private_class_a_ip_rejected(self):
        """A hostname resolving to RFC-1918 10.0.0.x must be rejected."""
        import socket
        from unittest.mock import patch as local_patch

        from src.webhooks.dispatcher import validate_webhook_url

        fake_addr = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 0))]
        with local_patch("socket.getaddrinfo", return_value=fake_addr):
            with pytest.raises(ValueError, match="blocked"):
                validate_webhook_url("https://internal.corp/hook")

    def test_link_local_aws_metadata_ip_rejected(self):
        """A hostname resolving to 169.254.x.x (AWS metadata) must be rejected."""
        import socket
        from unittest.mock import patch as local_patch

        from src.webhooks.dispatcher import validate_webhook_url

        fake_addr = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0))]
        with local_patch("socket.getaddrinfo", return_value=fake_addr):
            with pytest.raises(ValueError, match="blocked"):
                validate_webhook_url("https://metadata.aws/hook")

    def test_private_class_c_ip_rejected(self):
        """A hostname resolving to RFC-1918 192.168.x.x must be rejected."""
        import socket
        from unittest.mock import patch as local_patch

        from src.webhooks.dispatcher import validate_webhook_url

        fake_addr = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0))]
        with local_patch("socket.getaddrinfo", return_value=fake_addr):
            with pytest.raises(ValueError, match="blocked"):
                validate_webhook_url("https://router.home/hook")

    def test_valid_public_https_url_accepted(self):
        """A valid HTTPS URL resolving to a public IP is accepted and returned."""
        import socket
        from unittest.mock import patch as local_patch

        from src.webhooks.dispatcher import validate_webhook_url

        # 93.184.216.34 is the well-known example.com IP — a public address.
        fake_addr = [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]
        with local_patch("socket.getaddrinfo", return_value=fake_addr):
            result = validate_webhook_url("https://example.com/hook")

        assert result == "https://example.com/hook"

    def test_unresolvable_hostname_rejected(self):
        """A hostname that cannot be resolved raises ValueError (not OSError)."""
        from unittest.mock import patch as local_patch

        from src.webhooks.dispatcher import validate_webhook_url

        with local_patch("socket.getaddrinfo", side_effect=OSError("Name or service not known")):
            with pytest.raises(ValueError, match="could not be resolved"):
                validate_webhook_url("https://this-does-not-exist.example.invalid/hook")

    def test_missing_hostname_rejected(self):
        """A URL with no hostname component is rejected."""
        from src.webhooks.dispatcher import validate_webhook_url

        with pytest.raises(ValueError, match="hostname"):
            validate_webhook_url("https:///path")
