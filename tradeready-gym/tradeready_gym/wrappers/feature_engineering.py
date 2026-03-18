"""Wrapper that adds technical indicators to the observation."""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces


class FeatureEngineeringWrapper(gym.ObservationWrapper):
    """Adds rolling technical indicator features to the observation.

    Appends simple moving average (SMA) ratios and momentum features
    to the existing observation vector.

    Args:
        env:     Wrapped Gymnasium environment.
        periods: List of SMA periods to add as features.
    """

    def __init__(self, env: gym.Env, periods: list[int] | None = None) -> None:
        super().__init__(env)
        self._periods = periods or [5, 10, 20]
        self._extra_dims = len(self._periods) + 1  # SMA ratios + momentum
        self._price_history: list[float] = []

        orig_shape = env.observation_space.shape
        assert orig_shape is not None
        new_dim = orig_shape[0] + self._extra_dims
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(new_dim,), dtype=np.float32
        )

    def observation(self, observation: np.ndarray) -> np.ndarray:
        """Append indicator features to the observation."""
        # Extract the latest close price from the observation (assumed at index 3 for OHLCV)
        if len(observation) > 3:
            price = float(observation[3])
        else:
            price = float(observation[0]) if len(observation) > 0 else 0.0

        self._price_history.append(price)
        if len(self._price_history) > max(self._periods, default=20) + 1:
            self._price_history = self._price_history[-(max(self._periods, default=20) + 1) :]

        extra: list[float] = []
        for period in self._periods:
            if len(self._price_history) >= period and price > 0:
                sma = sum(self._price_history[-period:]) / period
                extra.append(price / sma if sma > 0 else 1.0)
            else:
                extra.append(1.0)

        # Momentum: price change over last 5 steps
        if len(self._price_history) >= 6 and self._price_history[-6] > 0:
            momentum = (price - self._price_history[-6]) / self._price_history[-6]
        else:
            momentum = 0.0
        extra.append(momentum)

        return np.concatenate([observation, np.array(extra, dtype=np.float32)])
