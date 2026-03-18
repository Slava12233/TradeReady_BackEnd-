"""Example 06: Custom reward function."""

from typing import Any

import gymnasium as gym

import tradeready_gym  # noqa: F401
from tradeready_gym import CustomReward, SingleAssetTradingEnv


class RiskAdjustedReward(CustomReward):
    """Reward that combines PnL with a volatility penalty."""

    def __init__(self, vol_penalty: float = 0.5):
        self._vol_penalty = vol_penalty
        self._returns: list[float] = []

    def compute(self, prev_equity: float, curr_equity: float, info: dict[str, Any]) -> float:
        ret = (curr_equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
        self._returns.append(ret)
        pnl = curr_equity - prev_equity

        # Penalize high volatility
        if len(self._returns) > 10:
            vol = sum((r - sum(self._returns[-10:]) / 10) ** 2 for r in self._returns[-10:]) / 10
            return pnl - self._vol_penalty * vol * 10000
        return pnl


env = SingleAssetTradingEnv(
    symbol="BTCUSDT",
    api_key="ak_live_YOUR_KEY",
    reward_function=RiskAdjustedReward(vol_penalty=0.5),
    start_time="2025-01-01T00:00:00Z",
    end_time="2025-01-15T00:00:00Z",
)

obs, info = env.reset()
for _ in range(100):
    action = env.action_space.sample()
    obs, reward, terminated, truncated, info = env.step(action)
    if terminated:
        break

env.close()
