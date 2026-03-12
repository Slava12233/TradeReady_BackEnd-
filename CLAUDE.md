# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Mandatory Pre/Post Task Protocol

Before starting ANY task, read these files in order:
1. `context.md` — architecture, stack, design decisions (single source of truth for architecture)
2. `tasks.md` — full task breakdown with statuses
3. `developmentprogress.md` — current phase, progress, blockers
4. `developmantPlan.md` — the relevant section(s) for the component you are implementing
5. `backtesting_tasks.md` — backtesting-specific task breakdown (for any BT-* tasks)

`developmantPlan.md` is the absolute authority. ALL implementation — file names, class names, method signatures, DB schema, API endpoints — MUST match what it specifies. Do not deviate or "improve" without explicit user approval.

After completing any task, update:
- `tasks.md` — mark task `[x]` Done
- `developmentprogress.md` — update progress %, add changelog entry
- `context.md` — only if architecture/stack decisions changed

**One file at a time:** Create exactly ONE source file per step, explain its purpose and connections, then wait for user confirmation before proceeding.

## Running the Platform

```bash
# Start all services (requires Docker)
docker compose up -d

# API server (local dev, no Docker)
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Price ingestion service
python -m src.price_ingestion.service

# MCP server (stdio transport — for Claude Desktop / MCP clients)
MCP_API_KEY=ak_live_... python -m src.mcp.server
# With JWT for authenticated endpoints:
MCP_API_KEY=ak_live_... MCP_JWT_TOKEN=eyJ... python -m src.mcp.server

# Celery worker
celery -A src.tasks.celery_app worker --loglevel=info

# Celery beat (scheduler)
celery -A src.tasks.celery_app beat --loglevel=info
```

Access points: API `http://localhost:8000`, Swagger docs `http://localhost:8000/docs`, Prometheus metrics `http://localhost:8000/metrics`, Grafana `http://localhost:3000`, Prometheus `http://localhost:9090`, WebSocket `ws://localhost:8000/ws/v1?api_key=...`

## Testing

```bash
pytest --cov=src --cov-report=html      # All tests with coverage
pytest tests/unit/                       # Unit tests only (mock external deps)
pytest tests/integration/                # Integration tests (requires Docker services)
pytest tests/unit/test_order_engine.py  # Single test file
pytest tests/unit/test_order_engine.py::test_market_buy_fills  # Single test
locust -f tests/load/locustfile.py --host=http://localhost:8000
```

- `asyncio_mode = "auto"` in pyproject.toml — no need for `@pytest.mark.asyncio` on async tests
- Ruff skips `ANN` and `S` rules for `tests/**/*.py`
- In tests, instantiate the app via `from src.main import create_app; app = create_app()` — do not import `app` directly, as the factory is the testable surface.
- `tests/conftest.py` provides factory fixtures (`make_tick()`, etc.) and `AsyncMock` wiring for Redis/asyncpg. Redis pipeline mocks need `__aenter__`/`__aexit__` for `async with redis.pipeline()`.
- **Gotcha:** `get_settings()` uses `lru_cache` — tests must patch it before the cached instance is created, or override via dependency injection.
- **Backtesting tests:**
  - Unit: `tests/unit/test_time_simulator.py`, `test_data_replayer.py`, `test_backtest_sandbox.py`, `test_backtest_engine.py`, `test_backtest_results.py`
  - Integration: `tests/integration/test_backtest_e2e.py`, `test_no_lookahead.py`, `test_agent_backtest_workflow.py`, `test_concurrent_backtests.py`, `test_backtest_api.py`

## Linting, Type Checking, Migrations

```bash
ruff check src/ tests/     # Lint (config in pyproject.toml: line-length=120, Python 3.12)
ruff check --fix src/      # Auto-fix lint issues
mypy src/                  # Type check (strict mode; asyncpg/celery/locust have ignore_missing_imports)

alembic revision --autogenerate -m "description"   # Create migration
alembic upgrade head                                # Apply migrations
alembic downgrade -1                                # Rollback one

python scripts/seed_pairs.py       # Seed Binance USDT pairs
python scripts/validate_phase1.py  # Validate Phase 1 health
python scripts/backfill_history.py # Backfill Binance historical klines into candles_backfill
```

## Architecture Overview

This is a simulated crypto exchange where AI agents trade **virtual USDT** against **real Binance market data**. Supports 600+ USDT pairs with real-time price feeds, order execution, risk controls, and portfolio tracking.

### Ten Core Components

| # | Component | Key Files |
|---|-----------|-----------|
| 1 | **Price Ingestion** — Binance WS → Redis + TimescaleDB | `src/price_ingestion/` |
| 2 | **Redis Cache** — sub-ms price lookups, rate limiting, pub/sub | `src/cache/` |
| 3 | **TimescaleDB** — tick history, OHLCV candles, trades | `src/database/` |
| 4 | **Order Engine** — Market/Limit/Stop-Loss/Take-Profit | `src/order_engine/` |
| 5 | **Account Management** — registration, auth, API keys, balances | `src/accounts/` |
| 6 | **Portfolio Tracker** — real-time PnL, Sharpe, drawdown | `src/portfolio/` |
| 7 | **Risk Management** — position limits, daily loss circuit breaker | `src/risk/` |
| 8 | **API Gateway** — REST + WebSocket, middleware | `src/api/` |
| 9 | **Monitoring** — Prometheus metrics, health checks, structured logs | `src/monitoring/` |
| 10 | **Backtesting Engine** — historical replay, sandbox trading, metrics | `src/backtesting/` |

### Dependency Direction (strict)
```
Routes → Schemas + Services
Services → Repositories + Cache + External clients
Repositories → Models + Session
```
Never import upward in this chain.

### Middleware Execution Order
Starlette adds middleware LIFO. Registration order in `create_app()`:
```
RateLimitMiddleware → AuthMiddleware → LoggingMiddleware → route handler
```
`AuthMiddleware` must run before `RateLimitMiddleware` so `request.state.account` is populated before rate-limit checks.

### Key Data Flows

**Price ingestion:** Binance WebSocket → update Redis `HSET prices {SYMBOL} {price}` → buffer ticks in memory → periodic flush to TimescaleDB via asyncpg COPY → broadcast on Redis pub/sub for WebSocket clients.

**Order execution:** `POST /api/v1/trade/order` → RiskManager (8-step validation) → fetch price from Redis → market orders fill immediately with slippage; limit/stop orders queue as pending and are matched by background Celery task.

**Backtesting:** `POST /backtest/create` → `POST /backtest/{id}/start` (bulk preloads all candle data into memory) → agent calls `POST /step` or `/step/batch` in a loop, reading prices and placing orders via sandbox endpoints → engine auto-completes on last step → `GET /results` returns metrics, equity curve, trade log. All data flows through an in-memory `BacktestSandbox` (no live Redis/exchange interaction). The `DataReplayer` enforces `WHERE bucket <= virtual_clock` on every query to prevent look-ahead bias.

### Redis Key Patterns
- Current prices: `HSET prices {SYMBOL} {price}`
- Rate limits: `INCR rate_limit:{api_key}:{endpoint}:{minute}` + `EXPIRE 60`
- Circuit breaker: `HSET circuit_breaker:{account_id} daily_pnl {value}`

### Database
- All DB access through repository classes in `src/database/repositories/`
- All write operations must be atomic (SQLAlchemy transactions)
- `NUMERIC(20,8)` for all price/quantity/balance columns
- TimescaleDB hypertables for time-series only (`ticks`, `portfolio_snapshots`, `backtest_snapshots`)
- Backtesting tables: `backtest_sessions`, `backtest_trades`, `backtest_snapshots` (migration: `005_backtesting_tables.py`)
- `candles_backfill` table stores Binance historical klines for periods before live ingestion (populated via `scripts/backfill_history.py`)

### API Authentication
All REST endpoints accept either:
- `X-API-Key: ak_live_...` header
- `Authorization: Bearer <jwt>` header

WebSocket authenticates via `?api_key=ak_live_...` query param (close code 4401 on failure).

### WebSocket Protocol
After connecting, send JSON messages to subscribe/unsubscribe:
```json
{"action": "subscribe",   "channel": "ticker", "symbol": "BTCUSDT"}
{"action": "unsubscribe", "channel": "ticker", "symbol": "BTCUSDT"}
{"action": "subscribe",   "channel": "orders"}
```

## Backtesting Engine

The backtesting system lets AI agents replay historical market data and test trading strategies without risking real funds. The agent drives everything via API — the UI is **read-only observation**.

### Architecture & Key Files

| File | Purpose |
|------|---------|
| `src/backtesting/engine.py` | **BacktestEngine** — orchestrator, manages active sessions (singleton) |
| `src/backtesting/time_simulator.py` | **TimeSimulator** — virtual clock, steps through time range |
| `src/backtesting/data_replayer.py` | **DataReplayer** — loads prices from TimescaleDB + candles_backfill |
| `src/backtesting/sandbox.py` | **BacktestSandbox** — in-memory exchange (balances, orders, positions, trades) |
| `src/backtesting/results.py` | **Metrics calculator** — Sharpe, Sortino, drawdown, win rate, profit factor |
| `src/api/routes/backtest.py` | All backtest REST endpoints |
| `src/api/schemas/backtest.py` | Pydantic request/response models |
| `src/database/repositories/backtest_repo.py` | DB persistence (sessions, trades, snapshots) |
| `src/tasks/backtest_cleanup.py` | Celery tasks: auto-cancel stale, delete old detail data |
| `alembic/versions/005_backtesting_tables.py` | Migration: backtest_sessions, backtest_trades, backtest_snapshots |
| `scripts/backfill_history.py` | Populate candles_backfill with Binance historical klines |

### API Endpoints

All under `/api/v1/backtest/` prefix, require authentication.

**Lifecycle:**
- `POST /create` — create session (date range, balance, pairs, strategy label)
- `POST /{id}/start` — initialize sandbox, bulk preload price data
- `POST /{id}/step` — advance one candle interval
- `POST /{id}/step/batch` — advance N candles (body: `{"steps": N}`)
- `POST /{id}/cancel` — abort early, save partial results
- `GET  /{id}/status` — progress, current equity, virtual time

**Sandbox trading (scoped to session):**
- `POST   /{id}/trade/order` — place order in sandbox
- `GET    /{id}/trade/orders` — list orders
- `GET    /{id}/trade/orders/open` — pending orders
- `GET    /{id}/trade/order/{oid}` — order status
- `DELETE /{id}/trade/order/{oid}` — cancel order
- `GET    /{id}/trade/history` — trade log

**Sandbox market data:**
- `GET /{id}/market/price/{symbol}` — price at virtual_time
- `GET /{id}/market/prices` — all prices at virtual_time
- `GET /{id}/market/ticker/{symbol}` — 24h stats at virtual_time
- `GET /{id}/market/candles/{symbol}` — candles before virtual_time

**Sandbox account:**
- `GET /{id}/account/balance` — sandbox balances
- `GET /{id}/account/positions` — sandbox positions
- `GET /{id}/account/portfolio` — sandbox portfolio summary

**Results & analysis:**
- `GET /{id}/results` — full results + metrics
- `GET /{id}/results/equity-curve` — equity curve data points
- `GET /{id}/results/trades` — complete trade log
- `GET /list` — list all backtests (filters: strategy_label, status, sort_by, limit)
- `GET /compare` — compare multiple sessions side-by-side
- `GET /best` — best session by metric

**Mode management (under `/api/v1/account/`):**
- `GET  /mode` — current operating mode (live/backtest)
- `POST /mode` — switch mode

**Historical data range (under `/api/v1/market/`):**
- `GET /data-range` — earliest/latest timestamps, total pairs

### Performance Optimizations

- **Bulk preload**: `DataReplayer.preload_range()` loads ALL candle close prices for the full date range in a single SQL query into an in-memory dict (`_price_cache`). Subsequent `load_prices()` calls serve from cache with zero DB queries.
- **Bisect lookup**: `_sorted_buckets` list + `bisect.bisect_right()` for O(log n) nearest-bucket lookups when timestamps don't align exactly.
- **Snapshot frequency**: Equity snapshots captured every 60 steps (not every step), or when orders fill, or on the last step.
- **DB write batching**: Progress written to DB every 500 steps (not every step), reducing write I/O.
- **UNION with backfill**: All price queries UNION `candles_1m` (live aggregates) with `candles_backfill` (historical klines at any interval: 1m, 5m, 1h, 1d) to cover periods before live ingestion.
- **Auto-completion**: Engine auto-calls `complete()` when the last step is reached, persisting all results.

### Orphan Detection

If the server restarts while a backtest is running, the in-memory session is lost but the DB status remains "running". The `/status` and `/list` endpoints detect orphaned sessions (status=running but not in `BacktestEngine._active`) and auto-mark them as "failed" via direct SQL UPDATE.

### Look-Ahead Bias Prevention

**Critical invariant**: Every query in `DataReplayer` filters `WHERE bucket <= virtual_clock`. The agent can never see future prices. This is enforced at the data layer, not the API layer, so there is no way to bypass it.

### Backtest DB Schema

- `backtest_sessions` — one row per backtest run (config, status, metrics JSONB, final equity, ROI, etc.)
- `backtest_trades` — all trades within a session (FK → sessions ON DELETE CASCADE)
- `backtest_snapshots` — equity snapshots over time (TimescaleDB hypertable, FK → sessions ON DELETE CASCADE)
- `accounts` table extended with `current_mode` and `active_strategy_label` columns

### Frontend (Read-Only)

The backtesting UI is observation-only — no create/edit/action buttons.

**Pages:**
- `/backtest` — list view (active card + completed table + agent mode status)
- `/backtest/[session_id]` — monitor (running) or results (completed)
- `/backtest/compare` — side-by-side comparison

**Components** (`Frontend/src/components/backtest/`):
- `shared/` — status badges, virtual time display, strategy label badge, improvement indicator
- `list/` — list page, active card, completed table, filters, agent mode status
- `monitor/` — monitor page, progress timeline, live equity chart, live stats, positions, trades feed
- `results/` — results page, summary cards, equity curve, drawdown chart, daily PnL, trade log, pair breakdown
- `compare/` — compare page, overlaid equity chart, metrics table, auto-selector

**Hooks** (`Frontend/src/hooks/`):
- `use-backtest-list.ts` — TanStack Query, fetches list with filters
- `use-backtest-status.ts` — polls running backtest every 2s, auto-stops when complete
- `use-backtest-results.ts` — fetches results + equity curve + trade log
- `use-backtest-compare.ts` — fetches comparison data, auto-groups by strategy prefix

### Documentation

- `docs/backtesting-guide.md` — technical guide (API lifecycle, strategies, step batching, position sizing)
- `docs/backtesting-explained.md` — non-technical guide (analogies, plain English)
- `docs/skill.md` — agent skill reference (includes backtesting workflow + strategy examples)
- `backtesting_tasks.md` — complete task breakdown with statuses

## Dependency Injection & Configuration

### FastAPI Dependencies (`src/dependencies.py`)
All service/repo instantiation goes through `src/dependencies.py` using FastAPI's `Depends()`. Pre-defined typed aliases exist for concise route signatures:
```python
# Use the typed aliases — NOT raw Annotated[Type, Depends(get_function)]
async def handler(db: DbSessionDep, cache: PriceCacheDep, settings: SettingsDep):
```
Available aliases: `DbSessionDep`, `RedisDep`, `PriceCacheDep`, `SettingsDep`, `AccountRepoDep`, `BalanceRepoDep`, `OrderRepoDep`, `TradeRepoDep`, `TickRepoDep`, `SnapshotRepoDep`, `BalanceManagerDep`, `AccountServiceDep`, `SlippageCalcDep`, `OrderEngineDep`, `RiskManagerDep`, `PortfolioTrackerDep`, `PerformanceMetricsDep`, `SnapshotServiceDep`, `BacktestEngineDep`, `BacktestRepoDep`.

Key patterns:
- **Lazy imports** inside dependency functions (`# noqa: PLC0415`) to avoid circular imports — do not move these to module level
- **Per-request lifecycle** for DB sessions (auto-commit on success, rollback on exception); Redis uses a shared pool (never closed per-request)
- **CircuitBreaker is account-scoped**, not a singleton — construct it per-account with `starting_balance` and `daily_loss_limit_pct` (see comment block in `dependencies.py`)
- **BacktestEngine is a singleton** — held in a module-level `_backtest_engine_instance` global

### Settings (`src/config.py`)
- `Settings` extends Pydantic v2 `BaseSettings` with `SettingsConfigDict(env_file=".env", case_sensitive=False)`
- `get_settings()` is decorated with `@lru_cache(maxsize=1)` — reads `.env` exactly once per process
- Field validators enforce: `DATABASE_URL` must use `postgresql+asyncpg://` scheme, `JWT_SECRET` must be 32+ chars
- In tests, patch `src.config.get_settings` BEFORE the cached instance is created, or it will use the real config

### Exception Hierarchy (`src/utils/exceptions.py`)
All exceptions inherit `TradingPlatformError` which provides:
- `code` (string) and `http_status` (int) class attributes as defaults
- `.to_dict()` → `{"error": {"code": ..., "message": ..., "details": ...}}`
- `details` dict for structured payloads (e.g., `InsufficientBalanceError` includes `available` and `required`)

The global exception handler in `src/main.py` auto-serializes any `TradingPlatformError` subclass.

### Alembic Async Migrations
- `alembic/env.py` uses async-first pattern: `asyncio.run(run_migrations_online())`
- Database URL is read from `get_settings()`, not hardcoded in `alembic.ini`
- Uses `NullPool` for short-lived migration connections
- `prepend_sys_path = .` in `alembic.ini` is required for `src` module imports
- Post-write hook runs `ruff format` on generated migrations

## Code Standards

- **Python 3.12+**, fully typed, `async/await` for all I/O
- **Pydantic v2** for all data models; **`Decimal`** (never `float`) for money/prices
- **Google-style docstrings** on every public class and function
- Custom exceptions from `src/utils/exceptions.py`; never bare `except:`
- All external calls (Redis, DB, Binance WS) wrapped in try/except with logging; fail closed on errors
- Import order: stdlib → third-party → local (enforced by ruff isort with `known-first-party = ["src", "sdk"]`)

### Security
- API keys generated via `secrets.token_urlsafe(48)` with `ak_live_` / `sk_live_` prefixes
- Store password/secret hashes (bcrypt), never plaintext
- Parameterized queries only (SQLAlchemy handles this — never use raw f-strings in SQL)
- All secrets via environment variables; see `.env.example`

### Naming
- Files: `snake_case.py`, Classes: `PascalCase`, Functions: `snake_case`, Constants: `UPPER_SNAKE_CASE`, Private: `_prefix`

### API Design
- All routes under `/api/v1/` prefix
- Error format: `{"error": {"code": "...", "message": "..."}}`
- Rate limit headers on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

## Git Commit Format

```
type(scope): description
```
Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`
Scope: component name (e.g., `ingestion`, `order-engine`, `api`)

## Current Phase Status

| Phase | Status |
|-------|--------|
| Phase 1: Foundation (price feed, Redis, TimescaleDB) | ✅ Complete |
| Phase 2: Trading Engine (orders, accounts, risk, portfolio) | ✅ Complete |
| Phase 3: API Layer (REST, WebSocket, Celery) | 🔄 ~85% done |
| Phase 4: Agent Connectivity (MCP server, SDK, framework guides) | 🔄 In progress |
| Phase 5: Polish & Launch | ⬜ Not started |
| **BT-1: Backtesting Backend** (engine, DB, API, tests) | ✅ Complete (31/31 tasks) |
| **BT-2: Backtesting Frontend** (list, monitor, results, compare) | ✅ Complete (31/31 tasks) |
| **BT-3: Backtesting Integration** (skill.md, SDK, MCP, E2E, ops) | 🔄 In progress (~10%) |

## SDK & Frontend

**Python SDK** (`sdk/`): `AgentExchangeClient` (sync), `AsyncAgentExchangeClient` (async), `AgentExchangeWS` (streaming). Install locally: `pip install -e sdk/`

**MCP Server** (`src/mcp/`): 12 trading tools over stdio transport. Env vars: `MCP_API_KEY` (required), `API_BASE_URL` (default `http://localhost:8000`), `MCP_JWT_TOKEN` (optional).

**Frontend** (`Frontend/`): Next.js 16, React 19, TypeScript, Tailwind CSS 4.2, pnpm. Development plans in `UiDevelopmentPlan.md` and `UIdevelopmentProgress.md`.

### Frontend Commands

```bash
cd Frontend
pnpm dev              # Dev server at http://localhost:3000
pnpm build            # Production build (zero TS/lint errors required)
pnpm test             # Unit tests (vitest)
pnpm test:e2e         # Playwright E2E tests
pnpm dlx shadcn@latest add <component-name>  # Add shadcn/ui component
```

Frontend has its own `CLAUDE.md` at `Frontend/CLAUDE.md` with full UI conventions. Key points:
- `UiDevelopmentPlan.md` is the authority for frontend (like `developmantPlan.md` is for backend)
- Read `UIcontext.md`, `UItasks.md`, `UIdevelopmentProgress.md` before frontend tasks
- Tailwind v4 configured via `@theme inline` in `src/app/globals.css` (no `tailwind.config.ts`)
- State: Zustand (WS/streaming), TanStack Query (REST), React state (local UI)
- `@/*` path alias maps to `./src/*`

## Docker

- `docker-compose.yml` — production-like setup with all services
- `docker-compose.dev.yml` — development overrides (hot reload, debug ports)
- `docker-compose.phase1.yml` — minimal setup for Phase 1 (TimescaleDB + Redis only)
- Healthchecks and resource limits defined for all containers

## Environment Variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | TimescaleDB async connection string |
| `REDIS_URL` | Redis connection string |
| `BINANCE_WS_URL` | Binance WebSocket base URL |
| `JWT_SECRET` | JWT signing secret (64+ chars) |
| `TRADING_FEE_PCT` | Simulated fee (default 0.1%) |
| `DEFAULT_STARTING_BALANCE` | New account balance (default 10000 USDT) |
| `DEFAULT_SLIPPAGE_FACTOR` | Base slippage factor (default 0.1) |
| `CELERY_BROKER_URL` | Celery broker (defaults to `REDIS_URL`) |
| `CELERY_RESULT_BACKEND` | Celery results (defaults to `REDIS_URL`) |
| `TICK_FLUSH_INTERVAL` | Tick buffer flush interval in seconds (default 1.0) |
| `TICK_BUFFER_MAX_SIZE` | Max ticks buffered before forced flush (default 5000) |
| `NEXT_PUBLIC_API_BASE_URL` | Frontend: backend REST API base URL |
| `NEXT_PUBLIC_WS_URL` | Frontend: backend WebSocket URL |
