# Background Tasks (Celery)

<!-- last-updated: 2026-04-01 -->

> Celery tasks and beat schedule for periodic jobs: order matching, portfolio snapshots, candle aggregation, data cleanup, backtest housekeeping, and battle monitoring.

## What This Module Does

This package defines all Celery background tasks for the platform. Tasks are registered via the `app` instance in `celery_app.py` and scheduled through Celery Beat. Every task bridges the sync Celery boundary to async code via `asyncio.run()` (or `asyncio.get_event_loop().run_until_complete()` in older tasks). Each task creates its own short-lived DB session factory and Redis client so tasks are stateless and safe to run on any worker process.

## Key Files

| File | Purpose |
|------|---------|
| `celery_app.py` | Celery app factory, broker/backend config, queue definitions, full beat schedule. The `agent.tasks` module import is wrapped in `try/except ModuleNotFoundError` so Celery starts successfully without the optional agent package installed. |
| `limit_order_monitor.py` | Sweeps all pending limit/stop-loss/take-profit orders every 1s via `run_matcher_once` |
| `portfolio_snapshots.py` | Captures minute/hourly/daily equity snapshots for all active accounts; resets circuit breakers at midnight |
| `candle_aggregation.py` | Safety-net refresh of TimescaleDB OHLCV continuous aggregates (`candles_1m/5m/1h/1d`) every 60s |
| `cleanup.py` | Daily cleanup: expire stale orders (>7d), prune minute snapshots (>7d), archive audit log (>30d) |
| `backtest_cleanup.py` | Auto-cancel idle backtests (>1h), delete old backtest detail data (>90d) |
| `battle_snapshots.py` | Capture battle equity snapshots every 5s; auto-complete expired battles every 10s |
| `strategy_tasks.py` | Strategy test episodes: `run_strategy_episode` (5min limit), `aggregate_test_results` (1min limit) |
| `agent_analytics.py` | 4 agent analytics tasks: `agent_strategy_attribution` (daily), `agent_memory_effectiveness` (weekly), `agent_platform_health_report` (daily), `settle_agent_decisions` (every 5 min) |
| `retrain_tasks.py` | 5 ML retraining tasks routed to `ml_training` queue: `run_retraining_cycle` (master, all due components), `retrain_ensemble`, `retrain_regime`, `retrain_genome`, `retrain_rl`; each with `soft_time_limit=3600`, `time_limit=3900` |
| `__init__.py` | Package docstring (no exports) |

## Architecture & Patterns

### Celery App Configuration (`celery_app.py`)

- **Broker and backend**: Both use `REDIS_URL` env var (default `redis://redis:6379/0`).
- **Serialization**: JSON only (`task_serializer`, `result_serializer`, `accept_content`).
- **Timezone**: UTC, `enable_utc=True`.
- **Result TTL**: 1 hour (`result_expires=3600`).
- **Worker settings**: `task_acks_late=True`, `task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1`.
- **Time limits**: 55s soft / 60s hard globally (overridden per task where needed).
- **Queues**: `default`, `high_priority`, and `ml_training`. Only `limit_order_monitor` routes to `high_priority`; all five retraining tasks route to `ml_training` so long-running ML jobs do not block platform-critical tasks.
- **Visibility timeout**: 300s (must exceed `task_time_limit`).

### Beat Schedule

| Beat Entry | Task | Frequency | Queue |
|------------|------|-----------|-------|
| `run-retraining-cycle` | `retrain_tasks.run_retraining_cycle` | Every 8h at :00 | `ml_training` |
| `limit-order-monitor` | `limit_order_monitor.run_limit_order_monitor` | Every 1s | `high_priority` |
| `capture-minute-snapshots` | `portfolio_snapshots.capture_minute_snapshots` | Every 60s | default |
| `capture-hourly-snapshots` | `portfolio_snapshots.capture_hourly_snapshots` | Every 3600s | default |
| `capture-daily-snapshots` | `portfolio_snapshots.capture_daily_snapshots` | Crontab 00:00 UTC | default |
| `reset-circuit-breakers` | `portfolio_snapshots.reset_circuit_breakers` | Crontab 00:01 UTC | default |
| `refresh-candle-aggregates` | `candle_aggregation.refresh_candle_aggregates` | Every 60s | default |
| `cleanup-old-data` | `cleanup.cleanup_old_data` | Crontab 01:00 UTC | default |
| `cancel-stale-backtests` | `backtest_cleanup.cancel_stale_backtests` | Every 3600s | default |
| `cleanup-backtest-detail-data` | `backtest_cleanup.cleanup_backtest_detail_data` | Crontab 02:00 UTC | default |
| `capture-battle-snapshots` | `battle_snapshots.capture_battle_snapshots` | Every 5s | default |
| `check-battle-completion` | `battle_snapshots.check_battle_completion` | Every 10s | default |
| `agent-strategy-attribution` | `agent_analytics.agent_strategy_attribution` | Crontab 02:00 UTC | default |
| `agent-memory-effectiveness` | `agent_analytics.agent_memory_effectiveness` | Crontab Sunday 03:00 UTC | default |
| `agent-platform-health-report` | `agent_analytics.agent_platform_health_report` | Crontab 06:00 UTC | default |
| `settle-agent-decisions` | `agent_analytics.settle_agent_decisions` | Every 300s (5 min) | default |

### Async Bridge Pattern

All tasks follow the same pattern: a sync Celery task function calls `asyncio.run(_async_impl())`. The async implementation does lazy imports (to avoid circular imports), creates a session factory and Redis client, does its work, then tears down connections. This keeps each invocation stateless.

### Fail Isolation

- **Per-account isolation**: Portfolio snapshots and cleanup iterate accounts individually; a failure on one account is logged but does not abort others.
- **Per-phase isolation**: `cleanup.cleanup_old_data` has three independent phases (expire orders, prune snapshots, archive audit log). Each phase catches its own exceptions and reports failures in the `phases_failed` list.
- **Per-view isolation**: `candle_aggregation` refreshes four views independently; a failure on one view does not skip the rest.

### Retention Constants (in `cleanup.py`)

| Constant | Value | Effect |
|----------|-------|--------|
| `_STALE_ORDER_DAYS` | 7 | Pending/partially_filled orders older than this are expired |
| `_MINUTE_SNAPSHOT_DAYS` | 7 | Minute-resolution portfolio snapshots older than this are deleted |
| `_AUDIT_LOG_DAYS` | 30 | Audit log rows older than this are deleted |
| `_ACCOUNT_BATCH_SIZE` | 500 | Batch size when paging through accounts for snapshot pruning |

### Custom Time Limits

| Task | Soft Limit | Hard Limit |
|------|-----------|------------|
| `run_retraining_cycle` / `retrain_*` | 3600s (1 h) | 3900s (1 h 5 min) |
| Global default | 55s | 60s |
| `capture_daily_snapshots` | 110s | 120s |
| `cleanup_old_data` | 110s | 120s |
| `capture_battle_snapshots` | 10s | 15s |
| `check_battle_completion` | 30s | 45s |
| `run_strategy_episode` | 300s | 360s |
| `aggregate_test_results` | 60s | 90s |

## Public API / Interfaces

All tasks return JSON-serializable `dict` summaries to the Celery result backend. Key return shapes:

- **`run_limit_order_monitor`** -- `{swept_at, orders_checked, orders_filled, orders_errored, duration_ms}`
- **`capture_*_snapshots`** -- `{snapshot_type, accounts_processed, accounts_failed, duration_ms}`
- **`reset_circuit_breakers`** -- `{duration_ms}`
- **`refresh_candle_aggregates`** -- `{views_refreshed, views_failed, view_details, duration_ms}`
- **`cleanup_old_data`** -- `{orders_expired, snapshots_deleted, audit_rows_deleted, accounts_processed, accounts_failed, phases_failed, duration_ms}`
- **`cancel_stale_backtests`** -- `{cancelled}`
- **`cleanup_backtest_detail_data`** -- `{deleted_rows}`
- **`capture_battle_snapshots`** -- `int` (total snapshots created)
- **`check_battle_completion`** -- `int` (battles auto-completed)

Manual trigger example:
```python
from src.tasks.limit_order_monitor import run_limit_order_monitor
result = run_limit_order_monitor.delay()
print(result.get(timeout=10))
```

## Dependencies

### Internal

- `src.config.get_settings` -- cached settings (broker URL, Redis URL, etc.)
- `src.database.session.get_session_factory` -- async SQLAlchemy session factory
- `src.cache.redis_client.RedisClient` / `get_redis_client` -- Redis connections
- `src.cache.price_cache.PriceCache` -- price lookups (used by limit order monitor and battle snapshots)
- `src.order_engine.matching.run_matcher_once` -- limit order matching sweep
- `src.portfolio.snapshots.SnapshotService` -- portfolio snapshot capture
- `src.risk.circuit_breaker.CircuitBreaker` -- daily PnL reset
- `src.battles.snapshot_engine.SnapshotEngine` -- battle equity capture
- `src.battles.service.BattleService` -- battle auto-completion
- `src.database.repositories.*` -- `BacktestRepository`, `SnapshotRepository`, `AccountRepository`

### External

- `celery` -- task framework
- `kombu` -- queue definitions
- `redis` -- broker and result backend
- `sqlalchemy` -- async DB access (via `asyncpg`)

## Common Tasks

### Adding a new Celery task

1. Create a new file in `src/tasks/` (e.g., `my_task.py`).
2. Import the app: `from src.tasks.celery_app import app`.
3. Define a sync task function decorated with `@app.task(name="src.tasks.my_task.do_thing")`.
4. Bridge to async: have the sync function call `asyncio.run(_async_impl())`.
5. Use lazy imports inside the async function to avoid circular imports.
6. Register the module in the `include` list in `celery_app.py`:
   ```python
   include=[
       ...,
       "src.tasks.my_task",
   ],
   ```
7. If the task needs a beat schedule, add an entry to `app.conf.beat_schedule` in `celery_app.py`.
8. If the task needs priority routing, add it to `task_routes` and use the `high_priority` queue.
9. Override `soft_time_limit` and `time_limit` in the `@app.task()` decorator if the default 55s/60s is insufficient.

### Running locally

```bash
# Start worker (processes both queues)
celery -A src.tasks.celery_app worker --loglevel=info -Q default,high_priority

# Start beat scheduler (separate process)
celery -A src.tasks.celery_app beat --loglevel=info
```

## Gotchas & Pitfalls

- **`asyncio.get_event_loop().run_until_complete()` vs `asyncio.run()`**: Older tasks (`backtest_cleanup.py`, `battle_snapshots.py`) use `get_event_loop().run_until_complete()`. Newer tasks use `asyncio.run()`. Both work, but `asyncio.run()` is preferred as it creates a fresh event loop and is the modern pattern.
- **Lazy imports are required**: All database model and service imports must happen inside the async function body (not at module level) to avoid circular import chains. Use `# noqa: PLC0415` to suppress the ruff warning.
- **`get_settings()` is `lru_cache`-wrapped**: In tests, you must patch it before the cached instance is created, or override via dependency injection. Tasks call `get_settings()` inside the async body, so patching at import time works.
- **Expired orders do not unlock funds**: `cleanup.py` phase 1 transitions stale orders to `"expired"` status but does NOT release locked balances. Balance recovery requires a separate admin action or account reset.
- **Candle aggregation is a no-op when auto-refresh is active**: The `refresh_candle_aggregates` task is a safety net. If TimescaleDB auto-refresh policies are configured (the normal production setup), the explicit `CALL refresh_continuous_aggregate(...)` overlaps with already-materialized data and does nothing.
- **Battle snapshot tasks have tight time limits**: `capture_battle_snapshots` has a 10s soft / 15s hard limit because it runs every 5s. If it takes longer than the interval, invocations will overlap.
- **Circuit breaker reset runs 1 minute after daily snapshots**: `reset-circuit-breakers` is at 00:01 UTC (not 00:00) so it does not race with `capture-daily-snapshots`. They are separate beat entries so a failure in one does not block the other.
- **No Redis needed for cleanup tasks**: `cleanup.py` and `backtest_cleanup.py` only touch the database. They do not create Redis clients, unlike `portfolio_snapshots.py` and `limit_order_monitor.py`.
- **`max_retries=0` on all tasks**: No task retries on failure. For high-frequency tasks (limit order monitor at 1s, battle snapshots at 5s), the next beat invocation serves as the implicit retry. For daily tasks, manual re-trigger is expected.
- **`agent.tasks` import is optional**: `celery_app.py` wraps the `agent.tasks` import in `try/except ModuleNotFoundError`. The agent package is not installed in the base platform Docker image, so Celery must start without it. If the package is present (e.g., in the agent profile), the tasks auto-register.

## Recent Changes

- `2026-04-01` — Production fix: `celery_app.py` `agent.tasks` import wrapped in `try/except ModuleNotFoundError` so Celery workers start successfully on deployments where the optional `agent` package is not installed.
- `2026-03-23` — Added `retrain_tasks.py` with 5 ML retraining Celery tasks (`run_retraining_cycle`, `retrain_ensemble`, `retrain_regime`, `retrain_genome`, `retrain_rl`). All tasks route to new `ml_training` queue, use `asyncio.run()` bridge to `RetrainOrchestrator`, and have `soft_time_limit=3600` / `time_limit=3900`. Beat entry `run-retraining-cycle` runs every 8h. Beat schedule count: 15 → 16.
- `2026-03-22` — Added `settle_agent_decisions` task to `agent_analytics.py` (every 5 min). Closes the feedback loop from trade outcome to agent learning: finds unresolved `AgentDecision` rows, checks if the linked order is filled, computes `realized_pnl` from `Trade` rows, writes back `outcome_pnl` + `outcome_recorded_at`. Beat schedule count: 14 → 15.
- `2026-03-21` — Added `agent_analytics.py` with 3 Celery tasks: `agent_strategy_attribution` (daily 02:00 UTC — queries `agent_strategy_signals` to compute per-strategy PnL attribution), `agent_memory_effectiveness` (weekly Sunday 03:00 UTC — measures memory retrieval hit rate), `agent_platform_health_report` (daily 06:00 UTC — aggregates agent API call latency and error rates). Beat schedule count: 11 → 14.
- `2026-03-17` -- Initial CLAUDE.md created
