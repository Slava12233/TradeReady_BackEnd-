"""Celery task: manual continuous aggregate refresh guard.

TimescaleDB's auto-refresh policies (added in Phase 1) normally keep the four
OHLCV materialized views (``candles_1m``, ``candles_5m``, ``candles_1h``,
``candles_1d``) up-to-date without any intervention.  This task exists as a
safety net that runs every 60 seconds and explicitly calls
``refresh_continuous_aggregate`` for each view over a short trailing window.

Design rationale
----------------
* If the auto-policy is active and already refreshed the view, the explicit
  call overlaps with the same data range and is effectively a no-op (TimescaleDB
  skips buckets that are already materialised and unmodified).
* If the auto-policy is not active (e.g. in a dev/CI environment that skipped
  migration step 7-10), this task fills the gap and keeps candles queryable.

Refresh windows
---------------
Each view is refreshed over a window that covers data that may have arrived
since the previous run:

* ``candles_1m`` — last 10 minutes → last 1 minute
* ``candles_5m`` — last 30 minutes → last 5 minutes
* ``candles_1h`` — last 4 hours   → last 1 hour
* ``candles_1d`` — last 3 days    → last 1 day

The ``end_offset`` intentionally excludes the most-recent incomplete bucket to
avoid partial candles.

Example (manual trigger)::

    from src.tasks.candle_aggregation import refresh_candle_aggregates
    result = refresh_candle_aggregates.delay()
    print(result.get(timeout=30))
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.tasks.celery_app import app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Continuous aggregate view definitions
# ---------------------------------------------------------------------------

# Each entry: (view_name, start_offset SQL interval, end_offset SQL interval)
_CANDLE_VIEWS: list[tuple[str, str, str]] = [
    ("candles_1m", "10 minutes", "1 minute"),
    ("candles_5m", "30 minutes", "5 minutes"),
    ("candles_1h", "4 hours", "1 hour"),
    ("candles_1d", "3 days", "1 day"),
]


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="src.tasks.candle_aggregation.refresh_candle_aggregates",
    bind=True,
    max_retries=0,
    ignore_result=False,
)
def refresh_candle_aggregates(self: Any) -> dict[str, Any]:  # noqa: ANN401
    """Trigger a manual refresh of all four OHLCV continuous aggregates.

    Runs every 60 seconds via Celery beat.  Each view is refreshed over a
    short trailing window so that any ticks that arrived since the last run
    are materialised into candles.

    The call is idempotent — if TimescaleDB's own auto-refresh policy already
    materialised the affected buckets, this is a no-op.

    Returns:
        A dict with keys ``views_refreshed``, ``views_failed``,
        ``view_details`` (per-view latency and outcome), and
        ``duration_ms``.

    Raises:
        Exception: Any unhandled top-level error is logged and re-raised so
            Celery records it.  Individual view failures are isolated and
            counted in ``views_failed`` without aborting remaining views.

    Example::

        result = refresh_candle_aggregates.delay()
        stats = result.get(timeout=30)
        print(f"Refreshed {stats['views_refreshed']} views in {stats['duration_ms']} ms")
    """
    return asyncio.run(_run_refresh())


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------


async def _run_refresh() -> dict[str, Any]:
    """Async body of :func:`refresh_candle_aggregates`.

    Creates a short-lived asyncpg connection, iterates over all four candle
    aggregate views, and executes ``CALL refresh_continuous_aggregate(...)``
    for each one.  Per-view failures are caught, logged, and counted without
    aborting the remaining views.

    Returns:
        Serialisable summary dict for the Celery result backend.
    """
    from src.config import get_settings
    from src.database.session import get_session_factory

    task_start = time.monotonic()
    _settings = get_settings()

    session_factory = get_session_factory()

    views_refreshed = 0
    views_failed = 0
    view_details: list[dict[str, Any]] = []

    for view_name, start_offset, end_offset in _CANDLE_VIEWS:
        view_start = time.monotonic()
        try:
            async with session_factory() as session:
                await _refresh_view(session, view_name, start_offset, end_offset)
            elapsed_ms = round((time.monotonic() - view_start) * 1000, 2)
            views_refreshed += 1
            view_details.append(
                {
                    "view": view_name,
                    "status": "ok",
                    "elapsed_ms": elapsed_ms,
                }
            )
            logger.debug(
                "candle_aggregation.view_refreshed",
                extra={
                    "view": view_name,
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                    "elapsed_ms": elapsed_ms,
                },
            )
        except Exception:
            elapsed_ms = round((time.monotonic() - view_start) * 1000, 2)
            views_failed += 1
            view_details.append(
                {
                    "view": view_name,
                    "status": "error",
                    "elapsed_ms": elapsed_ms,
                }
            )
            logger.exception(
                "candle_aggregation.view_error",
                extra={
                    "view": view_name,
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                },
            )

    duration_ms = round((time.monotonic() - task_start) * 1000, 2)

    level = logging.WARNING if views_failed else logging.INFO
    logger.log(
        level,
        "candle_aggregation.finished",
        extra={
            "views_refreshed": views_refreshed,
            "views_failed": views_failed,
            "duration_ms": duration_ms,
        },
    )

    return {
        "views_refreshed": views_refreshed,
        "views_failed": views_failed,
        "view_details": view_details,
        "duration_ms": duration_ms,
    }


async def _refresh_view(
    session: Any,  # noqa: ANN401
    view_name: str,
    start_offset: str,
    end_offset: str,
) -> None:
    """Execute ``CALL refresh_continuous_aggregate(...)`` for one view.

    Uses the async SQLAlchemy session to run raw DDL so we stay inside the
    same connection-pool management as all other database code in the project.

    Args:
        session:      Active :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        view_name:    Name of the TimescaleDB continuous aggregate view
                      (e.g. ``"candles_1m"``).
        start_offset: SQL interval string for the window start relative to
                      ``NOW()`` (e.g. ``"10 minutes"``).
        end_offset:   SQL interval string for the window end relative to
                      ``NOW()`` (e.g. ``"1 minute"``).

    Raises:
        sqlalchemy.exc.SQLAlchemyError: If the database call fails.
    """
    from sqlalchemy import text

    sql = text(
        f"CALL refresh_continuous_aggregate("  # noqa: S608
        f"  '{view_name}',"
        f"  NOW() - INTERVAL '{start_offset}',"
        f"  NOW() - INTERVAL '{end_offset}'"
        f");"
    )
    await session.execute(sql)
