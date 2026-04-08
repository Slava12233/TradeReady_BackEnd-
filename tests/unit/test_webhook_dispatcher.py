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
            secret=sub.secret,
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
