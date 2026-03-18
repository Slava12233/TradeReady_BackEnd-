"""Wrapper that batches multiple environment steps per agent action."""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np


class BatchStepWrapper(gym.Wrapper):
    """Executes N environment steps per agent action.

    Reduces HTTP overhead by holding the same action for multiple
    backtest steps. The agent only decides once every ``n_steps`` candles.

    The reward is the sum of rewards over all sub-steps.

    Args:
        env:     Wrapped Gymnasium environment.
        n_steps: Number of environment steps per agent action.
    """

    def __init__(self, env: gym.Env, n_steps: int = 5) -> None:
        super().__init__(env)
        self._n_steps = n_steps

    def step(
        self, action: Any
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Execute n_steps of the underlying environment with the same action."""
        total_reward = 0.0
        obs = np.zeros(self.observation_space.shape or (1,), dtype=np.float32)
        terminated = False
        truncated = False
        info: dict[str, Any] = {}

        for _ in range(self._n_steps):
            obs, reward, terminated, truncated, info = self.env.step(action)
            total_reward += float(reward)
            if terminated or truncated:
                break

        return obs, total_reward, terminated, truncated, info
