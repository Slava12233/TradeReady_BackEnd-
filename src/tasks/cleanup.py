"""Celery task: periodic data cleanup — expired orders, old snapshots, audit log.

Three cleanup operations are combined into a single daily Celery task
(``cleanup_old_data``) that runs at 01:00 UTC via beat schedule defined in
``src/tasks/celery_app.py``:

1. **Expired pending orders** — any order with status ``pending`` or
   ``partially_filled`` and a ``created_at`` older than
   :data:`_STALE_ORDER_DAYS` days (default 7) is transitioned to
   ``"expired"``.  Locked funds for those orders are *not* automatically
   unlocked here — a separate manual admin action or account-reset flow should
   handle balance recovery.  The cleanup merely prevents the limit-order
   matcher from checking orders that will never fill.

2. **Old minute-resolution snapshots** — ``portfolio_snapshots`` rows with
   ``snapshot_type = "minute"`` older than :data:`_MINUTE_SNAPSHOT_DAYS` days
   (default 7) are deleted account-by-account using the existing
   :meth:`~src.database.repositories.snapshot_repo.SnapshotRepository.delete_before`
   helper.  Hourly and daily snapshots are kept indefinitely.

3. **Audit log archival** — ``audit_log`` rows older than
   :data:`_AUDIT_LOG_DAYS` days (default 30) are bulk-deleted.  The audit log
   is append-only and grows without bound; pruning old entries keeps query
   performance acceptable.

Design notes
------------
* All three phases run inside the same ``asyncio.run`` invocation and share a
  single settings object and database session-factory.  Redis is *not* needed
  for this task, so no Redis client is opened.
* Each phase is fail-isolated: an exception in one phase is logged but does
  not abort the remaining phases.
* For snapshot cleanup, accounts are processed in batches of 500 IDs at a
  time.  Each account uses its own short-lived session so that a single
  bad account cannot roll back progress for others.
* Stale-order expiry uses a single bulk ``UPDATE`` across all accounts for
  efficiency (no per-account loop required).

Example (manual trigger)::

    from src.tasks.cleanup import cleanup_old_data
    result = cleanup_old_data.delay()
    print(result.get(timeout=120))
"""

from __future__ import annotations

import asyncio
from datetime import UTC
import logging
import time
from typing import Any

from src.tasks.celery_app import app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retention constants (days)
# ---------------------------------------------------------------------------

#: Pending orders older than this many days are transitioned to ``"expired"``.
_STALE_ORDER_DAYS: int = 7

#: Minute-resolution portfolio snapshots older than this many days are pruned.
_MINUTE_SNAPSHOT_DAYS: int = 7

#: Audit log entries older than this many days are deleted.
_AUDIT_LOG_DAYS: int = 30

#: Account batch size when iterating accounts for snapshot pruning.
_ACCOUNT_BATCH_SIZE: int = 500


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@app.task(
    name="src.tasks.cleanup.cleanup_old_data",
    bind=True,
    max_retries=0,
    ignore_result=False,
    # Cleanup may take a while on large datasets; give it extra headroom.
    soft_time_limit=110,
    time_limit=120,
)
def cleanup_old_data(self: Any) -> dict[str, Any]:  # noqa: ANN401
    """Run all three cleanup phases in one daily task.

    Phases:
    1. Expire stale pending/partially_filled orders (>7 days old).
    2. Prune minute-resolution portfolio snapshots (>7 days old).
    3. Archive (delete) old audit log entries (>30 days old).

    Returns:
        A dict with keys:

        * ``orders_expired``       — count of orders set to ``"expired"``.
        * ``snapshots_deleted``    — total minute-snapshot rows removed.
        * ``audit_rows_deleted``   — count of audit log rows removed.
        * ``accounts_processed``   — accounts iterated during snapshot phase.
        * ``accounts_failed``      — accounts that raised an exception.
        * ``phases_failed``        — list of phase names that raised errors.
        * ``duration_ms``          — total wall-clock time in milliseconds.

    Raises:
        Exception: Only if all three phases fail; a partial failure in one
            phase is logged and counted in ``phases_failed`` without aborting
            the remaining phases.

    Example::

        result = cleanup_old_data.delay()
        stats = result.get(timeout=120)
        print(
            f"Expired {stats['orders_expired']} orders, "
            f"deleted {stats['snapshots_deleted']} snapshots, "
            f"archived {stats['audit_rows_deleted']} audit rows "
            f"in {stats['duration_ms']} ms"
        )
    """
    return asyncio.run(_run_cleanup())


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------


async def _run_cleanup() -> dict[str, Any]:
    """Async body of :func:`cleanup_old_data`.

    Runs the three cleanup phases sequentially.  A short-lived session factory
    is created per invocation.  Each phase handles its own database sessions
    and failure isolation.

    Returns:
        Serialisable summary dict for the Celery result backend.
    """
    from src.config import get_settings
    from src.database.session import get_session_factory

    task_start = time.monotonic()
    _settings = get_settings()
    session_factory = get_session_factory()

    orders_expired = 0
    snapshots_deleted = 0
    audit_rows_deleted = 0
    accounts_processed = 0
    accounts_failed = 0
    phases_failed: list[str] = []

    # ── Phase 1: expire stale pending orders ─────────────────────────────────
    try:
        orders_expired = await _expire_stale_orders(session_factory)
    except Exception:
        phases_failed.append("expire_orders")
        logger.exception("cleanup.expire_orders.fatal_error")

    # ── Phase 2: prune old minute snapshots ──────────────────────────────────
    try:
        snapshots_deleted, accounts_processed, accounts_failed = await _prune_minute_snapshots(session_factory)
    except Exception:
        phases_failed.append("prune_snapshots")
        logger.exception("cleanup.prune_snapshots.fatal_error")

    # ── Phase 3: archive old audit log entries ────────────────────────────────
    try:
        audit_rows_deleted = await _archive_audit_log(session_factory)
    except Exception:
        phases_failed.append("archive_audit_log")
        logger.exception("cleanup.archive_audit_log.fatal_error")

    duration_ms = round((time.monotonic() - task_start) * 1000, 2)

    level = logging.WARNING if phases_failed else logging.INFO
    logger.log(
        level,
        "cleanup.finished",
        extra={
            "orders_expired": orders_expired,
            "snapshots_deleted": snapshots_deleted,
            "audit_rows_deleted": audit_rows_deleted,
            "accounts_processed": accounts_processed,
            "accounts_failed": accounts_failed,
            "phases_failed": phases_failed,
            "duration_ms": duration_ms,
        },
    )

    return {
        "orders_expired": orders_expired,
        "snapshots_deleted": snapshots_deleted,
        "audit_rows_deleted": audit_rows_deleted,
        "accounts_processed": accounts_processed,
        "accounts_failed": accounts_failed,
        "phases_failed": phases_failed,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Phase 1 — expire stale orders
# ---------------------------------------------------------------------------


async def _expire_stale_orders(session_factory: Any) -> int:  # noqa: ANN401
    """Bulk-expire pending/partially_filled orders older than ``_STALE_ORDER_DAYS``.

    Executes a single ``UPDATE orders SET status = 'expired' WHERE ...``
    across all accounts.  This is far more efficient than iterating per-account
    and avoids holding a long-lived session for individual row fetches.

    The ``updated_at`` column is also refreshed so the change is auditable.

    Note:
        Locked funds for expired orders are *not* automatically released here.
        Balance recovery for expired orders should be triggered through an
        account reset or a future dedicated unlock task.

    Args:
        session_factory: Async session factory from
            :func:`~src.database.session.get_session_factory`.

    Returns:
        The number of orders transitioned to ``"expired"``.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagated on any database failure.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import and_
    from sqlalchemy import update as sa_update

    from src.database.models import Order

    cutoff = datetime.now(tz=UTC) - timedelta(days=_STALE_ORDER_DAYS)

    async with session_factory() as session:
        stmt = (
            sa_update(Order)
            .where(
                and_(
                    Order.status.in_(["pending", "partially_filled"]),
                    Order.created_at < cutoff,
                )
            )
            .values(
                status="expired",
                updated_at=datetime.now(tz=UTC),
            )
        )
        result = await session.execute(stmt)
        expired_count: int = result.rowcount  # type: ignore[assignment]
        await session.commit()

    logger.info(
        "cleanup.expire_orders.done",
        extra={
            "expired_count": expired_count,
            "cutoff": cutoff.isoformat(),
            "stale_days": _STALE_ORDER_DAYS,
        },
    )
    return expired_count


# ---------------------------------------------------------------------------
# Phase 2 — prune minute-resolution portfolio snapshots
# ---------------------------------------------------------------------------


async def _prune_minute_snapshots(
    session_factory: Any,  # noqa: ANN401
) -> tuple[int, int, int]:
    """Delete minute-resolution snapshots older than ``_MINUTE_SNAPSHOT_DAYS``.

    Iterates all accounts in batches of :data:`_ACCOUNT_BATCH_SIZE` and calls
    :meth:`~src.database.repositories.snapshot_repo.SnapshotRepository.delete_before`
    for each account.  Each account uses an isolated session so that a failure
    on one account does not roll back progress for others.

    Args:
        session_factory: Async session factory from
            :func:`~src.database.session.get_session_factory`.

    Returns:
        A 3-tuple ``(total_deleted, accounts_processed, accounts_failed)``.

    Raises:
        Exception: Propagated only if loading account IDs fails entirely.
            Per-account deletion errors are caught, logged, and counted.
    """
    from datetime import datetime, timedelta

    cutoff = datetime.now(tz=UTC) - timedelta(days=_MINUTE_SNAPSHOT_DAYS)

    account_ids = await _load_all_account_ids(session_factory)

    total_deleted = 0
    accounts_processed = 0
    accounts_failed = 0

    logger.info(
        "cleanup.prune_snapshots.started",
        extra={
            "total_accounts": len(account_ids),
            "cutoff": cutoff.isoformat(),
            "retention_days": _MINUTE_SNAPSHOT_DAYS,
        },
    )

    for account_id in account_ids:
        try:
            async with session_factory() as session:
                from src.database.repositories.snapshot_repo import SnapshotRepository

                repo = SnapshotRepository(session)
                deleted = await repo.delete_before(account_id, "minute", cutoff)
                await session.commit()
            total_deleted += deleted
            accounts_processed += 1
        except Exception:
            accounts_failed += 1
            logger.exception(
                "cleanup.prune_snapshots.account_error",
                extra={"account_id": str(account_id)},
            )

    logger.info(
        "cleanup.prune_snapshots.done",
        extra={
            "total_deleted": total_deleted,
            "accounts_processed": accounts_processed,
            "accounts_failed": accounts_failed,
            "cutoff": cutoff.isoformat(),
        },
    )
    return total_deleted, accounts_processed, accounts_failed


# ---------------------------------------------------------------------------
# Phase 3 — archive old audit log entries
# ---------------------------------------------------------------------------


async def _archive_audit_log(session_factory: Any) -> int:  # noqa: ANN401
    """Bulk-delete audit log entries older than ``_AUDIT_LOG_DAYS``.

    The audit log grows without bound as every authenticated request is
    recorded.  This phase removes rows older than 30 days using a single
    ``DELETE`` statement keyed on the ``idx_audit_account`` index column
    ``created_at``.

    Args:
        session_factory: Async session factory from
            :func:`~src.database.session.get_session_factory`.

    Returns:
        The number of audit log rows deleted.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Propagated on any database failure.
    """
    from datetime import datetime, timedelta

    from sqlalchemy import delete as sa_delete

    from src.database.models import AuditLog

    cutoff = datetime.now(tz=UTC) - timedelta(days=_AUDIT_LOG_DAYS)

    async with session_factory() as session:
        stmt = sa_delete(AuditLog).where(AuditLog.created_at < cutoff)
        result = await session.execute(stmt)
        deleted_count: int = result.rowcount  # type: ignore[assignment]
        await session.commit()

    logger.info(
        "cleanup.archive_audit_log.done",
        extra={
            "deleted_count": deleted_count,
            "cutoff": cutoff.isoformat(),
            "retention_days": _AUDIT_LOG_DAYS,
        },
    )
    return deleted_count


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _load_all_account_ids(session_factory: Any) -> list[Any]:  # noqa: ANN401
    """Return UUIDs of all accounts (any status) for snapshot pruning.

    Minute snapshots should be pruned for every account, not just active ones,
    to prevent deactivated or suspended accounts from accumulating unbounded
    snapshot history.

    Uses a single short-lived session and pages through accounts in batches of
    :data:`_ACCOUNT_BATCH_SIZE` to bound peak memory usage.

    Args:
        session_factory: Async session factory from
            :func:`~src.database.session.get_session_factory`.

    Returns:
        Flat list of :class:`~uuid.UUID` values across all accounts.
    """
    from src.database.repositories.account_repo import AccountRepository

    ids: list[Any] = []
    offset = 0

    # Fetch from all non-deleted statuses; we iterate each status in turn
    # because AccountRepository.list_by_status filters on a single status.
    # Using all three known statuses keeps the query index-efficient.
    for status in ("active", "suspended", "inactive"):
        offset = 0
        async with session_factory() as session:
            repo = AccountRepository(session)
            while True:
                batch = await repo.list_by_status(
                    status,
                    limit=_ACCOUNT_BATCH_SIZE,
                    offset=offset,
                )
                if not batch:
                    break
                ids.extend(account.id for account in batch)
                if len(batch) < _ACCOUNT_BATCH_SIZE:
                    break
                offset += _ACCOUNT_BATCH_SIZE

    return ids
