"""Example 07: Custom observation features."""

import gymnasium as gym

import tradeready_gym  # noqa: F401
from tradeready_gym import SingleAssetTradingEnv

# Use a rich set of technical indicators in the observation
env = SingleAssetTradingEnv(
    symbol="BTCUSDT",
    api_key="ak_live_YOUR_KEY",
    observation_features=["ohlcv", "rsi_14", "macd", "bollinger", "atr", "balance", "position", "unrealized_pnl"],
    lookback_window=50,
    start_time="2025-01-01T00:00:00Z",
    end_time="2025-02-01T00:00:00Z",
)

obs, info = env.reset()
print(f"Observation shape: {obs.shape}")
print(f"Observation space: {env.observation_space}")

for step in range(50):
    action = env.action_space.sample()
    obs, reward, terminated, truncated, info = env.step(action)
    if terminated:
        break

env.close()
