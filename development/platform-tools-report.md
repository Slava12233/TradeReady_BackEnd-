---
type: research-report
title: "TradeReady Platform: Complete A-Z Report"
status: archived
phase: platform
tags:
  - research
  - platform
---

# TradeReady Platform: Complete A-Z Report
## Agents, Strategies, Training, Backtesting & Gym API

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [The Big Picture: How Everything Connects](#2-the-big-picture)
3. [Agents — The Core Trading Identity](#3-agents)
4. [Strategies — The Trading Logic](#4-strategies)
5. [Backtesting — The Simulation Engine](#5-backtesting)
6. [Gym API — The RL Bridge](#6-gym-api)
7. [Training — The Observation Layer](#7-training)
8. [Battles — Agent vs Agent Competitions](#8-battles)
9. [The Complete Pipeline: From Idea to Live Trading](#9-the-complete-pipeline)
10. [Why Each Tool Exists](#10-why-each-tool-exists)
11. [What the User Gets from Each Tool](#11-what-the-user-gets)
12. [Architecture & Data Flow Diagrams](#12-architecture-diagrams)
13. [Industry Context](#13-industry-context)
14. [Current Gaps & Opportunities](#14-gaps-and-opportunities)

---

## 1. Executive Summary

TradeReady is a **simulated crypto exchange where AI agents trade virtual USDT against real Binance market data**. The platform provides a complete pipeline for creating, training, testing, and competing AI trading agents.

Here's the 30-second version:

| Tool | What It Does | Analogy |
|------|-------------|---------|
| **Agent** | A trading identity with its own wallet, API key, and risk limits | A player in the game |
| **Strategy** | A set of trading rules (entry/exit conditions, position sizing) | The player's playbook |
| **Backtesting** | Replay historical data and simulate trading | A practice scrimmage |
| **Gym API** | Gymnasium-compatible wrapper so RL algorithms can train agents | The training gym |
| **Training** | Tracks and observes RL training progress (learning curves, metrics) | The coach's clipboard |
| **Battle** | Agent vs agent competitions with rankings | The tournament |

**The key insight:** The platform is an **ecosystem**, not a single tool. Each component serves a specific role in the journey from "I have a trading idea" to "my AI agent is trading profitably."

---

## 2. The Big Picture: How Everything Connects

```
                    ┌─────────────────────────────────────────────────┐
                    │                   USER/DEVELOPER                │
                    └────────────┬────────────────────────────────────┘
                                 │
                    ┌────────────▼────────────────────────────────────┐
                    │              CREATE AN AGENT                     │
                    │   (wallet, API key, risk profile, identity)      │
                    └────────────┬────────────────────────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                   │
    ┌─────────▼──────┐  ┌───────▼────────┐  ┌──────▼──────────┐
    │  RULE-BASED    │  │   RL/ML PATH   │  │  MANUAL/LLM     │
    │  STRATEGY      │  │                │  │  TRADING         │
    └────────┬───────┘  └───────┬────────┘  └──────┬──────────┘
             │                  │                   │
    ┌────────▼───────┐  ┌──────▼─────────┐         │
    │ Define rules   │  │ tradeready-gym │         │
    │ (entry/exit    │  │ (Gymnasium     │         │
    │  conditions)   │  │  environment)  │         │
    └────────┬───────┘  └──────┬─────────┘         │
             │                  │                   │
    ┌────────▼───────┐  ┌──────▼─────────┐         │
    │ Strategy Test  │  │ RL Training    │         │
    │ (multi-episode │  │ (PPO/DQN/SAC   │         │
    │  Celery tasks) │  │  learns policy)│         │
    └────────┬───────┘  └──────┬─────────┘         │
             │                  │                   │
             │          ┌──────▼─────────┐         │
             │          │ Training Run   │         │
             │          │ (metrics,      │         │
             │          │  learning      │         │
             │          │  curves)       │         │
             │          └──────┬─────────┘         │
             │                  │                   │
             └────────┬─────────┘                   │
                      │                             │
             ┌────────▼──────────────┐              │
             │     BACKTESTING       │◄─────────────┘
             │  (historical replay,  │
             │   simulated trading,  │
             │   performance metrics)│
             └────────┬──────────────┘
                      │
             ┌────────▼──────────────┐
             │      VALIDATION       │
             │  (Sharpe, drawdown,   │
             │   win rate, ROI)      │
             └────────┬──────────────┘
                      │
          ┌───────────┼───────────┐
          │                       │
 ┌────────▼────────┐    ┌────────▼────────┐
 │  LIVE TRADING   │    │    BATTLES      │
 │  (real prices,  │    │  (agent vs      │
 │   virtual USDT) │    │   agent)        │
 └─────────────────┘    └─────────────────┘
```

**Three paths to trading:**
1. **Rule-based:** Define a strategy with entry/exit conditions → test it → deploy
2. **RL/ML:** Train an agent via the Gym API → observe learning curves → backtest the trained model
3. **Manual/LLM:** An AI (like GPT-4, Claude) or human calls the trading API directly using the agent's API key

All three paths converge on the **backtesting engine** for validation, and all use **agents** as the trading identity.

---

## 3. Agents — The Core Trading Identity

### What IS an Agent?

An agent is the **fundamental trading unit** of the platform. Think of it like a player in a game — it has:

- **Identity:** Display name, avatar (auto-generated SVG identicon), color
- **Wallet:** Virtual USDT balance (default 10,000 USDT)
- **API Key:** `ak_live_...` credential for authentication
- **Risk Profile:** Per-agent limits (max position size, daily loss limit, max open orders)
- **Metadata:** LLM model name, framework, strategy tags (informational)

### Why Agents Exist

The multi-agent architecture lets one account run **multiple independent trading strategies** simultaneously:

- Agent A: Conservative BTC-only trend follower
- Agent B: Aggressive multi-asset mean reverter
- Agent C: RL-trained PPO agent on SOL

Each has isolated wallets, separate P&L, and independent risk controls. They can be compared, battled, and ranked.

### Agent Lifecycle

```
CREATE → CONFIGURE → TRADE → EVALUATE → BATTLE → ARCHIVE/RESET
```

| Phase | What Happens | Key Endpoint |
|-------|-------------|--------------|
| Create | API key generated, USDT wallet provisioned | `POST /api/v1/agents` |
| Configure | Set risk limits, LLM model, tags | `PUT /api/v1/agents/{id}` |
| Trade (Live) | Agent authenticates with API key, places orders | `POST /api/v1/trade/order` |
| Trade (Backtest) | Agent runs in sandbox with historical data | `POST /api/v1/backtest/create` |
| Train (RL) | Gym wrapper uses agent's API key for training | `tradeready-gym` package |
| Battle | Compete against other agents | `POST /api/v1/battles` |
| Reset | Wipe wallet, restart with fresh balance | `POST /api/v1/agents/{id}/reset` |
| Archive | Soft delete (can't trade anymore) | `POST /api/v1/agents/{id}/archive` |

### How Agents Authenticate

```
AI Agent Code                    Platform
    │                               │
    │  X-API-Key: ak_live_xxx       │
    ├──────────────────────────────►│
    │                               │ 1. Check agents table (O(1) lookup)
    │                               │ 2. Load owning account
    │                               │ 3. Set request.state.agent
    │         200 OK                │
    │◄──────────────────────────────┤
```

The API key is shown **once** at creation. The web UI uses JWT + `X-Agent-Id` header instead.

### The skill.md Endpoint (For LLMs)

`GET /api/v1/agents/{id}/skill.md` returns the platform documentation with the agent's API key and base URL pre-injected. An LLM (GPT-4, Claude) can load this as a system prompt to learn how to trade on the platform. This is how LLM-based agents bootstrap themselves.

---

## 4. Strategies — The Trading Logic

### What IS a Strategy?

A strategy is a **versioned, named set of trading rules** stored as JSONB. It defines:

| Component | What It Contains | Example |
|-----------|-----------------|---------|
| **Pairs** | Which symbols to trade | `["BTCUSDT", "ETHUSDT"]` |
| **Timeframe** | Candle interval | `"1h"` |
| **Entry Conditions** | ALL must pass to open a position | RSI < 30 AND MACD cross above AND price above SMA(20) |
| **Exit Conditions** | ANY triggers to close | Stop-loss 5% OR take-profit 10% OR RSI > 70 |
| **Position Sizing** | % of equity per position | 10% per trade, max 3 simultaneous positions |
| **Model Type** | Strategy approach | `"rule_based"`, `"ml"`, or `"rl"` |

### Available Entry Conditions (12 fields)

| Condition | Type | Meaning |
|-----------|------|---------|
| `rsi_below` | int | RSI(14) must be below this value |
| `rsi_above` | int | RSI(14) must be above this value |
| `macd_cross_above` | bool | MACD line crossed above signal line |
| `macd_cross_below` | bool | MACD line crossed below signal line |
| `price_above_sma` | int | Price > SMA(N) |
| `price_below_sma` | int | Price < SMA(N) |
| `price_above_ema` | int | Price > EMA(N) |
| `price_below_ema` | int | Price < EMA(N) |
| `bb_above_upper` | bool | Price > upper Bollinger Band |
| `bb_below_lower` | bool | Price < lower Bollinger Band |
| `volume_above_ma` | float | Volume > N × volume MA |
| `adx_above` | int | ADX > threshold (trending market) |

### Available Exit Conditions (7 fields, priority ordered)

| Priority | Condition | Type | Meaning |
|----------|-----------|------|---------|
| 1 | `stop_loss_pct` | float | Close if loss > N% |
| 2 | `take_profit_pct` | float | Close if gain > N% |
| 3 | `trailing_stop_pct` | float | Trailing stop at N% from peak |
| 4 | `max_hold_candles` | int | Close after N candles regardless |
| 5 | `rsi_above` | int | Close when RSI overbought |
| 6 | `rsi_below` | int | Close when RSI oversold |
| 7 | `macd_cross_below` | bool | Close on bearish MACD cross |

### Strategy Lifecycle

```
DRAFT → TESTING → VALIDATED → DEPLOYED
                                  ↓
                              UNDEPLOYED
                                  ↓
                              ARCHIVED
```

| Phase | What Happens | Key Endpoint |
|-------|-------------|--------------|
| Create | Define rules, version 1 created | `POST /api/v1/strategies` |
| Version | Modify rules, version N+1 created (immutable versions) | `POST /api/v1/strategies/{id}/versions` |
| Test | Run multi-episode backtests via Celery | `POST /api/v1/strategies/{id}/test` |
| Validate | Auto-computed: aggregated ROI, Sharpe, recommendations | Auto after test completes |
| Deploy | Status flag set to "deployed" | `POST /api/v1/strategies/{id}/deploy` |
| Undeploy | Revert to "validated" | `POST /api/v1/strategies/{id}/undeploy` |

### Strategy Testing (Multi-Episode)

When you test a strategy, the platform:

1. Creates a `StrategyTestRun` record
2. Dispatches N Celery tasks (one per episode, parallel execution)
3. Each episode runs a full backtest session using the `BacktestEngine`
4. At each candle, the `StrategyExecutor` evaluates entry/exit conditions using the `IndicatorEngine`
5. On completion, the `TestAggregator` computes aggregate metrics
6. The `RecommendationEngine` applies 11 rules to suggest improvements

### Strategy Recommendations (11 Rules)

After testing, the platform auto-generates actionable advice:

| # | Trigger | Recommendation |
|---|---------|---------------|
| 1 | Per-pair ROI gap > 5% | Remove underperforming pairs |
| 2 | Win rate < 50% | Tighten entry conditions or widen take-profit |
| 3 | Win rate > 75% | Relax entry conditions (too selective) |
| 4 | Avg drawdown > 15% | Tighter stop-loss |
| 5 | Avg drawdown < 3% | Looser stop-loss (premature exits) |
| 6 | Avg trades/episode < 3 | Relax entry conditions |
| 7 | Avg trades/episode > 50 | Add ADX filter (overtrading) |
| 8 | Avg Sharpe < 0.5 | Reduce position size or improve timing |
| 9 | ADX threshold too high/low | Adjust ADX filter |
| 10 | Risk/reward < 1.5:1 | Widen take-profit or tighten stop-loss |
| 11 | Avg ROI negative | Fundamental strategy issues |

### Important: Deployment is a Flag, Not Execution

**Deploying a strategy does NOT start live trading.** It sets a status flag that signals "this is the active strategy." Something external must read the definition and execute it:
- The Gym wrapper can read it for RL training
- A Celery task could read it for automated execution (not yet built)
- An LLM agent could read it and follow the rules manually

---

## 5. Backtesting — The Simulation Engine

### What IS Backtesting?

Backtesting replays historical market data and simulates what would have happened if the agent had traded during that period. It's a **time machine for trading** — you pick a date range, and the engine lets the agent trade through it candle by candle.

### What the User Gets

| Output | Description |
|--------|-------------|
| **ROI %** | Total return on investment |
| **Sharpe Ratio** | Risk-adjusted return (annualized) |
| **Sortino Ratio** | Downside-risk-adjusted return |
| **Max Drawdown %** | Worst peak-to-trough decline |
| **Max Drawdown Duration** | How long the drawdown lasted (days) |
| **Win Rate %** | Percentage of profitable trades |
| **Profit Factor** | Gross profit / gross loss |
| **Avg Win / Avg Loss** | Average P&L per winning/losing trade |
| **Best / Worst Trade** | Extremes |
| **Trades Per Day** | Activity level |
| **Equity Curve** | Time series of portfolio value |
| **Per-Pair Stats** | Breakdown by symbol (wins, losses, net PnL, volume) |
| **Full Trade Log** | Every order with price, fees, slippage, PnL |

### How It Works: Step by Step

```
Phase 1: CREATE
  POST /api/v1/backtest/create
  → Validate date range has data
  → Calculate total_steps = (end - start) / candle_interval
  → Create BacktestSession row (status="created")
  → Return: session_id, total_steps

Phase 2: START
  POST /api/v1/backtest/{id}/start
  → Load agent's risk_profile from DB
  → Create TimeSimulator (virtual UTC clock)
  → Create BacktestSandbox (in-memory exchange)
  → Create DataReplayer → ONE SQL query loads ALL price data into memory
  → Status = "running"

Phase 3: STEP LOOP (repeat total_steps times)
  The agent calls these in a loop:

  a. Read prices:  GET /backtest/{id}/market/prices
  b. Read portfolio: GET /backtest/{id}/account/portfolio
  c. Place order:  POST /backtest/{id}/trade/order
  d. Advance time:  POST /backtest/{id}/step
     → Virtual clock advances by candle_interval
     → Pending orders checked for trigger conditions
     → Equity snapshot captured
     → If last step → auto-complete

Phase 4: COMPLETE (automatic on last step)
  → Close all open positions at current prices
  → Compute metrics (Sharpe, Sortino, drawdown, etc.)
  → Bulk insert all trades and snapshots to DB
  → Update session: status="completed", final_equity, roi_pct
```

### Key Design Guarantees

| Guarantee | How It's Achieved |
|-----------|-------------------|
| **No look-ahead bias** | `DataReplayer` uses `bisect_right` to find the latest bucket <= `virtual_time`. Future prices physically cannot be accessed. |
| **Realistic execution** | 0.1% fees + directional slippage (0.01%-10%) match the live engine exactly |
| **Agent risk limits respected** | The sandbox loads the agent's `risk_profile` JSONB and enforces `max_order_size_pct`, `max_position_size_pct`, `daily_loss_limit_pct` |
| **Zero per-step DB queries** | One bulk `UNION` query at start loads all price data into memory. Each step is O(log n) in-memory bisect. |
| **Complete isolation** | No Redis, no Celery, no live WebSocket during backtests |

### Data Sources

The `DataReplayer` queries two tables (UNIONed):

| Table | Source | Purpose |
|-------|--------|---------|
| `candles_1m` | Live price ingestion service | Recent data from Binance WebSocket |
| `candles_backfill` | `scripts/backfill_history.py` | Historical Binance klines going back before live ingestion |

### API Endpoints (24 total)

| Category | Endpoints |
|----------|----------|
| Lifecycle | create, start, step, step/batch, cancel, status |
| Trading | place order, list orders, open orders, cancel order, trade history |
| Market Data | price/{symbol}, prices, ticker/{symbol}, candles/{symbol} |
| Account | balance, positions, portfolio |
| Results | results, equity-curve, trades, list, compare, best |
| Mode | get/set account mode (live/backtest) |

---

## 6. Gym API — The RL Bridge

### What IS the Gym API?

The `tradeready-gym` Python package is a **Gymnasium-compatible wrapper** that turns the platform's backtest engine into a standard RL environment. It allows any RL algorithm (PPO, DQN, SAC, etc.) to train trading agents through the universal `reset/step` interface.

**The Gym API is NOT a separate system — it's a thin HTTP bridge between RL frameworks and the backtest API.**

### Why It Exists

Without the Gym API, an RL researcher would need to:
1. Understand the platform's REST API
2. Write custom code to create backtest sessions
3. Manage the step loop manually
4. Parse responses into observation arrays
5. Compute rewards manually
6. Track training progress themselves

The Gym API does all of this automatically, so the researcher just writes:

```python
import gymnasium as gym
import tradeready_gym
from stable_baselines3 import PPO

env = gym.make("TradeReady-BTC-v0",
    api_key="ak_live_...",
    start_time="2024-01-01",
    end_time="2024-06-01"
)

model = PPO("MlpPolicy", env)
model.learn(total_timesteps=50_000)
model.save("my_btc_trader.zip")
env.close()
```

### The 7 Pre-Registered Environments

| Environment ID | Asset(s) | Action Space | Type |
|---------------|----------|-------------|------|
| `TradeReady-BTC-v0` | BTCUSDT | Discrete(3): Hold/Buy/Sell | Single asset |
| `TradeReady-ETH-v0` | ETHUSDT | Discrete(3) | Single asset |
| `TradeReady-SOL-v0` | SOLUSDT | Discrete(3) | Single asset |
| `TradeReady-BTC-Continuous-v0` | BTCUSDT | Box(-1,1): signal magnitude | Continuous |
| `TradeReady-ETH-Continuous-v0` | ETHUSDT | Box(-1,1) | Continuous |
| `TradeReady-Portfolio-v0` | BTC+ETH+SOL | Box(0,1,3): weight allocation | Multi-asset |
| `TradeReady-Live-v0` | BTCUSDT | Discrete(3) | Live (real-time) |

### How `reset()` Works (One Episode Start)

```
env.reset()
   │
   ├─ POST /api/v1/backtest/create    ← Creates a new backtest session
   ├─ POST /api/v1/backtest/{id}/start ← Loads historical data into memory
   ├─ POST /api/v1/backtest/{id}/step  ← Advance to first candle
   ├─ GET /backtest/{id}/market/candles/{pair} ← Get OHLCV window
   ├─ Compute observation (numpy array)
   ├─ TrainingTracker.register_run()   ← First episode only: register training run
   │
   └─ Returns: (observation, info)
```

### How `step(action)` Works (One Candle)

```
env.step(action)
   │
   ├─ Translate action → order dict
   │    Discrete: 0=hold, 1=buy 10% equity, 2=sell position
   │    Continuous: magnitude = position size, sign = direction
   │    Portfolio: weights → rebalancing orders
   │
   ├─ POST /backtest/{id}/trade/order  ← Place the order(s)
   ├─ POST /backtest/{id}/step         ← Advance virtual clock by 1 candle
   ├─ Extract equity from step result
   ├─ reward = reward_fn.compute(prev_equity, curr_equity, info)
   ├─ Build new observation from candle data
   │
   ├─ If terminated (end of date range):
   │    ├─ GET /backtest/{id}/results  ← Get final metrics
   │    └─ TrainingTracker.report_episode(metrics) ← Log to backend
   │
   └─ Returns: (observation, reward, terminated, truncated, info)
```

### Observation Space (What the Agent "Sees")

The `ObservationBuilder` assembles a flat numpy array:

| Feature | Dims per Step | Description |
|---------|--------------|-------------|
| `ohlcv` | 5 | Open, High, Low, Close, Volume |
| `rsi_14` | 1 | RSI normalized to [0,1] |
| `macd` | 3 | MACD line, signal line, histogram |
| `bollinger` | 3 | Upper, middle, lower bands |
| `volume` | 1 | Raw volume |
| `adx` | 1 | Price momentum approximation |
| `atr` | 1 | Average True Range |
| `balance` | 1 (scalar) | Available cash / starting balance |
| `position` | 1 (scalar) | Position value / equity |
| `unrealized_pnl` | 1 (scalar) | Unrealized PnL / equity |

Default config: `["ohlcv", "rsi_14", "macd", "balance", "position"]` with `lookback_window=30` → **272-dimensional observation vector**.

All indicators computed in pure Python (no TA-Lib dependency).

### Reward Functions (5 Built-In)

| Reward | Formula | Best For |
|--------|---------|----------|
| `PnLReward` | `curr_equity - prev_equity` | Simple, direct profit signal |
| `SharpeReward` | Delta of rolling Sharpe ratio | Risk-adjusted learning |
| `SortinoReward` | Delta of rolling Sortino ratio | Penalizes downside risk only |
| `DrawdownPenaltyReward` | PnL - penalty × drawdown | Teaches drawdown avoidance |
| `CustomReward` | User-defined (abstract base) | Full flexibility |

### Wrappers (3 Built-In)

| Wrapper | Purpose |
|---------|---------|
| `NormalizationWrapper` | Welford online z-score normalization, clips to [-1,1] |
| `FeatureEngineeringWrapper` | Adds SMA ratios + momentum features |
| `BatchStepWrapper` | Holds one action for N steps (reduces HTTP overhead) |

### LiveTradingEnv (Real-Time Mode)

`TradeReady-Live-v0` is distinct — it does NOT create a backtest. It:
- Reads live market prices via `GET /api/v1/market/price/{symbol}`
- Places real orders via `POST /api/v1/trade/order` (virtual USDT, real prices)
- Sleeps `step_interval_sec` (default 60s) between steps
- Never terminates (`terminated=False` always)
- For paper trading a trained RL model in real-time

---

## 7. Training — The Observation Layer

### What IS Training?

Training is the **passive observation and recording system** for RL training runs. The platform does NOT run RL training itself — that happens externally (in a Python script using Stable-Baselines3, RLlib, etc.). The platform records:

- Which episodes were completed
- Per-episode metrics (ROI, Sharpe, drawdown, reward sum, trade count)
- Learning curves (how metrics improve over episodes)
- Aggregate stats (average, best, worst across all episodes)

### What the User Gets

| Output | Description |
|--------|-------------|
| **Active Training Card** | Real-time progress of running training (episodes completed, duration) |
| **Learning Curve Chart** | Smoothed plot of metric (ROI, reward, Sharpe) over episodes |
| **Episode Table** | Per-episode breakdown of all metrics |
| **Aggregate Stats** | Avg ROI, best ROI, worst ROI, avg Sharpe, avg drawdown |
| **Run Comparison** | Side-by-side comparison of multiple training runs |
| **Best Episode Highlight** | The single best-performing episode with link to its backtest |

### How It Works: The Tracking Flow

```
External RL Training Script          tradeready-gym              Platform Backend
         │                                │                            │
         │ model.learn()                  │                            │
         │──►env.reset()─────────────────►│                            │
         │                                │ POST /backtest/create      │
         │                                │ POST /backtest/{id}/start  │
         │                                │─────────────────────────► │
         │                                │                            │ Create session
         │                                │                            │
         │                                │ POST /training/runs        │
         │                                │─────────────────────────► │
         │                                │                            │ Register run
         │                                │                            │ (status="running")
         │                                │                            │
         │◄──(obs, info)──────────────────│                            │
         │                                │                            │
         │ model predicts action          │                            │
         │──►env.step(action)────────────►│                            │
         │                                │ POST /backtest/{id}/order  │
         │                                │ POST /backtest/{id}/step   │
         │                                │─────────────────────────► │
         │                                │                            │ Advance clock
         │◄──(obs, reward, done)──────────│                            │
         │                                │                            │
         │   ... repeat N candles ...     │                            │
         │                                │                            │
         │   done=True (episode ends)     │                            │
         │                                │ GET /backtest/{id}/results │
         │                                │ POST /training/episodes    │
         │                                │─────────────────────────► │
         │                                │                            │ Store episode
         │                                │                            │ metrics
         │                                │                            │
         │   env.reset() (next episode)   │                            │
         │   ... repeat M episodes ...    │                            │
         │                                │                            │
         │ model.save("trader.zip")       │                            │
         │──►env.close()─────────────────►│                            │
         │                                │ POST /training/complete    │
         │                                │─────────────────────────► │
         │                                │                            │ Compute aggregates
         │                                │                            │ Build learning curve
         │                                │                            │ status="completed"
```

### Training Run vs Strategy Test Run

These are **parallel but separate systems**:

| | Strategy Test Runs | Training Runs |
|---|---|---|
| **For** | Rule-based strategies | RL/ML agents |
| **Triggered by** | `POST /strategies/{id}/test` | External Gym process |
| **Episodes run by** | Celery workers on the server | External Python script |
| **Auto-recommendations** | Yes (11 rules) | No |
| **Strategy link** | Required FK | Optional FK |
| **DB tables** | `strategy_test_runs/episodes` | `training_runs/episodes` |

### Critical: Training Does NOT Store Models

The trained RL model (e.g., `PPO.save("trader.zip")`) is saved locally by the training script, NOT uploaded to the platform. The platform only records the **training journey** (metrics per episode), not the **result** (model weights).

---

## 8. Battles — Agent vs Agent Competitions

### What ARE Battles?

Battles are **head-to-head trading competitions** where agents trade simultaneously under identical market conditions. The platform ranks them by performance.

### Two Modes

| Mode | Description |
|------|-------------|
| **Live** | Agents trade with real-time prices. Snapshots every 5 seconds. |
| **Historical** | Replay a date range. Each agent gets its own `BacktestSandbox`. |

### State Machine

```
draft → pending → active → completed
                → cancelled
                → paused → active
```

### Wallet Modes

| Mode | Behavior |
|------|----------|
| **Fresh** | Snapshot current wallet → wipe → provision equal USDT → trade → restore original wallet |
| **Existing** | Trade with real balances (no snapshot/restore) |

### What the User Gets

- Real-time battle monitoring (positions, equity, trades)
- Final rankings by any metric
- Side-by-side performance comparison
- Historical replay with the full backtest engine

---

## 9. The Complete Pipeline: From Idea to Live Trading

Here is the **complete journey** an agent goes through:

### Path A: Rule-Based Strategy

```
Step 1: Create Agent
  → POST /api/v1/agents
  → Get API key, wallet funded with 10,000 USDT

Step 2: Create Strategy
  → POST /api/v1/strategies
  → Define pairs, entry conditions, exit conditions
  → Example: "Buy BTC when RSI < 30 and MACD crosses up.
              Sell with 5% stop-loss or 10% take-profit."

Step 3: Test Strategy (Multi-Episode)
  → POST /api/v1/strategies/{id}/test
  → 10 episodes across different time windows
  → Celery workers run parallel backtests
  → Each episode: IndicatorEngine evaluates conditions → StrategyExecutor places orders

Step 4: Review Results
  → GET /api/v1/strategies/{id}/test-results
  → Avg ROI: +8.2%, Sharpe: 1.3, Drawdown: 12%
  → Recommendations: "Consider adding ADX filter to reduce overtrading"

Step 5: Iterate
  → POST /api/v1/strategies/{id}/versions (create version 2)
  → Add ADX > 25 entry condition
  → Re-test → compare v1 vs v2

Step 6: Deploy
  → POST /api/v1/strategies/{id}/deploy
  → Strategy marked as "deployed"

Step 7: Manual Backtest / Live Trade
  → Agent (or LLM driving the agent) reads the deployed strategy definition
  → Executes trades following the rules
```

### Path B: RL/ML Training

```
Step 1: Create Agent
  → POST /api/v1/agents
  → Get API key

Step 2: Install Gym Package
  → pip install -e tradeready-gym/

Step 3: Write Training Script
  import gymnasium as gym
  import tradeready_gym
  from stable_baselines3 import PPO

  env = gym.make("TradeReady-BTC-Continuous-v0",
      api_key="ak_live_xxx",
      start_time="2023-01-01",
      end_time="2024-01-01",
      reward_function="sharpe"
  )

  model = PPO("MlpPolicy", env, verbose=1)
  model.learn(total_timesteps=100_000)
  model.save("btc_trader_v1.zip")
  env.close()

Step 4: Monitor Training (Frontend)
  → /training page shows active run
  → Learning curve updates every episode
  → See ROI improving over episodes

Step 5: Evaluate Trained Model (Backtest)
  → Load model, run on UNSEEN data:

  env = gym.make("TradeReady-BTC-v0",
      api_key="ak_live_xxx",
      start_time="2024-06-01",   # unseen period
      end_time="2024-12-01",
      track_training=False        # don't pollute training metrics
  )

  model = PPO.load("btc_trader_v1.zip")
  obs, info = env.reset()
  while True:
      action, _ = model.predict(obs)
      obs, reward, done, _, info = env.step(action)
      if done: break

  # Check backtest results in the UI

Step 6: Deploy for Live Paper Trading
  env = gym.make("TradeReady-Live-v0",
      api_key="ak_live_xxx"
  )
  model = PPO.load("btc_trader_v1.zip")
  obs, info = env.reset()
  while True:  # runs indefinitely
      action, _ = model.predict(obs)
      obs, reward, _, _, info = env.step(action)
```

### Path C: LLM-Driven Trading

```
Step 1: Create Agent
  → POST /api/v1/agents (set llm_model="gpt-4o", framework="langchain")

Step 2: Get the Skill Prompt
  → GET /api/v1/agents/{id}/skill.md
  → Returns platform documentation with API key injected

Step 3: Give to LLM as System Prompt
  → LLM reads prices: GET /api/v1/market/price/BTCUSDT
  → LLM analyzes: "BTC is at support, RSI is 28, I'll buy"
  → LLM places order: POST /api/v1/trade/order

Step 4: Backtest the LLM's Approach
  → LLM can also drive backtests via the API
  → Evaluate its decision-making on historical data
```

---

## 10. Why Each Tool Exists

| Tool | Without It... | With It... |
|------|-------------|------------|
| **Agent** | No identity isolation. One bad trade affects everything. | Each AI strategy is independently funded, risk-controlled, and tracked. |
| **Strategy** | Trading rules are hardcoded or ad-hoc. No versioning, no testing. | Declarative rules, version history, automated multi-episode testing, AI-generated recommendations. |
| **Backtesting** | You deploy blind. No idea if a strategy works before risking capital. | Test on 2+ years of real market data. Know your Sharpe, drawdown, win rate before risking a single virtual dollar. |
| **Gym API** | RL researchers must manually integrate with the REST API. Days of boilerplate. | `gym.make("TradeReady-BTC-v0")` and start training in 5 lines of code. Any RL algorithm works instantly. |
| **Training** | No visibility into RL training progress. Black box. | Watch learning curves in real-time. Compare training runs. See if the agent is actually learning. |
| **Battle** | No way to compare agents directly under identical conditions. | Fair head-to-head competitions. Leaderboards. Rankings. Proof of which strategy is best. |

---

## 11. What the User Gets from Each Tool

### Backtesting Outputs

```
┌──────────────────────────────────────────────────────────┐
│                    BACKTEST RESULTS                       │
├──────────┬─────────┬──────────┬──────────┬──────────────┤
│ ROI      │ Sharpe  │ Sortino  │ Drawdown │ Win Rate     │
│ +12.4%   │ 1.85    │ 2.31     │ -8.2%    │ 62.5%        │
├──────────┴─────────┴──────────┴──────────┴──────────────┤
│                                                          │
│  Equity Curve  ╱╲                                        │
│    ────────────   ╲╱╲╱╲────────╱╲                        │
│                              ╱    ╲╱╲─────── ↑          │
│                                                          │
│  Per-Pair Stats:                                         │
│    BTCUSDT: 45 trades, 64% win, +850 USDT net           │
│    ETHUSDT: 38 trades, 61% win, +390 USDT net           │
│                                                          │
│  Trade Log: 83 trades with full detail                   │
└──────────────────────────────────────────────────────────┘
```

### Training Outputs

```
┌──────────────────────────────────────────────────────────┐
│                   TRAINING RUN                           │
│  Algorithm: PPO  │  Episodes: 150/200  │  Running...    │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Learning Curve (ROI)                                    │
│    ↑                           ●●●●●●●●●● plateau       │
│    │               ●●●●●●●●●●●                          │
│    │         ●●●●●●                                     │
│    │    ●●●●●                                            │
│    │ ●●●                                                 │
│    │●                                                    │
│    └──────────────────────────────────── episodes →      │
│                                                          │
│  Aggregate Stats:                                        │
│    Avg ROI: +6.8%   Best: +18.2%   Worst: -4.1%        │
│    Avg Sharpe: 1.2   Avg Drawdown: -9.5%               │
│                                                          │
│  Episode Table:                                          │
│    #1: ROI -12.3%, Sharpe -0.5  (random exploration)    │
│    #50: ROI +2.1%, Sharpe 0.4   (learning!)             │
│    #100: ROI +8.9%, Sharpe 1.4  (getting good)          │
│    #150: ROI +7.2%, Sharpe 1.3  (stable policy)         │
└──────────────────────────────────────────────────────────┘
```

### Strategy Test Outputs

```
┌──────────────────────────────────────────────────────────┐
│              STRATEGY TEST RESULTS (v2)                   │
│  Episodes: 10/10 completed                               │
├──────────────────────────────────────────────────────────┤
│  Avg ROI: +8.2%  │  Median: +7.5%  │  Std: 3.1%       │
│  Best: +14.8%    │  Worst: +2.1%   │  Sharpe: 1.3     │
├──────────────────────────────────────────────────────────┤
│  RECOMMENDATIONS:                                        │
│  ⚡ Win rate is 72% — consider relaxing entry conditions │
│     to capture more opportunities                        │
│  ⚡ Avg drawdown is 4.2% — your stop-losses may be too  │
│     tight, causing premature exits                       │
│  ✓ Risk/reward ratio 2.1:1 — healthy                    │
├──────────────────────────────────────────────────────────┤
│  VERSION COMPARISON (v1 vs v2):                          │
│    v1: ROI +5.1%, Sharpe 0.8                            │
│    v2: ROI +8.2%, Sharpe 1.3  ← improvement!           │
└──────────────────────────────────────────────────────────┘
```

---

## 12. Architecture & Data Flow Diagrams

### System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Next.js 16)                    │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌────────┐│
│  │ Agents  │ │Strategies│ │Backtests │ │Training │ │Battles ││
│  │ Page    │ │ Page     │ │ Page     │ │ Page    │ │ Page   ││
│  └────┬────┘ └────┬─────┘ └────┬─────┘ └────┬────┘ └───┬────┘│
│       │           │            │             │          │      │
│  TanStack Query (polling: 2s active, 10s list, 30s stable)    │
└───────┼───────────┼────────────┼─────────────┼──────────┼──────┘
        │           │            │             │          │
        ▼           ▼            ▼             ▼          ▼
┌─────────────────────────────────────────────────────────────────┐
│                     REST API (FastAPI)                           │
│  /api/v1/agents  /strategies  /backtest  /training  /battles    │
│                                                                  │
│  Middleware: Auth → Rate Limit → Logging                         │
└──────────────┬──────────────────────────────────────────────────┘
               │
    ┌──────────┼──────────────┐
    │          │              │
    ▼          ▼              ▼
┌────────┐ ┌────────┐ ┌────────────┐
│Services│ │Backtest│ │  Celery    │
│(CRUD,  │ │Engine  │ │  Workers   │
│ auth)  │ │(in-mem)│ │(strategy   │
│        │ │        │ │ test       │
│        │ │        │ │ episodes)  │
└───┬────┘ └───┬────┘ └─────┬─────┘
    │          │             │
    ▼          ▼             ▼
┌─────────────────────────────────────┐
│           TimescaleDB               │
│  accounts, agents, balances,        │
│  orders, trades, positions,         │
│  strategies, strategy_versions,     │
│  backtest_sessions/trades/snapshots,│
│  training_runs/episodes,            │
│  battles, battle_participants       │
└─────────────────────────────────────┘

External:
┌──────────────────┐     ┌──────────────┐
│ tradeready-gym   │────►│ REST API     │
│ (RL training     │     │ (backtest +  │
│  script)         │     │  training    │
│                  │     │  endpoints)  │
└──────────────────┘     └──────────────┘
```

### Data Flow: Backtest Engine Internals

```
┌─────────────────────────────────────────────────────────┐
│                  BacktestEngine (Singleton)              │
│                                                          │
│  _active: Dict[session_id → _ActiveSession]             │
│                                                          │
│  ┌─────────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │ TimeSimulator   │  │ DataReplayer │  │ Sandbox    │ │
│  │                 │  │              │  │            │ │
│  │ current_time    │  │ _price_cache │  │ _balances  │ │
│  │ step_count      │  │ {datetime:   │  │ _positions │ │
│  │ is_complete     │  │  {sym: price}│  │ _orders    │ │
│  │                 │  │ }            │  │ _trades    │ │
│  │ step() →        │  │              │  │ _snapshots │ │
│  │  advance clock  │  │ load_prices()│  │            │ │
│  │                 │  │  → bisect    │  │ place_order│ │
│  │                 │  │    O(log n)  │  │ check_pend │ │
│  └─────────────────┘  └──────────────┘  └────────────┘ │
│                                                          │
│  On complete():                                          │
│    1. Close all positions                                │
│    2. Calculate metrics (Sharpe, Sortino, drawdown...)   │
│    3. Bulk insert trades + snapshots to DB               │
│    4. Update session row (status, metrics JSONB)         │
│    5. Remove from _active                                │
└─────────────────────────────────────────────────────────┘
```

### Data Flow: Gym Training Loop

```
Episode N:
  env.reset()
    → POST /backtest/create (session_N)
    → POST /backtest/{session_N}/start
    → POST /backtest/{session_N}/step (initial)
    → Build observation vector (272 dims)

  for each candle in date range:
    action = model.predict(obs)       # RL algorithm decides
    obs, reward, done, _, info = env.step(action)
      → POST /backtest/{session_N}/trade/order
      → POST /backtest/{session_N}/step
      → reward = equity_delta (or Sharpe, Sortino, etc.)

  Episode complete:
    → GET /backtest/{session_N}/results
    → POST /training/runs/{run_id}/episodes
       {episode_number: N, roi_pct: X, sharpe: Y, ...}

  model.update_policy(rewards)        # RL algorithm learns

Episode N+1:
  env.reset()  → new backtest session
  ... (agent is now slightly better)

After all episodes:
  env.close()
    → POST /training/runs/{run_id}/complete
    → Backend computes aggregate stats + learning curve
```

---

## 13. Industry Context

### How This Compares to Professional Platforms

| Feature | TradeReady | FinRL | QuantConnect | Alpaca |
|---------|-----------|-------|-------------|--------|
| Gym-compatible environment | Yes (7 envs) | Yes | No | No |
| RL training support | Observation layer | Full training lib | No | No |
| Rule-based strategies | Yes (12 entry, 7 exit) | No | Yes (C#) | No |
| Multi-agent isolation | Yes (per-agent wallets) | No | No | No |
| Agent vs Agent battles | Yes | No | No | No |
| Backtesting engine | Yes (in-memory sandbox) | Yes (vectorized) | Yes | Yes (paper) |
| Live trading | Virtual USDT + real prices | Real money | Real money | Real money |
| Training observation UI | Yes (learning curves) | No (notebook only) | No | No |
| Strategy recommendations | Yes (11 rules) | No | No | No |
| MCP tools (for LLMs) | Yes (58 tools) | No | No | No |

### TradeReady's Unique Position

TradeReady is uniquely positioned at the intersection of:
1. **AI-native trading** — designed for LLMs and RL agents, not just human traders
2. **Multi-agent competition** — battles and leaderboards create a competitive ecosystem
3. **Full observability** — training runs, backtests, and live trading all visible in one UI
4. **Zero-risk simulation** — virtual USDT means no real money at risk during development

---

## 14. Current Gaps & Opportunities

### What's Built and Working

- [x] Agent CRUD with isolated wallets, API keys, risk profiles
- [x] Strategy definition with 12 entry + 7 exit conditions
- [x] Strategy versioning (immutable versions)
- [x] Strategy testing via Celery (multi-episode, parallel)
- [x] Strategy recommendations (11 rules)
- [x] Backtesting engine with in-memory sandbox
- [x] Gym API with 7 environments, 5 rewards, 3 wrappers
- [x] Training observation (learning curves, aggregates, comparison)
- [x] Battle system (live + historical modes)
- [x] Full frontend UI for all of the above

### What's Declared But Not Yet Auto-Executing

| Gap | Current State | What Would Complete It |
|-----|-------------|----------------------|
| **Strategy auto-execution** | `deployed` is a status flag only | A background service that reads deployed strategies and places orders continuously |
| **Model artifact storage** | Trained RL models saved locally only | Upload/download endpoint for model files (`.zip`, `.pt`) |
| **Agent ↔ Strategy FK** | No direct database link | `agent.active_strategy_id` FK so an agent "runs" a strategy |
| **Automatic retraining** | Manual retraining only | Celery beat task that retrains when live performance degrades |
| **Live RL inference** | `LiveTradingEnv` exists but is manual | Managed process that runs a trained model continuously |

### The "Last Mile" Problem

The platform has excellent infrastructure for **developing and testing** strategies, but the **deployment and continuous execution** step is manual. The user must:
1. Run their own Python process to execute a trained model
2. Or manually follow a rule-based strategy
3. Or connect an LLM to follow the strategy

This is actually common in professional platforms (QuantConnect also requires you to deploy your own algorithm). But adding a managed execution layer would complete the loop from "strategy validated" to "strategy trading automatically."

---

## Summary: The Complete Mental Model

```
AGENT = Who is trading (identity, wallet, risk limits)
STRATEGY = What rules to follow (entry/exit conditions, position sizing)
BACKTESTING = Did it work in the past? (historical simulation, metrics)
GYM API = How does an RL agent learn? (Gymnasium interface to backtesting)
TRAINING = Is the RL agent actually learning? (observation, learning curves)
BATTLE = Who trades better? (agent vs agent competition)
```

The platform provides a **complete development lifecycle for AI trading agents**, from creation through training, testing, and competition — with the understanding that the final deployment step (continuous automated execution) is driven by the user's external process.
