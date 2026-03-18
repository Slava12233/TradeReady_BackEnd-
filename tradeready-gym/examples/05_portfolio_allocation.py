"""Example 05: Multi-asset portfolio allocation."""

import gymnasium as gym
import numpy as np

import tradeready_gym  # noqa: F401

env = gym.make(
    "TradeReady-Portfolio-v0",
    api_key="ak_live_YOUR_KEY",
    symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    start_time="2025-01-01T00:00:00Z",
    end_time="2025-01-15T00:00:00Z",
)

obs, info = env.reset()
for step in range(200):
    # Equal-weight portfolio
    weights = np.array([0.33, 0.33, 0.33], dtype=np.float32)
    obs, reward, terminated, truncated, info = env.step(weights)
    if step % 50 == 0:
        print(f"Step {step} | Equity: {info.get('equity', '?')}")
    if terminated:
        break

env.close()
