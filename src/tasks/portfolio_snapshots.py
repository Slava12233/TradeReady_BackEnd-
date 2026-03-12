"""Celery tasks: portfolio snapshot capture and circuit breaker reset — Component 6.

Four tasks are exported, matching the beat schedule defined in
``src/tasks/celery_app.py``:

* :func:`capture_minute_snapshots`   — every 60 s; equity-only snapshot for all
  active accounts.
* :func:`capture_hourly_snapshots`   — every 3 600 s; equity + positions.
* :func:`capture_daily_snapshots`    — midnight UTC; equity + positions + full
  performance metrics.
* :func:`reset_circuit_breakers`     — midnight UTC (after daily snapshots);
  clears all per-account daily PnL accumulators so fresh totals start for the
  new calendar day.

Each task bridges the synchronous Celery boundary to the fully async service
layer via :func:`asyncio.run`.  A short-lived database session factory and
Redis client are created per invocation so tasks remain stateless and
reentrant.

All active accounts are processed in a single asyncio event loop per
invocation. Failures for individual accounts are logged but do not abort
processing of remaining accounts (fail-isolated-per-account). A final
summary dict is returned to the Celery result backend.

Example (manual trigger)::

    from src.tasks.portfolio_snapshots import capture_minute_snapshots
    result = capture_minute_snapshots.delay()
    print(result.get(timeout=30))
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.tasks.celery_app import app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Celery task definitions
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="src.tasks.portfolio_snapshots.capture_minute_snapshots",
    bind=True,
    max_retries=0,
    ignore_result=False,
)
def capture_minute_snapshots(self: Any) -> dict[str, Any]:  # noqa: ANN401
    """Capture equity-only snapshots for every active account.

    Runs every 60 seconds via Celery beat.  Each snapshot records only the
    current total equity and cash/position breakdown — no positions JSON or
    metrics are written, keeping the write volume low.

    Returns:
        A dict with keys ``snapshot_type``, ``accounts_processed``,
        ``accounts_failed``, and ``duration_ms``.

    Raises:
        Exception: Any unhandled exception at the task level is logged and
            re-raised so Celery can record it.  Per-account failures are
            isolated and do not raise.

    Example::

        result = capture_minute_snapshots.delay()
        stats = result.get(timeout=30)
        print(f"Processed {stats['accounts_processed']} accounts")
    """
    return asyncio.run(_run_snapshots("minute"))


@app.task(  # type: ignore[misc]
    name="src.tasks.portfolio_snapshots.capture_hourly_snapshots",
    bind=True,
    max_retries=0,
    ignore_result=False,
)
def capture_hourly_snapshots(self: Any) -> dict[str, Any]:  # noqa: ANN401
    """Capture equity + positions snapshots for every active account.

    Runs every 3 600 seconds via Celery beat.  Serialises each account's
    current open positions to JSONB alongside the equity summary.

    Returns:
        A dict with keys ``snapshot_type``, ``accounts_processed``,
        ``accounts_failed``, and ``duration_ms``.

    Raises:
        Exception: Any unhandled exception at the task level is logged and
            re-raised so Celery can record it.  Per-account failures are
            isolated and do not raise.

    Example::

        result = capture_hourly_snapshots.delay()
        stats = result.get(timeout=60)
        print(f"Processed {stats['accounts_processed']} accounts")
    """
    return asyncio.run(_run_snapshots("hourly"))


@app.task(  # type: ignore[misc]
    name="src.tasks.portfolio_snapshots.capture_daily_snapshots",
    bind=True,
    max_retries=0,
    ignore_result=False,
    # Daily tasks may take longer if there are many accounts with rich histories.
    soft_time_limit=110,
    time_limit=120,
)
def capture_daily_snapshots(self: Any) -> dict[str, Any]:  # noqa: ANN401
    """Capture full performance snapshots for every active account.

    Runs once per UTC calendar day at midnight (via Celery beat crontab).
    Each snapshot includes equity, serialised positions, and a complete
    :class:`~src.portfolio.metrics.Metrics` dict covering the account's
    entire trading history.

    Returns:
        A dict with keys ``snapshot_type``, ``accounts_processed``,
        ``accounts_failed``, and ``duration_ms``.

    Raises:
        Exception: Any unhandled exception at the task level is logged and
            re-raised so Celery can record it.  Per-account failures are
            isolated and do not raise.

    Example::

        result = capture_daily_snapshots.delay()
        stats = result.get(timeout=120)
        print(f"Processed {stats['accounts_processed']} accounts")
    """
    return asyncio.run(_run_snapshots("daily"))


@app.task(  # type: ignore[misc]
    name="src.tasks.portfolio_snapshots.reset_circuit_breakers",
    bind=True,
    max_retries=0,
    ignore_result=False,
)
def reset_circuit_breakers(self: Any) -> dict[str, Any]:  # noqa: ANN401
    """Reset all per-account circuit-breaker keys at the start of a new UTC day.

    Calls :meth:`~src.risk.circuit_breaker.CircuitBreaker.reset_all` which
    performs a Redis SCAN + DEL sweep to remove every
    ``circuit_breaker:{account_id}`` key.  After the reset, each account's
    daily PnL accumulator starts fresh for the new calendar day.

    Runs at midnight UTC via Celery beat (a separate entry from
    ``capture-daily-snapshots`` so failures are isolated and both tasks still
    run even if one errors).

    Returns:
        A dict with keys ``keys_deleted`` and ``duration_ms``.

    Example::

        result = reset_circuit_breakers.delay()
        stats = result.get(timeout=30)
        print(f"Deleted {stats['keys_deleted']} circuit-breaker keys")
    """
    return asyncio.run(_reset_circuit_breakers())


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------


async def _run_snapshots(snapshot_type: str) -> dict[str, Any]:
    """Async body shared by all three snapshot tasks.

    Loads all active account IDs then iterates through them, capturing a
    snapshot of the requested *snapshot_type* for each one.  Accounts are
    processed sequentially with isolated sessions so that a failure on one
    account does not roll back progress for the others.

    Args:
        snapshot_type: One of ``"minute"``, ``"hourly"``, or ``"daily"``.

    Returns:
        Serialisable summary dict suitable for the Celery result backend.
    """
    import time

    from src.cache.price_cache import PriceCache
    from src.cache.redis_client import RedisClient
    from src.config import get_settings
    from src.database.session import get_session_factory
    from src.portfolio.snapshots import SnapshotService

    start_ms = time.monotonic() * 1000
    settings = get_settings()

    redis_client = RedisClient(url=settings.redis_url)
    await redis_client.connect()

    session_factory = get_session_factory()
    price_cache = PriceCache(redis=redis_client.get_client())

    accounts_processed = 0
    accounts_failed = 0

    try:
        account_ids = await _load_active_account_ids(session_factory)

        logger.info(
            "portfolio_snapshots.started",
            extra={
                "snapshot_type": snapshot_type,
                "total_accounts": len(account_ids),
            },
        )

        for account_id in account_ids:
            try:
                async with session_factory() as session:
                    svc = SnapshotService(
                        session=session,
                        price_cache=price_cache,
                        settings=settings,
                    )
                    await _capture(svc, snapshot_type, account_id)
                    await session.commit()
                accounts_processed += 1
            except Exception:
                accounts_failed += 1
                logger.exception(
                    "portfolio_snapshots.account_error",
                    extra={
                        "snapshot_type": snapshot_type,
                        "account_id": str(account_id),
                    },
                )

    except Exception:
        logger.exception(
            "portfolio_snapshots.fatal_error",
            extra={"snapshot_type": snapshot_type},
        )
        raise
    finally:
        await redis_client.disconnect()

    duration_ms = round(time.monotonic() * 1000 - start_ms, 2)
    logger.info(
        "portfolio_snapshots.finished",
        extra={
            "snapshot_type": snapshot_type,
            "accounts_processed": accounts_processed,
            "accounts_failed": accounts_failed,
            "duration_ms": duration_ms,
        },
    )
    return {
        "snapshot_type": snapshot_type,
        "accounts_processed": accounts_processed,
        "accounts_failed": accounts_failed,
        "duration_ms": duration_ms,
    }


async def _load_active_account_ids(session_factory: Any) -> list[Any]:  # noqa: ANN401
    """Return the UUIDs of all accounts with status ``"active"``.

    Uses a single short-lived session to page through all active accounts in
    batches of 1 000 and collect their IDs.  Returning only UUIDs keeps peak
    memory low regardless of the total account count.

    Args:
        session_factory: Async session factory (from
            :func:`~src.database.session.get_session_factory`).

    Returns:
        Flat list of :class:`~uuid.UUID` values.
    """

    from src.database.repositories.account_repo import AccountRepository  # noqa: PLC0415

    ids: list[Any] = []
    batch_size = 1000
    offset = 0

    async with session_factory() as session:
        repo = AccountRepository(session)
        while True:
            batch = await repo.list_by_status(
                "active",
                limit=batch_size,
                offset=offset,
            )
            if not batch:
                break
            ids.extend(account.id for account in batch)
            if len(batch) < batch_size:
                break
            offset += batch_size

    return ids


async def _capture(
    svc: Any,  # noqa: ANN401
    snapshot_type: str,
    account_id: Any,  # noqa: ANN401
) -> None:
    """Dispatch to the correct :class:`~src.portfolio.snapshots.SnapshotService`
    capture method based on *snapshot_type*.

    Args:
        svc:           Initialised :class:`~src.portfolio.snapshots.SnapshotService`.
        snapshot_type: ``"minute"``, ``"hourly"``, or ``"daily"``.
        account_id:    UUID of the account to capture.

    Raises:
        ValueError: If *snapshot_type* is not a recognised value.
    """
    if snapshot_type == "minute":
        await svc.capture_minute_snapshot(account_id)
    elif snapshot_type == "hourly":
        await svc.capture_hourly_snapshot(account_id)
    elif snapshot_type == "daily":
        await svc.capture_daily_snapshot(account_id)
    else:
        raise ValueError(f"Unknown snapshot_type: {snapshot_type!r}")


async def _reset_circuit_breakers() -> dict[str, Any]:
    """Async body for :func:`reset_circuit_breakers`.

    Creates a short-lived Redis client, calls
    :meth:`~src.risk.circuit_breaker.CircuitBreaker.reset_all` to perform a
    SCAN + DEL sweep of all ``circuit_breaker:*`` keys, then disconnects.

    Returns:
        Serialisable summary dict with ``duration_ms``.
    """
    import time

    from src.cache.redis_client import RedisClient
    from src.config import get_settings
    from src.risk.circuit_breaker import CircuitBreaker

    start_ms = time.monotonic() * 1000
    settings = get_settings()

    redis_client = RedisClient(url=settings.redis_url)
    await redis_client.connect()

    try:
        cb = CircuitBreaker(redis=redis_client.get_client())
        await cb.reset_all()
    except Exception:
        logger.exception("circuit_breaker.reset_all.error")
        raise
    finally:
        await redis_client.disconnect()

    duration_ms = round(time.monotonic() * 1000 - start_ms, 2)
    return {"duration_ms": duration_ms}
