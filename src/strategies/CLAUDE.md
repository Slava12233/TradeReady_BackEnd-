# Strategies Module

<!-- last-updated: 2026-03-18 -->

> Strategy registry — CRUD, versioning, testing, and deployment for trading strategies.

## What This Module Does

Provides the business logic and data models for managing trading strategies. Strategies are versioned, testable, and deployable. This module is the foundation for the strategy executor (Phase STR-2) and Gymnasium wrapper (Phase STR-3).

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package marker |
| `models.py` | Pydantic domain models: `StrategyDefinition`, `EntryConditions`, `ExitConditions` |
| `service.py` | `StrategyService` — business logic for CRUD, versioning, deploy/undeploy |
| `indicators.py` | `IndicatorEngine` — 7 pure-numpy technical indicators (RSI, MACD, SMA, EMA, Bollinger, ADX, ATR) |
| `executor.py` | `StrategyExecutor` — evaluates entry/exit conditions, generates orders, tracks trailing stops |
| `test_orchestrator.py` | `TestOrchestrator` — multi-episode test run management, Celery task dispatch |
| `test_aggregator.py` | `TestAggregator` — statistical aggregation of episode results + per-pair breakdowns |
| `recommendation_engine.py` | `generate_recommendations()` — 11 rules for strategy improvement suggestions |

## Related Files (Outside This Module)

| File | Purpose |
|------|---------|
| `src/database/models.py` | ORM models: `Strategy`, `StrategyVersion`, `StrategyTestRun`, `StrategyTestEpisode`, `TrainingRun`, `TrainingEpisode` |
| `src/database/repositories/strategy_repo.py` | `StrategyRepository` — all DB access for strategy tables |
| `src/api/schemas/strategies.py` | Pydantic v2 request/response schemas for REST API |
| `src/api/routes/strategies.py` | 10 REST endpoints under `/api/v1/strategies` |
| `src/api/routes/strategy_tests.py` | 6 REST endpoints for strategy testing |
| `src/api/schemas/strategy_tests.py` | Pydantic v2 schemas for test endpoints |
| `src/database/repositories/test_run_repo.py` | `TestRunRepository` (extends `StrategyRepository`) |
| `src/tasks/strategy_tasks.py` | Celery tasks: `run_strategy_episode`, `aggregate_test_results` |
| `src/dependencies.py` | `StrategyRepoDep`, `StrategyServiceDep`, `TestRunRepoDep`, `TestOrchestratorDep` DI aliases |
| `alembic/versions/016_strategy_and_training_tables.py` | Migration creating 6 tables |

## Architecture

### Strategy Lifecycle

```
draft → testing → validated → deployed → archived
                                ↓
                            undeploy → validated
```

### Versioning

- Each strategy has immutable versions (1, 2, 3, ...)
- `StrategyService.create_version()` auto-increments via `get_max_version() + 1`
- The `current_version` field on `Strategy` tracks the latest
- Versions are never deleted, only the strategy can be archived

### Strategy Definition (JSONB)

Stored as JSONB in `strategy_versions.definition`. Validated against `StrategyDefinition` Pydantic model:

- `pairs`: list of trading pair symbols
- `timeframe`: candle interval (1m/5m/15m/1h/4h/1d)
- `entry_conditions`: 12 condition keys (all must pass)
- `exit_conditions`: 7 condition keys (any triggers exit)
- `position_size_pct`: % of equity per position
- `max_positions`: max simultaneous positions

### API Endpoints (10)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/strategies` | Create strategy |
| GET | `/strategies` | List strategies (paginated) |
| GET | `/strategies/{id}` | Get detail + definition + test results |
| PUT | `/strategies/{id}` | Update metadata |
| DELETE | `/strategies/{id}` | Archive (soft-delete) |
| POST | `/strategies/{id}/versions` | Create new version |
| GET | `/strategies/{id}/versions` | List versions |
| GET | `/strategies/{id}/versions/{v}` | Get specific version |
| POST | `/strategies/{id}/deploy` | Deploy to live |
| POST | `/strategies/{id}/undeploy` | Stop live |

## Dependencies

- `src.database.repositories.strategy_repo` — all DB access
- `src.utils.exceptions` — `StrategyNotFoundError`, `StrategyInvalidStateError`
- `src.api.middleware.auth` — `CurrentAccountDep` for authentication

## Gotchas

- Strategy definition validation happens in the service layer via Pydantic, not in the database
- `StrategyVersion` is immutable after creation — update by creating a new version
- Archiving a deployed strategy requires undeploying first
- Ownership checks are enforced in `StrategyService`, not in the repository
