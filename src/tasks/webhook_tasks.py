"""Celery task for outbound webhook delivery with HMAC-SHA256 signing and retry logic.

One task is registered here:

* :func:`dispatch_webhook` — sends a signed JSON POST to a webhook endpoint.
  Retries up to 3 times with exponential back-off (10 s, 30 s, 60 s).  On
  final failure the subscription's ``failure_count`` is incremented.
  Subscriptions with 10 or more consecutive failures are auto-disabled
  (``active=False``).  A successful delivery resets ``failure_count`` to 0 and
  updates ``last_triggered_at``.

Design notes
------------
* HMAC-SHA256 signing uses ``hmac.new(secret.encode(), payload_bytes, hashlib.sha256)``.
  The hex digest is sent in the ``X-Webhook-Signature`` header so receivers can
  verify authenticity without trusting the JSON body alone.
* ``json.dumps(payload, default=str)`` is used to serialise the payload so that
  Python :class:`~datetime.datetime` and :class:`~decimal.Decimal` values are
  coerced to strings rather than raising ``TypeError``.
* ``httpx`` (already a project dependency) is used for the HTTP POST with a
  10-second total timeout.
* The task uses ``bind=True`` to access ``self.retry()`` for Celery's built-in
  retry mechanism.  Countdown values (10, 30, 60 seconds) implement the
  exponential back-off schedule.
* All DB access is lazy-imported inside the async body (``# noqa: PLC0415``) to
  avoid circular import chains at Celery worker startup.
* ``max_retries=3`` — after three failed attempts the ``exc`` argument of
  ``self.retry`` propagates and the ``on_failure`` path executes.

Example (manual trigger)::

    from src.tasks.webhook_tasks import dispatch_webhook
    result = dispatch_webhook.delay(
        subscription_id="uuid-string",
        url="https://example.com/hooks",
        event_name="order.filled",
        payload={"order_id": "..."},
    )
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlparse

import structlog

from src.tasks.celery_app import app

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Subscriptions are auto-disabled after this many consecutive failures.
_MAX_FAILURES: int = 10

#: Countdown (seconds) for each retry attempt: 1st → 10 s, 2nd → 30 s, 3rd → 60 s.
_RETRY_COUNTDOWNS: tuple[int, ...] = (10, 30, 60)

#: HTTP timeout for the webhook POST request (seconds).
_HTTP_TIMEOUT: float = 10.0


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="src.tasks.webhook_tasks.dispatch_webhook",
    bind=True,
    max_retries=3,
    ignore_result=True,
)
def dispatch_webhook(
    self: Any,  # noqa: ANN401
    subscription_id: str,
    url: str,
    event_name: str,
    payload: dict,  # type: ignore[type-arg]
) -> dict[str, Any]:
    """Sign and POST a webhook payload to a subscriber's endpoint.

    Fetches the HMAC signing secret from the DB at dispatch time (not from the
    task arguments) to prevent the secret from being written to the Celery
    result backend in plaintext.

    Computes an HMAC-SHA256 signature over the JSON-serialised payload and
    sends it via HTTP POST.  Retries up to 3 times with exponential back-off
    (10 s, 30 s, 60 s) on any delivery failure.

    On successful delivery:

    * ``failure_count`` is reset to 0.
    * ``last_triggered_at`` is updated to the current UTC time.

    On final failure (all retries exhausted):

    * ``failure_count`` is incremented by 1.
    * If ``failure_count`` reaches :data:`_MAX_FAILURES`, ``active`` is set to
      ``False`` (subscription auto-disabled).

    If the subscription has been deleted between enqueue and dispatch, the task
    logs a warning and returns without making any HTTP request.

    Args:
        self:            Celery task instance (injected via ``bind=True``).
        subscription_id: String UUID of the :class:`~src.database.models.WebhookSubscription`.
        url:             Destination HTTPS endpoint.
        event_name:      Dot-separated event identifier (e.g. ``"order.filled"``).
        payload:         JSON-serialisable event data dict.

    Returns:
        A dict with keys:

        * ``subscription_id`` — echoed from args.
        * ``event_name``      — echoed from args.
        * ``status_code``     — HTTP status code returned by the endpoint.
        * ``duration_ms``     — wall-clock delivery time in milliseconds.

    Raises:
        :class:`celery.exceptions.Retry` — raised internally by ``self.retry()``
        to schedule the next attempt; Celery intercepts this and does not
        propagate it to the caller.
    """
    return asyncio.run(_async_dispatch(self, subscription_id, url, event_name, payload))


async def _async_dispatch(
    task: Any,  # noqa: ANN401
    subscription_id: str,
    url: str,
    event_name: str,
    payload: dict,  # type: ignore[type-arg]
) -> dict[str, Any]:
    """Async implementation of :func:`dispatch_webhook`.

    Fetches the HMAC signing secret from the DB so it is never stored in the
    Celery result backend.  Returns early with a warning log if the subscription
    has been deleted between enqueue and dispatch.

    Args:
        task:            The bound Celery task instance (for retry / retry_count).
        subscription_id: String UUID of the subscription.
        url:             Destination endpoint.
        event_name:      Event identifier.
        payload:         Event data.

    Returns:
        Delivery result dict (same shape as :func:`dispatch_webhook`).
    """
    from uuid import UUID  # noqa: PLC0415

    import httpx  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from src.database.models import WebhookSubscription  # noqa: PLC0415
    from src.database.session import get_session_factory  # noqa: PLC0415

    session_factory = get_session_factory()

    # ── Fetch secret from DB ─────────────────────────────────────────────────
    # The secret is intentionally NOT passed via Celery task arguments because
    # task arguments are serialised as plaintext JSON in the Redis result
    # backend.  Fetching from DB at dispatch time keeps the secret off the wire.
    try:
        async with session_factory() as _session:
            _result = await _session.execute(
                select(WebhookSubscription.secret).where(WebhookSubscription.id == UUID(subscription_id))
            )
            row = _result.one_or_none()
    except Exception:
        logger.exception(
            "webhook.dispatch.secret_fetch_failed",
            subscription_id=subscription_id,
        )
        return {
            "subscription_id": subscription_id,
            "event_name": event_name,
            "status_code": 0,
            "duration_ms": 0,
            "success": False,
        }

    if row is None:
        logger.warning(
            "webhook.dispatch.subscription_not_found",
            subscription_id=subscription_id,
            event_name=event_name,
        )
        return {
            "subscription_id": subscription_id,
            "event_name": event_name,
            "status_code": 0,
            "duration_ms": 0,
            "success": False,
        }

    secret: str = row.secret

    # ── Defence-in-depth SSRF check ──────────────────────────────────────────
    # This re-validates the URL immediately before delivery.  It catches URLs
    # that were stored in the DB before SSRF protection was introduced, or that
    # somehow bypassed schema validation.
    # NOTE: DNS rebinding is NOT fully mitigated — the hostname is resolved
    # here at task execution time, but an adversary could still switch DNS
    # records between this resolution and the actual httpx.post() call below.
    # This check closes the window against opportunistic attacks rather than
    # eliminating the race entirely.
    from src.webhooks.dispatcher import validate_webhook_url  # noqa: PLC0415

    try:
        validate_webhook_url(url)
    except ValueError:
        logger.warning(
            "webhook.delivery.ssrf_blocked",
            subscription_id=subscription_id,
            event_name=event_name,
            url_host=urlparse(url).netloc,  # full URL logged for security forensics
        )
        return {
            "subscription_id": subscription_id,
            "event_name": event_name,
            "status_code": 0,
            "duration_ms": 0,
            "success": False,
        }

    # ── Serialise payload ────────────────────────────────────────────────────
    payload_bytes: bytes = json.dumps(payload, default=str).encode("utf-8")

    # ── Compute HMAC-SHA256 signature ────────────────────────────────────────
    signature: str = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()

    # ── Attempt HTTP delivery ────────────────────────────────────────────────
    start = time.monotonic()
    status_code: int = 0

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            response = await client.post(
                url,
                content=payload_bytes,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": signature,
                    "X-Webhook-Event": event_name,
                },
            )
            status_code = response.status_code
            response.raise_for_status()

    except (httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException) as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        retry_index = task.request.retries  # 0-based current retry count
        logger.warning(
            "webhook.delivery.failed",
            subscription_id=subscription_id,
            event_name=event_name,
            url_host=urlparse(url).netloc,
            status_code=status_code,
            retry=retry_index,
            duration_ms=duration_ms,
            error=str(exc),
        )

        # Schedule next retry if attempts remain; otherwise record final failure.
        if retry_index < len(_RETRY_COUNTDOWNS):
            countdown = _RETRY_COUNTDOWNS[retry_index]
            raise task.retry(exc=exc, countdown=countdown) from exc

        # All retries exhausted — update failure_count in DB and possibly disable.
        await _record_failure(subscription_id, session_factory)
        return {
            "subscription_id": subscription_id,
            "event_name": event_name,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "success": False,
        }

    # ── Success path ─────────────────────────────────────────────────────────
    duration_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "webhook.delivery.success",
        subscription_id=subscription_id,
        event_name=event_name,
        url_host=urlparse(url).netloc,
        status_code=status_code,
        duration_ms=duration_ms,
    )

    await _record_success(subscription_id, session_factory)

    return {
        "subscription_id": subscription_id,
        "event_name": event_name,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "success": True,
    }


# ---------------------------------------------------------------------------
# DB helpers (called after HTTP attempt)
# ---------------------------------------------------------------------------


async def _record_success(subscription_id: str, session_factory: Any) -> None:  # noqa: ANN401
    """Reset failure_count and update last_triggered_at after a successful delivery.

    Args:
        subscription_id: String UUID of the :class:`~src.database.models.WebhookSubscription`.
        session_factory: Async session factory (``async_sessionmaker``).
    """
    from datetime import UTC, datetime  # noqa: PLC0415
    from uuid import UUID  # noqa: PLC0415

    from sqlalchemy import update  # noqa: PLC0415

    from src.database.models import WebhookSubscription  # noqa: PLC0415

    try:
        async with session_factory() as session:
            await session.execute(
                update(WebhookSubscription)
                .where(WebhookSubscription.id == UUID(subscription_id))
                .values(
                    failure_count=0,
                    last_triggered_at=datetime.now(UTC),
                )
            )
            await session.commit()
    except Exception:
        logger.exception(
            "webhook.db.success_update_failed",
            subscription_id=subscription_id,
        )


async def _record_failure(subscription_id: str, session_factory: Any) -> None:  # noqa: ANN401
    """Increment failure_count and auto-disable the subscription if the threshold is reached.

    If ``failure_count + 1 >= _MAX_FAILURES`` the subscription is also set to
    ``active=False`` so no further deliveries are attempted until an operator
    re-enables it.

    Args:
        subscription_id: String UUID of the :class:`~src.database.models.WebhookSubscription`.
        session_factory: Async session factory (``async_sessionmaker``).
    """
    from datetime import UTC, datetime  # noqa: PLC0415
    from uuid import UUID  # noqa: PLC0415

    from sqlalchemy import select, update  # noqa: PLC0415

    from src.database.models import WebhookSubscription  # noqa: PLC0415

    try:
        async with session_factory() as session:
            result = await session.execute(
                select(WebhookSubscription.failure_count).where(WebhookSubscription.id == UUID(subscription_id))
            )
            row = result.one_or_none()
            if row is None:
                return

            new_count: int = row.failure_count + 1
            values: dict[str, Any] = {
                "failure_count": new_count,
                "last_triggered_at": datetime.now(UTC),
            }
            if new_count >= _MAX_FAILURES:
                values["active"] = False
                logger.warning(
                    "webhook.subscription.auto_disabled",
                    subscription_id=subscription_id,
                    failure_count=new_count,
                )

            await session.execute(
                update(WebhookSubscription).where(WebhookSubscription.id == UUID(subscription_id)).values(**values)
            )
            await session.commit()

    except Exception:
        logger.exception(
            "webhook.db.failure_update_failed",
            subscription_id=subscription_id,
        )
