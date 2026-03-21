# CLAUDE.md

<!-- last-updated: 2026-03-20 (Docker agent profile, [ml]/[all] extras, checksum security, 901 tests) -->

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
| `src/api/routes/CLAUDE.md` | All REST endpoints (90+), auth requirements, patterns |
| `src/api/schemas/CLAUDE.md` | Pydantic v2 schemas, validation patterns |
| `src/api/middleware/CLAUDE.md` | Auth, rate limiting, logging middleware — execution order |
| `src/api/websocket/CLAUDE.md` | WebSocket channels, protocol, subscription model |
| `src/backtesting/CLAUDE.md` | Backtest engine, sandbox, time simulation, data replay |
| `src/battles/CLAUDE.md` | Battle system, ranking, snapshots, historical engine |
| `src/cache/CLAUDE.md` | Redis cache layer, key patterns, pub/sub |
| `src/exchange/CLAUDE.md` | CCXT-powered exchange abstraction, adapter pattern, symbol mapper |
| `src/database/CLAUDE.md` | ORM models, async session management, repository pattern |
| `src/database/repositories/CLAUDE.md` | All repository classes, query patterns |
| `src/mcp/CLAUDE.md` | MCP server, 58 tools, stdio transport |
| `src/metrics/CLAUDE.md` | Unified metrics calculator, adapters |
| `src/monitoring/CLAUDE.md` | Prometheus metrics, health checks |
| `src/order_engine/CLAUDE.md` | Order execution, matching, slippage |
| `src/portfolio/CLAUDE.md` | Portfolio tracking, PnL calculation, snapshots |
| `src/price_ingestion/CLAUDE.md` | Exchange WS (CCXT + legacy Binance), tick buffering, flush cycle |
| `src/risk/CLAUDE.md` | Risk manager, circuit breaker, position limits |
| `src/strategies/CLAUDE.md` | Strategy registry — CRUD, versioning, testing, deployment |
| `src/tasks/CLAUDE.md` | Celery tasks, beat schedule, cleanup jobs |
| `src/training/CLAUDE.md` | Training run observation — tracking, learning curves, comparison |
| `src/utils/CLAUDE.md` | Exception hierarchy, shared utilities |

### Tests

| Path | Description |
|------|-------------|
| `tests/CLAUDE.md` | Test philosophy, conftest fixtures, async patterns, gotchas |
| `tests/unit/CLAUDE.md` | Unit test inventory (70 files, 1184 tests), mock patterns |
| `tests/integration/CLAUDE.md` | Integration test setup (24 files, 504 tests), app factory |

### Frontend (`Frontend/`)

| Path | Description |
|------|-------------|
| `Frontend/CLAUDE.md` | Next.js 16 / React 19 / Tailwind v4 frontend conventions, architecture |
| `Frontend/src/app/CLAUDE.md` | App Router structure, layouts, route groups |
| `Frontend/src/components/CLAUDE.md` | Component organization (130+ files), shadcn/ui patterns |
| `Frontend/src/components/agents/CLAUDE.md` | Agent CRUD UI — cards, grid, create modal, edit drawer |
| `Frontend/src/components/alerts/CLAUDE.md` | Price alert management — create dialog, alert sections |
| `Frontend/src/components/analytics/CLAUDE.md` | Analytics charts — equity, drawdown, PnL, heatmaps |
| `Frontend/src/components/backtest/CLAUDE.md` | Backtest UI components, sub-folder structure |
| `Frontend/src/components/battles/CLAUDE.md` | Battle UI components (planned, not yet built) |
| `Frontend/src/components/coin/CLAUDE.md` | Coin detail — TradingView chart, order book, stats |
| `Frontend/src/components/docs/CLAUDE.md` | Documentation components — docs viewer, search |
| `Frontend/src/components/dashboard/CLAUDE.md` | Dashboard — portfolio, equity chart, positions, orders |
| `Frontend/src/components/landing/CLAUDE.md` | Landing page sections — hero, features, CTA |
| `Frontend/src/components/layout/CLAUDE.md` | App shell — sidebar, header, agent switcher, WS provider |
| `Frontend/src/components/leaderboard/CLAUDE.md` | Agent rankings — table, filters, profile modal |
| `Frontend/src/components/market/CLAUDE.md` | Market table (600+ pairs), virtual scrolling, search |
| `Frontend/src/components/settings/CLAUDE.md` | Settings — account, API keys, risk config, theme |
| `Frontend/src/components/setup/CLAUDE.md` | Onboarding wizard — multi-step registration flow |
| `Frontend/src/components/shared/CLAUDE.md` | Reusable domain building blocks (16 components) |
| `Frontend/src/components/strategies/CLAUDE.md` | Strategy management UI — list, detail, version history, deploy controls |
| `Frontend/src/components/trades/CLAUDE.md` | Trade history — table, filters, export, detail modal |
| `Frontend/src/components/training/CLAUDE.md` | Training run observation UI — run list, episode tracking, learning curves |
| `Frontend/src/components/ui/CLAUDE.md` | 59 shadcn/ui primitives + custom visual effects |
| `Frontend/src/components/wallet/CLAUDE.md` | Wallet — balance card, asset list, distribution chart |
| `Frontend/src/hooks/CLAUDE.md` | Hook inventory (23 hooks), TanStack Query patterns |
| `Frontend/src/lib/CLAUDE.md` | API client, utilities, constants, chart config |
| `Frontend/src/remotion/CLAUDE.md` | Remotion video compositions for landing animations |
| `Frontend/src/stores/CLAUDE.md` | Zustand stores (6), persistence, agent state |
| `Frontend/src/styles/CLAUDE.md` | Chart theme, style utilities |

### Infrastructure & Other

| Path | Description |
|------|-------------|
| `alembic/CLAUDE.md` | Migration workflow, async env, naming convention, inventory |
| `sdk/CLAUDE.md` | Python SDK — sync/async clients, WebSocket client |
| `agent/CLAUDE.md` | TradeReady Platform Testing Agent — Pydantic AI + OpenRouter, 4 workflows, 4 tool integrations; sub-files in `agent/models/`, `agent/tools/`, `agent/prompts/`, `agent/workflows/`, `agent/tests/`, `agent/strategies/`, `agent/conversation/`, `agent/memory/`, `agent/permissions/`, `agent/trading/` |
| `agent/conversation/CLAUDE.md` | Session management, message history, LLM context assembly, intent routing — `AgentSession`, `ConversationHistory`, `ContextBuilder`, `IntentRouter` |
| `agent/memory/CLAUDE.md` | Memory store (abstract + Postgres + Redis), scored retrieval — `MemoryStore`, `PostgresMemoryStore`, `RedisMemoryCache`, `MemoryRetriever` |
| `agent/permissions/CLAUDE.md` | Roles, capabilities, budget limits, enforcement — `AgentRole`, `CapabilityManager`, `BudgetManager`, `PermissionEnforcer` |
| `agent/trading/CLAUDE.md` | Trading loop, signal generator, executor, position monitor, journal, strategy manager, A/B testing — `TradingLoop`, `TradeExecutor`, `TradingJournal`, `ABTestRunner` |
| `agent/strategies/CLAUDE.md` | 5-strategy agent trading system — PPO RL, genetic algorithm, market regime detection, risk overlay, ensemble combiner; file inventory, CLI commands, dependencies |
| `agent/strategies/rl/CLAUDE.md` | PPO RL strategy — `RLConfig`, `train()`, `ModelEvaluator`, `PPODeployBridge`; CLI commands, SB3 gotchas |
| `agent/strategies/evolutionary/CLAUDE.md` | Genetic algorithm strategy — `StrategyGenome` (12 params), `Population`, `BattleRunner`; GA operators, fitness formula, CLI |
| `agent/strategies/regime/CLAUDE.md` | Market regime detection — `RegimeClassifier` (XGBoost/RF), `RegimeSwitcher` (cooldown+confidence), 4 pre-built strategy dicts |
| `agent/strategies/risk/CLAUDE.md` | Risk management overlay — `RiskAgent`, `VetoPipeline` (6 gates), `DynamicSizer`, `RiskMiddleware` async entry point |
| `agent/strategies/ensemble/CLAUDE.md` | Ensemble combiner — `MetaLearner` (weighted voting), `EnsembleRunner` (6-stage pipeline), weight optimiser CLI |
| `scripts/CLAUDE.md` | Available scripts, when to run each, dependencies |
| `docs/CLAUDE.md` | Documentation inventory, audience for each doc |
| `development/CLAUDE.md` | Development planning docs, progress tracking, archived phase plans |
| `development/code-reviews/CLAUDE.md` | Code review reports from code-reviewer agent |
| `tradeready-gym/CLAUDE.md` | Gymnasium RL environments (7 envs, 4 rewards, 3 wrappers) for agent training |

---

## Sub-Agents (`.claude/agents/`)

<!-- last-updated: 2026-03-20 -->

16 specialized agents that can be delegated to for specific tasks. Organized by role category.

### Agent Inventory

#### Quality Gate Agents (run after every change)

| Agent | Purpose | Tools | Model | Mode | When to Use |
|-------|---------|-------|-------|------|-------------|
| `code-reviewer` | Reviews code against project standards documented in CLAUDE.md files. Saves reports to `development/code-reviews/` | Read, Write, Grep, Glob, Bash | sonnet | report + write | **After every code change** (step 1 of post-change pipeline) |
| `test-runner` | Maps changed files → relevant tests, runs them, writes missing tests per `tests/CLAUDE.md` standards | Read, Write, Edit, Grep, Glob, Bash | sonnet | run + write | **After every code change** (step 2, after code-reviewer) |
| `context-manager` | Maintains `development/context.md` and syncs/creates CLAUDE.md navigation files across all directories | Read, Write, Edit, Grep, Glob, Bash | sonnet | write | **After every task completes** (mandatory final step) |

#### Security Agents (run for auth, input handling, sensitive changes)

| Agent | Purpose | Tools | Model | Mode | When to Use |
|-------|---------|-------|-------|------|-------------|
| `security-auditor` | Read-only audit for auth bypasses, injection risks, secret exposure, agent isolation violations, missing rate limits, XSS | Read, Grep, Glob, Bash | sonnet | read-only | After any security-sensitive change (auth, middleware, agent scoping) |
| `security-reviewer` | Vulnerability detection AND remediation. Can fix CRITICAL issues directly. OWASP Top 10, secrets, SSRF, injection, unsafe crypto | Read, Write, Edit, Bash, Grep, Glob | sonnet | read + fix | **PROACTIVELY** after writing code that handles user input, auth, API endpoints, or sensitive data |

> **Key difference:** `security-auditor` is read-only and reports findings. `security-reviewer` can also fix CRITICAL vulnerabilities directly. Use auditor for routine checks, reviewer when you suspect real issues.

#### Infrastructure Agents (run before deploys, migrations, API changes)

| Agent | Purpose | Tools | Model | Mode | When to Use |
|-------|---------|-------|-------|------|-------------|
| `migration-helper` | Generates and validates Alembic migrations. Checks destructive ops, two-phase NOT NULL, hypertable PK rules, rollback paths | Read, Write, Edit, Grep, Glob, Bash | sonnet | write | **Before** creating or running any migration |
| `api-sync-checker` | Compares Pydantic schemas vs TypeScript types, verifies `api-client.ts` routes match backend endpoints, checks WebSocket message shapes | Read, Grep, Glob, Bash | sonnet | read-only | After changing API routes, schemas, or frontend API code |
| `deploy-checker` | Full A-Z deployment readiness: lint, types, tests, migrations, Docker builds, env vars, security, API health, frontend build, GitHub Actions CI/CD | Read, Write, Edit, Grep, Glob, Bash | sonnet | report + write | Before deploying to production or merging to `main` |
| `doc-updater` | Syncs `docs/skill.md`, `docs/api_reference.md`, module CLAUDE.md files, and SDK docs with actual code | Read, Write, Edit, Grep, Glob, Bash | sonnet | write | After API, schema, or module changes |
| `perf-checker` | Detects N+1 queries, blocking async calls, missing indexes, unbounded growth, React render issues, bundle bloat | Read, Grep, Glob, Bash | sonnet | read-only | After changes to DB queries, async code, caching, hot paths, or frontend components |

#### Development Agents (run when building features)

| Agent | Purpose | Tools | Model | Mode | When to Use |
|-------|---------|-------|-------|------|-------------|
| `backend-developer` | Writes production-quality async Python 3.12+ modules, services, tools, integrations following project conventions | Read, Write, Edit, Grep, Glob, Bash | sonnet | write | When creating new Python packages, implementing business logic, or building integrations |
| `frontend-developer` | Implements Next.js 16 / React 19 / Tailwind v4 components, hooks, pages, and features per `Frontend/CLAUDE.md` | Read, Write, Edit, Grep, Glob, Bash | sonnet | write | When implementing frontend features, components, pages, or UI changes |
| `ml-engineer` | RL training pipelines, genetic algorithms, regime classifiers, ensemble systems. Integrates with `tradeready-gym/` environments | Read, Write, Edit, Grep, Glob, Bash | sonnet | write | When implementing Gymnasium RL agents, evolutionary optimization, or ML classifiers |
| `e2e-tester` | Runs live E2E scenarios against the running platform — creates accounts, agents, trades, backtests, battles. Returns credentials for UI verification | Read, Write, Edit, Grep, Glob, Bash | sonnet | write | When you need to populate realistic data, validate the full stack, or demo the platform |

#### Research & Planning Agents (run before implementing)

| Agent | Purpose | Tools | Model | Mode | When to Use |
|-------|---------|-------|-------|------|-------------|
| `planner` | Creates detailed, phased implementation plans with file paths, risks, dependencies, and testing strategies | Read, Grep, Glob | **opus** | read-only | **PROACTIVELY** when users request feature implementation, architectural changes, or complex refactoring |
| `codebase-researcher` | Investigates the codebase to answer questions, find patterns, trace data flows, locate implementations | Read, Grep, Glob, Bash | sonnet | read-only | When you need to understand how something works before making changes |

### Agent Pipelines (Execution Order)

Agents are not independent — they form pipelines that must be followed in order:

#### Standard Post-Change Pipeline (every code change)
```
code-reviewer → test-runner → context-manager
     │               │              │
  report          run tests     update context.md
  violations      fix gaps      sync CLAUDE.md files
```

#### API/Schema Change Pipeline
```
[make changes] → api-sync-checker → doc-updater → code-reviewer → test-runner → context-manager
```

#### Security-Sensitive Change Pipeline
```
[make changes] → security-reviewer (fix CRITICALs) → security-auditor (verify) → code-reviewer → test-runner → context-manager
```

#### Performance-Sensitive Change Pipeline
```
[make changes] → perf-checker → code-reviewer → test-runner → context-manager
```

#### Database Migration Pipeline
```
migration-helper (validate/generate) → [apply migration] → deploy-checker → context-manager
```

#### Feature Implementation Pipeline
```
planner → codebase-researcher → backend-developer / frontend-developer / ml-engineer → code-reviewer → test-runner → context-manager
```

### Mandatory Agent Rules

1. **After ANY code change**, run the standard pipeline: `code-reviewer` → `test-runner` → `context-manager`. Never skip.
2. **Before ANY migration**, delegate to `migration-helper` to validate or generate the migration safely.
3. **After API/schema changes**, delegate to `api-sync-checker` then `doc-updater` before the standard pipeline.
4. **For security-sensitive changes** (auth, middleware, agent scoping, input handling), run the security pipeline.
5. **For performance-sensitive changes** (DB queries, async code, caching, ingestion), run `perf-checker` before the standard pipeline.
6. If `test-runner` identifies missing coverage, it writes new tests following `tests/CLAUDE.md` standards.
7. If tests fail, fix the code (or tests if behavior intentionally changed), then re-run via `test-runner` until all pass.
8. **`context-manager` is ALWAYS the final step** of every task. It updates `development/context.md` and syncs all CLAUDE.md files. Not optional.

### Agent Configuration Reference

All agents use YAML frontmatter with these fields:

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Lowercase with hyphens (e.g., `code-reviewer`) |
| `description` | yes | When to delegate — include "Use proactively" for auto-trigger |
| `tools` | yes | Allowlist: `Read`, `Write`, `Edit`, `Grep`, `Glob`, `Bash` |
| `model` | no | `sonnet` (default), `opus` (for planning), `haiku` (for fast tasks) |

Advanced fields available but not yet used:
- `memory` — `project` / `user` / `local` — enables cross-session learning
- `effort` — `low` / `medium` / `high` / `max` — controls reasoning depth
- `isolation` — `worktree` — runs in isolated git worktree copy
- `maxTurns` — limits agentic turns before stopping
- `hooks` — `PreToolUse` / `PostToolUse` / `Stop` lifecycle hooks for conditional validation

### Keeping Agents Up to Date

Agents are only as effective as their instructions. When the project evolves:
- **New modules/patterns**: Update relevant agent `.md` files with new context loading paths
- **Renamed files**: Update file paths referenced in agent workflows
- **New conventions**: Add rules to agents that enforce them
- **Test count changes**: Update `test-runner` and module CLAUDE.md test inventories
- **Track changes**: When you modify an agent, note what changed and why in `development/context.md`

### Agent Improvement Checklist

When reviewing or improving an agent, verify:
- [ ] Description clearly states when to delegate (includes trigger phrases)
- [ ] Tools are minimal — only what the agent actually needs (read-only agents should NOT have Write/Edit)
- [ ] Context loading section lists specific CLAUDE.md files to read first
- [ ] Workflow has numbered steps with concrete actions
- [ ] Output format is specified (report structure, file paths, severity ratings)
- [ ] Rules section has hard constraints and non-negotiable practices
- [ ] Model choice matches complexity (opus for planning, sonnet for most tasks)
- [ ] Advanced features applied where beneficial (memory, effort, isolation)

---

## Skills (`.claude/skills/`)

Reusable slash-command workflows invoked with `/skill-name`:

| Skill | Command | Description |
|-------|---------|-------------|
| `commit` | `/commit` | Smart commit: stages, generates conventional message (`type(scope): desc`), runs ruff check, commits |
| `review-changes` | `/review-changes` | Full post-change pipeline: detects pipeline type, runs agents in order (code-reviewer → test-runner → context-manager + extras) |
| `run-checks` | `/run-checks` | Quick quality gate: ruff + mypy + pytest on changed files only. Fast feedback, no agent delegation |
| `sync-context` | `/sync-context` | Scan all CLAUDE.md files, fix stale inventories, create missing ones, update development/context.md |
| `plan-to-tasks` | `/plan-to-tasks <file>` | Read a plan file, discover agents, match tasks to agents, create task files in `development/tasks/` |

## Configuration (`.claude/settings.json`)

Shared team configuration (committed to git). Defines:
- **Permissions**: Pattern-based allow/deny rules for all tools (Bash, Read, Edit, etc.)
- **Env vars**: `PYTHONPATH=.`, `PYTHONDONTWRITEBYTECODE=1`
- **Hooks**: PostToolUse reminder after Write/Edit to run the quality pipeline
- **Denied**: Destructive operations (`rm -rf /`, `git push --force`, `DROP TABLE`)

Personal overrides go in `.claude/settings.local.json` (gitignored).

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

# Start the platform testing agent (opt-in profile; reads agent/.env)
docker compose --profile agent up agent

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

# Platform Testing Agent (autonomous E2E tester — requires agent/.env)
python -m agent.main smoke               # 10-step connectivity validation (no LLM)
python -m agent.main trade               # Full trading lifecycle with LLM
python -m agent.main backtest            # 7-day MA-crossover backtest with LLM analysis
python -m agent.main strategy            # Strategy create → test → improve → compare cycle
python -m agent.main all                 # Run all four workflows; writes platform-validation-*.json
python -m agent.main trade --model openrouter:anthropic/claude-opus-4-5  # Override model
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
| 1 | **Exchange Abstraction** — CCXT adapter for 110+ exchanges, symbol mapper | `src/exchange/` |
| 2 | **Price Ingestion** — Exchange WS (CCXT or legacy Binance) → Redis + TimescaleDB | `src/price_ingestion/` |
| 3 | **Redis Cache** — sub-ms price lookups, rate limiting, pub/sub | `src/cache/` |
| 4 | **TimescaleDB** — tick history, OHLCV candles, trades | `src/database/` |
| 5 | **Order Engine** — Market/Limit/Stop-Loss/Take-Profit | `src/order_engine/` |
| 6 | **Account Management** — registration, auth, API keys, balances | `src/accounts/` |
| 7 | **Portfolio Tracker** — real-time PnL, Sharpe, drawdown | `src/portfolio/` |
| 8 | **Risk Management** — position limits, daily loss circuit breaker | `src/risk/` |
| 9 | **API Gateway** — REST + WebSocket, middleware | `src/api/` |
| 10 | **Monitoring** — Prometheus metrics, health checks, structured logs | `src/monitoring/` |
| 11 | **Backtesting Engine** — historical replay, sandbox trading, metrics | `src/backtesting/` |
| 12 | **Agent Management** — multi-agent CRUD, per-agent wallets, API keys | `src/agents/` |
| 13 | **Battle System** — agent vs agent competitions with rankings, replays | `src/battles/` |
| 14 | **Unified Metrics** — shared calculator for backtests & battles | `src/metrics/` |

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

**Price ingestion:** Exchange WebSocket (via CCXT adapter or legacy Binance client) → update Redis `HSET prices {SYMBOL} {price}` → buffer ticks in memory → periodic flush to TimescaleDB via asyncpg COPY → broadcast on Redis pub/sub for WebSocket clients. The exchange is configurable via `EXCHANGE_ID` env var (default: `binance`). All CCXT calls go through the `ExchangeAdapter` interface in `src/exchange/`.

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
Available aliases: `DbSessionDep`, `RedisDep`, `PriceCacheDep`, `SettingsDep`, `AccountRepoDep`, `BalanceRepoDep`, `OrderRepoDep`, `TradeRepoDep`, `TickRepoDep`, `SnapshotRepoDep`, `BalanceManagerDep`, `AccountServiceDep`, `SlippageCalcDep`, `OrderEngineDep`, `RiskManagerDep`, `CircuitBreakerRedisDep`, `PortfolioTrackerDep`, `PerformanceMetricsDep`, `SnapshotServiceDep`, `BacktestEngineDep`, `BacktestRepoDep`, `BattleRepoDep`, `BattleServiceDep`, `AgentRepoDep`, `AgentServiceDep`, `StrategyRepoDep`, `StrategyServiceDep`, `TestRunRepoDep`, `TestOrchestratorDep`, `TrainingRunRepoDep`, `TrainingRunServiceDep`.

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

**MCP Server** (`src/mcp/`): 58 trading tools over stdio transport. See `src/mcp/CLAUDE.md`.

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
| `BINANCE_WS_URL` | Binance WebSocket base URL (legacy fallback) |
| `EXCHANGE_ID` | Primary exchange for CCXT (default `binance`; e.g. `okx`, `bybit`) |
| `EXCHANGE_API_KEY` | Exchange API key for live trading (Phase 8, optional) |
| `EXCHANGE_SECRET` | Exchange API secret for live trading (Phase 8, optional) |
| `ADDITIONAL_EXCHANGES` | Comma-separated extra exchange IDs for multi-exchange ingestion |
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
| `OPENROUTER_API_KEY` | Testing agent: OpenRouter API key (required; stored in `agent/.env`) |
| `AGENT_MODEL` | Testing agent: primary LLM model ID (default `openrouter:anthropic/claude-sonnet-4-5`) |
| `AGENT_CHEAP_MODEL` | Testing agent: cheap model for low-stakes tasks (default `openrouter:google/gemini-2.0-flash-001`) |
