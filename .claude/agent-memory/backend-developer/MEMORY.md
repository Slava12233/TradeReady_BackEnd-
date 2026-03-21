# Backend Developer — Project Memory

## Dependency Injection (`src/dependencies.py`)
- All service/repo instantiation goes through typed aliases — never construct directly in routes
- Use aliases: `DbSessionDep`, `RedisDep`, `PriceCacheDep`, `SettingsDep`, `AccountRepoDep`, `BalanceRepoDep`, `OrderRepoDep`, `TradeRepoDep`, `TickRepoDep`, `SnapshotRepoDep`, `BalanceManagerDep`, `AccountServiceDep`, `SlippageCalcDep`, `OrderEngineDep`, `RiskManagerDep`, `CircuitBreakerRedisDep`, `PortfolioTrackerDep`, `PerformanceMetricsDep`, `SnapshotServiceDep`, `BacktestEngineDep`, `BacktestRepoDep`, `BattleRepoDep`, `BattleServiceDep`, `AgentRepoDep`, `AgentServiceDep`, `StrategyRepoDep`, `StrategyServiceDep`, `TestRunRepoDep`, `TestOrchestratorDep`, `TrainingRunRepoDep`, `TrainingRunServiceDep`, `AgentApiCallRepoDep`, `AgentStrategySignalRepoDep`, `AgentDecisionRepoDep`
- Lazy imports inside dependency functions (`# noqa: PLC0415`) to avoid circular imports — do not move to module level
- Per-request lifecycle for DB sessions (auto-commit on success, rollback on exception)
- Redis uses a shared pool — never close per-request
- `BacktestEngine` is a singleton held in a module-level global
- `CircuitBreaker` is account-scoped, not a singleton — construct per-account with `starting_balance` and `daily_loss_limit_pct`

## Repository Pattern
- All DB access through `src/database/repositories/` — one repository class per domain entity
- All write operations must be atomic (SQLAlchemy transactions)
- Dependency direction: Routes → Schemas + Services → Repositories + Cache → Models + Session
- Never import upward in the chain

## Database Conventions (`src/database/models.py`)
- `Numeric(20, 8)` for all monetary values — never `float`; use `Decimal` in Python code
- `TIMESTAMP(timezone=True)` for all timestamps — always UTC
- `PG_UUID(as_uuid=True)` with `server_default=func.gen_random_uuid()` for UUID PKs
- Status fields: `VARCHAR(20)` with `CheckConstraint` enforcing valid values
- JSON data stored as `JSONB`
- `cascade="all, delete-orphan"` on parent side of relationships; FK uses `ondelete="CASCADE"`
- `expire_on_commit=False`, `autoflush=False` on all sessions
- `autoflush=False` means you must call `session.flush()` to get server-default UUIDs before commit
- Hypertable composite PKs: `Tick` (time+symbol+trade_id), `PortfolioSnapshot` (id+created_at), `BacktestSnapshot` (id+simulated_at), `BattleSnapshot` (id+timestamp)
- TimescaleDB hypertables: `ticks`, `portfolio_snapshots`, `backtest_snapshots`, `battle_snapshots`

## Agent Scoping
- Trading tables (`balances`, `orders`, `trades`, `positions`, `portfolio_snapshots`) carry both `account_id` and `agent_id` FKs
- `agent_id` is the primary scoping key for all trading operations
- API key auth: tries agents table first, falls back to accounts table
- JWT auth: resolves account from JWT, agent context via `X-Agent-Id` header

## Exception Hierarchy (`src/utils/exceptions.py`)
- All exceptions inherit `TradingPlatformError` with `code` (string) and `http_status` (int)
- `.to_dict()` returns `{"error": {"code": ..., "message": ..., "details": ...}}`
- Global handler in `src/main.py` auto-serializes any `TradingPlatformError` subclass
- Never use bare `except:` — always catch specific exceptions from the hierarchy

## Code Standards
- Python 3.12+, fully typed, `async/await` for all I/O
- Pydantic v2 for all data models
- Google-style docstrings on every public class and function
- Import order: stdlib → third-party → local (ruff isort with `known-first-party = ["src", "sdk"]`)
- Security: API keys via `secrets.token_urlsafe(48)` with `ak_live_`/`sk_live_` prefixes; bcrypt for passwords; parameterized queries only
- Settings via `get_settings()` — `lru_cache`d; in tests patch before any module imports it

## Middleware Execution Order
- Registration order: `RateLimitMiddleware` → `AuthMiddleware` → `LoggingMiddleware`
- Execution order (LIFO): `LoggingMiddleware` → `AuthMiddleware` → `RateLimitMiddleware` → handler
- `AuthMiddleware` opens its OWN DB session — objects on `request.state` are detached; do not lazy-load relationships in route handlers

## Adding New Models
1. Define class in `models.py` inheriting from `Base`
2. Use `Numeric(20,8)` for money, `PG_UUID` for IDs, `TIMESTAMP(timezone=True)` for times
3. Run `alembic revision --autogenerate -m "description"`
4. NOT NULL on existing data: two-step migration (add nullable → backfill → enforce NOT NULL)

## LLM Call Logging Pattern (`agent/`)
- Standard log event after every LLM call: `"agent.llm.completed"` with `model`, `purpose`, `input_tokens`, `output_tokens`, `latency_ms`, `cost_estimate_usd`
- On failure: `"agent.llm.failed"` with `model`, `purpose`, `error`
- Token extraction from Pydantic AI result: `getattr(getattr(result, "usage", None), "input_tokens", None)` — safe for None
- For httpx raw calls (session.py): tokens are in `response.json()["usage"]["prompt_tokens"]` / `"completion_tokens"` (OpenRouter naming, not `input_tokens`)
- `estimate_llm_cost` is in `agent.logging_middleware` — import lazy with `# noqa: PLC0415`
- `time.monotonic()` imported at module level where possible; inside try blocks use `import time as _time  # noqa: PLC0415`
- ruff I001: when mixing stdlib + third-party lazy imports inside a try block, auto-fix with `ruff --fix` rather than hand-ordering
- Purpose values by file: session.py=`"session_summarization"`, journal.py=`"trade_reflection"`, trading_workflow.py=`"trade_analysis"`, backtest_workflow.py=`"backtest_analysis"`, strategy_workflow.py=`"strategy_review"`

## LogBatchWriter Pattern (`agent/logging_writer.py`)
- Accepts `session_factory: Any  # noqa: ANN401` — the whole codebase uses this pattern for `async_sessionmaker` params (see `src/backtesting/engine.py`, `agent/trading/ab_testing.py`, `src/tasks/cleanup.py`)
- Uses `async with self._session_factory() as session:` + `await session.commit()` — writer owns the transaction, not a repository
- Two independent `deque(maxlen=10_000)` — separate transactions per table so a signal flush failure cannot roll back API call rows
- `asyncio.Lock` wraps both `_flush_api_calls` + `_flush_signals` inside `flush()` — prevents double-drain from concurrent size-trigger and periodic-task races
- `stop()` sets `_running=False`, cancels task, awaits `CancelledError`, then calls `flush()` outside the lock for final drain
- Flush failures swallowed (logged only) — "accept the loss" policy to avoid blocking the agent's trading path

## Trace ID Propagation Pattern (`agent/`)
- `set_trace_id()` is called at the top of `TradingLoop.tick()` — generates a 16-char hex ID via `uuid4().hex[:16]`, stored in contextvars
- `get_trace_id()` reads it from contextvars without passing through function args — safe across all `await` calls within the same asyncio task
- `AgentDecision.trace_id` is `VARCHAR(32), nullable=True` — pass `get_trace_id() or None` to keep empty string out of the DB
- `AgentStrategySignal.trace_id` is `VARCHAR(32), nullable=False` — always set; use `get_trace_id()` directly (empty string is valid)
- When verifying pre-existing ruff violations: `git stash` the changes, run ruff on originals, then `git stash pop` — prevents attributing existing errors to new code
- `EnsembleRunner` needs `agent_id: str | None` constructor param when `batch_writer` is provided — `agent_id` becomes `agent_id_str` stored as `self._agent_id_str` for signal rows

## Structlog Event Name Convention (`agent/`)
- Convention: `"{component}.{operation}[.{outcome}]"` — all event strings must start with `agent.`
- Component prefix table (Task 05): `agent.server`, `agent.session`, `agent.decision`, `agent.trade`, `agent.memory`, `agent.permission`, `agent.budget`, `agent.strategy`, `agent.api`, `agent.llm`, `agent.workflow`, `agent.task`
- `replace_all=true` edits are fast but dangerous — strings like `"training_log.json"` get corrupted if the prefix matches a filename substring. Verify file paths before applying bulk replace.
- `grep` cannot distinguish docstring `Example::` blocks from executable code — `logger.*()` calls inside docstrings are NOT real log calls and must be left unchanged.
- After a context summary break, the Edit tool requires a prior Read on the file — always read at least a few lines before editing a file in a new conversation segment.
- Files to skip (by task spec): `agent/tasks.py` (Task 06) and `agent/main.py` (Task 02)
