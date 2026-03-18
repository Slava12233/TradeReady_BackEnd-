"""Sortino ratio delta reward function."""

from __future__ import annotations

import math
from typing import Any

from tradeready_gym.rewards.custom_reward import CustomReward


class SortinoReward(CustomReward):
    """Reward based on the rolling Sortino ratio delta.

    Like Sharpe but only penalizes downside volatility.

    Args:
        window: Number of steps for the rolling calculation.
    """

    def __init__(self, window: int = 50) -> None:
        self._window = window
        self._returns: list[float] = []
        self._prev_sortino: float = 0.0

    def reset(self) -> None:
        self._returns = []
        self._prev_sortino = 0.0

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
        downside = [min(r, 0) ** 2 for r in self._returns]
        downside_var = sum(downside) / len(downside)
        downside_std = math.sqrt(downside_var) if downside_var > 0 else 1e-8

        sortino = mean / downside_std
        reward = sortino - self._prev_sortino
        self._prev_sortino = sortino
        return reward
