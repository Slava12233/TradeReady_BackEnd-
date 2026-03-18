# TradeReady Strategy & Gym API — Complete Guide

> Build, test, deploy, and train AI trading strategies on the TradeReady platform.

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Strategy System](#strategy-system)
   - [Creating a Strategy](#creating-a-strategy)
   - [Strategy Definition Reference](#strategy-definition-reference)
   - [Entry Conditions (ALL must pass)](#entry-conditions)
   - [Exit Conditions (ANY triggers)](#exit-conditions)
   - [Versioning](#versioning)
   - [Testing](#testing-strategies)
   - [Recommendations](#recommendations)
   - [Deploying](#deploying-a-strategy)
4. [Gymnasium Environments (tradeready-gym)](#gymnasium-environments)
   - [Installation](#installation)
   - [Registered Environments](#registered-environments)
   - [Single Asset Trading](#single-asset-trading)
   - [Multi-Asset Portfolio](#multi-asset-portfolio)
   - [Live Trading](#live-trading)
   - [Observation Space](#observation-space)
   - [Reward Functions](#reward-functions)
   - [Wrappers](#wrappers)
   - [Training Tracker](#training-tracker)
5. [Training Observation API](#training-observation-api)
6. [Improving Existing Agents](#improving-existing-agents-with-strategies)
7. [MCP Tools Reference](#mcp-tools-reference)
8. [SDK Reference](#sdk-reference)
9. [REST API Reference](#rest-api-reference)
10. [Indicators Reference](#indicators-reference)
11. [Examples](#examples)
12. [Architecture](#architecture)

---

## Overview

The TradeReady platform provides a complete pipeline for AI-driven crypto trading:

```
Define Strategy  -->  Test (multi-episode)  -->  Read Results  -->  Improve  -->  Deploy
      |                                                                            |
      v                                                                            v
  RL Training (Gym)  -->  Track Progress  -->  Compare Runs  -->  Best Model  -->  Live
```

**Three interfaces** to interact with the system:

| Interface | Best For | How |
|-----------|----------|-----|
| **REST API** | Programmatic access, custom dashboards | HTTP calls to `localhost:8000/api/v1` |
| **MCP Tools** | AI agents (Claude, GPT) managing strategies | 15 tools via MCP protocol |
| **Python SDK** | Python scripts, Jupyter notebooks | `pip install agentexchange-sdk` |
| **Gym Package** | RL training with Stable-Baselines3, RLlib, etc. | `pip install tradeready-gym` |

**What you can do:**
- Create rule-based strategies with 12 entry conditions and 7 exit conditions
- Test strategies across randomized historical episodes with automated metrics
- Get AI-generated recommendations to improve your strategy
- Train RL agents using OpenAI Gymnasium-compatible environments
- Track training progress with learning curves and episode metrics
- Deploy strategies to live paper trading
- Compare strategy versions and training runs side-by-side

---

## Quick Start

### For Human Users (API/SDK)

```python
from agentexchange import AgentExchangeClient

client = AgentExchangeClient(api_key="ak_live_...")

# 1. Create a strategy
strategy = client.create_strategy(
    name="RSI Momentum",
    definition={
        "pairs": ["BTCUSDT", "ETHUSDT"],
        "timeframe": "1h",
        "entry_conditions": {"rsi_below": 30, "volume_above_ma": 1.5},
        "exit_conditions": {"take_profit_pct": 5, "stop_loss_pct": 2},
        "position_size_pct": 10,
        "max_positions": 3
    }
)
sid = strategy["strategy_id"]

# 2. Test it (10 episodes across 60 days of history)
test = client.run_test(sid, version=1, episodes=10,
    date_range={"start": "2025-06-01", "end": "2025-08-01"})

# 3. Check results
results = client.get_test_results(sid, test["test_run_id"])
print(f"Avg ROI: {results['results']['avg_roi_pct']}%")
print(f"Recommendations: {results['recommendations']}")

# 4. Improve and create v2
v2 = client.create_version(sid,
    definition={...improved...},
    change_notes="Tightened stop loss based on recommendations")

# 5. Compare versions
comparison = client.compare_versions(sid, v1=1, v2=2)
print(comparison["verdict"])

# 6. Deploy the better version
client.deploy_strategy(sid, version=2)
```

### For RL Training (Gym)

```python
import gymnasium as gym
import tradeready_gym  # registers environments

env = gym.make("TradeReady-BTC-v0",
    api_key="ak_live_...",
    starting_balance=10000,
    timeframe="1h",
    start_time="2025-01-01T00:00:00Z",
    end_time="2025-03-01T00:00:00Z",
)

obs, info = env.reset()
for _ in range(1000):
    action = env.action_space.sample()  # Your model here
    obs, reward, terminated, truncated, info = env.step(action)
    if terminated or truncated:
        obs, info = env.reset()
env.close()
```

### For AI Agents (MCP)

```
User: Create a BTC scalping strategy with RSI and MACD conditions

Agent: [calls create_strategy tool]
       [calls run_strategy_test tool with 20 episodes]
       [calls get_test_results tool]
       [calls get_strategy_recommendations tool]
       "Your strategy achieved 3.2% avg ROI with 0.8 Sharpe.
        Recommendations: tighten stop loss to 1.5%, add ADX filter > 25"
```

---

## Strategy System

### Creating a Strategy

A strategy is a named, versioned set of trading rules. Create one via any interface:

**REST API:**
```bash
curl -X POST http://localhost:8000/api/v1/strategies \
  -H "Authorization: Bearer $JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "MACD Crossover",
    "description": "Buy on MACD bullish cross, sell on bearish cross",
    "definition": {
      "pairs": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
      "timeframe": "4h",
      "entry_conditions": {
        "macd_cross_above": true,
        "adx_above": 25,
        "volume_above_ma": 1.2
      },
      "exit_conditions": {
        "macd_cross_below": true,
        "take_profit_pct": 8,
        "stop_loss_pct": 3,
        "trailing_stop_pct": 2,
        "max_hold_candles": 48
      },
      "position_size_pct": 10,
      "max_positions": 4
    }
  }'
```

### Strategy Definition Reference

```json
{
  "pairs": ["BTCUSDT", "ETHUSDT"],       // Required. 1+ trading pairs
  "timeframe": "1h",                      // "1m" | "5m" | "15m" | "1h" | "4h" | "1d"
  "entry_conditions": { ... },            // ALL conditions must pass to enter
  "exit_conditions": { ... },             // ANY condition triggers exit
  "position_size_pct": 10,                // 1-100, % of equity per position
  "max_positions": 3,                     // 1-50, max concurrent positions
  "filters": {},                          // Optional additional filters
  "model_type": "rule_based",             // "rule_based" | "ml" | "rl"
  "model_reference": null                 // Optional model artifact reference
}
```

### Entry Conditions

All entry conditions use AND logic — **every** non-null condition must be true to generate a buy signal.

| Condition Key | Type | Description | Example |
|---------------|------|-------------|---------|
| `rsi_below` | `float` | RSI(14) must be below this value (oversold) | `30` |
| `rsi_above` | `float` | RSI(14) must be above this value (momentum) | `50` |
| `macd_cross_above` | `bool` | MACD line crossed above signal line | `true` |
| `macd_cross_below` | `bool` | MACD line crossed below signal line | `true` |
| `price_above_sma` | `int` | Price > SMA of this period | `50` (SMA-50) |
| `price_below_sma` | `int` | Price < SMA of this period | `20` (SMA-20) |
| `price_above_ema` | `int` | Price > EMA of this period | `12` (EMA-12) |
| `price_below_ema` | `int` | Price < EMA of this period | `26` (EMA-26) |
| `bb_below_lower` | `bool` | Price below lower Bollinger Band (mean reversion) | `true` |
| `bb_above_upper` | `bool` | Price above upper Bollinger Band (breakout) | `true` |
| `adx_above` | `float` | ADX(14) above threshold (trend strength filter) | `25` |
| `volume_above_ma` | `float` | Volume > N x 20-period volume MA | `1.5` (150% of avg) |

**Strategy patterns:**

| Style | Entry Conditions |
|-------|-----------------|
| RSI Oversold Bounce | `{"rsi_below": 30, "adx_above": 20}` |
| MACD Momentum | `{"macd_cross_above": true, "volume_above_ma": 1.2}` |
| Bollinger Mean Reversion | `{"bb_below_lower": true, "rsi_below": 40, "adx_below": 30}` |
| Trend Following | `{"price_above_sma": 50, "macd_cross_above": true, "adx_above": 25}` |
| Volume Breakout | `{"price_above_ema": 20, "volume_above_ma": 2.0, "adx_above": 30}` |

### Exit Conditions

Exit conditions use OR logic — **any** condition triggers a sell. Priority order:

```
stop_loss  >  take_profit  >  trailing_stop  >  max_hold_candles  >  indicator exits
```

| Condition Key | Type | Range | Description |
|---------------|------|-------|-------------|
| `stop_loss_pct` | `float` | 0-100 | Exit when loss from entry >= this % |
| `take_profit_pct` | `float` | 0-1000 | Exit when gain from entry >= this % |
| `trailing_stop_pct` | `float` | 0-100 | Exit when price drops this % from peak since entry |
| `max_hold_candles` | `int` | >= 1 | Force exit after N candles (prevents stuck positions) |
| `rsi_above` | `float` | — | Exit when RSI rises above value (overbought) |
| `rsi_below` | `float` | — | Exit when RSI drops below value |
| `macd_cross_below` | `bool` | — | Exit when MACD turns bearish |

**Recommended exit combos:**

| Style | Exit Conditions |
|-------|----------------|
| Conservative | `{"stop_loss_pct": 2, "take_profit_pct": 4, "max_hold_candles": 24}` |
| Trailing | `{"stop_loss_pct": 3, "trailing_stop_pct": 1.5, "take_profit_pct": 10}` |
| Indicator-based | `{"rsi_above": 70, "macd_cross_below": true, "stop_loss_pct": 5}` |
| Aggressive | `{"stop_loss_pct": 1, "take_profit_pct": 2, "max_hold_candles": 12}` |

### Versioning

Strategies support immutable versioning — you never overwrite a version, only create new ones.

```python
# Create v2 with improvements
v2 = client.create_version(strategy_id,
    definition={...updated conditions...},
    change_notes="Tightened RSI threshold from 30 to 25, added trailing stop"
)
# v2.version == 2, v2.parent_version == 1

# Compare v1 vs v2
comparison = client.compare_versions(strategy_id, v1=1, v2=2)
# Returns: {
#   "v1": {"avg_roi_pct": 2.1, "avg_sharpe": 0.8, ...},
#   "v2": {"avg_roi_pct": 3.5, "avg_sharpe": 1.2, ...},
#   "improvements": {"avg_roi_pct": 66.7, "avg_sharpe": 50.0},
#   "verdict": "Version 2 outperforms on 3/4 metrics"
# }
```

### Testing Strategies

Test a strategy version across multiple randomized historical episodes:

```python
test = client.run_test(
    strategy_id=sid,
    version=2,
    episodes=20,                           # Number of test episodes
    date_range={"start": "2025-01-01", "end": "2025-06-01"},
    episode_duration_days=30,              # Each episode spans 30 days
)

# Poll for completion
import time
while True:
    status = client.get_test_status(sid, test["test_run_id"])
    print(f"Progress: {status['progress_pct']:.0f}%")
    if status["status"] in ("completed", "failed"):
        break
    time.sleep(5)

# Get results
results = client.get_test_results(sid, test["test_run_id"])
```

**Result metrics:**

| Metric | Description |
|--------|-------------|
| `episodes_completed` | Number of episodes that ran |
| `episodes_profitable` | Episodes with positive ROI |
| `episodes_profitable_pct` | % of profitable episodes |
| `avg_roi_pct` | Average ROI across episodes |
| `median_roi_pct` | Median ROI |
| `best_roi_pct` / `worst_roi_pct` | Best and worst single-episode ROI |
| `std_roi_pct` | Standard deviation of ROI |
| `avg_sharpe` | Average Sharpe ratio |
| `avg_max_drawdown_pct` | Average maximum drawdown |
| `avg_trades_per_episode` | Average number of trades |
| `total_trades` | Total trades across all episodes |

Results also include **by-pair breakdown** — the same metrics grouped by trading pair, so you can identify which pairs perform best.

### Recommendations

After a test completes, the Recommendation Engine analyzes results and generates actionable suggestions:

| Trigger | Recommendation |
|---------|---------------|
| Pair ROI disparity > 5% | Remove the underperforming pair |
| Win rate < 50% | Tighten entry conditions or widen take-profit |
| Win rate > 75% | Relax entry conditions to capture more opportunities |
| Max drawdown > 15% | Tighten stop-loss |
| Max drawdown < 3% | Stop-loss may be too tight — loosen it |
| < 3 trades/episode | Entry conditions too restrictive |
| > 50 trades/episode | Add ADX filter to reduce overtrading |
| Sharpe < 0.5 | Reduce position size or improve entry timing |
| ADX threshold > 30 | Consider lowering to 20-25 |
| ADX threshold < 15 | Raise to 20+ for better trend filtering |
| TP/SL ratio < 1.5:1 | Widen take-profit or tighten stop-loss |
| Avg ROI negative | Strategy is losing money — review entry and exit |

```python
results = client.get_test_results(sid, test_id)
for rec in results["recommendations"]:
    print(f"  - {rec}")
```

### Deploying a Strategy

Deploy a tested version to go live:

```python
# Deploy version 3
client.deploy_strategy(strategy_id, version=3)

# Check status — now shows "deployed"
strategy = client.get_strategy(strategy_id)
assert strategy["status"] == "deployed"

# Undeploy when done
client.undeploy_strategy(strategy_id)
```

**Strategy lifecycle:**

```
draft  ──>  testing (automatic during test runs)
               |
               v
          validated (test completed)
               |
               v
           deployed (live trading)
               |
               v
           archived (soft delete)
```

---

## Gymnasium Environments

### Installation

```bash
pip install tradeready-gym

# Or install from source
cd tradeready-gym
pip install -e .

# With RL frameworks
pip install tradeready-gym stable-baselines3 torch
```

**Requirements:** Python 3.12+, Gymnasium >= 0.29, numpy >= 1.26, httpx >= 0.28, running TradeReady platform.

### Registered Environments

```python
import gymnasium as gym
import tradeready_gym  # This registers all environments

# Discrete action spaces (Hold/Buy/Sell)
env = gym.make("TradeReady-BTC-v0", api_key="ak_live_...")
env = gym.make("TradeReady-ETH-v0", api_key="ak_live_...")
env = gym.make("TradeReady-SOL-v0", api_key="ak_live_...")

# Continuous action spaces (position sizing)
env = gym.make("TradeReady-BTC-Continuous-v0", api_key="ak_live_...")
env = gym.make("TradeReady-ETH-Continuous-v0", api_key="ak_live_...")

# Multi-asset portfolio allocation
env = gym.make("TradeReady-Portfolio-v0", api_key="ak_live_...")

# Live paper trading (real-time)
env = gym.make("TradeReady-Live-v0", api_key="ak_live_...")
```

### Single Asset Trading

Two modes: **discrete** and **continuous**.

**Discrete (Hold/Buy/Sell):**

```python
env = gym.make("TradeReady-BTC-v0",
    api_key="ak_live_...",
    starting_balance=10000,
    timeframe="1h",
    lookback_window=30,
    start_time="2025-01-01T00:00:00Z",
    end_time="2025-03-01T00:00:00Z",
)

# action_space = Discrete(3)
# 0 = Hold, 1 = Buy (10% of equity), 2 = Sell (close position)
```

**Continuous (Direction + Magnitude):**

```python
env = gym.make("TradeReady-BTC-Continuous-v0",
    api_key="ak_live_...",
    starting_balance=10000,
)

# action_space = Box(-1.0, 1.0, shape=(1,))
# |signal| < 0.05: Hold (dead zone)
# signal > 0.05:   Buy, quantity = |signal| * position_size_pct * equity / price
# signal < -0.05:  Sell same formula
```

### Multi-Asset Portfolio

Target portfolio weights — the environment generates rebalancing orders:

```python
env = gym.make("TradeReady-Portfolio-v0",
    api_key="ak_live_...",
    pairs=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    starting_balance=50000,
)

# action_space = Box(0.0, 1.0, shape=(3,))
# Each value = target weight for that asset
# [0.5, 0.3, 0.2] = 50% BTC, 30% ETH, 20% SOL
# Weights > 1 total are normalized; remainder stays as cash
```

### Live Trading

Real-time paper trading with actual market prices:

```python
env = gym.make("TradeReady-Live-v0",
    api_key="ak_live_...",
    pairs=["BTCUSDT"],
    step_interval_sec=60,  # Wait 60s between steps
)

obs, info = env.reset()
while True:
    action = model.predict(obs)
    obs, reward, _, _, info = env.step(action)
    # Never terminates — runs until env.close()
```

### Observation Space

Configure what your model sees via `observation_features`:

```python
env = gym.make("TradeReady-BTC-v0",
    api_key="ak_live_...",
    lookback_window=30,
    observation_features=[
        "ohlcv",          # Open, High, Low, Close, Volume (5 dims/candle)
        "rsi_14",         # RSI normalized to [0,1] (1 dim/candle)
        "macd",           # MACD line, signal, histogram (3 dims/candle)
        "bollinger",      # Upper, middle, lower bands (3 dims/candle)
        "volume",         # Raw volume (1 dim/candle)
        "adx",            # Trend strength (1 dim/candle)
        "atr",            # Average True Range (1 dim/candle)
        "balance",        # Cash / starting_balance (1 scalar)
        "position",       # Position value / equity (1 scalar)
        "unrealized_pnl", # Unrealized PnL / equity (1 scalar)
    ]
)

# Observation shape: (lookback_window * windowed_dims * n_assets + scalar_dims,)
# Example: 30 * 15 * 1 + 3 = 453 for single-asset with all features
```

**Feature dimensions:**

| Feature | Dims per candle | Type |
|---------|-----------------|------|
| `ohlcv` | 5 | Windowed (per candle in lookback) |
| `rsi_14` | 1 | Windowed |
| `macd` | 3 | Windowed |
| `bollinger` | 3 | Windowed |
| `volume` | 1 | Windowed |
| `adx` | 1 | Windowed |
| `atr` | 1 | Windowed |
| `balance` | 1 | Scalar (appended once) |
| `position` | 1 | Scalar |
| `unrealized_pnl` | 1 | Scalar |

### Reward Functions

Choose how your agent is rewarded:

```python
from tradeready_gym.rewards import (
    PnLReward,
    LogReturnReward,
    SharpeReward,
    SortinoReward,
    DrawdownPenaltyReward,
    CustomReward,
)

# Simple equity change (default)
env = gym.make("TradeReady-BTC-v0", reward_function=PnLReward())

# Log returns (more stable gradients)
env = gym.make("TradeReady-BTC-v0", reward_function=LogReturnReward())

# Risk-adjusted: rolling Sharpe ratio delta
env = gym.make("TradeReady-BTC-v0", reward_function=SharpeReward(window=50))

# Downside risk: rolling Sortino ratio delta
env = gym.make("TradeReady-BTC-v0", reward_function=SortinoReward(window=50))

# PnL with drawdown penalty
env = gym.make("TradeReady-BTC-v0",
    reward_function=DrawdownPenaltyReward(penalty_coeff=1.0))
```

| Reward | Formula | Best For |
|--------|---------|----------|
| `PnLReward` | `curr_equity - prev_equity` | Simple baselines |
| `LogReturnReward` | `log(curr / prev)` | Stable gradient training |
| `SharpeReward` | Rolling Sharpe delta | Risk-adjusted strategies |
| `SortinoReward` | Rolling Sortino delta | Downside risk focus |
| `DrawdownPenaltyReward` | PnL - penalty * drawdown | Capital preservation |

**Custom reward:**

```python
from tradeready_gym.rewards import CustomReward

class MyReward(CustomReward):
    def compute(self, prev_equity, curr_equity, info):
        pnl = curr_equity - prev_equity
        # Bonus for profitable trades
        filled = len(info.get("filled_orders", []))
        return pnl + 0.01 * filled

env = gym.make("TradeReady-BTC-v0", reward_function=MyReward())
```

### Wrappers

Enhance environments with additional processing:

```python
from tradeready_gym.wrappers import (
    FeatureEngineeringWrapper,
    NormalizationWrapper,
    BatchStepWrapper,
)

env = gym.make("TradeReady-BTC-v0", api_key="ak_live_...")

# Add SMA ratios and momentum to observations
env = FeatureEngineeringWrapper(env, periods=[5, 10, 20])

# Normalize observations to [-1, 1] using online z-score
env = NormalizationWrapper(env, clip=1.0)

# Execute 5 underlying steps per action (reduces HTTP overhead)
env = BatchStepWrapper(env, n_steps=5)
```

| Wrapper | What it does | When to use |
|---------|-------------|-------------|
| `FeatureEngineeringWrapper` | Adds SMA ratios + momentum to obs | When you want derived features without custom obs |
| `NormalizationWrapper` | Online z-score normalization, clips to [-1,1] | Always recommended for neural network training |
| `BatchStepWrapper` | N steps per action, sums rewards | Reduce API latency during training |

### Training Tracker

Training progress is automatically reported to the platform when `track_training=True` (default):

```python
env = gym.make("TradeReady-BTC-v0",
    api_key="ak_live_...",
    track_training=True,     # Default: auto-report to training API
    strategy_label="ppo_v1", # Label for filtering in UI
)

# Every reset() registers a new episode
# Every env.close() completes the training run
# Progress visible at http://localhost:3001/training
```

The tracker:
1. Registers a training run on first `reset()` call
2. Reports episode metrics (ROI, Sharpe, drawdown, trades, reward) after each episode
3. Marks the run as complete on `env.close()`

Backtest sessions created by the gym use `strategy_label` prefixed with `gym_` or `training_` — the UI can filter these out from the regular backtest list.

---

## Training Observation API

Monitor RL training runs from the UI or programmatically:

### List Training Runs

```bash
GET /api/v1/training/runs?status=running&limit=20
```

### Get Run Detail (with learning curve)

```bash
GET /api/v1/training/runs/{run_id}
```

Returns: run metadata + `learning_curve` (smoothed metrics over episodes) + `aggregate_stats` + individual episodes.

### Learning Curve Data

```bash
GET /api/v1/training/runs/{run_id}/learning-curve?metric=roi_pct&window=10
```

Available metrics: `roi_pct`, `sharpe_ratio`, `max_drawdown_pct`, `total_trades`, `reward_sum`

### Compare Training Runs

```bash
GET /api/v1/training/compare?run_ids=uuid1,uuid2,uuid3
```

---

## Improving Existing Agents with Strategies

Here's how to use the Strategy & Gym system to improve your existing trading agents:

### Step 1: Analyze Your Agent's Current Performance

```python
client = AgentExchangeClient(api_key="ak_live_YOUR_AGENT_KEY")
perf = client.get_performance(period="30d")
print(f"Sharpe: {perf['sharpe_ratio']}")
print(f"Win Rate: {perf['win_rate']}")
print(f"Max Drawdown: {perf['max_drawdown_pct']}%")
```

### Step 2: Create a Strategy That Matches Your Agent's Logic

Encode your agent's trading rules as a strategy definition:

```python
strategy = client.create_strategy(
    name="My Agent v1 - Encoded Rules",
    definition={
        "pairs": ["BTCUSDT", "ETHUSDT"],
        "timeframe": "1h",
        "entry_conditions": {
            "rsi_below": 35,           # Your agent's buy signal
            "macd_cross_above": True,   # Confirmation
            "adx_above": 20            # Trend filter
        },
        "exit_conditions": {
            "stop_loss_pct": 3,         # Your current risk management
            "take_profit_pct": 6,
            "trailing_stop_pct": 2
        },
        "position_size_pct": 10,
        "max_positions": 3
    }
)
```

### Step 3: Test Against History

```python
test = client.run_test(strategy["strategy_id"], version=1,
    episodes=20,
    date_range={"start": "2025-01-01", "end": "2025-07-01"},
    episode_duration_days=30
)

# Wait for completion...
results = client.get_test_results(strategy["strategy_id"], test["test_run_id"])
```

### Step 4: Read Recommendations and Iterate

```python
for rec in results["recommendations"]:
    print(f"  Suggestion: {rec}")

# Create an improved version based on recommendations
v2 = client.create_version(strategy["strategy_id"],
    definition={
        "pairs": ["BTCUSDT", "ETHUSDT"],
        "timeframe": "1h",
        "entry_conditions": {
            "rsi_below": 30,           # Tightened per recommendation
            "macd_cross_above": True,
            "adx_above": 25,           # Raised per recommendation
            "volume_above_ma": 1.3     # Added volume confirmation
        },
        "exit_conditions": {
            "stop_loss_pct": 2,        # Tightened per recommendation
            "take_profit_pct": 5,
            "trailing_stop_pct": 1.5,  # Added trailing stop
            "max_hold_candles": 48     # Time-based exit
        },
        "position_size_pct": 8,
        "max_positions": 3
    },
    change_notes="Applied recommendations: tighter SL, volume filter, trailing stop"
)

# Test v2 and compare
test2 = client.run_test(strategy["strategy_id"], version=2, episodes=20, ...)
comparison = client.compare_versions(strategy["strategy_id"], v1=1, v2=2)
print(comparison["verdict"])
```

### Step 5: Train an RL Agent to Improve Further

Use the Gym package to train a neural network that learns optimal entry/exit timing:

```python
import gymnasium as gym
import tradeready_gym
from stable_baselines3 import PPO

# Train on historical data
env = gym.make("TradeReady-BTC-Continuous-v0",
    api_key="ak_live_...",
    starting_balance=10000,
    timeframe="1h",
    lookback_window=50,
    observation_features=["ohlcv", "rsi_14", "macd", "bollinger", "balance", "position"],
    reward_function=SharpeReward(window=50),
    start_time="2025-01-01T00:00:00Z",
    end_time="2025-07-01T00:00:00Z",
    track_training=True,
)

# Normalize observations
from tradeready_gym.wrappers import NormalizationWrapper
env = NormalizationWrapper(env)

# Train with PPO
model = PPO("MlpPolicy", env, verbose=1,
    learning_rate=3e-4,
    n_steps=2048,
    batch_size=64,
    n_epochs=10,
)
model.learn(total_timesteps=100_000)
model.save("ppo_btc_trader")
env.close()  # Completes the training run — visible in UI
```

### Step 6: Monitor Training in the UI

Navigate to `http://localhost:3001/training` to see:
- **Active training card** — live episode count and progress
- **Learning curves** — ROI, Sharpe, and reward over episodes
- **Episode table** — individual episode metrics
- **Run comparison** — compare PPO vs DQN or different hyperparameters

### Step 7: Deploy the Best Strategy

```python
# Deploy the best rule-based version
client.deploy_strategy(strategy["strategy_id"], version=2)

# Or use the trained RL model for live trading
env = gym.make("TradeReady-Live-v0",
    api_key="ak_live_...",
    pairs=["BTCUSDT"],
    step_interval_sec=60,
)
model = PPO.load("ppo_btc_trader")
obs, info = env.reset()
while True:
    action, _ = model.predict(obs)
    obs, reward, _, _, info = env.step(action)
```

### Improvement Workflow Summary

```
Current Agent Performance
        |
        v
Encode rules as Strategy Definition
        |
        v
Test across 20+ historical episodes  ──>  Read metrics + recommendations
        |                                          |
        v                                          v
Create improved version (v2)           Train RL agent with Gym
        |                                          |
        v                                          v
Compare v1 vs v2                       Monitor training curves
        |                                          |
        v                                          v
Deploy best version                    Deploy trained model to live
```

---

## MCP Tools Reference

15 MCP tools for AI agent workflows:

### Strategy Management (7 tools)

| Tool | Required Args | Optional Args |
|------|--------------|---------------|
| `create_strategy` | `name`, `definition` | `description` |
| `get_strategies` | — | `status`, `limit`, `offset` |
| `get_strategy` | `strategy_id` | — |
| `create_strategy_version` | `strategy_id`, `definition` | `change_notes` |
| `get_strategy_versions` | `strategy_id` | — |
| `deploy_strategy` | `strategy_id`, `version` | — |
| `undeploy_strategy` | `strategy_id` | — |

### Strategy Testing (5 tools)

| Tool | Required Args | Optional Args |
|------|--------------|---------------|
| `run_strategy_test` | `strategy_id`, `version` | `episodes`, `date_range`, `episode_duration_days` |
| `get_test_status` | `strategy_id`, `test_id` | — |
| `get_test_results` | `strategy_id`, `test_id` | — |
| `compare_versions` | `strategy_id`, `v1`, `v2` | — |
| `get_strategy_recommendations` | `strategy_id` | — |

### Training Observation (3 tools)

| Tool | Required Args | Optional Args |
|------|--------------|---------------|
| `get_training_runs` | — | `status`, `limit`, `offset` |
| `get_training_run_detail` | `run_id` | — |
| `compare_training_runs` | `run_ids` (comma-separated) | — |

---

## SDK Reference

```python
from agentexchange import AgentExchangeClient
# or
from agentexchange import AsyncAgentExchangeClient

client = AgentExchangeClient(api_key="ak_live_...")
```

### Strategy Methods

```python
client.create_strategy(name, definition, description=None)
client.get_strategies(status=None, limit=50, offset=0)
client.get_strategy(strategy_id)
client.create_version(strategy_id, definition, change_notes=None)
client.deploy_strategy(strategy_id, version)
client.undeploy_strategy(strategy_id)
```

### Testing Methods

```python
client.run_test(strategy_id, version, episodes=10, date_range=None, episode_duration_days=30)
client.get_test_status(strategy_id, test_id)
client.get_test_results(strategy_id, test_id)
client.compare_versions(strategy_id, v1, v2)
```

### Training Methods

```python
client.get_training_runs(status=None, limit=20, offset=0)
client.get_training_run(run_id)
client.compare_training_runs(run_ids)
```

---

## REST API Reference

### Strategy Endpoints (`/api/v1/strategies`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/` | Create strategy |
| `GET` | `/` | List strategies (`?status&limit&offset`) |
| `GET` | `/{id}` | Get detail (definition + latest test results) |
| `PUT` | `/{id}` | Update metadata (name, description) |
| `DELETE` | `/{id}` | Archive (soft delete) |
| `POST` | `/{id}/versions` | Create new version |
| `GET` | `/{id}/versions` | List all versions |
| `GET` | `/{id}/versions/{ver}` | Get specific version |
| `POST` | `/{id}/deploy` | Deploy version (`{"version": N}`) |
| `POST` | `/{id}/undeploy` | Undeploy |

### Strategy Test Endpoints (`/api/v1/strategies`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/{id}/test` | Start test run |
| `GET` | `/{id}/tests` | List test runs |
| `GET` | `/{id}/tests/{test_id}` | Get test status/results |
| `POST` | `/{id}/tests/{test_id}/cancel` | Cancel running test |
| `GET` | `/{id}/test-results` | Latest completed results |
| `GET` | `/{id}/compare-versions?v1=N&v2=M` | Compare versions |

### Training Endpoints (`/api/v1/training`)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/runs` | Register training run (called by Gym) |
| `POST` | `/runs/{run_id}/episodes` | Report episode (called by Gym) |
| `POST` | `/runs/{run_id}/complete` | Complete run (called by Gym) |
| `GET` | `/runs` | List runs (`?status&limit&offset`) |
| `GET` | `/runs/{run_id}` | Full detail + learning curve + episodes |
| `GET` | `/runs/{run_id}/learning-curve` | Learning curve (`?metric&window`) |
| `GET` | `/compare?run_ids=a,b,c` | Compare multiple runs |

**Auth:** All endpoints require `X-API-Key` or `Authorization: Bearer {jwt}` header.

---

## Indicators Reference

All indicators are computed with pure numpy (no TA-Lib dependency):

| Indicator | Output Keys | Default Period | Min Data |
|-----------|-------------|----------------|----------|
| RSI | `rsi_14` | 14 | 15 candles |
| MACD | `macd_line`, `macd_signal`, `macd_hist` | 12/26/9 | 26 candles |
| SMA | `sma_20`, `sma_50` | 20, 50 | Period candles |
| EMA | `ema_12`, `ema_26` | 12, 26 | Period candles |
| Bollinger Bands | `bb_upper`, `bb_middle`, `bb_lower` | 20 (2 std) | 20 candles |
| ADX | `adx` | 14 | 15 candles |
| ATR | `atr` | 14 | 15 candles |
| Volume MA | `volume_ma_20` | 20 | 20 candles |

Additional computed values: `current_price`, `current_volume`

---

## Examples

### 1. Random Agent (sanity check)

```python
import gymnasium as gym
import tradeready_gym

env = gym.make("TradeReady-BTC-v0", api_key="ak_live_...")
obs, info = env.reset()

total_reward = 0
for step in range(100):
    action = env.action_space.sample()
    obs, reward, terminated, truncated, info = env.step(action)
    total_reward += reward
    if terminated or truncated:
        break

print(f"Total reward: {total_reward:.4f}")
print(f"Final equity: {info['equity']}")
env.close()
```

### 2. PPO Training with Stable-Baselines3

```python
import gymnasium as gym
import tradeready_gym
from tradeready_gym.rewards import SharpeReward
from tradeready_gym.wrappers import NormalizationWrapper
from stable_baselines3 import PPO

env = gym.make("TradeReady-BTC-Continuous-v0",
    api_key="ak_live_...",
    reward_function=SharpeReward(window=50),
    lookback_window=50,
    track_training=True,
)
env = NormalizationWrapper(env)

model = PPO("MlpPolicy", env, verbose=1)
model.learn(total_timesteps=50_000)
model.save("ppo_btc")
env.close()
```

### 3. Portfolio Allocation

```python
env = gym.make("TradeReady-Portfolio-v0",
    api_key="ak_live_...",
    pairs=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    starting_balance=50000,
)

obs, info = env.reset()
# Allocate: 50% BTC, 30% ETH, 20% SOL
obs, reward, done, _, info = env.step([0.5, 0.3, 0.2])
```

### 4. Custom Reward Function

```python
from tradeready_gym.rewards import CustomReward

class RiskAdjustedReward(CustomReward):
    def __init__(self, risk_penalty=0.5):
        self.risk_penalty = risk_penalty
        self._peak = 0.0

    def compute(self, prev_equity, curr_equity, info):
        pnl = curr_equity - prev_equity
        self._peak = max(self._peak, curr_equity)
        drawdown = (self._peak - curr_equity) / self._peak if self._peak > 0 else 0
        return pnl - self.risk_penalty * drawdown * curr_equity

    def reset(self):
        self._peak = 0.0

env = gym.make("TradeReady-BTC-v0",
    api_key="ak_live_...",
    reward_function=RiskAdjustedReward(risk_penalty=0.5),
)
```

### 5. Strategy Iteration Workflow

```python
from agentexchange import AgentExchangeClient

client = AgentExchangeClient(api_key="ak_live_...")

# Create → Test → Read → Improve → Compare → Deploy
strategy = client.create_strategy("My Strategy", definition={...})
sid = strategy["strategy_id"]

# Test v1
t1 = client.run_test(sid, 1, episodes=20, date_range={"start":"2025-01-01","end":"2025-06-01"})
r1 = client.get_test_results(sid, t1["test_run_id"])

# Improve based on recommendations
v2 = client.create_version(sid, definition={...improved...}, change_notes="Applied recs")

# Test v2
t2 = client.run_test(sid, 2, episodes=20, date_range={"start":"2025-01-01","end":"2025-06-01"})

# Compare
comp = client.compare_versions(sid, v1=1, v2=2)
print(comp["verdict"])

# Deploy winner
best_version = 2 if comp["improvements"].get("avg_roi_pct", 0) > 0 else 1
client.deploy_strategy(sid, version=best_version)
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Frontend (Next.js)                        │
│  /strategies  /training  /backtest  /dashboard                   │
└──────────────┬───────────────────────────────────┬───────────────┘
               │ REST API                          │ WebSocket
┌──────────────▼───────────────────────────────────▼───────────────┐
│                     Backend (FastAPI)                             │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐    │
│  │  Strategy    │  │  Strategy    │  │  Training             │    │
│  │  Registry    │  │  Executor    │  │  Observation           │    │
│  │  (CRUD,      │  │  (Indicators,│  │  (Runs, Episodes,     │    │
│  │   versions,  │  │   conditions,│  │   Learning Curves,    │    │
│  │   deploy)    │  │   orders)    │  │   Comparison)         │    │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬────────────┘    │
│         │                │                      │                 │
│  ┌──────▼──────┐  ┌──────▼──────┐  ┌──────────▼────────────┐    │
│  │  Test       │  │  Celery     │  │  Training              │    │
│  │  Orchestr.  ├──►  Workers    │  │  Repository            │    │
│  │  (Episodes, │  │  (Episodes, │  │  (Postgres)            │    │
│  │   Aggregate)│  │   Backtest) │  └─────────────────────────┘    │
│  └─────────────┘  └─────────────┘                                │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │  Backtest Engine (Historical replay, sandbox trading)      │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ MCP (15  │  │ SDK      │  │ Redis    │  │ Postgres │        │
│  │ tools)   │  │ (13 API) │  │ (cache)  │  │ (Timescale)│      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘        │
└──────────────────────────────────────────────────────────────────┘
               ▲
               │ HTTP (backtest API)
┌──────────────┴───────────────────────────────────────────────────┐
│                   tradeready-gym Package                         │
│                                                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │ Single      │  │ Multi       │  │ Live                    │  │
│  │ Asset Env   │  │ Asset Env   │  │ Trading Env             │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────────┘  │
│         │                │                      │                 │
│  ┌──────▼────────────────▼──────────────────────▼──────────────┐ │
│  │ BaseTradingEnv (Gymnasium API, observation builder, rewards)│ │
│  └──────┬──────────────────────────────────────────────────────┘ │
│         │                                                        │
│  ┌──────▼──────────────────────────────────────────────────────┐ │
│  │ TrainingTracker (auto-reports episodes to training API)     │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  Wrappers: FeatureEngineering | Normalization | BatchStep        │
│  Rewards:  PnL | LogReturn | Sharpe | Sortino | DrawdownPenalty │
└──────────────────────────────────────────────────────────────────┘
```

---

*Last updated: 2026-03-18*
