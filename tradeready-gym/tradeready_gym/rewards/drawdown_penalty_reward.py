"""PnL reward with drawdown penalty."""

from __future__ import annotations

from typing import Any

from tradeready_gym.rewards.custom_reward import CustomReward


class DrawdownPenaltyReward(CustomReward):
    """Reward = PnL minus a penalty proportional to the current drawdown.

    ``reward = (curr_equity - prev_equity) - penalty_coeff * drawdown``

    where ``drawdown = (peak_equity - curr_equity) / peak_equity``.

    Args:
        penalty_coeff: Multiplier for the drawdown penalty (default 1.0).
    """

    def __init__(self, penalty_coeff: float = 1.0) -> None:
        self._penalty_coeff = penalty_coeff
        self._peak_equity: float = 0.0

    def reset(self) -> None:
        self._peak_equity = 0.0

    def compute(
        self,
        prev_equity: float,
        curr_equity: float,
        info: dict[str, Any],
    ) -> float:
        if curr_equity > self._peak_equity:
            self._peak_equity = curr_equity

        pnl = curr_equity - prev_equity
        drawdown = 0.0
        if self._peak_equity > 0:
            drawdown = (self._peak_equity - curr_equity) / self._peak_equity

        return pnl - self._penalty_coeff * drawdown
