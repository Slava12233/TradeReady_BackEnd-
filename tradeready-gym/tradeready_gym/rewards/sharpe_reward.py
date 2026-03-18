"""Rolling Sharpe ratio delta reward function."""

from __future__ import annotations

import math
from typing import Any

from tradeready_gym.rewards.custom_reward import CustomReward


class SharpeReward(CustomReward):
    """Reward based on the rolling Sharpe ratio delta.

    Tracks a window of returns and computes the change in Sharpe ratio
    at each step.

    Args:
        window: Number of steps for the rolling calculation.
    """

    def __init__(self, window: int = 50) -> None:
        self._window = window
        self._returns: list[float] = []
        self._prev_sharpe: float = 0.0

    def reset(self) -> None:
        self._returns = []
        self._prev_sharpe = 0.0

    def compute(
        self,
        prev_equity: float,
        curr_equity: float,
        info: dict[str, Any],
    ) -> float:
        ret = (curr_equity - prev_equity) / prev_equity if prev_equity > 0 else 0.0
        self._returns.append(ret)
        if len(self._returns) > self._window:
            self._returns = self._returns[-self._window :]

        if len(self._returns) < 2:
            return 0.0

        mean = sum(self._returns) / len(self._returns)
        variance = sum((r - mean) ** 2 for r in self._returns) / len(self._returns)
        std = math.sqrt(variance) if variance > 0 else 1e-8

        sharpe = mean / std
        reward = sharpe - self._prev_sharpe
        self._prev_sharpe = sharpe
        return reward
