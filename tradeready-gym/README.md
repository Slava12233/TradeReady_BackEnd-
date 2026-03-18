# TradeReady Gym

Gymnasium-compatible trading environments backed by the TradeReady backtest engine. Train RL agents on real crypto market data with zero risk.

## Installation

```bash
pip install tradeready-gym
```

Or install from source:

```bash
cd tradeready-gym
pip install -e .
```

## Quick Start

```python
import gymnasium as gym
import tradeready_gym  # registers environments

env = gym.make(
    "TradeReady-BTC-v0",
    api_key="ak_live_YOUR_KEY",
    start_time="2025-01-01T00:00:00Z",
    end_time="2025-02-01T00:00:00Z",
)

obs, info = env.reset()
for _ in range(1000):
    action = env.action_space.sample()
    obs, reward, terminated, truncated, info = env.step(action)
    if terminated:
        obs, info = env.reset()

env.close()
```

## Registered Environments

| ID | Action Space | Description |
|----|-------------|-------------|
| `TradeReady-BTC-v0` | Discrete(3) | Single-asset BTC: Hold/Buy/Sell |
| `TradeReady-ETH-v0` | Discrete(3) | Single-asset ETH: Hold/Buy/Sell |
| `TradeReady-SOL-v0` | Discrete(3) | Single-asset SOL: Hold/Buy/Sell |
| `TradeReady-BTC-Continuous-v0` | Box(-1, 1) | BTC with continuous position sizing |
| `TradeReady-ETH-Continuous-v0` | Box(-1, 1) | ETH with continuous position sizing |
| `TradeReady-Portfolio-v0` | Box(0, 1, N) | Multi-asset portfolio weight allocation |
| `TradeReady-Live-v0` | Discrete(3) | Live paper trading with real-time prices |

## Action Spaces

**Discrete(3):** 0=Hold, 1=Buy (10% of equity), 2=Sell (close position)

**Continuous Box(-1, 1):** Negative=sell, positive=buy, magnitude=position size fraction

**Portfolio Box(0, 1, N):** Target allocation weights per asset (auto-normalized)

## Observation Space

Configurable via `observation_features` parameter:

| Feature | Dims/Candle | Description |
|---------|------------|-------------|
| `ohlcv` | 5 | Open, High, Low, Close, Volume |
| `rsi_14` | 1 | Relative Strength Index (normalized) |
| `macd` | 3 | MACD line, signal, histogram |
| `bollinger` | 3 | Upper, middle, lower bands |
| `volume` | 1 | Raw volume |
| `adx` | 1 | Average Directional Index |
| `atr` | 1 | Average True Range |
| `balance` | 1 (scalar) | Available cash / starting balance |
| `position` | 1 (scalar) | Position value / equity |
| `unrealized_pnl` | 1 (scalar) | Unrealized PnL / equity |

## Reward Functions

```python
from tradeready_gym import PnLReward, SharpeReward, SortinoReward, DrawdownPenaltyReward

# Simple equity change
env = gym.make("TradeReady-BTC-v0", reward_function=PnLReward(), ...)

# Risk-adjusted (rolling Sharpe delta)
env = gym.make("TradeReady-BTC-v0", reward_function=SharpeReward(window=50), ...)

# Downside-risk adjusted
env = gym.make("TradeReady-BTC-v0", reward_function=SortinoReward(window=50), ...)

# PnL with drawdown penalty
env = gym.make("TradeReady-BTC-v0", reward_function=DrawdownPenaltyReward(penalty_coeff=1.0), ...)
```

### Custom Rewards

```python
from tradeready_gym import CustomReward

class MyReward(CustomReward):
    def compute(self, prev_equity, curr_equity, info):
        return (curr_equity - prev_equity) / prev_equity  # log-like return
```

## Training Tracker

Training runs are automatically reported to the TradeReady platform (set `track_training=False` to disable). View progress in the Training dashboard.

## Wrappers

```python
from tradeready_gym import FeatureEngineeringWrapper, NormalizationWrapper, BatchStepWrapper

# Add SMA ratios and momentum features
env = FeatureEngineeringWrapper(env, periods=[5, 10, 20])

# Normalize observations to [-1, 1]
env = NormalizationWrapper(env)

# Batch 5 environment steps per agent action
env = BatchStepWrapper(env, n_steps=5)
```

## Stable-Baselines3 Integration

```python
from stable_baselines3 import PPO
import gymnasium as gym
import tradeready_gym

env = gym.make("TradeReady-BTC-Continuous-v0", api_key="ak_live_...", ...)
model = PPO("MlpPolicy", env, verbose=1)
model.learn(total_timesteps=50_000)
model.save("btc_trader")
```

## Examples

See the `examples/` directory for 10 complete scripts covering:
1. Random agent
2. PPO training
3. DQN training
4. Continuous actions
5. Portfolio allocation
6. Custom rewards
7. Custom observations
8. Vectorized training
9. Model evaluation
10. Live paper trading

## Requirements

- Python 3.12+
- gymnasium >= 0.29
- numpy >= 1.26
- httpx >= 0.28
- A running TradeReady platform instance
