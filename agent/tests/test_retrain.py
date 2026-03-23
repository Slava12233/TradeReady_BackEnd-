"""Unit tests for RetrainOrchestrator.

All platform API calls, model training, and file I/O are mocked — no running
platform, SB3, xgboost, or trained model files are required.

Test coverage:
  - RetrainConfig field defaults and validation
  - ModelComparison construction and deploy gate logic
  - RetrainResult serialisation (to_log_dict)
  - Schedule helpers (_hours_since, _rolling_window_dates, _backtest_window)
  - run_scheduled_cycle: nothing-due, partial-due, all-due
  - retrain_ensemble: deploy on improvement, skip on none, first-run deploy
  - retrain_regime: deploy on accuracy improvement, skip on regression
  - retrain_genome: deploy on fitness improvement, skip on regression
  - retrain_rl: deploy on Sharpe improvement, skip on regression
  - Failure paths: exceptions are caught, result.success=False
  - _build_comparison: no-incumbent always deploys, threshold gate
  - _record_result: appended to audit_log
  - _failure_result: correct field values
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.strategies.retrain import (
    ModelComparison,
    RetrainConfig,
    RetrainOrchestrator,
    RetrainResult,
    ScheduleState,
    _backtest_window,
    _hours_since,
    _rolling_window_dates,
    _utc_now_iso,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────


def _make_config(tmp_path: Path, **kwargs: object) -> RetrainConfig:
    """Return a RetrainConfig with results_dir under tmp_path."""
    return RetrainConfig(
        results_dir=tmp_path / "retrain_results",
        platform_api_key="ak_live_test",
        **kwargs,
    )


def _make_orchestrator(
    config: RetrainConfig,
    *,
    rest_client: object | None = None,
    sdk_client: object | None = None,
    rl_trainer: object | None = None,
    genome_evolver: object | None = None,
    regime_trainer: object | None = None,
    ensemble_optimizer: object | None = None,
) -> RetrainOrchestrator:
    return RetrainOrchestrator(
        config=config,
        rest_client=rest_client,
        sdk_client=sdk_client,
        rl_trainer=rl_trainer,
        genome_evolver=genome_evolver,
        regime_trainer=regime_trainer,
        ensemble_optimizer=ensemble_optimizer,
    )


# ── RetrainConfig tests ────────────────────────────────────────────────────────


class TestRetrainConfig:
    def test_defaults(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        assert config.ensemble_retrain_interval_hours == 8.0
        assert config.regime_retrain_interval_days == 7.0
        assert config.genome_retrain_interval_days == 7.0
        assert config.rl_retrain_interval_days == 30.0
        assert config.min_improvement == 0.01
        assert config.backtest_days == 30
        assert config.rl_training_window_months == 6
        assert config.genome_refresh_generations == 2

    def test_results_dir_created(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        orc = _make_orchestrator(config)
        assert config.results_dir.exists()

    def test_min_improvement_zero_allowed(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, min_improvement=0.0)
        assert config.min_improvement == 0.0

    def test_backtest_days_minimum(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, backtest_days=7)
        assert config.backtest_days == 7

    def test_custom_intervals(self, tmp_path: Path) -> None:
        config = _make_config(
            tmp_path,
            ensemble_retrain_interval_hours=4.0,
            rl_retrain_interval_days=14.0,
        )
        assert config.ensemble_retrain_interval_hours == 4.0
        assert config.rl_retrain_interval_days == 14.0


# ── Helper function tests ──────────────────────────────────────────────────────


class TestHelpers:
    def test_hours_since_none(self) -> None:
        """None timestamp returns infinity."""
        assert _hours_since(None) == float("inf")

    def test_hours_since_recent(self) -> None:
        """Timestamp 30 minutes ago returns < 1 hour."""
        ts = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
        assert _hours_since(ts) < 1.0

    def test_hours_since_old(self) -> None:
        """Timestamp 25 hours ago returns > 24 hours."""
        ts = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        assert _hours_since(ts) > 24.0

    def test_rolling_window_dates_returns_iso_strings(self) -> None:
        start, end = _rolling_window_dates(6)
        # Both must parse as valid ISO-8601 UTC datetimes
        datetime.fromisoformat(start.replace("Z", "+00:00"))
        datetime.fromisoformat(end.replace("Z", "+00:00"))

    def test_rolling_window_dates_start_before_end(self) -> None:
        start, end = _rolling_window_dates(3)
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        assert start_dt < end_dt

    def test_rolling_window_dates_roughly_correct_span(self) -> None:
        start, end = _rolling_window_dates(6)
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        delta_days = (end_dt - start_dt).days
        # Should be approximately 6*30 = 180 days (±5 days tolerance)
        assert 170 <= delta_days <= 190

    def test_backtest_window_returns_iso_strings(self) -> None:
        start, end = _backtest_window(30)
        datetime.fromisoformat(start.replace("Z", "+00:00"))
        datetime.fromisoformat(end.replace("Z", "+00:00"))

    def test_backtest_window_start_before_end(self) -> None:
        start, end = _backtest_window(14)
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        assert start_dt < end_dt

    def test_utc_now_iso_is_parseable(self) -> None:
        ts = _utc_now_iso()
        dt = datetime.fromisoformat(ts)
        assert dt.tzinfo is not None


# ── ModelComparison tests ──────────────────────────────────────────────────────


class TestModelComparison:
    def test_fields(self) -> None:
        cmp = ModelComparison(
            component="rl",
            incumbent_score=1.2,
            candidate_score=1.35,
            improvement=0.15,
            deploy=True,
            metric_name="sharpe_ratio",
        )
        assert cmp.component == "rl"
        assert cmp.improvement == pytest.approx(0.15)
        assert cmp.deploy is True

    def test_immutable(self) -> None:
        cmp = ModelComparison(
            component="regime",
            incumbent_score=0.8,
            candidate_score=0.85,
            improvement=0.05,
            deploy=True,
            metric_name="accuracy",
        )
        with pytest.raises(Exception):
            cmp.deploy = False  # type: ignore[misc]

    def test_none_scores(self) -> None:
        cmp = ModelComparison(
            component="genome",
            incumbent_score=None,
            candidate_score=None,
            improvement=0.0,
            deploy=False,
            metric_name="composite_fitness",
        )
        assert cmp.incumbent_score is None
        assert cmp.candidate_score is None


# ── RetrainResult tests ────────────────────────────────────────────────────────


class TestRetrainResult:
    def _make(self, **kwargs: object) -> RetrainResult:
        defaults: dict = {
            "component": "rl",
            "triggered_at": "2026-03-22T00:00:00+00:00",
            "completed_at": "2026-03-22T01:00:00+00:00",
            "success": True,
        }
        defaults.update(kwargs)
        return RetrainResult(**defaults)

    def test_to_log_dict_success(self) -> None:
        cmp = ModelComparison(
            component="rl",
            incumbent_score=1.0,
            candidate_score=1.2,
            improvement=0.2,
            deploy=True,
            metric_name="sharpe_ratio",
        )
        r = self._make(comparison=cmp, deployed=True, artifact_path="/tmp/model.zip")
        d = r.to_log_dict()
        assert d["component"] == "rl"
        assert d["success"] is True
        assert d["deployed"] is True
        assert d["improvement"] == pytest.approx(0.2)
        assert d["metric"] == "sharpe_ratio"
        assert d["artifact_path"] == "/tmp/model.zip"
        assert d["error"] is None

    def test_to_log_dict_failure(self) -> None:
        r = self._make(success=False, error="timeout", comparison=None, deployed=False)
        d = r.to_log_dict()
        assert d["success"] is False
        assert d["error"] == "timeout"
        assert d["improvement"] is None

    def test_immutable(self) -> None:
        r = self._make()
        with pytest.raises(Exception):
            r.success = False  # type: ignore[misc]


# ── _build_comparison tests ────────────────────────────────────────────────────


class TestBuildComparison:
    def _make_orc(self, tmp_path: Path, min_improvement: float = 0.01) -> RetrainOrchestrator:
        config = _make_config(tmp_path, min_improvement=min_improvement)
        return _make_orchestrator(config)

    def test_no_incumbent_always_deploys(self, tmp_path: Path) -> None:
        orc = self._make_orc(tmp_path)
        cmp = orc._build_comparison("rl", None, 1.5, "sharpe_ratio")
        assert cmp.deploy is True
        assert cmp.improvement > 0

    def test_candidate_none_never_deploys(self, tmp_path: Path) -> None:
        orc = self._make_orc(tmp_path)
        cmp = orc._build_comparison("rl", 1.0, None, "sharpe_ratio")
        assert cmp.deploy is False
        assert cmp.improvement == pytest.approx(0.0)

    def test_above_threshold_deploys(self, tmp_path: Path) -> None:
        orc = self._make_orc(tmp_path, min_improvement=0.01)
        cmp = orc._build_comparison("rl", 1.0, 1.05, "sharpe_ratio")
        assert cmp.deploy is True
        assert cmp.improvement == pytest.approx(0.05)

    def test_below_threshold_does_not_deploy(self, tmp_path: Path) -> None:
        orc = self._make_orc(tmp_path, min_improvement=0.05)
        cmp = orc._build_comparison("rl", 1.0, 1.03, "sharpe_ratio")
        assert cmp.deploy is False

    def test_exact_threshold_deploys(self, tmp_path: Path) -> None:
        orc = self._make_orc(tmp_path, min_improvement=0.05)
        cmp = orc._build_comparison("rl", 1.0, 1.05, "sharpe_ratio")
        assert cmp.deploy is True

    def test_regression_does_not_deploy(self, tmp_path: Path) -> None:
        orc = self._make_orc(tmp_path)
        cmp = orc._build_comparison("rl", 1.5, 1.2, "sharpe_ratio")
        assert cmp.deploy is False
        assert cmp.improvement < 0

    def test_zero_threshold_always_deploys_if_candidate(self, tmp_path: Path) -> None:
        orc = self._make_orc(tmp_path, min_improvement=0.0)
        # Tie (no improvement) still deploys with threshold=0
        cmp = orc._build_comparison("rl", 1.0, 1.0, "sharpe_ratio")
        assert cmp.deploy is True


# ── audit_log and _failure_result tests ───────────────────────────────────────


class TestAuditLog:
    def test_audit_log_initially_empty(self, tmp_path: Path) -> None:
        orc = _make_orchestrator(_make_config(tmp_path))
        assert orc.audit_log == []

    def test_record_result_appends(self, tmp_path: Path) -> None:
        orc = _make_orchestrator(_make_config(tmp_path))
        r = RetrainOrchestrator._failure_result("rl", _utc_now_iso(), "test")
        orc._record_result(r)
        assert len(orc.audit_log) == 1
        assert orc.audit_log[0].component == "rl"

    def test_failure_result_fields(self) -> None:
        ts = _utc_now_iso()
        r = RetrainOrchestrator._failure_result("ensemble", ts, "boom")
        assert r.component == "ensemble"
        assert r.triggered_at == ts
        assert r.success is False
        assert r.error == "boom"
        assert r.deployed is False
        assert r.comparison is None


# ── run_scheduled_cycle tests ──────────────────────────────────────────────────


class TestRunScheduledCycle:
    async def test_nothing_due_returns_empty(self, tmp_path: Path) -> None:
        """All components were recently retrained — nothing runs."""
        config = _make_config(tmp_path)
        orc = _make_orchestrator(config)
        # Mark everything as recently retrained
        now_iso = _utc_now_iso()
        orc._schedule.last_ensemble_retrain = now_iso
        orc._schedule.last_regime_retrain = now_iso
        orc._schedule.last_genome_retrain = now_iso
        orc._schedule.last_rl_retrain = now_iso

        results = await orc.run_scheduled_cycle()
        assert results == []

    async def test_all_due_runs_four_jobs(self, tmp_path: Path) -> None:
        """All timestamps are None — all four jobs should run."""
        config = _make_config(tmp_path)

        # Inject fast no-op trainers
        async def _fake_ensemble() -> RetrainResult:
            return RetrainOrchestrator._failure_result("ensemble", _utc_now_iso(), "mock")

        async def _fake_regime() -> RetrainResult:
            return RetrainOrchestrator._failure_result("regime", _utc_now_iso(), "mock")

        async def _fake_genome() -> RetrainResult:
            return RetrainOrchestrator._failure_result("genome", _utc_now_iso(), "mock")

        async def _fake_rl() -> RetrainResult:
            return RetrainOrchestrator._failure_result("rl", _utc_now_iso(), "mock")

        orc = _make_orchestrator(config)
        orc.retrain_ensemble = _fake_ensemble  # type: ignore[method-assign]
        orc.retrain_regime = _fake_regime  # type: ignore[method-assign]
        orc.retrain_genome = _fake_genome  # type: ignore[method-assign]
        orc.retrain_rl = _fake_rl  # type: ignore[method-assign]

        results = await orc.run_scheduled_cycle()
        assert len(results) == 4

    async def test_only_ensemble_due(self, tmp_path: Path) -> None:
        """Only ensemble interval has elapsed — only ensemble runs."""
        config = _make_config(
            tmp_path,
            ensemble_retrain_interval_hours=0.0001,  # effectively always due
            regime_retrain_interval_days=999.0,
            genome_retrain_interval_days=999.0,
            rl_retrain_interval_days=999.0,
        )
        run_count = {"n": 0}

        async def _fake_ensemble() -> RetrainResult:
            run_count["n"] += 1
            return RetrainOrchestrator._failure_result("ensemble", _utc_now_iso(), "mock")

        now_iso = _utc_now_iso()
        orc = _make_orchestrator(config)
        orc._schedule.last_regime_retrain = now_iso
        orc._schedule.last_genome_retrain = now_iso
        orc._schedule.last_rl_retrain = now_iso
        orc.retrain_ensemble = _fake_ensemble  # type: ignore[method-assign]

        results = await orc.run_scheduled_cycle()
        assert run_count["n"] == 1
        assert len(results) == 1
        assert results[0].component == "ensemble"


# ── retrain_ensemble tests ─────────────────────────────────────────────────────


class TestRetrainEnsemble:
    async def test_first_run_always_deploys(self, tmp_path: Path) -> None:
        """No incumbent score → should deploy after first successful train."""
        config = _make_config(tmp_path)

        def _fake_optimizer() -> dict[str, float]:
            return {"rl": 0.4, "evolved": 0.35, "regime": 0.25}

        # Make the evaluation return a score so the gate passes
        orc = _make_orchestrator(config, ensemble_optimizer=_fake_optimizer)

        async def _eval_weights(_: dict) -> float:  # type: ignore[override]
            return 0.65

        orc._evaluate_ensemble_weights = _eval_weights  # type: ignore[method-assign]

        async def _deploy_weights(weights: dict) -> str:
            return str(tmp_path / "optimal_weights.json")

        orc._deploy_ensemble_weights = _deploy_weights  # type: ignore[method-assign]

        result = await orc.retrain_ensemble()
        assert result.success is True
        assert result.deployed is True
        assert result.comparison is not None
        assert result.comparison.deploy is True

    async def test_insufficient_improvement_does_not_deploy(self, tmp_path: Path) -> None:
        """Candidate score below threshold → no deployment."""
        config = _make_config(tmp_path, min_improvement=0.10)

        def _fake_optimizer() -> dict[str, float]:
            return {"rl": 0.333, "evolved": 0.333, "regime": 0.334}

        orc = _make_orchestrator(config, ensemble_optimizer=_fake_optimizer)
        orc._incumbent_scores["ensemble"] = 0.70  # existing incumbent

        async def _eval_weights(_: dict) -> float:
            return 0.72  # only +0.02, below 0.10 threshold

        orc._evaluate_ensemble_weights = _eval_weights  # type: ignore[method-assign]

        result = await orc.retrain_ensemble()
        assert result.success is True
        assert result.deployed is False
        assert result.comparison is not None
        assert result.comparison.deploy is False

    async def test_exception_returns_failure_result(self, tmp_path: Path) -> None:
        """Optimizer raising an exception → success=False result."""
        config = _make_config(tmp_path)

        def _bad_optimizer() -> dict[str, float]:
            raise RuntimeError("network down")

        orc = _make_orchestrator(config, ensemble_optimizer=_bad_optimizer)
        result = await orc.retrain_ensemble()
        assert result.success is False
        assert result.error is not None
        assert "network down" in result.error
        assert result.deployed is False

    async def test_result_added_to_audit_log(self, tmp_path: Path) -> None:
        """Successful retrain appends to audit_log."""
        config = _make_config(tmp_path)

        def _fake_optimizer() -> dict[str, float]:
            return {"rl": 0.5, "evolved": 0.3, "regime": 0.2}

        orc = _make_orchestrator(config, ensemble_optimizer=_fake_optimizer)

        async def _eval_weights(_: dict) -> float:
            return 0.65

        orc._evaluate_ensemble_weights = _eval_weights  # type: ignore[method-assign]

        async def _deploy_weights(weights: dict) -> str:
            return str(tmp_path / "optimal_weights.json")

        orc._deploy_ensemble_weights = _deploy_weights  # type: ignore[method-assign]

        await orc.retrain_ensemble()
        assert len(orc.audit_log) == 1
        assert orc.audit_log[0].component == "ensemble"

    async def test_schedule_updated_after_run(self, tmp_path: Path) -> None:
        """Schedule state is updated even when not deploying."""
        config = _make_config(tmp_path, min_improvement=0.99)  # nearly impossible to beat

        def _fake_optimizer() -> dict[str, float]:
            return {"rl": 0.333, "evolved": 0.333, "regime": 0.334}

        orc = _make_orchestrator(config, ensemble_optimizer=_fake_optimizer)
        orc._incumbent_scores["ensemble"] = 1.0  # high bar

        async def _eval_weights(_: dict) -> float:
            return 0.5  # well below threshold

        orc._evaluate_ensemble_weights = _eval_weights  # type: ignore[method-assign]

        assert orc._schedule.last_ensemble_retrain is None
        await orc.retrain_ensemble()
        assert orc._schedule.last_ensemble_retrain is not None


# ── retrain_regime tests ───────────────────────────────────────────────────────


class TestRetrainRegime:
    def _make_fake_classifier(self, accuracy: float) -> MagicMock:
        """Return a MagicMock classifier whose evaluate() returns *accuracy*."""
        clf = MagicMock()
        clf.evaluate.return_value = {"accuracy": accuracy, "precision": 0.8}
        clf.save = MagicMock()
        return clf

    def _make_fake_features(self, n: int = 100) -> "Any":
        """Return a minimal DataFrame-like structure for feature data."""
        import pandas as pd

        return pd.DataFrame(
            {
                "adx": [25.0] * n,
                "atr_ratio": [0.01] * n,
                "bb_width": [0.02] * n,
                "rsi": [50.0] * n,
                "macd_hist": [0.0] * n,
                "volume_ratio": [1.0] * n,
            }
        )

    async def test_improvement_triggers_deploy(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, min_improvement=0.01)
        fake_clf = self._make_fake_classifier(accuracy=0.88)

        def _fake_trainer(features: object, labels: object) -> MagicMock:
            return fake_clf

        orc = _make_orchestrator(config, regime_trainer=_fake_trainer)
        orc._incumbent_scores["regime"] = 0.80

        # Bypass actual API / file calls
        async def _fetch_candles() -> list[dict]:
            return [{"open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000}] * 200

        orc._fetch_candles_for_training = _fetch_candles  # type: ignore[method-assign]

        import pandas as pd
        fake_features = self._make_fake_features(160)

        def _split(candles: list) -> tuple:
            train_f = fake_features.iloc[:128]
            test_f = fake_features.iloc[128:]
            from agent.strategies.regime.labeler import RegimeType
            train_l = [RegimeType.TRENDING] * 128
            test_l = [RegimeType.TRENDING] * 32
            return train_f, train_l, test_f, test_l

        orc._split_regime_data = _split  # type: ignore[method-assign]

        async def _deploy_clf(clf: object) -> str:
            return str(tmp_path / "regime_classifier.joblib")

        orc._deploy_regime_classifier = _deploy_clf  # type: ignore[method-assign]

        result = await orc.retrain_regime()
        assert result.success is True
        assert result.deployed is True
        assert result.comparison is not None
        assert result.comparison.candidate_score == pytest.approx(0.88)

    async def test_regression_skips_deploy(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, min_improvement=0.01)
        fake_clf = self._make_fake_classifier(accuracy=0.72)

        def _fake_trainer(features: object, labels: object) -> MagicMock:
            return fake_clf

        orc = _make_orchestrator(config, regime_trainer=_fake_trainer)
        orc._incumbent_scores["regime"] = 0.85  # incumbent is better

        async def _fetch_candles() -> list[dict]:
            return [{"open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000}] * 200

        orc._fetch_candles_for_training = _fetch_candles  # type: ignore[method-assign]

        import pandas as pd
        fake_features = self._make_fake_features(160)

        def _split(candles: list) -> tuple:
            train_f = fake_features.iloc[:128]
            test_f = fake_features.iloc[128:]
            from agent.strategies.regime.labeler import RegimeType
            train_l = [RegimeType.TRENDING] * 128
            test_l = [RegimeType.TRENDING] * 32
            return train_f, train_l, test_f, test_l

        orc._split_regime_data = _split  # type: ignore[method-assign]

        result = await orc.retrain_regime()
        assert result.success is True
        assert result.deployed is False

    async def test_exception_returns_failure(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)

        def _bad_trainer(features: object, labels: object) -> None:
            raise ValueError("classifier broken")

        orc = _make_orchestrator(config, regime_trainer=_bad_trainer)

        async def _fetch_candles() -> list[dict]:
            return [{"open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000}] * 200

        orc._fetch_candles_for_training = _fetch_candles  # type: ignore[method-assign]

        import pandas as pd
        fake_features = self._make_fake_features(160)

        def _split(candles: list) -> tuple:
            train_f = fake_features.iloc[:128]
            test_f = fake_features.iloc[128:]
            from agent.strategies.regime.labeler import RegimeType
            train_l = [RegimeType.TRENDING] * 128
            test_l = [RegimeType.TRENDING] * 32
            return train_f, train_l, test_f, test_l

        orc._split_regime_data = _split  # type: ignore[method-assign]

        result = await orc.retrain_regime()
        assert result.success is False
        assert result.error is not None
        assert "classifier broken" in result.error


# ── retrain_genome tests ───────────────────────────────────────────────────────


class TestRetrainGenome:
    async def test_improvement_triggers_deploy(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, min_improvement=0.01)

        def _evolver(generations: int) -> float:
            return 2.5  # candidate fitness

        orc = _make_orchestrator(config, genome_evolver=_evolver)
        orc._incumbent_scores["genome"] = 2.0  # incumbent

        async def _deploy_champ() -> str:
            return str(tmp_path / "champion.json")

        orc._deploy_genome_champion = _deploy_champ  # type: ignore[method-assign]

        result = await orc.retrain_genome()
        assert result.success is True
        assert result.deployed is True
        assert result.comparison is not None
        assert result.comparison.candidate_score == pytest.approx(2.5)
        assert result.comparison.improvement == pytest.approx(0.5)

    async def test_no_improvement_skips_deploy(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, min_improvement=0.5)

        def _evolver(generations: int) -> float:
            return 2.1  # only +0.1

        orc = _make_orchestrator(config, genome_evolver=_evolver)
        orc._incumbent_scores["genome"] = 2.0

        result = await orc.retrain_genome()
        assert result.success is True
        assert result.deployed is False

    async def test_first_run_no_incumbent_deploys(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)

        def _evolver(generations: int) -> float:
            return 1.8

        orc = _make_orchestrator(config, genome_evolver=_evolver)
        # No incumbent

        async def _deploy_champ() -> str:
            return str(tmp_path / "champion.json")

        orc._deploy_genome_champion = _deploy_champ  # type: ignore[method-assign]

        result = await orc.retrain_genome()
        assert result.success is True
        assert result.deployed is True

    async def test_failure_fitness_does_not_deploy(self, tmp_path: Path) -> None:
        """Evolution failure (fitness = -999) should not deploy."""
        config = _make_config(tmp_path)

        def _evolver(generations: int) -> float:
            return -999.0

        orc = _make_orchestrator(config, genome_evolver=_evolver)
        orc._incumbent_scores["genome"] = 1.0  # incumbents beats -999

        result = await orc.retrain_genome()
        assert result.success is True
        assert result.deployed is False

    async def test_exception_returns_failure(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)

        def _bad_evolver(generations: int) -> float:
            raise RuntimeError("battle timeout")

        orc = _make_orchestrator(config, genome_evolver=_bad_evolver)
        result = await orc.retrain_genome()
        assert result.success is False
        assert result.error is not None
        assert "battle timeout" in result.error

    async def test_metadata_contains_generations(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, genome_refresh_generations=3)

        def _evolver(generations: int) -> float:
            return 2.0

        orc = _make_orchestrator(config, genome_evolver=_evolver)

        async def _deploy_champ() -> str:
            return str(tmp_path / "champion.json")

        orc._deploy_genome_champion = _deploy_champ  # type: ignore[method-assign]

        result = await orc.retrain_genome()
        assert result.metadata.get("generations_run") == 3


# ── retrain_rl tests ───────────────────────────────────────────────────────────


class TestRetrainRL:
    def _make_model_path(self, tmp_path: Path) -> Path:
        p = tmp_path / "ppo_seed42.zip"
        p.write_bytes(b"fake-model-zip")
        return p

    async def test_improvement_deploys(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, min_improvement=0.05)
        model_path = self._make_model_path(tmp_path)

        def _trainer(rl_config: object) -> Path:
            return model_path

        orc = _make_orchestrator(config, rl_trainer=_trainer)
        orc._incumbent_scores["rl"] = 1.0

        async def _eval_model(path: Path, cfg: object) -> float:
            return 1.2  # +0.2

        orc._evaluate_rl_model = _eval_model  # type: ignore[method-assign]

        async def _deploy_model(path: Path) -> str:
            return str(path)

        orc._deploy_rl_model = _deploy_model  # type: ignore[method-assign]

        result = await orc.retrain_rl()
        assert result.success is True
        assert result.deployed is True
        assert result.comparison is not None
        assert result.comparison.improvement == pytest.approx(0.2)

    async def test_no_improvement_skips_deploy(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, min_improvement=0.5)
        model_path = self._make_model_path(tmp_path)

        def _trainer(rl_config: object) -> Path:
            return model_path

        orc = _make_orchestrator(config, rl_trainer=_trainer)
        orc._incumbent_scores["rl"] = 1.8

        async def _eval_model(path: Path, cfg: object) -> float:
            return 1.85  # +0.05 < 0.5

        orc._evaluate_rl_model = _eval_model  # type: ignore[method-assign]

        result = await orc.retrain_rl()
        assert result.success is True
        assert result.deployed is False

    async def test_first_run_deploys(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        model_path = self._make_model_path(tmp_path)

        def _trainer(rl_config: object) -> Path:
            return model_path

        orc = _make_orchestrator(config, rl_trainer=_trainer)
        # No incumbent

        async def _eval_model(path: Path, cfg: object) -> float:
            return 0.9

        orc._evaluate_rl_model = _eval_model  # type: ignore[method-assign]

        async def _deploy_model(path: Path) -> str:
            return str(path)

        orc._deploy_rl_model = _deploy_model  # type: ignore[method-assign]

        result = await orc.retrain_rl()
        assert result.success is True
        assert result.deployed is True

    async def test_eval_returns_none_no_deploy(self, tmp_path: Path) -> None:
        """Evaluator returning None (SB3 not installed) → no deployment."""
        config = _make_config(tmp_path)
        model_path = self._make_model_path(tmp_path)

        def _trainer(rl_config: object) -> Path:
            return model_path

        orc = _make_orchestrator(config, rl_trainer=_trainer)

        async def _eval_model(path: Path, cfg: object) -> None:
            return None

        orc._evaluate_rl_model = _eval_model  # type: ignore[method-assign]

        result = await orc.retrain_rl()
        assert result.success is True
        assert result.deployed is False
        assert result.comparison is not None
        assert result.comparison.candidate_score is None

    async def test_trainer_exception_returns_failure(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)

        def _bad_trainer(rl_config: object) -> Path:
            raise RuntimeError("GPU out of memory")

        orc = _make_orchestrator(config, rl_trainer=_bad_trainer)
        result = await orc.retrain_rl()
        assert result.success is False
        assert result.error is not None
        assert "GPU out of memory" in result.error

    async def test_metadata_contains_windows(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        model_path = self._make_model_path(tmp_path)

        def _trainer(rl_config: object) -> Path:
            return model_path

        orc = _make_orchestrator(config, rl_trainer=_trainer)

        async def _eval_model(path: Path, cfg: object) -> float:
            return 1.5

        orc._evaluate_rl_model = _eval_model  # type: ignore[method-assign]

        async def _deploy_model(path: Path) -> str:
            return str(path)

        orc._deploy_rl_model = _deploy_model  # type: ignore[method-assign]

        result = await orc.retrain_rl()
        assert "train_start" in result.metadata
        assert "train_end" in result.metadata
        assert "eval_start" in result.metadata
        assert "eval_end" in result.metadata

    async def test_schedule_updated_on_success(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        model_path = self._make_model_path(tmp_path)

        def _trainer(rl_config: object) -> Path:
            return model_path

        orc = _make_orchestrator(config, rl_trainer=_trainer)

        async def _eval_model(path: Path, cfg: object) -> float:
            return 1.0

        orc._evaluate_rl_model = _eval_model  # type: ignore[method-assign]

        async def _deploy_model(path: Path) -> str:
            return str(path)

        orc._deploy_rl_model = _deploy_model  # type: ignore[method-assign]

        assert orc._schedule.last_rl_retrain is None
        await orc.retrain_rl()
        assert orc._schedule.last_rl_retrain is not None


# ── Persistence tests ──────────────────────────────────────────────────────────


class TestPersistence:
    async def test_result_json_written_to_disk(self, tmp_path: Path) -> None:
        """After a successful retrain cycle, a JSON file should appear."""
        config = _make_config(tmp_path)

        def _evolver(n: int) -> float:
            return 2.0

        orc = _make_orchestrator(config, genome_evolver=_evolver)

        async def _deploy_champ() -> str:
            return str(tmp_path / "champion.json")

        orc._deploy_genome_champion = _deploy_champ  # type: ignore[method-assign]

        await orc.retrain_genome()

        # Give the fire-and-forget task a moment to complete
        await asyncio.sleep(0.05)

        json_files = list(config.results_dir.glob("genome-*.json"))
        assert len(json_files) == 1
        data = json.loads(json_files[0].read_text())
        assert data["component"] == "genome"
        assert data["success"] is True


# ── Offline mode tests ─────────────────────────────────────────────────────────


class TestOfflineMode:
    async def test_ensemble_offline_uses_equal_weights(self, tmp_path: Path) -> None:
        """No rest_client → default equal weights, no API calls."""
        config = _make_config(tmp_path)
        orc = _make_orchestrator(config, rest_client=None)

        async def _eval_weights(weights: dict) -> None:
            # No REST client → evaluation returns None
            return None

        orc._evaluate_ensemble_weights = _eval_weights  # type: ignore[method-assign]

        result = await orc.retrain_ensemble()
        # Candidate score None → no deployment
        assert result.success is True
        assert result.deployed is False

    async def test_regime_offline_empty_candles(self, tmp_path: Path) -> None:
        """No SDK client → candle fetch returns empty list."""
        config = _make_config(tmp_path)
        orc = _make_orchestrator(config, sdk_client=None)

        # With no candles, _split_regime_data returns empty DataFrames
        result = await orc.retrain_regime()
        # Should succeed but with no useful data; regime trainer may fail gracefully
        # or succeed with an incumbent that beats an empty evaluation
        assert isinstance(result, RetrainResult)
