"""Gymnasium compliance tests for all TradeReady environments."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import gymnasium as gym
import numpy as np
import pytest

import tradeready_gym  # noqa: F401 — trigger registration
from tradeready_gym.envs.single_asset_env import SingleAssetTradingEnv
from tradeready_gym.envs.multi_asset_env import MultiAssetTradingEnv
from tradeready_gym.wrappers.normalization import NormalizationWrapper
from tradeready_gym.wrappers.batch_step import BatchStepWrapper
from tradeready_gym.wrappers.feature_engineering import FeatureEngineeringWrapper
from tradeready_gym.utils.training_tracker import TrainingTracker


def _mock_api_call(method: str, path: str, **kwargs):
    """Mock API call that returns realistic responses."""
    if "create" in path:
        return {"session_id": "test-session-123"}
    if "start" in path:
        return {"status": "active"}
    if "step" in path:
        return {
            "virtual_time": "2025-01-01T00:01:00Z",
            "step": 1,
            "total_steps": 1000,
            "progress_pct": 0.1,
            "prices": {"BTCUSDT": "97000.00", "ETHUSDT": "3500.00", "SOLUSDT": "150.00"},
            "filled_orders": [],
            "portfolio": {
                "total_equity": "10050.00",
                "available_cash": "10050.00",
                "locked_cash": "0",
                "total_position_value": "0",
                "unrealized_pnl": "0",
                "realized_pnl": "50.00",
                "total_pnl": "50.00",
                "roi_pct": "0.5",
                "starting_balance": "10000.00",
                "positions": [],
            },
            "is_complete": False,
        }
    if "candles" in path:
        return {
            "candles": [
                {
                    "time": f"2025-01-01T00:{i:02d}:00Z",
                    "open": str(97000 + i * 10),
                    "high": str(97050 + i * 10),
                    "low": str(96950 + i * 10),
                    "close": str(97020 + i * 10),
                    "volume": "100.5",
                    "trade_count": 50,
                }
                for i in range(30)
            ]
        }
    if "results" in path:
        return {
            "roi_pct": 0.5,
            "sharpe_ratio": 1.2,
            "max_drawdown_pct": 2.0,
            "total_trades": 15,
        }
    if "order" in path:
        return {"order_id": "test-order", "status": "filled"}
    return {}


@pytest.fixture()
def _mock_http():
    """Patch httpx.Client so no real HTTP calls are made."""
    with patch("tradeready_gym.envs.base_trading_env.httpx.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client

        def _request(method, path, **kwargs):
            resp = MagicMock()
            resp.status_code = 200
            resp.content = b"ok"
            resp.json.return_value = _mock_api_call(method, path, **kwargs)
            resp.raise_for_status.return_value = None
            return resp

        mock_client.request.side_effect = _request
        yield mock_client


@pytest.fixture()
def _mock_tracker():
    """Patch TrainingTracker to be a no-op."""
    with patch("tradeready_gym.envs.base_trading_env.TrainingTracker") as mock_cls:
        mock_tracker = MagicMock()
        mock_cls.return_value = mock_tracker
        yield mock_tracker


class TestSingleAssetDiscrete:
    """Tests for the discrete single-asset environment."""

    def test_reset_returns_correct_shape(self, _mock_http, _mock_tracker):
        env = SingleAssetTradingEnv(symbol="BTCUSDT", api_key="test")
        obs, info = env.reset()
        assert isinstance(obs, np.ndarray)
        assert obs.dtype == np.float32
        assert "session_id" in info
        env.close()

    def test_step_returns_five_tuple(self, _mock_http, _mock_tracker):
        env = SingleAssetTradingEnv(symbol="BTCUSDT", api_key="test")
        env.reset()
        result = env.step(0)  # hold
        assert len(result) == 5
        obs, reward, terminated, truncated, info = result
        assert isinstance(obs, np.ndarray)
        assert isinstance(reward, float)
        assert isinstance(terminated, bool)
        assert isinstance(truncated, bool)
        assert isinstance(info, dict)
        env.close()

    def test_action_space_is_discrete_3(self, _mock_http, _mock_tracker):
        env = SingleAssetTradingEnv(symbol="BTCUSDT", api_key="test")
        assert isinstance(env.action_space, gym.spaces.Discrete)
        assert env.action_space.n == 3
        env.close()

    def test_observation_space_shape(self, _mock_http, _mock_tracker):
        env = SingleAssetTradingEnv(symbol="BTCUSDT", api_key="test")
        assert isinstance(env.observation_space, gym.spaces.Box)
        assert len(env.observation_space.shape) == 1
        env.close()

    def test_buy_action_generates_order(self, _mock_http, _mock_tracker):
        env = SingleAssetTradingEnv(symbol="BTCUSDT", api_key="test")
        env.reset()
        env.step(1)  # buy — should call the order endpoint
        env.close()

    def test_sell_action_with_position(self, _mock_http, _mock_tracker):
        env = SingleAssetTradingEnv(symbol="BTCUSDT", api_key="test")
        env.reset()
        # Inject a position into the step result
        env._last_step_result["portfolio"]["positions"] = [
            {"symbol": "BTCUSDT", "quantity": "0.01", "market_value": "970"}
        ]
        env.step(2)  # sell
        env.close()


class TestSingleAssetContinuous:
    """Tests for the continuous single-asset environment."""

    def test_action_space_is_box(self, _mock_http, _mock_tracker):
        env = SingleAssetTradingEnv(symbol="BTCUSDT", continuous=True, api_key="test")
        assert isinstance(env.action_space, gym.spaces.Box)
        assert env.action_space.shape == (1,)
        env.close()

    def test_step_with_continuous_action(self, _mock_http, _mock_tracker):
        env = SingleAssetTradingEnv(symbol="BTCUSDT", continuous=True, api_key="test")
        env.reset()
        action = np.array([0.5], dtype=np.float32)
        obs, reward, terminated, truncated, info = env.step(action)
        assert isinstance(obs, np.ndarray)
        env.close()

    def test_dead_zone_holds(self, _mock_http, _mock_tracker):
        env = SingleAssetTradingEnv(symbol="BTCUSDT", continuous=True, api_key="test")
        env.reset()
        orders = env._execute_action(np.array([0.01]))
        assert len(orders) == 0  # below dead zone threshold
        env.close()


class TestMultiAsset:
    """Tests for the multi-asset portfolio environment."""

    def test_action_space_shape(self, _mock_http, _mock_tracker):
        env = MultiAssetTradingEnv(symbols=["BTCUSDT", "ETHUSDT"], api_key="test")
        assert isinstance(env.action_space, gym.spaces.Box)
        assert env.action_space.shape == (2,)
        env.close()

    def test_reset_and_step(self, _mock_http, _mock_tracker):
        env = MultiAssetTradingEnv(symbols=["BTCUSDT", "ETHUSDT"], api_key="test")
        obs, info = env.reset()
        assert isinstance(obs, np.ndarray)
        action = np.array([0.5, 0.3], dtype=np.float32)
        obs, reward, terminated, truncated, info = env.step(action)
        assert isinstance(obs, np.ndarray)
        env.close()

    def test_weight_normalization(self, _mock_http, _mock_tracker):
        env = MultiAssetTradingEnv(symbols=["BTCUSDT", "ETHUSDT"], api_key="test")
        env.reset()
        # Weights > 1 should be normalized
        orders = env._execute_action(np.array([0.8, 0.8]))
        env.close()


class TestRewardFunctions:
    """Tests for reward function implementations."""

    def test_pnl_reward(self):
        from tradeready_gym.rewards.pnl_reward import PnLReward

        reward = PnLReward()
        assert reward.compute(10000, 10100, {}) == 100.0
        assert reward.compute(10000, 9900, {}) == -100.0

    def test_sharpe_reward(self):
        from tradeready_gym.rewards.sharpe_reward import SharpeReward

        reward = SharpeReward(window=5)
        # First few steps should return 0 or small values
        r1 = reward.compute(10000, 10100, {})
        r2 = reward.compute(10100, 10200, {})
        assert isinstance(r1, float)
        assert isinstance(r2, float)

    def test_sortino_reward(self):
        from tradeready_gym.rewards.sortino_reward import SortinoReward

        reward = SortinoReward(window=5)
        r = reward.compute(10000, 10100, {})
        assert isinstance(r, float)

    def test_drawdown_penalty_reward(self):
        from tradeready_gym.rewards.drawdown_penalty_reward import DrawdownPenaltyReward

        reward = DrawdownPenaltyReward(penalty_coeff=1.0)
        # Going up: no drawdown penalty
        r1 = reward.compute(10000, 10100, {})
        assert r1 == 100.0  # pure PnL, no drawdown yet
        # Going down: drawdown penalty kicks in
        r2 = reward.compute(10100, 10000, {})
        assert r2 < -100.0  # PnL loss + drawdown penalty


class TestObservationBuilder:
    """Tests for the observation builder."""

    def test_build_basic(self):
        from tradeready_gym.spaces.observation_builders import ObservationBuilder

        builder = ObservationBuilder(
            features=["ohlcv", "balance"],
            lookback_window=10,
            n_assets=1,
        )
        candles = {
            "BTCUSDT": [
                {"open": 100, "high": 105, "low": 95, "close": 102, "volume": 50}
                for _ in range(10)
            ]
        }
        portfolio = {"total_equity": "10000", "available_cash": "10000", "starting_balance": "10000"}
        obs = builder.build(candles, portfolio)
        assert isinstance(obs, np.ndarray)
        assert obs.dtype == np.float32

    def test_empty_candles(self):
        from tradeready_gym.spaces.observation_builders import ObservationBuilder

        builder = ObservationBuilder(features=["ohlcv"], lookback_window=5, n_assets=1)
        obs = builder.build({"BTCUSDT": []}, {})
        assert isinstance(obs, np.ndarray)
        assert obs.shape[0] == builder._total_dim


class TestTrainingTracker:
    """Tests for the training tracker."""

    def test_register_and_report(self):
        with patch("tradeready_gym.utils.training_tracker.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_client.post.return_value = mock_resp

            tracker = TrainingTracker(api_key="test")
            tracker.register_run()
            assert tracker._registered
            tracker.report_episode(1, session_id="s1", metrics={"roi_pct": 1.5})
            assert mock_client.post.call_count == 2

    def test_complete_run(self):
        with patch("tradeready_gym.utils.training_tracker.httpx.Client") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client.post.return_value = mock_resp

            tracker = TrainingTracker(api_key="test")
            tracker.register_run()
            tracker.complete_run()
            assert tracker._completed


class TestWrappers:
    """Tests for Gymnasium wrappers."""

    def test_normalization_wrapper(self, _mock_http, _mock_tracker):
        env = SingleAssetTradingEnv(symbol="BTCUSDT", api_key="test")
        wrapped = NormalizationWrapper(env)
        obs, _ = wrapped.reset()
        assert isinstance(obs, np.ndarray)
        assert obs.dtype == np.float32
        wrapped.close()

    def test_batch_step_wrapper(self, _mock_http, _mock_tracker):
        env = SingleAssetTradingEnv(symbol="BTCUSDT", api_key="test")
        wrapped = BatchStepWrapper(env, n_steps=3)
        wrapped.reset()
        obs, reward, terminated, truncated, info = wrapped.step(0)
        assert isinstance(obs, np.ndarray)
        wrapped.close()

    def test_feature_engineering_wrapper(self, _mock_http, _mock_tracker):
        env = SingleAssetTradingEnv(symbol="BTCUSDT", api_key="test")
        wrapped = FeatureEngineeringWrapper(env, periods=[5, 10])
        obs, _ = wrapped.reset()
        assert isinstance(obs, np.ndarray)
        # Should have extra dimensions for SMA ratios + momentum
        orig_dim = env.observation_space.shape[0]
        assert obs.shape[0] == orig_dim + 3  # 2 SMA ratios + 1 momentum
        wrapped.close()


class TestActionSpaces:
    """Tests for action space presets."""

    def test_discrete(self):
        from tradeready_gym.spaces.action_spaces import discrete_action_space

        space = discrete_action_space()
        assert isinstance(space, gym.spaces.Discrete)
        assert space.n == 3

    def test_continuous(self):
        from tradeready_gym.spaces.action_spaces import continuous_action_space

        space = continuous_action_space()
        assert isinstance(space, gym.spaces.Box)
        assert space.shape == (1,)

    def test_portfolio(self):
        from tradeready_gym.spaces.action_spaces import portfolio_action_space

        space = portfolio_action_space(5)
        assert isinstance(space, gym.spaces.Box)
        assert space.shape == (5,)

    def test_multi_discrete(self):
        from tradeready_gym.spaces.action_spaces import multi_discrete_action_space

        space = multi_discrete_action_space(3)
        assert isinstance(space, gym.spaces.MultiDiscrete)

    def test_parametric(self):
        from tradeready_gym.spaces.action_spaces import parametric_action_space

        space = parametric_action_space()
        assert isinstance(space, gym.spaces.Tuple)


