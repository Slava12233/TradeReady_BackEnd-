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
* :func:`validate_webhook_url` provides SSRF protection by resolving the
  hostname and rejecting any IP address that falls in a private/loopback/
  link-local/cloud-metadata range.  DNS rebinding is NOT fully mitigated — a
  hostname that resolves to a public IP at validation time could resolve to a
  private IP at delivery time.  An additional check in the Celery task provides
  defence-in-depth but the same race condition applies there too.
"""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.parse
from uuid import UUID

from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# SSRF-blocked IP networks
# ---------------------------------------------------------------------------

#: All IPv4/IPv6 networks whose addresses must never be targeted by webhooks.
_BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.IPv4Network("127.0.0.0/8"),  # IPv4 loopback
    ipaddress.IPv6Network("::1/128"),  # IPv6 loopback
    ipaddress.IPv4Network("169.254.0.0/16"),  # IPv4 link-local / AWS metadata
    ipaddress.IPv6Network("fe80::/10"),  # IPv6 link-local
    ipaddress.IPv4Network("10.0.0.0/8"),  # RFC-1918 private class A
    ipaddress.IPv4Network("172.16.0.0/12"),  # RFC-1918 private class B
    ipaddress.IPv4Network("192.168.0.0/16"),  # RFC-1918 private class C
    ipaddress.IPv4Network("172.17.0.0/16"),  # Docker bridge default subnet
)


def validate_webhook_url(url: str) -> str:
    """Validate a webhook URL for SSRF safety and return it if valid.

    Checks performed (in order):

    1. Scheme must be ``https`` — ``http`` and all other schemes are rejected to
       prevent downgrade attacks and ensure transport-layer encryption.
    2. Hostname must be present and must **not** be a bare IP address string —
       callers must use a resolvable hostname so there is at least one DNS hop
       that can be controlled by network policy.
    3. The hostname is resolved via :func:`socket.getaddrinfo` and every
       resulting IP address is checked against :data:`_BLOCKED_NETWORKS`.  All
       resolved IPs must pass; a single match is sufficient to reject the URL.

    Limitation (DNS rebinding): the hostname is resolved at *validation time*.
    A malicious actor could serve a public IP during validation and switch the
    DNS record to a private IP before the actual HTTP request.  This check
    reduces opportunistic SSRF but does not eliminate the race.  The Celery
    task (:func:`~src.tasks.webhook_tasks._async_dispatch`) performs the same
    check immediately before delivery as defence-in-depth, but the same
    DNS-rebinding window applies there too.

    Args:
        url: The raw URL string to validate.

    Returns:
        The original ``url`` string if all checks pass.

    Raises:
        ValueError: With a human-readable message if the URL fails any check.
    """
    parsed = urllib.parse.urlparse(url)

    # 1. Scheme check — only https is permitted.
    if parsed.scheme != "https":
        raise ValueError(f"Webhook URL must use the https scheme; got {parsed.scheme!r}.")

    # 2. Hostname presence check.
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Webhook URL must contain a valid hostname.")

    # 3. Reject bare IP address literals — callers must use a resolvable hostname.
    try:
        ipaddress.ip_address(hostname)
        # If ip_address() succeeds the input IS a bare IP — reject it.
        raise ValueError(f"Webhook URL must use a hostname, not a bare IP address: {hostname!r}.")
    except ValueError as exc:
        # ip_address() raises ValueError when the string is NOT a valid IP,
        # meaning the hostname is a DNS name — exactly what we want.
        # Re-raise only when we raised it ourselves (bare-IP branch above).
        if "bare IP address" in str(exc):
            raise

    # 4. Resolve hostname and verify no returned IP is in a blocked network.
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        raise ValueError(f"Webhook URL hostname {hostname!r} could not be resolved: {exc}") from exc

    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            # Malformed address returned by the OS — skip rather than trust it.
            continue

        for network in _BLOCKED_NETWORKS:
            if ip in network:
                raise ValueError(
                    f"Webhook URL hostname {hostname!r} resolves to a blocked "
                    f"IP address ({ip}) in restricted network {network}. "
                    "Internal and cloud-metadata endpoints are not allowed as "
                    "webhook targets."
                )

    return url


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
    task is enqueued with the subscription id, url, event name, and serialised
    payload.  The HMAC signing secret is fetched inside the task from the DB so
    it is never stored in the Celery result backend.

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
            WebhookSubscription.events.cast(JSONB).contains(cast(json.dumps([event_name]), JSONB)),
        )
        result = await db.execute(stmt)
        subscriptions = result.scalars().all()

        for sub in subscriptions:
            try:
                dispatch_webhook.delay(
                    subscription_id=str(sub.id),
                    url=sub.url,
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
