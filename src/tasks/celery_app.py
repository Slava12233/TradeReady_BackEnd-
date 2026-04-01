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
- ``retrain_ensemble_weights``   — every 8 hours at :30 UTC (staggered from master cycle)
- ``retrain_regime_classifier``  — weekly Sunday 04:00 UTC
- ``retrain_genome_population``  — weekly Wednesday 05:00 UTC
- ``retrain_rl_models``          — monthly 1st of month 03:00 UTC

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

_INCLUDE_MODULES = [
    "src.tasks.limit_order_monitor",
    "src.tasks.portfolio_snapshots",
    "src.tasks.candle_aggregation",
    "src.tasks.cleanup",
    "src.tasks.backtest_cleanup",
    "src.tasks.battle_snapshots",
    "src.tasks.strategy_tasks",
    # Agent analytics tasks (src/tasks/ package)
    "src.tasks.agent_analytics",
    # ML retraining tasks — long-running; routed to ml_training queue
    "src.tasks.retrain_tasks",
]

# Agent ecosystem tasks (agent/ package) — optional; only available when the
# agent package is installed (profile-gated Docker service).
# We check importability via importlib.util.find_spec() instead of importing
# directly, because `agent.tasks` imports `app` from this module — importing
# it before `app` is defined would cause a circular ImportError.
import importlib.util  # noqa: E402

if importlib.util.find_spec("agent.tasks") is not None:
    _INCLUDE_MODULES.append("agent.tasks")

app = Celery(
    "agentexchange",
    broker=_REDIS_URL,
    backend=_REDIS_URL,
    include=_INCLUDE_MODULES,
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
        Queue("ml_training"),  # reserved for long-running ML retraining tasks
    ),
    task_routes={
        "src.tasks.limit_order_monitor.run_limit_order_monitor": {
            "queue": "high_priority",
        },
        "src.tasks.retrain_tasks.run_retraining_cycle": {
            "queue": "ml_training",
        },
        "src.tasks.retrain_tasks.retrain_ensemble": {
            "queue": "ml_training",
        },
        "src.tasks.retrain_tasks.retrain_regime": {
            "queue": "ml_training",
        },
        "src.tasks.retrain_tasks.retrain_genome": {
            "queue": "ml_training",
        },
        "src.tasks.retrain_tasks.retrain_rl": {
            "queue": "ml_training",
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
    # ── Agent Ecosystem Tasks ─────────────────────────────────────────────
    # Daily morning market scan — runs at the hour configured by
    # AgentConfig.agent_scheduled_review_hour (default 08:00 UTC).
    "agent-morning-review": {
        "task": "agent.tasks.agent_morning_review",
        "schedule": crontab(hour=8, minute=0),  # 08:00 UTC — overridable via env
    },
    # Daily budget reset at midnight UTC — clears trades_today,
    # exposure_today, and loss_today for every agent with a budget record.
    "agent-budget-reset": {
        "task": "agent.tasks.agent_budget_reset",
        "schedule": crontab(hour=0, minute=2),  # 00:02 UTC — after circuit-breaker reset
    },
    # Daily memory cleanup — prunes expired and low-confidence learnings.
    "agent-memory-cleanup": {
        "task": "agent.tasks.agent_memory_cleanup",
        "schedule": crontab(hour=3, minute=0),  # 03:00 UTC daily — off-peak
    },
    # Hourly rolling performance snapshot — one AgentPerformance row per
    # active agent per hour (skips agents with zero trades in the window).
    "agent-performance-snapshot": {
        "task": "agent.tasks.agent_performance_snapshot",
        "schedule": 3600.0,  # every hour
    },
    # ── Agent Analytics Tasks ─────────────────────────────────────────────
    # Daily strategy attribution — aggregates last 24 h of agent_strategy_signals
    # per strategy, correlates with decision outcomes via trace_id, and writes
    # one AgentPerformance row per strategy per agent with period="attribution".
    "agent-strategy-attribution": {
        "task": "src.tasks.agent_analytics.agent_strategy_attribution",
        "schedule": crontab(hour=2, minute=0),  # 02:00 UTC daily — after cleanup-backtest-detail-data
    },
    # Weekly memory effectiveness — counts decisions with/without memory context
    # for the last 7 days and writes an AgentJournal "insight" entry per agent.
    "agent-memory-effectiveness": {
        "task": "src.tasks.agent_analytics.agent_memory_effectiveness",
        "schedule": crontab(hour=3, minute=0, day_of_week=0),  # Sunday 03:00 UTC
    },
    # Daily platform health report — compares 24 h API call stats to the prior
    # day and auto-creates AgentFeedback entries on latency or error regressions.
    "agent-platform-health-report": {
        "task": "src.tasks.agent_analytics.agent_platform_health_report",
        "schedule": crontab(hour=6, minute=0),  # 06:00 UTC daily — off-peak
    },
    # Every-5-minute decision outcome settlement — closes the feedback loop from
    # trade outcome to agent learning.  Finds unresolved AgentDecision rows,
    # matches them to filled orders, computes realised PnL from Trade rows, and
    # writes outcome_pnl / outcome_recorded_at back to each decision.
    "settle-agent-decisions": {
        "task": "src.tasks.agent_analytics.settle_agent_decisions",
        "schedule": 300.0,  # every 5 minutes
    },
    # ── ML Retraining Tasks ───────────────────────────────────────────────
    # Master retraining cycle — checks all four components for overdue
    # retraining and runs any that are due.  Runs every 8 hours so the
    # ensemble weights (8h interval) are always picked up on time.  Regime,
    # genome, and RL checks are fast no-ops when not yet due.
    "run-retraining-cycle": {
        "task": "src.tasks.retrain_tasks.run_retraining_cycle",
        "schedule": crontab(minute=0, hour="*/8"),  # every 8 hours at :00
        "options": {"queue": "ml_training"},
    },
    # Ensemble weights retrain — every 8 hours (one full trading session).
    # Staggered 30 minutes after the master cycle to avoid concurrent CPU
    # contention; the master cycle already dispatches this when overdue.
    "retrain-ensemble-weights": {
        "task": "src.tasks.retrain_tasks.retrain_ensemble",
        "schedule": crontab(minute=30, hour="*/8"),  # every 8 hours at :30
        "options": {"queue": "ml_training"},
    },
    # Regime classifier retrain — weekly on Sunday at 04:00 UTC.
    # Sunday is the quietest period for crypto markets; running at 04:00
    # avoids overlap with the daily cleanup tasks (01:00–03:00 UTC).
    "retrain-regime-classifier": {
        "task": "src.tasks.retrain_tasks.retrain_regime",
        "schedule": crontab(hour=4, minute=0, day_of_week=0),  # Sunday 04:00 UTC
        "options": {"queue": "ml_training"},
    },
    # Genome population refresh — weekly on Wednesday at 05:00 UTC.
    # Mid-week timing avoids the Sunday regime retrain and the Monday/Friday
    # liquidity spikes; 05:00 UTC is off-peak for all major trading regions.
    "retrain-genome-population": {
        "task": "src.tasks.retrain_tasks.retrain_genome",
        "schedule": crontab(hour=5, minute=0, day_of_week=3),  # Wednesday 05:00 UTC
        "options": {"queue": "ml_training"},
    },
    # PPO RL model retrain — monthly on the 1st at 03:00 UTC.
    # Full PPO retraining (500k timesteps) takes 30-60 min on a CPU worker.
    # Running at 03:00 UTC on the 1st avoids overlap with daily cleanup tasks
    # and the weekly retraining jobs (genome runs Wednesday, regime Sunday).
    "retrain-rl-models": {
        "task": "src.tasks.retrain_tasks.retrain_rl",
        "schedule": crontab(hour=3, minute=0, day_of_month=1),  # 1st of month 03:00 UTC
        "options": {"queue": "ml_training"},
    },
}
