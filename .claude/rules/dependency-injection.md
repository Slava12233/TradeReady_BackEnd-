---
paths:
  - "src/**/*.py"
---

# Dependency Injection & Configuration

## FastAPI Dependencies (`src/dependencies.py`)

All service/repo instantiation via `Depends()`. Use typed aliases:

```python
async def handler(db: DbSessionDep, cache: PriceCacheDep, settings: SettingsDep):
```

Available aliases: `DbSessionDep`, `RedisDep`, `PriceCacheDep`, `SettingsDep`, `AccountRepoDep`, `BalanceRepoDep`, `OrderRepoDep`, `TradeRepoDep`, `TickRepoDep`, `SnapshotRepoDep`, `BalanceManagerDep`, `AccountServiceDep`, `SlippageCalcDep`, `OrderEngineDep`, `RiskManagerDep`, `CircuitBreakerRedisDep`, `PortfolioTrackerDep`, `PerformanceMetricsDep`, `SnapshotServiceDep`, `BacktestEngineDep`, `BacktestRepoDep`, `BattleRepoDep`, `BattleServiceDep`, `AgentRepoDep`, `AgentServiceDep`, `StrategyRepoDep`, `StrategyServiceDep`, `TestRunRepoDep`, `TestOrchestratorDep`, `TrainingRunRepoDep`, `TrainingRunServiceDep`.

Key patterns:
- **Lazy imports** inside dependency functions (`# noqa: PLC0415`) — don't move to module level
- **Per-request lifecycle** for DB sessions (auto-commit/rollback); Redis is shared pool (never close per-request)
- **CircuitBreaker is account-scoped** — construct per-account with `starting_balance` and `daily_loss_limit_pct`
- **BacktestEngine is singleton** — module-level `_backtest_engine_instance` global

## Settings (`src/config.py`)

- Pydantic v2 `BaseSettings` with `SettingsConfigDict(env_file=".env", case_sensitive=False)`
- `get_settings()` is `@lru_cache(maxsize=1)` — reads `.env` once per process
- Validators: `DATABASE_URL` must use `postgresql+asyncpg://`, `JWT_SECRET` must be 32+ chars
- **Tests**: patch `src.config.get_settings` BEFORE cached instance is created

## Exception Hierarchy (`src/utils/exceptions.py`)

All inherit `TradingPlatformError` → `code`, `http_status`, `.to_dict()`.
Global handler in `src/main.py` auto-serializes any `TradingPlatformError` subclass.
