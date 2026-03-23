"""TradeReady Gym — Gymnasium-compatible trading environments.

Provides OpenAI Gymnasium environments backed by the TradeReady backtest
engine for training RL agents on crypto trading strategies.

Registered Environments:
    - ``TradeReady-BTC-v0`` — Single-asset BTC discrete trading
    - ``TradeReady-ETH-v0`` — Single-asset ETH discrete trading
    - ``TradeReady-SOL-v0`` — Single-asset SOL discrete trading
    - ``TradeReady-BTC-Continuous-v0`` — Single-asset BTC continuous trading
    - ``TradeReady-ETH-Continuous-v0`` — Single-asset ETH continuous trading
    - ``TradeReady-Portfolio-v0`` — Multi-asset portfolio allocation
    - ``TradeReady-Live-v0`` — Live single-asset trading (real-time)

Quick Start::

    import gymnasium as gym
    import tradeready_gym  # noqa: F401 — triggers env registration

    env = gym.make("TradeReady-BTC-v0", api_key="ak_live_...")
    obs, info = env.reset()

    for _ in range(100):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated:
            obs, info = env.reset()

    env.close()
"""

from __future__ import annotations

import gymnasium

from tradeready_gym.envs.base_trading_env import BaseTradingEnv
from tradeready_gym.envs.live_env import LiveTradingEnv
from tradeready_gym.envs.multi_asset_env import MultiAssetTradingEnv
from tradeready_gym.envs.single_asset_env import SingleAssetTradingEnv
from tradeready_gym.rewards.composite import CompositeReward
from tradeready_gym.rewards.custom_reward import CustomReward
from tradeready_gym.rewards.drawdown_penalty_reward import DrawdownPenaltyReward
from tradeready_gym.rewards.pnl_reward import PnLReward
from tradeready_gym.rewards.sharpe_reward import SharpeReward
from tradeready_gym.rewards.sortino_reward import SortinoReward
from tradeready_gym.utils.training_tracker import TrainingTracker
from tradeready_gym.wrappers.batch_step import BatchStepWrapper
from tradeready_gym.wrappers.feature_engineering import FeatureEngineeringWrapper
from tradeready_gym.wrappers.normalization import NormalizationWrapper

__version__ = "0.1.0"

__all__ = [
    "BaseTradingEnv",
    "SingleAssetTradingEnv",
    "MultiAssetTradingEnv",
    "LiveTradingEnv",
    "CustomReward",
    "PnLReward",
    "SharpeReward",
    "SortinoReward",
    "DrawdownPenaltyReward",
    "CompositeReward",
    "TrainingTracker",
    "FeatureEngineeringWrapper",
    "NormalizationWrapper",
    "BatchStepWrapper",
]

# ---------------------------------------------------------------------------
# Gymnasium environment registration
# ---------------------------------------------------------------------------

# Single-asset discrete environments
gymnasium.register(
    id="TradeReady-BTC-v0",
    entry_point="tradeready_gym.envs.single_asset_env:SingleAssetTradingEnv",
    kwargs={"symbol": "BTCUSDT", "continuous": False},
)

gymnasium.register(
    id="TradeReady-ETH-v0",
    entry_point="tradeready_gym.envs.single_asset_env:SingleAssetTradingEnv",
    kwargs={"symbol": "ETHUSDT", "continuous": False},
)

gymnasium.register(
    id="TradeReady-SOL-v0",
    entry_point="tradeready_gym.envs.single_asset_env:SingleAssetTradingEnv",
    kwargs={"symbol": "SOLUSDT", "continuous": False},
)

# Single-asset continuous environments
gymnasium.register(
    id="TradeReady-BTC-Continuous-v0",
    entry_point="tradeready_gym.envs.single_asset_env:SingleAssetTradingEnv",
    kwargs={"symbol": "BTCUSDT", "continuous": True},
)

gymnasium.register(
    id="TradeReady-ETH-Continuous-v0",
    entry_point="tradeready_gym.envs.single_asset_env:SingleAssetTradingEnv",
    kwargs={"symbol": "ETHUSDT", "continuous": True},
)

# Multi-asset portfolio environment
gymnasium.register(
    id="TradeReady-Portfolio-v0",
    entry_point="tradeready_gym.envs.multi_asset_env:MultiAssetTradingEnv",
    kwargs={"symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"]},
)

# Live trading environment
gymnasium.register(
    id="TradeReady-Live-v0",
    entry_point="tradeready_gym.envs.live_env:LiveTradingEnv",
    kwargs={"symbol": "BTCUSDT"},
)


def register_envs() -> None:
    """Entry point for gymnasium.envs plugin discovery (no-op, registration above)."""
