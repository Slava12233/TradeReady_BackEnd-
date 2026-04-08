---
type: context-log
title: Development Context Log
maintained_by: context-manager
aliases:
  - context
  - dev log
  - development log
tags:
  - context
  - active
---

# Development Context Log

<!-- This file is maintained by the context-manager agent. It summarizes all development activity so future conversations have full context. -->

## Current State

**Active work:** Production stable. Battle live crash fixed. Backtest stop_price gap fixed (BT-02, BT-17). Migration 022 applied. CLAUDE.md files synced.
**Last session:** 2026-04-07 — (1) Battle live crash fix: resolved "Cannot read properties of undefined (reading 'toFixed')" on `GET /battles/{id}/live` — data shape mismatch (6 vs 13 fields). Typed `BattleLiveParticipantSchema`, `!= null` guard fix, 3 frontend components updated. (2) Backtest fixes: BT-02/BT-17 stop_price now persisted through sandbox→engine→DB (migration 022); orphan detection race condition fixed. (3) Context manager sync: context.md pruned 931→409 lines; 5 CLAUDE.md files updated (alembic, backtesting, database, api/routes, battles/schema).
**Previous session:** 2026-04-06 — CLAUDE.md sync: fixed 10 missing agent ecosystem repo files in `src/database/repositories/CLAUDE.md`; updated timestamps and recent-changes entries for `src/agents`, `src/database`, and `src/database/repositories`.
**Next steps:** (1) Monitor production stability. (2) Resume strategy search system: Build Module A (Feature Pipeline), Module B (Signal Interface), Module C (Deflated Sharpe). Implementation plan in `development/implementation-plan-a-to-z.md`.
**Blocked:** Nothing.

---

## Project Overview

A **production-deployed** simulated crypto exchange where AI agents trade **virtual USDT** against **real Binance market data**. Supports 600+ USDT pairs with real-time price feeds, order execution, risk controls, portfolio tracking, backtesting, and agent-vs-agent battles.

### What's Built (as of 2026-03-22)

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
| **Battle System (Frontend)** | Complete | 7 components (BattleList, BattleDetail, BattleCreateDialog, BattleLeaderboard, BattleReplay, EquityCurveChart, AgentPerformanceCard), 2 routes (`/battles`, `/battles/[id]`), 2 hooks (`useBattles`, `useBattleDetail`), 14 API functions, 15 TypeScript types |
| **Strategy & Training UI (STR-UI-1)** | Complete | 4 pages, 4 hooks, 21 components, 20 API functions, 20 types. 0 TS errors. |
| **Strategy & Training UI (STR-UI-2)** | Complete | Dashboard status cards, backtest filter toggle, sidebar active badges, empty states, mobile responsive layout, error boundaries. |
| **Unified Metrics** | Production | Shared calculator for backtests & battles |
| **MCP Server** | Production | 58 tools over stdio transport (43 base + 15 strategy/training from Phase STR-4) |
| **Python SDK** | Production | Sync + async + WebSocket clients |
| **Frontend** | Production | Next.js 16, React 19, Tailwind v4, agent switcher, backtest UI. Performance-optimized: memo'd rows, lazy sections, RAF batch buffer, GET dedup, prefetch, 207 unit tests. |
| **Monitoring** | Production | Prometheus metrics, health checks, structured logging |
| **Exchange Abstraction (CCXT)** | Production | Adapter pattern, 110+ exchanges, symbol mapper, multi-exchange backfill |
| **Agentic Layer** | Complete | 36 CLAUDE.md files, 16 sub-agents (categorized: 3 quality gates, 2 security, 5 infrastructure, 4 development, 2 research/planning) |
| **Platform Testing Agent** | Complete | `agent/` package — Pydantic AI + OpenRouter, 4 workflows, 3 integration layers, 117 unit tests |
| **Agent Strategy System** | Complete | `agent/strategies/` — 5 strategies (RL/evolutionary/regime/risk/ensemble), 578+ tests. Phase 1/2 upgrades: volume_ratio regime feature, composite RL reward, OOS evolutionary fitness, Kelly/Hybrid sizing, drawdown profiles, correlation-aware risk, strategy circuit breakers, 6 advanced order tools. RecoveryManager (3-state RECOVERING→SCALING_UP→FULL, Redis-backed, ATR normalization). Security review: 0 CRITICAL, 0 HIGH (all 7 HIGH issues resolved 2026-03-23). PairSelector, WSManager, memory-driven learning loop, DriftDetector (Page-Hinkley test), RetrainOrchestrator (4 schedules), Walk-Forward Validation (WFE metric, overfit warning at WFE < 50%), Attribution-driven weights, StrategyCircuitBreaker. All 37/37 Trading Agent Master Plan tasks complete. ~1200+ new tests added 2026-03-22. |
| **Continuous Retraining** | Complete | `agent/strategies/retrain.py` + `agent/tasks.py` — RetrainOrchestrator wired into Celery beat (4 schedules: ensemble weights 8h, regime 7d, genome 7d, PPO 30d). DriftDetector in live TradingLoop. Prometheus metrics for retrain events. Grafana dashboard panel. 29 integration tests. Regime classifier trained: 99.92% accuracy, WFE 97.46%, Sharpe 1.14 vs MACD 0.74. |
| **Agent Dashboard** | Complete | 4 new analytics components (strategy-attribution-chart, equity-comparison-chart, signal-confidence-histogram, active-trade-monitor), 2 new hooks (use-agent-decisions, use-agent-equity-comparison). Strategy attribution and decision analysis wired. |
| **Agent Ecosystem (Phase 1)** | Complete | DB migration 017, 10 models, 10 repos, conversation system, memory system, 5 agent tools, AgentServer, CLI REPL, 4 Celery tasks. 370+ tests. |
| **Agent Ecosystem (Phase 2)** | Complete | Permissions system (roles/capabilities/budget/enforcement), 4 CRITICAL security fixes, trading intelligence (TradingLoop, SignalGenerator, TradeExecutor, PositionMonitor, TradingJournal, StrategyManager, ABTestRunner). 414+ tests. |
| **Agent Memory & Learning System** | Complete | `memory: project` on all 16 agents, 16 MEMORY.md files seeded, Memory Protocol in all agent prompts, 3 activity logging scripts, PostToolUse hook, `/analyze-agents` skill, `/review-changes` feedback capture. |
| **Agent Logging System** | Complete | 34 tasks, 5 phases. Centralized structlog + trace_id correlation, API call logging middleware, LLM cost estimation, LogBatchWriter (async batched DB), 16 Prometheus metrics (AGENT_REGISTRY), 2 new DB tables, 3 new API endpoints, 3 Celery analytics tasks, 6 Grafana dashboards, 11 alert rules. 66 new tests. |
| **C-Level Report Skill** | Complete | `/c-level-report` slash-command skill (7th skill). Gathers live metrics from 12 data sources (git, tests, code reviews, agent memory, etc.), generates rich markdown reports with progress bars, KPI tables, and risk matrices. Output: `development/C-level_reports/report-YYYY-MM-DD.md`. Supports 6 scopes: full, progress, quality, risk, agents, roadmap. |
| **Docs Site** | **COMPLETE** | 8 phases done. 50 MDX pages, 12 sections, 7 custom components, Cmd+K search, MD downloads, 5 REST API routes, landing integration, OpenGraph metadata, sitemap, custom 404. Security + perf hardened. |
| **Strategy Registry (STR-1)** | Production | 6 DB tables, 10 REST endpoints, versioning, ownership checks, 24 tests |
| **Strategy Executor (STR-2)** | Production | IndicatorEngine (7 indicators), StrategyExecutor, TestOrchestrator, TestAggregator, RecommendationEngine, 6 REST endpoints, 2 Celery tasks, 91 tests |
| **Training Run Aggregation (STR-5)** | Production | TrainingRunService, TrainingRunRepository, 7 REST endpoints at /api/v1/training, learning curve smoothing, aggregate stats on complete(), 16 tests |
| **Gymnasium Wrapper (STR-3)** | Production | `tradeready-gym/` package — 4 envs, 5 rewards, 2 action/obs spaces, 3 wrappers, 10 examples, 25+ compliance tests |
| **MCP + SDK + Docs (STR-4)** | Production | MCP expanded to 58 tools (was 43), SDK +13 methods (sync + async), api_reference.md +23 sections, skill.md updated |

### Tech Stack

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2.0 + asyncpg, Pydantic v2
- **Database:** TimescaleDB (PostgreSQL), Redis 7+
- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS 4.2, pnpm
- **Tasks:** Celery + Redis broker (16 beat tasks, including 5 ML retraining on `ml_training` queue)
- **Auth:** JWT (PyJWT) + API keys (bcrypt), dual auth flow
- **Testing:** pytest — platform: 1,734 unit tests (post-QA sprint baseline); agent: 51 files / 1984 tests; frontend: 207 vitest tests. Grand total: ~3,900+ test functions.
- **Linting:** ruff + mypy (strict)
- **Containers:** Docker + Docker Compose
- **Monitoring:** Prometheus + Grafana + structlog

### Architecture (14 Components)

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
14. Strategy Registry  — Strategy CRUD, versioning, test/training runs (src/strategies/)
15. Strategy Executor  — IndicatorEngine, StrategyExecutor, TestOrchestrator, RecommendationEngine (src/strategies/)
```

### Multi-Agent Model

Each account owns multiple **agents**, each with its own API key, starting balance, risk profile, and trading history. All trading tables keyed by `agent_id`. Auth flow: API key tries agents table first, falls back to accounts. JWT uses `X-Agent-Id` header.

### Database (22 migrations, current head: 022)

Key tables: `accounts`, `agents`, `balances`, `orders`, `trades`, `positions`, `ticks` (hypertable), `portfolio_snapshots` (hypertable), `trading_pairs`, `backtest_sessions`, `backtest_trades`, `backtest_snapshots` (hypertable), `battles`, `battle_participants`, `battle_snapshots` (hypertable), `candles_backfill`, `waitlist`, `strategies`, `strategy_versions`, `strategy_test_runs`, `strategy_test_episodes`, `training_runs`, `training_episodes`, `agent_sessions`, `agent_messages`, `agent_decisions`, `agent_journal`, `agent_learnings`, `agent_feedback`, `agent_permissions`, `agent_budgets`, `agent_performance`, `agent_observations` (hypertable), `agent_api_calls`, `agent_strategy_signals`, `agent_audit_log`

Note: Migration 011 missing from directory — chain skips 010 → 012.

### Sub-Agent Fleet (16 agents in `.claude/agents/`, all with `memory: project`)

| Agent | Category | Purpose |
|-------|----------|---------|
| `code-reviewer` | Quality Gate | Reviews code against project standards after every change |
| `test-runner` | Quality Gate | Runs tests + writes missing tests after every change |
| `context-manager` | Quality Gate | Maintains this file — tracks changes, decisions, learnings |
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
13. **Dual-source price pattern** — Frontend components that compute asset USDT values must use WS prices (primary) + REST `/market/prices` (30s fallback). WebSocket-only is unreliable for initial page loads.
14. **Frontend performance baseline** — PriceBatchBuffer uses `requestAnimationFrame` (not `setTimeout`); dashboard header split into 4 memo'd islands; 8 below-fold sections lazy-loaded via `next/dynamic`; GET dedup in api-client; 3x exponential retry (200/400/800ms); `useDailyCandlesBatch` batches 50 symbols/query; landing CSS in its own file.
15. **Agent roles hierarchy** — `READ_ONLY < STANDARD < ADVANCED < AUTONOMOUS < ADMIN`; permissions only granted upward from role level; enforcement layer checks role then capability, never either alone.
16. **Budget enforcement is Redis-backed** — `BudgetManager` stores daily limits in Redis with TTL-expiry at midnight; ensures budget resets survive service restarts without DB migrations.
17. **PermissionEnforcer raises `PermissionDenied`, never silently allows** — audit log entry written for every denied action; fail-closed by default (unknown capabilities are DENIED, not allowed).
18. **TradingLoop is the single entry point** — all agent trading must go through `TradingLoop.run()` which sequences the 7-step observe→decide→execute→monitor→journal→learn→sleep cycle; calling executor or monitor directly bypasses budget checks and audit logging.
19. **TradeExecutor idempotency key** — every execution request carries a UUID4 idempotency key; re-submitted keys within the same session return the original result without re-executing (prevents double-fills on retry).
20. **ABTestRunner uses Welch's t-test** — Welch's t-test (unequal variance) rather than Student's t-test; real trading strategies rarely have equal variance; minimum 10 data points per arm before evaluation.

---

## Recent Activity

### 2026-04-07 — Battle Live Crash Fix + Backtest Bug Fixes (BT-02, BT-17, orphan detection)

**Changes:**
- `src/api/schemas/battles.py` — Added typed `BattleLiveParticipantSchema` (13 fields: agent_id, agent_name, avatar_url, color, current_equity, roi_pct, total_pnl, total_trades, win_rate, rank, sharpe_ratio, max_drawdown_pct, status). Updated `BattleLiveResponse` to include `elapsed_minutes`, `remaining_minutes`, and `updated_at` fields that were previously absent.
- `src/api/routes/battles.py` — Added elapsed/remaining time computation in `GET /battles/{id}/live` handler. Added `model_validate()` conversion to enforce typed schema. Added `sa_inspect` error handling.
- `src/battles/service.py` — Enriched `get_live_snapshot()` to return all 13 participant fields: avatar_url, color, current_equity, roi_pct, total_pnl, total_trades, win_rate, live-computed rank, sharpe_ratio/max_drawdown_pct (null during live battle, populated on completion).
- `Frontend/src/components/battles/BattleDetail.tsx` — Fixed `!== null` to `!= null` (the primary crash fix — was not catching `undefined`). Added elapsed time badge display.
- `Frontend/src/components/battles/AgentPerformanceCard.tsx` — Made `total_trades` display null-safe.
- `Frontend/src/components/battles/BattleList.tsx` — Made leader ROI display null-safe.
- `tests/integration/test_battle_endpoints.py` — Updated all mocks to use new field names (`current_equity`, `roi_pct`, `total_pnl` instead of `equity`, `pnl`, `pnl_pct`).
- `tests/integration/test_real_user_scenario_e2e.py` — Updated mocks for new field names.
- `src/backtesting/sandbox.py` — `BacktestSandbox` now records `stop_price` on `SandboxTrade` for stop-loss/take-profit fills. Fixes BT-02 (stop_price missing from trade objects) and BT-17 (take-profit stop_price was None).
- `src/backtesting/engine.py` — `_persist_results()` writes `stop_price` to `BacktestTrade` DB rows.
- `src/api/routes/backtest.py` — Fixed orphan detection logic that was incorrectly marking newly-created sessions as `"failed"` before they could start. Also fixed compare endpoint returning null metrics for cancelled sessions.
- `alembic/versions/022_add_stop_price_to_backtest_trades.py` — New migration: nullable `stop_price NUMERIC(20,8)` on `backtest_trades`. Head: 021 → 022.
- `tests/unit/test_backtest_sandbox.py` — Updated to verify `stop_price` on filled stop-loss/take-profit trades.

**Decisions:**
- Introduced typed `BattleLiveParticipantSchema` to replace the previous `dict[str, object]` for live participant data. This makes the mismatch between backend and frontend impossible going forward — the schema now documents the exact 13-field contract.
- `elapsed_minutes` and `remaining_minutes` computed in the route handler (not the service), since they depend on `battle.started_at` and `battle.config["duration_minutes"]` which the service returns but the route assembles into a response object.
- `sharpe_ratio` and `max_drawdown_pct` are null during a live battle and only populated in the results endpoint (`GET /battles/{id}/results`) after completion. This is intentional — rolling Sharpe during a live battle would be misleading with few data points.

**Bugs fixed:**
- **Battle live UI crash** — "Cannot read properties of undefined (reading 'toFixed')" — Root cause: frontend called `.toFixed()` on fields like `roi_pct` and `total_pnl` that were `undefined` because the backend used different field names (`pnl_pct`, `pnl`) than what the TypeScript types expected. The `!== null` guard didn't catch `undefined`. Primary crash fix was `!= null` in `BattleDetail.tsx`; full fix required aligning all 13 field names between backend schema and frontend types.
- **BT-02 / BT-17 (stop_price missing)** — `BacktestSandbox` computed stop-loss/take-profit fills but did not populate `stop_price` on the resulting `SandboxTrade`. Engine didn't write it to the DB either. Fixed by threading `stop_price` from sandbox through engine to DB + migration 022.
- **Orphan detection killing new sessions** — `GET /backtest/{id}` orphan detection logic checked session age from `created_at` and prematurely marked newly-created (not yet started) sessions as `"failed"` if the check ran before the session was registered in `_active`. Fixed by checking `is_active()` before applying orphan timeout logic.

**Learnings:**
- `!== null` (strict) vs `!= null` (loose) is a significant distinction in TypeScript null-checking. Using `!= null` catches both `null` and `undefined`; `!== null` only catches `null`. For any field that could arrive as `undefined` from an API mismatch, the loose check is safer as a crash guard.
- The `battles.py` schemas module had a comment: "Loose-Typed Response Schemas use `dict[str, Any]`" — this was the root of the mismatch. When a schema uses `dict[str, Any]`, there is no compile-time enforcement that the dict keys match what the frontend expects.

---

### 2026-04-06 — CLAUDE.md Sync (src/ directories)

**Changes:**
- `src/database/repositories/CLAUDE.md` — Added 10 missing agent ecosystem repo files to Key Files table: `agent_budget_repo.py`, `agent_observation_repo.py`, `agent_performance_repo.py`, `agent_permission_repo.py`, `agent_session_repo.py`, `agent_message_repo.py`, `agent_decision_repo.py`, `agent_journal_repo.py`, `agent_learning_repo.py`, `agent_feedback_repo.py`. These were created in the 2026-03-21 agent ecosystem phases but never added to the inventory.
- `src/agents/CLAUDE.md` — Updated timestamp; added BUG-002 recent change entry for agent-aware `reset_agent()`.
- `src/database/CLAUDE.md` — Updated timestamp; added migration 021 cascade delete fix to Recent Changes.

**Learnings:**
- 10 agent ecosystem repository files existed on disk but were absent from the CLAUDE.md Key Files table — created during the agent ecosystem phases (2026-03-21) but the context-manager apparently didn't run for that session.

---

### 2026-04-01/02 — QA Bugfix Sprint (17 Bugs Fixed, Production Deployed)

**Changes:**
- `src/accounts/service.py` — BUG-001: `register()` now auto-creates a default agent via lazy `AgentService` import; `AccountCredentials` gained `agent_id`/`agent_api_key` fields. BUG-002: `reset_account()` is now fully agent-aware; fetches all non-archived agents, cancels orders and closes sessions at account level, then re-creates per-agent `Balance` and `TradingSession` rows satisfying `NOT NULL` constraints.
- `src/api/routes/auth.py` + `src/api/schemas/auth.py` — BUG-001: `POST /auth/register` response now includes `agent_id` and `agent_api_key`. Clients should use `agent_api_key` as `X-API-Key` for trading.
- `src/api/routes/account.py` — BUG-017: `/account/positions` fetches `opened_at` from the `Position` table directly (removes epoch sentinel). Fixed `asyncio.gather` on shared DB session (`IllegalStateChangeError`); queries now run sequentially.
- `src/api/routes/battles.py` — BUG-003: `_battle_to_response()` checks SQLAlchemy inspect state before accessing `participants` relationship, preventing `MissingGreenlet` in async context.
- `src/api/routes/market.py` — BUG-012: `GET /market/tickers` `symbols` param is now optional; returns all tickers when omitted.
- `src/api/schemas/trading.py` — BUG-015: `OrderRequest.price` accepts `stop_price` as alias via `AliasChoices`; stop-loss/take-profit orders with `stop_price` field no longer 422.
- `src/database/repositories/battle_repo.py` — BUG-003: Removed locally-defined `BattleNotFoundError`; raises `TradingPlatformError` subclasses from `src/utils/exceptions.py` for consistent error handling.
- `src/order_engine/engine.py` — BUG-011: `_upsert_position()` now includes fee in cost basis for buys (`avg_entry_price` = true fee-inclusive cost) and subtracts sell fee from `realized_pnl`. Win/loss classification now reflects true economic P&L.
- `src/risk/manager.py` — BUG-016: Step 6 `position_limit_exceeded` rejection message now includes current position value, projected value, max allowed, and total equity.
- `src/strategies/service.py` — BUG-005: `create_strategy()` catches `pydantic.ValidationError` and raises `InputValidationError` (HTTP 400) instead of unhandled 500.
- `src/tasks/celery_app.py` — BUG-018: Wrapped `importlib.util.find_spec("agent.tasks")` in `try/except ModuleNotFoundError`; Celery no longer crashes on startup when `agent/` directory is present but not installed as a package.
- `alembic/versions/021_fix_cascade_delete_agent_fks.py` — BUG-004: New migration adding `ON DELETE CASCADE` to 6 FK constraints on agent-scoped trading tables. Head: 020 → 021. Applied to production.
- `scripts/backfill_history.py` — Fixed dry-run memory leak (accumulated candles list) and candle double-counting (off-by-one on `to_dt` calculation).
- `Frontend/src/lib/types.ts` — `BattleLiveParticipant.rank` changed from `number` to `number | null` (rank is null until battle completes).
- `Frontend/src/lib/api-client.ts` — 401 JWT expiry now falls back to API key auth for battle endpoints.
- `Frontend/src/hooks/use-battles.ts` + `use-battle-results.ts` — Both hooks now accept API key auth (not JWT-only).

**Decisions:**
- Registration auto-creates a default agent: eliminates the two-step "register then create agent" flow that was causing immediate 400 errors on first trade. Agent creation failure is non-fatal; caller can create manually.
- `BattleNotFoundError` migrated from local repo definition to `TradingPlatformError` hierarchy: ensures the global exception handler in `src/main.py` correctly serializes the error and returns the right HTTP status code.

**Bugs fixed:**
- BUG-001 (P0): New accounts had zero balance — auto-agent creation missing from registration → fixed in `service.py`.
- BUG-002 (P1): `reset_account()` wiped balances without recreating agent-scoped balance rows → account stuck at zero after reset.
- BUG-003 (P0): Battle creation/fetch raised `MissingGreenlet` in async context → SQLAlchemy lazy load outside async session. Fixed with inspect-state guard + exception hierarchy fix.
- BUG-004 (P1): `DELETE /agents/{id}` raised FK violation on 6 tables → cascade migration 021.
- BUG-005 (P0): `POST /strategies` returned 500 on bad strategy definition → now 400 with validation details.
- BUG-011 (P2): Win rate inflated — fees not included in `realized_pnl` calculation → fixed cost basis in `_upsert_position()`.
- BUG-012 (P2): `GET /market/tickers` required `symbols` param → optional, returns all on omit.
- BUG-015 (P3): `stop_price` field in order payload caused 422 → `AliasChoices` fix.
- BUG-016 (P3): `position_limit_exceeded` rejection gave no numbers → detailed message added.
- BUG-017 (P2): `opened_at` for positions always returned epoch `1970-01-01` → real value from DB.
- BUG-018 (P1): Celery crash on startup when `agent/` dir present but not installed → `try/except` on `find_spec`.

**New files:**
- `development/qa-bugfix-plan.md` — Full QA plan with all 17 bugs, priorities, and fix details.
- `development/reports/tester-guide.md` — Tester onboarding guide for running QA against production.
- `development/tasks/qa-bugfix-sprint/` — 13 task files + README + run-tasks guide.

---

### 2026-04-01 — C-Level Deployment & Data Continuity Analysis

**Report generated:** `development/C-level_reports/report-2026-04-01-deployment-analysis.md`

**Coverage:**
- CI/CD pipeline: GitHub Actions SSH-based deploy with auto-rollback on migration failure
- Database migration safety: additive-only pattern confirmed; pre-migration pg_dump backup in deploy workflow
- Candle data continuity during deploys: rolling restart strategy documented; tick buffer loss window (~1s) accepted; `DataReplayer` uses UNION of `candles_backfill` + `ticks` to span gap
- Data gap detection and recovery: gap-fill task designed (`development/gap_fill_implementation_plan.md`, `development/market_data_gap_fill.md`) but not yet deployed to production
- Backup strategy: pre-deploy backup exists in `deploy.yml`; no scheduled cron backup — identified as outstanding gap
- Monitoring: Prometheus + 11 alert rules + 7 Grafana dashboards confirmed in place

**No code was changed** — research and reporting only.

---

### 2026-04-01 — Production Market Data Fix

**Changes:**
- `src/exchange/ccxt_adapter.py` — `fetch_markets()` now filters to `type == "spot"` only; prevents ~2000 swap/futures markets from being included and crashing ingestion. `watch_trades()` now batches symbols in groups of 200 (`_WS_BATCH_SIZE`) via concurrent asyncio tasks writing to a shared `asyncio.Queue` (`_watch_single_batch`, `_batch_watcher`, `_watch_trades_roundrobin` extracted). Added `asyncio` import.
- `src/exchange/symbol_mapper.py` — `load_markets()` now skips non-spot entries when a spot mapping already exists; prevents `BTC/USDT:USDT` (perpetual swap) from overwriting `BTC/USDT` (spot) in the reverse lookup.
- `src/tasks/celery_app.py` — `agent.tasks` detection changed from direct `import` to `importlib.util.find_spec()` to avoid circular ImportError (`agent/tasks.py` → `celery_app.app` → not yet defined). Celery workers now start without the optional agent package.
- `agent/tasks.py` — Added `# type: ignore[attr-defined]` for lazy-imported `Agent.active_strategy_label`; replaced `func.Integer` with `Integer` for correct `Cast` typing.

**Decisions:**
- Run on legacy Binance WS fallback while CCXT fixes are validated in production; switch back to CCXT path once stability confirmed.
- Seed `trading_pairs` via `seed_pairs.py` SSH run (439 pairs) rather than automatic startup migration — seed is an operational step, not a schema migration.

**Bugs fixed:**
- **CCXT ingestion crash (spot/swap mixing)** — `fetch_markets()` returned ~3000 markets including perpetual swaps; the mapper tried to subscribe to swap symbols that Binance WS rejected. Fix: filter to `type == "spot"`.
- **Symbol mapper swap overwrite** — After loading spot symbols, a second loop iteration encountered swap variants (e.g., `BTC/USDT:USDT`) and overwrote the `BTCUSDT` → `BTC/USDT` reverse mapping. Fix: skip non-spot entry if spot mapping already present.
- **Celery circular ImportError** — `celery_app.py` directly imported `agent.tasks` which imports `app` from `celery_app` — but `app` wasn't defined yet. Fix: use `importlib.util.find_spec()` to check availability without importing.
- **Empty `trading_pairs` table** — Production DB had 0 pairs after initial deploy; ingestion service failed to subscribe to anything. Fix: ran `seed_pairs.py` on server via SSH, seeded 439 pairs.
- **DB connection exhaustion (401 errors)** — PostgreSQL `max_connections=50` was exhausted by leaked idle-in-transaction sessions from Celery tasks. Auth middleware couldn't get a DB connection, returning 401 for all authenticated requests. Fix: increased `max_connections` to 200, added `idle_in_transaction_session_timeout=60s` on production TimescaleDB.
- **mypy errors** — `ccxt_adapter.py` type narrowing issue with `ExchangeTick | None` queue; `agent/tasks.py` `func.Integer` wrong type for `Cast`. Both fixed.

**Learnings:**
- CCXT `fetch_markets()` on Binance returns spot + perpetual swaps + delivery futures by default. Always filter by `type` when you only want spot.
- The `watch_trades()` call on CCXT Pro opens one WS connection per symbol if not batched — for 439 symbols this means 439 connections. Batching is mandatory.
- Production Docker services were all healthy but ingestion was silent because the `trading_pairs` table was empty. Health checks don't verify seed data.
- Circular imports between Celery modules: never directly import a module that imports `app` before `app = Celery(...)` is executed. Use `importlib.util.find_spec()` to check availability without triggering the import chain.
- DB `max_connections=50` is too low for this stack (API + Celery 4 workers + Beat + ingestion + pgAdmin). Celery tasks that open sessions without proper cleanup leak idle-in-transaction connections. The `idle_in_transaction_session_timeout` PostgreSQL setting is essential protection.

---

### 2026-04-01 — V.0.0.2 Production Deployment Fixes

**Changes:**

CI/CD Pipeline Fixes:
- `pyproject.toml` — Added 2 mypy per-module overrides (`agent.strategies.rl.*` and `src.mcp.tools`) to suppress SB3/MCP stub warnings (`warn_unused_ignores=false`, `disallow_subclassing_any=false`)
- `requirements.txt` — Added `numpy>=1.26` required by `src/strategies/` (was missing, broke CI)
- `tests/unit/test_ab_testing.py` — Added `pytest.importorskip("pandas")` guard; skips gracefully when agent ML deps absent
- `tests/unit/test_strategy_manager.py` — Same `pytest.importorskip("pandas")` guard
- `tests/unit/test_agent_tools.py` — Added `pytest.importorskip("agentexchange")` guard; skips when SDK not installed
- `agent/strategies/rl/runner.py` — Fixed mypy type-ignore comments for SB3 `BaseCallback` stubs

Deployment Pipeline Fixes:
- `.github/workflows/deploy.yml` — Major rewrite: reads DB credentials from `.env` (not hardcoded), SSH timeout raised to 30m, excludes heavy time-series tables from pg_dump, stashes local changes before `git pull`, uses `git reset --hard`, starts `timescaledb` and `redis` before alembic commands, uses `docker compose run --rm` instead of `exec` for alembic
- `.github/workflows/test.yml` — Changed trigger: only runs on `main` branch (was running on all pushes)

Docker/Infrastructure Fixes:
- `docker-compose.yml` — Removed Redis `--requirepass` flag; Redis is internal-network-only with no host port exposure, password requirement was unnecessary and caused auth failures
- `.env.example` — Removed `REDIS_PASSWORD`, simplified `REDIS_URL` (no password component)

Migration Fix:
- `alembic/versions/012_agent_scoped_unique_constraints.py` — Fixed: now drops constraint before dropping the backing index. PostgreSQL prevents `DROP INDEX` on an index that backs a live constraint.

Registration Bug Fix:
- `src/accounts/service.py` — Removed `TradingSession` creation from `register()`. `TradingSession.agent_id` is NOT NULL but registration has no `agent_id`, causing every registration to fail with `IntegrityError` misreported as `DuplicateAccountError`. TradingSession is now created downstream when an agent is assigned.
- `src/config.py` — Added `https://tradeready.io` and `https://www.tradeready.io` to default `CORS_ORIGINS`

New Files:
- `development/deployment-fix-plan.md` — Deployment fix planning document (archived)

**Decisions:**
- Redis password removed from default config: Redis is on an internal Docker network only (no host-port binding), so `--requirepass` adds complexity with no security benefit in this topology.
- `test.yml` restricted to `main` branch only: feature branch CI was consuming quota and slowing iteration; production gate is sufficient on `main`.
- `docker compose run --rm` preferred over `exec` for alembic migrations in deploy: `exec` requires a running container; `run --rm` works whether or not the service is already up.

**Bugs fixed:**
- **Registration always failing** — `register()` tried to create a `TradingSession` with `agent_id=NULL`, but the column is `NOT NULL`. SQLAlchemy raised `IntegrityError`, which the exception handler misclassified as `DuplicateAccountError`. Fix: removed `TradingSession` creation from `register()`.
- **Migration 012 failing on redeploy** — `DROP INDEX` on a constraint-backing index raised `ERROR: cannot drop index ... because constraint ... requires it`. Fix: `DROP CONSTRAINT` first, then `DROP INDEX`.

**Learnings:**
- Always verify `NOT NULL` column constraints before constructing ORM objects — SQLAlchemy defers constraint checking to flush time, so the error appears at an unexpected call site.
- When `IntegrityError` is caught and re-raised as a domain error, the message can mask the real cause — log the original exception detail before re-raising.

---

### 2026-03-23 — `/c-level-report` Skill, C-Level Recommendations, Strategy Research

`/c-level-report` skill created (7th skill): `.claude/skills/c-level-report/SKILL.md` + templates + example, 6 scope variants, gathers from 12 data sources, outputs to `development/C-level_reports/`. All 5 C-level recommendations complete (39 tasks): Docker infra, security hardening (7 HIGH → 0 HIGH: privilege escalation, async budget leak, Redis password, audit logging, model checksum), regime classifier trained (99.92% accuracy, WFE 97.46%, Sharpe 1.14 vs MACD 0.74), continuous retraining pipeline (4 Celery beat schedules, DriftDetector in TradingLoop, Prometheus retrain metrics, Grafana panel, 29 integration tests). Strategy research completed: 4 documents created (`strategy-research-complete.md`, `strategy-research-intern-guide.md`, `training-loops-research-intern-guide.md`, `implementation-plan-a-to-z.md`). 16-module build plan across 6 phases; codebase audit found 14 of 16 planned modules missing. Key decisions: goal is ONE best strategy via automated search; autoresearch scoring: composite = Sharpe × (1 - DD/0.50); start with free data sources only. Key learnings: DSR is critical before mass-testing (1000 strategies produces expected best Sharpe 3.72 by pure chance); regime classifier's `volume_ratio` feature took accuracy from ~87% to 99.92%; all 7 ML training loops cost ~$0.35/month.

---

### 2026-03-22 — Trading Agent Master Plan ALL 37 Tasks Complete (~1200+ New Tests)

All 37 tasks of the Trading Agent Master Plan completed. Key deliverables: `DriftDetector` (Page-Hinkley test in `TradingLoop`), `RetrainOrchestrator` (4 Celery schedules: ensemble 8h, regime 7d, genome 7d, PPO 30d; A/B gate on deployments), `WalkForwardValidator` (WFE metric, `is_deployable=False` at WFE < 50%, 94 tests), `RecoveryManager` (3-state FSM: RECOVERING→SCALING_UP→FULL, Redis-backed, ATR normalization), `StrategyCircuitBreaker` (3 trigger rules, Redis TTL pauses), `PairSelector` (volume/momentum ranking with TTL cache), `WSManager` (ticker + order channel subscriptions, REST fallback), memory-driven learning loop, 5 new REST tools, 6 advanced order tools (SDK count: 17→25). Battle frontend: 7 components (BattleList, BattleDetail, BattleCreateDialog, BattleLeaderboard, BattleReplay, EquityCurveChart, AgentPerformanceCard), 2 routes, 2 hooks, 14 API functions, 15 TypeScript types. Agent dashboard analytics: 4 components, 2 hooks. Prometheus/Grafana: auto-provisioning volume mounts, `rule_files:` stanza, `agent:8001` scrape job. ~1200+ new tests. Key decisions: DriftDetector uses Page-Hinkley (not CUSUM) — single hyperparameter, well-suited for return streams; RetrainOrchestrator uses A/B gate on all deployments (min_improvement=0.01); `settle_agent_decisions` runs every 5 min; `monitoring/provisioning/` maps to `/etc/grafana/provisioning/` (not `/var/lib/grafana/`). Phase 0 Group A also completed: Redis cache glob bug fixed, working memory 24h TTL, `LogBatchWriter` singleton wired into `AgentServer`, 7 `IntentRouter` handlers, `PermissionDenied` as `TradingPlatformError` subclass, migrations 018/019 validated. 74 additional tests.



---

### 2026-03-21 — Agent Ecosystem Phases 1+2, Agent Memory & Learning System, Agent Logging System

Agent Ecosystem Phase 1 (Tasks 01-20): 10 new DB models (migration 017), 10 repo classes, conversation system (session/history/context/router with 3-layer IntentRouter: keyword→regex→LLM), memory system (abstract store + Postgres + Redis hot cache, two-phase retrieval, relevance scoring), 5 agent tools (reflect_on_trade, review_portfolio, scan_opportunities, journal_entry, request_platform_feature), AgentServer with lifecycle + SIGTERM handlers, CLI REPL with 10 slash commands, 4 Celery beat tasks, 22 config fields. 370+ tests.

Agent Ecosystem Phase 2 (Tasks 21-36): Permissions system (roles/capabilities/budget/enforcement; roles: READ_ONLY < STANDARD < ADVANCED < AUTONOMOUS < ADMIN), 4 CRITICAL security fixes (float precision, TOCTOU race, fail-open, default role), trading intelligence (TradingLoop 7-step cycle, SignalGenerator, TradeExecutor with UUID idempotency key, PositionMonitor, TradingJournal, StrategyManager, ABTestRunner with Welch's t-test). 414+ tests.

Agent Memory & Learning System (14 tasks):  enabled on all 16 agents, 16 MEMORY.md files seeded, Memory Protocol in all 16 agent prompts, 3 activity logging scripts (log-agent-activity.sh, agent-run-summary.sh, analyze-agent-metrics.sh), PostToolUse hook in settings.json, /analyze-agents skill, /review-changes feedback capture.

Agent Logging System (34 tasks, 5 phases): Centralized structlog + trace_id correlation, LogBatchWriter async batched DB persistence (avoids per-call latency on hot path), 16 Prometheus metrics (AGENT_REGISTRY separate from platform registry), 2 new DB tables (agent_api_calls, agent_strategy_signals), trace_id on AgentDecision (migration 018), feedback lifecycle (migration 019), AuditMiddleware (fire-and-forget, never blocks request), 4 platform metrics in src/monitoring/metrics.py, 3 new agent API endpoints, 3 Celery analytics tasks, 6 Grafana dashboards, 11 Prometheus alert rules, 66 new tests.

Key decisions (permanent): auto-summarize at 50 messages (context cost vs coherence); two-phase memory retrieval (Redis <1ms hot path, Postgres fallback); TradingLoop is single entry point (all agent trading must go through it — bypassing skips budget checks and audit logging); TradeExecutor uses UUID4 idempotency key (re-submitted keys return original result, no double-fills); ABTestRunner uses Welch's t-test (unequal variance is realistic for trading strategies); AGENT_REGISTRY separate from platform registry (served on different ports).
---

### 2026-03-20 — Summary: Agent Strategy System, Testing Agent V1, Frontend Performance, CLAUDE.md Sync (Multiple Sessions)

2026-03-20 was a multi-session day covering: (1) TradeReady Platform Testing Agent V1 complete — `agent/` package with Pydantic AI + OpenRouter, 4 workflows, 117 tests; (2) Agent strategy system complete — 5 strategies (RL/evolutionary/regime/risk/ensemble), 578 tests, security hardened; (3) Agent deployment prep — Dockerfile, `[ml]` extras, SHA-256 checksums, asyncio perf fixes; (4) Frontend performance optimization — 23 tasks, PriceFlashCell memo, 4 header islands, 8 lazy sections, GET dedup, 3x retry, requestAnimationFrame buffer, 207 tests; (5) Coming Soon page at `/`, landing moved to `/landing`; (6) CLAUDE.md sync — 5 strategy sub-package files created, new docs added. Rate limit tiers expanded (backtest 6000/min, training 3000/min). `parse_interval()` added to utils.

**Key decisions (permanent):** Pydantic AI over LangChain; three integration layers (SDK/MCP/REST); LLM for decisions only; `[ml]` extras isolate 1.5 GB ML deps; SHA-256 checksums for model files; rate limit tiers prevent backtest throttling; asyncio.to_thread for blocking ML ops; `--profile agent` gates resource use.

**Key learnings (permanent):** CCXT returns spot + swaps/futures by default — filter by `type`. `BattleRunner` must use JWT auth. `PPODeployBridge` silent until 30-candle buffer. `RegimeSwitcher` is stateful per session. Incremental sklearn learning rejected.

**Failed approaches:** Claude Agent SDK rejected (no typed return schemas). Full LLM execution loop too slow (3-5s/call × N steps).

---

### 2026-03-19 — Summary: Documentation Site Complete (All 8 Phases)

Docs site built from scratch using Fumadocs. All decisions and learnings are captured in the 2026-03-18 summary block below.

**Inventory (permanent reference):**
- 50 MDX pages across 12 sections: quickstart, concepts, api (13 pages), websocket, sdk, mcp, frameworks, strategies, gym, backtesting, battles, skill-reference
- 7 custom MDX components: endpoint, api-example, param-table, response-schema, swagger-button, status-badge, download-button
- Cmd+K full-text search (`/api/search`), 50 downloadable `.md` files generated at build time, 5 REST API routes under `/api/v1/docs/`
- Per-page OpenGraph metadata, `/docs/sitemap.xml`, custom 404 page
- Build: zero TypeScript/lint errors, 81 pages generated statically
- Deferred: OG image generation (requires `@vercel/og`), mobile responsiveness testing (5 tasks), screen reader testing (1 task)

---

### 2026-03-18 — Summary: Strategy Backend + Gymnasium + MCP + Frontend + Docs (STR-1 through STR-UI-2, all 8 docs phases)

All server-side strategy phases (STR-1 to STR-5), gymnasium wrapper (STR-3), MCP expansion (12→43→58 tools), SDK extensions, strategy/training frontend UI (STR-UI-1, STR-UI-2), wallet fix, and docs site (all 8 phases) completed.

**Key decisions (permanent):**
- `IndicatorEngine` uses pure numpy (not TA-Lib) — avoids C extension in Docker.
- Strategy versions are immutable after creation — new version for every update.
- Training run IDs are client-provided UUIDs — gym loops assign stable IDs before DB registration.
- Design decision #13: Dual-source price pattern — wallet components use WS prices primary + REST `/market/prices` (30s) fallback.
- `TrainingTracker` uses explicit `close()` / context manager (no `__del__` — unreliable finalizer).
- Gymnasium `reset()` returns `(obs, info)` 2-tuple; `step()` returns 5-tuple — gymnasium ≥0.29 API.
- Stateful reward functions require `reset()` — made abstract in base class; otherwise cross-episode state leakage.
- Root CLAUDE.md is cross-cutting only; all module details in sub-files.
- Mandatory pipeline: code-reviewer → test-runner → context-manager after every change.

**Key learnings (permanent):**
- `TrainingEpisode` data is nested under `episode.metrics.*` — all frontend components must use this path.
- `battle-store.ts` does not exist — battles use TanStack Query only (no Zustand store).
- Migration 011 is missing from `alembic/versions/` — chain skips 010 → 012.
- Fumadocs `source.config.ts` must be at repo root (not `src/`) for MDX plugin to resolve content paths.
- `RootProvider` with `search.options.api` requires an absolute path — fetched from a Web Worker context.

---

*Older entries will appear below as development continues. Entries older than 30 days are summarized; older than 90 days are pruned (decisions and learnings are permanent).*
