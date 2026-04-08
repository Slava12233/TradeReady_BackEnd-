# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **First step rule:** At the start of every conversation, read `development/context.md` before doing anything else. It contains a rolling summary of all development activity, decisions, and current state.

> **Self-maintenance rule:** When modifying code in any folder, update that folder's `CLAUDE.md` if behavior, files, or patterns changed. Update the `<!-- last-updated -->` timestamp when you do.

## Rules Organization

Domain-specific instructions are in `.claude/rules/` (loaded on-demand when matching files are opened):

- **agents-and-pipelines.md** — 16 sub-agents, execution pipelines, mandatory agent rules
- **architecture.md** — Core components, data flows, multi-agent architecture, middleware order
- **dependency-injection.md** — FastAPI Depends aliases, settings, exception hierarchy
- **backend-code-standards.md** — Python style, security, naming, API design conventions
- **frontend.md** — Next.js/React/Tailwind commands, SDK references
- **obsidian-vault.md** — development/ vault structure, frontmatter, wikilinks, file ownership
- **environment.md** — Docker setup, all environment variables

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
| `src/webhooks/CLAUDE.md` | Outbound webhook dispatcher — SSRF protection, HMAC signing, 4 event types, 6 endpoints |

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
| `Frontend/src/components/battles/CLAUDE.md` | Battle UI — 7 components, 2 routes, 2 hooks, 14 API functions, 15 types |
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
| `agent/CLAUDE.md` | TradeReady Platform Testing Agent — Pydantic AI + OpenRouter, 4 workflows |
| `agent/conversation/CLAUDE.md` | Session management, message history, context assembly |
| `agent/memory/CLAUDE.md` | Memory store (Postgres + Redis), scored retrieval |
| `agent/permissions/CLAUDE.md` | Roles, capabilities, budget limits, enforcement |
| `agent/trading/CLAUDE.md` | Trading loop, executor, journal, strategy manager, A/B testing |
| `agent/strategies/CLAUDE.md` | 5-strategy system — PPO RL, genetic, regime, risk, ensemble |
| `agent/strategies/rl/CLAUDE.md` | PPO RL strategy |
| `agent/strategies/evolutionary/CLAUDE.md` | Genetic algorithm strategy |
| `agent/strategies/regime/CLAUDE.md` | Market regime detection |
| `agent/strategies/risk/CLAUDE.md` | Risk management overlay |
| `agent/strategies/ensemble/CLAUDE.md` | Ensemble combiner |
| `scripts/CLAUDE.md` | Available scripts |
| `docs/CLAUDE.md` | Documentation inventory |
| `development/CLAUDE.md` | Development planning, Obsidian vault |
| `development/code-reviews/CLAUDE.md` | Code review reports |
| `tradeready-gym/CLAUDE.md` | Gymnasium RL environments (7 envs, 6 rewards, 3 wrappers) |
| `monitoring/CLAUDE.md` | 6 Grafana dashboards + 11 Prometheus alert rules |
| `.claude/agents/CLAUDE.md` | 16 sub-agent definitions |
| `.claude/skills/CLAUDE.md` | 7 slash-command skill workflows |
| `.claude/agent-memory/CLAUDE.md` | Agent memory storage |

---

## Skills (`.claude/skills/`)

| Skill | Command | Description |
|-------|---------|-------------|
| `commit` | `/commit` | Smart commit: stages, generates conventional message, runs ruff, commits |
| `review-changes` | `/review-changes` | Full post-change pipeline with agent delegation |
| `run-checks` | `/run-checks` | Quick quality gate: ruff + mypy + pytest on changed files |
| `sync-context` | `/sync-context` | Scan/fix all CLAUDE.md files, update context.md |
| `plan-to-tasks` | `/plan-to-tasks <file>` | Read plan, match tasks to agents, create task files |
| `analyze-agents` | `/analyze-agents` | Analyze agent activity logs, generate improvement report |
| `c-level-report` | `/c-level-report` | C-level executive report with KPIs, risk, roadmap |

## Configuration (`.claude/settings.json`)

- **Permissions**: Pattern-based allow/deny rules for all tools
- **Env vars**: `PYTHONPATH=.`, `PYTHONDONTWRITEBYTECODE=1`
- **Hooks**: PostToolUse reminder after Write/Edit to run quality pipeline
- **Denied**: Destructive operations (`rm -rf /`, `git push --force`, `DROP TABLE`)

Personal overrides: `.claude/settings.local.json` (gitignored).

---

## Production-First Development Protocol

This platform is **deployed in production with CI/CD pipelines**. Every change must be production-ready.

### Before ANY Change
1. Understand the existing code — read the files you're modifying
2. Check existing tests for the area you're changing
3. Run `ruff check` and `mypy` on affected files before committing

### After ANY Change
1. **Tests pass**: Run `pytest` for affected areas — fix broken tests or update if behavior changed
2. **Lint clean**: `ruff check src/ tests/` must pass with zero errors
3. **Type safe**: `mypy src/` must pass
4. **No regressions**: Verify API response shapes haven't broken consumers
5. **Migration safe**: DB changes need Alembic migrations that work on live database

### Test Quality Standards
- Tests must cover actual behavior, not just exist for coverage numbers
- Integration tests must use: `from src.main import create_app; app = create_app()`
- New features need tests before merging. Bug fixes need regression tests.
- **Gotcha:** `get_settings()` uses `lru_cache` — tests must patch before cached instance

## Running the Platform

```bash
# All services (Docker)
docker compose up -d

# API server (local dev)
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Price ingestion
python -m src.price_ingestion.service

# Celery worker + beat
celery -A src.tasks.celery_app worker --loglevel=info
celery -A src.tasks.celery_app beat --loglevel=info

# Platform Testing Agent
python -m agent.main smoke|trade|backtest|strategy|all
```

Access: API `http://localhost:8000`, Docs `http://localhost:8000/docs`, Grafana `http://localhost:3000`, WS `ws://localhost:8000/ws/v1?api_key=...`

## Testing & Linting

```bash
pytest --cov=src --cov-report=html      # All tests with coverage
pytest tests/unit/                       # Unit tests only
pytest tests/integration/                # Integration tests (needs Docker)
ruff check src/ tests/                   # Lint
ruff check --fix src/                    # Auto-fix
mypy src/                                # Type check
alembic revision --autogenerate -m "desc"  # Create migration
alembic upgrade head                       # Apply migrations
```

## Git Commit Format

```
type(scope): description
```
Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`
Scope: component name (e.g., `ingestion`, `order-engine`, `api`)
