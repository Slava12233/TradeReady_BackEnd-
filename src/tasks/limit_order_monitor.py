"""Celery task: limit order monitor — Component 4.

Wraps :func:`src.order_engine.matching.run_matcher_once` as a Celery task
scheduled by beat every 1 second.  Each invocation creates its own asyncio
event loop, connects to the database and Redis, runs a single sweep of all
pending limit / stop-loss / take-profit orders, then tears everything down.

Routing
-------
The task is routed to the ``high_priority`` queue (configured in
``src/tasks/celery_app.py``) so that the 1-second cadence is not delayed by
heavier tasks sharing the default queue.

Soft/hard time limits
---------------------
Inherited from the app-level defaults: 55 s soft / 60 s hard.  A single sweep
should complete well within 1–2 seconds under normal load; the limits are a
safety net for a pathological DB stall.

Example (manual trigger from a Python shell)::

    from src.tasks.limit_order_monitor import run_limit_order_monitor
    result = run_limit_order_monitor.delay()
    print(result.get(timeout=10))
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.tasks.celery_app import app

logger = logging.getLogger(__name__)


@app.task(  # type: ignore[misc]
    name="src.tasks.limit_order_monitor.run_limit_order_monitor",
    bind=True,
    max_retries=0,  # Do not retry on failure — beat will fire again in 1 s.
    queue="high_priority",
    ignore_result=False,
)
def run_limit_order_monitor(self: Any) -> dict[str, Any]:  # noqa: ANN401
    """Run one sweep of the limit order matcher synchronously.

    Celery workers are synchronous by default.  This task bridges the sync
    Celery boundary to the fully async matcher by running its own event loop
    via :func:`asyncio.run`.  A fresh database session factory and Redis
    client are created on each invocation so the task is stateless and can
    run safely on any worker process.

    Returns:
        A dict summary with keys: ``swept_at``, ``orders_checked``,
        ``orders_filled``, ``orders_errored``, ``duration_ms``.

    Raises:
        Exception: Any unhandled exception is logged and re-raised so Celery
            can record it in the result backend.  The task is *not* retried
            (``max_retries=0``); beat will simply schedule the next run 1 s
            later.

    Example::

        result = run_limit_order_monitor.delay()
        stats = result.get(timeout=10)
        print(f"Filled {stats['orders_filled']} orders")
    """
    return asyncio.run(_run_async())


async def _run_async() -> dict[str, Any]:
    """Async body of the Celery task.

    Builds all required singletons (settings, DB session factory, Redis
    client, PriceCache), calls :func:`~src.order_engine.matching.run_matcher_once`,
    then cleanly closes connections before returning the sweep statistics.

    Returns:
        Serialisable dict of :class:`~src.order_engine.matching.MatcherStats`
        fields.
    """
    from src.cache.price_cache import PriceCache
    from src.cache.redis_client import RedisClient
    from src.config import get_settings
    from src.database.session import get_session_factory
    from src.order_engine.matching import run_matcher_once

    settings = get_settings()

    # Build a short-lived Redis client and session factory for this sweep.
    redis_client = RedisClient(url=settings.redis_url)
    await redis_client.connect()

    session_factory = get_session_factory()
    price_cache = PriceCache(redis=redis_client.get_client())

    try:
        stats = await run_matcher_once(
            session_factory=session_factory,
            price_cache=price_cache,
            settings=settings,
        )
    except Exception:
        logger.exception("limit_order_monitor.unhandled_error")
        raise
    finally:
        await redis_client.disconnect()

    return {
        "swept_at": stats.swept_at.isoformat(),
        "orders_checked": stats.orders_checked,
        "orders_filled": stats.orders_filled,
        "orders_errored": stats.orders_errored,
        "duration_ms": round(stats.duration_ms, 2),
    }
