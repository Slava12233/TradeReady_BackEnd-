# CLAUDE.md

<!-- last-updated: 2026-03-17 -->

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **First step rule:** At the start of every conversation, read `development/context.md` before doing anything else. It contains a rolling summary of all development activity, decisions, and current state.

> **Self-maintenance rule:** When modifying code in any folder, update that folder's `CLAUDE.md` if behavior, files, or patterns changed. Update the `<!-- last-updated -->` timestamp when you do.

## CLAUDE.md Index

Each module has its own `CLAUDE.md` with detailed file inventories, public APIs, patterns, and gotchas. Read the local file before working in that folder.

### Backend (`src/`)

| Path | Description |
|------|-------------|
| `src/accounts/CLAUDE.md` | Account service, registration, auth, API keys, balance management |
| `src/agents/CLAUDE.md` | Multi-agent CRUD, clone, reset, avatar generation |
| `src/api/CLAUDE.md` | API gateway overview, middleware stack, route registry |
| `src/api/routes/CLAUDE.md` | All REST endpoints (86+), auth requirements, patterns |
| `src/api/schemas/CLAUDE.md` | Pydantic v2 schemas, validation patterns |
| `src/api/middleware/CLAUDE.md` | Auth, rate limiting, logging middleware — execution order |
| `src/api/websocket/CLAUDE.md` | WebSocket channels, protocol, subscription model |
| `src/backtesting/CLAUDE.md` | Backtest engine, sandbox, time simulation, data replay |
| `src/battles/CLAUDE.md` | Battle system, ranking, snapshots, historical engine |
| `src/cache/CLAUDE.md` | Redis cache layer, key patterns, pub/sub |
| `src/database/CLAUDE.md` | ORM models, async session management, repository pattern |
| `src/database/repositories/CLAUDE.md` | All repository classes, query patterns |
| `src/mcp/CLAUDE.md` | MCP server, 12 tools, stdio transport |
| `src/metrics/CLAUDE.md` | Unified metrics calculator, adapters |
| `src/monitoring/CLAUDE.md` | Prometheus metrics, health checks |
| `src/order_engine/CLAUDE.md` | Order execution, matching, slippage |
| `src/portfolio/CLAUDE.md` | Portfolio tracking, PnL calculation, snapshots |
| `src/price_ingestion/CLAUDE.md` | Binance WS, tick buffering, flush cycle |
| `src/risk/CLAUDE.md` | Risk manager, circuit breaker, position limits |
| `src/tasks/CLAUDE.md` | Celery tasks, beat schedule, cleanup jobs |
| `src/utils/CLAUDE.md` | Exception hierarchy, shared utilities |

### Tests

| Path | Description |
|------|-------------|
| `tests/CLAUDE.md` | Test philosophy, conftest fixtures, async patterns, gotchas |
| `tests/unit/CLAUDE.md` | Unit test inventory (62 files, 974 tests), mock patterns |
| `tests/integration/CLAUDE.md` | Integration test setup (20 files, 433 tests), app factory |

### Infrastructure & Other

| Path | Description |
|------|-------------|
| `alembic/CLAUDE.md` | Migration workflow, async env, naming convention, inventory |
| `Frontend/CLAUDE.md` | Next.js 16 / React 19 / Tailwind v4 frontend conventions |
| `Frontend/src/app/CLAUDE.md` | App Router structure, layouts, route groups |
| `Frontend/src/components/CLAUDE.md` | Component organization (130+ files), shadcn/ui patterns |
| `Frontend/src/components/backtest/CLAUDE.md` | Backtest UI components, sub-folder structure |
| `Frontend/src/components/battles/CLAUDE.md` | Battle UI components (planned, not yet built) |
| `Frontend/src/hooks/CLAUDE.md` | Hook inventory (23 hooks), TanStack Query patterns |
| `Frontend/src/lib/CLAUDE.md` | API client, utilities, constants, chart config |
| `Frontend/src/stores/CLAUDE.md` | Zustand stores (6), persistence, agent state |
| `sdk/CLAUDE.md` | Python SDK — sync/async clients, WebSocket client |
| `scripts/CLAUDE.md` | Available scripts, when to run each, dependencies |
| `docs/CLAUDE.md` | Documentation inventory, audience for each doc |

---

## Sub-Agents (`.claude/agents/`)

Custom agents that can be delegated to for specialized tasks:

| Agent | Purpose | When to Use |
|-------|---------|-------------|
| `code-reviewer` | Reviews code against all project standards by reading relevant CLAUDE.md files | After every code change |
| `test-runner` | Maps changed files to tests, runs them, writes missing tests | After every code change (after code-reviewer) |
| `migration-helper` | Generates and validates Alembic migrations for safety (destructive ops, two-phase NOT NULL, rollback paths) | Before creating or running any migration |
| `api-sync-checker` | Compares Pydantic schemas vs TypeScript types, verifies frontend/backend route sync | After changing API routes, schemas, or frontend API code |
| `doc-updater` | Updates docs/skill.md, api_reference.md, module CLAUDE.md files when code changes | After API, schema, or module changes |
| `security-auditor` | Audits for auth bypasses, injection risks, secret exposure, agent isolation violations | After security-sensitive changes |
| `perf-checker` | Detects N+1 queries, blocking async calls, missing indexes, unbounded growth | After changes to DB queries, async code, or hot paths |
| `context-manager` | Maintains a rolling summary of all development activity — changes, decisions, bugs, learnings, WIP | After every significant change (proactively) |
| `deploy-checker` | Comprehensive A-Z backend deployment readiness checker — lint, types, tests, migrations, Docker, env vars, security, GitHub Actions pipeline validation | Before deploying to production or merging to main |
| `codebase-researcher` | Researches the codebase to answer questions, find patterns, trace data flows, and explain how things work. Uses CLAUDE.md hierarchy as primary navigation | When you need to understand how something works, find implementations, or trace data flows before making changes |
| `planner` | Expert planning specialist for complex features and refactoring. Creates detailed, phased implementation plans with file paths, risks, and testing strategies | PROACTIVELY when users request feature implementation, architectural changes, or complex refactoring |
| `security-reviewer` | Security vulnerability detection and remediation. Flags secrets, SSRF, injection, agent isolation violations, OWASP Top 10. Can fix CRITICAL issues directly | PROACTIVELY after writing code that handles user input, auth, API endpoints, or sensitive data |
| `e2e-tester` | Runs live E2E scenarios against the running platform — creates accounts, agents, trades, backtests, battles. All data visible in the UI. Returns login credentials | When you need to populate realistic data for UI testing, validate the full stack end-to-end, or demo the platform |

### Mandatory Agent Rules

- **After ANY code change**, delegate to `code-reviewer` then `test-runner` in sequence. Do not skip either step.
- **Before ANY migration**, delegate to `migration-helper` to validate or generate the migration safely.
- **After API/schema changes**, delegate to `api-sync-checker` to verify frontend/backend are in sync, then `doc-updater` to update documentation.
- **For security-sensitive changes** (auth, middleware, agent scoping, input handling), delegate to `security-auditor`.
- **For performance-sensitive changes** (DB queries, async code, caching, ingestion), delegate to `perf-checker`.
- If the `test-runner` agent identifies missing test coverage, it will write new tests following `tests/CLAUDE.md` standards.
- If tests fail, fix the code (or tests if behavior intentionally changed), then re-run via `test-runner` until all pass.
- **After every significant change**, delegate to `context-manager` to log what changed, why, and any decisions/learnings. This keeps `development/context.md` fresh so future conversations have full context.
- **Keep agents up to date**: When the project evolves — new modules, new test patterns, new conventions, renamed files — update the relevant `.claude/agents/*.md` files. Agents are only as useful as the instructions they contain.

---

## Production-First Development Protocol

This platform is **deployed in production with CI/CD pipelines**. Every change must be production-ready.

### Before ANY Change
1. Understand the existing code — read the files you're modifying
2. Check existing tests for the area you're changing
3. Run `ruff check` and `mypy` on affected files before committing

### After ANY Change
1. **Tests pass**: Run `pytest` for affected areas — fix broken tests or update them if behavior intentionally changed
2. **Lint clean**: `ruff check src/ tests/` must pass with zero errors
3. **Type safe**: `mypy src/` must pass
4. **No regressions**: If changing an API endpoint, verify the response shape hasn't broken consumers
5. **Migration safe**: New DB changes need Alembic migrations that work on the live database (no destructive ALTER without a plan)

### Test Quality Standards
- Tests must cover the actual behavior, not just exist for coverage numbers
- When modifying code, update tests to match — stale tests that pass on wrong behavior are worse than no tests
- Integration tests must use the app factory: `from src.main import create_app; app = create_app()`
- New features need tests before merging. Bug fixes should include a regression test.

### Historical Development Files
Original planning docs are archived in `development/` for reference. These are **reference only** — do not update them. The source of truth is the code itself.

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
- In tests, instantiate the app via `from src.main import create_app; app = create_app()` — do not import `app` directly
- **Gotcha:** `get_settings()` uses `lru_cache` — tests must patch it before the cached instance is created

See `tests/CLAUDE.md` for full fixture inventory, mock patterns, and test-specific gotchas.

## Linting, Type Checking, Migrations

```bash
ruff check src/ tests/     # Lint (config in pyproject.toml: line-length=120, Python 3.12)
ruff check --fix src/      # Auto-fix lint issues
mypy src/                  # Type check (strict mode; asyncpg/celery/locust have ignore_missing_imports)

alembic revision --autogenerate -m "description"   # Create migration
alembic upgrade head                                # Apply migrations
alembic downgrade -1                                # Rollback one

python scripts/seed_pairs.py       # Seed Binance USDT pairs
python scripts/backfill_history.py # Backfill Binance historical klines into candles_backfill
```

## Architecture Overview

This is a simulated crypto exchange where AI agents trade **virtual USDT** against **real Binance market data**. Supports 600+ USDT pairs with real-time price feeds, order execution, risk controls, and portfolio tracking.

### Core Components

| # | Component | Module |
|---|-----------|--------|
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
| 11 | **Agent Management** — multi-agent CRUD, per-agent wallets, API keys | `src/agents/` |
| 12 | **Battle System** — agent vs agent competitions with rankings, replays | `src/battles/` |
| 13 | **Unified Metrics** — shared calculator for backtests & battles | `src/metrics/` |

### Multi-Agent Architecture

Each account can own multiple **agents**, each with its own API key, starting balance, risk profile, and trading history. Trading tables (`balances`, `orders`, `trades`, `positions`) are keyed by `agent_id`.

- **API key auth** (`X-API-Key`): tries agents table first, falls back to legacy accounts table
- **JWT auth** (`Authorization: Bearer`): resolves account from JWT, agent context via `X-Agent-Id` header
- All core services accept `agent_id` for scoping (balances, orders, risk, portfolio, backtests)

See `src/agents/CLAUDE.md` and `src/api/middleware/CLAUDE.md` for full details.

### Battle System

Agent vs agent trading competitions with live monitoring, replay, and rankings. Supports both `"live"` and `"historical"` modes.

**State machine:** `draft → pending → active → completed` (with `cancelled` and `paused` branches)

See `src/battles/CLAUDE.md` for full architecture, and `src/api/routes/CLAUDE.md` for the 20 battle endpoints.

### Backtesting Engine

Agent-driven historical replay with in-memory sandbox trading. The UI is read-only observation.

**Critical invariant**: `DataReplayer` filters `WHERE bucket <= virtual_clock` — no look-ahead bias possible.

See `src/backtesting/CLAUDE.md` for full lifecycle, performance optimizations, and sandbox details.

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

**Backtesting:** `POST /backtest/create` → `/start` (bulk preloads candle data) → agent calls `/step` or `/step/batch` in a loop → engine auto-completes on last step → `GET /results` returns metrics.

### API Authentication
All REST endpoints accept either:
- `X-API-Key: ak_live_...` header
- `Authorization: Bearer <jwt>` header

WebSocket authenticates via `?api_key=ak_live_...` query param (close code 4401 on failure).

### Database
- All DB access through repository classes in `src/database/repositories/`
- All write operations must be atomic (SQLAlchemy transactions)
- `NUMERIC(20,8)` for all price/quantity/balance columns
- TimescaleDB hypertables for time-series only (`ticks`, `portfolio_snapshots`, `backtest_snapshots`)

### Redis Key Patterns
- Current prices: `HSET prices {SYMBOL} {price}`
- Rate limits: `INCR rate_limit:{api_key}:{endpoint}:{minute}` + `EXPIRE 60`
- Circuit breaker: `HSET circuit_breaker:{account_id} daily_pnl {value}`

## Dependency Injection & Configuration

### FastAPI Dependencies (`src/dependencies.py`)
All service/repo instantiation goes through `src/dependencies.py` using FastAPI's `Depends()`. Pre-defined typed aliases exist for concise route signatures:
```python
# Use the typed aliases — NOT raw Annotated[Type, Depends(get_function)]
async def handler(db: DbSessionDep, cache: PriceCacheDep, settings: SettingsDep):
```
Available aliases: `DbSessionDep`, `RedisDep`, `PriceCacheDep`, `SettingsDep`, `AccountRepoDep`, `BalanceRepoDep`, `OrderRepoDep`, `TradeRepoDep`, `TickRepoDep`, `SnapshotRepoDep`, `BalanceManagerDep`, `AccountServiceDep`, `SlippageCalcDep`, `OrderEngineDep`, `RiskManagerDep`, `PortfolioTrackerDep`, `PerformanceMetricsDep`, `SnapshotServiceDep`, `BacktestEngineDep`, `BacktestRepoDep`, `AgentRepoDep`, `AgentServiceDep`.

Key patterns:
- **Lazy imports** inside dependency functions (`# noqa: PLC0415`) to avoid circular imports — do not move these to module level
- **Per-request lifecycle** for DB sessions (auto-commit on success, rollback on exception); Redis uses a shared pool (never closed per-request)
- **CircuitBreaker is account-scoped**, not a singleton — construct it per-account with `starting_balance` and `daily_loss_limit_pct`
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

The global exception handler in `src/main.py` auto-serializes any `TradingPlatformError` subclass. See `src/utils/CLAUDE.md` for the full hierarchy.

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

## SDK & Frontend

**Python SDK** (`sdk/`): `AgentExchangeClient` (sync), `AsyncAgentExchangeClient` (async), `AgentExchangeWS` (streaming). Install locally: `pip install -e sdk/`. See `sdk/CLAUDE.md`.

**MCP Server** (`src/mcp/`): 12 trading tools over stdio transport. See `src/mcp/CLAUDE.md`.

**Frontend** (`Frontend/`): Next.js 16, React 19, TypeScript, Tailwind CSS 4.2, pnpm. See `Frontend/CLAUDE.md`.

### Frontend Commands

```bash
cd Frontend
pnpm dev              # Dev server at http://localhost:3000
pnpm build            # Production build (zero TS/lint errors required)
pnpm test             # Unit tests (vitest)
pnpm test:e2e         # Playwright E2E tests
pnpm dlx shadcn@latest add <component-name>  # Add shadcn/ui component
```

## Docker

- `docker-compose.yml` — production setup with all services
- `docker-compose.dev.yml` — development overrides (hot reload, debug ports)
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
