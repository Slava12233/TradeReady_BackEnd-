"""Pre-built action space presets for trading environments."""

from __future__ import annotations

import numpy as np
from gymnasium import spaces


def discrete_action_space() -> spaces.Discrete:
    """Hold / Buy / Sell action space."""
    return spaces.Discrete(3)


def continuous_action_space() -> spaces.Box:
    """Continuous direction + magnitude action space.

    Values in ``[-1, 1]``: negative = sell, positive = buy, magnitude = position size.
    """
    return spaces.Box(low=-1.0, high=1.0, shape=(1,), dtype=np.float32)


def portfolio_action_space(n_assets: int) -> spaces.Box:
    """Target portfolio weight action space.

    Each element represents the target allocation weight for one asset.
    Weights are clipped to ``[0, 1]`` and normalized to sum to 1.
    """
    return spaces.Box(low=0.0, high=1.0, shape=(n_assets,), dtype=np.float32)


def multi_discrete_action_space(n_assets: int) -> spaces.MultiDiscrete:
    """Per-asset discrete action space.

    Each asset gets its own Hold(0) / Buy(1) / Sell(2) action.
    """
    return spaces.MultiDiscrete([3] * n_assets)


def parametric_action_space() -> spaces.Tuple:
    """Parametric action space: (direction, quantity_fraction).

    - ``direction``: Discrete(3) — Hold / Buy / Sell
    - ``quantity_fraction``: Box(0, 1) — fraction of max position size
    """
    return spaces.Tuple((
        spaces.Discrete(3),
        spaces.Box(low=0.0, high=1.0, shape=(1,), dtype=np.float32),
    ))
