# Development Context Log

<!-- This file is maintained by the context-manager agent. It summarizes all development activity so future conversations have full context. -->

## Current State

**Active work:** Cross-cutting tasks CC-1 through CC-14 (next up after STR-UI-2 completion)
**Last session:** 2026-03-18 — Phase STR-UI-2 (Integration & Polish) completed all 7 implementation tasks. Dashboard strategy/training status cards added, backtest list filter for training episodes, sidebar badges for `/strategies` and `/training`, empty states for both pages, mobile responsive layout for version comparison, and error boundaries for both routes.
**Next steps:** Cross-cutting tasks CC-1 through CC-14. Battle system frontend (`Frontend/src/components/battles/`) remains empty. Historical battle mode 500 bug still open.
**Blocked:** None

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
| **Strategy & Training UI (STR-UI-1)** | Complete | 4 pages, 4 hooks, 21 components, 20 API functions, 20 types. 0 TS errors. |
| **Strategy & Training UI (STR-UI-2)** | Complete | Dashboard status cards, backtest filter toggle, sidebar active badges, empty states, mobile responsive layout, error boundaries. |
| **Unified Metrics** | Production | Shared calculator for backtests & battles |
| **MCP Server** | Production | 58 tools over stdio transport (43 base + 15 strategy/training from Phase STR-4) |
| **Python SDK** | Production | Sync + async + WebSocket clients |
| **Frontend** | Production | Next.js 16, React 19, Tailwind v4, agent switcher, backtest UI |
| **Monitoring** | Production | Prometheus metrics, health checks, structured logging |
| **Exchange Abstraction (CCXT)** | Production | Adapter pattern, 110+ exchanges, symbol mapper, multi-exchange backfill |
| **Agentic Layer** | Complete | 36 CLAUDE.md files, 12 sub-agents |
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

### Database (16 migrations, current head: 016)

Key tables: `accounts`, `agents`, `balances`, `orders`, `trades`, `positions`, `ticks` (hypertable), `portfolio_snapshots` (hypertable), `trading_pairs`, `backtest_sessions`, `backtest_trades`, `backtest_snapshots` (hypertable), `battles`, `battle_participants`, `battle_snapshots` (hypertable), `candles_backfill`, `waitlist`, `strategies`, `strategy_versions`, `strategy_test_runs`, `strategy_test_episodes`, `training_runs`, `training_episodes`

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
13. **Dual-source price pattern** — Frontend components that compute asset USDT values must use WS prices (primary) + REST `/market/prices` (30s fallback). WebSocket-only is unreliable for initial page loads.

---

## Recent Activity

### 2026-03-18 — STR-UI-2: Strategy & Training Integration & Polish (Phase Complete)

**Changes:**
- `Frontend/src/components/dashboard/strategy-status-card.tsx` — New card showing the currently deployed strategy (name, version, status badge); renders on the main dashboard page.
- `Frontend/src/components/dashboard/training-status-card.tsx` — New card showing the active training run progress (run name, episode count, latest reward); renders on the main dashboard page.
- `Frontend/src/app/(dashboard)/page.tsx` (dashboard) — Imported and added `StrategyStatusCard` and `TrainingStatusCard` to the dashboard layout.
- `Frontend/src/components/backtest/backtest-list.tsx` — Added "Hide training episodes" toggle that filters out entries whose strategy label matches `gym_*` or `training_*` prefixes, preventing gym-generated backtest sessions from cluttering the list.
- `Frontend/src/lib/constants.ts` (nav/sidebar) — Added animated active indicator dots for `/strategies` (shown when any test run is in progress) and `/training` (shown when any training run is active) in the "Agents & Strategy" nav group.
- `Frontend/src/components/shared/empty-state.tsx` — Added `no-strategies` and `no-training-runs` variants so both new pages have consistent empty states matching the platform's shared design language.
- `Frontend/src/components/strategies/version-comparison.tsx` — Added stacked mobile layout via responsive Tailwind classes; desktop retains side-by-side comparison view.
- `Frontend/src/app/(dashboard)/strategies/error.tsx` — New Next.js error boundary for the `/strategies` route group; prevents strategy page errors from bubbling to the root layout.
- `Frontend/src/app/(dashboard)/training/error.tsx` — New Next.js error boundary for the `/training` route group.

**Decisions:**
- Dashboard status cards are separate components (not inline in the page) — keeps the dashboard page file readable and lets the cards be conditionally rendered without logic cluttering the layout.
- "Hide training episodes" is a client-side toggle (not a server query param) — the list is already paginated from the server; an additional filter param would require a new backend query parameter, and the toggle provides instant feedback without a network round-trip.
- Sidebar animated dots use conditional rendering based on polling data already fetched by the strategy/training hooks — no new API calls; the data is reused from the existing TanStack Query cache.
- Error boundaries added at the route level (not component level) — Next.js App Router error.tsx files catch all errors within the route segment, providing the right granularity without wrapping every component individually.

**Learnings:**
- Next.js App Router error.tsx must be a Client Component (`"use client"`) — server components cannot catch rendering errors at the boundary level; this is a Next.js constraint, not a design choice.
- The "hide training episodes" filter pattern (prefix-matching on a label field) should be documented for future callers: any Celery task or gym loop that creates backtest sessions for training must use the `gym_` or `training_` prefix on the strategy label to be filterable.

---

### 2026-03-18 — STR-UI-1: Strategy & Training Frontend Pages (Phase Complete)

**Changes:**
- `Frontend/src/lib/types.ts` — Added 20 new TypeScript types: `StrategyStatus`, `StrategyDefinition`, `Strategy`, `StrategyDetailResponse`, `StrategyVersion`, `StrategyListResponse`, `TestRunStatus`, `StrategyTestRun`, `PairBreakdown`, `AggregatedMetrics`, `TestResults`, `VersionMetrics`, `VersionComparisonResponse`, `TrainingRun`, `TrainingEpisodeMetrics`, `TrainingEpisode`, `LearningCurveData`, `TrainingRunDetail`, `RunMetrics`, `TrainingComparisonResponse`.
- `Frontend/src/lib/api-client.ts` — Added 20 new API functions covering strategy CRUD, strategy test operations, and training run operations.
- `Frontend/src/lib/constants.ts` — Added `/strategies` and `/training` to `ROUTES` and `NAV_ITEMS` (Brain + GraduationCap icons).
- `Frontend/src/hooks/use-strategies.ts` — New hook: strategy list query + 6 mutations (create, update, archive, create-version, deploy, undeploy).
- `Frontend/src/hooks/use-strategy-detail.ts` — New hook: strategy detail + test runs + version comparison.
- `Frontend/src/hooks/use-training-runs.ts` — New hook: training run list with 10s conditional polling.
- `Frontend/src/hooks/use-training-run-detail.ts` — New hook: active run (2s poll), detail, learning curve, comparison.
- `Frontend/src/components/strategies/` — 10 new components: `strategy-status-badge.tsx`, `strategy-list-table.tsx`, `strategy-detail-header.tsx`, `version-history.tsx`, `definition-viewer.tsx`, `test-results-summary.tsx`, `version-comparison.tsx`, `recommendations-card.tsx`, `strategies-page.tsx`, `strategy-detail-page.tsx`.
- `Frontend/src/components/training/` — 11 new components: `active-training-card.tsx`, `learning-curve-sparkline.tsx`, `completed-runs-table.tsx`, `run-header.tsx`, `run-summary-cards.tsx`, `learning-curve-chart.tsx`, `episode-highlight-card.tsx`, `episodes-table.tsx`, `run-comparison-view.tsx`, `training-page.tsx`, `training-run-detail-page.tsx`.
- `Frontend/src/app/(dashboard)/strategies/` — New page + loading.tsx.
- `Frontend/src/app/(dashboard)/strategies/[id]/` — New dynamic page + loading.tsx.
- `Frontend/src/app/(dashboard)/training/` — New page + loading.tsx.
- `Frontend/src/app/(dashboard)/training/[run_id]/` — New dynamic page + loading.tsx.

**Decisions:**
- Training list uses 10s polling (not WebSocket) — training runs are long-lived background jobs; a 10s poll is sufficient granularity and avoids opening extra WS channels.
- Active training run detail uses 2s polling — more aggressive to show learning curve progress in near-real-time while a run is `active`.
- `TrainingEpisodeMetrics` introduced as a sub-type of `TrainingEpisode` — backend nests episode metrics inside a `metrics` object; flat structure on the TypeScript type would have misaligned the shape and caused runtime `undefined` values.

**Bugs fixed (API sync):**
- `deployStrategy()` was missing a `version` body parameter — fixed to accept and send version.
- `getTrainingRuns()` backend returns a raw array (not a `{ runs: [...] }` wrapper) — frontend now wraps it to match expected shape.
- `TrainingEpisode` had flat field structure (`roi_pct` at top level) but backend nests under `metrics` — restructured type and all consuming components to use `episode.metrics.roi_pct`.
- `createStrategy()` had `definition` as optional — made required to match backend validation (backend rejects requests without it).
- `StrategyTestRun.strategy_id` removed from type — field is not present in the backend response schema.

**Learnings:**
- All training components must access episode data via `episode.metrics.*` not `episode.*` — the backend nests all performance fields under a `metrics` sub-object in `TrainingEpisode`.
- 10s conditional polling pattern (stop when run reaches terminal status) is already established in `use-backtest-list.ts` — replicated in `use-training-runs.ts` for consistency.

---

### 2026-03-18 — STR-3/STR-4 Security Hardening

**Changes:**
- `tradeready-gym/tradeready_gym/envs/base_trading_env.py` — Added `_validate_base_url()` to reject non-http/https schemes and URLs without a host (SSRF prevention); added `_validate_symbol()` regex (`^[A-Z0-9]{2,20}$`) to sanitize trading pair symbols before URL interpolation, applied to `self.pairs` in `__init__` (path injection prevention).
- `tradeready-gym/tradeready_gym/utils/training_tracker.py` — Changed all `exc_info=True` to `exc_info=False` to prevent httpx tracebacks from leaking `X-API-Key` headers into logs; added URL validation mirroring `base_trading_env.py` to reject non-http/https schemes and empty-host URLs.
- `src/mcp/tools.py` — Added UUID format validation for `run_ids` list in `compare_training_runs` tool to prevent query parameter injection; removed full `arguments` dict from `call_tool` debug log to stop financial data leaking into logs.
- `sdk/agentexchange/client.py` — Added UUID validation for `run_ids` in the sync `compare_training_runs` method to prevent query parameter injection.
- `sdk/agentexchange/async_client.py` — Identical UUID validation added to the async `compare_training_runs` method.

**Decisions:**
- Symbol validation uses a strict allowlist regex (`^[A-Z0-9]{2,20}$`) rather than a denylist — safer default; any symbol outside this range is invalid by the exchange's own naming conventions.
- `exc_info=False` preferred over removing exception logging entirely — preserves the error message (type + string) for observability while dropping the full traceback that exposes headers.
- UUID validation applied at both MCP tool layer and SDK layer — defense in depth; the REST API already validates, but clients should not send malformed data even if the server would reject it.

**Bugs fixed:**
- SSRF: `base_trading_env.py` and `training_tracker.py` accepted arbitrary `base_url` values including `file://`, `ftp://`, and URLs without a host — now rejected before any HTTP call is made.
- Path injection: unvalidated symbols were interpolated directly into URL paths (e.g., `f"/backtest/{symbol}/step"`) — a symbol like `../admin` could traverse to unintended endpoints.
- API key log leakage: httpx exceptions include full request context (headers) in their `__traceback__`; `exc_info=True` was writing these to the log stream.
- UUID injection: `compare_training_runs` accepted arbitrary strings as run IDs and passed them as query parameters — now validated to be well-formed UUIDs before the request is sent.
- Debug log data leak: `call_tool` debug log was dumping the full `arguments` dict, which can include API keys, account IDs, and financial parameters.

---

### 2026-03-18 — STR-4: MCP Tools, SDK Extensions, Documentation (Phase Complete)

**Changes:**
- `src/mcp/tools.py` — Added 15 new tools: 7 strategy management, 5 strategy testing, 3 training observation. Tool count raised from 43 to 58. Fixed `_call_api` to handle 204/empty responses. Moved lazy `import json` to module top level.
- `src/mcp/CLAUDE.md` — Updated tool count and tool tables to reflect 58 tools.
- `sdk/agentexchange/client.py` — Added 13 new methods: strategy CRUD (6), testing (4), training (3).
- `sdk/agentexchange/async_client.py` — Identical async counterparts of the 13 new SDK methods.
- `docs/skill.md` — Added Strategy Development Cycle and RL Developer sections.
- `docs/api_reference.md` — Added 23 new endpoint sections covering strategies, strategy tests, and training runs.
- `tests/unit/test_mcp_strategy_tools.py` — 15+ tests for the 15 new MCP tools.

**Decisions:**
- New MCP tools remain thin wrappers over existing REST endpoints, consistent with the prior pattern (no business logic in the MCP layer).
- `_call_api` now explicitly handles 204 No Content and empty body responses rather than failing on `.json()` parse — necessary for delete/cancel endpoints.

**Bugs fixed:**
- `_call_api` in `tools.py` would crash on 204 responses with an empty body — fixed by checking `response.content` before calling `.json()`.

**Learnings:**
- MCP tool count drift: `TOOL_COUNT` constant in `tools.py` must be kept in sync with `server.py` and `__init__.py` manually — no automated check enforces it.

---

### 2026-03-18 — STR-3: Gymnasium Wrapper Package (Phase Complete)

**Changes:**
- `tradeready-gym/pyproject.toml` — New package: `tradeready-gym`, depends on gymnasium>=0.29, numpy, httpx.
- `tradeready-gym/tradeready_gym/__init__.py` — Registers 7 environments (`TradeReady-SingleAsset-v0` through `TradeReady-Live-v0`); exports all public classes.
- `tradeready-gym/tradeready_gym/envs/base_trading_env.py` — `BaseTradingEnv(gymnasium.Env)` wrapping the backtest REST API. `api_key` made private (`_api_key`) to prevent accidental serialization. Registration guard simplified.
- `tradeready-gym/tradeready_gym/envs/single_asset_env.py` — `SingleAssetTradingEnv` with both discrete (HOLD/BUY/SELL) and continuous (-1 to 1) action modes.
- `tradeready-gym/tradeready_gym/envs/multi_asset_env.py` — `MultiAssetTradingEnv` using portfolio weight allocation as the action space.
- `tradeready-gym/tradeready_gym/envs/live_env.py` — `LiveTradingEnv` for real-time paper trading; bare `except` replaced with specific httpx exceptions; dead `_create_session` override removed.
- `tradeready-gym/tradeready_gym/spaces/action_spaces.py` — 5 action space presets: discrete, continuous, portfolio, multi-discrete, parametric.
- `tradeready-gym/tradeready_gym/spaces/observation_builders.py` — `ObservationBuilder` producing OHLCV + RSI, MACD, Bollinger Bands, ADX, ATR features.
- `tradeready-gym/tradeready_gym/rewards/custom_reward.py` — ABC base with `reset()` abstract method.
- `tradeready-gym/tradeready_gym/rewards/pnl_reward.py` — Simple equity delta reward.
- `tradeready-gym/tradeready_gym/rewards/sharpe_reward.py` — Rolling Sharpe ratio delta; `reset()` implemented.
- `tradeready-gym/tradeready_gym/rewards/sortino_reward.py` — Rolling Sortino ratio delta; `reset()` implemented.
- `tradeready-gym/tradeready_gym/rewards/drawdown_penalty_reward.py` — PnL minus drawdown penalty; `reset()` implemented.
- `tradeready-gym/tradeready_gym/utils/training_tracker.py` — Auto-reports training runs to platform API; `__del__` removed (unreliable finalizer replaced with explicit `close()` / context manager pattern).
- `tradeready-gym/tradeready_gym/wrappers/feature_engineering.py` — Adds SMA ratios and momentum features.
- `tradeready-gym/tradeready_gym/wrappers/normalization.py` — Welford's online normalization clipped to [-1, 1].
- `tradeready-gym/tradeready_gym/wrappers/batch_step.py` — Accumulates N environment steps per single agent action call.
- `tradeready-gym/examples/` — 10 example scripts: random agent, PPO, DQN, continuous, portfolio, custom reward, custom obs builder, vectorized envs, evaluation harness, live trading.
- `tradeready-gym/tests/test_gymnasium_compliance.py` — 25+ tests: gymnasium API compliance (reset/step/seed), all reward functions, all wrappers, all action space presets.
- `development/Gym_api/tasks.md` — All 25 tasks across STR-3 (16) and STR-4 (9) marked complete.

**Decisions:**
- Package uses httpx (not requests) for REST calls — consistent with the rest of the backend ecosystem, supports async usage.
- `TrainingTracker` drops `__del__` finalizer — Python's garbage collector makes `__del__` unreliable for network calls; replaced with explicit `close()` and context manager support.
- All stateful reward functions implement `reset()` — required so state (rolling windows, baseline equity) is cleared between episodes; without it, episode 2 would inherit episode 1's statistics.
- `api_key` renamed to `_api_key` in `BaseTradingEnv` — prevents the key from appearing in `env.__dict__` serialization or repr outputs.
- Bare `except` in `live_env.py` replaced with `except (httpx.HTTPError, httpx.TimeoutException)` — avoids swallowing `KeyboardInterrupt`, `SystemExit`, and other non-network exceptions.

**Learnings:**
- Gymnasium's `check_env()` utility enforces that `reset()` returns `(obs, info)` and `step()` returns `(obs, reward, terminated, truncated, info)` — the 5-tuple, not the old 4-tuple from gym 0.21. All envs must use the new API.
- Stateful reward classes that skip `reset()` cause cross-episode data leakage — Sharpe/Sortino windows from a previous episode inflate (or deflate) the signal in the next episode. Made `reset()` abstract in the base class to force implementation.

**Failed approaches:**
- Initially used `__del__` in `TrainingTracker` for auto-flushing the final training run record — rejected because `__del__` is not guaranteed to be called (circular refs, interpreter shutdown). Replaced with explicit resource management.

---

### 2026-03-18 — STR-3/STR-4 Code Review: Critical Fixes Applied

**Bugs fixed:**
- `live_env.py` bare `except` → `except (httpx.HTTPError, httpx.TimeoutException)` — was swallowing non-network exceptions including KeyboardInterrupt.
- `tools.py` `_call_api` crash on 204/empty body → added `response.content` guard before `.json()` parse.
- `TrainingTracker.__del__` removed — unreliable finalizer could silently fail on interpreter shutdown; replaced with context manager + explicit `close()`.
- `test_gymnasium_compliance.py` deferred imports moved to module top — import-time errors were surfacing as misleading test failures rather than import errors.
- `Decimal(starting_balance)` conversion comment added — `starting_balance` comes in as float from the API; explicit `Decimal` cast required for consistency with platform money rules.
- `reset()` added to `SharpeReward`, `SortinoReward`, `DrawdownPenaltyReward` — cross-episode state leakage without it.
- Dead `_create_session` override removed from `LiveTradingEnv` — was shadowing parent and doing nothing.
- `api_key` → `_api_key` in `BaseTradingEnv` — prevents accidental serialization/repr exposure.
- `import json` moved to top of `tools.py` — lazy import inside function is a ruff violation (PLC0415) when not needed for circular-import avoidance.
- Registration guard in `BaseTradingEnv` simplified — removed redundant try/except pattern around gymnasium registration.

---

### 2026-03-18 — STR-5: Training Run Aggregation (Phase Complete)

**Changes:**
- `src/strategies/training_service.py` — `TrainingRunService` with register, record_episode, complete, learning_curves, and comparison operations. Aggregate stats (win rate, avg reward, episode count, etc.) are computed only when `complete()` is called — not incrementally — to avoid partial-data reads mid-run.
- `src/strategies/training_repository.py` — `TrainingRunRepository` with full CRUD for training runs and episodes. Follows the same repository pattern as `StrategyRepository` — no business logic, no auth.
- `src/api/routes/training.py` — 7 REST endpoints under `/api/v1/training`: register run, record episode, complete run, get run, list runs, get learning curves, compare runs.
- `src/api/schemas/training.py` — Pydantic v2 request/response schemas for all 7 endpoints.
- `src/dependencies.py` — Added DI aliases for `TrainingRunRepoDep` and `TrainingRunServiceDep`.
- `tests/unit/test_training_service.py` — 10 unit tests covering register, record, complete, learning curves, comparison, and ownership checks.
- `tests/integration/test_training_endpoints.py` — 6 integration tests covering all 7 REST endpoints end-to-end.

**Decisions:**
- Training run IDs are client-provided UUIDs, not server-generated — allows the caller (e.g., a gym loop) to assign its own stable IDs and reference them before the run is registered in the DB.
- Learning curve smoothing uses rolling mean — simple, predictable, no extra deps. Window size is configurable per request.
- Aggregate stats (reward stats, episode counts, win rates) are computed only on `complete()`, not updated per episode — avoids expensive re-aggregation on every episode write and keeps reads fast during active runs.
- Routes access the service exclusively, never `_repo` directly — learned from STR-2 code review where a route was flagging direct repository access as a pattern violation.

**Learnings:**
- Client-provided UUIDs for run IDs require a uniqueness check at register time; the repository must raise a conflict error rather than letting the DB constraint surface an opaque IntegrityError to the route handler.
- Rolling mean smoothing with a window larger than the episode count silently returns unsmoothed data — callers should document this behavior expectation rather than assuming smoothing always applies.

---

### 2026-03-18 — STR-2: Server-Side Strategy Executor (Phase Complete)

**Changes:**
- `src/strategies/indicator_engine.py` — `IndicatorEngine` class with 7 pure-numpy technical indicators: RSI, MACD, SMA, EMA, Bollinger Bands, ADX, ATR. No TA-Lib dependency; uses only numpy for portability.
- `src/strategies/executor.py` — `StrategyExecutor` with 12 entry condition evaluators (AND logic — all must pass) and 7 exit condition handlers (OR logic — any can trigger). Exit priority order: stop_loss → take_profit → trailing_stop → max_hold_candles → indicator exits (RSI, MACD). Includes position sizing logic.
- `src/strategies/orchestrator.py` — `TestOrchestrator` managing multi-episode strategy test lifecycles: episode sequencing, state tracking, coordination between executor and repository.
- `src/strategies/aggregator.py` — `TestAggregator` computing overall and per-pair result breakdowns from completed episodes.
- `src/strategies/recommendations.py` — `RecommendationEngine` with 11 rules that analyze aggregated test results and produce concrete strategy improvement suggestions.
- `src/strategies/repository.py` — `TestRunRepository` extending `StrategyRepository` rather than a separate class, adding test run and episode CRUD without duplicating base methods.
- `src/tasks/strategy_tasks.py` — 2 Celery tasks: `run_strategy_episode` (5-min soft / 6-min hard time limit per episode) and `aggregate_test_results` (post-episode aggregation trigger).
- `src/api/routes/strategy_testing.py` — 6 REST endpoints under `/api/v1/strategies`: start test, get test status, get test results, list test runs, cancel test, get recommendations.
- `src/dependencies.py` — Added `TestRunRepoDep`, `TestOrchestratorDep`, `IndicatorEngineDep` DI aliases.
- `tests/unit/test_indicator_engine.py` — Unit tests for all 7 indicators covering edge cases (insufficient data, all-same prices, NaN propagation).
- `tests/unit/test_strategy_executor.py` — Unit tests for entry/exit condition logic, position sizing, exit priority ordering.
- `tests/unit/test_recommendation_engine.py` — Unit tests for all 11 recommendation rules.
- `tests/integration/test_strategy_testing_endpoints.py` — Integration tests for all 6 REST endpoints.
- `pyproject.toml` — Added `numpy` as a dependency (was not previously installed).

**Decisions:**
- `IndicatorEngine` uses pure numpy instead of TA-Lib to avoid a C extension dependency that complicates Docker builds and cross-platform deployment.
- `TestRunRepository` extends `StrategyRepository` rather than being a standalone class — avoids duplicating base CRUD methods and keeps the inheritance chain shallow.
- Celery episode tasks have a 5-min soft / 6-min hard time limit — prevents runaway episodes from blocking workers indefinitely while giving enough runway for large candle datasets.
- Entry conditions use AND logic (all must pass); exit conditions use OR logic (any triggers exit) — matches standard strategy semantics where you need conviction to enter but any risk event exits.
- Exit priority is deterministic: stop_loss → take_profit → trailing_stop → max_hold_candles → indicator exits — stop-loss always wins to protect capital regardless of profit signals.

**Learnings:**
- Numpy's rolling window calculations require minimum period checks before computing; insufficient data returns NaN arrays and must be handled explicitly — callers that don't guard get silent NaN propagation.
- Celery soft time limits raise `SoftTimeLimitExceeded` which can be caught for graceful cleanup; hard limits SIGKILL the worker so cleanup must happen before the soft limit.

---

### 2026-03-18 — STR-1: Strategy Registry (Phase Complete)

**Changes:**
- `alembic/versions/016_*.py` — Migration 016 adds 6 new tables: `strategies`, `strategy_versions`, `strategy_test_runs`, `strategy_test_episodes`, `training_runs`, `training_episodes`. Head advances from 015 → 016.
- `src/database/models.py` — Added 6 ORM models: `Strategy`, `StrategyVersion`, `StrategyTestRun`, `StrategyTestEpisode`, `TrainingRun`, `TrainingEpisode`.
- `src/strategies/repository.py` — `StrategyRepository` with full CRUD, versioning (get_max_version + auto-increment), and test run management. Follows repository pattern — no business logic.
- `src/strategies/service.py` — `StrategyService` with ownership enforcement, version auto-increment, and strategy lifecycle (create, publish, archive). Validation via Pydantic domain models, not at DB level.
- `src/strategies/schemas.py` — Pydantic domain models: `StrategyDefinition`, `EntryConditions`, `ExitConditions`. Used for validating strategy logic before persisting a version.
- `src/api/schemas/strategies.py` — API-layer Pydantic v2 request/response schemas for all 10 endpoints.
- `src/api/routes/strategies.py` — 10 REST endpoints under `/api/v1/strategies`: create, list, get, update, delete, publish, archive, create-version, list-versions, get-version.
- `src/utils/exceptions.py` — Added `StrategyNotFoundError` and `StrategyInvalidStateError` to exception hierarchy.
- `src/dependencies.py` — Added `StrategyRepoDep` and `StrategyServiceDep` DI aliases.
- `src/strategies/CLAUDE.md` — Full module documentation: file inventory, public API, patterns, state machine, gotchas.
- `tests/unit/test_strategy_service.py` — 16 unit tests covering ownership checks, version increment, state transitions, and validation errors.
- `tests/integration/test_strategy_endpoints.py` — 8 integration tests covering all 10 endpoints end-to-end; all passing.

**Decisions:**
- Strategy definitions are validated via Pydantic domain models in the service layer, not with DB constraints — keeps schema flexible for early iteration without migrations per change.
- Version auto-increment uses `get_max_version() + 1` inside a transaction — avoids gaps and race conditions without a DB sequence.
- Ownership checks live exclusively in `StrategyService`, not in `StrategyRepository` — repository is generic and reusable; authorization is a service concern.
- `StrategyVersion` is immutable after creation — updating a strategy creates a new version; old versions are permanently accessible for audit and replay.
- No restriction on number of deployed strategies per account — intentional to support multi-strategy agents.

**Learnings:**
- The existing DI alias pattern in `src/dependencies.py` required lazy imports (inside the dependency function) to avoid circular imports — consistent with all other DI aliases in the file.
- Exception hierarchy in `src/utils/exceptions.py` uses class-level `http_status` and `code` attributes; new exceptions only need to set those two fields to integrate with the global handler automatically.

---

### 2026-03-18 — Planning Docs Reorganized into development/ccxt/

**Changes:**
- `docs/plan-task.md` → `development/ccxt/plan-task.md` — 6-phase execution plan (CCXT integration, MCP expansion, SDK, battles, frontend, launch). Moved out of docs/ because it is internal execution tracking, not user-facing documentation.
- `docs/ccxt_resarch_report.md` → `development/ccxt/ccxt_resarch_report.md` — CCXT integration analysis and research report. Moved for the same reason.
- `docs/CLAUDE.md` — Removed both files from the docs inventory; logged the move.

**Decisions:**
- Internal planning and research documents live under `development/` (not `docs/`). `docs/` is for user-facing and external-audience documentation only. This keeps the docs inventory clean and avoids confusion for future agents reading `docs/CLAUDE.md`.

---

### 2026-03-18 — Phase 2 Complete: MCP Server Expansion (12 → 43 Tools)

**Changes:**
- `src/mcp/tools.py` — Expanded from 12 to 43 tools. Added 31 new tools across 5 categories: backtesting (8), market + trading (7), agent management (6), battles (6), account + analytics (4). Added `TOOL_COUNT` constant, `_call_api_text()` for plain-text responses, `_text_content()` helper.
- `src/mcp/server.py` — Updated tool count references from 12 to 43.
- `src/mcp/__init__.py` — Updated docstring tool count from 12 to 43.
- `src/mcp/CLAUDE.md` — Completely rewritten to document all 43 tools with categories, parameters, and return shapes.
- `tests/unit/test_mcp_tools.py` — Expanded from 67 to 142 tests; all 43 tools now covered.
- `docs/plan-task.md` — Phase 2 marked COMPLETE with all acceptance criteria checked.

**Decisions:**
- All 31 new tools are thin wrappers over existing REST endpoints — no new backend logic needed. Keeps the MCP layer simple and consistent with the REST API as the single source of truth.
- `cancel_all_orders` and `reset_account` include client-side confirmation guards to prevent accidental destructive calls.
- `get_agent_skill` returns plain text (not JSON) via the new `_call_api_text` helper, since the skill document is Markdown prose, not structured data.

**Learnings:**
- Adding `TOOL_COUNT = 43` as a module constant makes it easy to assert in tests and keep server.py in sync with tools.py without manual counting.

---

### 2026-03-18 — Wallet Bug Fix + Live E2E Script

**Changes:**
- **Bug fix: Wallet showing 100% USDT** — `asset-list.tsx`, `asset-distribution.tsx`, and `allocation-pie-chart.tsx` relied exclusively on WebSocket prices. When WS hadn't streamed `ticker_all` data, all non-USDT assets showed $0 → USDT appeared as 100%. Fixed by adding REST price fallback (`GET /market/prices`, 30s polling via TanStack Query).
- **New script: `scripts/e2e_full_scenario_live.py`** — Full 8-phase E2E against live backend: register, login, create 3 agents, 25 trades, 6 backtests, 1 battle, analytics, account management. All data persists in DB and is visible in the UI. Supports `--skip-backtest`, `--skip-battle`, `--email`.
- **CLAUDE.md updates** — `scripts/CLAUDE.md`, `Frontend/src/hooks/CLAUDE.md`, `Frontend/src/components/CLAUDE.md`, `Frontend/CLAUDE.md` all updated with dual-source price pattern and new script.

**E2E Results (live backend):**
- 101 passed, 5 failed out of 106 steps
- GammaBot trades: risk manager correctly blocked oversized positions (position_limit_exceeded) — expected behavior
- Battle historical mode: 500 INTERNAL_ERROR on create — **open bug, needs investigation**
- Default credentials: `e2e_trader@agentexchange.io` / `Tr@d1ng_S3cur3_2026!`

**Decisions:**
- Design decision #13: **Dual-source price pattern** — components that compute asset USDT values must use WS prices as primary and REST `/market/prices` as fallback. WebSocket-only is unreliable for initial page loads.

**Learnings:**
- WebSocket-only price sources break on initial load / slow connections — always have REST fallback
- Battle service has unresolved bug with historical mode configuration

---

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
