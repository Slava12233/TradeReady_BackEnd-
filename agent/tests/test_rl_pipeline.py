"""Tests for agent/strategies/rl/train.py — training pipeline structure.

These tests verify the pipeline surface without executing actual training.
SB3, gymnasium, and tradeready_gym are mocked throughout via sys.modules
injection so they do not need to be installed.

Test counts:
  TestTrainFunctionExists   — 3
  TestBuildReward           — 6
  TestEnvFactory            — 5
  TestMakeVecEnv            — 4
  TestCheckpointNaming      — 4
  TestEvaluationReport      — 6
  TestComputeMetrics        — 7

Total: 35
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_config(tmp_path: Path, **overrides: Any) -> MagicMock:
    """Minimal config mock matching the RLConfig interface."""
    cfg = MagicMock()
    cfg.platform_api_key = "ak_live_test"
    cfg.platform_base_url = "http://localhost:8000"
    cfg.env_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    cfg.timeframe = "1h"
    cfg.lookback_window = 30
    cfg.starting_balance = 10_000.0
    cfg.track_training = False
    cfg.reward_type = "sharpe"
    cfg.sharpe_window = 50
    cfg.drawdown_penalty_coeff = 0.5
    cfg.total_timesteps = 1_000
    cfg.n_envs = 1
    cfg.seed = 42
    cfg.save_freq = 100
    cfg.eval_freq = 200
    cfg.n_eval_episodes = 1
    cfg.learning_rate = 3e-4
    cfg.n_steps = 64
    cfg.batch_size = 32
    cfg.n_epochs = 2
    cfg.gamma = 0.99
    cfg.gae_lambda = 0.95
    cfg.clip_range = 0.2
    cfg.ent_coef = 0.01
    cfg.vf_coef = 0.5
    cfg.max_grad_norm = 0.5
    cfg.net_arch_pi = [64, 64]
    cfg.net_arch_vf = [64, 64]
    cfg.train_start = "2024-01-01T00:00:00Z"
    cfg.train_end = "2024-10-01T00:00:00Z"
    cfg.val_start = "2024-10-01T00:00:00Z"
    cfg.val_end = "2024-12-01T00:00:00Z"
    cfg.test_start = "2024-12-01T00:00:00Z"
    cfg.test_end = "2025-01-01T00:00:00Z"
    cfg.models_dir = tmp_path / "models"
    cfg.models_dir.mkdir(parents=True, exist_ok=True)
    cfg.log_dir = tmp_path / "models" / "logs"
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _make_reward_mocks() -> dict[str, MagicMock]:
    """Return a dict of mock reward class instances keyed by reward_type."""
    return {
        "pnl": MagicMock(name="PnLReward"),
        "sharpe": MagicMock(name="SharpeReward"),
        "sortino": MagicMock(name="SortinoReward"),
        "drawdown": MagicMock(name="DrawdownPenaltyReward"),
    }


def _inject_gym_mocks() -> dict[str, Any]:
    """
    Inject stub modules for stable_baselines3, gymnasium, and tradeready_gym
    into sys.modules so patch() targets can be resolved.

    Returns a dict of the injected mock objects for assertion use.
    Call _cleanup_gym_mocks(result) in a finally block.
    """
    mocks: dict[str, Any] = {}

    # ── stable_baselines3 ────────────────────────────────────────────────
    mock_ppo_instance = MagicMock(name="ppo_model_instance")
    mock_ppo_cls = MagicMock(name="PPO", return_value=mock_ppo_instance)
    mock_ppo_cls.load = MagicMock(return_value=mock_ppo_instance)

    mock_callback_list = MagicMock(name="CallbackList")
    mock_checkpoint_cb = MagicMock(name="CheckpointCallback")
    mock_eval_cb = MagicMock(name="EvalCallback")

    mock_sb3 = ModuleType("stable_baselines3")
    mock_sb3.PPO = mock_ppo_cls  # type: ignore[attr-defined]

    mock_sb3_callbacks = ModuleType("stable_baselines3.common.callbacks")
    mock_sb3_callbacks.CallbackList = mock_callback_list  # type: ignore[attr-defined]
    mock_sb3_callbacks.CheckpointCallback = mock_checkpoint_cb  # type: ignore[attr-defined]
    mock_sb3_callbacks.EvalCallback = mock_eval_cb  # type: ignore[attr-defined]

    mock_sb3_common = ModuleType("stable_baselines3.common")
    mock_sb3_common.callbacks = mock_sb3_callbacks  # type: ignore[attr-defined]

    mock_dummy_env = MagicMock(name="DummyVecEnvInstance")
    mock_subproc_env = MagicMock(name="SubprocVecEnvInstance")
    mock_dummy_cls = MagicMock(name="DummyVecEnv", return_value=mock_dummy_env)
    mock_subproc_cls = MagicMock(name="SubprocVecEnv", return_value=mock_subproc_env)

    mock_sb3_vec_env = ModuleType("stable_baselines3.common.vec_env")
    mock_sb3_vec_env.DummyVecEnv = mock_dummy_cls  # type: ignore[attr-defined]
    mock_sb3_vec_env.SubprocVecEnv = mock_subproc_cls  # type: ignore[attr-defined]

    # ── gymnasium ───────────────────────────────────────────────────────
    mock_base_env = MagicMock(name="base_env")
    mock_gym = ModuleType("gymnasium")
    mock_gym.make = MagicMock(return_value=mock_base_env)  # type: ignore[attr-defined]

    # ── tradeready_gym ───────────────────────────────────────────────────
    mock_fe_env = MagicMock(name="fe_env")
    mock_norm_env = MagicMock(name="norm_env")

    mock_fe_cls = MagicMock(name="FeatureEngineeringWrapper", return_value=mock_fe_env)
    mock_norm_cls = MagicMock(name="NormalizationWrapper", return_value=mock_norm_env)

    mock_tg_wrappers_fe = ModuleType("tradeready_gym.wrappers.feature_engineering")
    mock_tg_wrappers_fe.FeatureEngineeringWrapper = mock_fe_cls  # type: ignore[attr-defined]

    mock_tg_wrappers_norm = ModuleType("tradeready_gym.wrappers.normalization")
    mock_tg_wrappers_norm.NormalizationWrapper = mock_norm_cls  # type: ignore[attr-defined]

    mock_tg_wrappers = ModuleType("tradeready_gym.wrappers")
    mock_tg_wrappers.feature_engineering = mock_tg_wrappers_fe  # type: ignore[attr-defined]
    mock_tg_wrappers.normalization = mock_tg_wrappers_norm  # type: ignore[attr-defined]

    mock_pnl_reward = MagicMock(name="PnLReward")
    mock_sharpe_reward = MagicMock(name="SharpeReward")
    mock_sortino_reward = MagicMock(name="SortinoReward")
    mock_dd_reward = MagicMock(name="DrawdownPenaltyReward")

    mock_rewards_pnl = ModuleType("tradeready_gym.rewards.pnl_reward")
    mock_rewards_pnl.PnLReward = mock_pnl_reward  # type: ignore[attr-defined]

    mock_rewards_sharpe = ModuleType("tradeready_gym.rewards.sharpe_reward")
    mock_rewards_sharpe.SharpeReward = mock_sharpe_reward  # type: ignore[attr-defined]

    mock_rewards_sortino = ModuleType("tradeready_gym.rewards.sortino_reward")
    mock_rewards_sortino.SortinoReward = mock_sortino_reward  # type: ignore[attr-defined]

    mock_rewards_dd = ModuleType("tradeready_gym.rewards.drawdown_penalty_reward")
    mock_rewards_dd.DrawdownPenaltyReward = mock_dd_reward  # type: ignore[attr-defined]

    mock_rewards = ModuleType("tradeready_gym.rewards")

    mock_tg = ModuleType("tradeready_gym")
    mock_tg.wrappers = mock_tg_wrappers  # type: ignore[attr-defined]
    mock_tg.rewards = mock_rewards  # type: ignore[attr-defined]

    # Inject all into sys.modules
    to_inject = {
        "stable_baselines3": mock_sb3,
        "stable_baselines3.common": mock_sb3_common,
        "stable_baselines3.common.callbacks": mock_sb3_callbacks,
        "stable_baselines3.common.vec_env": mock_sb3_vec_env,
        "gymnasium": mock_gym,
        "tradeready_gym": mock_tg,
        "tradeready_gym.wrappers": mock_tg_wrappers,
        "tradeready_gym.wrappers.feature_engineering": mock_tg_wrappers_fe,
        "tradeready_gym.wrappers.normalization": mock_tg_wrappers_norm,
        "tradeready_gym.rewards": mock_rewards,
        "tradeready_gym.rewards.pnl_reward": mock_rewards_pnl,
        "tradeready_gym.rewards.sharpe_reward": mock_rewards_sharpe,
        "tradeready_gym.rewards.sortino_reward": mock_rewards_sortino,
        "tradeready_gym.rewards.drawdown_penalty_reward": mock_rewards_dd,
    }
    # Remember which ones were absent so we only remove those on cleanup
    absent = {k for k in to_inject if k not in sys.modules}
    sys.modules.update(to_inject)

    mocks.update(
        {
            "ppo_cls": mock_ppo_cls,
            "ppo_instance": mock_ppo_instance,
            "callback_list_cls": mock_callback_list,
            "checkpoint_cb_cls": mock_checkpoint_cb,
            "eval_cb_cls": mock_eval_cb,
            "dummy_cls": mock_dummy_cls,
            "dummy_env": mock_dummy_env,
            "subproc_cls": mock_subproc_cls,
            "subproc_env": mock_subproc_env,
            "gym_make": mock_gym.make,
            "fe_cls": mock_fe_cls,
            "fe_env": mock_fe_env,
            "norm_cls": mock_norm_cls,
            "norm_env": mock_norm_env,
            "pnl_reward": mock_pnl_reward,
            "sharpe_reward": mock_sharpe_reward,
            "sortino_reward": mock_sortino_reward,
            "dd_reward": mock_dd_reward,
            "_absent_keys": absent,
        }
    )
    return mocks


def _cleanup_gym_mocks(mocks: dict[str, Any]) -> None:
    """Remove only the sys.modules entries that were injected by _inject_gym_mocks."""
    for key in mocks["_absent_keys"]:
        sys.modules.pop(key, None)
    # Also force-reload the train module so subsequent tests get fresh imports
    sys.modules.pop("agent.strategies.rl.train", None)


# ── TestTrainFunctionExists ────────────────────────────────────────────────────


class TestTrainFunctionExists:
    """train() and related helpers exist and are callable."""

    def test_train_is_importable(self) -> None:
        from agent.strategies.rl.train import train

        assert callable(train)

    def test_env_factory_is_importable(self) -> None:
        from agent.strategies.rl.train import _env_factory

        assert callable(_env_factory)

    def test_build_reward_is_importable(self) -> None:
        from agent.strategies.rl.train import _build_reward

        assert callable(_build_reward)


# ── TestBuildReward ────────────────────────────────────────────────────────────


class TestBuildReward:
    """_build_reward returns the right reward instance for each reward_type."""

    def setup_method(self) -> None:
        self._mocks = _inject_gym_mocks()
        # Force reimport so the module picks up injected stubs
        sys.modules.pop("agent.strategies.rl.train", None)

    def teardown_method(self) -> None:
        _cleanup_gym_mocks(self._mocks)

    def test_pnl_reward_instantiated(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _build_reward

        cfg = _make_config(tmp_path, reward_type="pnl")
        result = _build_reward(cfg)
        self._mocks["pnl_reward"].assert_called_once()
        assert result is self._mocks["pnl_reward"].return_value

    def test_sharpe_reward_instantiated(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _build_reward

        cfg = _make_config(tmp_path, reward_type="sharpe")
        result = _build_reward(cfg)
        self._mocks["sharpe_reward"].assert_called_once()
        assert result is self._mocks["sharpe_reward"].return_value

    def test_sortino_reward_instantiated(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _build_reward

        cfg = _make_config(tmp_path, reward_type="sortino")
        result = _build_reward(cfg)
        self._mocks["sortino_reward"].assert_called_once()
        assert result is self._mocks["sortino_reward"].return_value

    def test_drawdown_reward_instantiated(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _build_reward

        cfg = _make_config(tmp_path, reward_type="drawdown")
        result = _build_reward(cfg)
        self._mocks["dd_reward"].assert_called_once()
        assert result is self._mocks["dd_reward"].return_value

    def test_unknown_reward_type_raises(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _build_reward

        cfg = _make_config(tmp_path, reward_type="unknown_type")
        with pytest.raises(ValueError, match="Unknown reward_type"):
            _build_reward(cfg)

    def test_sharpe_reward_passes_window(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _build_reward

        cfg = _make_config(tmp_path, reward_type="sharpe", sharpe_window=75)
        _build_reward(cfg)
        self._mocks["sharpe_reward"].assert_called_once_with(window=75)


# ── TestEnvFactory ────────────────────────────────────────────────────────────


class TestEnvFactory:
    """_env_factory returns a no-arg callable that produces a wrapped env."""

    def setup_method(self) -> None:
        self._mocks = _inject_gym_mocks()
        sys.modules.pop("agent.strategies.rl.train", None)

    def teardown_method(self) -> None:
        _cleanup_gym_mocks(self._mocks)

    def test_env_factory_returns_callable(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _env_factory

        cfg = _make_config(tmp_path)
        factory = _env_factory(cfg, "2024-01-01T00:00:00Z", "2024-10-01T00:00:00Z")
        assert callable(factory)

    def test_env_factory_calls_gym_make(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _env_factory

        cfg = _make_config(tmp_path, reward_type="sharpe")
        factory = _env_factory(cfg, "2024-01-01T00:00:00Z", "2024-10-01T00:00:00Z")
        env = factory()

        self._mocks["gym_make"].assert_called_once()
        # Final env is the NormalizationWrapper output
        assert env is self._mocks["norm_env"]

    def test_env_factory_applies_feature_engineering_wrapper(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _env_factory

        cfg = _make_config(tmp_path, reward_type="sharpe")
        factory = _env_factory(cfg, "2024-01-01T00:00:00Z", "2024-10-01T00:00:00Z")
        factory()

        # FeatureEngineeringWrapper must have been called
        self._mocks["fe_cls"].assert_called_once()
        # Verify periods=[5,10,20] is in the call args
        call_args = self._mocks["fe_cls"].call_args
        periods_arg = call_args[1].get("periods") or (
            call_args[0][1] if len(call_args[0]) >= 2 else None
        )
        assert periods_arg == [5, 10, 20]

    def test_env_factory_uses_config_symbols(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _env_factory

        cfg = _make_config(tmp_path, env_symbols=["BTCUSDT", "ETHUSDT"])
        factory = _env_factory(cfg, "2024-01-01T00:00:00Z", "2024-10-01T00:00:00Z")
        factory()

        call_kwargs = self._mocks["gym_make"].call_args[1]
        assert call_kwargs.get("symbols") == ["BTCUSDT", "ETHUSDT"]

    def test_env_factory_passes_start_end_times(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _env_factory

        cfg = _make_config(tmp_path)
        start = "2024-01-01T00:00:00Z"
        end = "2024-06-01T00:00:00Z"
        factory = _env_factory(cfg, start, end)
        factory()

        call_kwargs = self._mocks["gym_make"].call_args[1]
        assert call_kwargs.get("start_time") == start
        assert call_kwargs.get("end_time") == end


# ── TestMakeVecEnv ─────────────────────────────────────────────────────────────


class TestMakeVecEnv:
    """_make_vec_env uses DummyVecEnv when n_envs=1, SubprocVecEnv otherwise."""

    def setup_method(self) -> None:
        self._mocks = _inject_gym_mocks()
        sys.modules.pop("agent.strategies.rl.train", None)

    def teardown_method(self) -> None:
        _cleanup_gym_mocks(self._mocks)

    def test_n_envs_1_uses_dummy(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _make_vec_env

        cfg = _make_config(tmp_path, n_envs=1)
        result = _make_vec_env(cfg, "2024-01-01T00:00:00Z", "2024-10-01T00:00:00Z")

        self._mocks["dummy_cls"].assert_called_once()
        assert result is self._mocks["dummy_env"]

    def test_n_envs_gt_1_tries_subproc(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _make_vec_env

        cfg = _make_config(tmp_path, n_envs=2)
        result = _make_vec_env(cfg, "2024-01-01T00:00:00Z", "2024-10-01T00:00:00Z")

        self._mocks["subproc_cls"].assert_called_once()
        assert result is self._mocks["subproc_env"]

    def test_subproc_failure_falls_back_to_dummy(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _make_vec_env

        cfg = _make_config(tmp_path, n_envs=2)
        self._mocks["subproc_cls"].side_effect = OSError("fork not supported")

        result = _make_vec_env(cfg, "2024-01-01T00:00:00Z", "2024-10-01T00:00:00Z")

        self._mocks["dummy_cls"].assert_called_once()
        assert result is self._mocks["dummy_env"]

    def test_vec_env_factory_count_matches_n_envs(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import _make_vec_env

        cfg = _make_config(tmp_path, n_envs=3)
        captured_factories: list[Any] = []

        def _capture(factories: list[Any]) -> MagicMock:
            captured_factories.extend(factories)
            return MagicMock()

        self._mocks["subproc_cls"].side_effect = _capture
        _make_vec_env(cfg, "2024-01-01T00:00:00Z", "2024-10-01T00:00:00Z")

        assert len(captured_factories) == 3


# ── TestCheckpointNaming ──────────────────────────────────────────────────────


class TestCheckpointNaming:
    """Saved model filename follows the convention ppo_portfolio_final.zip."""

    def setup_method(self) -> None:
        self._mocks = _inject_gym_mocks()
        sys.modules.pop("agent.strategies.rl.train", None)

    def teardown_method(self) -> None:
        _cleanup_gym_mocks(self._mocks)

    def test_train_saves_to_models_dir(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import train

        cfg = _make_config(tmp_path)
        saved = train(cfg)

        assert str(saved).endswith(".zip")
        assert str(cfg.models_dir) in str(saved)

    def test_train_final_model_name_prefix(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import train

        cfg = _make_config(tmp_path)
        saved = train(cfg)

        assert "ppo_portfolio_final" in str(saved)

    def test_train_checkpoint_prefix_is_ppo_portfolio(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import train

        cfg = _make_config(tmp_path)
        captured: dict[str, Any] = {}

        original_checkpoint_cls = self._mocks["checkpoint_cb_cls"]

        def _capture(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock()

        original_checkpoint_cls.side_effect = _capture
        train(cfg)

        assert captured.get("name_prefix") == "ppo_portfolio"

    def test_train_returns_path_object(self, tmp_path: Path) -> None:
        from agent.strategies.rl.train import train

        cfg = _make_config(tmp_path)
        result = train(cfg)

        assert isinstance(result, Path)


# ── TestEvaluationReport ──────────────────────────────────────────────────────


class TestEvaluationReport:
    """EvaluationReport and StrategyMetrics are valid Pydantic models."""

    def test_strategy_metrics_valid_construction(self) -> None:
        from agent.strategies.rl.evaluate import StrategyMetrics

        m = StrategyMetrics(name="ppo_seed42", is_benchmark=False)
        assert m.name == "ppo_seed42"
        assert m.is_benchmark is False

    def test_strategy_metrics_is_frozen(self) -> None:
        from agent.strategies.rl.evaluate import StrategyMetrics

        m = StrategyMetrics(name="ppo_seed42")
        with pytest.raises(Exception):
            m.name = "changed"  # type: ignore[misc]

    def test_strategy_metrics_optional_fields_default_none(self) -> None:
        from agent.strategies.rl.evaluate import StrategyMetrics

        m = StrategyMetrics(name="benchmark")
        assert m.sharpe_ratio is None
        assert m.roi_pct is None
        assert m.win_rate is None
        assert m.error is None

    def test_evaluation_report_valid_construction(self) -> None:
        from agent.strategies.rl.evaluate import EvaluationReport, StrategyMetrics

        report = EvaluationReport(
            timestamp="2025-01-01T00:00:00Z",
            test_start="2024-12-01T00:00:00Z",
            test_end="2025-01-01T00:00:00Z",
            symbols=["BTCUSDT", "ETHUSDT"],
            starting_balance="10000",
            strategies=[StrategyMetrics(name="ppo_seed42")],
            total_wall_time_sec=30.0,
        )
        assert report.best_strategy is None
        assert report.ensemble is None
        assert len(report.strategies) == 1

    def test_evaluation_report_is_frozen(self) -> None:
        from agent.strategies.rl.evaluate import EvaluationReport

        report = EvaluationReport(
            timestamp="2025-01-01T00:00:00Z",
            test_start="2024-12-01T00:00:00Z",
            test_end="2025-01-01T00:00:00Z",
            symbols=["BTCUSDT"],
            starting_balance="10000",
            strategies=[],
            total_wall_time_sec=1.0,
        )
        with pytest.raises(Exception):
            report.best_strategy = "changed"  # type: ignore[misc]

    def test_evaluation_report_json_round_trip(self) -> None:
        from agent.strategies.rl.evaluate import EvaluationReport, StrategyMetrics

        report = EvaluationReport(
            timestamp="2025-01-01T00:00:00Z",
            test_start="2024-12-01T00:00:00Z",
            test_end="2025-01-01T00:00:00Z",
            symbols=["BTCUSDT"],
            starting_balance="10000",
            strategies=[StrategyMetrics(name="ppo_seed42", sharpe_ratio=1.2)],
            total_wall_time_sec=5.5,
        )
        restored = EvaluationReport.model_validate_json(report.model_dump_json())
        assert restored == report


# ── TestComputeMetrics ─────────────────────────────────────────────────────────


class TestComputeMetrics:
    """_compute_metrics produces correct Sharpe, ROI, drawdown, and win rate."""

    def test_positive_roi(self) -> None:
        from agent.strategies.rl.evaluate import _compute_metrics

        equity = [10_000.0, 10_500.0, 11_000.0]
        m = _compute_metrics(equity, 2, 1.5, 10_000.0, "test")
        assert m.roi_pct is not None
        assert m.roi_pct > 0

    def test_negative_roi(self) -> None:
        from agent.strategies.rl.evaluate import _compute_metrics

        equity = [10_000.0, 9_500.0, 9_000.0]
        m = _compute_metrics(equity, 0, 0.0, 10_000.0, "test")
        assert m.roi_pct is not None
        assert m.roi_pct < 0

    def test_max_drawdown_zero_on_monotone_increase(self) -> None:
        from agent.strategies.rl.evaluate import _compute_metrics

        equity = [10_000.0, 10_500.0, 11_000.0, 11_500.0]
        m = _compute_metrics(equity, 0, 0.0, 10_000.0, "test")
        assert m.max_drawdown_pct == 0.0

    def test_max_drawdown_positive_on_decline(self) -> None:
        from agent.strategies.rl.evaluate import _compute_metrics

        equity = [10_000.0, 12_000.0, 9_000.0]  # peak=12000, trough=9000 → dd=25%
        m = _compute_metrics(equity, 0, 0.0, 10_000.0, "test")
        assert m.max_drawdown_pct is not None
        assert m.max_drawdown_pct > 0

    def test_win_rate_all_wins(self) -> None:
        from agent.strategies.rl.evaluate import _compute_metrics

        equity = [10_000.0, 10_100.0, 10_200.0, 10_300.0]
        m = _compute_metrics(equity, 0, 0.0, 10_000.0, "test")
        assert m.win_rate == 1.0

    def test_error_returns_minimal_metrics(self) -> None:
        from agent.strategies.rl.evaluate import _compute_metrics

        m = _compute_metrics([], 0, 0.0, 10_000.0, "test", error="crash")
        assert m.error == "crash"
        assert m.sharpe_ratio is None
        assert m.roi_pct is None

    def test_is_benchmark_flag_propagated(self) -> None:
        from agent.strategies.rl.evaluate import _compute_metrics

        m = _compute_metrics(
            [10_000.0, 10_500.0], 0, 0.0, 10_000.0, "equal_weight", is_benchmark=True
        )
        assert m.is_benchmark is True
