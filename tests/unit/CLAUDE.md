# Unit Tests

<!-- last-updated: 2026-04-06 -->

> 1734 unit tests across 87 files covering every backend component — services, repositories, engines, exchange abstraction, middleware, tasks, MCP tools, SDK client, strategies, agent ecosystem, and training.

## What This Module Does

The `tests/unit/` directory contains fast, isolated unit tests that mock all external dependencies (database, Redis, Binance WS, Celery). No Docker or live services required. Tests exercise business logic, error paths, and edge cases for every layer of the platform.

## Test Inventory

| File | Tests | What It Covers |
|------|-------|----------------|
| `test_account_repo.py` | 18 | `AccountRepository` CRUD — create, get_by_id, get_by_api_key, get_by_email, update_status |
| `test_account_service.py` | 12 | `AccountService` lifecycle — register, authenticate (API key + password), get, reset, suspend/unsuspend |
| `test_agent_repo.py` | 25 | `AgentRepository` — CRUD, api_key lookup, list, archive, delete |
| `test_agent_scoping.py` | 15 | Agent-scoped data isolation across balances, orders, trades, positions |
| `test_agent_service.py` | 24 | `AgentService` — create, clone, reset, archive, regenerate API key |
| `test_auth.py` | 19 | Auth utilities — API key generation, password hashing, JWT encode/decode |
| `test_auth_middleware_agents.py` | 14 | Auth middleware agent resolution — API key vs JWT, `X-Agent-Id` header |
| `test_backtest_engine.py` | 13 | `BacktestEngine` orchestrator — create, start, step, step_batch, order, cancel, complete, concurrent sessions |
| `test_backtest_repo_agent_scope.py` | 5 | `BacktestRepository` agent-scoped filtering |
| `test_backtest_results.py` | 14 | Backtest results computation — metrics, equity curve, trade log |
| `test_backtest_sandbox.py` | 20 | `BacktestSandbox` in-memory exchange — orders, positions, balances, fills, slippage |
| `test_balance_manager.py` | 23 | `BalanceManager` — credit, debit, lock, unlock, execute_trade, agent-scoped balances |
| `test_balance_repo.py` | 21 | `BalanceRepository` — get, create, update, get_by_agent, get_all |
| `test_battle_ranking.py` | 8 | `RankingCalculator` — ROI, PnL, win rate, profit factor, drawdown, rank_participants |
| `test_battle_replay.py` | 6 | Battle replay — config cloning, agent subset selection |
| `test_battle_repo.py` | 17 | `BattleRepository` — CRUD for battles, participants, snapshots |
| `test_battle_service.py` | 19 | `BattleService` — lifecycle (create, start, pause, stop, cancel), participant management |
| `test_binance_ws.py` | 13 | Binance WebSocket client — connect, reconnect, parse messages, error handling |
| `test_circuit_breaker.py` | 12 | Circuit breaker — daily loss threshold, trip, reset |
| `test_config.py` | 8 | `Settings` validation — DB URL scheme, JWT secret length, defaults |
| `test_data_replayer.py` | 9 | `DataReplayer` — preload_range, load_prices, bisect lookup, backfill UNION |
| `test_database_session.py` | 10 | Database session factory — engine creation, session lifecycle |
| `test_decimal_edge_cases.py` | 10 | Decimal precision edge cases — rounding, very small/large values, zero division |
| `test_error_scenarios.py` | 12 | Cross-cutting error scenarios — cascading failures, concurrent errors |
| `test_exceptions.py` | 13 | Custom exception hierarchy — `TradingPlatformError` subclasses, `to_dict()`, HTTP status codes |
| `test_health.py` | 10 | Health check endpoint — DB/Redis/Binance status, degraded mode |
| `test_historical_battle_engine.py` | 26 | `HistoricalBattleEngine` — shared clock, per-agent sandboxes, step, batch, order, complete |
| `test_logging_middleware.py` | 10 | `LoggingMiddleware` — request/response logging, sensitive header redaction |
| `test_mcp_tools.py` | 138 | MCP server tools — all 43 original trading tools over stdio transport |
| `test_mcp_strategy_tools.py` | 21 | MCP strategy/training tools — 15 new tools (strategy management, testing, training observation) |
| `test_indicator_engine.py` | 26 | `IndicatorEngine` — RSI, MACD, SMA, EMA, Bollinger, ADX, ATR against known values |
| `test_strategy_service.py` | 16 | `StrategyService` — create, get, list, update, archive, versions, deploy/undeploy |
| `test_strategy_executor.py` | 21 | `StrategyExecutor` — 19 condition keys, entry/exit logic, position sizing, trailing stop |
| `test_test_aggregator.py` | 5 | `TestAggregator` — aggregation math (avg, median, std, by-pair) |
| `test_recommendation_engine.py` | 10 | `RecommendationEngine` — each recommendation rule triggers correctly |
| `test_training_tracker.py` | 10 | `TrainingRunService` — register, record episode, complete, learning curve, comparison |
| `test_metrics_adapters.py` | 13 | Metric adapters — `from_sandbox_trades`, `from_sandbox_snapshots`, `from_db_trades`, `from_battle_snapshots` |
| `test_metrics_consistency.py` | 5 | Cross-domain metrics consistency — backtest vs battle produce identical results for same inputs |
| `test_order_engine.py` | 16 | `OrderEngine` — market buy/sell, limit, stop_loss, take_profit, cancel, execute_pending |
| `test_order_matching.py` | 13 | Order matching logic — limit trigger, stop_loss trigger, partial fills |
| `test_order_repo.py` | 21 | `OrderRepository` — create, get, list, cancel, update_status, count_open |
| `test_order_validators.py` | 15 | `OrderValidator` — symbol validation, quantity bounds, price requirements per type |
| `test_portfolio_metrics.py` | 14 | `PerformanceMetrics` — Sharpe, Sortino, drawdown, win rate from trade history |
| `test_portfolio_tracker.py` | 8 | `PortfolioTracker` — get_portfolio, get_positions, get_pnl, agent-scoped |
| `test_price_cache.py` | 21 | `PriceCache` — get/set price, get_all, pipeline batch update, pub/sub |
| `test_price_ingestion_service.py` | 6 | Price ingestion service — tick source creation, tick processing, shutdown, error handling (patches `_create_tick_source`) |
| `test_rate_limit_middleware.py` | 13 | `RateLimitMiddleware` — per-endpoint limits, header injection, Redis key patterns |
| `test_redis_client.py` | 8 | Redis client wrapper — connect, disconnect, health check |
| `test_risk_manager.py` | 23 | `RiskManager` 8-step validation chain — account status, daily loss, rate limit, order size, position limit, balance |
| `test_sandbox_risk_limits.py` | 9 | `BacktestSandbox` risk limits — max_order_size_pct, max_position_size_pct, daily_loss_limit_pct |
| `test_sdk_client.py` | 116 | Python SDK — sync/async clients, all API methods, error handling, WebSocket streaming |
| `test_slippage.py` | 14 | `SlippageCalculator` — market impact, fee calculation, edge cases |
| `test_snapshot_engine.py` | 3 | `SnapshotEngine` — capture for active participants, skip paused, capture_all_active_battles |
| `test_snapshot_engine_pnl.py` | 6 | Snapshot PnL — unrealized PnL calculation with real price cache lookups |
| `test_snapshot_repo.py` | 15 | `SnapshotRepository` — insert, query by time range, bulk insert |
| `test_snapshot_service.py` | 4 | `SnapshotService` — periodic capture orchestration |
| `test_symbol_mapper.py` | 30 | `SymbolMapper` — forward/reverse mapping, heuristic fallback, round-trip, market data loading |
| `test_task_backtest_cleanup.py` | 9 | Celery task: auto-cancel stale backtests, delete old detail data |
| `test_task_battle_snapshots.py` | 10 | Celery task: battle snapshot capture (5s interval), auto-completion (10s) |
| `test_task_candle_aggregation.py` | 5 | Celery task: OHLCV candle aggregation from raw ticks |
| `test_task_cleanup.py` | 11 | Celery task: general cleanup — old ticks, expired sessions |
| `test_task_limit_order_monitor.py` | 10 | Celery task: pending order matching — limit, stop_loss, take_profit triggers |
| `test_task_portfolio_snapshots.py` | 7 | Celery task: periodic portfolio snapshot capture |
| `test_tick_buffer.py` | 14 | `TickBuffer` — buffer, flush to DB via asyncpg COPY, max size trigger |
| `test_tick_repo.py` | 14 | `TickRepository` — insert, query by symbol/time range, aggregation |
| `test_time_simulator.py` | 14 | `TimeSimulator` — virtual clock stepping, bounds, interval math |
| `test_trade_repo.py` | 21 | `TradeRepository` — create, get, list by account/agent, PnL aggregation |
| `test_unified_metrics.py` | 15 | `calculate_unified_metrics` — ROI, PnL, Sharpe, Sortino, drawdown, win rate, profit factor, annualization |
| `test_wallet_manager.py` | 5 | `WalletManager` — snapshot/restore wallets for battle isolation |
| `test_ws_manager.py` | 23 | `WebSocketManager` — connect, subscribe, unsubscribe, broadcast, channel routing |
| `test_agent_api_call_repo.py` | 9 | `AgentApiCallRepository` — bulk save, list by trace_id, aggregate latency/cost stats |
| `test_agent_strategy_signal_repo.py` | 10 | `AgentStrategySignalRepository` — bulk save, list by source/action, daily attribution query |
| `test_task_agent_analytics.py` | 16 | `settle_agent_decisions` Celery task — settlement flows, pending-skip, missing-order, negative PnL, cancelled orders, beat schedule registration |
| `test_ab_testing.py` | 59 | `ABTestRunner` — A/B test creation, variant assignment, statistical significance, result aggregation |
| `test_agent_budget.py` | 21 | `BudgetManager` — daily trade limits, budget exhaustion, reset, Redis-backed state |
| `test_agent_budget_repo.py` | 25 | `AgentBudgetRepository` — CRUD for budget limits and budget history |
| `test_agent_decision_repo.py` | 20 | `AgentDecisionRepository` — decision persistence, query by session/status, settlement tracking |
| `test_agent_learning_repo.py` | 25 | `AgentLearningRepository` — learning record CRUD, query by agent/strategy |
| `test_agent_message_repo.py` | 17 | `AgentMessageRepository` — message store/retrieve for conversation history |
| `test_agent_permissions.py` | 39 | `PermissionEnforcer`, `CapabilityManager` — role checks, capability grants, ADMIN enforcement |
| `test_agent_session.py` | 33 | `AgentSession` — DB-backed session lifecycle, auto-summarisation, error handling |
| `test_agent_session_repo.py` | 20 | `AgentSessionRepository` — session CRUD, list by agent/status |
| `test_agent_tools.py` | 31 | Agent self-reflection and journal tools — feedback submission, memory query |
| `test_context_builder.py` | 29 | `ContextBuilder` — 6-section LLM context assembly, symbol/regime scoping |
| `test_intent_router.py` | 64 | `IntentRouter` — 3-layer classification, 7 intent types, routing to handlers |
| `test_permission_enforcement.py` | 35 | `PermissionEnforcer` — action→capability mapping, TOCTOU safety, audit logging |
| `test_strategy_manager.py` | 85 | `StrategyManager` — rolling windows, degradation detection, strategy adjustments, A/B wiring |

## Mock Patterns

### Shared fixtures (from `tests/conftest.py`)

All shared fixtures live in `tests/conftest.py` (not a unit-level conftest):

- **`test_settings`** — Patches `src.config.get_settings` to bypass `lru_cache`, returns a `Settings` with test-safe values (fake DB/Redis URLs, short JWT secret). Use this whenever code calls `get_settings()`.
- **`mock_db_session`** — `AsyncMock` of `AsyncSession` with `execute`, `flush`, `commit`, `rollback`, `refresh`, `add`, `begin_nested` pre-wired. The standard way to mock database access.
- **`mock_redis`** — `AsyncMock` of `redis.asyncio.Redis` with `hset`, `hget`, `hgetall`, `publish`, `pipeline` (including `__aenter__`/`__aexit__`) pre-wired. Pipeline commands (`hset`, `publish`) are sync `MagicMock`; only `execute()` is async.
- **`mock_asyncpg_pool`** — Mock asyncpg pool whose `acquire()` returns an async context manager with `copy_records_to_table`. Used by `TickBuffer` tests.
- **`mock_price_cache`** — `AsyncMock` of `PriceCache` with `get_price`, `set_price`, `get_all_prices`, `update_ticker`.
- **`sample_tick` / `sample_ticks`** — Pre-built `Tick` namedtuples for price ingestion tests.

### ORM model factories (from `tests/conftest.py`)

Plain functions (not fixtures) for creating unpersisted ORM instances:

- `make_account(display_name, balance, account_id, email, status)` — returns `Account`
- `make_agent(account_id, name, risk_profile, agent_id)` — returns `Agent`
- `make_order(symbol, side, type, quantity, price, status, account_id, agent_id)` — returns `Order`
- `make_trade(symbol, side, quantity, price, fee, pnl, account_id, agent_id, order_id)` — returns `Trade`
- `make_battle(name, status, mode, config, account_id)` — returns `Battle`
- `make_balance(asset, available, locked, account_id, agent_id)` — returns `Balance`

### Common per-file mock patterns

1. **Service tests** (e.g., `test_account_service.py`, `test_battle_service.py`): Construct the service with mocked dependencies, then set return values on `svc._some_repo.method = AsyncMock(return_value=...)`. Use `@patch("src.module.function")` for utility functions like `hash_password`, `generate_api_credentials`.

2. **Repository tests** (e.g., `test_order_repo.py`, `test_balance_repo.py`): Construct the repo with `mock_db_session`, wire `session.execute.return_value` to a `MagicMock()` chain: `mock_result.scalars().first()` or `.all()` for query results.

3. **Engine tests** (e.g., `test_backtest_engine.py`, `test_historical_battle_engine.py`): Construct the engine with a `MagicMock(session_factory)`, then `patch("src.backtesting.engine.DataReplayer")` to control price data. Use `mock_session_model` fixtures for ORM models loaded from DB.

4. **Direct instantiation tests** (e.g., `test_sandbox_risk_limits.py`, `test_unified_metrics.py`, `test_time_simulator.py`): No mocking needed — instantiate the class directly with known inputs and assert outputs. Used for pure-logic components.

5. **Middleware tests** (e.g., `test_rate_limit_middleware.py`, `test_logging_middleware.py`): Build a minimal Starlette/FastAPI test app, mount the middleware, and use `httpx.AsyncClient` or `TestClient` to send requests.

6. **Builder pattern** (e.g., `test_order_engine.py`): A `_build_engine()` helper constructs the `OrderEngine` with all collaborators pre-mocked and returns `(engine, mocks_dict)` for easy access in assertions.

### DB query result mocking

The standard pattern for mocking SQLAlchemy async query results:
```python
mock_result = MagicMock()
mock_result.scalars.return_value.first.return_value = some_orm_object  # for .first()
mock_result.scalars.return_value.all.return_value = [obj1, obj2]       # for .all()
mock_result.scalar_one_or_none.return_value = some_value               # for scalar
mock_db_session.execute.return_value = mock_result
```

### Redis pipeline mocking

Pipeline commands are synchronous inside a pipeline context; only `execute()` is awaited:
```python
mock_pipe = MagicMock()
mock_pipe.hset = MagicMock()       # sync
mock_pipe.publish = MagicMock()    # sync
mock_pipe.execute = AsyncMock()    # async
mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
mock_pipe.__aexit__ = AsyncMock(return_value=False)
redis.pipeline = MagicMock(return_value=mock_pipe)
```

## Common Tasks

### Adding a new unit test file

1. Create `tests/unit/test_<module_name>.py`.
2. Import from `tests.conftest` factories as needed: `from tests.conftest import make_account, make_agent, make_order, make_trade`.
3. Use shared fixtures by name in function signatures: `mock_db_session`, `mock_redis`, `mock_price_cache`, `test_settings`.
4. No `@pytest.mark.asyncio` decorator needed — `asyncio_mode = "auto"` is set in `pyproject.toml`.
5. Group related tests in classes (e.g., `class TestRegister:`, `class TestDrawdown:`).
6. Use `Decimal` for all monetary values — never `float`.
7. Run `ruff check tests/unit/test_<module_name>.py` before committing. Note: `ANN` and `S` rules are skipped for test files.

### Running specific tests

```bash
pytest tests/unit/test_order_engine.py                          # one file
pytest tests/unit/test_order_engine.py::test_market_buy_fills   # one test
pytest tests/unit/ -k "backtest"                                # keyword filter
pytest tests/unit/ --cov=src --cov-report=html                  # with coverage
```

## Gotchas & Pitfalls

- **`get_settings()` uses `lru_cache`** — In tests, you must patch `src.config.get_settings` *before* the cached instance is created, or use the `test_settings` fixture which handles this. If a test imports a module that calls `get_settings()` at import time, the real config leaks in.
- **Redis pipeline mock must have `__aenter__`/`__aexit__`** — Code uses `async with redis.pipeline() as pipe:`. If the mock pipeline lacks these dunder methods, you get `TypeError: object MagicMock can't be used in 'await' expression`.
- **`session.add()` is sync, not async** — SQLAlchemy's `session.add()` is synchronous. Use `MagicMock()` not `AsyncMock()` for it. Same for `session.add_all()`.
- **`begin_nested()` returns an async context manager** — Must be wired with `__aenter__`/`__aexit__` on the return value.
- **MagicMock spec matters for attribute access** — When using `MagicMock(spec=Order)`, accessing attributes not on the real `Order` class raises `AttributeError`. Use plain `MagicMock()` when you need flexible attribute setting.
- **Order engine tests: `cancel()` must return the order object** — `order_repo.cancel` must be mocked to return the order (not a bare `AsyncMock`), because `_release_locked_funds` accesses `.price`, `.quantity`, `.side` on the result.
- **No `conftest.py` inside `tests/unit/`** — All shared fixtures live in `tests/conftest.py` (one level up). If you need unit-specific fixtures, you can create `tests/unit/conftest.py`, but currently none exists.
- **`BacktestSandbox` tests are pure (no mocks)** — `BacktestSandbox` and `TimeSimulator` are direct-instantiation tests. They take plain Python inputs and return plain outputs. Do not add unnecessary mocks.
- **Test classes do not inherit from anything** — Plain classes, no `unittest.TestCase`. Methods are `async def` or `def` depending on whether the code under test is async.

## Recent Changes

- `2026-03-17` — Initial CLAUDE.md created
- `2026-03-18` — Added `test_symbol_mapper.py` (30 tests). Updated `test_price_ingestion_service.py` to patch `_create_tick_source` instead of removed module-level `BinanceWebSocketClient` import.
- `2026-03-18` — Removed duplicate inventory rows. Verified 70 files on disk match 70 entries in the table.
- `2026-03-19` — Synced test count: 1194 → 1184 (actual grep count of `def test_` / `async def test_` functions). 70 files confirmed.
- `2026-03-20` — Verified: still 70 test files on disk. No new unit test files added this session.
- `2026-04-06` — Added 15 new test files from agent ecosystem phases (conversation, memory, permissions) and QA sprint fixes: `test_ab_testing.py`, `test_agent_budget.py`, `test_agent_budget_repo.py`, `test_agent_decision_repo.py`, `test_agent_learning_repo.py`, `test_agent_message_repo.py`, `test_agent_permissions.py`, `test_agent_session.py`, `test_agent_session_repo.py`, `test_agent_tools.py`, `test_context_builder.py`, `test_intent_router.py`, `test_permission_enforcement.py`, `test_strategy_manager.py`. File count: 72 → 87. Test count updated to 1734.
- `2026-03-21` — Added `test_agent_api_call_repo.py` (9 tests) and `test_agent_strategy_signal_repo.py` (10 tests) for Agent Logging System. File count: 70 → 72. Test count: 1184 → 1203.
