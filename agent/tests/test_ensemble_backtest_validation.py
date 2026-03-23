"""Tests for ensemble backtest validation mode.

Covers:
- EnsembleReport new financial metric fields (defaults and validation)
- BacktestValidationReport model (fields, immutability)
- build_validation_report() acceptance criteria logic
- EnsembleRunner._fetch_backtest_metrics() — success, nested metrics, HTTP error,
  bad session_id, missing keys, non-numeric values
- EnsembleRunner._build_report() propagates platform_metrics into EnsembleReport
- EnsembleRunner.run_backtest() fetches metrics and attaches them to the report
- _cli_main() backtest mode produces a BacktestValidationReport JSON
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent.strategies.ensemble.config import EnsembleConfig
from agent.strategies.ensemble.run import (
    BacktestValidationReport,
    EnsembleReport,
    EnsembleRunner,
    SourceStats,
    build_validation_report,
    _cli_main,
)
from agent.strategies.ensemble.signals import SignalSource


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_config(**kwargs) -> EnsembleConfig:
    """Return a minimal EnsembleConfig with all signals disabled by default."""
    defaults = dict(
        enable_rl_signal=False,
        enable_evolved_signal=False,
        enable_regime_signal=False,
        enable_risk_overlay=False,
        symbols=["BTCUSDT"],
        mode="backtest",
    )
    defaults.update(kwargs)
    return EnsembleConfig(_env_file=None, **defaults)  # type: ignore[call-arg]


def _make_source_stats(
    source: str,
    buy: int = 0,
    sell: int = 0,
    hold: int = 5,
) -> SourceStats:
    return SourceStats(
        source=source,
        total_steps=buy + sell + hold,
        buy_signals=buy,
        sell_signals=sell,
        hold_signals=hold,
    )


def _make_ensemble_report(**overrides) -> EnsembleReport:
    """Return a minimal EnsembleReport with sensible defaults."""
    source_stats = [
        _make_source_stats("rl"),
        _make_source_stats("evolved"),
        _make_source_stats("regime"),
    ]
    defaults = dict(
        session_id="test-session-id",
        mode="backtest",
        start_time="2024-01-01T00:00:00",
        end_time="2024-01-07T00:00:00",
        total_steps=10,
        total_orders_placed=3,
        total_orders_vetoed=1,
        overall_agreement_rate=0.75,
        source_stats=source_stats,
        config_summary={"mode": "backtest"},
        platform_metrics_available=True,
        sharpe_ratio=1.2,
        win_rate=0.6,
        roi_pct=5.5,
        max_drawdown_pct=3.1,
        total_trades=5,
        final_equity=10500.0,
    )
    defaults.update(overrides)
    return EnsembleReport(**defaults)


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


# ── EnsembleReport new fields ─────────────────────────────────────────────────


class TestEnsembleReportFinancialFields:
    """EnsembleReport now carries optional financial metric fields."""

    def test_financial_fields_default_to_none(self) -> None:
        report = _make_ensemble_report(
            platform_metrics_available=False,
            sharpe_ratio=None,
            win_rate=None,
            roi_pct=None,
            max_drawdown_pct=None,
            total_trades=0,
            final_equity=None,
        )
        assert report.sharpe_ratio is None
        assert report.win_rate is None
        assert report.roi_pct is None
        assert report.max_drawdown_pct is None
        assert report.total_trades == 0
        assert report.final_equity is None
        assert report.platform_metrics_available is False

    def test_financial_fields_accept_valid_values(self) -> None:
        report = _make_ensemble_report()
        assert report.sharpe_ratio == 1.2
        assert report.win_rate == 0.6
        assert report.roi_pct == 5.5
        assert report.max_drawdown_pct == 3.1
        assert report.total_trades == 5
        assert report.final_equity == 10500.0
        assert report.platform_metrics_available is True

    def test_ensemble_report_is_frozen(self) -> None:
        report = _make_ensemble_report()
        with pytest.raises(Exception):  # ValidationError from frozen model
            report.sharpe_ratio = 9.9  # type: ignore[misc]

    def test_round_trip_serialisation(self) -> None:
        report = _make_ensemble_report()
        as_dict = json.loads(report.model_dump_json())
        assert as_dict["sharpe_ratio"] == pytest.approx(1.2)
        assert as_dict["win_rate"] == pytest.approx(0.6)
        assert as_dict["platform_metrics_available"] is True

    def test_negative_sharpe_allowed(self) -> None:
        report = _make_ensemble_report(sharpe_ratio=-2.5)
        assert report.sharpe_ratio == pytest.approx(-2.5)


# ── BacktestValidationReport model ────────────────────────────────────────────


class TestBacktestValidationReportModel:
    """BacktestValidationReport Pydantic model field validation."""

    def _make(self, **overrides) -> BacktestValidationReport:
        base = dict(
            report_id="bt-validation-20240101_120000",
            generated_at="2024-01-01T12:00:00+00:00",
            base_url="http://localhost:8000",
            symbols=["BTCUSDT"],
            backtest_days=7,
            backtest_start="2024-01-01T00:00:00Z",
            backtest_end="2024-01-08T00:00:00Z",
            ensemble_report=_make_ensemble_report(),
            validation_passed=True,
            acceptance_criteria={
                "metrics_available": True,
                "min_one_trade": True,
                "sharpe_above_floor": True,
                "all_sources_contributed": True,
                "no_fatal_errors": True,
            },
            active_sources=["rl", "evolved", "regime"],
            errors=[],
        )
        base.update(overrides)
        return BacktestValidationReport(**base)

    def test_validation_passed_stored(self) -> None:
        assert self._make().validation_passed is True

    def test_validation_failed_stored(self) -> None:
        report = self._make(validation_passed=False)
        assert report.validation_passed is False

    def test_acceptance_criteria_dict_preserved(self) -> None:
        report = self._make()
        assert report.acceptance_criteria["metrics_available"] is True

    def test_active_sources_list_preserved(self) -> None:
        report = self._make()
        assert "rl" in report.active_sources

    def test_errors_list_preserved(self) -> None:
        report = self._make(errors=["something went wrong"])
        assert report.errors == ["something went wrong"]

    def test_frozen_model(self) -> None:
        report = self._make()
        with pytest.raises(Exception):
            report.validation_passed = False  # type: ignore[misc]

    def test_round_trip_json(self) -> None:
        report = self._make()
        as_dict = json.loads(report.model_dump_json())
        assert as_dict["report_id"].startswith("bt-validation-")
        assert as_dict["validation_passed"] is True


# ── build_validation_report() ─────────────────────────────────────────────────


class TestBuildValidationReport:
    """build_validation_report() acceptance criteria evaluation."""

    def _make_report_with_sources(self, buy_rl=2, buy_evolved=1, buy_regime=3) -> EnsembleReport:
        return _make_ensemble_report(
            source_stats=[
                _make_source_stats("rl", buy=buy_rl),
                _make_source_stats("evolved", buy=buy_evolved),
                _make_source_stats("regime", buy=buy_regime),
            ]
        )

    def test_all_criteria_pass_when_report_is_healthy(self) -> None:
        report = self._make_report_with_sources()
        val = build_validation_report(
            report=report,
            base_url="http://localhost:8000",
            symbols=["BTCUSDT"],
            backtest_days=7,
            backtest_start="2024-01-01T00:00:00Z",
            backtest_end="2024-01-08T00:00:00Z",
        )
        assert val.validation_passed is True
        assert val.acceptance_criteria["metrics_available"] is True
        assert val.acceptance_criteria["min_one_trade"] is True
        assert val.acceptance_criteria["sharpe_above_floor"] is True
        assert val.acceptance_criteria["all_sources_contributed"] is True
        assert val.acceptance_criteria["no_fatal_errors"] is True

    def test_fails_when_no_metrics_available(self) -> None:
        report = self._make_report_with_sources()
        report = EnsembleReport(
            **{**report.model_dump(), "platform_metrics_available": False}
        )
        val = build_validation_report(
            report=report,
            base_url="http://localhost:8000",
            symbols=["BTCUSDT"],
            backtest_days=7,
            backtest_start="2024-01-01T00:00:00Z",
            backtest_end="2024-01-08T00:00:00Z",
        )
        assert val.acceptance_criteria["metrics_available"] is False
        assert val.validation_passed is False

    def test_fails_when_no_orders_placed(self) -> None:
        report = self._make_report_with_sources()
        report = EnsembleReport(**{**report.model_dump(), "total_orders_placed": 0})
        val = build_validation_report(
            report=report,
            base_url="http://localhost:8000",
            symbols=["BTCUSDT"],
            backtest_days=7,
            backtest_start="2024-01-01T00:00:00Z",
            backtest_end="2024-01-08T00:00:00Z",
        )
        assert val.acceptance_criteria["min_one_trade"] is False
        assert val.validation_passed is False

    def test_fails_when_sharpe_below_floor(self) -> None:
        report = self._make_report_with_sources()
        report = EnsembleReport(**{**report.model_dump(), "sharpe_ratio": -2.5})
        val = build_validation_report(
            report=report,
            base_url="http://localhost:8000",
            symbols=["BTCUSDT"],
            backtest_days=7,
            backtest_start="2024-01-01T00:00:00Z",
            backtest_end="2024-01-08T00:00:00Z",
        )
        assert val.acceptance_criteria["sharpe_above_floor"] is False
        assert val.validation_passed is False

    def test_sharpe_criterion_passes_when_none(self) -> None:
        """When Sharpe is None (no metric), the floor criterion passes."""
        report = self._make_report_with_sources()
        report = EnsembleReport(**{**report.model_dump(), "sharpe_ratio": None})
        val = build_validation_report(
            report=report,
            base_url="http://localhost:8000",
            symbols=["BTCUSDT"],
            backtest_days=7,
            backtest_start="2024-01-01T00:00:00Z",
            backtest_end="2024-01-08T00:00:00Z",
        )
        assert val.acceptance_criteria["sharpe_above_floor"] is True

    def test_fails_when_not_all_sources_contributed(self) -> None:
        # REGIME source emits only HOLD signals (buy=0, sell=0)
        report = _make_ensemble_report(
            source_stats=[
                _make_source_stats("rl", buy=2),
                _make_source_stats("evolved", buy=1),
                _make_source_stats("regime", buy=0, sell=0, hold=10),  # HOLD only
            ]
        )
        val = build_validation_report(
            report=report,
            base_url="http://localhost:8000",
            symbols=["BTCUSDT"],
            backtest_days=7,
            backtest_start="2024-01-01T00:00:00Z",
            backtest_end="2024-01-08T00:00:00Z",
        )
        assert val.acceptance_criteria["all_sources_contributed"] is False
        assert val.validation_passed is False

    def test_fails_when_errors_present(self) -> None:
        report = self._make_report_with_sources()
        val = build_validation_report(
            report=report,
            base_url="http://localhost:8000",
            symbols=["BTCUSDT"],
            backtest_days=7,
            backtest_start="2024-01-01T00:00:00Z",
            backtest_end="2024-01-08T00:00:00Z",
            errors=["connection timed out"],
        )
        assert val.acceptance_criteria["no_fatal_errors"] is False
        assert val.validation_passed is False
        assert "connection timed out" in val.errors

    def test_active_sources_only_includes_non_hold(self) -> None:
        report = _make_ensemble_report(
            source_stats=[
                _make_source_stats("rl", buy=2),
                _make_source_stats("evolved", buy=0, sell=0, hold=10),
                _make_source_stats("regime", sell=1),
            ]
        )
        val = build_validation_report(
            report=report,
            base_url="http://localhost:8000",
            symbols=["BTCUSDT"],
            backtest_days=7,
            backtest_start="2024-01-01T00:00:00Z",
            backtest_end="2024-01-08T00:00:00Z",
        )
        assert "rl" in val.active_sources
        assert "regime" in val.active_sources
        assert "evolved" not in val.active_sources

    def test_report_id_has_bt_validation_prefix(self) -> None:
        report = self._make_report_with_sources()
        val = build_validation_report(
            report=report,
            base_url="http://localhost:8000",
            symbols=["BTCUSDT"],
            backtest_days=7,
            backtest_start="2024-01-01T00:00:00Z",
            backtest_end="2024-01-08T00:00:00Z",
        )
        assert val.report_id.startswith("bt-validation-")

    def test_metadata_fields_are_propagated(self) -> None:
        report = self._make_report_with_sources()
        val = build_validation_report(
            report=report,
            base_url="http://example.com",
            symbols=["BTCUSDT", "ETHUSDT"],
            backtest_days=14,
            backtest_start="2024-01-01T00:00:00Z",
            backtest_end="2024-01-15T00:00:00Z",
        )
        assert val.base_url == "http://example.com"
        assert val.symbols == ["BTCUSDT", "ETHUSDT"]
        assert val.backtest_days == 14


# ── EnsembleRunner._fetch_backtest_metrics() ──────────────────────────────────


class TestFetchBacktestMetrics:
    """EnsembleRunner._fetch_backtest_metrics() extracts financial metrics."""

    def _make_runner(self, rest_client=None) -> EnsembleRunner:
        config = _make_config()
        return EnsembleRunner(
            config=config,
            sdk_client=None,
            rest_client=rest_client,
        )

    async def test_returns_metrics_on_success(self) -> None:
        rest = AsyncMock()
        rest.get.return_value = _mock_response(
            {
                "metrics": {
                    "sharpe_ratio": 1.5,
                    "win_rate": 0.65,
                    "roi_pct": 8.2,
                    "max_drawdown_pct": 4.1,
                    "total_trades": 12,
                    "final_equity": 10820.0,
                }
            }
        )
        runner = self._make_runner(rest_client=rest)
        result = await runner._fetch_backtest_metrics("test-session-123")

        assert result["sharpe_ratio"] == pytest.approx(1.5)
        assert result["win_rate"] == pytest.approx(0.65)
        assert result["roi_pct"] == pytest.approx(8.2)
        assert result["max_drawdown_pct"] == pytest.approx(4.1)
        assert result["total_trades"] == 12
        assert result["final_equity"] == pytest.approx(10820.0)
        assert result["platform_metrics_available"] is True

    async def test_handles_flat_response_shape(self) -> None:
        """Platform may return metrics at top level (no nested 'metrics' key)."""
        rest = AsyncMock()
        rest.get.return_value = _mock_response(
            {
                "sharpe_ratio": 0.9,
                "win_rate": 0.55,
                "roi_pct": 3.0,
                "max_drawdown_pct": 2.5,
                "total_trades": 7,
                "final_equity": 10300.0,
            }
        )
        runner = self._make_runner(rest_client=rest)
        result = await runner._fetch_backtest_metrics("session-abc")

        assert result["sharpe_ratio"] == pytest.approx(0.9)
        assert result["platform_metrics_available"] is True

    async def test_returns_unavailable_on_http_error(self) -> None:
        rest = AsyncMock()
        rest.get.return_value = _mock_response({}, status_code=404)
        runner = self._make_runner(rest_client=rest)
        result = await runner._fetch_backtest_metrics("bad-session")

        assert result["platform_metrics_available"] is False
        assert len(result) == 1

    async def test_returns_unavailable_on_request_error(self) -> None:
        rest = AsyncMock()
        rest.get.side_effect = httpx.RequestError("connection refused")
        runner = self._make_runner(rest_client=rest)
        result = await runner._fetch_backtest_metrics("session-xyz")

        assert result["platform_metrics_available"] is False

    async def test_returns_unavailable_when_rest_is_none(self) -> None:
        runner = self._make_runner(rest_client=None)
        result = await runner._fetch_backtest_metrics("any-session")

        assert result["platform_metrics_available"] is False

    async def test_returns_unavailable_for_error_session_id(self) -> None:
        runner = self._make_runner(rest_client=AsyncMock())
        result = await runner._fetch_backtest_metrics("error")
        assert result["platform_metrics_available"] is False

    async def test_returns_unavailable_for_live_session_id(self) -> None:
        runner = self._make_runner(rest_client=AsyncMock())
        result = await runner._fetch_backtest_metrics("live")
        assert result["platform_metrics_available"] is False

    async def test_handles_missing_keys_gracefully(self) -> None:
        """Partial metrics response — only some keys present."""
        rest = AsyncMock()
        rest.get.return_value = _mock_response({"metrics": {"sharpe_ratio": 1.1}})
        runner = self._make_runner(rest_client=rest)
        result = await runner._fetch_backtest_metrics("partial-session")

        assert result["sharpe_ratio"] == pytest.approx(1.1)
        assert result["win_rate"] is None
        assert result["roi_pct"] is None
        assert result["platform_metrics_available"] is True

    async def test_handles_non_numeric_values_gracefully(self) -> None:
        """Non-numeric strings should produce None, not crash."""
        rest = AsyncMock()
        rest.get.return_value = _mock_response(
            {"metrics": {"sharpe_ratio": "N/A", "total_trades": "many"}}
        )
        runner = self._make_runner(rest_client=rest)
        result = await runner._fetch_backtest_metrics("session-nan")

        assert result["sharpe_ratio"] is None
        assert result["total_trades"] == 0

    async def test_calls_correct_endpoint(self) -> None:
        rest = AsyncMock()
        rest.get.return_value = _mock_response({"metrics": {}})
        runner = self._make_runner(rest_client=rest)
        await runner._fetch_backtest_metrics("my-session-uuid")

        rest.get.assert_called_once_with("/api/v1/backtest/my-session-uuid/results")


# ── EnsembleRunner._build_report() with platform_metrics ─────────────────────


class TestBuildReportWithPlatformMetrics:
    """_build_report() propagates platform_metrics into EnsembleReport."""

    def _make_runner(self) -> EnsembleRunner:
        config = _make_config()
        runner = EnsembleRunner(config=config, sdk_client=None, rest_client=None)
        # Seed MetaLearner so _build_report can access config
        from agent.strategies.ensemble.meta_learner import MetaLearner
        from agent.strategies.ensemble.signals import SignalSource

        runner._meta_learner = MetaLearner(
            weights={s: 1.0 / 3 for s in SignalSource},
            confidence_threshold=0.6,
        )
        runner._signal_source_weights = {s: 1.0 / 3 for s in SignalSource}
        return runner

    def test_report_has_none_fields_when_no_metrics(self) -> None:
        runner = self._make_runner()
        report = runner._build_report(
            session_id="s1",
            start_time="2024-01-01T00:00:00",
            end_time="2024-01-07T00:00:00",
            platform_metrics=None,
        )
        assert report.sharpe_ratio is None
        assert report.platform_metrics_available is False

    def test_report_carries_all_financial_fields(self) -> None:
        runner = self._make_runner()
        metrics = {
            "sharpe_ratio": 2.1,
            "win_rate": 0.7,
            "roi_pct": 12.5,
            "max_drawdown_pct": 6.0,
            "total_trades": 20,
            "final_equity": 11250.0,
            "platform_metrics_available": True,
        }
        report = runner._build_report(
            session_id="s2",
            start_time="2024-01-01T00:00:00",
            end_time="2024-01-07T00:00:00",
            platform_metrics=metrics,
        )
        assert report.sharpe_ratio == pytest.approx(2.1)
        assert report.win_rate == pytest.approx(0.7)
        assert report.roi_pct == pytest.approx(12.5)
        assert report.max_drawdown_pct == pytest.approx(6.0)
        assert report.total_trades == 20
        assert report.final_equity == pytest.approx(11250.0)
        assert report.platform_metrics_available is True

    def test_empty_metrics_dict_produces_none_fields(self) -> None:
        runner = self._make_runner()
        report = runner._build_report(
            session_id="s3",
            start_time="2024-01-01T00:00:00",
            end_time="2024-01-07T00:00:00",
            platform_metrics={"platform_metrics_available": False},
        )
        assert report.sharpe_ratio is None
        assert report.platform_metrics_available is False


# ── EnsembleRunner.run_backtest() metrics integration ─────────────────────────


class TestRunBacktestMetricsIntegration:
    """run_backtest() calls _fetch_backtest_metrics and attaches results."""

    def _make_runner(self, rest_client) -> EnsembleRunner:
        config = _make_config(max_iterations=1, batch_size=1)
        return EnsembleRunner(config=config, sdk_client=None, rest_client=rest_client)

    async def test_run_backtest_attaches_financial_metrics(self) -> None:
        """End-to-end: run_backtest returns an EnsembleReport with Sharpe, etc."""
        rest = AsyncMock()

        # POST /create
        create_resp = _mock_response({"session_id": "sess-1"})
        # POST /start
        start_resp = _mock_response({"status": "started"})
        # GET /candles — returns empty to avoid step logic complexity
        candles_resp = _mock_response({"candles": []})
        # POST /step/batch — complete immediately
        step_resp = _mock_response({"is_complete": True})
        # GET /results
        results_resp = _mock_response(
            {
                "metrics": {
                    "sharpe_ratio": 0.8,
                    "win_rate": 0.5,
                    "roi_pct": 2.0,
                    "max_drawdown_pct": 5.0,
                    "total_trades": 3,
                    "final_equity": 10200.0,
                }
            }
        )

        rest.post.side_effect = [create_resp, start_resp, step_resp]
        rest.get.side_effect = [candles_resp, results_resp]

        runner = self._make_runner(rest_client=rest)
        await runner.initialize()

        report = await runner.run_backtest(
            start="2024-01-01T00:00:00Z",
            end="2024-01-08T00:00:00Z",
        )

        assert report.sharpe_ratio == pytest.approx(0.8)
        assert report.win_rate == pytest.approx(0.5)
        assert report.roi_pct == pytest.approx(2.0)
        assert report.max_drawdown_pct == pytest.approx(5.0)
        assert report.total_trades == 3
        assert report.platform_metrics_available is True

    async def test_run_backtest_handles_results_error_gracefully(self) -> None:
        """If the results endpoint fails, the report still returns (no crash)."""
        rest = AsyncMock()

        create_resp = _mock_response({"session_id": "sess-2"})
        start_resp = _mock_response({"status": "started"})
        candles_resp = _mock_response({"candles": []})
        step_resp = _mock_response({"is_complete": True})
        results_resp = _mock_response({}, status_code=500)

        rest.post.side_effect = [create_resp, start_resp, step_resp]
        rest.get.side_effect = [candles_resp, results_resp]

        runner = self._make_runner(rest_client=rest)
        await runner.initialize()

        report = await runner.run_backtest(
            start="2024-01-01T00:00:00Z",
            end="2024-01-08T00:00:00Z",
        )

        # Report returned — no crash, financial metrics are None/False
        assert isinstance(report, EnsembleReport)
        assert report.platform_metrics_available is False
        assert report.sharpe_ratio is None

    async def test_run_backtest_error_session_skips_results_fetch(self) -> None:
        """If session creation fails, _fetch_backtest_metrics is not called."""
        rest = AsyncMock()
        rest.post.return_value = _mock_response({}, status_code=500)

        runner = self._make_runner(rest_client=rest)
        await runner.initialize()

        report = await runner.run_backtest(
            start="2024-01-01T00:00:00Z",
            end="2024-01-08T00:00:00Z",
        )

        # report is returned, no GET /results attempted
        rest.get.assert_not_called()
        assert report.session_id == "error"


# ── _cli_main() backtest mode ──────────────────────────────────────────────────


class TestCliMainBacktestMode:
    """_cli_main() in backtest mode saves two JSON files."""

    async def test_cli_saves_both_reports_in_backtest_mode(
        self, tmp_path: Path
    ) -> None:
        """_cli_main produces ensemble-report-*.json AND validation-report-*.json."""

        # Patch all external dependencies: date resolution, httpx, EnsembleRunner
        finished_report = _make_ensemble_report(
            source_stats=[
                _make_source_stats("rl", buy=2),
                _make_source_stats("evolved", buy=1),
                _make_source_stats("regime", buy=3),
            ],
            total_orders_placed=3,
            platform_metrics_available=True,
            sharpe_ratio=1.0,
        )

        mock_runner = AsyncMock()
        mock_runner.initialize = AsyncMock()
        mock_runner.run_backtest = AsyncMock(return_value=finished_report)

        with (
            patch(
                "agent.strategies.ensemble.run._resolve_backtest_dates",
                return_value=("2024-01-01T00:00:00Z", "2024-01-08T00:00:00Z"),
            ),
            patch(
                "agent.strategies.ensemble.run.EnsembleRunner",
                return_value=mock_runner,
            ),
            patch("agent.strategies.ensemble.run.httpx.AsyncClient") as mock_ac,
            # configure_agent_logging is imported lazily inside _cli_main — patch at source
            patch("agent.logging.configure_agent_logging"),
        ):
            # httpx.AsyncClient used as async context manager
            mock_ac.return_value.__aenter__.return_value = AsyncMock()
            mock_ac.return_value.__aexit__.return_value = AsyncMock()

            await _cli_main(
                mode="backtest",
                base_url="http://localhost:8000",
                api_key="ak_live_test",
                symbols=["BTCUSDT"],
                days=7,
                seed=42,
                output_dir=tmp_path,
                no_rl=True,
                no_evolved=True,
                no_regime=True,
                no_risk=True,
            )

        # Both report files must exist
        ensemble_files = list(tmp_path.glob("ensemble-report-backtest-*.json"))
        validation_files = list(tmp_path.glob("validation-report-backtest-*.json"))

        assert len(ensemble_files) == 1, "ensemble report not written"
        assert len(validation_files) == 1, "validation report not written"

        # Validate the content of the validation report
        val_data = json.loads(validation_files[0].read_text(encoding="utf-8"))
        assert val_data["report_id"].startswith("bt-validation-")
        assert "acceptance_criteria" in val_data
        assert "active_sources" in val_data
        assert "ensemble_report" in val_data
        assert val_data["backtest_start"] == "2024-01-01T00:00:00Z"
        assert val_data["backtest_end"] == "2024-01-08T00:00:00Z"

    async def test_cli_live_mode_does_not_write_validation_report(
        self, tmp_path: Path
    ) -> None:
        """In live mode, no validation report should be produced."""
        finished_report = _make_ensemble_report()

        mock_runner = AsyncMock()
        mock_runner.initialize = AsyncMock()
        mock_runner.generate_report = MagicMock(return_value=finished_report)

        with (
            patch(
                "agent.strategies.ensemble.run.EnsembleRunner",
                return_value=mock_runner,
            ),
            # configure_agent_logging is imported lazily inside _cli_main — patch at source
            patch("agent.logging.configure_agent_logging"),
        ):
            await _cli_main(
                mode="live",
                base_url="http://localhost:8000",
                api_key="ak_live_test",
                symbols=["BTCUSDT"],
                days=7,
                seed=42,
                output_dir=tmp_path,
                no_rl=True,
                no_evolved=True,
                no_regime=True,
                no_risk=True,
            )

        validation_files = list(tmp_path.glob("validation-report-*.json"))
        assert len(validation_files) == 0, "validation report should not exist in live mode"
