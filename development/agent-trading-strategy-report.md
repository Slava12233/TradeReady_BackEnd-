---
type: research-report
title: "Building a 5%-Daily AI Trading Agent: Complete Strategy Report"
status: archived
phase: agent-strategies
tags:
  - research
  - agent-strategies
---

# Building a 5%-Daily AI Trading Agent: Complete Strategy Report
## How to Use Every Platform Tool to Maximize Agent Performance

---

## Table of Contents

1. [Reality Check: The Math of 5% Daily](#1-reality-check)
2. [Adjusted Target: What's Actually Achievable](#2-adjusted-target)
3. [The Master Plan: 7-Phase Pipeline](#3-the-master-plan)
4. [Phase 1: Agent Creation & Configuration](#4-phase-1)
5. [Phase 2: Strategy Discovery (Run 1000+ Backtests)](#5-phase-2)
6. [Phase 3: RL Training Pipeline](#6-phase-3)
7. [Phase 4: Ensemble & Regime Detection](#7-phase-4)
8. [Phase 5: Validation & Walk-Forward Testing](#8-phase-5)
9. [Phase 6: Live Paper Trading](#9-phase-6)
10. [Phase 7: Battle Tournament & Selection](#10-phase-7)
11. [How Each Platform Tool Is Used](#11-tool-usage-map)
12. [What We Need to Build/Connect](#12-what-to-build)
13. [The Complete Agent Architecture](#13-agent-architecture)
14. [Risk Management Strategy](#14-risk-management)
15. [Concrete Implementation Plan](#15-implementation-plan)
16. [Appendix: Math, Formulas & References](#16-appendix)

---

## 1. Reality Check: The Math of 5% Daily

Before building anything, let's understand what 5% daily means:

### Compound Growth

| Duration | 5% Daily Compound | $10,000 Becomes |
|----------|-------------------|-----------------|
| 1 week | +27.6% | $12,763 |
| 1 month | +191% | $29,253 |
| 3 months | +24,540% | $2,464,000 |
| 6 months | +6,000,000% | $602,000,000 |
| 1 year | +26,800,000,000% | $2.68 TRILLION |

**This is mathematically impossible to sustain.** If it were possible, a single trader would own more wealth than exists on Earth.

### What the Best in the World Actually Achieve

| Who | Annual Return | Daily Equivalent |
|-----|-------------|-----------------|
| Renaissance Medallion (best hedge fund ever) | 60-80% | 0.18-0.24% |
| Jane Street (top HFT firm) | 30-100%+ | 0.1-0.3% |
| FinRL Ensemble (best published RL agent) | 52.6% | 0.17% |
| Top crypto bots (documented) | 25-40% | 0.08-0.13% |

### BUT — On a Virtual Platform...

On our virtual platform, we have advantages real traders don't:
- **No real market impact** (our orders don't move prices)
- **600+ pairs** to spread across simultaneously
- **No withdrawal/deposit friction**
- **Can run extremely aggressive risk profiles**
- **Can train on millions of episodes**

**Realistic aggressive target for our virtual platform: 1-3% daily average.** Some days will be 5%+, others will be -2%. The monthly average is what matters.

---

## 2. Adjusted Target: What's Actually Achievable

### The Target Framework

| Metric | Conservative | Aggressive | Maximum Risk |
|--------|-------------|-----------|--------------|
| Daily average return | 0.3-0.5% | 1-2% | 2-5% |
| Annual compound | 110-280% | 3,600-100,000%+ | Astronomical |
| Max daily drawdown | -3% | -8% | -15% |
| Win rate needed | 55-60% | 60-70% | 65-75% |
| Trades per day | 10-30 | 30-100 | 100-500 |
| Risk per trade | 1-2% equity | 2-5% equity | 5-10% equity |
| Sharpe ratio target | >1.5 | >2.0 | >2.5 |

### The Math: What It Takes for 3% Daily

```
Target: 3% daily = $300 on $10,000

Strategy: Multi-pair scalping
  - 50 trades/day across 10 pairs
  - Win rate: 65%
  - Average win: 0.4% of equity = $40
  - Average loss: 0.25% of equity = $25
  - Position size: 10% of equity per trade

Expected daily:
  Wins:  50 × 0.65 × $40  = $1,300 gross wins
  Losses: 50 × 0.35 × $25 = $437.50 gross losses
  Fees: 50 × 0.1% × $1,000 = $50 (0.1% per trade on $1,000 position)

  Net: $1,300 - $437.50 - $50 = $812.50 = 8.1% daily

Wait — that seems too good. The catch: trades are NOT independent.
In reality, correlated losses happen in clusters (market dumps).
Apply a 0.5 correlation discount: $812.50 × 0.5 = $406 = 4.06% daily.
Apply a realism discount (slippage, missed fills): × 0.75 = $304 = 3.04% daily.
```

**This is achievable on a virtual platform with the right agent.** The key is:
1. High win rate (65%+) — achieved through massive strategy optimization
2. Good risk/reward (1.6:1) — achieved through smart exit conditions
3. High trade volume (50+/day) — achieved through multi-pair trading
4. Controlled losses — achieved through strict risk management

---

## 3. The Master Plan: 7-Phase Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                    THE 7-PHASE PIPELINE                         │
│                                                                 │
│  Phase 1: CREATE AGENT ARMY                                     │
│    → Create 10 agents with different risk profiles              │
│    → Each agent gets $10,000 virtual USDT                       │
│                                                                 │
│  Phase 2: STRATEGY DISCOVERY (1000+ backtests)                  │
│    → Create 50+ rule-based strategies                           │
│    → Test each with 20 episodes across different date ranges    │
│    → Find the top 5-10 strategies by Sharpe ratio               │
│    → Use recommendations to iterate                             │
│                                                                 │
│  Phase 3: RL TRAINING                                           │
│    → Train PPO agent on top strategy's pairs                    │
│    → Train SAC agent as alternative                             │
│    → Train multi-asset portfolio agent                          │
│    → 500+ episodes each, monitor learning curves                │
│                                                                 │
│  Phase 4: ENSEMBLE & REGIME DETECTION                           │
│    → Build regime detector (bull/bear/sideways)                 │
│    → Weight strategies by regime                                │
│    → Combine rule-based + RL outputs                            │
│                                                                 │
│  Phase 5: WALK-FORWARD VALIDATION                               │
│    → Test on unseen date ranges                                 │
│    → Run 100+ validation backtests                              │
│    → Compute deflated Sharpe ratio                              │
│    → Only promote strategies that pass ALL windows              │
│                                                                 │
│  Phase 6: LIVE PAPER TRADING                                    │
│    → Deploy best agents to live trading                         │
│    → Monitor performance vs backtest expectations               │
│    → Retrain if performance degrades                            │
│                                                                 │
│  Phase 7: BATTLE TOURNAMENT                                     │
│    → Pit all agent variants against each other                  │
│    → Rank by Sharpe, ROI, drawdown                              │
│    → Winner becomes the production agent                        │
│    → Repeat tournament monthly                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Phase 1: Agent Creation & Configuration

### Create the Agent Army

Create 10 agents, each specialized for a different approach:

```python
from sdk.agentexchange import AgentExchangeClient

# Agent configs
agents = [
    {"name": "Scout-BTC-Scalper",     "balance": 10000, "risk": "aggressive-scalp"},
    {"name": "Scout-Multi-Momentum",  "balance": 10000, "risk": "aggressive-multi"},
    {"name": "Scout-Mean-Revert",     "balance": 10000, "risk": "aggressive-revert"},
    {"name": "Scout-Breakout",        "balance": 10000, "risk": "moderate-breakout"},
    {"name": "PPO-BTC-v1",            "balance": 10000, "risk": "rl-aggressive"},
    {"name": "PPO-Multi-v1",          "balance": 10000, "risk": "rl-aggressive"},
    {"name": "SAC-BTC-v1",            "balance": 10000, "risk": "rl-aggressive"},
    {"name": "Ensemble-Alpha",        "balance": 10000, "risk": "ensemble"},
    {"name": "Ensemble-Beta",         "balance": 10000, "risk": "ensemble"},
    {"name": "Champion",              "balance": 10000, "risk": "champion"},
]
```

### Risk Profiles for Aggressive Trading

```python
# Aggressive scalping profile
aggressive_scalp_profile = {
    "max_position_size_pct": 50,     # Up to 50% equity in one position
    "max_order_size_pct": 30,        # Up to 30% equity per order
    "daily_loss_limit_pct": 15,      # Stop trading after 15% daily loss
    "max_open_orders": 200,          # Allow many concurrent orders
    "order_rate_limit": 500          # High rate limit for scalping
}

# RL agent profile
rl_aggressive_profile = {
    "max_position_size_pct": 40,
    "max_order_size_pct": 25,
    "daily_loss_limit_pct": 20,
    "max_open_orders": 100,
    "order_rate_limit": 300
}
```

### Platform Tools Used

| Tool | How Used |
|------|---------|
| `POST /api/v1/agents` | Create each agent |
| `PUT /api/v1/agents/{id}/risk-profile` | Set aggressive risk limits |
| `GET /api/v1/agents/{id}/skill.md` | Generate system prompt for LLM agents |

---

## 5. Phase 2: Strategy Discovery (Run 1000+ Backtests)

This is the **most critical phase**. We systematically search through strategy space to find what works.

### Step 1: Generate Strategy Candidates (50+ strategies)

Create strategies covering different approaches:

```
Category 1: RSI Mean Reversion (10 variants)
  - RSI period: 7, 14, 21
  - Entry threshold: 25, 30, 35
  - Exit: stop-loss 2-5%, take-profit 3-8%
  - Pairs: BTC, ETH, SOL, top 10 by volume

Category 2: MACD Momentum (10 variants)
  - MACD cross with ADX filter
  - ADX threshold: 15, 20, 25, 30
  - Position size: 5%, 10%, 15%, 20%
  - Timeframe: 1m, 5m, 1h

Category 3: Bollinger Band Breakout (10 variants)
  - BB squeeze + volume surge
  - Volume threshold: 1.5x, 2x, 3x MA
  - Stop-loss: 1%, 2%, 3%
  - Take-profit: 2%, 4%, 6%

Category 4: Multi-Indicator Combo (10 variants)
  - RSI + MACD + BB (all must agree)
  - Different strength combinations
  - Tight vs wide conditions

Category 5: Aggressive Scalp (10 variants)
  - Very tight stops (0.5-1%)
  - Quick take-profits (0.5-2%)
  - High frequency, many pairs
  - ATR-based dynamic sizing
```

### Step 2: Create Each Strategy via API

```python
# Example: RSI Mean Reversion strategy
strategy_definition = {
    "pairs": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
    "timeframe": "5m",
    "entry_conditions": {
        "rsi_below": 30,
        "adx_above": 20,           # Only enter in trending markets
        "volume_above_ma": 1.5     # Volume confirmation
    },
    "exit_conditions": {
        "stop_loss_pct": 2.0,
        "take_profit_pct": 4.0,    # 2:1 risk/reward
        "trailing_stop_pct": 1.5,
        "max_hold_candles": 60,    # 5 hours max at 5m candles
        "rsi_above": 70            # Exit on overbought
    },
    "position_size_pct": 15,
    "max_positions": 5,
    "model_type": "rule_based"
}
```

### Step 3: Run Mass Testing (1000+ backtests)

For each of the 50 strategies, run 20 episodes:

```python
# Test each strategy with 20 episodes
test_config = {
    "version": 1,
    "episodes": 20,
    "date_range": {
        "start": "2024-01-01",
        "end": "2024-12-31"
    },
    "episode_duration_days": 30,  # Each episode = 1 month
    "starting_balance": 10000
}

# 50 strategies × 20 episodes = 1,000 backtests
# This runs via Celery workers in parallel
```

### Step 4: Analyze Results & Iterate

After all 1000 tests complete:

```python
# Rank strategies by Sharpe ratio
# GET /api/v1/strategies/{id}/test-results for each

# Top strategies might look like:
# 1. RSI-30-ADX-20-Multi-5m  → Sharpe 2.1, ROI +12.4%, Drawdown -8%
# 2. BB-Squeeze-Volume-3x    → Sharpe 1.9, ROI +9.8%, Drawdown -6%
# 3. MACD-Cross-ADX-25-1m    → Sharpe 1.7, ROI +15.2%, Drawdown -12%
```

### Step 5: Use Recommendations to Create v2 Strategies

The platform's 11-rule recommendation engine suggests improvements:

```
Strategy: RSI-30-ADX-20-Multi-5m (v1)
Recommendations:
  - "Win rate is 72% — consider relaxing entry conditions"
  - "Avg drawdown is 4.2% — stop-losses may be too tight"
  - "ETHUSDT underperforms by 6% — consider removing"

→ Create v2:
  - Relax RSI from 30 to 35
  - Widen stop-loss from 2% to 3%
  - Remove ETHUSDT, add DOGEUSDT

→ Test v2 with 20 more episodes
→ Compare v1 vs v2: GET /strategies/{id}/compare-versions?v1=1&v2=2
```

### Step 6: Second Round — 500 More Backtests

Take the top 10 strategies (v2), test with:
- Different date ranges (bull market, bear market, sideways)
- Different starting balances ($5k, $10k, $50k)
- Different position sizes (5%, 10%, 15%, 20%)

**Total: 10 strategies × 50 episodes × various configs = 500+ more backtests**

### Why 1000+ Backtests Matter

| Without Mass Testing | With 1000+ Backtests |
|---------------------|---------------------|
| Pick strategy based on gut feeling | Data-driven strategy selection |
| Overfit to one time period | Validated across multiple regimes |
| Single point of failure | Statistical significance (p < 0.05) |
| Don't know what works | Clear ranking of what works |
| No way to improve | Recommendation engine guides iteration |

### Platform Tools Used

| Tool | How Used | Volume |
|------|---------|--------|
| `POST /api/v1/strategies` | Create 50+ strategy definitions | 50 calls |
| `POST /api/v1/strategies/{id}/versions` | Create v2, v3 iterations | 50+ calls |
| `POST /api/v1/strategies/{id}/test` | Launch multi-episode tests | 100+ test runs |
| Celery workers | Execute parallel backtest episodes | 1500+ episodes |
| `GET /api/v1/strategies/{id}/test-results` | Read aggregated metrics | 100+ reads |
| `GET /api/v1/strategies/{id}/compare-versions` | Compare v1 vs v2 | 30+ comparisons |
| Recommendation Engine | Get improvement suggestions | Automatic per test |
| `POST /api/v1/strategies/{id}/deploy` | Deploy top strategies | 5-10 deploys |

---

## 6. Phase 3: RL Training Pipeline

### Why RL on Top of Rule-Based Strategies?

Rule-based strategies have fixed rules. RL agents can:
1. **Learn when to apply which rules** (dynamic decision-making)
2. **Optimize position sizing** continuously based on market state
3. **Discover patterns** humans can't express as rules
4. **Adapt** their behavior over many episodes

### Training Setup: PPO Agent

```python
import gymnasium as gym
import tradeready_gym
from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env

# Custom environment with aggressive settings
def make_env():
    env = gym.make("TradeReady-BTC-Continuous-v0",
        api_key="ak_live_PPO_AGENT_KEY",
        base_url="http://localhost:8000",
        start_time="2024-01-01T00:00:00Z",
        end_time="2024-07-01T00:00:00Z",
        starting_balance=10000,
        candle_interval=300,          # 5-minute candles
        pairs=["BTCUSDT"],
        lookback_window=60,           # Look back 60 candles (5 hours)
        observation_features=[
            "ohlcv", "rsi_14", "macd", "bollinger", "atr",
            "balance", "position", "unrealized_pnl"
        ],
        reward_function="sharpe",     # Risk-adjusted reward
        position_size_pct=15,
        strategy_label="ppo_btc_aggressive_v1",
        track_training=True           # Report to /training endpoints
    )
    # Add normalization for stable training
    env = tradeready_gym.NormalizationWrapper(env, clip=1.0)
    return env

# Vectorized training (4 parallel environments)
vec_env = make_vec_env(make_env, n_envs=4)

# PPO with tuned hyperparameters for trading
model = PPO(
    "MlpPolicy",
    vec_env,
    learning_rate=3e-4,
    n_steps=2048,
    batch_size=64,
    n_epochs=10,
    gamma=0.99,              # Discount factor
    gae_lambda=0.95,         # GAE lambda
    clip_range=0.2,          # PPO clipping
    ent_coef=0.01,           # Exploration bonus
    vf_coef=0.5,
    max_grad_norm=0.5,
    verbose=1
)

# Train for 500,000 timesteps (across 4 envs = ~125K steps each)
# Each episode ≈ 52,560 steps (6 months of 5m candles)
# So ~500,000/52,560 ≈ 38 episodes total
model.learn(total_timesteps=500_000)
model.save("models/ppo_btc_aggressive_v1")
vec_env.close()
```

### Training Setup: SAC Agent (For Comparison)

```python
from stable_baselines3 import SAC

# SAC is off-policy (more sample-efficient, reuses experience)
model_sac = SAC(
    "MlpPolicy",
    make_env(),
    learning_rate=3e-4,
    buffer_size=100_000,        # Replay buffer
    learning_starts=1000,
    batch_size=256,
    tau=0.005,
    gamma=0.99,
    train_freq=1,
    gradient_steps=1,
    verbose=1
)

model_sac.learn(total_timesteps=200_000)  # SAC needs fewer steps
model_sac.save("models/sac_btc_aggressive_v1")
```

### Training Setup: Multi-Asset Portfolio Agent

```python
# Portfolio agent allocates across multiple assets
env = gym.make("TradeReady-Portfolio-v0",
    api_key="ak_live_PORTFOLIO_KEY",
    start_time="2024-01-01T00:00:00Z",
    end_time="2024-07-01T00:00:00Z",
    pairs=["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"],
    observation_features=["ohlcv", "rsi_14", "macd", "balance", "position"],
    reward_function="sortino",  # Penalize downside only
    track_training=True
)

model_portfolio = PPO("MlpPolicy", env, verbose=1)
model_portfolio.learn(total_timesteps=300_000)
model_portfolio.save("models/ppo_portfolio_v1")
```

### Custom Reward Function for Aggressive Returns

```python
from tradeready_gym.rewards import CustomReward

class AggressiveReturnReward(CustomReward):
    """
    Reward that:
    1. Rewards positive equity changes MORE than it penalizes negative ones
    2. Gives a bonus for maintaining high Sharpe ratio
    3. Penalizes drawdowns exponentially
    4. Discourages inactivity (not trading)
    """

    def __init__(self, drawdown_penalty=2.0, inactivity_penalty=0.01):
        self._peak_equity = 0.0
        self._returns_window = []
        self._steps_since_trade = 0
        self._drawdown_penalty = drawdown_penalty
        self._inactivity_penalty = inactivity_penalty

    def reset(self):
        self._peak_equity = 0.0
        self._returns_window = []
        self._steps_since_trade = 0

    def compute(self, prev_equity, curr_equity, info):
        # 1. Asymmetric PnL reward (wins count 1.5x more than losses)
        pnl = curr_equity - prev_equity
        if pnl > 0:
            reward = pnl * 1.5
        else:
            reward = pnl * 1.0

        # 2. Drawdown penalty (exponential)
        self._peak_equity = max(self._peak_equity, curr_equity)
        drawdown = (self._peak_equity - curr_equity) / self._peak_equity
        if drawdown > 0.05:  # Penalize drawdowns > 5%
            reward -= self._drawdown_penalty * (drawdown ** 2) * curr_equity

        # 3. Rolling Sharpe bonus
        ret = (curr_equity - prev_equity) / prev_equity if prev_equity > 0 else 0
        self._returns_window.append(ret)
        if len(self._returns_window) > 50:
            self._returns_window.pop(0)
        if len(self._returns_window) >= 10:
            import numpy as np
            mean_ret = np.mean(self._returns_window)
            std_ret = np.std(self._returns_window)
            if std_ret > 0:
                sharpe = mean_ret / std_ret
                reward += sharpe * 10  # Scale Sharpe bonus

        # 4. Inactivity penalty
        filled = info.get("filled_orders", [])
        if filled:
            self._steps_since_trade = 0
        else:
            self._steps_since_trade += 1
            if self._steps_since_trade > 20:
                reward -= self._inactivity_penalty

        return float(reward)
```

### Monitor Training in Real-Time

While training runs, the platform tracks everything:

```
Frontend /training page shows:
┌──────────────────────────────────────────────────────┐
│  PPO-BTC-Aggressive-v1                               │
│  Episodes: 23/38  │  Running for 2h 15m              │
│                                                       │
│  Learning Curve (ROI):                                │
│    Episode 1:  -8.2%   (random exploration)           │
│    Episode 5:  -2.1%   (learning to not lose)         │
│    Episode 10: +3.4%   (finding patterns)             │
│    Episode 15: +7.8%   (getting consistent)           │
│    Episode 20: +11.2%  (optimizing)                   │
│    Episode 23: +9.5%   (stabilizing)                  │
│                                                       │
│  Avg Sharpe: 1.8  │  Best Episode ROI: +18.4%        │
└──────────────────────────────────────────────────────┘
```

### Training Runs to Execute

| Agent Name | Algorithm | Pairs | Episodes | Estimated Time |
|-----------|----------|-------|----------|---------------|
| PPO-BTC-v1 | PPO | BTCUSDT | 50+ | 4-8 hours |
| PPO-Multi-v1 | PPO | Top 5 pairs | 50+ | 6-12 hours |
| SAC-BTC-v1 | SAC | BTCUSDT | 30+ | 3-6 hours |
| PPO-Portfolio-v1 | PPO | Top 5 pairs | 40+ | 8-16 hours |
| DQN-Scalp-v1 | DQN | BTCUSDT | 50+ | 3-6 hours |

### Platform Tools Used

| Tool | How Used |
|------|---------|
| `tradeready-gym` environments | Reset/step loop for each episode |
| `POST /api/v1/backtest/create` | One session per episode (auto by gym) |
| `POST /api/v1/backtest/{id}/step` | Advance simulation (43K+ calls/episode for 1m candles) |
| `POST /api/v1/training/runs` | Register training run (auto by TrainingTracker) |
| `POST /api/v1/training/runs/{id}/episodes` | Report episode metrics |
| `GET /api/v1/training/runs/{id}/learning-curve` | Monitor learning progress |
| `GET /api/v1/training/compare` | Compare PPO vs SAC vs DQN |
| NormalizationWrapper | Z-score normalize observations |
| BatchStepWrapper | Reduce decision frequency for faster training |
| Custom reward function | Aggressive return + drawdown penalty |

---

## 7. Phase 4: Ensemble & Regime Detection

### The Ensemble Architecture

Don't rely on a single agent. Combine the best from each approach:

```
Market State
    │
    ├─ Regime Detector (HMM or rule-based)
    │   → "bull" / "bear" / "sideways" / "volatile"
    │
    ├─ Rule-Based Strategy Signals
    │   → RSI-Mean-Revert: "buy BTCUSDT, confidence 0.7"
    │   → MACD-Momentum: "hold, confidence 0.5"
    │   → BB-Breakout: "buy ETHUSDT, confidence 0.8"
    │
    ├─ RL Agent Signals
    │   → PPO: action=0.6 (buy 60% of max position)
    │   → SAC: action=0.4 (buy 40% of max position)
    │
    └─ Ensemble Combiner
        → Weighted by regime:
          Bull:  PPO(0.4) + Momentum(0.3) + Breakout(0.2) + MeanRevert(0.1)
          Bear:  SAC(0.3) + MeanRevert(0.4) + PPO(0.2) + Hold(0.1)
          Side:  MeanRevert(0.5) + SAC(0.3) + PPO(0.1) + Hold(0.1)
          Volat: Hold(0.4) + MeanRevert(0.3) + SAC(0.2) + PPO(0.1)

        → Final decision: BUY BTCUSDT, size = 12% of equity
```

### Regime Detection (Build This)

```python
class RegimeDetector:
    """
    Detect market regime using multiple signals.
    This is what we need to BUILD — not yet in the platform.
    """

    def detect(self, candles_1h, candles_1d):
        # Signal 1: Trend direction (SMA crossover)
        sma_20 = mean(candles_1d[-20:].close)
        sma_50 = mean(candles_1d[-50:].close)
        trend = "bull" if sma_20 > sma_50 else "bear"

        # Signal 2: Volatility (ATR ratio)
        atr_short = atr(candles_1h[-24:])   # 24h ATR
        atr_long = atr(candles_1d[-30:])     # 30d ATR
        vol_ratio = atr_short / atr_long
        volatile = vol_ratio > 1.5

        # Signal 3: ADX trend strength
        adx_value = adx(candles_1h[-48:])
        trending = adx_value > 25

        # Combine
        if volatile:
            return "volatile"
        elif trending and trend == "bull":
            return "bull"
        elif trending and trend == "bear":
            return "bear"
        else:
            return "sideways"
```

### How to Implement the Ensemble with Our Platform

```python
# The Master Agent — runs continuously
class EnsembleAgent:
    def __init__(self, api_key):
        self.client = AgentExchangeClient(api_key=api_key, base_url="...")
        self.ws = AgentExchangeWS(api_key=api_key)

        # Load trained models
        self.ppo = PPO.load("models/ppo_btc_aggressive_v1")
        self.sac = SAC.load("models/sac_btc_aggressive_v1")

        # Load deployed strategy definitions
        strategies = self.client.get_strategies(status="deployed")
        self.rule_strategies = [s.definition for s in strategies]

        # Regime detector
        self.regime = RegimeDetector()

    async def run(self):
        """Main trading loop."""
        @self.ws.on_candles("BTCUSDT", "5m")
        async def on_new_candle(data):
            # 1. Detect regime
            candles = self.client.get_candles("BTCUSDT", "1h", limit=48)
            regime = self.regime.detect(candles)

            # 2. Get signals from all sources
            obs = self.build_observation()
            ppo_action = self.ppo.predict(obs)[0]
            sac_action = self.sac.predict(obs)[0]
            rule_signals = [s.evaluate(candles) for s in self.rule_strategies]

            # 3. Combine with regime weights
            final_action = self.combine(regime, ppo_action, sac_action, rule_signals)

            # 4. Execute
            if final_action["action"] == "buy":
                self.client.place_market_order(
                    symbol=final_action["symbol"],
                    side="buy",
                    quantity=final_action["quantity"]
                )
            elif final_action["action"] == "sell":
                self.client.place_market_order(
                    symbol=final_action["symbol"],
                    side="sell",
                    quantity=final_action["quantity"]
                )

        await self.ws.connect()
```

---

## 8. Phase 5: Validation & Walk-Forward Testing

### Walk-Forward Optimization

The **only** way to know if a strategy is real or overfit:

```
Train Period          Test Period       Result
─────────────────     ────────────     ────────
Jan 2024 - Jun 2024   Jul 2024        +8.2% ✓
Feb 2024 - Jul 2024   Aug 2024        +5.1% ✓
Mar 2024 - Aug 2024   Sep 2024        -2.3% ✗
Apr 2024 - Sep 2024   Oct 2024        +6.7% ✓
May 2024 - Oct 2024   Nov 2024        +4.9% ✓
Jun 2024 - Nov 2024   Dec 2024        +3.2% ✓

Pass rate: 5/6 = 83% → VALID (need >60% to proceed)
```

### How to Run Walk-Forward with Our Platform

```python
# Walk-forward validation: 100+ backtests on unseen data
windows = [
    ("2024-01-01", "2024-06-30", "2024-07-01", "2024-07-31"),
    ("2024-02-01", "2024-07-31", "2024-08-01", "2024-08-31"),
    ("2024-03-01", "2024-08-31", "2024-09-01", "2024-09-30"),
    # ... 12 rolling windows
]

for train_start, train_end, test_start, test_end in windows:
    # Train RL agent on train period
    env = gym.make("TradeReady-BTC-Continuous-v0",
        api_key="...",
        start_time=train_start,
        end_time=train_end,
        track_training=False
    )
    model = PPO("MlpPolicy", env)
    model.learn(total_timesteps=100_000)

    # Test on unseen period (separate backtest)
    test_env = gym.make("TradeReady-BTC-Continuous-v0",
        api_key="...",
        start_time=test_start,
        end_time=test_end,
        track_training=False
    )
    obs, _ = test_env.reset()
    while True:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, done, _, info = test_env.step(action)
        if done: break

    # Get results: GET /backtest/{session_id}/results
    # Record: ROI, Sharpe, drawdown for this window
```

### Deflated Sharpe Ratio (Avoid False Positives)

When you test 50+ strategies, the best one will look great by pure chance. The deflated Sharpe ratio corrects for this:

```python
import numpy as np
from scipy.stats import norm

def deflated_sharpe(observed_sharpe, num_trials, avg_sharpe_all_trials, std_sharpe_all_trials):
    """
    Adjusts Sharpe ratio for multiple testing.
    Returns the probability that the observed Sharpe is genuine.
    """
    # Expected maximum Sharpe from N random trials
    expected_max = avg_sharpe_all_trials + std_sharpe_all_trials * (
        (1 - 0.5772) * norm.ppf(1 - 1/num_trials) +
        0.5772 * norm.ppf(1 - 1/(num_trials * np.e))
    )

    # Deflated Sharpe
    dsr = norm.cdf((observed_sharpe - expected_max) / std_sharpe_all_trials)
    return dsr  # Must be > 0.95 to be statistically significant
```

### Platform Tools Used

| Tool | How Used |
|------|---------|
| `POST /api/v1/backtest/create` | Create validation backtests |
| `POST /api/v1/backtest/{id}/step/batch` | Fast-forward through test periods |
| `GET /api/v1/backtest/{id}/results` | Get per-window metrics |
| `GET /api/v1/backtest/compare` | Compare performance across windows |
| `GET /api/v1/backtest/best` | Find best session by metric |

---

## 9. Phase 6: Live Paper Trading

### Deploy the Best Agent

```python
# Use the LiveTradingEnv for RL agents
import gymnasium as gym
import tradeready_gym

env = gym.make("TradeReady-Live-v0",
    api_key="ak_live_CHAMPION_KEY",
    base_url="http://localhost:8000",
    symbol="BTCUSDT",
    step_interval_sec=60  # Check every minute
)

model = PPO.load("models/champion_ppo_v3")
obs, info = env.reset()

while True:
    action, _ = model.predict(obs, deterministic=True)
    obs, reward, done, truncated, info = env.step(action)

    # Log performance
    equity = info.get("equity", 0)
    print(f"Step {info['step']}: equity=${equity:.2f}")
```

### OR: Use SDK for Custom Agent Logic

```python
import asyncio
from sdk.agentexchange import AsyncAgentExchangeClient, AgentExchangeWS

async def run_champion_agent():
    client = AsyncAgentExchangeClient(api_key="ak_live_CHAMPION_KEY")
    ws = AgentExchangeWS(api_key="ak_live_CHAMPION_KEY")

    # Load ensemble components
    ppo_model = PPO.load("models/ppo_btc_v3")
    regime_detector = RegimeDetector()

    @ws.on_candles("BTCUSDT", "5m")
    async def on_candle(data):
        # Get full market state
        portfolio = await client.get_portfolio()
        candles = await client.get_candles("BTCUSDT", "1h", limit=48)
        positions = await client.get_positions()

        # Ensemble decision
        regime = regime_detector.detect(candles)
        obs = build_observation(candles, portfolio)
        action = ppo_model.predict(obs)[0]

        # Apply regime-adjusted action
        if regime == "volatile":
            action *= 0.3  # Reduce position in volatile markets

        # Execute trade
        if action > 0.05:
            quantity = calculate_position_size(portfolio.total_equity, action)
            await client.place_market_order("BTCUSDT", "buy", quantity)
        elif action < -0.05 and has_position("BTCUSDT", positions):
            await client.place_market_order("BTCUSDT", "sell", position_size)

    await ws.connect()

asyncio.run(run_champion_agent())
```

### Monitoring Live Performance

```python
# Periodic check: is the agent performing as expected?
performance = client.get_performance("7d")
backtest_sharpe = 1.8  # From Phase 5 validation

if performance.sharpe_ratio < backtest_sharpe * 0.5:
    print("WARNING: Live Sharpe is <50% of backtest. Consider retraining.")
    # Trigger retraining pipeline
```

### Platform Tools Used

| Tool | How Used |
|------|---------|
| `TradeReady-Live-v0` env | Continuous live RL inference |
| SDK `AsyncAgentExchangeClient` | Custom ensemble agent logic |
| SDK `AgentExchangeWS` | Real-time price streaming |
| `POST /api/v1/trade/order` | Execute live trades |
| `GET /api/v1/account/portfolio` | Monitor portfolio state |
| `GET /api/v1/analytics/performance` | Track live Sharpe, drawdown |

---

## 10. Phase 7: Battle Tournament & Selection

### Monthly Agent Tournament

Pit all agent variants against each other to find the champion:

```python
# Create a historical battle
battle_config = {
    "name": "March 2025 Championship",
    "mode": "historical",
    "start_time": "2025-02-01T00:00:00Z",
    "end_time": "2025-02-28T23:59:59Z",
    "starting_balance": 10000,
    "wallet_mode": "fresh",  # Equal starting conditions
    "participants": [
        agent_ppo_btc_id,
        agent_sac_btc_id,
        agent_ppo_multi_id,
        agent_ensemble_alpha_id,
        agent_ensemble_beta_id,
        agent_rule_rsi_id,
        agent_rule_macd_id
    ]
}

# POST /api/v1/battles (battle runs on the server)
```

### Battle Results

```
┌──────────────────────────────────────────────────────────┐
│              MARCH 2025 CHAMPIONSHIP                      │
├──────────────────────────────────────────────────────────┤
│  Rank │ Agent              │ ROI    │ Sharpe │ Drawdown  │
│  #1   │ Ensemble-Alpha     │ +34.2% │ 2.4    │ -7.3%    │
│  #2   │ PPO-Multi-v3       │ +28.7% │ 2.1    │ -9.1%    │
│  #3   │ SAC-BTC-v2         │ +22.1% │ 1.8    │ -5.4%    │
│  #4   │ Rule-RSI-v2        │ +18.9% │ 1.6    │ -6.2%    │
│  #5   │ PPO-BTC-v3         │ +15.3% │ 1.4    │ -11.2%   │
│  #6   │ Ensemble-Beta      │ +12.8% │ 1.3    │ -8.7%    │
│  #7   │ Rule-MACD-v2       │ +8.4%  │ 0.9    │ -13.5%   │
├──────────────────────────────────────────────────────────┤
│  Winner: Ensemble-Alpha                                   │
│  → Promoted to Champion agent for live trading            │
└──────────────────────────────────────────────────────────┘
```

### Platform Tools Used

| Tool | How Used |
|------|---------|
| `POST /api/v1/battles` | Create tournament |
| `POST /api/v1/battles/{id}/participants` | Add agents |
| `POST /api/v1/battles/{id}/start` | Run battle |
| `GET /api/v1/battles/{id}/results` | Compare all agents |
| `GET /api/v1/battles/{id}/replay` | Analyze equity curves |
| `GET /api/v1/analytics/leaderboard` | Cross-agent rankings |

---

## 11. How Each Platform Tool Is Used (Summary)

```
┌────────────────────────────────────────────────────────────────┐
│                    TOOL USAGE MAP                               │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  AGENTS (10 created)                                           │
│    ├─ Create agents with different roles/risk profiles          │
│    ├─ Configure aggressive risk limits per agent                │
│    ├─ Isolate strategies (each agent = one approach)            │
│    └─ Get skill.md for LLM-driven agents                       │
│                                                                 │
│  STRATEGIES (50+ created, 100+ versions)                       │
│    ├─ Define 50+ rule-based strategies across categories        │
│    ├─ Version immutably (v1, v2, v3...) based on results        │
│    ├─ Test with 20 episodes each (Celery parallel)              │
│    ├─ Read recommendations → iterate → re-test                  │
│    ├─ Compare versions (v1 vs v2) to prove improvement          │
│    └─ Deploy top strategies for ensemble consumption            │
│                                                                 │
│  BACKTESTING (1500+ sessions)                                  │
│    ├─ Strategy testing episodes (1000+ via Celery)              │
│    ├─ Walk-forward validation windows (100+)                    │
│    ├─ RL training episodes (500+ via Gym)                       │
│    ├─ Final validation on unseen data                           │
│    ├─ Compare sessions across time periods                      │
│    └─ Find best session by metric                               │
│                                                                 │
│  GYM API (500+ training episodes)                              │
│    ├─ Train PPO on BTC (50+ episodes)                           │
│    ├─ Train SAC on BTC (30+ episodes)                           │
│    ├─ Train portfolio PPO on 5 pairs (40+ episodes)             │
│    ├─ Custom reward function (aggressive returns + drawdown)    │
│    ├─ Vectorized training (4 envs in parallel)                  │
│    ├─ NormalizationWrapper for stable training                  │
│    └─ LiveTradingEnv for production inference                   │
│                                                                 │
│  TRAINING OBSERVATION                                          │
│    ├─ Monitor learning curves in real-time                      │
│    ├─ Compare PPO vs SAC vs DQN learning speed                  │
│    ├─ Identify when training has converged (plateau)            │
│    └─ Track aggregate stats (avg ROI, best episode)             │
│                                                                 │
│  BATTLES (monthly tournaments)                                 │
│    ├─ Historical battles: fair A/B testing of agent variants    │
│    ├─ Rank all agents by Sharpe, ROI, drawdown                  │
│    ├─ Replay equity curves to understand behavior               │
│    └─ Promote winner to Champion agent                          │
│                                                                 │
│  SDK + WEBSOCKET (live trading)                                │
│    ├─ Real-time price streaming via WebSocket                   │
│    ├─ Fast order execution via SDK                              │
│    ├─ Portfolio monitoring                                      │
│    └─ Performance tracking vs backtest expectations             │
│                                                                 │
│  MCP SERVER (LLM agents)                                       │
│    ├─ 58 tools for Claude/GPT to trade autonomously             │
│    └─ Full platform access via natural language                 │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

---

## 12. What We Need to Build/Connect

### Must-Build (Critical for 3%+ daily)

| Component | Why Critical | Effort |
|-----------|-------------|--------|
| **Regime Detector** | Bull/bear/sideways detection for ensemble weights | Medium |
| **Ensemble Combiner** | Merge rule-based + RL signals | Medium |
| **Walk-Forward Runner** | Automated rolling-window validation | Medium |
| **Gym Batch Step Integration** | Use `/step/batch` instead of per-step HTTP calls (10x faster training) | Small |
| **Model Artifact Storage** | Store trained models (`.zip`, `.pt`) in the platform | Medium |
| **Custom Reward Functions** | Aggressive return + drawdown penalty + Sharpe bonus | Small (library exists) |
| **Automated Retraining Trigger** | Retrain when live Sharpe drops below threshold | Medium |

### Should-Build (Significant Performance Improvement)

| Component | Why Important | Effort |
|-----------|-------------|--------|
| **Order Book Depth Feed** | Top-1 predictive signal for short-term moves | Large |
| **Funding Rate Ingestion** | Contrarian signal at extremes | Medium |
| **Multi-Timeframe Observations** | 1m + 5m + 1h candles in one observation | Medium |
| **Real IndicatorEngine in Gym** | Connect the proper ADX, Stochastic, OBV to gym obs | Medium |
| **Date Range Randomization in TestOrchestrator** | Currently all episodes use same dates | Small |
| **Async LiveTradingEnv** | Current one blocks with `time.sleep` | Medium |
| **Strategy Auto-Executor** | Read deployed strategy and trade automatically | Large |

### Nice-to-Have (For Excellence)

| Component | Why Useful | Effort |
|-----------|----------|--------|
| **Cross-Exchange Spread Feed** | Multi-exchange price comparison signals | Large |
| **Sentiment Data Integration** | Fear/Greed index, social mention velocity | Medium |
| **Population-Based Training (PBT)** | Evolve hyperparameters during training | Large |
| **Curriculum Learning Pipeline** | Train on easy markets first, then hard | Medium |
| **Liquidation Heatmap Data** | Know where leveraged positions will cascade | Large |
| **Sub-1m Candles (15s, 30s)** | More data points for scalping strategies | Medium |

---

## 13. The Complete Agent Architecture

### The Champion Agent (Final Design)

```
┌─────────────────────────────────────────────────────────────┐
│                    CHAMPION AGENT                            │
│                                                              │
│  ┌──────────────────────┐                                    │
│  │   DATA LAYER          │                                    │
│  │                        │                                    │
│  │  WebSocket Feeds:      │                                    │
│  │  ├─ ticker:BTCUSDT     │ ← Real-time per-tick prices      │
│  │  ├─ ticker:ETHUSDT     │                                    │
│  │  ├─ candles:BTCUSDT:5m │ ← 5-minute OHLCV updates         │
│  │  └─ portfolio           │ ← Portfolio state changes        │
│  │                        │                                    │
│  │  REST API:             │                                    │
│  │  ├─ GET /market/candles │ ← Historical lookback window     │
│  │  ├─ GET /account/portfolio │ ← Current equity state        │
│  │  └─ GET /account/positions │ ← Open positions              │
│  └──────────┬─────────────┘                                    │
│             │                                                  │
│  ┌──────────▼─────────────┐                                    │
│  │  ANALYSIS LAYER         │                                    │
│  │                         │                                    │
│  │  Regime Detector:       │                                    │
│  │  ├─ SMA crossover       │ → trend direction                │
│  │  ├─ ATR ratio           │ → volatility level               │
│  │  └─ ADX                 │ → trend strength                 │
│  │  Output: bull/bear/     │                                    │
│  │          sideways/volatile                                   │
│  │                         │                                    │
│  │  Indicator Engine:      │                                    │
│  │  ├─ RSI(14)             │                                    │
│  │  ├─ MACD + signal       │                                    │
│  │  ├─ Bollinger Bands     │                                    │
│  │  ├─ ATR(14)             │                                    │
│  │  └─ Volume MA           │                                    │
│  └──────────┬─────────────┘                                    │
│             │                                                  │
│  ┌──────────▼─────────────┐                                    │
│  │  SIGNAL LAYER           │                                    │
│  │                         │                                    │
│  │  RL Signals:            │                                    │
│  │  ├─ PPO → continuous    │ action: -1.0 to +1.0             │
│  │  ├─ SAC → continuous    │ action: -1.0 to +1.0             │
│  │  └─ Portfolio PPO       │ weights: [0.3, 0.2, 0.5]        │
│  │                         │                                    │
│  │  Rule Signals:          │                                    │
│  │  ├─ RSI-MeanRevert      │ "buy" / "sell" / "hold"         │
│  │  ├─ MACD-Momentum       │ "buy" / "sell" / "hold"         │
│  │  └─ BB-Breakout         │ "buy" / "sell" / "hold"         │
│  └──────────┬─────────────┘                                    │
│             │                                                  │
│  ┌──────────▼─────────────┐                                    │
│  │  ENSEMBLE COMBINER      │                                    │
│  │                         │                                    │
│  │  Regime Weights:        │                                    │
│  │  bull:  PPO 40%, Mom 30%│                                    │
│  │  bear:  SAC 30%, MR 40% │                                    │
│  │  side:  MR 50%, SAC 30% │                                    │
│  │  volat: Hold 40%, MR 30%│                                    │
│  │                         │                                    │
│  │  Confidence Threshold:   │                                    │
│  │  Only trade if combined  │                                    │
│  │  signal confidence > 0.6 │                                    │
│  └──────────┬─────────────┘                                    │
│             │                                                  │
│  ┌──────────▼─────────────┐                                    │
│  │  RISK LAYER             │                                    │
│  │                         │                                    │
│  │  Position Sizing:       │                                    │
│  │  ├─ Half-Kelly formula   │                                    │
│  │  ├─ Max 15% per trade   │                                    │
│  │  └─ Scale by regime     │                                    │
│  │                         │                                    │
│  │  Risk Controls:         │                                    │
│  │  ├─ Circuit breaker 15% │ daily loss limit                 │
│  │  ├─ Trailing stops       │                                    │
│  │  ├─ Max 5 open positions │                                    │
│  │  └─ Cooldown after loss  │ 10min pause after 3 losses      │
│  └──────────┬─────────────┘                                    │
│             │                                                  │
│  ┌──────────▼─────────────┐                                    │
│  │  EXECUTION LAYER        │                                    │
│  │                         │                                    │
│  │  POST /api/v1/trade/order                                    │
│  │  ├─ Market orders       │ for immediate entry/exit          │
│  │  ├─ Stop-loss orders    │ for risk management               │
│  │  └─ Take-profit orders  │ for automatic exits               │
│  └─────────────────────────┘                                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## 14. Risk Management Strategy

### Position Sizing: Half-Kelly Criterion

```python
def half_kelly_size(win_rate, avg_win, avg_loss, equity):
    """
    Calculate position size using Half-Kelly criterion.

    Half-Kelly captures ~75% of optimal growth with ~50% less drawdown.
    """
    b = avg_win / avg_loss  # Win/loss ratio
    p = win_rate
    q = 1 - p

    full_kelly = (p * b - q) / b
    half_kelly = full_kelly / 2

    # Clamp between 1% and 15% of equity
    position_pct = max(0.01, min(0.15, half_kelly))
    return equity * position_pct
```

### Risk Profile for the Champion Agent

```json
{
    "max_position_size_pct": 40,
    "max_order_size_pct": 20,
    "daily_loss_limit_pct": 15,
    "max_open_orders": 100,
    "order_rate_limit": 300
}
```

### Dynamic Risk by Regime

| Regime | Max Position | Trades/Hour | Stop-Loss | Take-Profit |
|--------|-------------|-------------|-----------|-------------|
| Bull | 20% equity | 10-20 | 2% | 4% |
| Bear | 10% equity | 5-10 | 1.5% | 3% |
| Sideways | 15% equity | 15-25 | 1% | 2% |
| Volatile | 5% equity | 2-5 | 3% | 6% |

### Loss Recovery Protocol

```python
class LossRecoveryManager:
    def __init__(self):
        self.consecutive_losses = 0
        self.daily_loss_pct = 0.0

    def on_trade_result(self, pnl_pct):
        if pnl_pct < 0:
            self.consecutive_losses += 1
            self.daily_loss_pct += abs(pnl_pct)
        else:
            self.consecutive_losses = 0

    def get_position_scale(self):
        """Scale down position size after losses."""
        if self.consecutive_losses >= 5:
            return 0.0  # Stop trading for 30 minutes
        elif self.consecutive_losses >= 3:
            return 0.25  # Quarter size
        elif self.consecutive_losses >= 2:
            return 0.5   # Half size
        elif self.daily_loss_pct > 10:
            return 0.25  # Heavy daily loss: scale way down
        elif self.daily_loss_pct > 5:
            return 0.5   # Moderate daily loss: scale down
        else:
            return 1.0   # Full size
```

---

## 15. Concrete Implementation Plan

### Week 1: Foundation

| Day | Task | Platform Tools |
|-----|------|---------------|
| 1 | Create 10 agents with different risk profiles | `POST /agents`, `PUT /agents/{id}/risk-profile` |
| 1-2 | Create 50 strategy definitions (5 categories × 10 variants) | `POST /strategies` |
| 2-3 | Run first batch: test all 50 strategies (20 episodes each = 1000 backtests) | `POST /strategies/{id}/test`, Celery |
| 4-5 | Analyze results, read recommendations, create v2 strategies | `GET /strategies/{id}/test-results`, `POST /strategies/{id}/versions` |
| 5 | Run second batch: test top 10 v2 strategies (50 episodes each = 500 backtests) | `POST /strategies/{id}/test` |

### Week 2: RL Training

| Day | Task | Platform Tools |
|-----|------|---------------|
| 1-2 | Train PPO-BTC agent (50+ episodes) | `tradeready-gym`, `POST /training/runs` |
| 2-3 | Train SAC-BTC agent (30+ episodes) | `tradeready-gym` |
| 3-4 | Train PPO-Portfolio agent (40+ episodes) | `TradeReady-Portfolio-v0` |
| 4-5 | Compare training runs, identify best models | `GET /training/compare` |
| 5 | Implement custom reward function, retrain best agent | Custom `AggressiveReturnReward` |

### Week 3: Ensemble & Validation

| Day | Task | Platform Tools |
|-----|------|---------------|
| 1-2 | Build regime detector | Custom Python code |
| 2-3 | Build ensemble combiner | Custom Python code |
| 3-4 | Walk-forward validation (100+ backtests) | `POST /backtest/create`, `GET /backtest/results` |
| 4-5 | Battle tournament: all agents compete | `POST /battles` |
| 5 | Promote winner to Champion | Agent reset + deploy |

### Week 4: Live & Iterate

| Day | Task | Platform Tools |
|-----|------|---------------|
| 1-2 | Deploy Champion to live paper trading | `TradeReady-Live-v0` or SDK |
| 2-5 | Monitor performance, compare vs backtest | `GET /analytics/performance` |
| 3-5 | Iterate: retrain if needed, adjust regime weights | Full pipeline |
| 5 | Second battle tournament | `POST /battles` |

### Ongoing (Weekly)

- Run a battle tournament every week with all agent variants
- Retrain RL agents monthly on recent data
- Create new strategy versions based on recommendations
- Track performance vs backtest expectations

---

## 16. Appendix: Math, Formulas & References

### Kelly Criterion Calculator

```
f* = (p × b - q) / b

Where:
  f* = optimal fraction of capital to bet
  p  = probability of winning (win rate)
  q  = probability of losing (1 - p)
  b  = average win / average loss (reward-to-risk ratio)

Example for our target:
  p = 0.65 (65% win rate)
  b = 1.6  (win $1.60 for every $1.00 risked)
  f* = (0.65 × 1.6 - 0.35) / 1.6 = (1.04 - 0.35) / 1.6 = 0.43

  Full Kelly: 43% of equity per trade (WAY too aggressive!)
  Half Kelly: 21.5% (still aggressive, but survivable)
  Quarter Kelly: 10.75% (our target range)
```

### Expected Daily Return Formula

```
E[daily] = N × (p × W - q × L) - N × F

Where:
  N = number of trades per day
  p = win rate
  W = average win per trade (% of equity)
  q = 1 - p
  L = average loss per trade (% of equity)
  F = fee per trade (% of trade value × position size)

Example:
  N = 50 trades/day
  p = 0.65
  W = 0.6% (of equity, with 10% position size and 6% average win)
  L = 0.375% (of equity, with 10% position size and 3.75% avg loss)
  F = 0.01% (0.1% fee × 10% position size)

  E[daily] = 50 × (0.65 × 0.006 - 0.35 × 0.00375) - 50 × 0.0001
           = 50 × (0.0039 - 0.0013125) - 0.005
           = 50 × 0.0025875 - 0.005
           = 0.129375 - 0.005
           = 0.124375 = 12.4% daily (theoretical maximum)

  Apply realism discount (0.25): 12.4% × 0.25 = 3.1% daily (achievable)
```

### Sharpe Ratio Formula

```
SR = (R_p - R_f) / σ_p × √252

Where:
  R_p = average daily portfolio return
  R_f = risk-free rate (0 for virtual platform)
  σ_p = standard deviation of daily returns
  √252 = annualization factor (252 trading days)

Target: SR > 2.0

  If daily return = 3% and daily std = 2%:
  SR = 0.03 / 0.02 × √252 = 1.5 × 15.87 = 23.8 (unrealistic — std would be higher)

  More realistic: daily return = 1%, daily std = 2%:
  SR = 0.01 / 0.02 × 15.87 = 7.94 (still very high)

  For reference, Renaissance Medallion has SR ~6-7
```

### Probability of Ruin

```
P(ruin) = ((1 - edge) / (1 + edge))^(capital / bet_size)

Where:
  edge = p - q = win_rate - (1 - win_rate) = 2 × win_rate - 1

Example:
  win_rate = 0.65, edge = 0.30
  capital = 100 units, bet_size = 10 units

  P(ruin) = (0.70/1.30)^(100/10) = 0.538^10 = 0.0021 = 0.21%

  With Half Kelly: effectively 5-unit bets
  P(ruin) = 0.538^20 = 0.0000044 = 0.00044% (essentially zero)
```

### Research Sources

- FinRL Ensemble: 52.6% annual return, Sharpe 2.81 (best published RL trading result)
- FinRL Contest 2024: Top ensemble achieved Sharpe 0.28, drawdown -0.73% on crypto
- Jane Street: $10.1B Q2 2025 revenue, single $2B day in April 2025 volatility
- Renaissance Medallion: ~60-80% annual returns over 30+ years (greatest track record ever)
- Kelly Criterion: John L. Kelly Jr., 1956; widely used in quantitative finance
- Walk-Forward Optimization: Robert Pardo, "The Evaluation and Optimization of Trading Strategies"
- Deflated Sharpe Ratio: Bailey & Lopez de Prado, 2014

---

## Summary: The 30-Second Version

1. **Create 10 agents** with different risk profiles
2. **Build 50+ strategies**, test each with 20 episodes (**1000 backtests**)
3. **Iterate** using recommendations, create v2/v3 (**500+ more backtests**)
4. **Train RL agents** (PPO, SAC) on top strategies (**500+ training episodes**)
5. **Build an ensemble** that combines rule-based + RL with regime detection
6. **Validate** with walk-forward testing (**100+ validation backtests**)
7. **Battle tournament** all agents against each other monthly
8. **Deploy** the Champion to live paper trading
9. **Monitor** and retrain when performance degrades
10. **Repeat** the cycle continuously

**Total platform usage: 2000+ backtests, 500+ training episodes, 10+ battles**

The platform provides every tool needed for this pipeline. The main pieces to build are:
- Regime detector (custom Python)
- Ensemble combiner (custom Python)
- Walk-forward validation runner (custom Python using the backtest API)
- Custom reward function (already supported by the gym)

**Target: 1-3% daily average is achievable with this pipeline on the virtual platform.**
