---
type: plan
title: "AgentExchange — Backtesting Engine Development Plan v2"
status: archived
phase: backtesting
tags:
  - plan
  - backtesting
---

# AgentExchange — Backtesting Engine Development Plan v2

> **Version:** 2.0 | **Date:** February 2026
> **Core Principle:** THE AGENT DOES EVERYTHING. The UI is a read-only window for humans to observe.
> **Goal:** Enable AI agents to autonomously create, configure, run, and analyze backtests — then decide whether to go live — all without human intervention.

---

## Table of Contents

1. [Design Philosophy: Agent-First](#1-design-philosophy-agent-first)
2. [System Architecture](#2-system-architecture)
3. [The Agent's Autonomous Workflow](#3-the-agents-autonomous-workflow)
4. [Backend: Backtesting Engine](#4-backend-backtesting-engine)
5. [Backend: API Endpoints (Agent-Facing)](#5-backend-api-endpoints-agent-facing)
6. [Backend: Database Schema](#6-backend-database-schema)
7. [Backend: Project Structure](#7-backend-project-structure)
8. [Frontend: Read-Only Observation UI](#8-frontend-read-only-observation-ui)
9. [Frontend: Components](#9-frontend-components)
10. [Frontend: Project Structure](#10-frontend-project-structure)
11. [Skill.md — The Agent's Complete Playbook](#11-skillmd--the-agents-complete-playbook)
12. [Development Phases & Tasks](#12-development-phases--tasks)
13. [Testing Strategy](#13-testing-strategy)

---

## 1. Design Philosophy: Agent-First

### The Rule

**The human may never touch the platform.** Every action — creating backtests, choosing time ranges, selecting pairs, executing trades, analyzing results, deciding to switch strategies, resetting accounts — comes from the agent through the API. The human deploys their agent, gives it an API key, and walks away.

### What the Agent Controls

- Creating backtest sessions (choosing time range, pairs, candle interval, starting balance)
- Running through historical data at its own pace
- Making all trading decisions during backtests
- Analyzing its own backtest results
- Comparing multiple backtests it ran
- Deciding whether a strategy is good enough
- Switching from backtest mode to live paper trading
- Managing its own risk parameters
- Resetting its account when it wants to start fresh
- Running multiple backtests in sequence to optimize parameters

### What the UI Shows (Read-Only)

The human opens the dashboard and sees:

- "Your agent has run 14 backtests in the last 24 hours"
- "Best performing strategy: mean_reversion_v7 with +31% ROI and 1.92 Sharpe"
- "Agent is currently running live with mean_reversion_v7"
- "Current live equity: $12,458 (+24.6% since start)"
- All the charts, trade logs, comparisons — but the human can't create, modify, or trigger anything trading-related

The only things the human does through the UI:

- Views everything (pure observation)
- Manages their account settings (API keys, email, display name)
- Sets up alert preferences (notify me when agent loses >10%)
- Views billing/subscription information
- Initially creates their account and gets API credentials (one-time setup)

### Why This Matters

This is not just a philosophical distinction — it changes the API design. Every endpoint must be designed for an autonomous AI agent as the caller, not a human clicking buttons. The agent needs:

- **Self-assessment endpoints:** "How did my last backtest perform?" "Is my current strategy better than the previous one?"
- **Comparison endpoints:** "Compare my last 5 backtests and tell me which was best"
- **Mode switching:** "I've validated my strategy via backtest, now switch me to live trading"
- **Auto-optimization:** "Run the same strategy on 5 different time periods and aggregate the results"

---

## 2. System Architecture

### The Agent's Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                     THE AUTONOMOUS AGENT                         │
│                                                                  │
│  The agent runs continuously in its own environment              │
│  (developer's server, cloud function, local machine).            │
│  It calls our API for everything.                                │
│                                                                  │
│  Agent's decision loop:                                          │
│                                                                  │
│  1. "Let me backtest my strategy against last 30 days"           │
│      → POST /backtest/create                                     │
│      → POST /backtest/{id}/start                                 │
│      → Loop: POST /backtest/{id}/step → analyze → trade          │
│      → GET /backtest/{id}/results                                │
│                                                                  │
│  2. "ROI was 18%, let me tweak parameters and try again"         │
│      → POST /backtest/create (different config)                  │
│      → ... run again ...                                         │
│      → GET /backtest/compare?sessions=id1,id2                    │
│                                                                  │
│  3. "v3 has Sharpe 1.9 vs v2's 1.4, v3 is better"              │
│      → POST /mode/switch {"mode": "live"}                        │
│      → Now trading live with virtual money                       │
│                                                                  │
│  4. "Live results match backtest expectations, keeping it"       │
│      → Continues trading live                                    │
│      → Periodically re-backtests on new data                     │
│                                                                  │
│  ALL of this happens without any human interaction.              │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           │ REST API calls
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AGENTEXCHANGE PLATFORM                         │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                    API GATEWAY                              │ │
│  │  Receives all commands from the agent via REST              │ │
│  │  Routes to: Live Trading Engine OR Backtest Engine          │ │
│  └─────────────┬───────────────────────────┬──────────────────┘ │
│                │                           │                     │
│       ┌────────▼────────┐        ┌─────────▼──────────┐        │
│       │  LIVE TRADING   │        │   BACKTEST ENGINE   │        │
│       │                 │        │                     │        │
│       │ Real-time prices│        │ Historical replay   │        │
│       │ from Binance WS │        │ from TimescaleDB    │        │
│       │                 │        │                     │        │
│       │ Virtual money   │        │ Sandboxed accounts  │        │
│       │ Real market     │        │ Simulated time      │        │
│       └────────┬────────┘        └─────────┬──────────┘        │
│                │                           │                     │
│                └──────────┬────────────────┘                     │
│                           │                                      │
│                    ┌──────▼──────┐                               │
│                    │  DATABASE   │                               │
│                    │             │                               │
│                    │ All trades  │                               │
│                    │ All results │                               │
│                    │ All metrics │                               │
│                    └──────┬──────┘                               │
│                           │                                      │
│                    ┌──────▼──────┐                               │
│                    │  READ-ONLY  │                               │
│                    │     UI      │                               │
│                    │             │                               │
│                    │ Human just  │                               │
│                    │ watches     │                               │
│                    └─────────────┘                               │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Change: Unified Account, Dual Mode

Instead of separate live and backtest systems, each agent account has a **mode**:

```
Account
├── mode: "live" | "backtest"
├── live_session (always exists, for real-time paper trading)
└── backtest_sessions[] (0 or more, for historical testing)
```

The agent can:
- Run live and backtests simultaneously (the live session continues while backtests run independently)
- Switch its primary focus between modes
- Run multiple backtests in parallel

---

## 3. The Agent's Autonomous Workflow

This is the complete lifecycle an agent follows — entirely on its own:

### Phase A: Initial Backtesting

```
Agent starts up with a strategy idea.

1. Check what historical data is available
   GET /market/data-range
   → {"earliest": "2025-01-01", "latest": "2026-02-22", "pairs_count": 647}

2. Create first backtest — recent 30 days
   POST /backtest/create
   {
     "start_time": "2026-01-23T00:00:00Z",
     "end_time": "2026-02-22T23:59:59Z",
     "starting_balance": 10000,
     "mode": "step",
     "candle_interval": "1m",
     "strategy_label": "momentum_v1"
   }
   → {"session_id": "bt_aaa..."}

3. Start and step through
   POST /backtest/bt_aaa.../start
   Loop:
     POST /backtest/bt_aaa.../step
     → agent gets prices, analyzes, trades
     → repeats until is_complete=true

4. Review results
   GET /backtest/bt_aaa.../results
   → ROI: +18%, Sharpe: 1.4, Max DD: -12%
```

### Phase B: Optimization Loop

```
Agent decides to iterate.

5. Tweak strategy, run again on same period
   POST /backtest/create
   {
     "start_time": "2026-01-23T00:00:00Z",
     "end_time": "2026-02-22T23:59:59Z",
     "starting_balance": 10000,
     "mode": "step",
     "strategy_label": "momentum_v2"
   }
   → run through...
   → GET results: ROI: +22%, Sharpe: 1.6

6. Run on a DIFFERENT time period to check robustness
   POST /backtest/create
   {
     "start_time": "2025-10-01T00:00:00Z",
     "end_time": "2025-12-31T23:59:59Z",
     "starting_balance": 10000,
     "strategy_label": "momentum_v2"
   }
   → run through...
   → GET results: ROI: +15%, Sharpe: 1.3

7. Compare all results
   GET /backtest/compare?sessions=bt_aaa,bt_bbb,bt_ccc
   → side-by-side metrics for all three runs

8. Agent decides momentum_v2 is robust enough
```

### Phase C: Go Live

```
9. Switch to live paper trading
   POST /account/mode
   {"mode": "live", "strategy_label": "momentum_v2"}

10. Agent now trades against real-time prices with virtual money
    Same endpoints but without /backtest/{id}/ prefix:
    GET /market/price/BTCUSDT → real live price
    POST /trade/order → executes against live market

11. Periodically, agent re-backtests on newest data
    (every week, creates a new backtest on last 7 days to validate)
```

### Phase D: Continuous Improvement

```
12. After 2 weeks live, agent evaluates performance
    GET /analytics/performance?period=14d
    → compares live results to backtest predictions

13. If live matches backtest: keep going
    If live underperforms: agent may:
    - Run new backtests with modified parameters
    - Switch back to a previous strategy version
    - Reset account and start fresh

14. The cycle never stops. The agent is always testing,
    comparing, and improving — autonomously.
```

---

## 4. Backend: Backtesting Engine

### Implementation: `src/backtesting/engine.py`

```python
"""
Backtest Execution Engine

The agent controls everything. This engine responds to agent commands.

Class: BacktestEngine
  - async create_session(self, account_id, config: BacktestConfig) → BacktestSession
    Agent decides: time range, pairs, interval, balance, label.
    Platform validates: time range has data, balance is reasonable.

  - async start(self, session_id) → None
    Initializes sandboxed environment. Sets virtual_clock to start_time.

  - async step(self, session_id) → StepResult
    Advance one candle. Agent calls this at its own pace.
    Returns: current prices, filled orders, portfolio, is_complete.
    Agent analyzes the StepResult and decides what to do.

  - async step_batch(self, session_id, steps: int) → BatchStepResult
    Advance multiple candles at once.
    Useful when agent wants to fast-forward (e.g., "skip to next day").
    Returns: summary of all fills, final portfolio state.

  - async get_price(self, session_id, symbol) → PriceAtTime
    Returns price at virtual_clock. Agent calls this like live price check.

  - async get_candles(self, session_id, symbol, interval, limit) → list[Candle]
    Returns candles BEFORE virtual_clock only. No future data ever.

  - async execute_order(self, session_id, order: OrderRequest) → OrderResult
    Agent places order. Executes at historical price with slippage.

  - async cancel_order(self, session_id, order_id) → bool
  - async get_balance(self, session_id) → list[Balance]
  - async get_positions(self, session_id) → list[Position]
  - async get_portfolio(self, session_id) → PortfolioSummary

  - async complete(self, session_id) → BacktestResult
    Called when virtual_clock reaches end. Persists everything.

  - async cancel(self, session_id) → BacktestResult
    Agent can cancel early if results look bad. Saves partial results.
"""
```

### Implementation: `src/backtesting/time_simulator.py`

```python
"""
Virtual Clock

Step mode ONLY for MVP. The agent controls time.
No auto-advancing "realtime" mode — it adds complexity and LLMs are too
slow for it anyway. The agent steps when it's ready.

Class: TimeSimulator
  - __init__(self, start_time, end_time, interval_seconds=60)
  - current_time → datetime
  - step() → datetime (advance by interval, return new time)
  - step_batch(n) → datetime (advance by n intervals)
  - is_complete → bool (current_time >= end_time)
  - progress_pct → float (0-100)
  - elapsed_simulated → timedelta (how much simulated time has passed)
  - remaining_steps → int (how many steps until end)
"""
```

### Implementation: `src/backtesting/data_replayer.py`

```python
"""
Historical Data Replayer

Reads from TimescaleDB continuous aggregates (candles_1m, candles_5m, etc.)

Class: DataReplayer
  - __init__(self, db_pool, pairs: list[str] | None)

  - async load_prices(self, timestamp) → dict[str, Decimal]
    Get close price for all pairs at this timestamp.
    Used by step() to return current prices to agent.

  - async load_candles(self, symbol, end_time, interval, limit) → list[Candle]
    Historical candles BEFORE end_time only.
    CRITICAL: Never return data after virtual_clock.

  - async load_ticker_24h(self, symbol, timestamp) → TickerData
    Calculate 24h stats (open, high, low, close, volume, change%)
    using candles from (timestamp - 24h) to timestamp.

  - async get_data_range() → DataRange
    Returns earliest and latest timestamps with data.
    Agent uses this to know what periods it can backtest.

  - async get_available_pairs(self, timestamp) → list[str]
    Pairs that had trading activity at this timestamp.

LOOK-AHEAD BIAS PREVENTION:
  Every single query MUST filter: WHERE bucket <= virtual_clock
  This is the #1 source of invalid backtests in quantitative finance.
  A backtest that accidentally peeks at future data produces
  unrealistically good results that fail in live trading.
  This must be enforced at the database query level, not in application code.
"""
```

### Implementation: `src/backtesting/sandbox.py`

```python
"""
Sandboxed Trading Environment

In-memory isolated trading state per backtest session.
Uses identical business logic to live OrderEngine.

Class: BacktestSandbox
  - __init__(self, session_id, starting_balance, slippage_calculator)

  State (all in-memory for speed):
    balances: dict[str, Balance]          # {asset: {available, locked}}
    positions: dict[str, Position]         # {symbol: {qty, avg_entry}}
    orders: list[Order]                    # all orders (pending + filled + cancelled)
    trades: list[Trade]                    # executed fills
    snapshots: list[Snapshot]              # equity curve points

  Methods:
    place_order(order, current_prices) → OrderResult
    cancel_order(order_id) → bool
    check_pending_orders(current_prices) → list[OrderResult]
    get_balance() → list[Balance]
    get_positions() → list[Position]
    get_portfolio(current_prices) → PortfolioSummary
    get_orders(filters) → list[Order]
    get_trades(filters) → list[Trade]
    capture_snapshot(current_prices, virtual_time) → Snapshot
    close_all_positions(current_prices) → list[Trade]
    export_results() → dict  # full state for persistence

  On completion: sandbox.export_results() → persisted to database
"""
```

---

## 5. Backend: API Endpoints (Agent-Facing)

All endpoints are called by the agent. The UI only reads data from the database.

### Data Discovery

#### GET /market/data-range
Agent checks what historical data is available before creating a backtest.

```json
{
  "earliest": "2025-01-01T00:00:00Z",
  "latest": "2026-02-22T23:59:59Z",
  "total_pairs": 647,
  "intervals_available": ["1m", "5m", "15m", "1h", "4h", "1d"],
  "data_gaps": []
}
```

### Backtest Lifecycle (Agent Controls Everything)

#### POST /backtest/create
Agent decides all parameters.

```json
{
  "start_time": "2026-01-01T00:00:00Z",
  "end_time": "2026-01-31T23:59:59Z",
  "starting_balance": 10000.00,
  "candle_interval": "1m",
  "pairs": null,
  "strategy_label": "momentum_v2"
}
```

Response:
```json
{
  "session_id": "bt_550e8400-e29b-41d4-a716-446655440000",
  "status": "created",
  "total_steps": 44640,
  "estimated_pairs": 647
}
```

#### POST /backtest/{session_id}/start
Agent starts execution when ready.

#### POST /backtest/{session_id}/step
Agent advances one candle. This is the heartbeat of the backtest.

```json
{
  "virtual_time": "2026-01-01T00:01:00Z",
  "step": 1,
  "total_steps": 44640,
  "progress_pct": 0.002,
  "prices": {
    "BTCUSDT": {"open": "42150.00", "high": "42180.00", "low": "42130.00", "close": "42165.30", "volume": "12.34"},
    "ETHUSDT": {"open": "2280.00", "high": "2285.00", "low": "2278.00", "close": "2282.50", "volume": "145.67"}
  },
  "orders_filled": [],
  "portfolio": {
    "total_equity": "10000.00",
    "available_cash": "10000.00",
    "positions": [],
    "unrealized_pnl": "0.00"
  },
  "is_complete": false,
  "remaining_steps": 44639
}
```

**This single response gives the agent everything it needs to make a decision:** current candle data for all pairs, current portfolio state, what orders filled, and progress info. The agent doesn't need to call separate /market/price or /account/balance endpoints — it's all here. But those endpoints still work for deeper analysis (historical candles, order details, etc.)

#### POST /backtest/{session_id}/step/batch
Agent fast-forwards when it doesn't need to analyze every single candle.

Request:
```json
{"steps": 60}
```

Response: same structure as step, but `orders_filled` includes ALL fills during the 60 steps, and `prices` shows the final candle.

#### POST /backtest/{session_id}/trade/order
Agent places an order during backtest. Identical format to live trading.

```json
{"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": 0.5}
```

Response: identical to live order response.

#### All other trading endpoints (same as live, scoped to session)
```
GET    /backtest/{sid}/market/price/{symbol}         → price at virtual_time
GET    /backtest/{sid}/market/prices                  → all prices at virtual_time
GET    /backtest/{sid}/market/ticker/{symbol}          → 24h stats at virtual_time
GET    /backtest/{sid}/market/candles/{symbol}         → candles BEFORE virtual_time
GET    /backtest/{sid}/trade/order/{order_id}          → order status
GET    /backtest/{sid}/trade/orders                    → all orders
GET    /backtest/{sid}/trade/orders/open               → pending orders
DELETE /backtest/{sid}/trade/order/{order_id}          → cancel order
GET    /backtest/{sid}/trade/history                   → trade log
GET    /backtest/{sid}/account/balance                 → sandbox balances
GET    /backtest/{sid}/account/positions               → sandbox positions
GET    /backtest/{sid}/account/portfolio               → sandbox portfolio summary
```

#### POST /backtest/{session_id}/cancel
Agent decides to abort early (bad results, waste of time).

Returns partial results with metrics calculated from whatever was completed.

### Results & Analysis (Agent Self-Assessment)

#### GET /backtest/{session_id}/results
Agent reviews its own performance after completion.

```json
{
  "session_id": "bt_550e...",
  "status": "completed",
  "config": {
    "start_time": "2026-01-01T00:00:00Z",
    "end_time": "2026-01-31T23:59:59Z",
    "starting_balance": "10000.00",
    "strategy_label": "momentum_v2",
    "candle_interval": "1m"
  },
  "summary": {
    "final_equity": "12458.30",
    "total_pnl": "2458.30",
    "roi_pct": "24.58",
    "total_trades": 156,
    "total_fees": "234.50",
    "duration_simulated_days": 31,
    "duration_real_seconds": 750
  },
  "metrics": {
    "sharpe_ratio": 1.85,
    "sortino_ratio": 2.31,
    "max_drawdown_pct": 8.5,
    "max_drawdown_duration_days": 3,
    "win_rate": 65.71,
    "profit_factor": 2.1,
    "avg_win": "156.30",
    "avg_loss": "-74.50",
    "best_trade": "523.00",
    "worst_trade": "-210.00",
    "avg_trade_duration_minutes": 340,
    "trades_per_day": 5.03
  },
  "by_pair": [
    {"symbol": "BTCUSDT", "trades": 45, "win_rate": 71.1, "net_pnl": "1200.00"},
    {"symbol": "ETHUSDT", "trades": 32, "win_rate": 62.5, "net_pnl": "580.00"}
  ]
}
```

#### GET /backtest/{session_id}/results/equity-curve
```json
{
  "interval": "1h",
  "snapshots": [
    {"time": "2026-01-01T00:00:00Z", "equity": "10000.00"},
    {"time": "2026-01-01T01:00:00Z", "equity": "10045.30"}
  ]
}
```

#### GET /backtest/{session_id}/results/trades
Full trade log from the backtest.

#### GET /backtest/list
Agent lists all its previous backtests to review history.

Query params: `strategy_label`, `status`, `sort_by` (roi_pct, sharpe_ratio, created_at), `limit`

```json
{
  "backtests": [
    {
      "session_id": "bt_ccc...",
      "strategy_label": "momentum_v2",
      "period": "2026-01-01 to 2026-01-31",
      "status": "completed",
      "roi_pct": 24.58,
      "sharpe_ratio": 1.85,
      "max_drawdown_pct": 8.5,
      "total_trades": 156,
      "created_at": "2026-02-23T10:30:00Z"
    },
    {
      "session_id": "bt_bbb...",
      "strategy_label": "momentum_v2",
      "period": "2025-10-01 to 2025-12-31",
      "status": "completed",
      "roi_pct": 15.20,
      "sharpe_ratio": 1.32,
      "max_drawdown_pct": 11.2,
      "total_trades": 89
    }
  ]
}
```

#### GET /backtest/compare?sessions=bt_aaa,bt_bbb,bt_ccc
Agent compares multiple backtests it ran.

```json
{
  "comparisons": [
    {
      "session_id": "bt_aaa...",
      "strategy_label": "momentum_v1",
      "roi_pct": 18.20,
      "sharpe_ratio": 1.42,
      "max_drawdown_pct": 12.3,
      "win_rate": 58.33
    },
    {
      "session_id": "bt_bbb...",
      "strategy_label": "momentum_v2",
      "roi_pct": 24.58,
      "sharpe_ratio": 1.85,
      "max_drawdown_pct": 8.5,
      "win_rate": 65.71
    }
  ],
  "best_by_roi": "bt_bbb...",
  "best_by_sharpe": "bt_bbb...",
  "best_by_drawdown": "bt_bbb...",
  "recommendation": "bt_bbb (momentum_v2) outperforms on all key metrics"
}
```

#### GET /backtest/best?metric=sharpe_ratio&strategy_label=momentum
Agent asks: "What's my best backtest ever for this strategy?"

```json
{
  "session_id": "bt_bbb...",
  "strategy_label": "momentum_v2",
  "sharpe_ratio": 1.85,
  "roi_pct": 24.58
}
```

### Mode Management

#### GET /account/mode
Agent checks its current operating mode.

```json
{
  "mode": "live",
  "live_session": {
    "started_at": "2026-02-20T00:00:00Z",
    "current_equity": "12458.30",
    "strategy_label": "momentum_v2"
  },
  "active_backtests": 1,
  "total_backtests_completed": 14
}
```

#### POST /account/mode
Agent switches between modes.

```json
{"mode": "live", "strategy_label": "momentum_v2"}
```

This doesn't stop backtests — agent can run backtests while also trading live. The `mode` simply indicates the agent's primary operating focus for dashboard display.

---

## 6. Backend: Database Schema

```sql
-- ============================================
-- BACKTEST SESSIONS
-- ============================================
CREATE TABLE backtest_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id          UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    strategy_label      VARCHAR(100),
    status              VARCHAR(20) NOT NULL DEFAULT 'created'
                        CHECK (status IN ('created','running','paused','completed','failed','cancelled')),
    candle_interval     VARCHAR(5) NOT NULL DEFAULT '1m',
    start_time          TIMESTAMPTZ NOT NULL,
    end_time            TIMESTAMPTZ NOT NULL,
    starting_balance    NUMERIC(20,8) NOT NULL DEFAULT 10000.00,
    pairs               JSONB,                              -- null = all pairs
    virtual_clock       TIMESTAMPTZ,                        -- current simulated time
    current_step        INT DEFAULT 0,
    total_steps         INT,
    progress_pct        NUMERIC(5,2) DEFAULT 0,

    -- Results (populated on completion)
    final_equity        NUMERIC(20,8),
    total_pnl           NUMERIC(20,8),
    roi_pct             NUMERIC(10,4),
    total_trades        INT,
    total_fees          NUMERIC(20,8),
    metrics             JSONB,                              -- full performance metrics

    -- Timing
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    duration_real_sec   INT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_bt_sessions_account ON backtest_sessions(account_id);
CREATE INDEX idx_bt_sessions_status ON backtest_sessions(account_id, status);
CREATE INDEX idx_bt_sessions_label ON backtest_sessions(account_id, strategy_label);
CREATE INDEX idx_bt_sessions_roi ON backtest_sessions(account_id, roi_pct DESC NULLS LAST);

-- ============================================
-- BACKTEST TRADES
-- ============================================
CREATE TABLE backtest_trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES backtest_sessions(id) ON DELETE CASCADE,
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(4) NOT NULL,
    type            VARCHAR(20) NOT NULL,
    quantity        NUMERIC(20,8) NOT NULL,
    price           NUMERIC(20,8) NOT NULL,
    quote_amount    NUMERIC(20,8) NOT NULL,
    fee             NUMERIC(20,8) NOT NULL,
    slippage_pct    NUMERIC(10,6),
    realized_pnl    NUMERIC(20,8),
    simulated_at    TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_bt_trades_session ON backtest_trades(session_id);
CREATE INDEX idx_bt_trades_session_time ON backtest_trades(session_id, simulated_at);

-- ============================================
-- BACKTEST EQUITY SNAPSHOTS
-- ============================================
CREATE TABLE backtest_snapshots (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES backtest_sessions(id) ON DELETE CASCADE,
    simulated_at    TIMESTAMPTZ NOT NULL,
    total_equity    NUMERIC(20,8) NOT NULL,
    available_cash  NUMERIC(20,8) NOT NULL,
    position_value  NUMERIC(20,8) NOT NULL,
    unrealized_pnl  NUMERIC(20,8) NOT NULL,
    realized_pnl    NUMERIC(20,8) NOT NULL,
    positions       JSONB
);

CREATE INDEX idx_bt_snapshots_session ON backtest_snapshots(session_id, simulated_at);
SELECT create_hypertable('backtest_snapshots', 'simulated_at', chunk_time_interval => INTERVAL '1 day');

-- ============================================
-- ACCOUNT MODE TRACKING
-- ============================================
ALTER TABLE accounts ADD COLUMN current_mode VARCHAR(10) DEFAULT 'live';
ALTER TABLE accounts ADD COLUMN active_strategy_label VARCHAR(100);
```

---

## 7. Backend: Project Structure

```
src/
├── backtesting/
│   ├── __init__.py
│   ├── engine.py                        # BacktestEngine — orchestrator
│   ├── time_simulator.py                # Virtual clock (step mode only)
│   ├── data_replayer.py                 # Historical candle loading from TimescaleDB
│   ├── sandbox.py                       # In-memory isolated trading environment
│   └── results.py                       # Calculate metrics on completion
│
├── api/
│   └── routes/
│       └── backtest.py                  # All backtest endpoints
│   └── schemas/
│       └── backtest.py                  # Pydantic models
│
├── database/
│   └── repositories/
│       └── backtest_repo.py             # CRUD for backtest tables
│
└── tasks/
    └── backtest_cleanup.py              # Auto-cancel stale sessions, clean old data
```

---

## 8. Frontend: Read-Only Observation UI

### Core Principle Reinforcement

The frontend has NO forms, NO buttons, NO controls related to backtesting operations. No "Create Backtest" form. No "Start" button. No parameter inputs. The agent does all of that through the API.

The frontend ONLY:
- Shows a list of backtests the agent has created
- Shows real-time progress of running backtests
- Shows results and charts of completed backtests
- Allows the human to compare backtests visually

### New Page: `/backtest`

#### List View (Default)

```
┌──────────────────────────────────────────────────────────────┐
│  🧪 BACKTESTING                                               │
│  Your agent has run 14 backtests. 1 currently running.        │
├──────────────────────────────────────────────────────────────┤
│  ACTIVE BACKTEST                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  momentum_v4  │  🔄 Running  │  67.3%                  │  │
│  │  Jan 1-31, 2026  │  Step 30,052 / 44,640               │  │
│  │  [████████████████████████████████░░░░░░░░░░░░░░] 67%  │  │
│  │  Current equity: $11,234 (+12.3%)  │  42 trades so far  │  │
│  └────────────────────────────────────────────────────────┘  │
├──────────────────────────────────────────────────────────────┤
│  COMPLETED BACKTESTS                                          │
│  Strategy       │ Period      │ ROI    │ Sharpe │ Drawdown │ Trades │
│  momentum_v3    │ Jan 1-31    │ +24.6% │ 1.85   │ -8.5%    │ 156    │ ← Best
│  momentum_v2    │ Jan 1-31    │ +18.2% │ 1.42   │ -12.3%   │ 89     │
│  momentum_v2    │ Oct-Dec '25 │ +15.2% │ 1.32   │ -11.2%   │ 120    │
│  momentum_v1    │ Jan 1-31    │ +8.5%  │ 0.95   │ -15.1%   │ 45     │
│  scalping_v1    │ Jan 1-14    │ -3.1%  │ -0.42  │ -18.4%   │ 312    │
│  ...                                                          │
│  Click any row to view detailed results                       │
├──────────────────────────────────────────────────────────────┤
│  AGENT STATUS                                                 │
│  Mode: 🟢 Live Trading  │  Strategy: momentum_v3              │
│  Live since: Feb 20     │  Live equity: $12,458 (+24.6%)      │
│  Last backtest: 2 hours ago                                   │
└──────────────────────────────────────────────────────────────┘
```

#### Running Backtest Detail (Live Progress)

```
┌──────────────────────────────────────────────────────────────┐
│  🔄 momentum_v4  │  Running  │  Step 30,052 / 44,640         │
│  Simulating: Jan 1-31, 2026  │  Currently at: Jan 21 08:52   │
│  Running for: 8m 34s real time                                │
├──────────────────────────────────────────────────────────────┤
│  PROGRESS                                                     │
│  [████████████████████████████████░░░░░░░░░░░░░░] 67.3%      │
│  Jan 1 ────────────────────── Jan 21 ────────── Jan 31        │
├──────────────────────────────────────────────────────────────┤
│  EQUITY CURVE (building in real-time)                         │
│  $11.2k ┤                              ╱──                   │
│  $10.8k ┤                    ╱────────╱                      │
│  $10.4k ┤          ╱────────╱                                │
│  $10.0k ┤──────────╱                                         │
│         └──────────────────────────────                      │
│         Jan 1        Jan 8       Jan 15    Jan 21             │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│  EQUITY  │ PnL      │ TRADES   │ WIN RATE │ MAX DD          │
│ $11,234  │ +$1,234  │   42     │  64.3%   │  -6.2%          │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│  LATEST AGENT TRADES (in simulated time)                      │
│  Jan 21 08:45  BUY  0.30 BTC @ $42,150  │ Fee: $12.65       │
│  Jan 21 06:20  SELL 2.00 SOL @ $99.80   │ PnL: +$24.30      │
│  Jan 20 22:15  BUY  1.50 ETH @ $2,305   │ Fee: $3.46        │
└──────────────────────────────────────────────────────────────┘
```

#### Completed Backtest Results

```
┌──────────────────────────────────────────────────────────────┐
│  ✅ momentum_v3  │  Completed  │  Ran in 12.5 minutes         │
│  Period: Jan 1-31, 2026  │  156 trades                        │
├──────────┬──────────┬──────────┬──────────┬─────────────────┤
│  ROI     │ SHARPE   │ MAX DD   │ WIN RATE │ PROFIT FACTOR   │
│ +24.58%  │  1.85    │  -8.5%   │  65.7%   │  2.10           │
├──────────┴──────────┴──────────┴──────────┴─────────────────┤
│                                                               │
│  FULL EQUITY CURVE                                            │
│  (reuse analytics charts — equity curve, drawdown, daily PnL) │
│                                                               │
├──────────────────────────────────────────────────────────────┤
│  PAIR PERFORMANCE                                             │
│  BTC/USDT: 45 trades, 71% win, +$1,200                       │
│  ETH/USDT: 32 trades, 63% win, +$580                         │
│  SOL/USDT: 28 trades, 57% win, +$340                         │
├──────────────────────────────────────────────────────────────┤
│  TRADE LOG                                                    │
│  (full table, same component as /trades page)                 │
└──────────────────────────────────────────────────────────────┘
```

#### Compare View

```
┌──────────────────────────────────────────────────────────────┐
│  📊 COMPARE BACKTESTS                                         │
│  Showing: momentum_v1 vs momentum_v2 vs momentum_v3          │
├──────────────────────────────────────────────────────────────┤
│  OVERLAID EQUITY CURVES                                       │
│  ── v3 (green)    ── v2 (blue)    ── v1 (gray)              │
│  -- BTC buy & hold (dashed)                                   │
│                                                               │
│  $12.5k ┤                              ╱── green             │
│  $11.5k ┤                    ╱────── blue                    │
│  $10.8k ┤          ╱───── gray                               │
│  $10.0k ┤──────────                                          │
│                                                               │
├──────────────────────────────────────────────────────────────┤
│  METRICS COMPARISON                                           │
│                  │  v1      │  v2      │  v3      │ BTC Hold │
│  ROI            │  +8.5%   │  +18.2%  │  +24.6%  │  +12.3%  │
│  Sharpe         │  0.95    │  1.42    │  1.85    │  0.82    │
│  Max Drawdown   │ -15.1%   │ -12.3%   │  -8.5%   │ -15.8%  │
│  Win Rate       │  52.1%   │  58.3%   │  65.7%   │  N/A     │
│  Trades         │  45      │  89      │  156     │  1       │
│  Profit Factor  │  1.15    │  1.65    │  2.10    │  N/A     │
│                                                               │
│  📈 Clear improvement from v1 → v2 → v3 across all metrics   │
└──────────────────────────────────────────────────────────────┘
```

The compare view auto-selects backtests with the same `strategy_label` prefix for easy version comparison. The human sees their agent getting smarter over time.

---

## 9. Frontend: Components

```
src/components/backtest/                     # ALL READ-ONLY

├── list/
│   ├── backtest-list-page.tsx               # Main page: active + completed backtests
│   ├── active-backtest-card.tsx             # Highlighted card for running backtest
│   ├── completed-backtest-table.tsx         # Table of all completed backtests
│   ├── backtest-row.tsx                     # Single row with metrics + status badge
│   ├── agent-mode-status.tsx               # Shows "Agent is live with strategy X"
│   └── backtest-list-filters.tsx            # Filter/sort by label, date, metrics

├── monitor/
│   ├── backtest-monitor-page.tsx            # Live progress of running backtest
│   ├── progress-timeline.tsx                # Timeline bar: start → current → end
│   ├── live-equity-chart.tsx                # Equity curve building in real-time
│   ├── live-stats-cards.tsx                 # Updating metrics (equity, PnL, trades, win rate)
│   ├── live-positions-table.tsx             # Agent's current positions at virtual time
│   └── live-trades-feed.tsx                 # Agent's trades at simulated timestamps

├── results/
│   ├── backtest-results-page.tsx            # Full results for completed backtest
│   ├── results-summary-cards.tsx            # ROI, Sharpe, drawdown, win rate cards
│   ├── results-equity-curve.tsx             # Full period equity chart (reuse analytics)
│   ├── results-drawdown-chart.tsx           # Drawdown visualization (reuse analytics)
│   ├── results-daily-pnl.tsx               # Daily PnL bars (reuse analytics)
│   ├── results-trade-log.tsx                # Complete trade table (reuse trades)
│   └── results-pair-breakdown.tsx           # Performance by pair

├── compare/
│   ├── backtest-compare-page.tsx            # Side-by-side comparison
│   ├── overlaid-equity-chart.tsx            # Multiple equity curves on one chart
│   ├── compare-metrics-table.tsx            # Metrics side by side
│   └── compare-auto-selector.tsx            # Auto-groups by strategy_label

└── shared/
    ├── backtest-status-badge.tsx             # created/running/completed/failed
    ├── virtual-time-display.tsx              # "Simulating: Jan 15 14:30"
    ├── strategy-label-badge.tsx              # Colored tag for strategy name
    └── improvement-indicator.tsx             # "↑ 35% better than v2" callout
```

### Key Component Patterns

```typescript
/**
 * ActiveBacktestCard — shown at top of list when a backtest is running
 *
 * Data source: GET /backtest/{session_id}/status (polled every 2 seconds)
 *
 * Shows:
 * - Strategy label and period
 * - Progress bar with simulated date markers
 * - Current equity and PnL (live updating)
 * - Trade count so far
 * - Real-time elapsed
 *
 * When backtest completes:
 * - Card transitions to "Completed" state with celebration effect
 * - Auto-refreshes the completed backtests table below
 */

/**
 * CompareAutoSelector — auto-groups backtests for comparison
 *
 * Logic:
 * - Groups backtests by strategy_label prefix (e.g., "momentum_v1", "momentum_v2", "momentum_v3")
 * - Shows dropdown: "Compare momentum versions (3)" | "Compare scalping versions (2)"
 * - Auto-adds BTC buy-and-hold as benchmark
 * - Human clicks a group → sees overlaid equity curves and metrics table
 *
 * The human never creates comparisons — the UI auto-suggests based on
 * the strategy labels the AGENT chose when creating backtests.
 */

/**
 * ImprovementIndicator — shows strategy evolution
 *
 * When viewing backtest results, if there are previous backtests with
 * the same strategy_label prefix, show callouts like:
 * "↑ Sharpe improved 30% from v2 (1.42) to v3 (1.85)"
 * "↑ Drawdown reduced from -12.3% to -8.5%"
 * "↓ Trade count increased from 89 to 156 (more active)"
 *
 * This helps the human understand how their agent is improving
 * its own strategy over time WITHOUT the human doing anything.
 */
```

---

## 10. Frontend: Project Structure

```
src/app/(dashboard)/
├── backtest/
│   ├── page.tsx                           # List view (active + completed)
│   ├── loading.tsx
│   ├── [session_id]/
│   │   ├── page.tsx                       # Monitor (running) or Results (completed)
│   │   └── loading.tsx
│   └── compare/
│       └── page.tsx                       # Comparison view

src/hooks/
├── use-backtest-list.ts                   # Fetch all backtests for account
├── use-backtest-status.ts                 # Poll running backtest status (2s interval)
├── use-backtest-results.ts                # Fetch completed results + equity curve
└── use-backtest-compare.ts                # Fetch comparison data

src/lib/types.ts                           # Add: BacktestSession, BacktestResult, StepResult
```

### Sidebar Navigation

```
📊  Market Overview
📈  Agent Dashboard
🧪  Backtesting              ← NEW (shows count badge: "3 completed today")
💰  Wallet
📋  Trade History
📉  Analytics
🏆  Leaderboard
```

---

## 11. Skill.md — The Agent's Complete Playbook

This is what matters most. The skill.md additions must teach the agent HOW to think about backtesting, not just the endpoints.

```markdown
---

## BACKTESTING — Test your strategies against history

You can replay historical market data and trade against it at your own pace.
This lets you test a strategy against 30 days of data in minutes instead of
waiting 30 real days. Your trading code works identically in backtest and live mode.

### Check available data range
GET /market/data-range
→ Tells you the earliest and latest dates you can backtest against.

### Create a backtest session
POST /backtest/create
{
  "start_time": "2026-01-01T00:00:00Z",
  "end_time": "2026-01-31T23:59:59Z",
  "starting_balance": 10000,
  "candle_interval": "1m",
  "strategy_label": "my_strategy_v1"
}
→ Returns session_id. Use strategy_label to track versions.

### Start the backtest
POST /backtest/{session_id}/start

### Step forward one candle
POST /backtest/{session_id}/step
→ Returns: prices for all pairs, filled orders, portfolio state, progress.
  Use this data to analyze and decide whether to trade.

### Fast-forward multiple candles
POST /backtest/{session_id}/step/batch
{"steps": 60}
→ Advances 60 candles at once. Good for skipping quiet periods.

### Trade during backtest (identical to live)
POST /backtest/{session_id}/trade/order
{"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": 0.1}

GET /backtest/{session_id}/market/candles/BTCUSDT?interval=1h&limit=24
GET /backtest/{session_id}/account/balance
GET /backtest/{session_id}/account/positions

### Cancel early if results look bad
POST /backtest/{session_id}/cancel
→ Saves partial results. Don't waste time on a losing strategy.

### Get results when complete
GET /backtest/{session_id}/results
→ ROI, Sharpe ratio, max drawdown, win rate, profit factor, per-pair breakdown.

### List all your backtests
GET /backtest/list?strategy_label=my_strategy&sort_by=sharpe_ratio
→ Review everything you've tested.

### Compare backtests
GET /backtest/compare?sessions=bt_id1,bt_id2,bt_id3
→ Side-by-side metrics. Identifies the best performer.

### Find your best backtest
GET /backtest/best?metric=sharpe_ratio
→ Returns your highest-performing backtest session.

### The recommended workflow

STEP 1: Backtest your strategy on a recent period
  POST /backtest/create → start → step loop → results

STEP 2: If results are promising, backtest on a DIFFERENT time period
  This checks if your strategy is robust or just lucky on one period.
  POST /backtest/create (different dates, same strategy) → run → results

STEP 3: Compare all backtests
  GET /backtest/compare → see which version performs best across periods

STEP 4: If satisfied, switch to live trading
  POST /account/mode {"mode": "live", "strategy_label": "my_strategy_v3"}
  Now you trade against real-time prices with virtual money.

STEP 5: Periodically re-backtest on newest data
  Every few days, create a new backtest on the latest data to verify
  your strategy still works. Markets change.

STEP 6: If live performance degrades, iterate
  Run new backtests with tweaked parameters.
  Compare old vs new. Switch to whichever version is better.

### Tips for effective backtesting

1. Always test on at least 2 different time periods. A strategy that only
   works on one period is likely overfitting.

2. Use strategy_label with version numbers (v1, v2, v3) so you can
   track your improvements over time.

3. Cancel backtests early if drawdown exceeds your tolerance. Don't waste
   steps on a strategy that's clearly failing.

4. Compare your results against "buy and hold BTC" — if your strategy
   doesn't beat simply holding BTC, it might not be worth the complexity.

5. Pay attention to Sharpe ratio, not just ROI. A strategy with 50% ROI
   but -40% max drawdown is worse than 20% ROI with -8% max drawdown.

6. Step-batch through periods where you have no signal. If your strategy
   only trades on 1h candles, batch 60 steps at a time to skip the
   1-minute candles you don't need.
```

---

## 12. Development Phases & Tasks

### Phase BT-1: Backend Engine (Week 1-2)

**Goal:** Agent can create, run, and get results from backtests via API

Tasks:
- [ ] Database migration: backtest_sessions, backtest_trades, backtest_snapshots tables
- [ ] Add current_mode and active_strategy_label columns to accounts table
- [ ] Implement `src/backtesting/time_simulator.py` — step-mode virtual clock
- [ ] Implement `src/backtesting/data_replayer.py` — load candles from TimescaleDB
- [ ] Implement look-ahead bias prevention (all queries filter by virtual_clock)
- [ ] Implement `src/backtesting/sandbox.py` — in-memory trading environment
- [ ] Implement `src/backtesting/engine.py` — create, start, step, step_batch, complete, cancel
- [ ] Implement `src/backtesting/results.py` — calculate Sharpe, drawdown, win rate, per-pair stats
- [ ] Implement `src/database/repositories/backtest_repo.py`
- [ ] Add Pydantic schemas: `src/api/schemas/backtest.py`
- [ ] Implement `GET /market/data-range`
- [ ] Implement `POST /backtest/create`
- [ ] Implement `POST /backtest/{sid}/start`
- [ ] Implement `POST /backtest/{sid}/step`
- [ ] Implement `POST /backtest/{sid}/step/batch`
- [ ] Implement `POST /backtest/{sid}/cancel`
- [ ] Implement all proxied trading endpoints (`/backtest/{sid}/market/*`, `/backtest/{sid}/trade/*`, `/backtest/{sid}/account/*`)
- [ ] Implement `GET /backtest/{sid}/results`
- [ ] Implement `GET /backtest/{sid}/results/equity-curve`
- [ ] Implement `GET /backtest/{sid}/results/trades`
- [ ] Implement `GET /backtest/list`
- [ ] Implement `GET /backtest/compare`
- [ ] Implement `GET /backtest/best`
- [ ] Implement `GET /account/mode` and `POST /account/mode`
- [ ] Write unit tests for time_simulator, data_replayer, sandbox
- [ ] Write integration test: full backtest lifecycle
- [ ] Write test: verify NO future data leakage (critical)
- [ ] Write test: concurrent backtests don't interfere
- [ ] Load test: 5 concurrent backtests

**Deliverable:** Agent can autonomously run backtests via REST API

---

### Phase BT-2: Frontend Observation UI (Week 3)

**Goal:** Human can observe everything the agent is doing

Tasks:
- [ ] Add "Backtesting" to sidebar with dynamic badge
- [ ] Build `src/hooks/use-backtest-list.ts`
- [ ] Build `src/hooks/use-backtest-status.ts` (polling for running backtests)
- [ ] Build `src/hooks/use-backtest-results.ts`
- [ ] Build `src/hooks/use-backtest-compare.ts`
- [ ] Build list page: active-backtest-card, completed-backtest-table, agent-mode-status
- [ ] Build monitor page: progress-timeline, live-equity-chart, live-stats-cards, live-trades-feed
- [ ] Build results page: reuse analytics components with backtest data
- [ ] Build compare page: overlaid-equity-chart, compare-metrics-table, compare-auto-selector
- [ ] Build shared components: backtest-status-badge, virtual-time-display, strategy-label-badge, improvement-indicator
- [ ] Mobile responsive pass on all backtest pages
- [ ] Add loading skeletons
- [ ] Verify: NO create/edit/action buttons anywhere in the UI (read-only)

**Deliverable:** Human can watch agent's backtesting activity

---

### Phase BT-3: Skill.md & Agent Integration (Week 4)

**Goal:** Any agent can use backtesting through the skill.md file

Tasks:
- [ ] Update skill.md with backtesting section (see Section 11)
- [ ] Update Python SDK with backtest methods
- [ ] Update MCP server with backtest tools (create, start, step, results, compare, best)
- [ ] End-to-end test: agent reads skill.md, creates backtest, runs to completion, reviews results
- [ ] End-to-end test: agent runs 3 backtests, compares them, picks the best one
- [ ] Add backtest metrics to Grafana dashboards
- [ ] Add cleanup task: auto-cancel backtests idle for >1 hour
- [ ] Add cleanup task: delete backtest detail data older than 90 days (keep summary)
- [ ] Documentation: backtesting guide in docs/

**Deliverable:** Production-ready backtesting, fully agent-driven

---

## 13. Testing Strategy

### Unit Tests

```
test_time_simulator.py:
  - test_step_advances_by_interval
  - test_step_does_not_exceed_end_time
  - test_is_complete_at_end
  - test_remaining_steps_calculation
  - test_progress_pct_accurate

test_data_replayer.py:
  - test_load_prices_at_timestamp
  - test_candle_range_only_returns_past_data
  - test_NO_FUTURE_DATA_LEAKAGE (critical — query with timestamps after virtual_clock must return empty)
  - test_ticker_24h_calculation
  - test_handles_pairs_without_data
  - test_get_data_range

test_sandbox.py:
  - test_initial_balance_correct
  - test_market_buy_execution
  - test_market_sell_execution
  - test_limit_order_pending_then_triggered
  - test_stop_loss_triggers
  - test_insufficient_balance_rejected
  - test_position_tracking
  - test_pnl_calculation
  - test_close_all_positions
  - test_export_results

test_engine.py:
  - test_create_session
  - test_start_initializes_sandbox
  - test_step_returns_correct_data
  - test_step_batch_advances_correctly
  - test_order_during_backtest
  - test_completion_persists_results
  - test_cancel_saves_partial_results
  - test_concurrent_sessions_isolated
```

### Integration Tests

```
test_backtest_e2e.py:
  1. POST /backtest/create (Jan 1-7, 1m candles)
  2. POST /backtest/{id}/start
  3. Step 10 times, verify prices match actual TimescaleDB candles
  4. Place market buy for BTC
  5. Verify balance updated
  6. Step 100 more times
  7. Verify limit order triggered when price crossed target
  8. Step until completion
  9. GET /backtest/{id}/results
  10. Verify equity curve length matches expected candle count
  11. Verify trade log matches orders placed
  12. Verify metrics are mathematically correct

test_no_lookahead.py:
  1. Create backtest at Jan 15 12:00
  2. GET /backtest/{id}/market/candles/BTCUSDT?limit=100
  3. Assert ALL candle timestamps < Jan 15 12:00
  4. Step to Jan 15 13:00
  5. GET candles again
  6. Assert new candles include 12:00-13:00 but NOT 13:01+

test_agent_workflow.py:
  1. Agent creates backtest A with strategy_label "test_v1"
  2. Runs to completion
  3. Agent creates backtest B with strategy_label "test_v2"
  4. Runs to completion
  5. Agent calls GET /backtest/compare?sessions=A,B
  6. Verify comparison returns both with correct metrics
  7. Agent calls GET /backtest/best?metric=sharpe_ratio
  8. Verify returns the better one
  9. Agent calls POST /account/mode {"mode": "live", "strategy_label": "test_v2"}
  10. Verify account mode switched
```

---

*End of Backtesting Engine Development Plan v2 — Agent-First Design*