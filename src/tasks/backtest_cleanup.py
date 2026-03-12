"""Background tasks for backtest housekeeping.

Tasks:
- Auto-cancel backtest sessions idle for >1 hour (no step in last hour).
- Delete backtest detail data (trades, snapshots) older than 90 days.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging

from src.tasks.celery_app import app

logger = logging.getLogger(__name__)


@app.task(name="src.tasks.backtest_cleanup.cancel_stale_backtests")  # type: ignore[misc]
def cancel_stale_backtests() -> dict[str, int]:
    """Auto-cancel backtest sessions that have been idle for >1 hour.

    A session is considered idle if its ``updated_at`` is older than 1 hour
    and its status is ``running`` or ``created``.

    Returns:
        Dict with count of cancelled sessions.
    """
    return asyncio.get_event_loop().run_until_complete(_cancel_stale_backtests_async())


async def _cancel_stale_backtests_async() -> dict[str, int]:
    from sqlalchemy import update

    from src.database.models import BacktestSession
    from src.database.session import get_session_factory

    cutoff = datetime.now(tz=UTC) - timedelta(hours=1)
    factory = get_session_factory()

    async with factory() as session:
        stmt = (
            update(BacktestSession)
            .where(
                BacktestSession.status.in_(["running", "created"]),
                BacktestSession.updated_at < cutoff,
            )
            .values(status="cancelled", completed_at=datetime.now(tz=UTC))
        )
        result = await session.execute(stmt)
        await session.commit()

        cancelled = result.rowcount or 0
        if cancelled > 0:
            logger.info("Cancelled %d stale backtest sessions", cancelled)
        return {"cancelled": cancelled}


@app.task(name="src.tasks.backtest_cleanup.cleanup_backtest_detail_data")  # type: ignore[misc]
def cleanup_backtest_detail_data() -> dict[str, int]:
    """Delete backtest trades and snapshots older than 90 days.

    Keeps session summaries intact for historical reference.

    Returns:
        Dict with count of deleted rows.
    """
    return asyncio.get_event_loop().run_until_complete(_cleanup_detail_async())


async def _cleanup_detail_async() -> dict[str, int]:
    from src.database.repositories.backtest_repo import BacktestRepository
    from src.database.session import get_session_factory

    factory = get_session_factory()

    async with factory() as session:
        repo = BacktestRepository(session)
        deleted = await repo.delete_old_detail_data(days=90)
        await session.commit()

        if deleted > 0:
            logger.info("Deleted %d old backtest detail rows", deleted)
        return {"deleted_rows": deleted}
