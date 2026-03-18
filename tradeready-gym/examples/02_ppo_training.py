"""Example 02: PPO training with Stable-Baselines3.

Requires: pip install stable-baselines3
"""

import gymnasium as gym

import tradeready_gym  # noqa: F401

try:
    from stable_baselines3 import PPO
except ImportError:
    print("Install stable-baselines3: pip install stable-baselines3")
    raise

env = gym.make(
    "TradeReady-BTC-Continuous-v0",
    api_key="ak_live_YOUR_KEY",
    start_time="2025-01-01T00:00:00Z",
    end_time="2025-02-01T00:00:00Z",
    starting_balance=10000.0,
)

model = PPO("MlpPolicy", env, verbose=1, n_steps=256, batch_size=64)
model.learn(total_timesteps=10_000)
model.save("ppo_btc_trader")
print("Training complete. Model saved to ppo_btc_trader.zip")
env.close()
