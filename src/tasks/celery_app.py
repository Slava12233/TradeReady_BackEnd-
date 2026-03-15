"""Celery application factory and beat schedule for the AI Agent Crypto Trading Platform.

Beat schedule
-------------
- ``limit_order_monitor``      — every 1 second    (runs :func:`src.order_engine.matching.run_matcher_once`)
- ``capture_minute_snapshots`` — every 60 seconds  (portfolio equity snapshots for all accounts)
- ``capture_hourly_snapshots`` — every 3 600 seconds
- ``capture_daily_snapshots``  — midnight UTC; equity + positions + full metrics
- ``reset_circuit_breakers``   — midnight UTC; clears all per-account daily PnL accumulators
- ``cleanup_old_data``         — 01:00 UTC daily; prune stale orders + minute snapshots
- ``refresh_candle_aggregates`` — every 60 seconds  (manual refresh guard; no-op if auto-policy active)

All tasks are routed to the default queue unless overridden.  The broker
and result-backend both use the ``REDIS_URL`` environment variable
(defaulting to ``redis://redis:6379/0``).

Example (start worker)::

    celery -A src.tasks.celery_app worker --loglevel=info

Example (start beat scheduler)::

    celery -A src.tasks.celery_app beat --loglevel=info
"""

import os

from celery import Celery
from celery.schedules import crontab  # noqa: F401  — exported for convenience
from kombu import Queue

# ---------------------------------------------------------------------------
# Broker / backend URL
# ---------------------------------------------------------------------------

_REDIS_URL: str = os.environ.get("REDIS_URL", "redis://redis:6379/0")

# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = Celery(
    "agentexchange",
    broker=_REDIS_URL,
    backend=_REDIS_URL,
    include=[
        "src.tasks.limit_order_monitor",
        "src.tasks.portfolio_snapshots",
        "src.tasks.candle_aggregation",
        "src.tasks.cleanup",
        "src.tasks.backtest_cleanup",
        "src.tasks.battle_snapshots",
    ],
)

# ---------------------------------------------------------------------------
# General configuration
# ---------------------------------------------------------------------------

app.conf.update(
    # Serialisation
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Result TTL — keep results for 1 hour, then discard
    result_expires=3600,
    # Worker behaviour
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Prevent tasks from running indefinitely
    task_soft_time_limit=55,  # SIGTERM after 55 s
    task_time_limit=60,  # SIGKILL after 60 s  (overridden per task where needed)
    # Queues
    task_default_queue="default",
    task_queues=(
        Queue("default"),
        Queue("high_priority"),  # reserved for limit_order_monitor
    ),
    task_routes={
        "src.tasks.limit_order_monitor.run_limit_order_monitor": {
            "queue": "high_priority",
        },
    },
    # Beat — default persistent scheduler (writes celerybeat-schedule file).
    # Switch to redbeat.RedBeatScheduler if running multiple beat nodes.
    # Broker transport options — visibility timeout must be > task_time_limit
    broker_transport_options={
        "visibility_timeout": 300,
    },
)

# ---------------------------------------------------------------------------
# Beat schedule
# ---------------------------------------------------------------------------

app.conf.beat_schedule = {
    # ── Limit Order Matcher ──────────────────────────────────────────────────
    # Checks all pending limit/stop-loss/take-profit orders every 1 second.
    # Routed to high_priority queue to minimise latency.
    "limit-order-monitor": {
        "task": "src.tasks.limit_order_monitor.run_limit_order_monitor",
        "schedule": 1.0,  # seconds
        "options": {"queue": "high_priority"},
    },
    # ── Portfolio Snapshots ──────────────────────────────────────────────────
    # Minute-resolution snapshots for charting (equity only, no heavy metrics).
    "capture-minute-snapshots": {
        "task": "src.tasks.portfolio_snapshots.capture_minute_snapshots",
        "schedule": 60.0,  # seconds
    },
    # Hourly snapshots (equity + serialised positions list).
    "capture-hourly-snapshots": {
        "task": "src.tasks.portfolio_snapshots.capture_hourly_snapshots",
        "schedule": 3600.0,  # seconds
    },
    # Daily snapshots at midnight UTC — equity + positions + full metrics.
    "capture-daily-snapshots": {
        "task": "src.tasks.portfolio_snapshots.capture_daily_snapshots",
        "schedule": crontab(hour=0, minute=0),  # midnight UTC
    },
    # Reset all per-account circuit-breaker keys at midnight UTC so daily PnL
    # accumulators start fresh for the new calendar day.  Runs as a separate
    # entry from capture-daily-snapshots so a failure in one does not block the
    # other.
    "reset-circuit-breakers": {
        "task": "src.tasks.portfolio_snapshots.reset_circuit_breakers",
        "schedule": crontab(hour=0, minute=1),  # 00:01 UTC — just after daily snapshots
    },
    # ── Candle Aggregation ───────────────────────────────────────────────────
    # Manual continuous-aggregate refresh guard.  Runs every minute but is a
    # no-op if TimescaleDB auto-refresh policies are active (Phase 1 migration).
    "refresh-candle-aggregates": {
        "task": "src.tasks.candle_aggregation.refresh_candle_aggregates",
        "schedule": 60.0,  # seconds
    },
    # ── Cleanup ──────────────────────────────────────────────────────────────
    # Prune stale pending orders and minute snapshots older than 7 days;
    # archive audit log entries older than 30 days.
    "cleanup-old-data": {
        "task": "src.tasks.cleanup.cleanup_old_data",
        "schedule": crontab(hour=1, minute=0),  # 01:00 UTC daily
    },
    # ── Backtest Cleanup ─────────────────────────────────────────────────
    # Auto-cancel stale backtests (idle for >1 hour) — every hour.
    "cancel-stale-backtests": {
        "task": "src.tasks.backtest_cleanup.cancel_stale_backtests",
        "schedule": 3600.0,  # every hour
    },
    # Delete old backtest detail data (trades, snapshots >90 days) — daily.
    "cleanup-backtest-detail-data": {
        "task": "src.tasks.backtest_cleanup.cleanup_backtest_detail_data",
        "schedule": crontab(hour=2, minute=0),  # 02:00 UTC daily
    },
    # ── Battle Snapshots ─────────────────────────────────────────────────
    # Capture equity snapshots for all active battle participants every 5 seconds.
    "capture-battle-snapshots": {
        "task": "src.tasks.battle_snapshots.capture_battle_snapshots",
        "schedule": 5.0,  # seconds
    },
    # Check for battles that have exceeded their duration and auto-complete.
    "check-battle-completion": {
        "task": "src.tasks.battle_snapshots.check_battle_completion",
        "schedule": 10.0,  # seconds
    },
}
