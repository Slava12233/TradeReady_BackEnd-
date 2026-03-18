"""Example 04: Continuous action space for fine-grained position sizing."""

import gymnasium as gym
import numpy as np

import tradeready_gym  # noqa: F401

env = gym.make(
    "TradeReady-BTC-Continuous-v0",
    api_key="ak_live_YOUR_KEY",
    start_time="2025-01-01T00:00:00Z",
    end_time="2025-01-15T00:00:00Z",
)

obs, info = env.reset()
for step in range(200):
    # Simple momentum signal: buy when observation is positive, sell when negative
    signal = np.clip(np.mean(obs[-10:]) * 10, -1, 1)
    action = np.array([signal], dtype=np.float32)
    obs, reward, terminated, truncated, info = env.step(action)
    if terminated:
        break

print(f"Final equity: {info.get('equity', '?')}")
env.close()
