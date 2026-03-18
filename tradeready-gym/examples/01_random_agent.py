"""Example 01: Random agent trading BTC."""

import gymnasium as gym
import tradeready_gym  # noqa: F401

env = gym.make(
    "TradeReady-BTC-v0",
    api_key="ak_live_YOUR_KEY",
    start_time="2025-01-01T00:00:00Z",
    end_time="2025-01-15T00:00:00Z",
)

obs, info = env.reset()
total_reward = 0.0

for step in range(500):
    action = env.action_space.sample()
    obs, reward, terminated, truncated, info = env.step(action)
    total_reward += reward
    if step % 100 == 0:
        print(f"Step {step} | Equity: {info.get('equity', '?')} | Reward: {total_reward:.2f}")
    if terminated:
        print(f"Episode done at step {step} | Total reward: {total_reward:.2f}")
        break

env.close()
