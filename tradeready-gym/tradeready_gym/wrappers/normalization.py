"""Wrapper that normalizes observations to [-1, 1] range."""

from __future__ import annotations

import gymnasium as gym
import numpy as np
from gymnasium import spaces


class NormalizationWrapper(gym.ObservationWrapper):
    """Normalizes observations to the [-1, 1] range using running statistics.

    Uses Welford's online algorithm to track mean and variance, then
    applies z-score normalization clipped to [-1, 1].

    Args:
        env:     Wrapped Gymnasium environment.
        clip:    Maximum absolute value after normalization.
        epsilon: Small constant for numerical stability.
    """

    def __init__(
        self,
        env: gym.Env,
        clip: float = 1.0,
        epsilon: float = 1e-8,
    ) -> None:
        super().__init__(env)
        self._clip = clip
        self._epsilon = epsilon
        obs_shape = env.observation_space.shape
        assert obs_shape is not None

        self._count: int = 0
        self._mean = np.zeros(obs_shape, dtype=np.float64)
        self._var = np.ones(obs_shape, dtype=np.float64)
        self._m2 = np.zeros(obs_shape, dtype=np.float64)

        self.observation_space = spaces.Box(
            low=-clip, high=clip, shape=obs_shape, dtype=np.float32
        )

    def observation(self, observation: np.ndarray) -> np.ndarray:
        """Normalize the observation using running statistics."""
        self._update_stats(observation)
        std = np.sqrt(self._var + self._epsilon)
        normalized = (observation - self._mean) / std
        return np.clip(normalized, -self._clip, self._clip).astype(np.float32)

    def _update_stats(self, obs: np.ndarray) -> None:
        """Update running mean and variance using Welford's algorithm."""
        self._count += 1
        delta = obs.astype(np.float64) - self._mean
        self._mean += delta / self._count
        delta2 = obs.astype(np.float64) - self._mean
        self._m2 += delta * delta2
        if self._count > 1:
            self._var = self._m2 / (self._count - 1)
