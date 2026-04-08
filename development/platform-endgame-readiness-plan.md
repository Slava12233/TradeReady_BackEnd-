---
type: plan
tags:
  - platform
  - strategy
  - endgame
  - infrastructure
  - roadmap
date: 2026-04-07
status: active
audience: development team
---

# Platform Endgame Readiness Plan

> 7 platform improvements to make TradeReady ready for external AI trading agents to do automated strategy discovery.

**Context:** The platform is infrastructure ("AWS for trading agents"). The AI trading agent will be a **separate project**. These 7 improvements make the platform the best possible gym, arena, and execution layer for any external AI agent.

**Source:** CTO advisory session 2026-04-07. C-level report at `development/C-level_reports/platform-strategy-infrastructure-report-2026-04-07.md`.

**Key Architectural Decision:** The `agent/` folder in this repo is a reference implementation only. The production AI trading agent will be a separate repository. This plan focuses exclusively on platform-side improvements.

---

## What Exists Today

| Service | Status | Key Numbers |
|---------|--------|-------------|
| Real-Time Market Data | Production | 600+ USDT pairs, <1ms Redis lookups |
| Backtesting Engine | Production | In-memory sandbox, no look-ahead bias |
| Battle System | Production | Live + historical modes, ranking |
| Order Execution | Production | Market/Limit/Stop/TP, 8-step risk validation |
| Strategy Registry | Production | CRUD, versioning, multi-episode testing |
| Gymnasium Environments | Production | 7 envs, 5 reward functions, 3 wrappers |
| Multi-Agent Management | Production | Isolated wallets, API keys, risk profiles |
| REST API | Production | 100+ endpoints |
| Python SDK | Production | 37+ methods (sync + async + WebSocket) |
| MCP Server | Production | 58 tools over stdio |
| Frontend | Production | Next.js 16, full dashboard |

---

## The 7 Improvements

### Overview

| # | Improvement | Phase | Est. Effort | Impact |
|---|------------|-------|-------------|--------|
| 1 | Optimized Batch Backtesting API | 1 | 2-3 days | 100-500x RL training speedup |
| 2 | Deflated Sharpe Ratio Service | 1 | 1-2 days | Rejects >99% overfitted strategies |
| 3 | Market Data Indicators API | 1 | 1-2 days | Eliminates duplicate feature code |
| 4 | Strategy Comparison API | 2 | 1 day | Enables automated winner selection |
| 5 | Enhanced Gymnasium Environments | 2 | 2-3 days | More flexible RL training |
| 6 | Webhooks for Strategy Events | 2 | 3-4 days | Event-driven agent architectures |
| 7 | SDK Examples & Documentation | 3 | 2 days | Onboarding for external agents |

### Dependency Graph

```
Phase 1 (Week 1-2) — all three are independent, can be built in parallel:
  [1] Batch Backtesting ──┐
  [2] Deflated Sharpe ────┤── no dependencies between them
  [3] Indicators API ─────┘

Phase 2 (Week 3-4) — depends on Phase 1:
  [4] Strategy Comparison ←── uses deflated Sharpe from [2]
  [5] Gym Enhancements   ←── uses batch step from [1]
  [6] Webhooks            ←── standalone (triggers wired to existing code)

Phase 3 (Week 5) — depends on Phase 1 + 2:
  [7] SDK Examples ←── demonstrates all features from [1]-[6]
```

---

## Phase 1 — Core Agent Infrastructure (Week 1-2)

---

### Improvement 1: Optimized Batch Backtesting API

**Problem:** RL training makes 500K+ individual HTTP calls (one `POST /step` per candle). The Gymnasium environment calls the backtest API once per candle — this HTTP overhead is the #1 bottleneck for agent training speed.

**Current state:** `step_batch()` exists in `src/backtesting/engine.py:369-405` and the route at `src/api/routes/backtest.py:205-219`, but it just loops `step()` internally with full per-step overhead: snapshots every 60 steps, DB writes every 500 steps, full `PortfolioSummary` computation each iteration.

**Solution:** A new `step_batch_fast()` engine method + API endpoint that optimizes the inner loop:
- Defer snapshot capture to only fills + final step (skip every-60-steps modulo)
- Single DB progress write at the end of the batch (skip every-500-steps)
- Skip intermediate `get_portfolio()` calls — compute once at end
- Accumulate order fills into a flat list without constructing `StepResult` per step

**Expected result:** 500K candles / 500 per batch = ~1,000 HTTP calls. **100-500x throughput improvement** for RL training.

**New dataclass:**

```python
@dataclass(frozen=True, slots=True)
class BatchStepResult:
    virtual_time: datetime
    step: int
    total_steps: int
    progress_pct: Decimal
    prices: dict[str, Decimal]
    orders_filled: list[OrderResult]  # aggregated from all sub-steps
    portfolio: PortfolioSummary       # computed once at end
    is_complete: bool
    remaining_steps: int
    steps_executed: int               # how many steps were actually taken
```

**New engine method:**

```python
async def step_batch_fast(
    self, session_id: str, steps: int, db: AsyncSession,
    *, include_intermediate_trades: bool = False,
) -> BatchStepResult:
```

**New API endpoint:**

```
POST /api/v1/backtest/{session_id}/step/batch/fast
Body: { "steps": 500, "include_intermediate_trades": false }
Response: BatchStepFastResponse
```

**Gymnasium integration:** Add `batch_size: int = 1` constructor param to `base_trading_env.py`. When `batch_size > 1`, `step()` calls `/step/batch/fast` instead of `/step`.

**Files to modify:**

| File | Change |
|------|--------|
| `src/backtesting/engine.py` | Add `BatchStepResult` dataclass + `step_batch_fast()` method |
| `src/api/routes/backtest.py` | Add new endpoint |
| `src/api/schemas/backtest.py` | Add `BacktestStepBatchFastRequest` + `BatchStepFastResponse` |
| `tradeready-gym/tradeready_gym/envs/base_trading_env.py` | Add `batch_size` param, use fast endpoint |
| `sdk/agentexchange/client.py` | Add `batch_step_fast()` |
| `sdk/agentexchange/async_client.py` | Add `batch_step_fast()` |

**Files to create:**

| File | Purpose |
|------|---------|
| `tests/unit/test_batch_step_fast.py` | Unit tests for engine method |
| `tests/integration/test_batch_step_fast_api.py` | API endpoint tests |

**Tasks:**
- [ ] Add `BatchStepResult` dataclass to `src/backtesting/engine.py`
- [ ] Implement `step_batch_fast()` in `BacktestEngine`
- [ ] Add `POST /backtest/{session_id}/step/batch/fast` endpoint
- [ ] Add request/response schemas
- [ ] Add `batch_step_fast()` to SDK sync + async clients
- [ ] Update gym `base_trading_env.py` with `batch_size` param
- [ ] Write unit tests
- [ ] Write integration tests

---

### Improvement 2: Deflated Sharpe Ratio as a Platform Service

**Problem:** When an external agent tests thousands of strategy variants (autoresearch), it will find strategies that look profitable purely by chance. With 1,000 backtests, you're almost guaranteed to find strategies with Sharpe > 2.0 that are complete overfitting. No multiple-testing correction exists on the platform.

**Current state:** `src/metrics/calculator.py` computes raw `sharpe_ratio`. `StrategyTestRun.results` is JSONB — can add fields without a DB migration.

**Solution:** Implement the Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio as both:
1. A standalone REST endpoint any agent can call
2. Auto-computed when strategy tests complete (stored in results JSONB)

**The math (Bailey & Lopez de Prado 2014):**

```
Given:
  SR_observed  = observed Sharpe ratio
  N           = number of strategy trials
  T           = number of return observations
  γ           = skewness of returns
  κ           = excess kurtosis of returns

Step 1: Expected maximum Sharpe under null hypothesis (all strategies are noise)
  E[max(SR)] ≈ √(2 * ln(N)) * (1 - γ_euler / (2 * ln(N))) + γ_euler / √(2 * ln(N))
  where γ_euler ≈ 0.5772 (Euler-Mascheroni constant)

Step 2: Variance of observed Sharpe
  Var(SR_hat) = (1/T) * (1 - γ * SR + ((κ - 1) / 4) * SR²)

Step 3: Deflated Sharpe test statistic
  DSR = (SR_observed - E[max(SR)]) / √(Var(SR_hat))

Step 4: p-value via standard normal CDF
  p_value = Φ(DSR)

  is_significant = p_value > 0.95 (strategy genuinely profitable at 95% confidence)
```

**Key design decision:** Pure-Python normal CDF using Abramowitz & Stegun rational approximation (accurate to 7.5e-8). No scipy dependency.

**New REST endpoint:**

```
POST /api/v1/metrics/deflated-sharpe
Body: {
  "returns": [0.01, -0.005, 0.02, ...],  // daily/candle returns
  "num_trials": 100,                       // how many strategies were tested
  "annualization_factor": 252              // optional, default 252 (daily)
}
Response: {
  "observed_sharpe": 1.85,
  "expected_max_sharpe": 2.31,
  "deflated_sharpe": -0.72,
  "p_value": 0.24,
  "is_significant": false,               // THIS strategy is likely overfitted
  "num_trials": 100,
  "num_returns": 504,
  "skewness": -0.15,
  "kurtosis": 3.82
}
```

**Auto-compute on test completion:** In `src/strategies/test_aggregator.py`, after computing standard metrics, if `len(episode_sharpes) >= 2`, compute deflated Sharpe and store in `results["deflated_sharpe"]`. The `num_trials` defaults to the number of strategy versions that have been tested for this strategy.

**Files to create:**

| File | Purpose |
|------|---------|
| `src/metrics/deflated_sharpe.py` | Core implementation: `compute_deflated_sharpe()`, `DeflatedSharpeResult`, pure-Python normal CDF |
| `src/api/routes/metrics.py` | REST endpoint: `POST /api/v1/metrics/deflated-sharpe` |
| `src/api/schemas/metrics.py` | Pydantic v2 request/response schemas |
| `tests/unit/test_deflated_sharpe.py` | Unit tests with reference values |
| `tests/integration/test_metrics_api.py` | API endpoint tests |

**Files to modify:**

| File | Change |
|------|--------|
| `src/main.py` | Register metrics router |
| `src/strategies/test_aggregator.py` | Auto-compute on test completion |
| `sdk/agentexchange/client.py` | Add `compute_deflated_sharpe()` |
| `sdk/agentexchange/async_client.py` | Add `compute_deflated_sharpe()` |

**Tasks:**
- [ ] Create `src/metrics/deflated_sharpe.py` with Bailey & Lopez de Prado formula
- [ ] Create `src/api/routes/metrics.py` with POST endpoint
- [ ] Create `src/api/schemas/metrics.py` with request/response schemas
- [ ] Register metrics router in `src/main.py`
- [ ] Auto-compute in `src/strategies/test_aggregator.py` on test completion
- [ ] Add `compute_deflated_sharpe()` to SDK clients
- [ ] Write unit tests (validate against known reference values)
- [ ] Write integration tests

---

### Improvement 3: Market Data Indicators API

**Problem:** Every external agent re-implements RSI, MACD, Bollinger Bands, etc. The platform already has a working `IndicatorEngine` in `src/strategies/indicators.py` with 7 indicators — it's just not exposed via REST API.

**Current state:** `IndicatorEngine` computes 15 values per symbol (RSI, MACD line/signal/histogram, SMA-20/50, EMA-12/26, Bollinger upper/mid/lower, ADX, ATR, volume MA, current price). Uses rolling deque buffers with max 200 candles. Only used internally by `StrategyExecutor`.

**Solution:** Expose indicators as a REST API. Agent sends a symbol and gets back computed indicator values. Cached in Redis (30-second TTL for live data).

**New REST endpoints:**

```
GET /api/v1/market/indicators/{symbol}
  Query params:
    indicators: comma-separated list (e.g., "rsi_14,macd_hist,bb_width")
    lookback: number of historical candles to feed (default 200, range 14-500)

  Response: {
    "symbol": "BTCUSDT",
    "timestamp": "2026-04-07T12:00:00Z",
    "candles_used": 200,
    "indicators": {
      "rsi_14": 45.2,
      "macd_line": 0.003,
      "macd_signal": 0.001,
      "macd_hist": 0.002,
      "sma_20": 67450.50,
      "sma_50": 66800.00,
      "ema_12": 67500.25,
      "ema_26": 67200.10,
      "bb_upper": 68100.00,
      "bb_mid": 67450.50,
      "bb_lower": 66800.00,
      "adx_14": 28.5,
      "atr_14": 450.00,
      "volume_ma_20": 1250000.0,
      "price": 67500.00
    }
  }

GET /api/v1/market/indicators/available
  Response: { "indicators": ["rsi_14", "macd_line", "macd_signal", ...] }
```

**Implementation flow:**
1. Validate symbol format (`^[A-Z]{2,10}USDT$`)
2. Check Redis cache: `indicators:{symbol}:{sorted_indicator_hash}` (30s TTL)
3. On cache miss: query last N 1-minute candles from TimescaleDB
4. Feed candles through a fresh `IndicatorEngine` instance
5. Filter result to requested indicators (or return all if omitted)
6. Cache in Redis, return response

**Auth:** Falls under `/api/v1/market/*` public prefix — no auth changes needed.

**Files to create:**

| File | Purpose |
|------|---------|
| `src/api/routes/indicators.py` | REST endpoints |
| `src/api/schemas/indicators.py` | Pydantic v2 schemas |
| `tests/unit/test_indicators_api.py` | Unit tests |
| `tests/integration/test_indicators_endpoint.py` | Integration tests |

**Files to modify:**

| File | Change |
|------|--------|
| `src/main.py` | Register indicators router |
| `sdk/agentexchange/client.py` | Add `get_indicators()` |
| `sdk/agentexchange/async_client.py` | Add `get_indicators()` |

**Tasks:**
- [ ] Create `src/api/routes/indicators.py` with GET endpoints
- [ ] Create `src/api/schemas/indicators.py`
- [ ] Implement: fetch candles → IndicatorEngine → Redis cache
- [ ] Add `GET /api/v1/market/indicators/available` (static list)
- [ ] Register router in `src/main.py`
- [ ] Add `get_indicators()` to SDK clients
- [ ] Write unit + integration tests

---

## Phase 2 — Platform Experience (Week 3-4)

---

### Improvement 4: Strategy Comparison API Enhancement

**Problem:** Current `compare_versions` endpoint at `GET /strategies/{id}/compare-versions?v1=1&v2=2` only compares 2 versions of the **same** strategy. An agent running autoresearch needs to compare N **different** strategies and rank them.

**Solution:** New endpoint that accepts a list of strategy IDs, fetches their latest test results, normalizes metrics, ranks them, and returns a winner with recommendation.

**New REST endpoint:**

```
POST /api/v1/strategies/compare
Body: {
  "strategy_ids": ["uuid-1", "uuid-2", "uuid-3", ...],  // 2-10 strategies
  "ranking_metric": "sharpe_ratio"                        // optional, default "sharpe_ratio"
}
Response: {
  "strategies": [
    {
      "strategy_id": "uuid-2",
      "name": "BTC MA Crossover v3",
      "version": 3,
      "rank": 1,
      "metrics": { "sharpe": 1.85, "max_drawdown": 8.2, "win_rate": 62.5, "roi_pct": 14.3 },
      "deflated_sharpe": { "p_value": 0.97, "is_significant": true }
    },
    ...
  ],
  "winner": "uuid-2",
  "recommendation": "BTC MA Crossover v3 ranks first by Sharpe ratio (1.85) and passes the Deflated Sharpe test (p=0.97). Consider deploying."
}
```

**Files to modify:**

| File | Change |
|------|--------|
| `src/api/routes/strategies.py` | Add `POST /api/v1/strategies/compare` |
| `src/api/schemas/strategies.py` | Add comparison request/response schemas |
| `src/strategies/service.py` | Add `compare_strategies()` method |
| `sdk/agentexchange/client.py` | Add `compare_strategies()` |
| `sdk/agentexchange/async_client.py` | Add `compare_strategies()` |

**Files to create:**

| File | Purpose |
|------|---------|
| `tests/unit/test_strategy_comparison.py` | Unit tests |

**Tasks:**
- [ ] Add `POST /api/v1/strategies/compare` endpoint
- [ ] Add `StrategyComparisonRequest` + `StrategyComparisonResponse` schemas
- [ ] Add `compare_strategies()` to service layer
- [ ] Add SDK methods
- [ ] Write tests

---

### Improvement 5: Enhanced Gymnasium Environments

**Problem:** Portfolio env hardcoded to BTC/ETH/SOL. Fees hardcoded at 0.1%. No fast mode for same-process training.

**Solutions:**

**5a. Configurable fee model:**
- Add `fee_rate: Decimal` param to `BacktestSandbox.__init__()` (currently hardcoded `_FEE_FRACTION = Decimal("0.001")`)
- Thread through: `BacktestConfig` → `BacktestCreateRequest` schema → API route → gym env constructor
- Default remains `0.001` — no breaking change

**5b. Configurable portfolio env:**
- Register `TradeReady-Portfolio-Custom-v0` in `tradeready-gym/__init__.py`
- `MultiAssetTradingEnv` already accepts `symbols` param — just needs a registration entry
- Users pass `symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]` etc.

**5c. Native batch stepping:**
- Already covered by Improvement 1 — gym env uses `batch_size` param

**5d. Headless mode (in-process, no HTTP):**
- Create `tradeready-gym/tradeready_gym/envs/headless_env.py`
- Imports platform source directly (`from src.backtesting.engine import BacktestEngine` etc.)
- Creates engine, replayer, sandbox in-process during `reset()`
- Calls engine methods directly in `step()` — zero HTTP overhead
- Requires DB connection string (for price data)
- Register as `TradeReady-BTC-Headless-v0`

**Files to modify:**

| File | Change |
|------|--------|
| `src/backtesting/sandbox.py` | `fee_rate` param in `__init__()` |
| `src/backtesting/engine.py` | `fee_rate` in `BacktestConfig`, pass to sandbox |
| `src/api/schemas/backtest.py` | `fee_rate` field in `BacktestCreateRequest` |
| `src/api/routes/backtest.py` | Pass `fee_rate` to config |
| `tradeready-gym/tradeready_gym/__init__.py` | Register custom + headless envs |
| `tradeready-gym/tradeready_gym/envs/base_trading_env.py` | `fee_rate` constructor param |
| `tradeready-gym/tradeready_gym/envs/multi_asset_env.py` | Accept `symbols` kwarg |

**Files to create:**

| File | Purpose |
|------|---------|
| `tradeready-gym/tradeready_gym/envs/headless_env.py` | Headless env (no HTTP) |
| `tradeready-gym/tests/test_headless_env.py` | Tests |
| `tradeready-gym/tests/test_configurable_fees.py` | Tests |

**Tasks:**
- [ ] Add `fee_rate` param to `BacktestSandbox`, thread through engine → API → gym
- [ ] Register `TradeReady-Portfolio-Custom-v0`
- [ ] Create headless env (`headless_env.py`)
- [ ] Write tests

---

### Improvement 6: Webhooks for Strategy Events

**Problem:** External agents must poll API endpoints to check if backtests, tests, or battles are done. No push notifications exist. No webhook infrastructure at all.

**Solution:** Full webhook system with HMAC-signed payloads, retry logic, and 4 event types.

**Supported events:**
- `backtest.completed` — fired from `BacktestEngine.complete()`
- `strategy.test.completed` — fired from `aggregate_test_results()` Celery task
- `strategy.deployed` — fired from `StrategyService.deploy()`
- `battle.completed` — fired from battle completion flow

**Database model:**

```python
class WebhookSubscription(Base):
    __tablename__ = "webhook_subscriptions"

    id: Mapped[UUID]                     # PK
    account_id: Mapped[UUID]             # FK → accounts
    url: Mapped[str]                     # Webhook URL (max 2048)
    events: Mapped[list]                 # JSONB array of event names
    secret: Mapped[str]                  # HMAC-SHA256 signing key
    description: Mapped[str | None]      # Optional label
    active: Mapped[bool]                 # Default True
    failure_count: Mapped[int]           # Default 0
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    last_triggered_at: Mapped[datetime | None]
```

**REST endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/v1/webhooks` | Create subscription (returns HMAC secret once) |
| GET | `/api/v1/webhooks` | List subscriptions |
| GET | `/api/v1/webhooks/{id}` | Get detail |
| PUT | `/api/v1/webhooks/{id}` | Update (url, events, active) |
| DELETE | `/api/v1/webhooks/{id}` | Delete |
| POST | `/api/v1/webhooks/{id}/test` | Send test event |

**Dispatcher flow:**
1. Event occurs (e.g., backtest completes)
2. `fire_event(account_id, "backtest.completed", payload, db)` called
3. Queries active `WebhookSubscription` rows where event in `events` array
4. For each subscription: enqueue Celery task `dispatch_webhook`
5. Task sends POST to `url` with HMAC-SHA256 signature in `X-Webhook-Signature` header
6. 10-second HTTP timeout, 3 retries with exponential backoff (10s, 30s, 60s)
7. Increment `failure_count` after max retries; auto-disable after 10 consecutive failures

**Files to create:**

| File | Purpose |
|------|---------|
| `alembic/versions/023_add_webhook_subscriptions.py` | DB migration |
| `src/webhooks/__init__.py` | Package marker |
| `src/webhooks/dispatcher.py` | `fire_event()` function |
| `src/tasks/webhook_tasks.py` | `dispatch_webhook` Celery task |
| `src/api/routes/webhooks.py` | 6 REST endpoints |
| `src/api/schemas/webhooks.py` | Pydantic v2 schemas |
| `tests/unit/test_webhook_dispatcher.py` | Unit tests |
| `tests/unit/test_webhook_task.py` | Unit tests |
| `tests/integration/test_webhooks_api.py` | Integration tests |

**Files to modify:**

| File | Change |
|------|--------|
| `src/database/models.py` | Add `WebhookSubscription` model |
| `src/main.py` | Register webhooks router |
| `src/backtesting/engine.py` | Fire `backtest.completed` in `complete()` |
| `src/tasks/strategy_tasks.py` | Fire `strategy.test.completed` |
| `src/strategies/service.py` | Fire `strategy.deployed` in `deploy()` |
| `src/tasks/celery_app.py` | Register new task module |
| `sdk/agentexchange/client.py` | Add webhook CRUD methods |
| `sdk/agentexchange/async_client.py` | Add webhook CRUD methods |

**Tasks:**
- [ ] Add `WebhookSubscription` model to `src/database/models.py`
- [ ] Create migration `023_add_webhook_subscriptions.py`
- [ ] Create `src/webhooks/dispatcher.py` with `fire_event()`
- [ ] Create `src/tasks/webhook_tasks.py` with HMAC signing + retries
- [ ] Create `src/api/routes/webhooks.py` (6 endpoints)
- [ ] Create `src/api/schemas/webhooks.py`
- [ ] Wire event triggers in engine, strategy tasks, and service
- [ ] Register router in `src/main.py`
- [ ] Add SDK webhook CRUD methods
- [ ] Write unit + integration tests

---

## Phase 3 — Documentation (Week 5)

---

### Improvement 7: SDK Examples & Documentation

**Problem:** No example projects showing how to build an agent on top of the platform. The `agent/` folder is a reference implementation but too complex for onboarding new agent developers.

**Solution:** Create 5 standalone example scripts that demonstrate the platform's key capabilities.

**Examples to create:**

| File | What It Demonstrates |
|------|---------------------|
| `sdk/examples/basic_backtest.py` | Create session → batch step fast → get results → print metrics |
| `sdk/examples/rl_training.py` | PPO training with Stable-Baselines3 + TradeReady-Portfolio-v0 gym env + batch stepping |
| `sdk/examples/genetic_optimization.py` | Create 10 strategy variants → test each → deflated Sharpe filter → compare → deploy winner |
| `sdk/examples/strategy_tester.py` | Create strategy → create version → run multi-episode test → check DSR → deploy if significant |
| `sdk/examples/webhook_integration.py` | Register webhook → start local HTTP server → kick off backtest → wait for completion event |

Each example should be:
- Self-contained (single file, runnable with `python examples/basic_backtest.py`)
- Well-commented (explain what each step does)
- Uses real SDK methods (not mocked)
- Includes error handling
- Has a `if __name__ == "__main__"` block

**Tasks:**
- [ ] Create `sdk/examples/basic_backtest.py`
- [ ] Create `sdk/examples/rl_training.py`
- [ ] Create `sdk/examples/genetic_optimization.py`
- [ ] Create `sdk/examples/strategy_tester.py`
- [ ] Create `sdk/examples/webhook_integration.py`
- [ ] Update `sdk/README.md` with example descriptions and quickstart

---

## Summary

```
Phase 1 (Week 1-2): Foundation — make the platform FAST and SAFE
  ├── [1] Batch Backtesting  → 100-500x RL training speedup
  ├── [2] Deflated Sharpe    → reject overfitted strategies
  └── [3] Indicators API     → eliminate duplicate feature code

Phase 2 (Week 3-4): Experience — make the platform SMART and EVENT-DRIVEN
  ├── [4] Strategy Compare   → automated winner selection
  ├── [5] Gym Enhancements   → flexible RL training
  └── [6] Webhooks           → event-driven agent architectures

Phase 3 (Week 5): Onboarding — make the platform EASY TO USE
  └── [7] SDK Examples       → onboarding for external agent projects
```

**Total scope:** ~29 new files, ~20 modified files, ~5 weeks of focused work.

**No breaking changes.** All improvements are purely additive. Existing APIs, schemas, and SDK methods remain unchanged. New features use sensible defaults (fee_rate=0.001, batch_size=1).

**Verification after each improvement:**
1. `ruff check src/ tests/` — zero lint errors
2. `mypy src/` — type check passes
3. `pytest tests/unit/` — all tests pass
4. `pytest tests/integration/` — all tests pass
5. Manual test via Swagger UI at `http://localhost:8000/docs`
6. SDK example script runs end-to-end

---

*Plan created: 2026-04-07*
*Task board: `development/tasks/platform-endgame-readiness/README.md`*
*C-level report: `development/C-level_reports/platform-strategy-infrastructure-report-2026-04-07.md`*
