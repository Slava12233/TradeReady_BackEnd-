"""Webhook subscription management routes.

Implements 6 endpoints:

- ``POST   /api/v1/webhooks``               — create subscription (returns secret once)
- ``GET    /api/v1/webhooks``               — list subscriptions (secret omitted)
- ``GET    /api/v1/webhooks/{webhook_id}``  — get detail (secret omitted)
- ``PUT    /api/v1/webhooks/{webhook_id}``  — update url / events / active / description
- ``DELETE /api/v1/webhooks/{webhook_id}``  — delete subscription
- ``POST   /api/v1/webhooks/{webhook_id}/test`` — fire a test event

All endpoints require authentication (JWT or API key).
"""

from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select, update
import structlog

from src.api.middleware.auth import CurrentAccountDep
from src.api.schemas.webhooks import (
    WebhookCreateRequest,
    WebhookCreateResponse,
    WebhookListResponse,
    WebhookResponse,
    WebhookUpdateRequest,
)
from src.database.models import WebhookSubscription
from src.dependencies import DbSessionDep
from src.utils.exceptions import PermissionDeniedError

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sub_to_response(sub: WebhookSubscription) -> WebhookResponse:
    """Convert a :class:`~src.database.models.WebhookSubscription` ORM row to a response schema.

    Args:
        sub: An ORM ``WebhookSubscription`` instance.

    Returns:
        A :class:`WebhookResponse` with all public fields populated.
    """
    return WebhookResponse(
        id=sub.id,
        url=sub.url,
        events=list(sub.events),
        description=sub.description,
        active=sub.active,
        failure_count=sub.failure_count,
        created_at=sub.created_at,
        updated_at=sub.updated_at,
        last_triggered_at=sub.last_triggered_at,
    )


async def _get_owned_sub(
    webhook_id: UUID,
    account_id: UUID,
    db: DbSessionDep,
) -> WebhookSubscription:
    """Fetch a subscription and verify ownership.

    Args:
        webhook_id: UUID of the webhook subscription.
        account_id: UUID of the requesting account.
        db:         Active async SQLAlchemy session.

    Returns:
        The matching :class:`~src.database.models.WebhookSubscription` row.

    Raises:
        HTTPException: 404 if no subscription with ``webhook_id`` exists.
        PermissionDeniedError: If the subscription belongs to a different account.
    """
    stmt = select(WebhookSubscription).where(WebhookSubscription.id == webhook_id)
    result = await db.execute(stmt)
    sub = result.scalars().first()
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Webhook subscription '{webhook_id}' not found.",
        )
    if sub.account_id != account_id:
        raise PermissionDeniedError(
            message="You do not own this webhook subscription.",
        )
    return sub


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=WebhookCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    body: WebhookCreateRequest,
    account: CurrentAccountDep,
    db: DbSessionDep,
) -> WebhookCreateResponse:
    """Create a new webhook subscription.

    Generates an HMAC-SHA256 signing secret and returns it **once**.
    The caller must store it immediately; it cannot be retrieved again.

    Args:
        body:    Validated request body with url, events, and optional description.
        account: Authenticated account (injected by middleware).
        db:      Per-request async DB session.

    Returns:
        :class:`WebhookCreateResponse` including the one-time ``secret``.
    """
    secret = secrets.token_urlsafe(32)
    sub = WebhookSubscription(
        account_id=account.id,
        url=body.url,
        events=body.events,
        secret=secret,
        description=body.description,
        active=True,
        failure_count=0,
    )
    db.add(sub)
    await db.flush()  # get server-default UUID and timestamps
    await db.commit()

    logger.info(
        "webhook.created",
        account_id=str(account.id),
        webhook_id=str(sub.id),
        events=body.events,
    )

    return WebhookCreateResponse(
        id=sub.id,
        url=sub.url,
        events=list(sub.events),
        description=sub.description,
        active=sub.active,
        secret=secret,
        created_at=sub.created_at,
    )


@router.get("", response_model=WebhookListResponse)
async def list_webhooks(
    account: CurrentAccountDep,
    db: DbSessionDep,
) -> WebhookListResponse:
    """List all webhook subscriptions for the authenticated account.

    Args:
        account: Authenticated account (injected by middleware).
        db:      Per-request async DB session.

    Returns:
        :class:`WebhookListResponse` with a list of subscriptions and total count.
    """
    stmt = (
        select(WebhookSubscription)
        .where(WebhookSubscription.account_id == account.id)
        .order_by(WebhookSubscription.created_at.desc())
    )
    result = await db.execute(stmt)
    subs = result.scalars().all()

    count_stmt = select(func.count()).select_from(WebhookSubscription).where(
        WebhookSubscription.account_id == account.id
    )
    count_result = await db.execute(count_stmt)
    total: int = count_result.scalar_one()

    return WebhookListResponse(
        webhooks=[_sub_to_response(s) for s in subs],
        total=total,
    )


@router.get("/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(
    webhook_id: UUID,
    account: CurrentAccountDep,
    db: DbSessionDep,
) -> WebhookResponse:
    """Get detail for a single webhook subscription.

    Args:
        webhook_id: UUID of the subscription.
        account:    Authenticated account (injected by middleware).
        db:         Per-request async DB session.

    Returns:
        :class:`WebhookResponse` for the requested subscription.

    Raises:
        HTTPException: 404 if the subscription does not exist.
        PermissionDeniedError: If the subscription belongs to another account.
    """
    sub = await _get_owned_sub(webhook_id, account.id, db)
    return _sub_to_response(sub)


@router.put("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: UUID,
    body: WebhookUpdateRequest,
    account: CurrentAccountDep,
    db: DbSessionDep,
) -> WebhookResponse:
    """Update a webhook subscription.

    Accepts partial updates: only fields present in the request body are changed.

    Args:
        webhook_id: UUID of the subscription.
        body:       Partial update body (url, events, active, description).
        account:    Authenticated account (injected by middleware).
        db:         Per-request async DB session.

    Returns:
        Updated :class:`WebhookResponse`.

    Raises:
        HTTPException: 404 if the subscription does not exist.
        PermissionDeniedError: If the subscription belongs to another account.
    """
    sub = await _get_owned_sub(webhook_id, account.id, db)

    values: dict[str, object] = {}
    if body.url is not None:
        values["url"] = body.url
    if body.events is not None:
        values["events"] = body.events
    if body.active is not None:
        values["active"] = body.active
    if body.description is not None:
        values["description"] = body.description

    if values:
        stmt = (
            update(WebhookSubscription)
            .where(WebhookSubscription.id == webhook_id)
            .values(**values)
            .returning(WebhookSubscription)
        )
        result = await db.execute(stmt)
        updated = result.scalars().first()
        await db.commit()
        if updated is not None:
            sub = updated

    logger.info(
        "webhook.updated",
        account_id=str(account.id),
        webhook_id=str(webhook_id),
        fields=list(values.keys()),
    )

    return _sub_to_response(sub)


@router.delete(
    "/{webhook_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_webhook(
    webhook_id: UUID,
    account: CurrentAccountDep,
    db: DbSessionDep,
) -> Response:
    """Delete a webhook subscription.

    Args:
        webhook_id: UUID of the subscription to delete.
        account:    Authenticated account (injected by middleware).
        db:         Per-request async DB session.

    Returns:
        Empty 204 response on success.

    Raises:
        HTTPException: 404 if the subscription does not exist.
        PermissionDeniedError: If the subscription belongs to another account.
    """
    sub = await _get_owned_sub(webhook_id, account.id, db)
    await db.delete(sub)
    await db.commit()

    logger.info(
        "webhook.deleted",
        account_id=str(account.id),
        webhook_id=str(webhook_id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{webhook_id}/test", response_model=dict)
async def test_webhook(
    webhook_id: UUID,
    account: CurrentAccountDep,
    db: DbSessionDep,
) -> dict:  # type: ignore[type-arg]
    """Send a test event payload to the webhook endpoint.

    Enqueues a ``webhook.test`` delivery task directly for the specified
    subscription so the subscriber can verify their endpoint receives and
    validates HMAC-SHA256 signatures correctly.  The subscription does not
    need to include ``"webhook.test"`` in its event list.

    Args:
        webhook_id: UUID of the subscription to test.
        account:    Authenticated account (injected by middleware).
        db:         Per-request async DB session.

    Returns:
        Dict with ``enqueued`` count and ``webhook_id``.

    Raises:
        HTTPException: 404 if the subscription does not exist.
        PermissionDeniedError: If the subscription belongs to another account.
    """
    from src.tasks.webhook_tasks import dispatch_webhook  # noqa: PLC0415

    sub = await _get_owned_sub(webhook_id, account.id, db)

    payload = {
        "event": "webhook.test",
        "webhook_id": str(webhook_id),
        "message": "This is a test event from the AgentExchange platform.",
    }

    dispatch_webhook.delay(
        subscription_id=str(sub.id),
        url=sub.url,
        secret=sub.secret,
        event_name="webhook.test",
        payload=payload,
    )

    logger.info(
        "webhook.test_fired",
        account_id=str(account.id),
        webhook_id=str(webhook_id),
    )

    return {"enqueued": 1, "webhook_id": str(webhook_id)}
