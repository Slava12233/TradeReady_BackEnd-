"""Unit tests for agent.strategies.rl.runner.

All platform API calls, SB3 imports, and filesystem writes are mocked.
No running platform, SB3 installation, or .env file is required.

Test counts:
  TestSeedMetrics          — 7
  TestMultiSeedComparison  — 6
  TestConvergenceMonitor   — 8
  TestTuneConfig           — 5
  TestTrainingRunnerValidate — 4
  TestTrainingRunnerBuild  — 4
  TestTrainingRunnerSave   — 3
  TestParseSeeds           — 4
  TestCLIArgParsing        — 5

Total: 46
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.strategies.rl.runner import (
    MultiSeedComparison,
    SeedMetrics,
    TrainingRunner,
    _ConvergenceMonitor,
    _parse_seeds,
    _tune_config,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_config(tmp_path: Path, **overrides: Any) -> MagicMock:
    """Return a MagicMock that behaves like an RLConfig."""
    cfg = MagicMock()
    cfg.platform_base_url = "http://localhost:8000"
    cfg.platform_api_key = "ak_live_test"
    cfg.env_symbols = ["BTCUSDT", "ETHUSDT"]
    cfg.timeframe = "1h"
    cfg.total_timesteps = 1000
    cfg.n_envs = 1
    cfg.eval_freq = 200
    cfg.test_start = "2024-12-01T00:00:00Z"
    cfg.test_end = "2025-01-01T00:00:00Z"
    cfg.models_dir = tmp_path / "models"
    cfg.models_dir.mkdir(parents=True, exist_ok=True)
    cfg.model_copy.side_effect = lambda **kw: cfg  # return same mock on copy
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _seed_metrics(seed: int = 42, **overrides: Any) -> SeedMetrics:
    """Build a SeedMetrics with sensible defaults."""
    fields = {
        "seed": seed,
        "model_path": f"/models/ppo_seed{seed}.zip",
        "sharpe_ratio": 1.2,
        "roi_pct": 5.0,
        "max_drawdown_pct": 8.0,
        "win_rate": 0.55,
        "total_timesteps": 500_000,
        "training_wall_time_sec": 3600.0,
        "converged": True,
        "final_eval_reward": 15.0,
        "tuned": False,
        "error": None,
    }
    fields.update(overrides)
    return SeedMetrics(**fields)


# ── SeedMetrics ───────────────────────────────────────────────────────────────


class TestSeedMetrics:
    def test_valid_construction(self) -> None:
        m = _seed_metrics()
        assert m.seed == 42
        assert m.sharpe_ratio == 1.2

    def test_model_is_frozen(self) -> None:
        m = _seed_metrics()
        with pytest.raises(Exception):
            m.seed = 99  # type: ignore[misc]

    def test_optional_fields_default_none(self) -> None:
        m = SeedMetrics(
            seed=1,
            model_path="/models/ppo_seed1.zip",
            total_timesteps=100,
            training_wall_time_sec=10.0,
            converged=False,
        )
        assert m.sharpe_ratio is None
        assert m.roi_pct is None
        assert m.win_rate is None
        assert m.error is None

    def test_with_error(self) -> None:
        m = _seed_metrics(error="ConnectionRefusedError")
        assert m.error == "ConnectionRefusedError"
        assert m.converged is True  # convergence field is independent

    def test_json_round_trip(self) -> None:
        m = _seed_metrics()
        restored = SeedMetrics.model_validate_json(m.model_dump_json())
        assert restored == m

    def test_tuned_default_false(self) -> None:
        m = _seed_metrics()
        assert m.tuned is False

    def test_zero_timesteps_allowed(self) -> None:
        m = SeedMetrics(
            seed=0,
            model_path="/eval.zip",
            total_timesteps=0,
            training_wall_time_sec=0.0,
            converged=True,
        )
        assert m.total_timesteps == 0


# ── MultiSeedComparison ───────────────────────────────────────────────────────


class TestMultiSeedComparison:
    def _make(self, **overrides: Any) -> MultiSeedComparison:
        fields = {
            "seeds": [_seed_metrics(42), _seed_metrics(123, sharpe_ratio=0.8)],
            "best_seed": 42,
            "best_model_path": "/models/ppo_seed42.zip",
            "mean_sharpe": 1.0,
            "mean_roi_pct": 4.5,
            "target_sharpe_met": True,
            "total_wall_time_sec": 7200.0,
            "tuning_applied": False,
        }
        fields.update(overrides)
        return MultiSeedComparison(**fields)

    def test_valid_construction(self) -> None:
        c = self._make()
        assert c.best_seed == 42
        assert c.target_sharpe_met is True

    def test_frozen(self) -> None:
        c = self._make()
        with pytest.raises(Exception):
            c.best_seed = 999  # type: ignore[misc]

    def test_none_best_seed_allowed(self) -> None:
        c = self._make(best_seed=None, best_model_path=None)
        assert c.best_seed is None

    def test_json_round_trip(self) -> None:
        c = self._make()
        restored = MultiSeedComparison.model_validate_json(c.model_dump_json())
        assert restored == c

    def test_empty_seeds_list(self) -> None:
        c = self._make(seeds=[], best_seed=None, best_model_path=None)
        assert c.seeds == []

    def test_tuning_applied_flag(self) -> None:
        c = self._make(tuning_applied=True)
        assert c.tuning_applied is True


# ── ConvergenceMonitor ────────────────────────────────────────────────────────


class TestConvergenceMonitor:
    def test_no_plateau_on_improvement(self) -> None:
        mon = _ConvergenceMonitor(patience=3, min_delta=0.01)
        for r in [1.0, 1.5, 2.0, 3.0]:
            plateau = mon.record(r)
        assert not plateau
        assert mon.converged

    def test_plateau_detected_after_patience(self) -> None:
        mon = _ConvergenceMonitor(patience=3, min_delta=0.01)
        mon.record(1.0)       # sets best to 1.0
        mon.record(1.0)       # +1 plateau
        mon.record(1.0)       # +2 plateau
        plateau = mon.record(1.0)  # +3 plateau — triggers
        assert plateau
        assert not mon.converged

    def test_plateau_reset_on_improvement(self) -> None:
        mon = _ConvergenceMonitor(patience=3, min_delta=0.01)
        mon.record(1.0)
        mon.record(1.0)  # count = 2
        plateau = mon.record(2.0)  # improvement resets counter
        assert not plateau

    def test_history_accumulated(self) -> None:
        mon = _ConvergenceMonitor(patience=5)
        for r in [1.0, 1.1, 1.2]:
            mon.record(r)
        assert mon.history == [1.0, 1.1, 1.2]

    def test_min_delta_threshold(self) -> None:
        mon = _ConvergenceMonitor(patience=2, min_delta=0.1)
        mon.record(1.0)
        # Improvement is only 0.05 — below min_delta
        mon.record(1.05)
        plateau = mon.record(1.05)
        assert plateau  # patience=2 reached

    def test_initial_state_not_converged(self) -> None:
        mon = _ConvergenceMonitor(patience=3)
        assert mon.converged  # no plateau recorded yet

    def test_empty_history(self) -> None:
        mon = _ConvergenceMonitor()
        assert mon.history == []

    def test_large_patience_never_plateaus(self) -> None:
        mon = _ConvergenceMonitor(patience=100, min_delta=0.0)
        for r in [1.0] * 50:
            plateau = mon.record(r)
        assert not plateau


# ── TuneConfig ────────────────────────────────────────────────────────────────


class TestTuneConfig:
    def _base(self) -> MagicMock:
        cfg = MagicMock()
        cfg.ent_coef = 0.01
        cfg.learning_rate = 3e-4
        cfg.total_timesteps = 500_000
        # model_copy should return a new mock with the same values + overrides.
        def _copy(**kw: Any) -> MagicMock:
            new = MagicMock()
            new.ent_coef = kw.get("update", {}).get("ent_coef", cfg.ent_coef)
            new.learning_rate = kw.get("update", {}).get("learning_rate", cfg.learning_rate)
            new.total_timesteps = kw.get("update", {}).get("total_timesteps", cfg.total_timesteps)
            return new

        cfg.model_copy.side_effect = _copy
        return cfg

    def test_attempt_1_raises_ent_coef(self) -> None:
        cfg = self._base()
        result = _tune_config(cfg, attempt=1)
        assert result.ent_coef == 0.05

    def test_attempt_2_lowers_lr(self) -> None:
        cfg = self._base()
        result = _tune_config(cfg, attempt=2)
        assert result.learning_rate == 1e-4

    def test_attempt_3_increases_timesteps(self) -> None:
        cfg = self._base()
        result = _tune_config(cfg, attempt=3)
        assert result.total_timesteps == int(500_000 * 1.5)

    def test_attempt_4_applies_all(self) -> None:
        cfg = self._base()
        result = _tune_config(cfg, attempt=4)
        assert result.ent_coef == 0.05
        assert result.learning_rate == 1e-4
        assert result.total_timesteps == int(500_000 * 1.5)

    def test_attempt_0_no_changes(self) -> None:
        cfg = self._base()
        result = _tune_config(cfg, attempt=0)
        # attempt=0 triggers no update block
        assert result.ent_coef == cfg.ent_coef


# ── TrainingRunner.validate_data ──────────────────────────────────────────────


class TestTrainingRunnerValidate:
    def test_validate_ok_returns_true(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        runner = TrainingRunner(config=config)

        mock_report = MagicMock()
        mock_report.unready_assets = []
        mock_report.ready_assets = ["BTCUSDT", "ETHUSDT"]
        mock_report.model_dump_json.return_value = '{"status": "ok"}'

        with patch(
            "agent.strategies.rl.runner.asyncio.run", return_value=mock_report
        ):
            result = runner.validate_data()

        assert result is True

    def test_validate_unready_returns_false(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        runner = TrainingRunner(config=config)

        mock_report = MagicMock()
        mock_report.unready_assets = ["SOLUSDT"]
        mock_report.ready_assets = []
        mock_report.model_dump_json.return_value = '{"status": "insufficient_data"}'

        with patch(
            "agent.strategies.rl.runner.asyncio.run", return_value=mock_report
        ):
            result = runner.validate_data()

        assert result is False

    def test_validate_exception_returns_false(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        runner = TrainingRunner(config=config)

        with patch(
            "agent.strategies.rl.runner.asyncio.run",
            side_effect=ConnectionRefusedError("platform unreachable"),
        ):
            result = runner.validate_data()

        assert result is False

    def test_validate_writes_report_file(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        runner = TrainingRunner(config=config)

        mock_report = MagicMock()
        mock_report.unready_assets = []
        mock_report.ready_assets = ["BTCUSDT"]
        mock_report.model_dump_json.return_value = '{"status": "ok"}'

        with patch(
            "agent.strategies.rl.runner.asyncio.run", return_value=mock_report
        ):
            runner.validate_data()

        report_file = runner._results_dir / "data_readiness.json"
        assert report_file.exists()
        assert "ok" in report_file.read_text()


# ── TrainingRunner._build_comparison ─────────────────────────────────────────


class TestTrainingRunnerBuild:
    def _runner(self, tmp_path: Path) -> TrainingRunner:
        config = _make_config(tmp_path)
        return TrainingRunner(config=config, target_sharpe=1.0)

    def test_best_seed_is_highest_sharpe(self, tmp_path: Path) -> None:
        runner = self._runner(tmp_path)
        m1 = _seed_metrics(42, sharpe_ratio=0.8)
        m2 = _seed_metrics(123, sharpe_ratio=1.5)
        m3 = _seed_metrics(456, sharpe_ratio=1.1)
        comparison = runner._build_comparison([m1, m2, m3], 100.0)
        assert comparison.best_seed == 123

    def test_target_met_when_any_exceeds(self, tmp_path: Path) -> None:
        runner = self._runner(tmp_path)
        m1 = _seed_metrics(42, sharpe_ratio=0.5)
        m2 = _seed_metrics(123, sharpe_ratio=1.2)
        comparison = runner._build_comparison([m1, m2], 50.0)
        assert comparison.target_sharpe_met is True

    def test_target_not_met_when_all_below(self, tmp_path: Path) -> None:
        runner = self._runner(tmp_path)
        m1 = _seed_metrics(42, sharpe_ratio=0.5)
        m2 = _seed_metrics(123, sharpe_ratio=0.7)
        comparison = runner._build_comparison([m1, m2], 50.0)
        assert comparison.target_sharpe_met is False

    def test_all_failed_seeds(self, tmp_path: Path) -> None:
        runner = self._runner(tmp_path)
        m1 = _seed_metrics(42, error="crash", sharpe_ratio=None)
        comparison = runner._build_comparison([m1], 10.0)
        assert comparison.best_seed is None
        assert comparison.mean_sharpe is None


# ── TrainingRunner save helpers ───────────────────────────────────────────────


class TestTrainingRunnerSave:
    def _runner(self, tmp_path: Path) -> TrainingRunner:
        config = _make_config(tmp_path)
        return TrainingRunner(config=config)

    def test_save_training_log_creates_file(self, tmp_path: Path) -> None:
        runner = self._runner(tmp_path)
        metrics = [_seed_metrics(42), _seed_metrics(123)]
        runner._save_training_log(metrics)
        log_file = runner._results_dir / "training_log.json"
        assert log_file.exists()
        data = json.loads(log_file.read_text())
        assert len(data) == 2
        assert data[0]["seed"] == 42

    def test_save_comparison_creates_file(self, tmp_path: Path) -> None:
        runner = self._runner(tmp_path)
        comparison = MultiSeedComparison(
            seeds=[_seed_metrics(42)],
            best_seed=42,
            best_model_path="/models/ppo_seed42.zip",
            mean_sharpe=1.2,
            mean_roi_pct=5.0,
            target_sharpe_met=True,
            total_wall_time_sec=3600.0,
            tuning_applied=False,
        )
        runner._save_comparison(comparison)
        comp_file = runner._results_dir / "comparison.json"
        assert comp_file.exists()
        data = json.loads(comp_file.read_text())
        assert data["best_seed"] == 42

    def test_training_log_overwrites_on_second_call(self, tmp_path: Path) -> None:
        runner = self._runner(tmp_path)
        runner._save_training_log([_seed_metrics(42)])
        runner._save_training_log([_seed_metrics(42), _seed_metrics(123)])
        log_file = runner._results_dir / "training_log.json"
        data = json.loads(log_file.read_text())
        assert len(data) == 2


# ── _parse_seeds ──────────────────────────────────────────────────────────────


class TestParseSeeds:
    def test_single_seed(self) -> None:
        assert _parse_seeds("42") == [42]

    def test_multiple_seeds(self) -> None:
        assert _parse_seeds("42,123,456") == [42, 123, 456]

    def test_spaces_ignored(self) -> None:
        assert _parse_seeds("42, 123, 456") == [42, 123, 456]

    def test_invalid_raises(self) -> None:
        import argparse
        with pytest.raises(argparse.ArgumentTypeError):
            _parse_seeds("42,abc,456")


# ── CLI argument parsing (smoke) ──────────────────────────────────────────────


class TestCLIArgParsing:
    def _parse(self, *argv: str) -> Any:
        from agent.strategies.rl.runner import _build_parser
        return _build_parser().parse_args(list(argv))

    def test_default_seeds(self) -> None:
        args = self._parse()
        assert args.seeds == [42, 123, 456]

    def test_custom_seeds(self) -> None:
        args = self._parse("--seeds", "1,2,3")
        assert args.seeds == [1, 2, 3]

    def test_no_validate_flag(self) -> None:
        args = self._parse("--no-validate")
        assert args.no_validate is True

    def test_tune_flag(self) -> None:
        args = self._parse("--tune")
        assert args.tune is True

    def test_evaluate_mode(self) -> None:
        args = self._parse("--evaluate", "/models/ppo_seed42.zip")
        assert args.evaluate == "/models/ppo_seed42.zip"
