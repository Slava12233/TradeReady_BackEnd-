# TradeReady Gym & Strategy System — Complete Documentation

> **Version:** 1.0 | **Date:** March 18, 2026
> **Audience:** Agent developers (LLM and RL), internal team, investors
> **Status:** Planning phase — describes target system

---

## What This Is

TradeReady provides a **closed-loop strategy development system** for AI trading agents. Agents create trading strategies, test them against real historical market data, read the results, improve their strategies, and deploy the winners to live trading — all through the API.

The system serves two types of AI agents through two interfaces, both sharing the same backend infrastructure:

| Agent Type | Interface | How It Works |
|---|---|---|
| **LLM Agents** (Claude, GPT, LangChain, CrewAI) | REST API / MCP / skill.md | Agent defines strategy as JSON rules → platform tests it → agent reads results → agent iterates |
| **RL Agents** (PPO, DQN, SAC via Stable-Baselines3) | Gymnasium API (`pip install tradeready-gym`) | Agent trains through standard reset()/step() loop → results auto-save → developer queries via API |

Both paths produce results that end up in the same database. An LLM agent can read the results of an RL training run. An RL developer can use a strategy that an LLM agent designed as a starting point.

---

## The Closed Loop

This is the core value proposition. Every step is an API call. The agent drives everything.

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   ① Create Strategy                                        │
│   POST /strategies { name, definition: {rules} }            │
│                                                             │
│   ② Test Strategy                                          │
│   POST /strategies/{id}/test { episodes: 200 }              │
│   Backend runs 200 backtest episodes automatically          │
│                                                             │
│   ③ Read Results                                           │
│   GET /strategies/{id}/tests/{test_id}                      │
│   → ROI, Sharpe, drawdown, per-pair breakdown,              │
│     improvement recommendations                             │
│                                                             │
│   ④ Improve Strategy                                       │
│   POST /strategies/{id}/versions { new definition }         │
│   Agent creates v2 based on what it learned                 │
│                                                             │
│   ⑤ Compare Versions                                       │
│   GET /strategies/{id}/compare-versions?v1=1&v2=2           │
│   → Side-by-side metrics showing which is better            │
│                                                             │
│   ⑥ Deploy Winner                                          │
│   POST /strategies/{id}/deploy { version: 2 }              │
│   Strategy is now active for live trading                   │
│                                                             │
│   ⑦ Monitor & Repeat                                       │
│   Agent watches live performance, re-tests when needed      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Part 1: Strategy System (For LLM Agents)

### Creating a Strategy

A strategy is a set of trading rules defined as JSON. The agent sends this to the platform, and the platform can execute these rules against historical market data.

```
POST /api/v1/strategies
Content-Type: application/json
X-API-Key: ak_live_...

{
  "name": "momentum_breakout_v1",
  "definition": {
    "pairs": ["BTCUSDT", "ETHUSDT"],
    "timeframe": "1h",
    "entry_conditions": {
      "rsi_14_below": 30,
      "volume_above_ma20": true,
      "adx_above": 25
    },
    "exit_conditions": {
      "stop_loss_pct": 5.0,
      "take_profit_pct": 10.0,
      "rsi_14_above": 70
    },
    "position_size_pct": 10,
    "max_positions": 3
  }
}
```

**Response:**
```json
{
  "strategy_id": "str_abc123",
  "name": "momentum_breakout_v1",
  "version": 1,
  "status": "draft",
  "created_at": "2026-03-18T10:00:00Z"
}
```

### Strategy Definition Format

The `definition` object tells the platform how to trade. Every field is optional except `pairs`.

#### Trading Rules

```json
{
  "pairs": ["BTCUSDT", "ETHUSDT"],     // Required. Which pairs to trade.
  "timeframe": "1h",                    // Candle interval: 1m, 5m, 15m, 1h, 4h, 1d
  
  "entry_conditions": {                  // ALL must be true to enter a trade
    // ... see conditions list below
  },
  
  "exit_conditions": {                   // ANY triggers an exit
    // ... see conditions list below
  },
  
  "position_size_pct": 10,              // Use 10% of available balance per trade
  "max_positions": 3,                   // Maximum simultaneous open positions
  
  "filters": {                           // Optional pre-filters
    "min_24h_volume_usdt": 1000000,     // Skip low-volume pairs
    "excluded_pairs": ["DOGEUSDT"]      // Blacklist specific pairs
  }
}
```

#### Available Conditions

**Entry conditions** (all must be true to trigger a buy):

| Condition | Type | Example | Meaning |
|---|---|---|---|
| `rsi_14_below` | number | `30` | RSI(14) is below 30 (oversold) |
| `rsi_14_above` | number | `70` | RSI(14) is above 70 (overbought) |
| `macd_cross_up` | boolean | `true` | MACD line crossed above signal line |
| `macd_cross_down` | boolean | `true` | MACD line crossed below signal line |
| `volume_above_ma20` | boolean | `true` | Current volume exceeds 20-period average |
| `adx_above` | number | `25` | ADX(14) above 25 (trending market) |
| `price_above_sma_20` | boolean | `true` | Price above 20-period SMA |
| `price_below_sma_50` | boolean | `true` | Price below 50-period SMA |
| `price_above_ema_12` | boolean | `true` | Price above 12-period EMA |
| `bollinger_below_lower` | boolean | `true` | Price below lower Bollinger Band |
| `bollinger_above_upper` | boolean | `true` | Price above upper Bollinger Band |
| `atr_pct_above` | number | `2.0` | ATR as % of price exceeds 2% (volatile) |

**Exit conditions** (any one triggers a sell):

| Condition | Type | Example | Meaning |
|---|---|---|---|
| `stop_loss_pct` | number | `5.0` | Sell if position drops 5% from entry |
| `take_profit_pct` | number | `10.0` | Sell if position gains 10% from entry |
| `trailing_stop_pct` | number | `3.0` | Sell if position drops 3% from its peak |
| `max_hold_candles` | number | `48` | Sell after holding for 48 candles |
| `rsi_14_above` | number | `70` | Sell when RSI becomes overbought |
| `rsi_14_below` | number | `30` | Sell when RSI drops (used for short strategies) |
| `macd_cross_down` | boolean | `true` | Sell on bearish MACD crossover |

### Testing a Strategy

Tell the platform to test your strategy. It runs N backtest episodes automatically.

```
POST /api/v1/strategies/str_abc123/test
{
  "episodes": 200,
  "date_range": {
    "start": "2025-06-01",
    "end": "2025-12-31"
  },
  "randomize_dates": true,
  "episode_duration_days": 7
}
```

**What happens internally:**
1. Backend creates 200 backtest sessions
2. Each session uses a random 7-day window within the date range
3. For each session, the StrategyExecutor reads your rules and makes trading decisions at every candle
4. All sessions run as Celery background tasks (parallel when possible)
5. Results are aggregated into a summary

**Response:**
```json
{
  "test_id": "test_xyz789",
  "status": "queued",
  "episodes_requested": 200,
  "estimated_time_minutes": 5
}
```

### Checking Test Progress

```
GET /api/v1/strategies/str_abc123/tests/test_xyz789
```

While running:
```json
{
  "test_id": "test_xyz789",
  "status": "running",
  "progress": {
    "episodes_completed": 134,
    "episodes_total": 200,
    "pct": 67.0
  },
  "partial_results": {
    "avg_roi_pct": 3.8,
    "avg_sharpe": 1.1,
    "episodes_profitable_pct": 61.2
  }
}
```

### Reading Completed Results

When `status` is `"completed"`:

```json
{
  "test_id": "test_xyz789",
  "status": "completed",
  "strategy_version": 1,
  "results": {
    "episodes_completed": 200,
    "episodes_profitable": 124,
    "episodes_profitable_pct": 62.0,
    
    "avg_roi_pct": 4.3,
    "median_roi_pct": 3.1,
    "best_roi_pct": 28.7,
    "worst_roi_pct": -35.2,
    
    "avg_sharpe": 1.2,
    "avg_max_drawdown_pct": 8.5,
    "avg_trades_per_episode": 23,
    
    "by_pair": {
      "BTCUSDT": { "avg_roi": 5.8, "win_rate": 68.2, "avg_sharpe": 1.5, "trades": 1840 },
      "ETHUSDT": { "avg_roi": 2.1, "win_rate": 54.3, "avg_sharpe": 0.8, "trades": 1260 }
    },
    
    "recommendations": [
      "ETHUSDT significantly underperforms BTCUSDT (2.1% vs 5.8% avg ROI). Consider removing ETHUSDT.",
      "Average max drawdown is 8.5%. Your stop loss at 5% is reasonable.",
      "Win rate of 62% is good. Profit factor suggests take-profit at 10% may be leaving money on table — test 12-15%.",
      "Strategy performs best when ADX > 30 (strong trends). Consider raising ADX filter from 25 to 30."
    ]
  }
}
```

### Improving the Strategy

Based on the results, the agent creates a new version:

```
POST /api/v1/strategies/str_abc123/versions
{
  "definition": {
    "pairs": ["BTCUSDT"],
    "timeframe": "1h",
    "entry_conditions": {
      "rsi_14_below": 35,
      "volume_above_ma20": true,
      "adx_above": 30
    },
    "exit_conditions": {
      "stop_loss_pct": 4.0,
      "take_profit_pct": 12.0,
      "trailing_stop_pct": 3.0
    },
    "position_size_pct": 15,
    "max_positions": 2
  },
  "change_notes": "Dropped ETH (underperforming). Raised ADX filter 25→30. Tightened stop loss 5%→4%. Widened take-profit 10%→12%. Added trailing stop 3%. Increased position size 10%→15%."
}
```

### Comparing Versions

```
GET /api/v1/strategies/str_abc123/compare-versions?v1=1&v2=2
```

```json
{
  "v1": {
    "version": 1,
    "avg_roi_pct": 4.3,
    "avg_sharpe": 1.2,
    "avg_max_drawdown_pct": 8.5,
    "win_rate": 62.0,
    "avg_trades_per_episode": 23
  },
  "v2": {
    "version": 2,
    "avg_roi_pct": 7.1,
    "avg_sharpe": 1.8,
    "avg_max_drawdown_pct": 5.2,
    "win_rate": 71.8,
    "avg_trades_per_episode": 14
  },
  "improvements": {
    "roi_pct": "+2.8% (v2 better)",
    "sharpe": "+0.6 (v2 better)",
    "max_drawdown": "-3.3% (v2 better)",
    "win_rate": "+9.8% (v2 better)"
  },
  "verdict": "v2 outperforms v1 on all key metrics. Fewer trades but higher quality."
}
```

### Deploying

```
POST /api/v1/strategies/str_abc123/deploy
{ "version": 2 }
```

The strategy is now active for live trading. The platform executes the v2 rules against real-time market data with the agent's virtual funds.

### Listing and Managing Strategies

```
GET /api/v1/strategies                        → all your strategies
GET /api/v1/strategies/str_abc123             → one strategy + current version
GET /api/v1/strategies/str_abc123/versions    → version history
PUT /api/v1/strategies/str_abc123             → update name/description
DELETE /api/v1/strategies/str_abc123          → archive
POST /api/v1/strategies/str_abc123/undeploy   → stop live trading
```

---

## Part 2: Gymnasium API (For RL Agents)

### What It Is

The Gymnasium API provides a standard reinforcement learning interface to TradeReady's backtesting engine. RL agents (neural networks trained with algorithms like PPO, DQN, SAC) interact with the trading environment through the universal `reset()`/`step()` contract that every RL library expects.

### Installation

```bash
pip install tradeready-gym stable-baselines3
```

### Quick Start

```python
import gymnasium as gym
import tradeready_gym  # registers TradeReady environments

# Create environment
env = gym.make("TradeReady-BTC-v0",
    api_key="ak_live_...",
    base_url="https://api.tradeready.io",
    starting_balance=10000,
    timeframe="1h",
    lookback_window=30,
)

# Standard Gymnasium loop
observation, info = env.reset()

for _ in range(1000):
    action = env.action_space.sample()  # random agent
    observation, reward, terminated, truncated, info = env.step(action)
    if terminated or truncated:
        observation, info = env.reset()

env.close()
```

### Training with Stable-Baselines3

```python
from stable_baselines3 import PPO

env = gym.make("TradeReady-BTC-v0", api_key="ak_live_...", starting_balance=10000)

model = PPO("MlpPolicy", env, verbose=1, learning_rate=3e-4)
model.train(total_timesteps=100_000)
model.save("btc_trader_v1")
```

During training, the Gym wrapper automatically:
- Creates a new backtest session for each episode
- Reports episode results to TradeReady's training run tracker
- Saves learning curve data to the database

The developer can monitor training progress at `tradeready.io/training` while it runs.

### Available Environments

| Environment ID | Description | Action Space |
|---|---|---|
| `TradeReady-BTC-v0` | Trade BTC/USDT | Discrete(3): Hold, Buy, Sell |
| `TradeReady-ETH-v0` | Trade ETH/USDT | Discrete(3) |
| `TradeReady-SOL-v0` | Trade SOL/USDT | Discrete(3) |
| `TradeReady-BTC-Continuous-v0` | Trade BTC with continuous sizing | Box(-1, 1) |
| `TradeReady-ETH-Continuous-v0` | Trade ETH with continuous sizing | Box(-1, 1) |
| `TradeReady-Portfolio-v0` | Trade multiple assets | Box(0, 1, shape=(N,)) |
| `TradeReady-Live-v0` | Real-time simulation (not historical) | Configurable |

### Action Spaces

**Discrete (default):** `Discrete(3)` — 0=Hold, 1=Buy (10% of balance), 2=Sell (close position)

**Continuous:** `Box(-1, 1, shape=(1,))` — -1.0=Sell everything, 0.0=Hold, +1.0=Buy with all available. The magnitude determines position size.

**Portfolio:** `Box(0, 1, shape=(N,))` — target weight for each of N assets. The wrapper generates rebalancing orders.

### Observation Space

Default observation is a `Box` containing:

| Feature | Shape | Description |
|---|---|---|
| OHLCV candles | (window, 5) | Last N candles: open, high, low, close, volume |
| RSI(14) | (window, 1) | Relative Strength Index |
| MACD | (window, 3) | MACD line, signal, histogram |
| Balance | (1,) | Available USDT (normalized to starting balance) |
| Position size | (1,) | Current position (normalized) |
| Unrealized PnL | (1,) | Current unrealized profit/loss (normalized) |

Customizable via parameters:

```python
env = gym.make("TradeReady-BTC-v0",
    observation_features=["ohlcv", "rsi_14", "macd", "bollinger", "balance", "position"],
    lookback_window=50,
)
```

### Reward Functions

```python
# Simple PnL change (default)
env = gym.make("TradeReady-BTC-v0", reward_function="pnl")

# Risk-adjusted (Sharpe-like)
env = gym.make("TradeReady-BTC-v0", reward_function="sharpe")

# Downside-risk-adjusted
env = gym.make("TradeReady-BTC-v0", reward_function="sortino")

# PnL minus drawdown penalty
env = gym.make("TradeReady-BTC-v0", reward_function="drawdown_penalty")

# Custom
from tradeready_gym.rewards import CustomReward

class MyReward(CustomReward):
    def compute(self, prev_equity, curr_equity, info):
        return your_logic_here

env = gym.make("TradeReady-BTC-v0", reward_function=MyReward())
```

### Vectorized Training (Parallel)

```python
# 8 environments running in parallel
envs = gym.make_vec("TradeReady-BTC-v0", num_envs=8,
    api_key="ak_live_...", vectorization_mode="async")

model = PPO("MlpPolicy", envs, verbose=1)
model.train(total_timesteps=500_000)
```

Each environment is a separate backtest session on the TradeReady backend. All 8 run concurrently.

---

## Part 3: How Both Systems Connect

### The Architecture

```
                ┌─────────────────────────────────┐
                │      TradeReady Database          │
                │                                  │
                │  strategies → versions → tests   │
                │  training_runs → episodes         │
                │  backtest_sessions → trades       │
                │                                  │
                └───────────┬──────────────────────┘
                            │
              ┌─────────────┼─────────────────────┐
              │             │                     │
         ┌────▼────┐  ┌────▼──────┐  ┌───────────▼──────┐
         │ Strategy │  │ Training  │  │   Backtest       │
         │ Registry │  │ Tracker   │  │   Engine         │
         │ (CRUD)   │  │ (aggreg.) │  │   (step/sandbox) │
         └────┬─────┘  └────┬──────┘  └────────┬─────────┘
              │             │                   │
    ┌─────────┤             │                   │
    │         │             │                   │
┌───▼────┐ ┌──▼──────┐  ┌──▼───────────┐  ┌───▼──────────┐
│REST API│ │MCP Tools│  │Gym Wrapper   │  │Direct        │
│/strat/*│ │(15 new) │  │(PyPI pkg)    │  │Backtest API  │
└───┬────┘ └──┬──────┘  └──┬───────────┘  └───┬──────────┘
    │         │            │                   │
┌───▼────┐ ┌──▼──────┐  ┌──▼───────────┐  ┌───▼──────────┐
│LLM     │ │Claude   │  │RL Agents     │  │Manual        │
│Agents  │ │Desktop  │  │(SB3, RLlib)  │  │Backtesting   │
└────────┘ └─────────┘  └──────────────┘  └──────────────┘
```

### Data Flows Between Systems

**LLM agent creates strategy → RL agent trains it:**
1. LLM agent calls `POST /strategies` with trading rules
2. Developer exports the strategy definition
3. Developer creates a custom Gym reward function based on the strategy's logic
4. RL agent trains via Gym, optimizing the neural network policy
5. Training results appear in the database
6. LLM agent reads training results via `GET /training/runs/{id}`
7. LLM agent decides whether to adjust the strategy or deploy

**RL agent discovers strategy → LLM agent manages it:**
1. RL agent trains via Gym, discovers profitable behavior
2. Developer analyzes what the trained agent learned
3. Developer (or LLM agent) codifies the learned behavior into a strategy definition
4. LLM agent manages the strategy lifecycle: testing, versioning, deployment
5. LLM agent monitors live performance and triggers retraining when needed

**Fully autonomous loop:**
1. LLM agent creates strategy v1
2. LLM agent calls `POST /strategies/{id}/test` (backend runs 200 episodes)
3. LLM agent reads results and recommendations
4. LLM agent creates v2 with improvements
5. LLM agent tests v2, compares with v1
6. LLM agent deploys the winner
7. LLM agent monitors live performance via existing analytics endpoints
8. When performance degrades, LLM agent creates v3 and repeats

---

## Part 4: MCP Tools Reference

These tools are available when using TradeReady via Claude Desktop or any MCP-compatible client.

### Strategy Management Tools

| Tool | Description | Parameters |
|---|---|---|
| `create_strategy` | Create a new trading strategy | `name`, `definition` (JSON) |
| `get_strategies` | List all your strategies | none |
| `get_strategy` | Get strategy + current version + latest results | `strategy_id` |
| `create_strategy_version` | Save improved rules as new version | `strategy_id`, `definition`, `change_notes` |
| `get_strategy_versions` | See version history | `strategy_id` |
| `deploy_strategy` | Deploy to live trading | `strategy_id`, `version` |
| `undeploy_strategy` | Stop live trading | `strategy_id` |

### Strategy Testing Tools

| Tool | Description | Parameters |
|---|---|---|
| `run_strategy_test` | Test across N episodes | `strategy_id`, `episodes`, `date_range` |
| `get_test_status` | Check test progress | `strategy_id`, `test_id` |
| `get_test_results` | Full results with recommendations | `strategy_id`, `test_id` |
| `compare_versions` | Compare two versions side by side | `strategy_id`, `v1`, `v2` |
| `get_recommendations` | AI-generated improvement suggestions | `strategy_id` |

### Training Observation Tools

| Tool | Description | Parameters |
|---|---|---|
| `get_training_runs` | List all RL training runs | none |
| `get_training_run_detail` | Full detail + learning curve | `run_id` |
| `compare_training_runs` | Compare multiple runs | `run_ids` (list) |

---

## Part 5: UI Overview

The UI provides read-only observation of strategies and training. No buttons create or modify strategies — agents do that via API.

### Strategy Pages

**`/strategies`** — lists all strategies with status badges, latest test results, and deploy state.

**`/strategies/[id]`** — full detail: version history timeline, strategy definition viewer (shows the JSON rules in a readable format), test results with metrics and recommendations, version comparison.

### Training Pages

**`/training`** — lists all training runs. Active runs show a live learning curve and episode counter. Completed runs show sparkline learning curves in a sortable table.

**`/training/[run_id]`** — deep dive: full interactive learning curve chart with metric selector and smoothing slider, best/worst episode cards with mini equity curves, searchable/sortable episode table. Click any episode to see its full backtest results on the existing `/backtest/[session_id]` page.

### Dashboard Integration

The main agent dashboard (`/dashboard`) shows a strategy status card (deployed strategy name, version, live ROI) and a training status card (active training run, episode count, learning trend).

---

## Part 6: Glossary

| Term | Definition |
|---|---|
| **Strategy** | A set of trading rules (entry/exit conditions, position sizing, pair selection) stored as JSON |
| **Strategy Version** | A numbered iteration of a strategy's rules. v1 → v2 → v3 as the agent improves |
| **Test Run** | A batch of backtest episodes testing a specific strategy version |
| **Episode** | A single backtest session — one complete run through historical data |
| **Training Run** | A group of episodes generated by an RL agent training through the Gym API |
| **Learning Curve** | A chart showing how an RL agent's performance improves over episodes |
| **Strategy Executor** | The backend component that reads a strategy definition and makes trading decisions |
| **Indicator Engine** | Computes RSI, MACD, Bollinger Bands, etc. from price data |
| **Recommendation Engine** | Analyzes test results and suggests improvements |
| **Gymnasium** | The standard Python API for RL environments (formerly OpenAI Gym) |
| **Stable-Baselines3** | The most popular RL training library, compatible with Gymnasium |
| **Deploy** | Activate a strategy for live trading against real-time market data (virtual funds) |

---

*This document describes the target system. Implementation status is tracked in `gym_strategy_development_plan.md`.*
