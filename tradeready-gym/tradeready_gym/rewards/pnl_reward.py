"""Simple PnL-based reward function."""

from __future__ import annotations

from typing import Any

from tradeready_gym.rewards.custom_reward import CustomReward


class PnLReward(CustomReward):
    """Reward = equity change between steps.

    ``reward = curr_equity - prev_equity``
    """

    def compute(
        self,
        prev_equity: float,
        curr_equity: float,
        info: dict[str, Any],
    ) -> float:
        return curr_equity - prev_equity
