# Development Context Log

<!-- This file is maintained by the context-manager agent. It summarizes all development activity so future conversations have full context. -->

## Current State

**Active work:** Agentic layer buildout complete — all 36 CLAUDE.md files + 8 sub-agents deployed
**Last session:** 2026-03-17 — Completed full agentic knowledge layer and sub-agent fleet
**Next steps:** Battle frontend UI (components/battles/ is empty), or begin next feature work
**Blocked:** Nothing currently blocked

---

## Project Overview

A **production-deployed** simulated crypto exchange where AI agents trade **virtual USDT** against **real Binance market data**. Supports 600+ USDT pairs with real-time price feeds, order execution, risk controls, portfolio tracking, backtesting, and agent-vs-agent battles.

### What's Built (as of 2026-03-17)

| System | Status | Key Details |
|--------|--------|-------------|
| **Price Ingestion** | Production | Binance WS → Redis + TimescaleDB, 600+ pairs, tick buffering |
| **Order Engine** | Production | Market/Limit/Stop-Loss/Take-Profit, slippage simulation |
| **Account System** | Production | Registration, JWT + API key auth, bcrypt passwords |
| **Multi-Agent** | Production | Per-agent wallets, API keys, risk profiles, trading isolation |
| **Portfolio Tracker** | Production | Real-time PnL, Sharpe, drawdown, equity snapshots |
| **Risk Management** | Production | 8-step validation, circuit breaker, position limits |
| **API Gateway** | Production | 86+ REST endpoints, WebSocket (5 channels), middleware stack |
| **Backtesting** | Production | Historical replay, in-memory sandbox, look-ahead prevention |
| **Battle System (Backend)** | Production | Live + historical modes, 20 endpoints, ranking, replay |
| **Battle System (Frontend)** | Not started | `Frontend/src/components/battles/` is empty |
| **Unified Metrics** | Production | Shared calculator for backtests & battles |
| **MCP Server** | Production | 12 tools over stdio transport |
| **Python SDK** | Production | Sync + async + WebSocket clients |
| **Frontend** | Production | Next.js 16, React 19, Tailwind v4, agent switcher, backtest UI |
| **Monitoring** | Production | Prometheus metrics, health checks, structured logging |
| **Agentic Layer** | Complete | 36 CLAUDE.md files, 8 sub-agents |

### Tech Stack

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2.0 + asyncpg, Pydantic v2
- **Database:** TimescaleDB (PostgreSQL), Redis 7+
- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS 4.2, pnpm
- **Tasks:** Celery + Redis broker (11 beat tasks)
- **Auth:** JWT (PyJWT) + API keys (bcrypt), dual auth flow
- **Testing:** pytest (62 unit files / 974 tests, 20 integration files / 433 tests)
- **Linting:** ruff + mypy (strict)
- **Containers:** Docker + Docker Compose
- **Monitoring:** Prometheus + Grafana + structlog

### Architecture (13 Components)

```
 1. Price Ingestion    — Binance WS → Redis + TimescaleDB (src/price_ingestion/)
 2. Redis Cache        — Sub-ms price lookups, rate limiting, pub/sub (src/cache/)
 3. TimescaleDB        — Tick history, OHLCV candles, trades (src/database/)
 4. Order Engine       — Market/Limit/Stop-Loss/Take-Profit (src/order_engine/)
 5. Account Mgmt       — Registration, auth, API keys, balances (src/accounts/)
 6. Portfolio Tracker   — Real-time PnL, Sharpe, drawdown (src/portfolio/)
 7. Risk Management    — Position limits, circuit breaker (src/risk/)
 8. API Gateway        — REST + WebSocket, middleware (src/api/)
 9. Monitoring         — Prometheus, health checks (src/monitoring/)
10. Backtesting        — Historical replay, sandbox trading (src/backtesting/)
11. Agent Management   — Multi-agent CRUD, per-agent wallets (src/agents/)
12. Battle System      — Agent vs agent competitions (src/battles/)
13. Unified Metrics    — Shared calculator for backtests & battles (src/metrics/)
```

### Multi-Agent Model

Each account owns multiple **agents**, each with its own API key, starting balance, risk profile, and trading history. All trading tables keyed by `agent_id`. Auth flow: API key tries agents table first, falls back to accounts. JWT uses `X-Agent-Id` header.

### Database (15 migrations, current head: 015)

Key tables: `accounts`, `agents`, `balances`, `orders`, `trades`, `positions`, `ticks` (hypertable), `portfolio_snapshots` (hypertable), `trading_pairs`, `backtest_sessions`, `backtest_trades`, `backtest_snapshots` (hypertable), `battles`, `battle_participants`, `battle_snapshots` (hypertable), `candles_backfill`, `waitlist`

Note: Migration 011 missing from directory — chain skips 010 → 012.

### Sub-Agent Fleet (8 agents in `.claude/agents/`)

| Agent | Purpose |
|-------|---------|
| `code-reviewer` | Reviews code against project standards after every change |
| `test-runner` | Runs tests + writes missing tests after every change |
| `context-manager` | Maintains this file — tracks changes, decisions, learnings |
| `migration-helper` | Validates/generates safe Alembic migrations |
| `api-sync-checker` | Verifies frontend/backend API sync |
| `doc-updater` | Updates docs when code changes |
| `security-auditor` | Audits for security vulnerabilities |
| `perf-checker` | Detects performance regressions |

### Key Design Decisions (permanent)

1. **TimescaleDB over plain PostgreSQL** — native time-series compression, continuous aggregates, retention policies
2. **Redis for current prices** — sub-ms reads, 600+ pairs fit in ~50-100 MB, also handles rate limiting + circuit breaker
3. **Celery for background tasks** — limit order matching (1s), snapshots (1m/1h/1d), circuit breaker reset, cleanup
4. **Slippage simulation** — proportional to order size vs daily volume, realistic without a full order book
5. **Five connectivity layers** — REST API, WebSocket, MCP Server, Python SDK, skill.md
6. **Decimal everywhere** — never float for money; NUMERIC(20,8) in DB
7. **Repository pattern** — all DB access through repo classes, never raw queries in routes/services
8. **Strict dependency direction** — Routes → Services → Repositories → Models (never upward)
9. **Agent-scoped everything** — all trading operations scoped by agent_id, no cross-agent data leakage
10. **In-memory backtesting** — sandbox has zero live deps (no Redis, no Binance), look-ahead bias prevented at data layer
11. **Unified metrics pipeline** — same calculator for backtests and battles, adapter pattern for different input sources
12. **Self-maintaining knowledge layer** — CLAUDE.md files in every folder, mandatory update rule when code changes

---

## Recent Activity

### 2026-03-17 — Agentic Layer Complete Build

**Changes:**
- Root `CLAUDE.md` — Refactored: added index (35 sub-files), self-maintenance rule, sub-agents section, trimmed ~300 lines of redundancy
- 21 `src/*/CLAUDE.md` files — Created for every backend module
- 3 `tests/*/CLAUDE.md` files — Tests root, unit (62 files/974 tests), integration (20 files/433 tests)
- 1 `alembic/CLAUDE.md` — 14-migration inventory
- 7 `Frontend/*/CLAUDE.md` files — Components, hooks, stores, app, lib, backtest, battles
- 3 other CLAUDE.md files — SDK, scripts, docs
- 8 `.claude/agents/*.md` files — Full sub-agent fleet
- `development/agentic-layer-plan-tasks.md` — All Phase 1-6 marked DONE

**Decisions:**
- CLAUDE.md template standardized: purpose → key files → architecture → public API → dependencies → tasks → gotchas → recent changes
- Root CLAUDE.md is cross-cutting only; module details in sub-files (no duplication)
- Mandatory agent flow: code-reviewer → test-runner after every change; context-manager proactively

**Learnings:**
- `Frontend/src/components/battles/` completely empty — backend done, frontend not started
- `battle-store.ts` doesn't exist despite being referenced — battles use TanStack Query only
- Migration 011 missing from versions directory
- Test coverage: 974 unit + 433 integration = 1,407 total tests

---

*Older entries will appear below as development continues. Entries older than 30 days are summarized; older than 90 days are pruned (decisions and learnings are permanent).*
