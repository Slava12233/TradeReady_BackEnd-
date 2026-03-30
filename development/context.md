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

**Active work:** Strategy search system planning complete. Full A-Z implementation plan created (16 modules, 6 phases). Comprehensive research produced (strategy landscape, autoresearch integration, training loop analysis, cost modeling). Ready to begin Phase 1: Foundation modules (Feature Pipeline, Signal Interface, Deflated Sharpe).
**Last session:** 2026-03-23 — Full strategy research cycle: (1) strategy-research-complete.md (senior report), (2) strategy-research-intern-guide.md (intern version), (3) training-loops-research-intern-guide.md (training loop costs and schedules), (4) implementation-plan-a-to-z.md (16-module build plan). Codebase audit revealed 14 of 16 planned modules are MISSING. Vision clarified: find ONE best strategy via automated search, not run 1000 agents.
**Next steps:** (1) Build Module A: Unified Feature Pipeline (`agent/strategies/features/`). (2) Build Module B: Pluggable Signal Interface (`agent/strategies/signals/`). (3) Build Module C: Deflated Sharpe Ratio (`agent/strategies/validation/`). (4) Then Phase 2: Volume Spike, Momentum, Mean Reversion strategies.
**Blocked:** Nothing. All infrastructure in place. Implementation plan ready.

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
- **Testing:** pytest — platform: 87 unit files / 981 tests + 26 integration files / 553 tests; agent: 51 files / 1984 tests; frontend: 207 vitest tests. Grand total: ~3,700+ test functions.
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

### Database (20 migrations, current head: 020)

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

### 2026-03-23 — Strategy Research & Implementation Planning

**Changes:**

Research Documents Created:
- `development/strategy-research-complete.md` — Comprehensive A-Z research: current platform state (15 production systems), 5 existing strategies, autoresearch integration plan (Karpathy loop adapted for trading), 20+ new strategy candidates across 4 priority tiers, tools/libraries to add, data sources to integrate, search funnel architecture, overfitting prevention (Deflated Sharpe Ratio)
- `development/strategy-research-intern-guide.md` — Same content rewritten for a senior middle school intern: every concept explained with analogies, full glossary of 30+ trading/ML terms
- `development/training-loops-research-intern-guide.md` — Complete analysis of all 7 training loops: how they connect, exact schedules (ensemble 8h, regime 7d, genome 7d, PPO 30d, drift continuous), real costs ($0.35/month total for all training), time budgets, weekly/monthly play-by-play, what-can-go-wrong guide
- `development/implementation-plan-a-to-z.md` — 16-module build plan across 6 phases (10 weeks): Module A (Feature Pipeline) through Module P (Order Flow). Each module specifies: files to create, interfaces, config, tests, time estimate, cost, dependencies

Codebase Audit Results (14 of 16 planned modules MISSING):
- MISSING: Autoresearch harness, cross-sectional momentum, pairs trading, volume spike detector, LLM sentiment signal, transformer prediction, Deflated Sharpe Ratio, funding rate arb, VectorBT, synthetic data, order flow analysis, external data connectors, modular strategy template, pluggable signal interface
- PARTIAL: Walk-forward (3 of 5 strategies), feature engineering (3 separate implementations, no unified pipeline), signal aggregation (hardwired to 3 sources, not pluggable)
- EXISTS: Mean reversion (config only in regime strategy_definitions.py)

**Decisions:**
- Vision clarified: goal is to find ONE best strategy via automated search, not run 1000 agents in parallel. Agents are test subjects during search, not permanent production runners.
- Build order determined by dependency analysis: Foundation (A/B/C) → First Strategies (D/E/F) → Autoresearch (G/H) → Stat-Arb (I/J) → Data (K/L/M) → Advanced ML (N/O/P)
- Autoresearch scoring: composite = Sharpe × (1 - max_drawdown/0.50), with hard rejects at DD>30%, Sharpe<0, trades<50
- Start with free data sources only (Fear & Greed, CoinGecko, Binance depth); add paid sources only if strategy search shows they help

**Learnings:**
- All ML training loops combined cost ~$0.35/month in LLM API fees. $5/day LLM budget uses <1% for training.
- PPO training on CPU takes 30-60 min for 500K timesteps — no GPU needed
- Regime classifier retrains in ~30 seconds (XGBoost is incredibly fast for 8,760 samples)
- Deflated Sharpe Ratio is CRITICAL before mass-testing: testing 1000 strategies produces expected best Sharpe of 3.72 by pure luck
- Karpathy autoresearch yields ~12 experiments/hour, ~100 overnight — directly applicable to our strategy template

---

### 2026-03-23 — All 5 C-Level Recommendations Implemented (39 Tasks Complete)

**Changes:**

Phase 1 — Docker Infrastructure:
- `.env` created from `.env.example`, all Docker Compose services started and healthy
- Alembic migrations applied (head: 019), exchange pairs seeded, 5 agent accounts provisioned
- Grafana dashboards imported and Prometheus scrape targets verified
- Historical candle data backfill initiated (12+ months BTC/ETH/USDT pairs)

Phase 2 — Security Hardening (all 7 HIGH issues resolved):
- `agent/permissions/manager.py` — ADMIN role check added to `grant_capability()` and `set_role()`; privilege escalation vector closed (R2-01)
- `agent/permissions/budget.py` — `ensure_future` tasks tracked and awaited; no more fire-and-forget async budget updates (R2-02)
- `docker-compose.yml` — Redis `requirepass` enabled + Docker internal bind only; Redis no longer accessible externally (R2-03)
- `agent/permissions/audit.py` — "allow" audit events now persisted to `agent_audit_log`; previously only denials were stored (R2-04)
- `agent/strategies/rl/train.py` — SHA-256 checksum verified before every `PPO.load()` call; prevents loading tampered model files (R2-05)
- `agent/strategies/evolutionary/evolve.py` — Checksum verification added before `joblib.load()` for genome serialization (R2-06)
- CLI entrypoints — All remaining `--api-key` argument exposures removed from 3 CLI scripts; API keys passed via env var only (R2-07)
- `agent/trading/loop.py`, `agent/server_handlers.py` — All `float(Decimal)` casts replaced with `Decimal`-safe arithmetic (R2-08)
- `agent/tests/test_security_regression.py` — 20 regression tests covering all 7 security fixes (R2-10)

Phase 3 — Regime Classifier Training:
- Regime classifier trained on 12-month BTC 1h data: 99.92% test accuracy (R3-01, R3-02)
- Regime switcher demo run: correct bull/bear/sideways/volatile transitions validated (R3-03)
- Walk-forward validation: WFE 97.46% (well above 50% deployability threshold) (R3-04)
- Backtest comparison: Regime strategy Sharpe 1.14 vs MACD 0.74 vs Buy-and-Hold 0.61 (R3-05, R3-06)

Phase 4 — Continuous Retraining Pipeline:
- `src/tasks/retrain_tasks.py` — Celery task wrapping `RetrainOrchestrator` with A/B gate on all deployments (R5-01)
- `src/tasks/celery_app.py` — 4 new beat schedule entries: ensemble weights 8h, regime 7d, genome 7d, PPO 30d (R5-02)
- `agent/trading/loop.py` — `DriftDetector` wired into live `TradingLoop._observe()` with retrain trigger (R5-03)
- `src/monitoring/metrics.py` — 4 new Prometheus metrics for retrain events (retrain_triggered, retrain_completed, retrain_duration_seconds, retrain_ab_gate_result) (R5-04)
- `monitoring/dashboards/retraining.json` — New Grafana dashboard panel for retraining event timeline (R5-05)
- `agent/tests/test_retrain_integration.py` — 29 integration tests for retrain Celery tasks and drift-triggered retrain flow (R5-06)

Quality Gate:
- Full code review passed (QG-01): 0 blockers, 3 MEDIUM suggestions noted
- Full test suite passed (QG-02): all existing tests green, 49 new tests added
- Context and CLAUDE.md files updated (QG-03): 12 CLAUDE.md files synced (permissions, regime, strategies, rl, trading, tasks, database, monitoring, tests, agent, sdk, alembic)

**Decisions:**
- Redis `requirepass` approach over network ACLs — simpler to maintain in Docker Compose; network ACLs require custom redis.conf volume mounts and add operational complexity without meaningful security gain in this deployment topology
- Checksum verification uses SHA-256 stored alongside model file (`.sha256` sidecar) — avoids DB dependency at load time; `.sha256` files committed to git for auditability

**Learnings:**
- Regime classifier achieved 99.92% accuracy on 12-month BTC data with 6 features (added `volume_ratio` was the key improvement over 5-feature baseline at ~87%)
- WFE of 97.46% indicates very low overfitting; regime strategy generalizes well out-of-sample — the walk-forward validation confirmed the classifier is not curve-fitted to specific market periods

---

### 2026-03-23 — `/c-level-report` Skill Created (7th Skill)

**Changes:**
- `.claude/skills/c-level-report/SKILL.md` — Core workflow definition: 6 steps, 11 report sections, 9 rules. Invoked via `/c-level-report [scope]`. Gathers metrics from 12 data sources (git, tests, code reviews, agent memory, daily notes, Grafana, task boards, etc.)
- `.claude/skills/c-level-report/templates/report-template.md` — Section templates and visual elements reference (progress bars, KPI tables, risk matrices, mermaid diagrams)
- `.claude/skills/c-level-report/examples/sample-report.md` — Realistic sample report (~310 lines) using actual project data
- `development/C-level_reports/.gitkeep` — Output directory created for generated reports
- `development/tasks/c-level-report-skill/` — 5 task files + README + run-tasks.md for the skill build process
- `development/c-level-report-skill-plan.md` — Implementation plan for the skill

**CLAUDE.md updates (done inline by task agent):**
- Root `CLAUDE.md` — `/c-level-report` row added to Skills table; skill count updated to 7
- `.claude/skills/CLAUDE.md` — New row in inventory table; `Recent Changes` entry added; `last-updated` set to 2026-03-23
- `development/CLAUDE.md` — `C-level_reports/` added to subdirectories table; `c-level-report-skill/` added to tasks listing; `Recent Changes` entry added

**Decisions:**
- Skill saves to `development/C-level_reports/` (not `development/reports/`) — consistent with Obsidian vault structure and the skill name; directory name mirrors the command
- Supports 6 scope variants (full, progress, quality, risk, agents, roadmap) — covers CTO, CPO, and investor audiences with a single skill
- Report uses markdown progress bars (`[====------] 40%`) — renders cleanly in both Obsidian and GitHub without requiring chart libraries

---

### 2026-03-22 — Trading Agent Master Plan ALL 37 Tasks Complete (~1200+ New Tests)

**Changes:**

New files created:
- `agent/server_handlers.py` — 7 async intent handler functions + `REASONING_LOOP_SENTINEL` for fallback routing
- `agent/tests/test_server_writer_wiring.py` — 20 tests for `LogBatchWriter` singleton wiring in `AgentServer`
- `agent/tests/test_server_handlers.py` — 54 tests for all 7 intent handlers
- `agent/strategies/risk/recovery.py` — `RecoveryManager` 3-state FSM (RECOVERING→SCALING_UP→FULL), Redis persistence, ATR normalization
- `agent/strategies/ensemble/circuit_breaker.py` — `StrategyCircuitBreaker`: 3 trigger rules (consecutive losses, weekly drawdown, ensemble accuracy), Redis-backed TTL pauses
- `agent/strategies/ensemble/attribution.py` — `AttributionLoader`, `AttributionResult`: reads 7-day Celery-computed PnL attribution, updates `MetaLearner` weights, auto-pauses negative-PnL strategies
- `agent/strategies/drift.py` — `DriftDetector` using Page-Hinkley test; integrated into `TradingLoop._observe()`
- `agent/strategies/retrain.py` — `RetrainOrchestrator`: 4 schedules (ensemble weights 8h, regime classifier 7d, genome population 7d, PPO RL 30d), A/B gate on deployments
- `agent/strategies/walk_forward.py` — `WalkForwardConfig`, `WindowResult`, `WalkForwardResult`, `generate_windows()`, `compute_wfe()`, `run_walk_forward()`, `walk_forward_rl()`, `walk_forward_evolutionary()`; WFE < 50% triggers `is_deployable=False`
- `agent/trading/ws_manager.py` — `WSManager`: subscribes to ticker + order channels, maintains price buffer, handles fill notifications, REST fallback on disconnect
- `agent/trading/pair_selector.py` — `PairSelector`, `SelectedPairs`, `PairInfo`: volume/momentum ranking with TTL cache and `asyncio.Lock`
- `tradeready-gym/tradeready_gym/rewards/composite.py` — `CompositeReward`: 4-factor weighted reward (Sortino, PnL, activity, drawdown)
- `scripts/e2e_provision_agents.py` — provisions 5 trading agents with distinct risk profiles for production deployment
- `monitoring/provisioning/datasources/prometheus.yml` — Grafana auto-provisioned datasource (Prometheus, uid `prometheus`)
- `monitoring/provisioning/dashboards/dashboards.yml` — Grafana dashboard loader (serves all JSON from `/var/lib/grafana/dashboards`)
- `Frontend/src/components/battles/*.tsx` — 7 battle UI components (BattleList, BattleDetail, BattleCreateDialog, BattleLeaderboard, BattleReplay, EquityCurveChart, AgentPerformanceCard)
- `Frontend/src/components/dashboard/strategy-attribution-chart.tsx` — bar chart of avg PnL per direction from decisions API
- `Frontend/src/components/dashboard/equity-comparison-chart.tsx` — multi-line Recharts overlay for all non-archived agents
- `Frontend/src/components/dashboard/signal-confidence-histogram.tsx` — histogram of confidence scores in 10 deciles
- `Frontend/src/components/dashboard/active-trade-monitor.tsx` — live PnL per open position, sorted by abs PnL
- `Frontend/src/hooks/use-battles.ts` — TanStack Query hook: list battles, filter by status, create, start, stop
- `Frontend/src/hooks/use-battle-results.ts` — TanStack Query hook: single battle detail, live metrics, results
- `Frontend/src/hooks/use-agent-decisions.ts` — decision analysis hook (direction/confidence/pnl_outcome filters)
- `Frontend/src/hooks/use-agent-equity-comparison.ts` — parallel multi-agent equity history via `useQueries`
- `Frontend/src/app/(dashboard)/battles/page.tsx` — battles list page
- `Frontend/src/app/(dashboard)/battles/[id]/page.tsx` — battle detail/live dashboard page

Modified files:
- `agent/memory/redis_cache.py` — `get_cached()` bug fix (HGET→HGETALL pipeline), `set_working()` 24h TTL
- `agent/logging_middleware.py` — added optional `writer: LogBatchWriter` param
- `agent/server.py` — `LogBatchWriter` singleton (`batch_writer` property), `IntentRouter` with 7 handlers, `WSManager` init/shutdown
- `agent/tools/sdk_tools.py` — added `get_ticker()` and `get_pnl()` tools (count: 13→15)
- `agent/tools/rest_tools.py` — added 5 REST tools (`compare_backtests`, `get_best_backtest`, `get_equity_curve`, `analyze_decisions`, `update_risk_profile`; count: 11→16)
- `agent/trading/loop.py` — WS integration via `ws_manager`, drift detector hookup
- `agent/trading/signal_generator.py` — volume confirmation filter, confidence threshold 0.5→0.55
- `agent/trading/journal.py` — `save_episodic_memory()`, `save_procedural_memory()` for memory-driven learning
- `agent/conversation/context.py` — memory retrieval in context builder, `build_trade_context()`
- `agent/strategies/regime/labeler.py` — `volume_ratio` added as 6th feature
- `agent/strategies/regime/classifier.py` — 6-feature input vector (was 5)
- `agent/strategies/risk/sizing.py` — `KellyFractionalSizer`, `HybridSizer`, `SizingMethod` enum added
- `agent/strategies/risk/risk_agent.py` — `DrawdownProfile`, `DrawdownTier`, 3 presets (AGGRESSIVE/MODERATE/CONSERVATIVE)
- `agent/strategies/risk/veto.py` — `scale_factor` on `VetoDecision`
- `agent/strategies/risk/middleware.py` — correlation gate as step 5 (Pearson r on log-returns)
- `agent/strategies/ensemble/meta_learner.py` — dynamic weights (rolling Sharpe, regime-conditional modifiers), `TradeOutcome`, `apply_attribution_weights()`
- `agent/strategies/ensemble/run.py` — circuit breaker integration, `BacktestValidationReport`, `build_validation_report()`
- `agent/strategies/evolutionary/evolve.py` — OOS composite fitness (5-factor), `walk_forward_evolve()`
- `agent/strategies/evolutionary/config.py` — `oos_split_ratio` field added
- `agent/strategies/rl/config.py` — `composite` reward type + 5 new config fields
- `agent/strategies/rl/train.py` — `CompositeReward` builder
- `agent/strategies/rl/runner.py` — `walk_forward_train()` method
- `agent/config.py` — `signal_confidence_threshold` field added
- `src/utils/exceptions.py` — `PermissionDenied` added as `TradingPlatformError` subclass
- `src/tasks/agent_analytics.py` — `settle_agent_decisions` task added (every 5 min)
- `src/tasks/celery_app.py` — beat schedule 14→15 entries
- `prometheus.yml` — `rule_files:` stanza, `agent:8001` scrape job
- `docker-compose.yml` — Grafana provisioning volume mounts
- `Frontend/src/lib/api-client.ts` — 14 battle API functions + 2 dashboard API functions (getAgentDecisionAnalysis, getAgentEquityHistory)
- `Frontend/src/lib/types.ts` — battle types (15) + dashboard analytics types (5: DecisionItem, DecisionAnalysisResponse, DirectionStats, AgentEquityPoint, AgentEquityHistoryResponse)

**Decisions:**
- `DriftDetector` uses Page-Hinkley test (not CUSUM) — simpler, single hyperparameter (`delta=0.1`, `threshold=50.0`), and well-suited for trading return streams
- `RetrainOrchestrator` uses A/B gate on all deployments — minimum improvement threshold (`min_improvement=0.01`) prevents deploying marginally worse retrained models
- Battle frontend uses 7 components (not 9 as initially planned) — `BattleCard` and `BattleStatusBadge` were absorbed into `BattleList` and `BattleLeaderboard` respectively after UI review
- `settle_agent_decisions` runs every 5 min (not 1 min) — balances latency vs DB load for decision resolution

**Learnings:**
- `monitoring/provisioning/` mount must map to `/etc/grafana/provisioning/` in docker-compose (not `/var/lib/grafana/provisioning/`) — Grafana reads provisioning from `/etc/grafana/provisioning/` at startup
- Page-Hinkley test requires log-transformed returns (not raw price deltas) to be stationary — always transform before feeding to `DriftDetector`
- `AttributionLoader` requires `period="attribution"` on `AgentPerformance` rows — this is written by the `agent_strategy_attribution` Celery task, not by the trading loop directly

---

### 2026-03-22 — Task 29 Walk-Forward Validation Complete (94 New Tests)

**Changes:**

- `agent/strategies/walk_forward.py` — New shared module (1100+ lines). `WalkForwardConfig` (Pydantic BaseSettings, env prefix `WF_`), `WindowResult` / `WalkForwardResult` (frozen Pydantic models), `generate_windows()` (calendar-aware rolling splits with end-of-month clamping), `compute_wfe()` (OOS/IS ratio, `None` on zero denominator), `run_walk_forward()` (async orchestrator with per-window error isolation and JSON report persistence), `walk_forward_rl()` (SB3 integration via `asyncio.to_thread`), `walk_forward_evolutionary()` (GA integration with `_create_evo_battle_runner()` factory for test seam), CLI entry point.
- `agent/strategies/rl/runner.py` — Added `walk_forward_train()` synchronous method to `TrainingRunner`. Uses `asyncio.run()` to call `walk_forward_rl()`. Defaults dates from `config.train_start` / `config.test_end`.
- `agent/strategies/evolutionary/evolve.py` — Added `walk_forward_evolve()` async function. Thin wrapper around `walk_forward_evolutionary()`.
- `agent/tests/test_walk_forward.py` — 94 new tests across 11 test classes covering window splitting, WFE computation, config validation, frozen models, run orchestration, RL/evolutionary integrations, and `TrainingRunner` method.
- `agent/strategies/CLAUDE.md` — Updated: `walk_forward.py` added to sub-package table, Task 29 in Recent Changes.

**Key design decisions:**
- WFE < 50% → `is_deployable=False` + `overfit_warning=True` in `WalkForwardResult`
- Named factory `_create_evo_battle_runner()` is the single test seam for BattleRunner auth
- `asyncio.to_thread` wraps SB3 synchronous training (CPU-bound, incompatible with async)
- `structlog.get_logger(__name__)` called at module level — no `configure_agent_logging()` to avoid `PrintLogger.name` failure in tests

### 2026-03-22 — Trading Agent Master Plan Tasks 21-22, 24, 26-27, 30, 32-37 Complete (13 Tasks, 289 New Tests)

**Changes:**

Phase 2 completion:
- `agent/strategies/risk/recovery.py` — New `RecoveryManager` class: 3-state FSM (RECOVERING → SCALING_UP → FULL), Redis persistence, ATR normalization for HALT trigger, configurable ramp schedule. 53 tests. (Task 21)
- Security review (Task 22): 0 CRITICAL, 0 HIGH found. 2 MEDIUM deferred: 1) `StrategyCircuitBreaker` failure mode for Redis OOM, 2) `DrawdownProfile` threshold validation gap. All risk gates confirmed fail-closed.

Phase 3 (Intelligence):
- `agent/tools/sdk_tools.py` — Added `get_ticker()` (24h volume/high/low/change) and `get_pnl()` (session PnL) tools. Tool count: 13 → 15. 35 new tests. (Task 24)
- `agent/trading/signal_generator.py` — Volume confirmation filter: signals below `volume_confirmation_threshold` (default 0.8 of 20-period SMA) are suppressed. Confidence threshold raised from 0.5 to 0.55. (Task 24)
- `agent/trading/pair_selector.py` — New `PairSelector`: fetches 24h tickers, ranks by volume, filters minimum $10M daily volume and max 5% spread, caches pair universe 1h in Redis, rotates weekly. 42 tests. (Task 26)
- `agent/trading/ws_manager.py` — New `WSManager`: subscribes `AgentExchangeWS` to ticker and order channels for active pairs, maintains price buffer, handles fill notifications, REST fallback on WS disconnect. 46 tests. (Task 27)

Phase 4 (Continuous Learning):
- `agent/tasks.py` — Added `settle_agent_decisions` Celery beat task (every 5 min): finds unresolved decisions via `AgentDecisionRepository.find_unresolved()`, checks order fill status, calls `update_outcome(decision_id, outcome_pnl)`. 16 tests. (Task 30)
- `agent/trading/journal.py` — `generate_reflection()` now saves EPISODIC and PROCEDURAL memories after each trade; retrieves top-5 PROCEDURAL memories for symbol/regime and includes in LLM prompt. 29 tests. (Task 32)
- `agent/memory/retrieval.py` — `MemoryRetriever.retrieve_targeted()` added: retrieves by `memory_type` + `tags` for targeted procedural/episodic retrieval. (Task 32)

Phase 5 (Platform Improvements):
- `agent/tools/rest_tools.py` — 5 new REST tools: `compare_backtests`, `get_best_backtest`, `get_equity_curve`, `analyze_decisions`, `update_risk_profile`. 24 new tests. (Task 33)
- `Frontend/src/components/battles/` — 9 new components: `BattleList`, `BattleCard`, `BattleDetail`, `BattleCreateForm`, `BattleLeaderboard`, `BattleParticipantRow`, `BattleStatusBadge`, `BattleTimeline`, `BattleResultsChart`. 3 routes added. 2 hooks: `useBattles`, `useBattleDetail`. 14 API functions in `api-client.ts`. 15 TypeScript types in `types.ts`. (Task 34)
- `Frontend/src/components/agents/` — 4 new dashboard components: `StrategyAttributionCard`, `EquityComparisonChart`, `ConfidenceHistogram`, `TradeMonitorTable`. 2 new hooks: `useStrategyAttribution`, `useAgentDecisions`. (Task 35)

Phase 6 (Monitoring & Hardening):
- `monitoring/prometheus.yml` — Fixed scrape config: added `agent:8001` job alongside `platform:8000`. Alert rules loading validated. Grafana auto-provisioning confirmed. (Task 36)
- Performance audit findings (Task 37): 2 HIGH — `ContextBuilder.build()` makes fresh network calls on every invocation (fix: add 30s cache for portfolio state); `WSManager` subscribes to all 600+ pairs instead of filtered pair universe (fix: wire `PairSelector` output). 3 MEDIUM — batch API calls for price fetches; add circuit breaker for REST fallback in `WSManager`; memory retrieval does full table scan without index. 1 LOW — `EnsembleRunner` re-instantiates `MetaLearner` on each step.

**Decisions:**
- `RecoveryManager` uses ATR normalization to determine HALT resumption (not a fixed time delay) — prevents resuming during a volatility spike that caused the halt; ATR returning to < 1.5x median is an objective condition, not an arbitrary wait.
- Memory-driven learning uses `targeted retrieval` by type + tags rather than semantic search — procedural memories for a specific symbol/regime are structurally tagged; semantic search would surface irrelevant memories from other contexts.
- `PairSelector` 1h cache instead of per-tick refresh — 24h volume rankings are stable at 1-minute granularity; refreshing every tick would hammer the market API with 600+ ticker fetches.
- Battle frontend built as standalone route group, not embedded in the agent dashboard — battles involve multiple agents and the UI needs to support creation, live monitoring, and replay independently of a single agent context.
- `settle_agent_decisions` Celery task runs every 5 minutes (not on trade fill) — decouples the learning feedback loop from the hot execution path; order fills can be delayed and async settlement is more resilient.

**Bugs fixed:**
- Prometheus scrape config only targeted `:8000` (platform) — agent metrics on `:8001` were never scraped; fixed by adding dedicated `agent` job in `monitoring/prometheus.yml`.
- `ContextBuilder.build()` created a new HTTP client on every call — root cause: no connection pooling or caching; identified as HIGH perf issue in Task 37 audit; not yet fixed (fix is Task 37 follow-up).

**Learnings:**
- `RecoveryManager` state must be Redis-persisted (not in-process memory) — a service restart during recovery would reset to FULL state, bypassing the ramp-up schedule and potentially re-exposing full risk immediately after a drawdown.
- Volume confirmation filter should use 20-period SMA of volume (not absolute volume) — absolute volume varies wildly across pairs (BTC vs altcoins by 100x); SMA-relative comparison is asset-agnostic.
- Security review found all risk gates are fail-closed — the 2 MEDIUM findings are edge cases (Redis OOM, misconfigured DrawdownProfile), not architectural gaps. The fail-closed default was explicitly validated.

---

### 2026-03-22 — Trading Agent Master Plan Phase 1 Branch + Phase 2 Independent Tasks Complete (8 Tasks, 361 New Tests)

**Changes:**

Phase 1 branch starts:
- `agent/strategies/regime/labeler.py` — Added `_volume_ratio_series()` helper and `volume_ratio` (current_volume / SMA(volume,20)) as the 6th classifier feature; corrects for regime detection bias in low-volume markets.
- `agent/strategies/regime/classifier.py` — Updated `FEATURE_NAMES` from 5 → 6 entries; added missing `_print_evaluation()` function (was referenced in tests but not defined). 17 new tests; 189 total regime tests passing.
- `tradeready-gym/tradeready_gym/rewards/composite.py` — New `CompositeReward` class implementing weighted Sortino/PnL/activity/drawdown reward; allows per-component weight tuning without rewriting the env.
- `agent/strategies/rl/config.py` — Added `"composite"` to valid `reward_type` enum. Added 5 composite-specific config fields: `composite_sortino_weight`, `composite_pnl_weight`, `composite_activity_weight`, `composite_drawdown_weight`, `composite_activity_bonus`.
- `agent/strategies/rl/train.py` — Added `"composite"` case to `_build_reward()` dispatcher; instantiates `CompositeReward` with weights from config. 41 new tests.
- `agent/strategies/evolutionary/evolve.py` — Added `compute_composite_fitness()` with 5-factor formula (0.35 × Sharpe + 0.25 × profit_factor − 0.20 × max_drawdown + 0.10 × win_rate + 0.10 × OOS Sharpe); dual IS/OOS battle loop; OOS-aware `ConvergenceDetector`.
- `agent/strategies/evolutionary/config.py` — Added `oos_split_ratio` field (default 0.30); `is_split`, `in_sample_window`, `oos_window` properties. `fitness_fn` default changed from `sharpe_minus_drawdown` to `composite`.
- `agent/strategies/evolutionary/battle_runner.py` — Added `get_detailed_metrics()` returning full 5-metric dict per agent (sharpe, drawdown, profit_factor, win_rate, roi_pct). 57 new tests.

Phase 2 risk hardening:
- `agent/strategies/risk/sizing.py` — Added `KellyFractionalSizer` (Kelly criterion with safety fraction and win/loss stats), `HybridSizer` (blends Kelly and volatility-adjusted sizing), and `SizingMethod` enum. 67 new tests; 93 total sizing tests.
- `agent/strategies/risk/risk_agent.py` — Added `DrawdownProfile`, `DrawdownTier` dataclasses and 3 preset profiles (`AGGRESSIVE`, `MODERATE`, `CONSERVATIVE`). `RiskAgent` now accepts a `DrawdownProfile` for tiered size reduction as drawdown deepens. 67 new tests.
- `agent/strategies/risk/veto.py` — Added `scale_factor` field to `VetoDecision` to expose the cumulative size scaling applied across all RESIZED gates.
- `agent/strategies/risk/middleware.py` — Added `_check_correlation()` as step 5 in the `RiskMiddleware` pipeline: fetches 1h candles concurrently via `asyncio.gather`, computes Pearson r on log-returns, reduces size when `max(|r|) > 0.70`, caps correlated exposure at `2 × max_single_position`. 32 new tests; 59 total middleware tests.
- `agent/strategies/ensemble/circuit_breaker.py` — New `StrategyCircuitBreaker`: 3 trigger rules (3 consecutive losses → 24h Redis pause, weekly PnL < −5% → 48h pause, ensemble accuracy < 40% → 25% size reduction). All state is Redis-backed with TTL auto-expiry; all methods async and fail-open on Redis errors. 56 new tests.
- `agent/strategies/ensemble/run.py` — `EnsembleRunner.__init__()` now accepts optional `circuit_breaker: StrategyCircuitBreaker`; `step()` checks paused sources (stage 0) and applies size multiplier after `MetaLearner` (stage 3b).
- `agent/tools/sdk_tools.py` — Added 6 new tools: `place_limit_order`, `place_stop_loss`, `place_take_profit`, `cancel_order`, `cancel_all_orders`, `get_open_orders`. Added `_serialize_order()` module-level helper. Tool count: 7 → 13. 24 new tests; 48 total SDK tools tests.

Quality pipeline:
- Code review: PASS WITH WARNINGS (no criticals; 4 minor warnings).
- Test runner: fixed 1 import bug in `RiskMiddleware` (importing `SizingMethod` before it was added to `sizing.py`); all 539/539 new tests pass.

**Decisions:**
- `volume_ratio` added as 6th regime feature — ADX/ATR/RSI/MACD alone miss low-volume regime transitions; volume normalisation reveals institutional participation shifts.
- `CompositeReward` as a separate class in `tradeready-gym/` (not inline in train.py) — keeps the gymnasium env boundary clean; allows the same reward to be used in future environments without duplicating logic.
- OOS fitness in evolutionary GA uses a separate held-out battle window (30% split) rather than train-set Sharpe — prevents overfitting to the in-sample period; `ConvergenceDetector` now tracks OOS Sharpe as the primary stopping criterion.
- `DrawdownProfile` with preset tiers (`AGGRESSIVE`/`MODERATE`/`CONSERVATIVE`) rather than free-form config fields — presets are tested and documented; prevents misconfigured thresholds from creating dangerous step-down schedules.
- `StrategyCircuitBreaker` Redis-backed with TTL — pause state survives service restarts; TTL auto-expiry means no cron job is needed to reset pauses.
- Kelly/Hybrid sizing separate from existing `DynamicSizer` — Kelly has different input requirements (win rate, W/L ratio) that are not available at volatility-sizing time; keeping them as distinct classes lets callers choose based on available data.

**Bugs fixed:**
- `agent/strategies/risk/middleware.py` imported `SizingMethod` from `sizing.py` before the enum was defined — root cause: circular refactor during Task 16; fix: moved import after enum definition and added `SizingMethod` to `__init__.py`.
- `agent/strategies/regime/classifier.py` referenced `_print_evaluation()` in 3 test files but the function was never defined in the module — root cause: function was sketched during initial implementation and never fleshed out; fix: added the function in Task 08.

**Learnings:**
- Pearson r on linearly-growing prices is near zero — log-returns of linear trends have nearly constant values (low variance), making Pearson r numerically noisy. Test fixtures that need high correlation must use shared random shocks, not synthetic price levels.
- `StrategyCircuitBreaker.ensemble_accuracy()` returns `None` (not 0.0) when the accuracy window has fewer than 20 observations — callers must guard against `None` before comparing to a threshold.

---

### 2026-03-22 — Trading Agent Master Plan Phase 0 Group A Complete (5 Tasks)

**Changes:**
- `agent/memory/redis_cache.py` — Fixed broken `get_cached()` glob pattern (`agent:memory:*:{memory_id}` always returned None); now requires `agent_id` parameter and delegates to `get_cached_for_agent()`. Also: `set_working()` now uses atomic pipeline with `hset + expire(86400)` for 24h TTL crash safety.
- `agent/logging_middleware.py` — `log_api_call()` accepts optional `writer: LogBatchWriter` parameter; calls `writer.add_api_call()` on both success and failure paths.
- `agent/server.py` — `LogBatchWriter` instantiated as a singleton; `batch_writer` property exposed; lifecycle managed (start in `_init_dependencies()`, stop in `_shutdown()`). `IntentRouter` registered with all 7 handlers in `__init__()`, `process_message()` routes through router first.
- `agent/server_handlers.py` — New file: 7 async handler functions (trade, analyze, portfolio, status, journal, learn, permissions) + `REASONING_LOOP_SENTINEL` for general fallback routing.
- `src/utils/exceptions.py` — Added `PermissionDenied(TradingPlatformError)` with `code="permission_denied"`, `http_status=403`. Now auto-serialized by global exception handler.
- `agent/permissions/enforcement.py` — Imports `PermissionDenied` from `src/utils/exceptions` instead of defining it locally; removes the local definition.
- `agent/tests/test_redis_memory_cache.py` — 4 new tests in `TestGetCached` class; updated pipeline mock to verify TTL.
- `agent/tests/test_server_writer_wiring.py` — New file, 20 tests for `LogBatchWriter` singleton wiring in `AgentServer`.
- `agent/tests/test_server_handlers.py` — New file, 54 tests for 7 intent handler functions.
- `tests/unit/test_exceptions.py` — 8 new tests for `PermissionDenied` exception.
- `tests/unit/test_permission_enforcement.py` — 10 new tests for updated import path.

**Decisions:**
- `PermissionDenied` promoted from a locally-defined exception in `agent/permissions/enforcement.py` to a proper `TradingPlatformError` subclass in `src/utils/exceptions.py`. This makes it auto-serializable by the global exception handler and consistent with the platform's error envelope pattern.
- `get_cached()` now requires `agent_id` — the old glob pattern `agent:memory:*:{memory_id}` is not supported by Redis and always returns None. Callers must know the `agent_id` to look up a cached memory.

**Bugs fixed:**
- `RedisMemoryCache.get_cached()` glob pattern always returned None → root cause: Redis does not support glob patterns in `get()`; the key pattern requires both `agent_id` and `memory_id` → fix: added required `agent_id` parameter and delegated to the existing `get_cached_for_agent()` method.
- `set_working()` had no TTL → root cause: Redis hash had no expiry, so a mid-session crash left stale working memory in Redis indefinitely → fix: atomic `hset + expire(86400)` pipeline sets a 24h TTL.

**Decisions:**
- Migrations 018 and 019 validated as safe (PASS). Advisory noted: document downgrade data risk for migration 019 before production rollback (status/resolution columns are additive but downgrade drops them).

---

### 2026-03-21 — MILESTONE: Agent Logging System Complete (34 Tasks, 5 Phases)

**What was built:**
Full observability stack for the agent ecosystem: distributed trace correlation across all agent operations, Prometheus metrics, async batched DB persistence, Grafana dashboards, and Prometheus alert rules.

**Changes:**

New agent infrastructure files:
- `agent/logging.py` — `configure_agent_logging()`: centralized structlog config with ISO timestamps, JSON output, and structlog-contextvars context (trace_id, span_id, agent_id). Call once at startup.
- `agent/logging_middleware.py` — `log_api_call()` async context manager: wraps every tool call with structured logging, latency measurement, and LLM token/cost estimation. `set_agent_id()` binds agent context.
- `agent/logging_writer.py` — `LogBatchWriter`: accumulates `AgentApiCall` rows in-memory, flushes to DB in batches (configurable size/interval). Used by `trading/loop.py` and `strategies/ensemble/run.py`.
- `agent/metrics.py` — 16 Prometheus metrics in `AGENT_REGISTRY` (separate from platform registry): API call counters/histograms, LLM cost gauges, memory hit/miss counters, permission denial counters, budget utilization gauges, strategy signal counters.
- `agent/server.py` — Added `/metrics` endpoint via `asyncio.start_server`; `set_agent_id()` helper.

Modified agent files (structlog migration + instrumentation):
- `agent/main.py` — Calls `configure_agent_logging()` at startup.
- `agent/tasks.py` — Migrated to structlog; calls `configure_agent_logging()`.
- `agent/tools/sdk_tools.py` — Wraps all 7 tool functions with `log_api_call()`; passes `get_trace_id` as `trace_id_provider` to `AsyncAgentExchangeClient`.
- `agent/tools/rest_tools.py` — Wraps tool functions; injects `X-Trace-Id` header on every outbound request.
- `agent/tools/agent_tools.py` — Wraps tool functions with `log_api_call()`.
- `agent/conversation/session.py` — LLM calls wrapped with `log_api_call()` for cost tracking.
- `agent/trading/loop.py` — Generates fresh `trace_id` per tick; passes to `LogBatchWriter`; EMA-based anomaly detection on tick latency.
- `agent/trading/journal.py` — LLM reflection calls wrapped with `log_api_call()`.
- `agent/memory/postgres_store.py` — Logs all memory operations; increments `memory_operations_total` counter.
- `agent/memory/redis_cache.py` — Records cache hit/miss via `memory_cache_hits_total`/`memory_cache_misses_total`.
- `agent/memory/retrieval.py` — Logs retrieval latency and result count.
- `agent/permissions/enforcement.py` — Increments `permission_denials_total` on every `PermissionDenied` event.
- `agent/permissions/budget.py` — Emits `budget_usage_ratio` gauge on each check.
- `agent/strategies/ensemble/run.py` — Writes `AgentStrategySignal` rows per step via `LogBatchWriter`.
- `agent/strategies/rl/*.py` (5 files) — All call `configure_agent_logging()` at startup.
- `agent/strategies/evolutionary/*.py` (2 files) — Migrated to `configure_agent_logging()`.
- `agent/strategies/ensemble/*.py` (3 files) — Migrated; standardized event names.
- `agent/strategies/regime/*.py` (2 files) — Standardized event names.
- `agent/pyproject.toml` — Added `prometheus-client>=0.20` to dependencies.
- `sdk/agentexchange/async_client.py` — Added `trace_id_provider: Callable[[], str] | None` to inject `X-Trace-Id` header on every outbound request.

New backend files:
- `src/api/middleware/audit.py` — `AuditMiddleware`: fire-and-forget middleware that writes request metadata to `audit_log` table; registered after other middleware in `src/main.py`.
- `src/monitoring/metrics.py` — 4 platform Prometheus metrics: `platform_orders_total`, `platform_order_latency_seconds`, `platform_api_errors_total`, `platform_price_ingestion_lag_seconds`.
- `src/database/repositories/agent_api_call_repo.py` — `AgentApiCallRepository`: bulk save + analytics queries.
- `src/database/repositories/agent_strategy_signal_repo.py` — `AgentStrategySignalRepository`: bulk save + attribution queries.
- `src/tasks/agent_analytics.py` — 3 Celery tasks: `agent_strategy_attribution` (daily 02:00 UTC), `agent_memory_effectiveness` (weekly Sunday 03:00 UTC), `agent_platform_health_report` (daily 06:00 UTC).
- `alembic/versions/018_add_agent_logging_tables.py` — `agent_api_calls` table, `agent_strategy_signals` table, `trace_id` column on `agent_decisions`.
- `alembic/versions/019_add_feedback_lifecycle_columns.py` — `status` CHECK constraint + default, `resolution` column on `agent_feedback`.
- `monitoring/alerts/agent-alerts.yml` — 11 Prometheus alert rules.
- `monitoring/dashboards/*.json` — 6 Grafana dashboard definitions.

Modified backend files:
- `src/api/routes/agents.py` — 3 new endpoints: `GET /decisions/trace/{trace_id}`, `GET /decisions/analyze`, `PATCH /feedback/{feedback_id}`.
- `src/api/schemas/agents.py` — 8+ new Pydantic schemas for trace/analyze/feedback endpoints.
- `src/api/middleware/logging.py` — Extracts `X-Trace-Id`; increments `platform_api_errors_total` on 4xx/5xx.
- `src/database/models.py` — `AgentApiCall`, `AgentStrategySignal` models; `trace_id` on `AgentDecision`; `status`/`resolution` on `AgentFeedback`.
- `src/dependencies.py` — 3 new dependency aliases: `AgentApiCallRepoDep`, `AgentStrategySignalRepoDep`, etc.
- `src/main.py` — `AuditMiddleware` registered.
- `src/order_engine/engine.py` — Instruments `platform_orders_total` counter and `platform_order_latency_seconds` histogram.
- `src/price_ingestion/service.py` — Updates `platform_price_ingestion_lag_seconds` gauge.
- `src/tasks/celery_app.py` — 3 new beat schedule entries (02:00, 03:00 Sunday, 06:00 UTC).

New tests:
- `agent/tests/test_logging.py` — 25 tests for `configure_agent_logging()` and structlog context.
- `agent/tests/test_logging_middleware.py` — 24 tests for `log_api_call()` and LLM cost estimator.
- `agent/tests/test_logging_writer.py` — 17 tests for `LogBatchWriter` async batching.
- `tests/unit/test_agent_api_call_repo.py` — 9 tests for `AgentApiCallRepository`.
- `tests/unit/test_agent_strategy_signal_repo.py` — 10 tests for `AgentStrategySignalRepository`.

**Decisions:**
- Separate `AGENT_REGISTRY` from platform's default Prometheus registry — agent and platform metrics are served on different ports; mixing them would require all consumers to filter by prefix.
- `LogBatchWriter` over per-call DB inserts — agent tools fire on every LLM/SDK call (potentially hundreds per minute); synchronous per-call inserts would add latency to the hot path.
- EMA anomaly detection in `TradingLoop` — lightweight stateful detection without a separate ML model; detects tick latency spikes that correlate with connectivity degradation.
- `AuditMiddleware` is fire-and-forget — audit logging must never block a request; a failed DB write is logged but the request proceeds.
- `trace_id` on `AgentDecision` (not a separate table) — decision rows already exist per trading action; adding a column is additive (migration 018) and enables trace→decision lookup without a join.

**Learnings:**
- `configure_agent_logging()` must be called before any structlog event is emitted — if called after the first log, context vars may be unbound.
- `LogBatchWriter.flush()` should be called explicitly on shutdown — the background flush task may have unflushed rows when the event loop closes.
- Prometheus `AGENT_REGISTRY` must use `registry=AGENT_REGISTRY` on every `Counter`/`Histogram`/`Gauge` definition — omitting it registers to the default registry and appears at the platform's `/metrics` instead.

---

### 2026-03-21 — MILESTONE: Agent Memory & Learning System Complete (14 Tasks)

**What was built:**
Persistent cross-session memory and activity monitoring for the entire 16-agent sub-agent fleet. Three phases: native memory expansion, structured activity logging, and feedback capture loop.

**Changes:**

Phase 1 — Native Memory Expansion:
- `.claude/agents/*.md` (all 16) — Added `memory: project` frontmatter field; each agent now reads and writes its own MEMORY.md at `.claude/agent-memory/{agent-name}/`.
- `.claude/agent-memory/{16 agent dirs}/MEMORY.md` — Created and seeded: each file pre-loaded with project-specific patterns, conventions, gotchas relevant to that agent's role. Organized by category (quality gate, security, infrastructure, development, research/planning).
- `.claude/agents/*.md` (all 16) — Added Memory Protocol section to all system prompts: read MEMORY.md on entry, save new learnings on exit, prune stale entries periodically.
- `.gitignore` — Added `agent-memory-local/` exclusion for personal memory overrides that should not be shared.

Phase 2 — Structured Activity Logging:
- `scripts/log-agent-activity.sh` — New: PostToolUse hook script. Appends `{ts, tool, target}` JSONL to `development/agent-activity-log.jsonl`. Pure-bash fallback when `jq` unavailable. Always exits 0.
- `scripts/agent-run-summary.sh` — New: activity summary script. Reads JSONL log, outputs tool frequency, file heatmap, activity by day. Accepts `--days N` argument.
- `scripts/analyze-agent-metrics.sh` — New: deep analysis script (requires `jq`). Generates tool histogram, file heatmap, hourly activity distribution. Called by `/analyze-agents` skill.
- `.claude/settings.json` — Added second PostToolUse hook entry: `Write|Edit|Bash` tool calls trigger `bash scripts/log-agent-activity.sh` (timeout 5s, non-blocking).

Phase 3 — Feedback Loop:
- `.claude/skills/analyze-agents/SKILL.md` — New: `/analyze-agents` skill reads activity log + all agent MEMORY.md files + code review reports; generates improvement report at `development/agent-analysis/report-{date}.md`; applies quick memory fixes.
- `.claude/skills/review-changes/SKILL.md` — Updated: added explicit feedback capture step after code-reviewer runs — saves recurring patterns to agent MEMORY.md files.

Supporting files:
- `development/agent-memory-strategy-report.md` — Research report: evaluation of memory strategies for the agent fleet.
- `development/tasks/agent-memory-system/` — 14-task board (all done): task files for each of the 14 tasks, README, run-tasks.md.

**Decisions:**
- File-based memory (MEMORY.md) over DB-backed memory — simpler, version-controlled (shared via git), no schema migration required; sufficient for the agent fleet's inter-session learning needs.
- Per-agent subdirectory isolation — each agent only reads its own MEMORY.md on startup, preventing cross-agent memory contamination.
- PostToolUse hook is non-blocking (exit 0 always, 5s timeout) — activity logging must never block agent execution; a broken JSONL log is preferable to a stalled agent.
- `/analyze-agents` reads the JSONL log to generate suggestions — pattern-driven recommendations rather than manual review; agents improve based on actual usage data.

---

### 2026-03-21 — MILESTONE: Agent Ecosystem Phase 2 Complete (Tasks 21-36)

**What was built:**
Trading intelligence layer on top of the Phase 1 conversation/memory/tool foundation. Adds permissions enforcement, budget management, and a full 7-step autonomous trading loop with A/B testing, journaling, and degradation-aware strategy management.

**Changes:**

Permissions system (`agent/permissions/`):
- `permissions/roles.py` — `AgentRole` enum with `ROLE_HIERARCHY` and `ROLE_CAPABILITIES` mappings; helper functions `get_role_capabilities()`, `has_role_or_higher()`, `promote_role()`.
- `permissions/capabilities.py` — `Capability` enum (24 fine-grained capabilities), `ALL_CAPABILITIES` set, `CapabilityManager` with role-capability intersection checks.
- `permissions/budget.py` — `BudgetManager`: Redis-backed daily trade count, volume, and drawdown limits per agent; automatic midnight TTL expiry.
- `permissions/enforcement.py` — `PermissionEnforcer`: action-to-capability mapping (`ACTION_CAPABILITY_MAP`), `check()` method that verifies role + capability + budget; raises `PermissionDenied` with audit trail; fail-closed on unknown capabilities.

Security review (critical fixes applied before merge):
- `permissions/budget.py` — Fixed float precision in budget comparison: `Decimal(str(amount))` instead of raw `float` to prevent rounding bypass near budget limits.
- `permissions/enforcement.py` — Fixed TOCTOU race: budget deduction and permission check now done in a single Redis transaction (Lua script) instead of two sequential calls.
- `permissions/enforcement.py` — Fixed fail-open default: unknown capabilities now DENIED by default instead of silently allowed.
- `permissions/roles.py` — Fixed missing default role: agents without a persisted role now default to `READ_ONLY` instead of `AUTONOMOUS`.
- Security report saved at `development/code-reviews/security-review-permissions.md`.

Trading intelligence (`agent/trading/`):
- `trading/loop.py` — `TradingLoop`: 7-step cycle (fetch candles → generate signals → check permissions → execute → monitor → journal → learn); exponential backoff on errors (max 5 min); graceful shutdown on SIGTERM; `LoopStoppedError` for clean teardown.
- `trading/signal_generator.py` — `SignalGenerator`, `TradingSignal`: wraps `EnsembleRunner` from `agent/strategies/ensemble/`; converts ensemble `ConsensusSignal` to typed `TradingSignal` with confidence and metadata.
- `trading/execution.py` — `TradeExecutor`: idempotent execution with UUID4 idempotency key; 3-attempt retry with 500ms backoff; budget check via `PermissionEnforcer` before every execution.
- `trading/monitor.py` — `PositionMonitor`: per-position stop-loss / take-profit / max-hold-duration exit triggers; configurable thresholds; fires async callbacks on trigger.
- `trading/journal.py` — `TradingJournal`: records every execution decision with context; `reflect_on_trade()` calls LLM for post-trade reflection; `daily_summary()` and `weekly_summary()` aggregate patterns; persists to `agent_journal` table via `AgentJournalRepo`.
- `trading/strategy_manager.py` — `StrategyManager`: rolling 30-step performance window per strategy; `detect_degradation()` compares recent vs historical Sharpe; `adjust_weights()` demotes degraded strategies; `promote_strategy()` runs A/B test before promotion.
- `trading/ab_testing.py` — `ABTestRunner`, `ABTest`: runs two strategy arms simultaneously in a backtest session; Welch's t-test evaluation with minimum 10 samples; structured `ABTest` result with winner, p-value, effect size.

Tests (414+ in Phase 2):
- `agent/tests/test_veto.py` — 42 tests for `VetoPipeline` and individual gate logic.
- `agent/tests/test_risk_agent.py` — 39 tests for `RiskAgent` assessment and approval logic.
- `agent/tests/test_risk_middleware.py` — 31 tests for `RiskMiddleware` full pipeline.
- `agent/tests/test_sizing.py` — 26 tests for `DynamicSizer` volatility and drawdown adjustments.
- `agent/tests/test_trade_executor.py` — 19 tests covering idempotency, retry, budget enforcement.
- `agent/tests/test_trading_journal.py` — 33 tests for journal write, LLM reflection, summary.
- `agent/tests/test_trading_loop.py` — 20 tests for loop step cycle, error backoff, shutdown.
- `agent/tests/test_strategy_manager.py` — 81 tests for rolling window, degradation detection, weight adjustment, A/B promotion.
- `agent/tests/test_ensemble_pipeline.py` — 68 tests for full 6-stage ensemble pipeline.
- `agent/tests/test_runner.py` — 46 tests for multi-seed orchestrator.

CLAUDE.md files created/updated:
- `agent/permissions/CLAUDE.md` — New: roles, capabilities, budget limits, enforcement patterns, audit logging.
- `agent/trading/CLAUDE.md` — New: trading loop, signal generator, executor, position monitor, journal, strategy manager, A/B testing.
- `agent/CLAUDE.md` — Updated: added `permissions/` and `trading/` to directory structure and Sub-CLAUDE.md Index.

**Decisions:**
- `PermissionEnforcer` fail-closed by default — unknown capabilities are DENIED, never silently allowed; security review identified this as CRITICAL before merge.
- `BudgetManager` uses Redis with TTL rather than DB rows — avoids DB write on every trade check; Redis TTL naturally resets daily limits at midnight even after service restarts.
- `TradingLoop` is the mandatory entry point for all agent execution — bypassing it skips budget enforcement and audit logging; enforced by convention (no public `TradeExecutor` method outside the loop).
- `StrategyManager` uses a 30-step rolling window for degradation detection — short enough to react to regime changes, long enough to avoid noise triggering false degradations.
- `ABTestRunner` uses Welch's t-test (unequal variance) — real strategy arms almost never have equal variance; Student's t-test would be statistically invalid.

**Bugs fixed (CRITICAL — from security review):**
- Float precision bypass near budget limits — `float` comparison allowed submitting orders 0.0000001 USDT under limit. Fixed: `Decimal(str(amount))` for all budget comparisons.
- TOCTOU race in `PermissionEnforcer.check()` — a check + deduct two-step could allow double-execution under concurrency. Fixed: single Lua script atomically checks and deducts in one Redis call.
- Fail-open on unknown capabilities — missing `ACTION_CAPABILITY_MAP` entries silently allowed execution. Fixed: default is DENIED with audit log entry.
- Default role was `AUTONOMOUS` for unpersisted agents — agents without a DB role record could execute unrestricted trades. Fixed: default is `READ_ONLY`.

---

### 2026-03-21 — MILESTONE: Agent Ecosystem Phase 1 Complete (Tasks 01-20)

**What was built:**
DB foundation and reasoning infrastructure for autonomous agents: persistent memory, conversation tracking, self-reflection tools, server lifecycle management, and a CLI REPL.

**Changes:**

Database layer (`src/database/models.py` + `alembic/versions/017_agent_ecosystem_tables.py`):
- 10 new SQLAlchemy models: `AgentSession`, `AgentMessage`, `AgentDecision`, `AgentJournal`, `AgentLearning`, `AgentFeedback`, `AgentPermission`, `AgentBudget`, `AgentPerformance`, `AgentObservation`.
- `agent_observations` created as TimescaleDB hypertable (high-frequency telemetry; time-partitioned).
- Migration 017 is a pure-additive migration — no destructive ALTER; safe to run on live DB.

Repository classes (`src/database/repositories/`):
- `AgentSessionRepo` — session CRUD, active session lookup by agent_id.
- `AgentMessageRepo` — message append, conversation window retrieval (most-recent-N).
- `AgentDecisionRepo` — decision persistence, recent decisions by session.
- `AgentJournalRepo` — journal entries, date-range queries.
- `AgentLearningRepo` — learning records, search by keyword.
- `AgentFeedbackRepo` — feedback CRUD with rating filter.
- `AgentPermissionRepo` — permission read/write by agent and capability.
- `AgentBudgetRepo` — budget snapshot read/write by agent and period.
- `AgentPerformanceRepo` — performance upsert, range query.
- `AgentObservationRepo` — bulk-insert observations, time-window query.

Pydantic models (`agent/models/ecosystem.py`):
- 19 v2 Pydantic models covering request/response shapes for all 10 tables: `AgentSessionCreate`, `AgentSessionRead`, `AgentMessageCreate`, `AgentMessageRead`, `AgentDecisionCreate`, `AgentDecisionRead`, `AgentJournalCreate`, `AgentJournalRead`, `AgentLearningCreate`, `AgentLearningRead`, `AgentFeedbackCreate`, `AgentFeedbackRead`, `AgentPermissionCreate`, `AgentPermissionRead`, `AgentBudgetCreate`, `AgentBudgetRead`, `AgentPerformanceCreate`, `AgentPerformanceRead`, `AgentObservationCreate`.

Conversation system (`agent/conversation/`):
- `session.py` — `AgentSession`: DB-backed session lifecycle with auto-summarisation when message window exceeds 50; `open()`, `close()`, `add_message()`, `get_context()`.
- `history.py` — `ConversationHistory`, `Message`: read-only window-based access to message history; supports `to_llm_messages()` for direct Pydantic AI injection.
- `context.py` — `ContextBuilder`: assembles 6-section LLM context (system prompt + session summary + recent history + memory excerpts + platform state + task description).
- `router.py` — `IntentRouter`, `IntentType`: 3-layer classification (keyword → regex → LLM fallback); routes to TRADE, ANALYZE, REFLECT, JOURNAL, ADMIN, UNKNOWN.

Memory system (`agent/memory/`):
- `store.py` — `MemoryStore` (abstract), `Memory` model, `MemoryType` (SHORT_TERM/LONG_TERM/WORKING/EPISODIC), `MemoryNotFoundError`.
- `postgres_store.py` — `PostgresMemoryStore`: durable write-through to `agent_learnings` table; full-text search via `ILIKE`; metadata JSON filtering.
- `redis_cache.py` — `RedisMemoryCache`: hot cache for working memory and regime/signal state; TTL-based expiry; `get_working_memory()` for current-session context.
- `retrieval.py` — `MemoryRetriever`, `RetrievalResult`: two-phase retrieval (Redis hot cache first, Postgres fallback); relevance scoring by recency + keyword overlap; returns scored list.

Agent tools (`agent/tools/agent_tools.py`):
- `reflect_on_trade(trade_id, outcome)` — retrieves trade context, calls LLM for reflection, persists to `agent_journal`.
- `review_portfolio(period)` — fetches portfolio metrics, identifies patterns vs memory, returns structured analysis.
- `scan_opportunities(symbols, timeframe)` — fetches candles for symbols, runs regime classifier, surfaces regime-appropriate opportunities.
- `journal_entry(content, tags)` — persists a free-form journal entry with tags to `agent_journal`.
- `request_platform_feature(description, rationale)` — persists a structured feature request to `agent_feedback` with SUGGESTION type.

Server + tasks:
- `agent/server.py` — `AgentServer`: lifecycle management (`startup()`, `shutdown()`), SIGTERM/SIGINT handlers, periodic health checks (60s), scheduled task registration.
- `agent/tasks.py` — 4 Celery beat tasks: `morning_review` (07:00 daily), `reset_daily_budgets` (midnight), `cleanup_old_memories` (weekly), `take_performance_snapshot` (hourly).
- `agent/cli.py` — Interactive REPL with `prompt_toolkit` and `rich` formatting; 10 slash commands: `/help`, `/status`, `/session`, `/memory`, `/journal`, `/reflect`, `/permissions`, `/budget`, `/trade`, `/quit`.
- `agent/config.py` — 22 configuration fields covering API credentials, session/memory settings, budget defaults, trading loop parameters, Celery broker URL.

Tests (370+):
- `agent/tests/test_memory_store.py` — 22 tests for abstract store, Memory model, MemoryType.
- `agent/tests/test_memory_retrieval.py` — 31 tests for two-phase retrieval, scoring, fallback.
- `agent/tests/test_redis_memory_cache.py` — 25 tests for hot cache, TTL, working memory.
- `agent/tests/test_rl_pipeline.py` — 35 tests for RL train/eval/deploy pipeline.
- (plus existing strategy tests from prior phases: 578 tests across 5 sub-packages)

**Decisions:**
- `agent_observations` as a TimescaleDB hypertable — agent telemetry (price observations, portfolio snapshots, signal recordings) is high-frequency and time-ordered; native time-series partitioning reduces query latency for lookback windows.
- Auto-summarisation at 50 messages — long context windows are expensive and degrade LLM coherence; summarisation at 50 captures the arc without token waste; summary stored in session record.
- Two-phase memory retrieval (Redis → Postgres) — working memory hot path hits Redis in <1ms; only cache misses hit Postgres; memory store is transparent to callers.
- `IntentRouter` uses 3-layer fallback (keyword → regex → LLM) — most intents resolved without LLM call (fast + no token cost); LLM fallback handles ambiguous natural-language input that keyword/regex cannot classify.

---

### 2026-03-20 — CLAUDE.md Sync + New Development Docs

**Changes:**
- `src/api/middleware/rate_limit.py` — Added `backtest` (6000 req/min) and `training` (3000 req/min) rate limit tiers; allows the high-frequency step/batch calls in backtesting and episode reporting during training.
- `src/utils/helpers.py` — Added `parse_interval(interval: str | int) -> int` utility; normalises candle interval to seconds, accepting `"1h"`, `"5m"`, raw integers, and string integers. Used by `backtest.py` create endpoint.
- `src/api/routes/backtest.py` — Backtest create endpoint now accepts string interval shorthand via `parse_interval()`; previously only accepted raw integer seconds.
- `agent/pyproject.toml` — Added `[ml]` optional group (stable-baselines3, torch, xgboost, scikit-learn, joblib, numpy, pandas) and `[all]` meta-group; core package remains pip-installable without 1.5 GB ML deps.
- `agent/Dockerfile` — New: python:3.12-slim, 3-layer build (system deps → Python deps → app code), non-root user.
- `docker-compose.yml` — Added `agent` service under `--profile agent` so it does not start during normal `docker compose up -d`.
- `agent/strategies/checksum.py` — New: SHA-256 checksum generation and verification (`compute_checksum`, `save_checksum`, `verify_checksum`, `SecurityError`) for `.zip` and `.joblib` model files.
- `agent/strategies/rl/train.py`, `rl/evaluate.py` — Integrated checksum write-on-save and verify-on-load; eliminates pickle-based code execution risk for local model files.
- `agent/strategies/*/battle_runner.py`, `data_prep.py`, `ensemble/run.py` — Replaced sequential awaits with `asyncio.gather()` at 6 locations; removed latency bottleneck on battles with 5+ participants.
- `agent/strategies/rl/deploy.py`, `regime/classifier.py` — Wrapped `model.predict()` and `classifier.fit()` in `asyncio.to_thread()` to unblock event loop during numpy/sklearn C-extension calls.
- `agent/strategies/rl/deploy.py`, `ensemble/run.py` — Capped `step_history` and `regime_history` deques to prevent unbounded memory growth.
- `agent/strategies/regime/switcher.py` — Added in-memory regime detection cache; avoids re-running classifier on identical candle windows within the same step.
- 10 CLI scripts across `agent/strategies/` — Removed `--api-key` CLI argument from all entry points; API key must come from `AGENT_API_KEY` env var only.
- `agent/strategies/regime/classifier.py` — `_fetch_candles` now paginates (API limit 1000); previously could silently truncate long date ranges.
- `agent/strategies/regime/models/regime_classifier.joblib` — Trained classifier model committed alongside source.
- `agent/strategies/rl/models/ppo_portfolio_final.zip` — Smoke-test model committed for CI validation.
- `development/plan.md` — New: agent deployment + training plan (Docker setup, data loading, training pipeline ordering).
- `development/executive-summary.md` — New: C-level executive summary of the platform.
- `development/agent-ecosystem-plan.md` — New: master plan for agent ecosystem (36 tasks: DB migrations, conversation system, memory, multi-agent coordination).
- `development/tasks/agent-deployment-training/` — New 23-task board: Docker setup, data loading, regime training, PPO training, evolutionary optimisation, ensemble search, monitoring.
- `development/tasks/agent-ecosystem/` — New 36-task board: full agent ecosystem expansion phases.
- `development/agent-development/battle-historical-investigation.md` — New investigation report on battle historical mode 500 error.

**Decisions:**
- `backtest` rate tier set to 6000/min — backtest step loops call the API in tight loops (up to 100 steps/session); 600/min general tier would throttle active backtests within seconds.
- `training` rate tier set to 3000/min — episode reporting calls happen every gym step during training; moderate headroom without fully uncapping.
- `asyncio.to_thread()` preferred over `ProcessPoolExecutor` for blocking ML operations — process pools have high startup overhead and pickle cost for numpy arrays; thread pool releases GIL during C-extension execution.
- `--profile agent` in docker-compose prevents accidental resource consumption in staging; operators must opt in explicitly.
- SHA-256 checksums as `.sha256` sidecar files — simple, CI-verifiable with standard shell tools, no file format changes needed.

**Learnings:**
- `agent/strategies/regime/classifier._fetch_candles` was silently truncating long date ranges because the API returns at most 1000 candles per request; pagination is required for > ~40 days of hourly data.

---

### 2026-03-20 — MILESTONE: Frontend Performance Optimization (23 Tasks, 3 Phases)

**What was done:**
A systematic performance audit and optimization pass across the entire frontend. Three phases covering quick wins, architectural improvements, and polish.

**Changes:**

Phase 1 — Quick Wins:
- `Frontend/src/components/market/market-table-row.tsx` — Wrapped `PriceFlashCell` in `React.memo` with a custom comparator that only re-renders on price or direction change; prevents cascading re-renders across 600+ market table rows.
- `Frontend/src/app/(dashboard)/battles/loading.tsx` — New: Next.js skeleton loading UI for the battles route (instant perceived performance on navigation).
- `Frontend/src/hooks/use-portfolio.ts` — Removed incorrect `useShallow` usage (was causing unnecessary deep comparison overhead); portfolio selector is already a primitive value.
- `Frontend/src/hooks/use-price.ts` — Memoized the price selector with `useMemo` so the selector function reference is stable across renders; prevents Zustand re-subscription churn.
- `Frontend/src/components/analytics/chart.tsx` — Memoized chart context value with `useMemo` to prevent all chart children from re-rendering when the parent re-renders without data changes.
- `Frontend/package.json` / `next.config.ts` — Installed `@next/bundle-analyzer`; activated via `ANALYZE=true` env var.

Phase 2 — Architecture:
- `Frontend/src/components/layout/header.tsx` — Restructured dashboard Header into 4 independently memo'd islands: `WsStatusBadge`, `NotificationBell`, `UserAvatar`, `SearchShell`. Each island only re-renders when its own data changes, not when any sibling updates.
- `Frontend/src/components/layout/sidebar.tsx` — Sidebar strategy/training activity dot badges given `staleTime: 60_000` (was 10s) — reduces badge-triggered re-fetches; activity state changes rarely enough that 60s staleness is acceptable.
- `Frontend/src/app/(dashboard)/layout.tsx` — Added `Suspense` boundaries around 8 below-fold dashboard sections; replaced them with `next/dynamic` lazy-loaded variants with skeleton fallbacks. These sections now only load after above-fold content is interactive.
- `Frontend/src/lib/api-client.ts` — GET request deduplication: concurrent identical GET requests share a single in-flight fetch (Map keyed by URL). Retry logic fixed: 3 attempts with exponential backoff (200/400/800ms), previously 1 retry with flat 1s delay.
- `Frontend/src/app/(dashboard)/coin/[symbol]/page.tsx` (or coin hooks) — Order book polling interval increased 5s→15s; trade history polling 10s→30s; REST price polling disabled entirely when WebSocket is connected for that symbol.
- `Frontend/src/hooks/use-daily-candles-batch.ts` — New: `useDailyCandlesBatch` batches up to 50 symbols per TanStack Query entry instead of one query per symbol; reduces query entries from 600 to 12 for the market table sparklines.
- `Frontend/src/app/globals.css` — 660 lines of landing-page CSS extracted to `Frontend/src/styles/landing.css`; globals.css trimmed from 1090 to 279 lines. Landing page imports the new file directly; non-landing pages no longer parse unused CSS.
- `Frontend/src/styles/landing.css` — New: extracted landing-page styles (animations, hero gradients, section layouts).

Phase 3 — Polish:
- `Frontend/src/components/shared/section-error-boundary.tsx` — New: `SectionErrorBoundary` component wraps individual dashboard sections so one failing section doesn't blank the entire dashboard. 11 dashboard sections wrapped independently.
- `Frontend/src/lib/prefetch.ts` — New: route prefetch utilities (`prefetchDashboard`, `prefetchMarket`, `prefetchCoin`); each calls `queryClient.prefetchQuery()` with keys matching hook factories. Used by sidebar `onMouseEnter` handlers.
- `Frontend/src/lib/websocket-client.ts` — `PriceBatchBuffer` switched from `setTimeout` to `requestAnimationFrame` with a 100ms minimum interval guard. Added `Map`-based deduplication (last price wins per symbol within a frame) and a mounted guard to prevent post-unmount flushes.
- `Frontend/src/hooks/use-backtest-list.ts`, `use-backtest-results.ts`, `use-leaderboard.ts`, `use-market-data.ts` (and 3 others) — `keepPreviousData` (`placeholderData: keepPreviousData`) added to 7 hooks across 4 files; eliminates loading flashes on page/filter changes.

Validation:
- `Frontend/tests/unit/components/price-flash-cell.test.tsx` — New: 11 tests covering PriceFlashCell memo comparator, flash class application, direction tracking.
- `Frontend/tests/unit/api-client.test.ts` — New: 20 tests covering GET deduplication, retry backoff timing, error propagation.
- 207 frontend tests passing (was 187 before Phase 2 test additions).

**Decisions:**
- `requestAnimationFrame` chosen over `setTimeout(fn, 100)` for PriceBatchBuffer flush — RAF fires at display refresh rate (16ms) and is paused by the browser when the tab is backgrounded, saving CPU. The 100ms minimum guard prevents excessive flushes on high-frequency feeds.
- Header split into 4 memo'd islands rather than one memo'd monolith — each island subscribes to its own data source; a WS reconnection only re-renders `WsStatusBadge`, not the entire header including search and avatar.
- GET deduplication implemented at the `api-client.ts` layer (not TanStack Query) because it handles raw `fetch()` calls outside React components (e.g., prefetch utility) that don't go through the query cache.
- Landing CSS extracted to a separate file rather than using `@layer` scoping — allows the landing page to import it explicitly; the dashboard layout never imports it, so landing styles are never parsed on authenticated pages.
- `staleTime: 60_000` on sidebar activity badges — these drive animated dot indicators (active strategies / running training); 60s staleness is acceptable since the underlying data changes on user action, not continuously.

**Bugs fixed:**
- `use-price.ts` selector reference instability — memoized selector now prevents Zustand from treating each render as a new subscription, which was causing subtle double-subscription bugs in pages with many price cells.
- API client retry was doing 1 retry with flat 1s delay (documented as 3x exponential in Frontend/CLAUDE.md but not implemented); now matches documentation.

**Tests:** 207 frontend unit tests passing after Phase 2 test suite additions (11 new PriceFlashCell + 20 new API client tests). Previous baseline was 187.

---

### 2026-03-20 — Agent Deployment Preparation (Tasks 19-23)

**Changes:**
- `agent/pyproject.toml` — Added `[ml]` optional group (stable-baselines3, torch, xgboost, scikit-learn, joblib, numpy, pandas) and `[all]` meta-group that installs everything; core package remains installable without ML deps.
- `agent/Dockerfile` — New: python:3.12-slim base, 3-layer install (system deps → Python deps → app code), non-root user for production safety.
- `docker-compose.yml` — Added `agent` service pinned to `--profile agent` so it does not start by default; only activated when explicitly requested.
- `agent/strategies/*/battle_runner.py`, `data_prep.py`, `ensemble/run.py` — Performance: replaced sequential `await` calls with `asyncio.gather()` at 4 locations in battle_runner; data_prep parallelised; ensemble run parallelised.
- `agent/strategies/rl/deploy.py`, `agent/strategies/regime/classifier.py` — Performance: wrapped `model.predict()` and `classifier.fit()` in `asyncio.to_thread()` to unblock the event loop during blocking numpy/sklearn operations.
- `agent/strategies/rl/deploy.py`, `agent/strategies/ensemble/run.py` — Performance: capped `step_history` and `regime_history` deques to prevent unbounded memory growth over long runs.
- `agent/strategies/regime/switcher.py` — Performance: added in-memory regime detection cache; avoids re-running the classifier on identical candle windows within the same step.
- `agent/strategies/utils/checksum.py` — New: SHA-256 checksum generation and verification for saved model files; raises `ModelIntegrityError` if the checksum does not match on load.
- `agent/strategies/rl/train.py`, `agent/strategies/rl/evaluate.py` — Security: integrated `checksum.py` — checksum written alongside `.zip` on save, verified on load. Removes pickle-based arbitrary code execution risk for local model files.
- `agent/strategies/rl/runner.py`, `agent/strategies/regime/validate.py`, `agent/strategies/ensemble/validate.py`, `agent/strategies/ensemble/optimize_weights.py` (and 6 other CLI scripts) — Security: removed `--api-key` positional/flag argument from all 10 CLI entry points; API key must now come from `AGENT_API_KEY` env var only, eliminating `ps aux` exposure.
- `development/tasks/agent-deployment-training/` — New task board: 23 tasks covering Docker setup, data loading, regime training, PPO training, evolutionary optimisation, ensemble search, and monitoring setup.

**Decisions:**
- `[ml]` and `[all]` extras keep the core `agent/` package pip-installable in CI/CD without pulling in torch (1.5 GB+); ML deps are only installed in the training Docker image.
- `--profile agent` in docker-compose prevents the agent container from starting during normal `docker compose up -d`; operators must opt in explicitly. This avoids accidental resource consumption in staging environments.
- SHA-256 checksums stored as sidecar files (`<model>.sha256`) alongside model zips — simpler than embedding in the file format; easy to verify in CI pipelines with standard shell tools.
- `asyncio.to_thread()` chosen over `ProcessPoolExecutor` for blocking ML calls — process pool has significant startup overhead and pickle serialisation cost for numpy arrays; thread pool is sufficient since the GIL is released during numpy/sklearn C-extension execution.

**Bugs fixed:**
- Battle historical mode `500 INTERNAL_ERROR` on create — confirmed fixed (was fixed 2026-03-18; regression test added).
- `asyncio.gather()` introduced at 4 battle_runner locations resolves a latency bug where sequential agent provisioning could time out on battles with 5+ participants.

**Tests:** 901 agent tests passing (0 failures, 1 skipped). Previous count was 578 (strategy layer) + 117 (agent package) = 695; the increase to 901 reflects new checksum utility tests and CLI security tests added in this session.

---

### 2026-03-20 — CLAUDE.md Sync Pass

Created 5 strategy sub-package CLAUDE.md files (`rl/`, `evolutionary/`, `regime/`, `risk/`, `ensemble/`); added to root CLAUDE.md index. Strategy sub-package CLAUDE.md files are detailed enough to stand alone — working in a sub-package does not require reading the parent first. Did not create CLAUDE.md for output-only model/results directories.

---

### 2026-03-20 — Coming Soon Page + Landing Page Route Reorganization

**Changes:**
- `Frontend/src/app/page.tsx` — New root route (`/`) replaced the landing page with a "Coming Soon" page. Renders the `ComingSoon` component.
- `Frontend/src/app/landing/page.tsx` — Original landing page moved here; accessible at `/landing` for direct reference or future re-activation.
- `Frontend/src/components/coming-soon/coming-soon.tsx` — New component implementing the Coming Soon page: platform summary paragraph, 6-feature grid (Real-Time Trading, AI Agents, Backtesting, Battle System, Strategy Builder, Analytics), "How It Works" 3-step flow, and a waitlist email signup form.

**Decisions:**
- Waitlist form posts to the existing `/api/waitlist` endpoint with `source: "coming-soon"` — no new backend endpoint needed; the `waitlist` DB table and route were already in place.
- Original landing page preserved at `/landing` rather than deleted — allows internal navigation and future re-promotion without rebuilding the component.
- Coming Soon page is a standalone client component (no layout wrapping) — it serves as the public-facing entry point before the platform opens, separate from the authenticated dashboard layout.

**Build verification:** Both `/` (coming-soon) and `/landing` routes appear in the Next.js route table. Zero TypeScript/lint errors.

---

### 2026-03-20 — MILESTONE: Agent Trading Strategy System Complete (5 Strategies, 29 Tasks)

Five sub-packages: `rl/` (PPO SB3), `evolutionary/` (StrategyGenome 12-param GA), `regime/` (XGBoost/RF regime classifier, 4 regime types), `risk/` (VetoPipeline 6-gate, DynamicSizer), `ensemble/` (MetaLearner weighted voting, EnsembleRunner 6-stage pipeline). 578 tests. Details in `agent/strategies/*/CLAUDE.md`.

**Key decisions:**
- `StrategyGenome` as float64 numpy vector — enables standard GA operators without marshalling overhead.
- Fitness: `sharpe - 0.5 * max_drawdown` — weights drawdown at half Sharpe contribution.
- Regime cooldown 20 candles — prevents thrashing at regime boundaries.
- `VetoPipeline` RESIZED does not short-circuit — all size reduction factors stack (intentional).
- `MetaLearner` falls back to HOLD on low confidence or source disagreement — never speculative trades.
- Optional ML extras: `[rl]`, `[evolutionary]`, `[regime]` — core agent package installable without torch/xgboost.

**Key learnings:**
- `BattleRunner` must authenticate with JWT — `POST /api/v1/battles` requires Bearer auth.
- `PPODeployBridge` silently returns equal weights until buffer has 30 candles.
- `RegimeSwitcher.step()` is stateful — new instance per trading session.
- Incremental sklearn learning rejected — XGBoost `partial_fit` interface incompatible with sklearn wrapper.
- Evolutionary fitness via battles not backtests — battles support parallel multi-agent scoring.

---

### 2026-03-20 — MILESTONE: TradeReady Platform Testing Agent V1 Complete (Tasks 1-18)

`agent/` package: Pydantic AI + OpenRouter, 4 workflows (smoke/trading/backtest/strategy), 3 integration layers (SDK/MCP/REST), 6 Pydantic output models, 117 tests, CLI entry point with structlog JSON.

**Key decisions:**
- Pydantic AI over LangChain/CrewAI — typed tool registration and structured output natively.
- Three integration layers (SDK / MCP / REST) — SDK for execution, MCP for tool discovery, REST for backtest/strategy endpoints not in SDK.
- LLM for decisions only; direct SDK/REST calls for mechanical execution — avoids hallucination on order IDs/parsing.
- Workflows never crash on step failure — `success=False` recorded, execution continues.

**Key learnings:**
- `MCPServerStdio` requires server process running before agent instantiation — starts as subprocess; degrades gracefully if MCP not on PATH.
- `structlog` and `logging` cannot be mixed — must replace all `getLogger` calls.
- `gemini-2.0-flash` occasionally produces trailing commas in JSON output — added strip/repair step.

**Failed approaches:**
- Claude Agent SDK rejected — no typed return schemas; every tool response is untyped `str`.
- Full LLM execution loop rejected — 3-5s per LLM call × N steps is too slow; hybrid adopted.

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
