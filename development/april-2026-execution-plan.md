---
type: plan
title: "April 2026 Execution Plan — From Platform Built to Platform Trading"
source: "[[C-level_reports/report-2026-04-12]]"
created: 2026-04-12
status: active
tags:
  - plan
  - execution
  - rl-training
  - ci-cd
  - frontend-testing
  - live-trading
---

# April 2026 Execution Plan

**Goal:** Move the AI Trading Agent platform from "fully built" to "actively trading and continuously validated."

**Source:** 5 recommendations from the [C-level report (2026-04-12)](C-level_reports/report-2026-04-12.md)

**Timeline:** 14 days (2026-04-12 → 2026-04-26)

---

## Executive Summary

The platform has 5,130+ tests, 127 API endpoints, 5 ML strategies, 7 gym environments, and a complete agent trading stack — but zero trained models and zero live trades. This plan closes the gap across 5 parallel tracks and 47 tasks.

| Track | Recommendation | Tasks | Days | Key Deliverable |
|-------|---------------|-------|------|-----------------|
| A | Load Historical Data | 7 | 1-2 | 12+ months of candle data for 20 pairs |
| B | PPO Training Pipeline | 9 | 2-5 | Trained PPO model with DSR validation |
| C | End-to-End Trade Loop | 8 | 5-8 | First live agent trade cycle |
| D | Frontend Test Coverage | 12 | 1-10 | vitest suite for 50+ critical components |
| E | CI/CD Pipeline | 11 | 1-5 | Full GitHub Actions gate (lint + type + test + build) |

---

## Track A: Load Historical Data (Days 1-2)

**Why first:** PPO training (Track B), regime classifier, evolutionary fitness, and backtesting all require historical candle data. Without it, everything downstream uses synthetic data or limited windows.

**Existing assets:**
- `scripts/backfill_history.py` — supports `--daily`, `--hourly`, `--resume`, `--dry-run`, `--exchange`
- `scripts/seed_pairs.py` — fetches all USDT pairs from Binance
- `candles_backfill` TimescaleDB hypertable already exists (migration applied)

### Tasks

| # | Task | Description | Depends | Agent |
|---|------|-------------|---------|-------|
| A-01 | Verify Docker services running | Ensure TimescaleDB, Redis, API are healthy via `validate_phase1.py` | — | deploy-checker |
| A-02 | Refresh trading pairs | Run `seed_pairs.py` to pick up any new Binance listings | A-01 | backend-developer |
| A-03 | Dry-run daily backfill | `backfill_history.py --daily --dry-run` — preview pair count and date ranges | A-02 | backend-developer |
| A-04 | Execute daily backfill (top 20) | `backfill_history.py --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,DOTUSDT,LINKUSDT,MATICUSDT,SHIBUSDT,LTCUSDT,UNIUSDT,ATOMUSDT,NEARUSDT,AAVEUSDT,ARBUSDT,OPUSDT,APTUSDT --interval 1d --resume` | A-03 | backend-developer |
| A-05 | Execute hourly backfill (top 5) | `backfill_history.py --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT --interval 1h --resume` — 1h data for PPO training | A-04 | backend-developer |
| A-06 | Validate data completeness | Query `candles_backfill` to confirm row counts, date ranges, and gap-free coverage for BTCUSDT 1d and 1h | A-05 | e2e-tester |
| A-07 | Document data inventory | Record pair count, date ranges, row counts in `development/data-inventory.md` | A-06 | doc-updater |

**Estimated time:** 4-8 hours (mostly backfill runtime). Daily backfill for 20 pairs from 2017 is ~2-3 hours; hourly for 5 pairs is ~3-5 hours.

---

## Track B: PPO Training Pipeline (Days 2-5)

**Why:** All 5 ML strategies are built but untrained. PPO is the first and most impactful — it validates the entire training→eval→deploy pipeline.

**Existing assets:**
- `scripts/train_ppo_btc.py` — complete training script (500K timesteps, BatchStepWrapper, NormalizationWrapper, CompositeReward, TensorBoard, OOS eval, DSR validation)
- `tradeready-gym/` — 7 environments including `TradeReady-BTC-Headless-v0` (recently fixed for connection pool exhaustion)
- `src/metrics/deflated_sharpe.py` — DSR validation endpoint

### Tasks

| # | Task | Description | Depends | Agent |
|---|------|-------------|---------|-------|
| B-01 | Verify gym installation | `pip install -e tradeready-gym/` + `pip install stable-baselines3>=2.0 tensorboard` | A-05 | ml-engineer |
| B-02 | Smoke-test headless env | Create `TradeReady-BTC-Headless-v0`, run 100 steps, confirm no connection pool errors | B-01 | ml-engineer |
| B-03 | Run PPO training (100K steps) | `python scripts/train_ppo_btc.py --timesteps 100000 --eval-episodes 3` — quick validation run | B-02 | ml-engineer |
| B-04 | Verify TensorBoard output | Check `runs/` directory for training curves: reward, episode length, policy loss | B-03 | ml-engineer |
| B-05 | Run full PPO training (500K steps) | `python scripts/train_ppo_btc.py` — full training run (est. 2-6 hours on CPU) | B-04 | ml-engineer |
| B-06 | Evaluate OOS performance | Review 10-episode OOS eval output: avg reward, Sharpe, max drawdown, win rate | B-05 | ml-engineer |
| B-07 | Validate with DSR API | Confirm DSR endpoint returns valid Deflated Sharpe Ratio for the trained model | B-06 | ml-engineer |
| B-08 | Save model artifact | Verify `models/ppo_btc_v1.zip` exists, record size and checksum (SHA-256) | B-07 | ml-engineer |
| B-09 | Document training results | Create `development/training-results-ppo-btc-v1.md` with metrics, hyperparams, and next steps | B-08 | doc-updater |

**Estimated time:** 6-10 hours (B-03: 30min, B-05: 2-6h, rest: setup/validation).

**Success criteria:**
- Model file at `models/ppo_btc_v1.zip`
- OOS Sharpe ratio > 0 (positive risk-adjusted return)
- DSR validation passes (not just lucky backtest)
- TensorBoard curves show learning (reward increasing over timesteps)

---

## Track C: End-to-End Trade Loop (Days 5-8)

**Why:** The TradingLoop has 414+ tests but has never run against a live platform instance. Integration bugs are the #1 risk for any untested end-to-end path.

**Existing assets:**
- `agent/trading/loop.py` — TradingLoop (observe→decide→execute→monitor→journal→learn)
- `agent/trading/executor.py` — TradeExecutor (SDK-backed order placement)
- `agent/strategies/risk/` — Risk Overlay strategy (VetoPipeline, DynamicSizer)
- `scripts/e2e_provision_agents.py` — provisions 5 agents with distinct risk profiles

**Prerequisites:** Track A complete (historical data loaded), Docker services running.

### Tasks

| # | Task | Description | Depends | Agent |
|---|------|-------------|---------|-------|
| C-01 | Provision test agent | Run `e2e_provision_agents.py` or create a single conservative agent via API | A-06 | e2e-tester |
| C-02 | Verify agent SDK connectivity | Use SDK client to authenticate, fetch agent balance, list available pairs | C-01 | e2e-tester |
| C-03 | Run single observe cycle | Execute one TradingLoop.observe() — confirm price data, portfolio state, and regime detection all return valid data | C-02 | ml-engineer |
| C-04 | Run single decide cycle | Execute TradingLoop.decide() with risk overlay — confirm signal generation and veto pipeline work | C-03 | ml-engineer |
| C-05 | Execute first live trade | Execute a single market buy order (minimum size) through TradingLoop.execute() | C-04 | ml-engineer |
| C-06 | Verify trade in DB + API | Confirm trade appears in `trades` table, position updated in `positions`, balance deducted | C-05 | e2e-tester |
| C-07 | Run full trade cycle | Execute complete loop: observe→decide→execute→monitor→journal→learn for 10 iterations | C-06 | ml-engineer |
| C-08 | Document integration findings | Record any bugs, latency numbers, and configuration adjustments needed | C-07 | doc-updater |

**Estimated time:** 1-2 days. Most time spent debugging integration issues.

**Success criteria:**
- At least 1 executed trade visible in DB and API
- Full 10-iteration loop completes without crash
- Journal entries recorded for each decision
- No connection pool exhaustion or session leaks

---

## Track D: Frontend Test Coverage (Days 1-10, parallel)

**Why:** 250+ .tsx components with 0 running tests. Financial data rendering (PnL, equity, positions) is especially critical — a formatting bug could mislead users.

**Existing assets:**
- `Frontend/vitest.config.ts` — vitest configured
- `Frontend/src/components/` — 130+ component files organized by domain
- `Frontend/src/hooks/` — 23 hooks with TanStack Query patterns
- `Frontend/src/lib/` — API client, utilities

### Tasks

| # | Task | Description | Depends | Agent |
|---|------|-------------|---------|-------|
| D-01 | Fix vitest setup | Ensure `npm run test` works — install missing deps, fix config issues, get 0-test green baseline | — | frontend-developer |
| D-02 | Create test utilities | Set up `test-utils.tsx` with custom render (providers: QueryClient, theme, router mocks) | D-01 | frontend-developer |
| D-03 | Test dashboard components (5) | Tests for: EquityChart, PortfolioSummary, PositionsTable, RecentOrders, DashboardLayout | D-02 | frontend-developer |
| D-04 | Test agent components (4) | Tests for: AgentCard, AgentGrid, CreateAgentModal, AgentSwitcher | D-02 | frontend-developer |
| D-05 | Test battle components (4) | Tests for: BattleCard, BattleList, BattleDetail, CreateBattleDialog | D-02 | frontend-developer |
| D-06 | Test strategy components (3) | Tests for: StrategyList, StrategyDetail, StrategyVersionHistory | D-02 | frontend-developer |
| D-07 | Test market components (3) | Tests for: MarketTable (virtual scroll), CoinDetail, OrderBook | D-02 | frontend-developer |
| D-08 | Test wallet components (3) | Tests for: BalanceCard, AssetList, DistributionChart | D-02 | frontend-developer |
| D-09 | Test shared components (5) | Tests for: PriceFlashCell, SectionErrorBoundary, LoadingSkeleton, StatusBadge, TimeAgo | D-02 | frontend-developer |
| D-10 | Test hooks (5) | Tests for: useAgent, usePortfolio, useTrades, useBattles, useWebSocket | D-02 | frontend-developer |
| D-11 | Run full frontend test suite | `npm run test` — all tests pass, collect coverage report | D-03..D-10 | test-runner |
| D-12 | Add test script to CI | Ensure `npm run test` is part of the GitHub Actions pipeline (connects to Track E) | D-11, E-05 | frontend-developer |

**Estimated time:** 5-7 days. ~32 component test files + 5 hook test files.

**Target:** 50+ test files covering critical financial data rendering and user interactions. Coverage goal: >60% of components in `dashboard/`, `agents/`, `battles/`, `strategies/`, `wallet/`.

---

## Track E: CI/CD Automated Pipeline (Days 1-5, parallel)

**Why:** Quality enforcement currently relies on manual agent runs. No automated gate blocks broken code from reaching production.

**Existing assets:**
- `.github/workflows/test.yml` — lint (ruff) + type check (mypy) + unit tests (no integration, no frontend)
- `.github/workflows/deploy.yml` — SSH deploy to production (triggers test.yml first)
- Redis service container already configured in test.yml

### Gap Analysis

| Check | Current | Needed |
|-------|---------|--------|
| ruff lint | ✅ In CI | — |
| ruff format | ✅ In CI | — |
| mypy | ✅ In CI | — |
| Unit tests | ✅ In CI (Redis only) | — |
| Integration tests | ❌ Missing | TimescaleDB service container |
| Frontend build | ❌ Missing | `npm run build` in CI |
| Frontend lint | ❌ Missing | ESLint/tsc check |
| Frontend tests | ❌ Missing | `npm run test` (after Track D) |
| Agent tests | ❌ Missing | Agent package test suite |
| Gym tests | ❌ Missing | tradeready-gym test suite |
| Dependency caching | ❌ Missing | pip + npm cache for faster runs |
| Artifact upload | ❌ Missing | Coverage reports |

### Tasks

| # | Task | Description | Depends | Agent |
|---|------|-------------|---------|-------|
| E-01 | Add TimescaleDB service | Add TimescaleDB/PostgreSQL service container to `test.yml` for integration tests | — | backend-developer |
| E-02 | Add integration test job | New job in `test.yml`: `pytest tests/integration -v --tb=short` with DB + Redis | E-01 | backend-developer |
| E-03 | Add agent test job | New job: `pytest agent/tests -v --tb=short` — runs the 2,304 agent tests | E-01 | backend-developer |
| E-04 | Add gym test job | New job: `pytest tradeready-gym/tests -v --tb=short` — runs the 159 gym tests | E-01 | backend-developer |
| E-05 | Add frontend build + lint job | New job: `npm ci && npm run build && npm run lint` | — | frontend-developer |
| E-06 | Add frontend test job | New job: `npm run test` (dependent on Track D delivering tests) | D-11 | frontend-developer |
| E-07 | Add dependency caching | `actions/cache` for pip (`~/.cache/pip`) and npm (`~/.npm`) | E-02 | backend-developer |
| E-08 | Add coverage upload | Upload pytest coverage as artifact; add coverage badge to README | E-02 | backend-developer |
| E-09 | Update deploy.yml gate | Ensure deploy waits for ALL test jobs (not just lint + unit) | E-02..E-06 | backend-developer |
| E-10 | Test pipeline on branch | Create test branch, push, verify all jobs pass | E-09 | test-runner |
| E-11 | Document CI/CD pipeline | Update `development/` docs with pipeline diagram and job descriptions | E-10 | doc-updater |

**Estimated time:** 2-3 days for backend CI, 1-2 days for frontend CI.

---

## Execution Schedule

```
Day 1-2:  ├── Track A: Data backfill (sequential, long-running)
          ├── Track D: vitest setup + test utilities (D-01, D-02)
          └── Track E: CI backend jobs (E-01..E-04, E-07, E-08)

Day 2-5:  ├── Track B: PPO training (B-01..B-05 — training is long-running)
          ├── Track D: Component tests (D-03..D-09 — parallel per domain)
          └── Track E: CI frontend jobs + deploy gate (E-05, E-09..E-11)

Day 5-7:  ├── Track B: Evaluation + DSR validation (B-06..B-09)
          ├── Track C: Agent provisioning + SDK test + first trade (C-01..C-06)
          └── Track D: Hook tests + full suite run (D-10, D-11)

Day 7-8:  ├── Track C: Full trade loop + documentation (C-07, C-08)
          └── Track D: CI integration (D-12)

Day 9-10: Final validation and documentation sweep
```

### Critical Path

```
A-04 (daily backfill) → A-05 (hourly backfill) → B-02 (smoke-test gym)
  → B-05 (full PPO training) → B-06 (OOS eval) → C-03 (first observe cycle)
  → C-05 (first live trade) → C-07 (full trade loop)
```

The critical path is **data → training → trading**. Frontend tests (Track D) and CI/CD (Track E) run in parallel and don't block the critical path.

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| Backfill takes >8 hours | Delays Track B by 1 day | Use `--resume` if interrupted; start with top 5 pairs only for PPO |
| PPO training diverges | No usable model | Run 100K-step smoke test first (B-03); tune learning rate and reward weights |
| Headless gym connection issues | Training crashes | Fixed in latest commit (881e27f); monitor with `--eval-episodes 1` first |
| TradingLoop integration bugs | Trade loop fails | Start with observe-only, then decide-only, then execute (incremental) |
| vitest setup broken | Frontend tests delayed | Fallback: manually test critical paths in browser; fix vitest in parallel |
| CI TimescaleDB flaky | False negatives | Use `--health-cmd` with retries; set generous startup timeout |

---

## Success Metrics

| Metric | Target | How to Verify |
|--------|--------|---------------|
| Historical data loaded | 20 pairs, 12+ months daily | Query `candles_backfill` row count |
| PPO model trained | `models/ppo_btc_v1.zip` exists | File exists + TensorBoard curves |
| OOS Sharpe > 0 | Positive risk-adjusted return | Training script output |
| DSR validation passes | p-value < 0.05 | DSR API response |
| First live trade | 1+ trade in DB | `SELECT COUNT(*) FROM trades WHERE agent_id = ?` |
| Full trade loop | 10 iterations complete | TradingLoop logs |
| Frontend test files | 37+ test files | `find Frontend/src -name "*.test.*" \| wc -l` |
| Frontend test pass rate | 100% | `npm run test` exit code 0 |
| CI pipeline green | All jobs pass on main | GitHub Actions status |
| CI time | < 15 minutes total | GitHub Actions run duration |

---

## Agent Assignments

| Agent | Tracks | Task Count |
|-------|--------|------------|
| ml-engineer | B, C | 11 |
| backend-developer | A, E | 10 |
| frontend-developer | D, E | 9 |
| e2e-tester | A, C | 4 |
| deploy-checker | A | 1 |
| test-runner | D, E | 2 |
| doc-updater | A, B, C, E | 4 |
| **Total** | | **47** (some tasks overlap with 6 doc tasks) |
