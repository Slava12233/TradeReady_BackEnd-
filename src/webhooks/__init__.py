"""Webhook dispatcher package for the AI Agent Crypto Trading Platform.

Provides :func:`fire_event` which fans out a platform event to all active
:class:`~src.database.models.WebhookSubscription` rows that subscribe to the
given event name.  Each matching subscription is handed off to a Celery worker
via :func:`~src.tasks.webhook_tasks.dispatch_webhook` so the HTTP delivery
does not block the caller.

:func:`validate_webhook_url` is exported for use by Pydantic schema validators
and by the Celery task as defence-in-depth SSRF protection.

Example::

    from src.webhooks import fire_event, validate_webhook_url
    await fire_event(account_id, "order.filled", payload, db)
"""

from src.webhooks.dispatcher import fire_event, validate_webhook_url

__all__ = ["fire_event", "validate_webhook_url"]
