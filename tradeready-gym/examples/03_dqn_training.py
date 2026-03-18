"""Example 03: DQN training with Stable-Baselines3.

Requires: pip install stable-baselines3
"""

import gymnasium as gym

import tradeready_gym  # noqa: F401

try:
    from stable_baselines3 import DQN
except ImportError:
    print("Install stable-baselines3: pip install stable-baselines3")
    raise

env = gym.make(
    "TradeReady-BTC-v0",
    api_key="ak_live_YOUR_KEY",
    start_time="2025-01-01T00:00:00Z",
    end_time="2025-02-01T00:00:00Z",
)

model = DQN(
    "MlpPolicy",
    env,
    verbose=1,
    learning_rate=1e-4,
    buffer_size=10_000,
    batch_size=64,
    exploration_fraction=0.3,
)
model.learn(total_timesteps=10_000)
model.save("dqn_btc_trader")
print("Training complete. Model saved to dqn_btc_trader.zip")
env.close()
