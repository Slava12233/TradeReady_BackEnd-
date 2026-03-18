"""Base class for custom reward functions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class CustomReward(ABC):
    """Abstract base class for reward functions.

    Subclass this and implement :meth:`compute` to create a custom reward.

    Example::

        class MyReward(CustomReward):
            def compute(self, prev_equity, curr_equity, info):
                return (curr_equity - prev_equity) * 2  # double PnL
    """

    def reset(self) -> None:
        """Reset internal state between episodes. Override in stateful subclasses."""

    @abstractmethod
    def compute(
        self,
        prev_equity: float,
        curr_equity: float,
        info: dict[str, Any],
    ) -> float:
        """Calculate the reward for the current step.

        Args:
            prev_equity: Portfolio equity at the previous step.
            curr_equity: Portfolio equity at the current step.
            info:        Full step result dict from the backtest API.

        Returns:
            Scalar reward value.
        """
        ...
