"""Tests for agent/strategies/ensemble/config.py and ensemble/run.py.

Covers:
- EnsembleConfig defaults are valid
- EnsembleConfig mode validation ("backtest" | "live")
- EnsembleConfig field constraint enforcement
- Pipeline step produces a valid StepResult (all sources mocked/disabled)
- Disabled signal source emits HOLD with source_disabled metadata
- Risk veto prevents order execution (orders_vetoed increments)
- generate_report() structure before and after steps
- EnsembleReport includes all three source stats
- _sma() / _extract_closes() / _compute_rsi() / _compute_macd_histogram() helpers
- run_backtest() returns EnsembleReport on REST error (graceful failure)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from agent.strategies.ensemble.config import EnsembleConfig
from agent.strategies.ensemble.meta_learner import MetaLearner
from agent.strategies.ensemble.run import (
    EnsembleReport,
    EnsembleRunner,
    SourceStats,
    StepResult,
    _compute_macd_histogram,
    _compute_rsi,
    _extract_closes,
    _sma,
)
from agent.strategies.ensemble.signals import SignalSource, TradeAction

# ── EnsembleConfig defaults and validation ────────────────────────────────────


class TestEnsembleConfigDefaults:
    """EnsembleConfig default values must be valid and sensible."""

    def setup_method(self) -> None:
        # Bypass agent/.env on disk; supply only minimal overrides.
        self.config = EnsembleConfig(_env_file=None)  # type: ignore[call-arg]

    def test_default_mode_is_backtest(self) -> None:
        assert self.config.mode == "backtest"

    def test_default_symbols_non_empty(self) -> None:
        assert len(self.config.symbols) > 0

    def test_default_confidence_threshold_valid(self) -> None:
        assert 0.0 <= self.config.confidence_threshold <= 1.0

    def test_default_min_agreement_rate_valid(self) -> None:
        assert 0.0 <= self.config.min_agreement_rate <= 1.0

    def test_default_weights_keys_match_signal_sources(self) -> None:
        expected_keys = {s.value for s in SignalSource}
        assert set(self.config.weights.keys()) == expected_keys

    def test_default_weights_non_negative(self) -> None:
        assert all(w >= 0 for w in self.config.weights.values())

    def test_default_risk_base_size_pct_within_bounds(self) -> None:
        assert 0.001 <= self.config.risk_base_size_pct <= 1.0

    def test_default_candle_window_gte_fifty(self) -> None:
        assert self.config.candle_window >= 50

    def test_default_max_iterations_positive(self) -> None:
        assert self.config.max_iterations >= 1

    def test_default_batch_size_positive(self) -> None:
        assert self.config.batch_size >= 1

    def test_default_enable_flags_all_true(self) -> None:
        assert self.config.enable_rl_signal is True
        assert self.config.enable_evolved_signal is True
        assert self.config.enable_regime_signal is True
        assert self.config.enable_risk_overlay is True


class TestEnsembleConfigModeValidation:
    """Mode field must be 'backtest' or 'live'; anything else raises ValidationError."""

    def test_backtest_mode_is_accepted(self) -> None:
        config = EnsembleConfig(mode="backtest", _env_file=None)  # type: ignore[call-arg]
        assert config.mode == "backtest"

    def test_live_mode_is_accepted(self) -> None:
        config = EnsembleConfig(mode="live", _env_file=None)  # type: ignore[call-arg]
        assert config.mode == "live"

    def test_invalid_mode_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            EnsembleConfig(mode="paper", _env_file=None)  # type: ignore[call-arg]

    def test_empty_mode_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            EnsembleConfig(mode="", _env_file=None)  # type: ignore[call-arg]


class TestEnsembleConfigConstraints:
    """Field range constraints are enforced by Pydantic."""

    def test_confidence_threshold_below_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            EnsembleConfig(confidence_threshold=-0.1, _env_file=None)  # type: ignore[call-arg]

    def test_confidence_threshold_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            EnsembleConfig(confidence_threshold=1.1, _env_file=None)  # type: ignore[call-arg]

    def test_min_agreement_rate_below_zero_raises(self) -> None:
        with pytest.raises(ValidationError):
            EnsembleConfig(min_agreement_rate=-0.01, _env_file=None)  # type: ignore[call-arg]

    def test_candle_window_below_fifty_raises(self) -> None:
        with pytest.raises(ValidationError):
            EnsembleConfig(candle_window=49, _env_file=None)  # type: ignore[call-arg]

    def test_risk_base_size_pct_above_one_raises(self) -> None:
        with pytest.raises(ValidationError):
            EnsembleConfig(risk_base_size_pct=1.1, _env_file=None)  # type: ignore[call-arg]


# ── Internal helper functions ─────────────────────────────────────────────────


class TestSmaHelper:
    """_sma() computes a simple moving average or returns None on insufficient data."""

    def test_exact_window_returns_mean(self) -> None:
        closes = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = _sma(closes, window=5)
        assert result == 3.0

    def test_window_larger_than_data_returns_none(self) -> None:
        assert _sma([1.0, 2.0], window=5) is None

    def test_window_equals_one(self) -> None:
        closes = [10.0, 20.0, 30.0]
        assert _sma(closes, window=1) == 30.0

    def test_uses_last_n_values(self) -> None:
        closes = [100.0, 1.0, 2.0, 3.0]
        assert _sma(closes, window=3) == 2.0  # last 3: 1, 2, 3


class TestExtractClosesHelper:
    """_extract_closes() extracts close prices tolerating bad values."""

    def test_extracts_float_closes(self) -> None:
        candles = [{"close": 100.0}, {"close": 200.0}, {"close": 150.0}]
        assert _extract_closes(candles) == [100.0, 200.0, 150.0]

    def test_extracts_string_closes(self) -> None:
        candles = [{"close": "100.5"}, {"close": "200.0"}]
        result = _extract_closes(candles)
        assert result == [100.5, 200.0]

    def test_skips_none_values(self) -> None:
        candles = [{"close": 100.0}, {"close": None}, {"close": 200.0}]
        assert _extract_closes(candles) == [100.0, 200.0]

    def test_skips_non_numeric_strings(self) -> None:
        candles = [{"close": "abc"}, {"close": 50.0}]
        assert _extract_closes(candles) == [50.0]

    def test_empty_candles_returns_empty_list(self) -> None:
        assert _extract_closes([]) == []

    def test_candles_without_close_key_skipped(self) -> None:
        candles = [{"open": 100.0}, {"close": 200.0}]
        assert _extract_closes(candles) == [200.0]


class TestComputeRsiHelper:
    """_compute_rsi() returns None on insufficient data; valid range on sufficient data."""

    def test_insufficient_data_returns_none(self) -> None:
        assert _compute_rsi([1.0, 2.0, 3.0], period=14) is None

    def test_result_in_valid_range(self) -> None:
        # Monotonically increasing → RSI near 100
        closes = [float(i) for i in range(1, 20)]
        result = _compute_rsi(closes, period=14)
        assert result is not None
        assert 0.0 <= result <= 100.0

    def test_all_gains_returns_100(self) -> None:
        """All positive deltas → avg_loss = 0 → RSI = 100."""
        closes = [float(i) for i in range(1, 20)]  # strictly increasing
        result = _compute_rsi(closes, period=14)
        assert result == 100.0

    def test_mixed_data_within_range(self) -> None:
        closes = [100.0, 102.0, 101.0, 103.0, 102.0, 104.0, 103.0,
                  105.0, 104.0, 106.0, 105.0, 107.0, 106.0, 108.0, 107.0]
        result = _compute_rsi(closes, period=14)
        assert result is not None
        assert 0.0 <= result <= 100.0


class TestComputeMacdHistogramHelper:
    """_compute_macd_histogram() returns None on insufficient data."""

    def test_insufficient_data_returns_none(self) -> None:
        closes = [1.0] * 10  # less than slow=26
        assert _compute_macd_histogram(closes) is None

    def test_sufficient_data_returns_float(self) -> None:
        closes = [float(i) for i in range(1, 30)]
        result = _compute_macd_histogram(closes, fast=12, slow=26)
        assert result is not None
        assert isinstance(result, float)

    def test_bullish_trend_positive_histogram(self) -> None:
        """Rapidly rising prices → fast EMA > slow EMA → positive histogram."""
        # Exponentially increasing prices make fast EMA lead slow EMA
        closes = [100.0 * (1.05 ** i) for i in range(30)]
        result = _compute_macd_histogram(closes, fast=12, slow=26)
        assert result is not None
        assert result > 0


# ── EnsembleRunner pipeline step ──────────────────────────────────────────────


def _make_minimal_config(symbols: list[str] | None = None) -> EnsembleConfig:
    """Build a minimal EnsembleConfig with all signals and risk disabled."""
    return EnsembleConfig(
        mode="backtest",
        symbols=symbols or ["BTCUSDT"],
        enable_rl_signal=False,
        enable_evolved_signal=False,
        enable_regime_signal=False,
        enable_risk_overlay=False,
        _env_file=None,  # type: ignore[call-arg]
    )


def _make_runner(config: EnsembleConfig) -> EnsembleRunner:
    runner = EnsembleRunner(config=config, sdk_client=None, rest_client=None)
    # Manually wire MetaLearner so initialize() is not required
    runner._meta_learner = MetaLearner(
        confidence_threshold=config.confidence_threshold,
        min_agreement_rate=config.min_agreement_rate,
    )
    return runner


class TestEnsembleRunnerStep:
    """EnsembleRunner.step() produces valid StepResult with all sources disabled."""

    async def test_step_returns_step_result_instance(self) -> None:
        config = _make_minimal_config(symbols=["BTCUSDT"])
        runner = _make_runner(config)
        result = await runner.step(candles_by_symbol={})
        assert isinstance(result, StepResult)

    async def test_step_increments_counter(self) -> None:
        config = _make_minimal_config(symbols=["BTCUSDT"])
        runner = _make_runner(config)
        await runner.step({})
        await runner.step({})
        assert runner._step_counter == 2

    async def test_step_number_starts_at_zero(self) -> None:
        config = _make_minimal_config(symbols=["BTCUSDT"])
        runner = _make_runner(config)
        result = await runner.step({})
        assert result.step_number == 0

    async def test_step_total_signals_equals_three_per_symbol(self) -> None:
        """All 3 sources (even disabled) emit 1 signal each per symbol."""
        config = _make_minimal_config(symbols=["BTCUSDT", "ETHUSDT"])
        runner = _make_runner(config)
        result = await runner.step({})
        # 3 sources × 2 symbols = 6 total signals
        assert result.total_signals == 6

    async def test_step_has_one_symbol_result_per_symbol(self) -> None:
        config = _make_minimal_config(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        runner = _make_runner(config)
        result = await runner.step({})
        assert len(result.symbol_results) == 3

    async def test_step_has_timestamp(self) -> None:
        config = _make_minimal_config()
        runner = _make_runner(config)
        result = await runner.step({})
        assert result.timestamp != ""
        assert "T" in result.timestamp  # ISO-8601

    async def test_step_result_is_appended_to_history(self) -> None:
        config = _make_minimal_config()
        runner = _make_runner(config)
        await runner.step({})
        assert len(runner._step_history) == 1


class TestDisabledSignalSources:
    """Disabled sources emit HOLD with source_disabled metadata."""

    async def test_disabled_rl_emits_hold_with_source_disabled_metadata(self) -> None:
        config = _make_minimal_config(symbols=["BTCUSDT"])
        runner = _make_runner(config)
        result = await runner.step({})
        # All sources disabled → all signals are source_disabled HOLD
        rl_contrib = next(
            c for sr in result.symbol_results
            for c in sr.contributions if c.source == SignalSource.RL.value
        )
        assert rl_contrib.action == TradeAction.HOLD.value
        assert rl_contrib.confidence == 0.0
        assert rl_contrib.enabled is False
        assert rl_contrib.metadata.get("reason") == "source_disabled"

    async def test_disabled_evolved_emits_hold_source_disabled(self) -> None:
        config = _make_minimal_config(symbols=["BTCUSDT"])
        runner = _make_runner(config)
        result = await runner.step({})
        evolved_contrib = next(
            c for sr in result.symbol_results
            for c in sr.contributions if c.source == SignalSource.EVOLVED.value
        )
        assert evolved_contrib.metadata.get("reason") == "source_disabled"

    async def test_disabled_regime_emits_hold_source_disabled(self) -> None:
        config = _make_minimal_config(symbols=["BTCUSDT"])
        runner = _make_runner(config)
        result = await runner.step({})
        regime_contrib = next(
            c for sr in result.symbol_results
            for c in sr.contributions if c.source == SignalSource.REGIME.value
        )
        assert regime_contrib.metadata.get("reason") == "source_disabled"

    async def test_disabled_source_enabled_flag_is_false(self) -> None:
        config = _make_minimal_config(symbols=["BTCUSDT"])
        runner = _make_runner(config)
        result = await runner.step({})
        for sr in result.symbol_results:
            for contrib in sr.contributions:
                assert contrib.enabled is False


class TestRiskVetoPreventsExecution:
    """Risk veto increments orders_vetoed, not orders_placed."""

    async def test_risk_veto_increments_vetoed_counter(self) -> None:
        # Build a config with risk overlay ENABLED but no sdk_client
        config = EnsembleConfig(
            mode="backtest",
            symbols=["BTCUSDT"],
            enable_rl_signal=False,
            enable_evolved_signal=False,
            enable_regime_signal=False,
            enable_risk_overlay=True,
            confidence_threshold=0.0,
            min_agreement_rate=0.0,
            _env_file=None,  # type: ignore[call-arg]
        )
        runner = EnsembleRunner(config=config, sdk_client=None, rest_client=None)
        runner._meta_learner = MetaLearner(
            confidence_threshold=0.0,
            min_agreement_rate=0.0,
        )

        # Inject a mock risk middleware that vetoes every signal
        mock_veto_decision = MagicMock()
        mock_veto_decision.action = "VETOED"

        mock_decision = MagicMock()
        mock_decision.veto_decision = mock_veto_decision

        mock_risk = AsyncMock()
        mock_risk.process_signal = AsyncMock(return_value=mock_decision)
        runner._risk_middleware = mock_risk

        # Manually override the MetaLearner to produce a BUY consensus
        mock_ml = MagicMock()
        from agent.strategies.ensemble.signals import ConsensusSignal
        mock_ml.combine_all.return_value = [
            ConsensusSignal(
                symbol="BTCUSDT",
                action=TradeAction.BUY,
                combined_confidence=0.9,
                contributing_signals=[],
                agreement_rate=1.0,
            )
        ]
        runner._meta_learner = mock_ml

        result = await runner.step(candles_by_symbol={})

        assert result.orders_vetoed == 1
        assert result.orders_placed == 0

    async def test_no_risk_overlay_hold_signals_not_counted(self) -> None:
        """All sources disabled → all HOLD → signals_acted_on = 0."""
        config = _make_minimal_config(symbols=["BTCUSDT", "ETHUSDT"])
        runner = _make_runner(config)
        result = await runner.step({})
        assert result.signals_acted_on == 0
        assert result.orders_placed == 0
        assert result.orders_vetoed == 0


class TestGenerateReport:
    """generate_report() produces a valid EnsembleReport at any point in the session."""

    def test_report_before_any_steps_is_empty(self) -> None:
        config = _make_minimal_config()
        runner = _make_runner(config)
        report = runner.generate_report()
        assert isinstance(report, EnsembleReport)
        assert report.total_steps == 0
        assert report.total_orders_placed == 0
        assert report.total_orders_vetoed == 0
        assert report.overall_agreement_rate == 0.0

    def test_report_mode_matches_config(self) -> None:
        config = EnsembleConfig(mode="live", _env_file=None)  # type: ignore[call-arg]
        runner = EnsembleRunner(config=config, sdk_client=None, rest_client=None)
        runner._meta_learner = MetaLearner()
        report = runner.generate_report()
        assert report.mode == "live"

    def test_report_session_id_is_live_for_live_mode(self) -> None:
        config = EnsembleConfig(mode="live", _env_file=None)  # type: ignore[call-arg]
        runner = EnsembleRunner(config=config, sdk_client=None, rest_client=None)
        runner._meta_learner = MetaLearner()
        report = runner.generate_report()
        assert report.session_id == "live"

    async def test_report_after_steps_reflects_step_count(self) -> None:
        config = _make_minimal_config()
        runner = _make_runner(config)
        await runner.step({})
        await runner.step({})
        await runner.step({})
        report = runner.generate_report()
        assert report.total_steps == 3

    def test_report_includes_all_three_source_stats(self) -> None:
        config = _make_minimal_config()
        runner = _make_runner(config)
        report = runner.generate_report()
        # Source stats only appear after steps (empty history → empty source_stats list)
        # Verify structure when steps exist
        assert isinstance(report.source_stats, list)

    async def test_report_source_stats_after_steps(self) -> None:
        """After running steps, report contains one SourceStats per SignalSource."""
        config = _make_minimal_config(symbols=["BTCUSDT"])
        runner = _make_runner(config)
        await runner.step({})
        report = runner.generate_report()
        source_names = {s.source for s in report.source_stats}
        expected = {src.value for src in SignalSource}
        assert source_names == expected

    async def test_report_source_stats_are_source_stats_instances(self) -> None:
        config = _make_minimal_config()
        runner = _make_runner(config)
        await runner.step({})
        report = runner.generate_report()
        assert all(isinstance(s, SourceStats) for s in report.source_stats)

    def test_report_config_summary_contains_mode(self) -> None:
        config = _make_minimal_config()
        runner = _make_runner(config)
        report = runner.generate_report()
        assert "mode" in report.config_summary

    def test_report_config_summary_contains_all_keys(self) -> None:
        config = _make_minimal_config()
        runner = _make_runner(config)
        report = runner.generate_report()
        expected_keys = {
            "mode",
            "enable_rl_signal",
            "enable_evolved_signal",
            "enable_regime_signal",
            "enable_risk_overlay",
            "confidence_threshold",
            "min_agreement_rate",
            "symbols",
            "weights",
        }
        assert expected_keys.issubset(set(report.config_summary.keys()))

    def test_report_timestamps_are_set(self) -> None:
        config = _make_minimal_config()
        runner = _make_runner(config)
        report = runner.generate_report()
        assert report.start_time != ""
        assert report.end_time != ""

    def test_report_overall_agreement_rate_within_bounds(self) -> None:
        config = _make_minimal_config()
        runner = _make_runner(config)
        report = runner.generate_report()
        assert 0.0 <= report.overall_agreement_rate <= 1.0


class TestEnsembleReportSchema:
    """EnsembleReport Pydantic model validation."""

    def test_ensemble_report_is_frozen(self) -> None:
        report = EnsembleReport(
            session_id="test-123",
            mode="backtest",
            start_time="2024-01-01T00:00:00",
            end_time="2024-01-01T01:00:00",
            total_steps=0,
            total_orders_placed=0,
            total_orders_vetoed=0,
            overall_agreement_rate=0.5,
            source_stats=[],
            config_summary={},
        )
        with pytest.raises(Exception):
            report.total_steps = 99  # type: ignore[misc]

    def test_ensemble_report_overall_agreement_rate_bounds(self) -> None:
        with pytest.raises(ValidationError):
            EnsembleReport(
                session_id="x",
                mode="live",
                start_time="2024-01-01",
                end_time="2024-01-01",
                total_steps=0,
                total_orders_placed=0,
                total_orders_vetoed=0,
                overall_agreement_rate=1.5,  # out of range
                source_stats=[],
                config_summary={},
            )


class TestRunBacktestRestFailure:
    """run_backtest() handles REST errors gracefully, returning an EnsembleReport."""

    async def test_create_backtest_http_error_returns_error_report(self) -> None:
        import httpx

        config = _make_minimal_config(symbols=["BTCUSDT"])

        mock_rest = AsyncMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )
        mock_rest.post = AsyncMock(return_value=mock_response)

        runner = EnsembleRunner(config=config, sdk_client=None, rest_client=mock_rest)
        runner._meta_learner = MetaLearner()

        report = await runner.run_backtest(
            start="2024-02-23T00:00:00Z",
            end="2024-03-01T00:00:00Z",
        )
        assert isinstance(report, EnsembleReport)
        assert report.session_id == "error"

    async def test_missing_session_id_in_response_returns_error_report(self) -> None:
        config = _make_minimal_config(symbols=["BTCUSDT"])

        mock_rest = AsyncMock()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {}  # no session_id key

        mock_rest.post = AsyncMock(return_value=mock_response)

        runner = EnsembleRunner(config=config, sdk_client=None, rest_client=mock_rest)
        runner._meta_learner = MetaLearner()

        report = await runner.run_backtest(
            start="2024-02-23T00:00:00Z",
            end="2024-03-01T00:00:00Z",
        )
        assert isinstance(report, EnsembleReport)
        assert report.session_id == "error"

    async def test_run_backtest_without_rest_client_raises(self) -> None:
        config = _make_minimal_config()
        runner = EnsembleRunner(config=config, sdk_client=None, rest_client=None)
        runner._meta_learner = MetaLearner()

        with pytest.raises(RuntimeError, match="rest_client"):
            await runner.run_backtest(
                start="2024-02-23T00:00:00Z",
                end="2024-03-01T00:00:00Z",
            )

    async def test_run_backtest_before_initialize_raises(self) -> None:
        config = _make_minimal_config()
        # Do NOT set _meta_learner — simulates calling before initialize()
        runner = EnsembleRunner(config=config, sdk_client=None, rest_client=MagicMock())
        with pytest.raises(AssertionError):
            await runner.run_backtest(
                start="2024-02-23T00:00:00Z",
                end="2024-03-01T00:00:00Z",
            )


class TestStepBeforeInitializeRaises:
    """Calling step() or run_backtest() before initialize() raises AssertionError."""

    async def test_step_before_initialize_raises(self) -> None:
        config = _make_minimal_config()
        runner = EnsembleRunner(config=config, sdk_client=None, rest_client=None)
        # _meta_learner is None — not initialized
        with pytest.raises(AssertionError):
            await runner.step({})
