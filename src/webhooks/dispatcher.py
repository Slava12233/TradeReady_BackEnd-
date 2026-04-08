"""Webhook event dispatcher — queries subscriptions and enqueues delivery tasks.

The public entry-point is :func:`fire_event`.  It is async-safe and designed
to be called from anywhere inside the FastAPI request lifecycle (route handlers,
services, Celery tasks that already have a DB session, etc.).

Design notes
------------
* The query filters on ``active=True`` and uses a PostgreSQL JSONB containment
  operator (``@>`` / ``cast(ANY(...) as text)``) to check whether the event
  name is present in the ``events`` array.  Filtering happens in the DB so no
  rows are transferred unless they match.
* Celery task enqueuing is fire-and-forget from the dispatcher's perspective.
  The task handles retries, failure counting, and auto-disable logic.
* Errors during subscription lookup are logged but are not propagated — the
  platform event that triggered the dispatch must not fail because a webhook
  subscriber is unreachable.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

logger = structlog.get_logger(__name__)


async def fire_event(
    account_id: UUID,
    event_name: str,
    payload: dict,  # type: ignore[type-arg]
    db: AsyncSession,
) -> int:
    """Query active webhook subscriptions for *event_name* and enqueue delivery.

    Finds all :class:`~src.database.models.WebhookSubscription` rows where:

    * ``active = True``
    * ``account_id`` matches the caller's account
    * ``event_name`` is contained in the ``events`` JSONB array

    For each match a :func:`~src.tasks.webhook_tasks.dispatch_webhook` Celery
    task is enqueued with the subscription id, url, secret, event name, and
    serialised payload.

    Args:
        account_id: The account whose subscriptions should be checked.
        event_name: Dot-separated event identifier (e.g. ``"order.filled"``).
        payload:    Arbitrary JSON-serialisable dict that will be sent as the
                    webhook request body.
        db:         Active async SQLAlchemy session (read-only; no writes made
                    here).

    Returns:
        The number of Celery tasks enqueued (one per matching subscription).

    Raises:
        Nothing — all exceptions are caught, logged, and swallowed so the
        caller's business logic is never interrupted by a webhook failure.

    Example::

        enqueued = await fire_event(
            account_id=account.id,
            event_name="backtest.completed",
            payload={"backtest_id": str(session_id), "status": "completed"},
            db=db,
        )
    """
    from src.database.models import WebhookSubscription  # noqa: PLC0415
    from src.tasks.webhook_tasks import dispatch_webhook  # noqa: PLC0415

    enqueued = 0

    try:
        # PostgreSQL JSONB containment: events @> '["<event_name>"]'
        # This efficiently checks whether the array contains the given string.
        stmt = select(WebhookSubscription).where(
            WebhookSubscription.account_id == account_id,
            WebhookSubscription.active.is_(True),
            WebhookSubscription.events.cast(JSONB).contains(
                cast(json.dumps([event_name]), JSONB)
            ),
        )
        result = await db.execute(stmt)
        subscriptions = result.scalars().all()

        for sub in subscriptions:
            try:
                dispatch_webhook.delay(
                    subscription_id=str(sub.id),
                    url=sub.url,
                    secret=sub.secret,
                    event_name=event_name,
                    payload=payload,
                )
                enqueued += 1
            except Exception:
                logger.exception(
                    "webhook.dispatch.enqueue_failed",
                    subscription_id=str(sub.id),
                    account_id=str(account_id),
                    event_name=event_name,
                )

    except Exception:
        logger.exception(
            "webhook.dispatch.query_failed",
            account_id=str(account_id),
            event_name=event_name,
        )

    if enqueued:
        logger.info(
            "webhook.dispatch.enqueued",
            account_id=str(account_id),
            event_name=event_name,
            enqueued=enqueued,
        )

    return enqueued
