# TradeReady Strategy & Gym System — Complete Development Plan

> **Version:** 1.0 | **Date:** March 18, 2026
> **Stack:** Python 3.12+ | FastAPI | Celery | TimescaleDB | Redis | Next.js 16
> **Estimated Total Effort:** ~7 weeks (Backend ~5 weeks, UI ~2 weeks)
> **Dependencies:** Backtesting engine (BT-1 ✅), Python SDK (Phase 4 ✅), Frontend (UI-1 through UI-6 ✅)
> **Goal:** Build a closed-loop system where agents create strategies, test them at scale, read results, iterate, and deploy — all through the API.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [Database Schema](#3-database-schema)
4. [Phase STR-1: Strategy Registry](#4-phase-str-1-strategy-registry)
5. [Phase STR-2: Server-Side Strategy Executor](#5-phase-str-2-server-side-strategy-executor)
6. [Phase STR-3: Gymnasium Wrapper Package](#6-phase-str-3-gymnasium-wrapper-package)
7. [Phase STR-4: MCP Tools & skill.md](#7-phase-str-4-mcp-tools--skillmd)
8. [Phase STR-5: Training Run Aggregation](#8-phase-str-5-training-run-aggregation)
9. [Phase STR-UI-1: Strategy & Training Pages](#9-phase-str-ui-1-strategy--training-pages)
10. [Phase STR-UI-2: Integration & Polish](#10-phase-str-ui-2-integration--polish)
11. [Testing Strategy](#11-testing-strategy)
12. [File Inventory](#12-file-inventory)
13. [Complete Task Checklist](#13-complete-task-checklist)

---

## 1. System Overview

### What We're Building

A closed-loop strategy development system with three entry points for agents:

1. **LLM agents** (Claude, GPT, LangChain, CrewAI) — create strategies as JSON definitions via API/MCP, trigger server-side testing, read results, iterate
2. **RL agents** (PPO, DQN via Stable-Baselines3) — train through the Gymnasium interface, results auto-save to database
3. **Hybrid** — RL trains the strategy, LLM monitors and adjusts parameters

### The Closed Loop

```
Agent creates strategy v1 (JSON definition)
  → Agent triggers test (POST /strategies/{id}/test)
    → Backend runs N backtest episodes via Celery
      → Results aggregated and saved to DB
        → Agent reads results (GET /strategies/{id}/test-results)
          → Agent reasons about what to improve
            → Agent creates strategy v2 (POST /strategies/{id}/versions)
              → Agent tests v2, compares v1 vs v2
                → Agent deploys winner to live trading
                  → Agent monitors, eventually re-tests → loop continues
```

### How the Two Agent Types Connect

```
                    ┌───────────────────────────────────┐
                    │       TradeReady Backend           │
                    │                                   │
                    │  ┌─────────────────────────────┐  │
                    │  │    Strategy Registry         │  │
                    │  │    (DB: strategies,          │  │
                    │  │     versions, test_runs)     │  │
                    │  └──────────┬──────────────────┘  │
                    │             │                      │
                    │    ┌────────┴────────┐             │
                    │    │                 │             │
                    │    ▼                 ▼             │
                    │  ┌──────────┐  ┌───────────────┐  │
                    │  │ Strategy │  │  Backtest      │  │
                    │  │ Executor │  │  Engine        │  │
                    │  │ (Celery) │  │  (existing)    │  │
                    │  └──────────┘  └───────┬───────┘  │
                    │                        │          │
                    └────────────────────────┼──────────┘
                                             │
                         ┌───────────────────┼───────────────┐
                         │                   │               │
                    ┌────▼─────┐    ┌────────▼──────┐  ┌────▼─────┐
                    │ REST API │    │ Gym Wrapper   │  │ MCP      │
                    │ /strat/* │    │ (PyPI pkg)    │  │ Server   │
                    └────┬─────┘    └───────┬───────┘  └────┬─────┘
                         │                  │               │
                    ┌────▼─────┐    ┌───────▼───────┐  ┌───▼──────┐
                    │ LLM      │    │ RL Agents     │  │ Claude   │
                    │ Agents   │    │ (SB3, RLlib)  │  │ Desktop  │
                    │ (skill)  │    │               │  │          │
                    └──────────┘    └───────────────┘  └──────────┘
```

---

## 2. Architecture

### New Backend Components

| Component | Purpose | Key Files |
|---|---|---|
| **Strategy Registry** | CRUD for strategies + versions | `src/strategies/service.py`, `src/strategies/models.py` |
| **Strategy Executor** | Reads JSON definition, makes trading decisions | `src/strategies/executor.py` |
| **Indicator Engine** | Computes RSI, MACD, Bollinger, etc. from candle data | `src/strategies/indicators.py` |
| **Test Orchestrator** | Manages multi-episode test runs via Celery | `src/strategies/test_orchestrator.py` |
| **Test Aggregator** | Combines episode results into summary metrics | `src/strategies/test_aggregator.py` |
| **Training Run Tracker** | Groups Gym episodes into runs, tracks learning curves | `src/training/tracker.py` |
| **Strategy API Routes** | REST endpoints for strategy lifecycle | `src/api/routes/strategies.py` |
| **Training API Routes** | REST endpoints for training run observation | `src/api/routes/training.py` |
| **Gym Wrapper** | Gymnasium-compatible env (separate PyPI package) | `tradeready-gym/` |

### Dependency Direction

```
Routes → Schemas + Services
  Strategy Service → Strategy Repo + Test Orchestrator + Executor
    Test Orchestrator → BacktestEngine (existing) + Strategy Executor
      Strategy Executor → Indicator Engine + Sandbox (existing)
        Indicator Engine → pure numpy calculations (no dependencies)
```

---

## 3. Database Schema

### Migration: `006_strategy_tables.py`

```sql
-- Strategies: the top-level entity
CREATE TABLE strategies (
    strategy_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id      UUID NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    name            VARCHAR(100) NOT NULL,
    description     TEXT,
    current_version INT NOT NULL DEFAULT 1,
    status          VARCHAR(20) NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'testing', 'validated', 'deployed', 'archived')),
    deployed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_strategies_account ON strategies(account_id);
CREATE INDEX idx_strategies_status ON strategies(account_id, status);

-- Strategy Versions: each iteration of a strategy's trading rules
CREATE TABLE strategy_versions (
    version_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID NOT NULL REFERENCES strategies(strategy_id) ON DELETE CASCADE,
    version         INT NOT NULL,
    definition      JSONB NOT NULL,          -- the actual trading rules
    change_notes    TEXT,                     -- what changed from previous version
    parent_version  INT,                     -- null for v1
    status          VARCHAR(20) NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'testing', 'validated', 'deployed', 'rejected')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(strategy_id, version)
);
CREATE INDEX idx_sv_strategy ON strategy_versions(strategy_id);

-- Strategy Test Runs: each time a strategy version is tested
CREATE TABLE strategy_test_runs (
    test_run_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID NOT NULL REFERENCES strategies(strategy_id) ON DELETE CASCADE,
    version         INT NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'queued'
                    CHECK (status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    config          JSONB NOT NULL,          -- episodes, date_range, etc.
    episodes_total  INT NOT NULL,
    episodes_completed INT NOT NULL DEFAULT 0,
    results         JSONB,                   -- aggregated results when complete
    recommendations JSONB,                   -- auto-generated improvement suggestions
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_str_strategy ON strategy_test_runs(strategy_id, version);

-- Links test runs to individual backtest sessions
CREATE TABLE strategy_test_episodes (
    test_run_id     UUID NOT NULL REFERENCES strategy_test_runs(test_run_id) ON DELETE CASCADE,
    episode_number  INT NOT NULL,
    session_id      UUID NOT NULL REFERENCES backtest_sessions(session_id) ON DELETE CASCADE,
    roi_pct         NUMERIC(10,4),
    sharpe_ratio    NUMERIC(10,4),
    max_drawdown_pct NUMERIC(10,4),
    total_trades    INT,
    reward_sum      NUMERIC(20,8),
    completed_at    TIMESTAMPTZ,
    PRIMARY KEY (test_run_id, episode_number)
);

-- Training runs: groups Gym API episodes (created by the Gym wrapper)
CREATE TABLE training_runs (
    run_id          VARCHAR(64) PRIMARY KEY,  -- gym_run_{uuid}
    account_id      UUID NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE,
    strategy_id     UUID REFERENCES strategies(strategy_id) ON DELETE SET NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running', 'completed', 'cancelled')),
    config          JSONB NOT NULL,          -- symbol, timeframe, reward_function, etc.
    episodes_total  INT NOT NULL DEFAULT 0,
    episodes_completed INT NOT NULL DEFAULT 0,
    learning_curve  JSONB,                   -- sampled: {episodes: [], rewards: [], roi: []}
    aggregate_stats JSONB,                   -- computed on completion
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);
CREATE INDEX idx_tr_account ON training_runs(account_id);

-- Links training runs to individual backtest sessions
CREATE TABLE training_episodes (
    run_id          VARCHAR(64) NOT NULL REFERENCES training_runs(run_id) ON DELETE CASCADE,
    episode_number  INT NOT NULL,
    session_id      UUID NOT NULL REFERENCES backtest_sessions(session_id) ON DELETE CASCADE,
    roi_pct         NUMERIC(10,4),
    sharpe_ratio    NUMERIC(10,4),
    max_drawdown_pct NUMERIC(10,4),
    total_trades    INT,
    reward_sum      NUMERIC(20,8),
    completed_at    TIMESTAMPTZ,
    PRIMARY KEY (run_id, episode_number)
);
```

---

## 4. Phase STR-1: Strategy Registry

**Estimated Effort:** 5–7 days
**Goal:** Full CRUD for strategies and versions, stored in database, accessible via REST API

### Backend Files

| File | Purpose |
|---|---|
| `alembic/versions/006_strategy_tables.py` | Migration for all strategy + training tables |
| `src/strategies/__init__.py` | Package init |
| `src/strategies/models.py` | Pydantic models for strategy definitions |
| `src/strategies/service.py` | Business logic: create, version, validate, deploy |
| `src/database/repositories/strategy_repo.py` | DB operations for strategies + versions |
| `src/api/schemas/strategies.py` | Request/response Pydantic schemas |
| `src/api/routes/strategies.py` | REST endpoints |

### API Endpoints

```
POST   /api/v1/strategies                         → create strategy
GET    /api/v1/strategies                         → list all strategies
GET    /api/v1/strategies/{id}                    → get strategy + current version
PUT    /api/v1/strategies/{id}                    → update metadata (name, status)
DELETE /api/v1/strategies/{id}                    → archive strategy

POST   /api/v1/strategies/{id}/versions           → create new version
GET    /api/v1/strategies/{id}/versions           → list all versions
GET    /api/v1/strategies/{id}/versions/{v}       → get specific version

POST   /api/v1/strategies/{id}/deploy             → deploy to live trading
POST   /api/v1/strategies/{id}/undeploy           → stop live trading
```

### Strategy Definition Schema

The `definition` JSONB supports these fields:

```python
class StrategyDefinition(BaseModel):
    """The trading rules that define a strategy."""
    
    # What to trade
    pairs: list[str]                           # ["BTCUSDT", "ETHUSDT"]
    timeframe: str = "1h"                      # candle interval
    
    # When to enter (all conditions must be true)
    entry_conditions: dict[str, Any]           # {"rsi_14_below": 30, "volume_above_ma20": true}
    
    # When to exit (any condition triggers)
    exit_conditions: dict[str, Any]            # {"stop_loss_pct": 5.0, "take_profit_pct": 10.0}
    
    # How much to trade
    position_size_pct: Decimal = Decimal("10") # % of balance per trade
    max_positions: int = 3                     # max simultaneous positions
    
    # Optional filters
    filters: dict[str, Any] | None = None      # {"min_24h_volume_usdt": 1000000}
    
    # For RL-trained strategies
    model_type: str | None = None              # "rl_model" for trained agents
    model_reference: str | None = None         # training run ID or model path
```

### Supported Conditions

The executor will recognize these condition keys:

**Entry conditions:**
- `rsi_14_below`, `rsi_14_above` — RSI(14) threshold
- `macd_cross_up`, `macd_cross_down` — MACD signal crossover
- `price_above_sma_N`, `price_below_sma_N` — Price vs N-period SMA
- `price_above_ema_N`, `price_below_ema_N` — Price vs N-period EMA
- `bollinger_below_lower`, `bollinger_above_upper` — Bollinger Band breakout
- `volume_above_ma_N` — Volume exceeds N-period average
- `adx_above` — ADX(14) trending filter
- `atr_pct_above` — ATR as % of price (volatility filter)

**Exit conditions:**
- `stop_loss_pct` — Exit at N% loss from entry
- `take_profit_pct` — Exit at N% gain from entry
- `trailing_stop_pct` — Exit at N% drop from peak since entry
- `rsi_14_above`, `rsi_14_below` — RSI-based exit
- `max_hold_candles` — Time-based exit after N candles
- `macd_cross_down`, `macd_cross_up` — MACD-based exit

---

## 5. Phase STR-2: Server-Side Strategy Executor

**Estimated Effort:** 7–10 days
**Goal:** Backend can run N backtest episodes of a strategy definition automatically, aggregate results

### Backend Files

| File | Purpose |
|---|---|
| `src/strategies/indicators.py` | Pure-numpy technical indicator calculations |
| `src/strategies/executor.py` | Reads strategy definition, makes trading decisions per step |
| `src/strategies/test_orchestrator.py` | Manages test runs: spawns Celery tasks, tracks progress |
| `src/strategies/test_aggregator.py` | Combines episode results into summary + recommendations |
| `src/strategies/recommendation_engine.py` | Analyzes results, generates improvement suggestions |
| `src/database/repositories/test_run_repo.py` | DB operations for test runs + episodes |
| `src/tasks/strategy_test.py` | Celery tasks for running test episodes |
| `src/api/routes/strategy_tests.py` | REST endpoints for triggering and reading tests |
| `src/api/schemas/strategy_tests.py` | Request/response schemas for test endpoints |

### API Endpoints

```
POST   /api/v1/strategies/{id}/test               → trigger test run
GET    /api/v1/strategies/{id}/tests               → list all test runs
GET    /api/v1/strategies/{id}/tests/{test_id}     → get test status + results
POST   /api/v1/strategies/{id}/tests/{test_id}/cancel → cancel running test
GET    /api/v1/strategies/{id}/test-results        → latest test results (shortcut)
GET    /api/v1/strategies/{id}/compare-versions    → compare v1 vs v2 results
```

### Indicator Engine

```python
# src/strategies/indicators.py
"""Pure-numpy technical indicator calculations. No external TA-Lib dependency."""

import numpy as np
from collections import deque

class IndicatorEngine:
    """Computes technical indicators from price history."""
    
    def __init__(self, max_history: int = 200):
        self._prices: dict[str, deque] = {}   # symbol → price history
        self._volumes: dict[str, deque] = {}  # symbol → volume history
    
    def update(self, symbol: str, ohlcv: dict):
        """Feed new candle data."""
        if symbol not in self._prices:
            self._prices[symbol] = deque(maxlen=self.max_history)
            self._volumes[symbol] = deque(maxlen=self.max_history)
        self._prices[symbol].append(float(ohlcv["close"]))
        self._volumes[symbol].append(float(ohlcv.get("volume", 0)))
    
    def compute(self, symbol: str) -> dict:
        """Compute all indicators for a symbol. Returns dict of indicator values."""
        prices = np.array(self._prices.get(symbol, []))
        volumes = np.array(self._volumes.get(symbol, []))
        if len(prices) < 2:
            return {}
        
        result = {}
        result["rsi_14"] = self._rsi(prices, 14)
        result["macd_line"], result["macd_signal"], result["macd_hist"] = self._macd(prices)
        result["sma_20"] = self._sma(prices, 20)
        result["sma_50"] = self._sma(prices, 50)
        result["ema_12"] = self._ema(prices, 12)
        result["ema_26"] = self._ema(prices, 26)
        result["bb_upper"], result["bb_middle"], result["bb_lower"] = self._bollinger(prices)
        result["adx"] = self._adx(prices, 14)
        result["atr"] = self._atr(prices, 14)
        result["volume_ma_20"] = self._sma(volumes, 20) if len(volumes) >= 20 else None
        result["current_price"] = prices[-1]
        result["current_volume"] = volumes[-1] if len(volumes) > 0 else 0
        return result
    
    # Private methods: _rsi, _macd, _sma, _ema, _bollinger, _adx, _atr
    # All pure numpy, no external dependencies
```

### Strategy Executor

```python
# src/strategies/executor.py
"""Reads a strategy definition and makes trading decisions at each backtest step."""

class StrategyExecutor:
    def __init__(self, definition: dict, indicator_engine: IndicatorEngine):
        self.entry = definition.get("entry_conditions", {})
        self.exit = definition.get("exit_conditions", {})
        self.pairs = definition.get("pairs", [])
        self.position_size_pct = Decimal(str(definition.get("position_size_pct", 10)))
        self.max_positions = definition.get("max_positions", 3)
        self.indicators = indicator_engine
    
    def decide(self, step_result: dict) -> list[dict]:
        """Given a backtest step result, return list of orders to place."""
        orders = []
        prices = step_result["prices"]
        portfolio = step_result["portfolio"]
        positions = portfolio.get("positions", [])
        
        # Update indicators with new price data
        for symbol, price_data in prices.items():
            self.indicators.update(symbol, price_data)
        
        # Check exits first (risk management takes priority)
        for position in positions:
            if self._should_exit(position):
                orders.append({
                    "symbol": position["symbol"],
                    "side": "sell",
                    "type": "market",
                    "quantity": str(position["quantity"]),
                })
        
        # Check entries (only if under max_positions limit)
        current_position_count = len(positions)
        for symbol in self.pairs:
            if current_position_count >= self.max_positions:
                break
            if self._has_position(symbol, positions):
                continue
            if self._should_enter(symbol):
                quantity = self._calculate_quantity(symbol, prices, portfolio)
                if quantity > 0:
                    orders.append({
                        "symbol": symbol,
                        "side": "buy",
                        "type": "market",
                        "quantity": str(quantity),
                    })
                    current_position_count += 1
        
        return orders
    
    def _should_enter(self, symbol: str) -> bool:
        """Check all entry conditions for a symbol."""
        ind = self.indicators.compute(symbol)
        if not ind:
            return False
        for condition, value in self.entry.items():
            if not self._evaluate_condition(condition, value, ind):
                return False
        return True  # all conditions passed
    
    def _should_exit(self, position: dict) -> bool:
        """Check any exit condition for a position."""
        symbol = position["symbol"]
        ind = self.indicators.compute(symbol)
        entry_price = float(position["avg_entry_price"])
        current_price = ind.get("current_price", entry_price)
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
        
        # Stop loss
        if "stop_loss_pct" in self.exit:
            if pnl_pct <= -float(self.exit["stop_loss_pct"]):
                return True
        
        # Take profit
        if "take_profit_pct" in self.exit:
            if pnl_pct >= float(self.exit["take_profit_pct"]):
                return True
        
        # Indicator-based exits
        for condition, value in self.exit.items():
            if condition in ("stop_loss_pct", "take_profit_pct", "trailing_stop_pct", "max_hold_candles"):
                continue  # handled above or separately
            if self._evaluate_condition(condition, value, ind):
                return True
        
        return False
    
    def _evaluate_condition(self, condition: str, value, indicators: dict) -> bool:
        """Evaluate a single condition against current indicators."""
        if condition == "rsi_14_below":
            return indicators.get("rsi_14", 50) < float(value)
        elif condition == "rsi_14_above":
            return indicators.get("rsi_14", 50) > float(value)
        elif condition == "volume_above_ma20":
            vol = indicators.get("current_volume", 0)
            vol_ma = indicators.get("volume_ma_20")
            return vol_ma is not None and vol > vol_ma
        elif condition == "adx_above":
            return indicators.get("adx", 0) > float(value)
        elif condition == "macd_cross_up":
            return indicators.get("macd_hist", 0) > 0
        elif condition == "macd_cross_down":
            return indicators.get("macd_hist", 0) < 0
        elif condition == "bollinger_below_lower":
            price = indicators.get("current_price", 0)
            lower = indicators.get("bb_lower", 0)
            return price < lower if lower else False
        elif condition == "bollinger_above_upper":
            price = indicators.get("current_price", 0)
            upper = indicators.get("bb_upper", float("inf"))
            return price > upper
        elif condition.startswith("price_above_sma_"):
            period = int(condition.split("_")[-1])
            sma = indicators.get(f"sma_{period}")
            return sma is not None and indicators["current_price"] > sma
        elif condition.startswith("price_below_sma_"):
            period = int(condition.split("_")[-1])
            sma = indicators.get(f"sma_{period}")
            return sma is not None and indicators["current_price"] < sma
        return False
```

### Test Orchestrator (Celery)

```python
# src/strategies/test_orchestrator.py
"""Manages multi-episode test runs."""

class TestOrchestrator:
    async def start_test(self, strategy_id, version, config) -> str:
        """Create a test run and spawn Celery tasks for each episode."""
        # 1. Create test_run record in DB
        # 2. For each episode: create Celery task that:
        #    a. Creates a backtest session with randomized dates
        #    b. Creates StrategyExecutor from strategy definition
        #    c. Runs the backtest loop: step → executor.decide() → place orders → step
        #    d. Saves episode results to strategy_test_episodes
        #    e. Updates test_run progress
        # 3. Final Celery task: aggregate all episode results
```

### Recommendation Engine

```python
# src/strategies/recommendation_engine.py
"""Analyzes test results and generates improvement suggestions."""

def generate_recommendations(test_results: dict, by_pair: dict, episodes: list) -> list[str]:
    """Returns list of actionable improvement suggestions."""
    recs = []
    
    # Pair performance disparity
    if by_pair:
        best = max(by_pair.items(), key=lambda x: x[1]["avg_roi"])
        worst = min(by_pair.items(), key=lambda x: x[1]["avg_roi"])
        if best[1]["avg_roi"] - worst[1]["avg_roi"] > 5:
            recs.append(
                f"{worst[0]} significantly underperforms ({worst[1]['avg_roi']:.1f}% avg ROI) "
                f"vs {best[0]} ({best[1]['avg_roi']:.1f}%). Consider removing {worst[0]}."
            )
    
    # Win rate analysis
    if test_results.get("win_rate", 0) < 50:
        recs.append("Win rate below 50%. Consider tightening entry conditions or widening take-profit.")
    
    # Drawdown vs stop loss
    avg_dd = test_results.get("avg_max_drawdown_pct", 0)
    if avg_dd > 15:
        recs.append(f"Average max drawdown is {avg_dd:.1f}% — consider tightening stop loss.")
    
    # ... more rules
    return recs
```

---

## 6. Phase STR-3: Gymnasium Wrapper Package

**Estimated Effort:** 5–7 days
**Goal:** PyPI package `tradeready-gym` providing Gymnasium-compatible environments

### Package Structure

```
tradeready-gym/                          # Separate repository
├── tradeready_gym/
│   ├── __init__.py                      # Environment registration
│   ├── envs/
│   │   ├── base_trading_env.py          # Core: reset/step/close → TradeReady API
│   │   ├── single_asset_env.py          # TradeReady-{SYMBOL}-v0
│   │   ├── multi_asset_env.py           # TradeReady-Portfolio-v0
│   │   └── live_env.py                  # TradeReady-Live-v0
│   ├── spaces/
│   │   ├── action_spaces.py             # 5 presets (discrete → continuous → portfolio)
│   │   └── observation_builders.py      # Builds numpy arrays from API responses
│   ├── rewards/
│   │   ├── pnl_reward.py                # Simple equity delta
│   │   ├── sharpe_reward.py             # Risk-adjusted
│   │   ├── sortino_reward.py            # Downside-risk-adjusted
│   │   ├── drawdown_penalty_reward.py   # PnL minus drawdown penalty
│   │   └── custom_reward.py             # User-extensible base class
│   ├── wrappers/
│   │   ├── feature_engineering.py       # Add technical indicators to observation
│   │   ├── normalization.py             # Normalize observations to [-1, 1]
│   │   └── batch_step.py               # N steps per action (reduce HTTP calls)
│   └── utils/
│       ├── api_client.py                # Wraps SDK for Gym use
│       ├── indicators.py                # Client-side RSI, MACD, Bollinger
│       └── training_tracker.py          # Reports episodes to /training/runs API
├── examples/                            # 10 example scripts
├── tests/                               # Unit + integration + compliance tests
├── pyproject.toml
└── README.md
```

### Key: Training Run Tracking

The Gym wrapper automatically reports training progress to the backend:

```python
# tradeready_gym/utils/training_tracker.py
class TrainingTracker:
    """Reports Gym training episodes to TradeReady backend."""
    
    def __init__(self, client, config):
        self.run_id = f"gym_run_{uuid4().hex[:12]}"
        # Register training run on first episode
        client.post("/training/runs", {
            "run_id": self.run_id,
            "config": config,
        })
    
    def report_episode(self, episode_num, session_id, metrics):
        """Called after each episode completes."""
        client.post(f"/training/runs/{self.run_id}/episodes", {
            "episode_number": episode_num,
            "session_id": session_id,
            "roi_pct": metrics["roi_pct"],
            "sharpe_ratio": metrics["sharpe_ratio"],
            "reward_sum": metrics["reward_sum"],
        })
    
    def complete(self):
        """Called when training ends."""
        client.post(f"/training/runs/{self.run_id}/complete")
```

This is what makes Gym training episodes visible in the UI and queryable via API.

---

## 7. Phase STR-4: MCP Tools & skill.md

**Estimated Effort:** 2–3 days
**Goal:** Expose strategy + training endpoints through MCP and document in skill.md

### New MCP Tools (add to existing `src/mcp/tools.py`)

```python
# Strategy management (7 tools)
create_strategy          # "Create a trading strategy with entry/exit rules"
get_strategies           # "List all your trading strategies"
get_strategy             # "Get strategy details, current version, and test results"
create_strategy_version  # "Save an improved version with new trading rules"
get_strategy_versions    # "See version history and what changed"
deploy_strategy          # "Deploy a tested strategy to live trading"
undeploy_strategy        # "Stop live trading with a strategy"

# Strategy testing (5 tools)
run_strategy_test        # "Test a strategy across N episodes. Returns test_id"
get_test_status          # "Check test progress and partial results"
get_test_results         # "Get full test results with recommendations"
compare_versions         # "Compare two strategy versions side by side"
get_strategy_recommendations  # "Get AI-generated improvement suggestions"

# Training observation (3 tools)
get_training_runs        # "List all RL training runs with metrics"
get_training_run_detail  # "Get full detail for an RL training run"
compare_training_runs    # "Compare multiple training runs"
```

### skill.md Additions

Add two new sections to `docs/skill.md`:

1. **Strategy Development Cycle** — full workflow with all endpoints, condition definitions, example walkthrough of creating → testing → improving → deploying
2. **For RL Agent Developers** — short pointer to `pip install tradeready-gym` + how to query training results via API

---

## 8. Phase STR-5: Training Run Aggregation

**Estimated Effort:** 3–4 days
**Goal:** Backend endpoints for observing Gym training runs

### API Endpoints

```
POST   /api/v1/training/runs                      → register new training run (called by Gym wrapper)
POST   /api/v1/training/runs/{id}/episodes         → report episode result (called by Gym wrapper)
POST   /api/v1/training/runs/{id}/complete          → mark run complete (called by Gym wrapper)
GET    /api/v1/training/runs                       → list all training runs
GET    /api/v1/training/runs/{id}                  → full detail + learning curve + episodes
GET    /api/v1/training/runs/{id}/learning-curve   → learning curve data with metric/window params
GET    /api/v1/training/compare                    → compare multiple runs
```

### Backend Files

| File | Purpose |
|---|---|
| `src/training/__init__.py` | Package init |
| `src/training/tracker.py` | Service: create runs, record episodes, compute curves |
| `src/database/repositories/training_repo.py` | DB operations for training_runs + training_episodes |
| `src/api/routes/training.py` | REST endpoints |
| `src/api/schemas/training.py` | Request/response schemas |

### Learning Curve Computation

```python
def compute_learning_curve(episodes: list, metric: str, window: int) -> dict:
    """Compute smoothed learning curve from episode results."""
    values = [getattr(ep, metric) for ep in sorted(episodes, key=lambda e: e.episode_number)]
    smoothed = rolling_mean(values, window)
    return {
        "episode_numbers": list(range(1, len(values) + 1)),
        "raw_values": values,
        "smoothed_values": smoothed,
        "metric": metric,
        "window": window,
    }
```

---

## 9. Phase STR-UI-1: Strategy & Training Pages

**Estimated Effort:** 5–7 days
**Goal:** UI pages for strategies and training runs

### New Pages

| Route | Page | Purpose |
|---|---|---|
| `/strategies` | Strategy List | All strategies with status, latest test results, deploy state |
| `/strategies/[id]` | Strategy Detail | Version history, test results, comparison, deploy button view |
| `/training` | Training Runs List | All training runs with learning curve sparklines |
| `/training/[run_id]` | Training Run Detail | Full learning curve, episode table, best/worst episodes |

### New Components (17 total)

**Strategy components** (`src/components/strategies/`):

| # | Component | File |
|---|---|---|
| 1 | Strategy list table | `strategy-list-table.tsx` |
| 2 | Strategy status badge | `strategy-status-badge.tsx` |
| 3 | Strategy detail header | `strategy-detail-header.tsx` |
| 4 | Version history timeline | `version-history.tsx` |
| 5 | Strategy definition viewer | `definition-viewer.tsx` |
| 6 | Test results summary | `test-results-summary.tsx` |
| 7 | Version comparison | `version-comparison.tsx` |
| 8 | Recommendations card | `recommendations-card.tsx` |

**Training components** (`src/components/training/`):

| # | Component | File |
|---|---|---|
| 9 | Active training card | `active-training-card.tsx` |
| 10 | Learning curve sparkline | `learning-curve-sparkline.tsx` |
| 11 | Completed runs table | `completed-runs-table.tsx` |
| 12 | Run header | `run-header.tsx` |
| 13 | Run summary cards | `run-summary-cards.tsx` |
| 14 | Learning curve chart (full) | `learning-curve-chart.tsx` |
| 15 | Episode highlight card | `episode-highlight-card.tsx` |
| 16 | Episodes table | `episodes-table.tsx` |
| 17 | Run comparison view | `run-comparison-view.tsx` |

### New Hooks (7 total)

| Hook | File | Purpose |
|---|---|---|
| `useStrategies` | `use-strategies.ts` | List all strategies |
| `useStrategyDetail` | `use-strategy-detail.ts` | Strategy + versions + test results |
| `useTrainingRuns` | `use-training-runs.ts` | List training runs, polls every 10s |
| `useActiveTrainingRun` | `use-active-training-run.ts` | Active run stats, polls every 2s |
| `useTrainingRunDetail` | `use-training-run-detail.ts` | Full run detail + episodes |
| `useLearningCurve` | `use-learning-curve.ts` | Learning curve with metric/window params |
| `useTrainingCompare` | `use-training-compare.ts` | Compare multiple runs |

---

## 10. Phase STR-UI-2: Integration & Polish

**Estimated Effort:** 3–4 days
**Goal:** Wire into existing UI, handle edge cases, responsive design

### Tasks

- Add "Strategies" and "Training" to sidebar navigation
- Add strategy status card to main dashboard page
- Add training status card to main dashboard page
- Filter Gym episodes from backtest list page (default hidden)
- Sidebar badges when tests or training runs are active
- Empty states for all zero-data scenarios
- Mobile responsive pass on all 4 new pages
- Loading skeletons for all new pages
- Error boundaries and API error handling
- Update `UIcontext.md`, `UItasks.md`, `UIdevelopmentProgress.md`

---

## 11. Testing Strategy

### Unit Tests (Backend)

| Test File | What It Tests |
|---|---|
| `tests/unit/test_indicator_engine.py` | RSI, MACD, Bollinger, SMA, EMA, ADX computations |
| `tests/unit/test_strategy_executor.py` | Condition evaluation, entry/exit logic, position sizing |
| `tests/unit/test_recommendation_engine.py` | Recommendation generation from known result sets |
| `tests/unit/test_test_aggregator.py` | Multi-episode result aggregation |
| `tests/unit/test_strategy_service.py` | CRUD operations, version management |
| `tests/unit/test_training_tracker.py` | Episode reporting, learning curve computation |

### Integration Tests (Backend)

| Test File | What It Tests |
|---|---|
| `tests/integration/test_strategy_api.py` | Full CRUD via REST endpoints |
| `tests/integration/test_strategy_test_flow.py` | Create strategy → test → get results |
| `tests/integration/test_training_api.py` | Training run registration + episode reporting |
| `tests/integration/test_full_cycle.py` | Create → test → iterate → compare → deploy |

### Gym Package Tests

| Test File | What It Tests |
|---|---|
| `tests/test_gymnasium_compliance.py` | `check_env()` passes for all env variants |
| `tests/test_single_asset_env.py` | Reset/step/close lifecycle with mocked API |
| `tests/test_multi_asset_env.py` | Portfolio allocation action translation |
| `tests/test_rewards.py` | All 5 reward functions produce expected values |
| `tests/test_training_tracker.py` | Episodes correctly reported to backend |
| `tests/integration/test_full_training.py` | 100 steps of SB3 PPO against real API |

---

## 12. File Inventory

### Backend: New Files (27)

```
src/strategies/
├── __init__.py
├── models.py                          # Strategy definition Pydantic models
├── service.py                         # Business logic
├── executor.py                        # Strategy → trading decisions
├── indicators.py                      # Technical indicator engine (pure numpy)
├── test_orchestrator.py               # Multi-episode test management
├── test_aggregator.py                 # Result aggregation
└── recommendation_engine.py           # Improvement suggestions

src/training/
├── __init__.py
└── tracker.py                         # Training run management

src/database/repositories/
├── strategy_repo.py                   # Strategy + version DB operations
├── test_run_repo.py                   # Test run + episode DB operations
└── training_repo.py                   # Training run + episode DB operations

src/api/schemas/
├── strategies.py                      # Strategy request/response schemas
├── strategy_tests.py                  # Test run schemas
└── training.py                        # Training run schemas

src/api/routes/
├── strategies.py                      # Strategy CRUD endpoints
├── strategy_tests.py                  # Test trigger/read endpoints
└── training.py                        # Training run endpoints

src/tasks/
└── strategy_test.py                   # Celery tasks for running test episodes

alembic/versions/
└── 006_strategy_tables.py             # Migration

tests/unit/
├── test_indicator_engine.py
├── test_strategy_executor.py
├── test_recommendation_engine.py
├── test_test_aggregator.py
├── test_strategy_service.py
└── test_training_tracker.py

tests/integration/
├── test_strategy_api.py
├── test_strategy_test_flow.py
├── test_training_api.py
└── test_full_cycle.py
```

### Frontend: New Files (30)

```
src/app/(dashboard)/strategies/page.tsx
src/app/(dashboard)/strategies/loading.tsx
src/app/(dashboard)/strategies/[id]/page.tsx
src/app/(dashboard)/strategies/[id]/loading.tsx
src/app/(dashboard)/training/page.tsx
src/app/(dashboard)/training/loading.tsx
src/app/(dashboard)/training/[run_id]/page.tsx
src/app/(dashboard)/training/[run_id]/loading.tsx

src/components/strategies/
├── strategy-list-table.tsx
├── strategy-status-badge.tsx
├── strategy-detail-header.tsx
├── version-history.tsx
├── definition-viewer.tsx
├── test-results-summary.tsx
├── version-comparison.tsx
└── recommendations-card.tsx

src/components/training/
├── active-training-card.tsx
├── learning-curve-sparkline.tsx
├── completed-runs-table.tsx
├── run-header.tsx
├── run-summary-cards.tsx
├── learning-curve-chart.tsx
├── episode-highlight-card.tsx
├── episodes-table.tsx
└── run-comparison-view.tsx

src/hooks/
├── use-strategies.ts
├── use-strategy-detail.ts
├── use-training-runs.ts
├── use-active-training-run.ts
├── use-training-run-detail.ts
├── use-learning-curve.ts
└── use-training-compare.ts
```

### Gym Package: New Files (25+)

```
tradeready-gym/                        # Separate repository
├── tradeready_gym/ (15 source files)
├── tests/ (6 test files)
├── examples/ (10 example scripts)
├── pyproject.toml
├── README.md
└── CHANGELOG.md
```

---

## 13. Complete Task Checklist

### Phase STR-1: Strategy Registry (5–7 days)

- [ ] STR-1.1 — Create migration `006_strategy_tables.py` (all 6 tables)
- [ ] STR-1.2 — Create `src/strategies/models.py` (StrategyDefinition, condition schemas)
- [ ] STR-1.3 — Create `src/database/repositories/strategy_repo.py`
- [ ] STR-1.4 — Create `src/strategies/service.py` (CRUD + version management)
- [ ] STR-1.5 — Create `src/api/schemas/strategies.py`
- [ ] STR-1.6 — Create `src/api/routes/strategies.py` (8 endpoints)
- [ ] STR-1.7 — Register routes in `src/main.py`
- [ ] STR-1.8 — Update `src/dependencies.py` with new DI aliases
- [ ] STR-1.9 — Unit tests for strategy service (10+ tests)
- [ ] STR-1.10 — Integration tests for strategy API (8+ tests)

### Phase STR-2: Server-Side Strategy Executor (7–10 days)

- [ ] STR-2.1 — Create `src/strategies/indicators.py` (RSI, MACD, Bollinger, SMA, EMA, ADX, ATR)
- [ ] STR-2.2 — Create `src/strategies/executor.py` (condition evaluation + order generation)
- [ ] STR-2.3 — Create `src/strategies/test_orchestrator.py` (Celery task spawning)
- [ ] STR-2.4 — Create `src/tasks/strategy_test.py` (Celery task: run single episode)
- [ ] STR-2.5 — Create `src/strategies/test_aggregator.py` (combine episode results)
- [ ] STR-2.6 — Create `src/strategies/recommendation_engine.py`
- [ ] STR-2.7 — Create `src/database/repositories/test_run_repo.py`
- [ ] STR-2.8 — Create `src/api/schemas/strategy_tests.py`
- [ ] STR-2.9 — Create `src/api/routes/strategy_tests.py` (5 endpoints)
- [ ] STR-2.10 — Register Celery tasks in Celery beat schedule
- [ ] STR-2.11 — Unit tests for indicator engine (20+ tests, verified against known values)
- [ ] STR-2.12 — Unit tests for executor (15+ tests, condition evaluation)
- [ ] STR-2.13 — Unit tests for aggregator + recommendation engine (10+ tests)
- [ ] STR-2.14 — Integration test: create strategy → run test → verify results (end-to-end)

### Phase STR-3: Gymnasium Wrapper Package (5–7 days)

- [ ] STR-3.1 — Create `tradeready-gym/` package scaffold (pyproject.toml, structure)
- [ ] STR-3.2 — Implement `BaseTradingEnv` (reset, step, close → TradeReady API)
- [ ] STR-3.3 — Implement `SingleAssetTradingEnv` (discrete + continuous)
- [ ] STR-3.4 — Implement `MultiAssetTradingEnv` (portfolio allocation)
- [ ] STR-3.5 — Implement 5 action space presets
- [ ] STR-3.6 — Implement `ObservationBuilder` with 10+ feature options
- [ ] STR-3.7 — Implement 5 reward functions (PnL, LogReturn, Sharpe, Sortino, DrawdownPenalty)
- [ ] STR-3.8 — Implement `TrainingTracker` (auto-reports episodes to backend)
- [ ] STR-3.9 — Environment registration (gym.make works)
- [ ] STR-3.10 — Gymnasium compliance test passes (check_env)
- [ ] STR-3.11 — Unit tests (20+ tests, mocked API)
- [ ] STR-3.12 — Create 10 example scripts
- [ ] STR-3.13 — Write README.md with quickstart
- [ ] STR-3.14 — Publish to PyPI

### Phase STR-4: MCP Tools & skill.md (2–3 days)

- [ ] STR-4.1 — Add 7 strategy MCP tools to `src/mcp/tools.py`
- [ ] STR-4.2 — Add 5 strategy testing MCP tools
- [ ] STR-4.3 — Add 3 training observation MCP tools
- [ ] STR-4.4 — Unit tests for new MCP tools (15+ tests)
- [ ] STR-4.5 — Add Strategy Development Cycle section to `docs/skill.md`
- [ ] STR-4.6 — Add RL Developer section to `docs/skill.md`
- [ ] STR-4.7 — Update `docs/api_reference.md` with all new endpoints
- [ ] STR-4.8 — Update SDK (`sdk/agentexchange/`) with strategy + training methods

### Phase STR-5: Training Run Aggregation (3–4 days)

- [ ] STR-5.1 — Create `src/training/tracker.py` (service layer)
- [ ] STR-5.2 — Create `src/database/repositories/training_repo.py`
- [ ] STR-5.3 — Create `src/api/schemas/training.py`
- [ ] STR-5.4 — Create `src/api/routes/training.py` (7 endpoints)
- [ ] STR-5.5 — Learning curve computation logic
- [ ] STR-5.6 — Unit tests for training tracker (8+ tests)
- [ ] STR-5.7 — Integration tests for training API (5+ tests)

### Phase STR-UI-1: Strategy & Training Pages (5–7 days)

- [ ] STR-UI-1.1 — Add type definitions to `src/lib/types.ts`
- [ ] STR-UI-1.2 — Build 2 strategy hooks
- [ ] STR-UI-1.3 — Build 5 training hooks
- [ ] STR-UI-1.4 — Build 8 strategy components
- [ ] STR-UI-1.5 — Build 9 training components
- [ ] STR-UI-1.6 — Assemble 4 pages + 4 loading skeletons
- [ ] STR-UI-1.7 — Add sidebar nav items (Strategies, Training)

### Phase STR-UI-2: Integration & Polish (3–4 days)

- [ ] STR-UI-2.1 — Dashboard integration (strategy + training status cards)
- [ ] STR-UI-2.2 — Backtest list filter (hide Gym episodes)
- [ ] STR-UI-2.3 — Sidebar active badges
- [ ] STR-UI-2.4 — Empty states for all pages
- [ ] STR-UI-2.5 — Mobile responsive pass
- [ ] STR-UI-2.6 — Loading skeletons + error boundaries
- [ ] STR-UI-2.7 — Update project documentation files

---

**Total tasks: 82**
**Total new backend files: ~27**
**Total new frontend files: ~30**
**Total Gym package files: ~25**
**Total estimated effort: ~7 weeks**

---

*This plan can be executed sequentially (STR-1 → STR-2 → STR-3 → STR-4 → STR-5 → UI) or partially parallelized (STR-1+STR-3 in parallel, STR-2+STR-5 in parallel, UI after backend is stable).*
