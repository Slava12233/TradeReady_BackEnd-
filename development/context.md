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

**Active work:** Agent template Memory Protocol rollout complete — all 16 agent templates updated.
**Last session:** 2026-03-21 — Added `memory: project` frontmatter and `## Memory Protocol` sections to all 16 agent templates in `claude-code-starter-kit/templates/agents/`. 12 agents were missing `memory: project` (test-runner, deploy-checker, security-auditor, api-sync-checker, perf-checker, e2e-tester, migration-helper, doc-updater, frontend-developer, ml-engineer, codebase-researcher, plus backend-developer which already had the flag but lacked the section). All 4 pre-existing agents (code-reviewer, context-manager, planner, security-reviewer) also received Memory Protocol sections. Write-capable agents got the full MEMORY.md update protocol; read-only agents (security-auditor, perf-checker, api-sync-checker, codebase-researcher) got the analysis-oriented variant.
**Next steps:** (1) Start Docker services, load historical OHLCV data via `scripts/backfill_history.py`. (2) Run training pipeline: regime classifier → PPO RL → evolutionary optimiser → ensemble weight search. (3) Battle system frontend (`Frontend/src/components/battles/`) remains empty — last major incomplete frontend area. (4) Monitoring and alerting for live ensemble + trading loop runs. (5) Integration test the full agent ecosystem against a live platform instance.
**Blocked:** Nothing currently blocked.

---

## Project Overview

A **production-deployed** simulated crypto exchange where AI agents trade **virtual USDT** against **real Binance market data**. Supports 600+ USDT pairs with real-time price feeds, order execution, risk controls, portfolio tracking, backtesting, and agent-vs-agent battles.

### What's Built (as of 2026-03-20)

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
| **Agent Strategy System** | Complete | `agent/strategies/` — 5 strategies (RL/evolutionary/regime/risk/ensemble), 29 tasks, 578 tests. Perf + security hardened: asyncio.gather (6 locations), asyncio.to_thread (4 locations), SHA-256 checksums, no CLI API key exposure. |
| **Agent Ecosystem (Phase 1)** | Complete | DB migration 017, 10 models, 10 repos, conversation system, memory system, 5 agent tools, AgentServer, CLI REPL, 4 Celery tasks. 370+ tests. |
| **Agent Ecosystem (Phase 2)** | Complete | Permissions system (roles/capabilities/budget/enforcement), 4 CRITICAL security fixes, trading intelligence (TradingLoop, SignalGenerator, TradeExecutor, PositionMonitor, TradingJournal, StrategyManager, ABTestRunner). 414+ tests. |
| **Agent Memory & Learning System** | Complete | `memory: project` on all 16 agents, 16 MEMORY.md files seeded, Memory Protocol in all agent prompts, 3 activity logging scripts, PostToolUse hook, `/analyze-agents` skill, `/review-changes` feedback capture. |
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
- **Tasks:** Celery + Redis broker (11 beat tasks)
- **Auth:** JWT (PyJWT) + API keys (bcrypt), dual auth flow
- **Testing:** pytest (62+ unit files / 1000+ tests, 20+ integration files / 440+ tests) — STR-2 added 67 tests (91 total for strategies); STR-5 added 16 tests; STR-3 added 25+ gymnasium compliance tests; STR-4 added 15+ MCP tool tests
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

### Database (17 migrations, current head: 017)

Key tables: `accounts`, `agents`, `balances`, `orders`, `trades`, `positions`, `ticks` (hypertable), `portfolio_snapshots` (hypertable), `trading_pairs`, `backtest_sessions`, `backtest_trades`, `backtest_snapshots` (hypertable), `battles`, `battle_participants`, `battle_snapshots` (hypertable), `candles_backfill`, `waitlist`, `strategies`, `strategy_versions`, `strategy_test_runs`, `strategy_test_episodes`, `training_runs`, `training_episodes`, `agent_sessions`, `agent_messages`, `agent_decisions`, `agent_journal`, `agent_learnings`, `agent_feedback`, `agent_permissions`, `agent_budgets`, `agent_performance`, `agent_observations` (hypertable)

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
