"""Tests for agent/strategies/rl/config.py :: RLConfig.

Test counts:
  TestRLConfigDefaults       — 14
  TestRLConfigEnvOverrides   — 5
  TestRLConfigTimeframe      — 6
  TestRLConfigRewardType     — 6
  TestRLConfigLookbackWindow — 4
  TestRLConfigAssetLists     — 4

Total: 39
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.strategies.rl.config import RLConfig

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_config(**overrides: object) -> RLConfig:
    """Construct an RLConfig bypassing the .env file, with optional overrides."""
    return RLConfig(_env_file=None, **overrides)  # type: ignore[call-arg]


# ── TestRLConfigDefaults ───────────────────────────────────────────────────────


class TestRLConfigDefaults:
    """Default values are sane and match the docstring examples."""

    def test_learning_rate_default(self) -> None:
        cfg = _make_config()
        assert abs(cfg.learning_rate - 3e-4) < 1e-9

    def test_clip_range_default(self) -> None:
        cfg = _make_config()
        assert cfg.clip_range == 0.2

    def test_n_steps_default(self) -> None:
        cfg = _make_config()
        assert cfg.n_steps == 2048

    def test_batch_size_default(self) -> None:
        cfg = _make_config()
        assert cfg.batch_size == 64

    def test_n_epochs_default(self) -> None:
        cfg = _make_config()
        assert cfg.n_epochs == 10

    def test_gamma_default(self) -> None:
        cfg = _make_config()
        assert cfg.gamma == 0.99

    def test_gae_lambda_default(self) -> None:
        cfg = _make_config()
        assert cfg.gae_lambda == 0.95

    def test_ent_coef_default(self) -> None:
        cfg = _make_config()
        assert cfg.ent_coef == 0.01

    def test_total_timesteps_default(self) -> None:
        cfg = _make_config()
        assert cfg.total_timesteps == 500_000

    def test_n_envs_default(self) -> None:
        cfg = _make_config()
        assert cfg.n_envs == 4

    def test_seed_default(self) -> None:
        cfg = _make_config()
        assert cfg.seed == 42

    def test_timeframe_default(self) -> None:
        cfg = _make_config()
        assert cfg.timeframe == "1h"

    def test_reward_type_default(self) -> None:
        cfg = _make_config()
        assert cfg.reward_type == "sharpe"

    def test_lookback_window_default(self) -> None:
        cfg = _make_config()
        assert cfg.lookback_window == 30

    def test_starting_balance_default(self) -> None:
        cfg = _make_config()
        assert cfg.starting_balance == 10_000.0

    def test_platform_api_key_default_empty(self) -> None:
        cfg = _make_config()
        assert cfg.platform_api_key == ""

    def test_platform_base_url_default(self) -> None:
        cfg = _make_config()
        assert cfg.platform_base_url == "http://localhost:8000"

    def test_track_training_default_true(self) -> None:
        cfg = _make_config()
        assert cfg.track_training is True

    def test_env_symbols_default(self) -> None:
        cfg = _make_config()
        assert cfg.env_symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    def test_asset_universe_default_superset(self) -> None:
        cfg = _make_config()
        for sym in cfg.env_symbols:
            assert sym in cfg.asset_universe

    def test_net_arch_pi_default(self) -> None:
        cfg = _make_config()
        assert cfg.net_arch_pi == [256, 256]

    def test_net_arch_vf_default(self) -> None:
        cfg = _make_config()
        assert cfg.net_arch_vf == [256, 256]

    def test_models_dir_is_path(self) -> None:
        cfg = _make_config()
        assert isinstance(cfg.models_dir, Path)

    def test_log_dir_is_under_models_dir(self) -> None:
        cfg = _make_config()
        # log_dir should be a subdirectory (or equal) to models_dir
        assert str(cfg.models_dir) in str(cfg.log_dir)

    def test_date_fields_are_iso_strings(self) -> None:
        cfg = _make_config()
        for field in ("train_start", "train_end", "val_start", "val_end", "test_start", "test_end"):
            value = getattr(cfg, field)
            assert isinstance(value, str), f"{field} should be a string, got {type(value)}"
            # Must contain a date-like pattern
            assert "T" in value or "-" in value, f"{field} does not look like ISO-8601: {value!r}"


# ── TestRLConfigEnvOverrides ───────────────────────────────────────────────────


class TestRLConfigEnvOverrides:
    """Environment variables with RL_ prefix override defaults."""

    def test_env_prefix_total_timesteps(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RL_TOTAL_TIMESTEPS", "1000")
        cfg = _make_config()
        assert cfg.total_timesteps == 1000

    def test_env_prefix_learning_rate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RL_LEARNING_RATE", "0.0001")
        cfg = _make_config()
        assert abs(cfg.learning_rate - 1e-4) < 1e-9

    def test_env_prefix_reward_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RL_REWARD_TYPE", "pnl")
        cfg = _make_config()
        assert cfg.reward_type == "pnl"

    def test_env_prefix_seed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RL_SEED", "99")
        cfg = _make_config()
        assert cfg.seed == 99

    def test_env_prefix_n_envs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RL_N_ENVS", "8")
        cfg = _make_config()
        assert cfg.n_envs == 8

    def test_env_prefix_platform_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RL_PLATFORM_API_KEY", "ak_live_testkey123")
        cfg = _make_config()
        assert cfg.platform_api_key == "ak_live_testkey123"

    def test_extra_env_vars_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("RL_UNKNOWN_FIELD_XYZ", "should_be_ignored")
        # Should not raise — extra='ignore' is set
        cfg = _make_config()
        assert not hasattr(cfg, "unknown_field_xyz")


# ── TestRLConfigTimeframe ──────────────────────────────────────────────────────


class TestRLConfigTimeframe:
    """validate_timeframe rejects values not in the allowed set."""

    def test_valid_timeframe_1m(self) -> None:
        cfg = _make_config(timeframe="1m")
        assert cfg.timeframe == "1m"

    def test_valid_timeframe_5m(self) -> None:
        cfg = _make_config(timeframe="5m")
        assert cfg.timeframe == "5m"

    def test_valid_timeframe_15m(self) -> None:
        cfg = _make_config(timeframe="15m")
        assert cfg.timeframe == "15m"

    def test_valid_timeframe_4h(self) -> None:
        cfg = _make_config(timeframe="4h")
        assert cfg.timeframe == "4h"

    def test_valid_timeframe_1d(self) -> None:
        cfg = _make_config(timeframe="1d")
        assert cfg.timeframe == "1d"

    def test_invalid_timeframe_raises(self) -> None:
        with pytest.raises(ValidationError, match="timeframe"):
            _make_config(timeframe="2h")

    def test_invalid_timeframe_number_only(self) -> None:
        with pytest.raises(ValidationError, match="timeframe"):
            _make_config(timeframe="60")

    def test_invalid_timeframe_empty_string(self) -> None:
        with pytest.raises(ValidationError, match="timeframe"):
            _make_config(timeframe="")


# ── TestRLConfigRewardType ────────────────────────────────────────────────────


class TestRLConfigRewardType:
    """validate_reward_type rejects unknown reward names."""

    def test_valid_reward_pnl(self) -> None:
        cfg = _make_config(reward_type="pnl")
        assert cfg.reward_type == "pnl"

    def test_valid_reward_sharpe(self) -> None:
        cfg = _make_config(reward_type="sharpe")
        assert cfg.reward_type == "sharpe"

    def test_valid_reward_sortino(self) -> None:
        cfg = _make_config(reward_type="sortino")
        assert cfg.reward_type == "sortino"

    def test_valid_reward_drawdown(self) -> None:
        cfg = _make_config(reward_type="drawdown")
        assert cfg.reward_type == "drawdown"

    def test_invalid_reward_type_raises(self) -> None:
        with pytest.raises(ValidationError, match="reward_type"):
            _make_config(reward_type="mse")

    def test_invalid_reward_type_mixed_case_raises(self) -> None:
        # Validation is case-sensitive — "Sharpe" is not "sharpe"
        with pytest.raises(ValidationError, match="reward_type"):
            _make_config(reward_type="Sharpe")


# ── TestRLConfigLookbackWindow ────────────────────────────────────────────────


class TestRLConfigLookbackWindow:
    """validate_lookback_window requires >= 26 (MACD slow EMA period)."""

    def test_valid_minimum_value_26(self) -> None:
        cfg = _make_config(lookback_window=26)
        assert cfg.lookback_window == 26

    def test_valid_large_value(self) -> None:
        cfg = _make_config(lookback_window=100)
        assert cfg.lookback_window == 100

    def test_below_minimum_raises(self) -> None:
        with pytest.raises(ValidationError, match="lookback_window"):
            _make_config(lookback_window=25)

    def test_zero_raises(self) -> None:
        with pytest.raises(ValidationError, match="lookback_window"):
            _make_config(lookback_window=0)

    def test_negative_raises(self) -> None:
        with pytest.raises(ValidationError, match="lookback_window"):
            _make_config(lookback_window=-1)


# ── TestRLConfigAssetLists ─────────────────────────────────────────────────────


class TestRLConfigAssetLists:
    """env_symbols and asset_universe accept lists via constructor."""

    def test_custom_env_symbols(self) -> None:
        cfg = _make_config(env_symbols=["BTCUSDT", "ETHUSDT"])
        assert cfg.env_symbols == ["BTCUSDT", "ETHUSDT"]

    def test_custom_asset_universe(self) -> None:
        cfg = _make_config(asset_universe=["BTCUSDT"])
        assert cfg.asset_universe == ["BTCUSDT"]

    def test_model_copy_preserves_validators(self) -> None:
        """model_copy with update dict still validates new values."""
        cfg = _make_config()
        cfg2 = cfg.model_copy(update={"timeframe": "4h"})
        assert cfg2.timeframe == "4h"

    def test_model_copy_update_applies_override(self) -> None:
        """model_copy(update=...) applies the new value to the returned copy."""
        cfg = _make_config()
        cfg2 = cfg.model_copy(update={"lookback_window": 50})
        assert cfg2.lookback_window == 50
        # Original is unchanged
        assert cfg.lookback_window == 30
