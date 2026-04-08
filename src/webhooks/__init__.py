"""Webhook dispatcher package for the AI Agent Crypto Trading Platform.

Provides :func:`fire_event` which fans out a platform event to all active
:class:`~src.database.models.WebhookSubscription` rows that subscribe to the
given event name.  Each matching subscription is handed off to a Celery worker
via :func:`~src.tasks.webhook_tasks.dispatch_webhook` so the HTTP delivery
does not block the caller.

Example::

    from src.webhooks import fire_event
    await fire_event(account_id, "order.filled", payload, db)
"""

from src.webhooks.dispatcher import fire_event

__all__ = ["fire_event"]
