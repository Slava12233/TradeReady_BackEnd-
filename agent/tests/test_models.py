"""Tests for agent/models/ — TradeSignal, MarketAnalysis, BacktestAnalysis,
WorkflowResult, and PlatformValidationReport."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.models.analysis import BacktestAnalysis, MarketAnalysis
from agent.models.report import PlatformValidationReport, WorkflowResult
from agent.models.trade_signal import SignalType, TradeSignal

# ---------------------------------------------------------------------------
# SignalType
# ---------------------------------------------------------------------------


class TestSignalType:
    """Tests for the SignalType string enum."""

    def test_values_are_lowercase_strings(self) -> None:
        """Enum members serialise as plain lowercase strings."""
        assert SignalType.BUY == "buy"
        assert SignalType.SELL == "sell"
        assert SignalType.HOLD == "hold"

    def test_is_str_subclass(self) -> None:
        """SignalType inherits from str for JSON-compatible serialisation."""
        assert isinstance(SignalType.BUY, str)

    def test_all_three_members_exist(self) -> None:
        """All three expected members are present."""
        members = {m.value for m in SignalType}
        assert members == {"buy", "sell", "hold"}


# ---------------------------------------------------------------------------
# TradeSignal
# ---------------------------------------------------------------------------


class TestTradeSignal:
    """Tests for agent/models/trade_signal.py :: TradeSignal."""

    def _valid_kwargs(self) -> dict:
        return {
            "symbol": "BTCUSDT",
            "signal": SignalType.BUY,
            "confidence": 0.72,
            "quantity_pct": 0.05,
            "reasoning": "20-SMA crossed above 50-SMA.",
            "risk_notes": "FOMC in 2 h.",
        }

    def test_construct_valid_buy_signal(self) -> None:
        """Happy path: all fields valid, BUY signal."""
        sig = TradeSignal(**self._valid_kwargs())
        assert sig.symbol == "BTCUSDT"
        assert sig.signal == SignalType.BUY
        assert sig.confidence == 0.72
        assert sig.quantity_pct == 0.05

    def test_construct_sell_signal(self) -> None:
        """SELL signal type constructs correctly."""
        kwargs = self._valid_kwargs()
        kwargs["signal"] = SignalType.SELL
        sig = TradeSignal(**kwargs)
        assert sig.signal == SignalType.SELL

    def test_construct_hold_signal(self) -> None:
        """HOLD signal type constructs correctly."""
        kwargs = self._valid_kwargs()
        kwargs["signal"] = SignalType.HOLD
        sig = TradeSignal(**kwargs)
        assert sig.signal == SignalType.HOLD

    def test_round_trip_model_dump_and_validate(self) -> None:
        """model_dump() round-trips cleanly through model_validate()."""
        original = TradeSignal(**self._valid_kwargs())
        dumped = original.model_dump()
        restored = TradeSignal.model_validate(dumped)
        assert restored == original

    def test_confidence_boundary_zero(self) -> None:
        """confidence=0.0 is a valid lower bound."""
        kwargs = self._valid_kwargs()
        kwargs["confidence"] = 0.0
        sig = TradeSignal(**kwargs)
        assert sig.confidence == 0.0

    def test_confidence_boundary_one(self) -> None:
        """confidence=1.0 is a valid upper bound."""
        kwargs = self._valid_kwargs()
        kwargs["confidence"] = 1.0
        sig = TradeSignal(**kwargs)
        assert sig.confidence == 1.0

    def test_confidence_above_one_raises(self) -> None:
        """confidence > 1.0 is rejected by Pydantic validation."""
        kwargs = self._valid_kwargs()
        kwargs["confidence"] = 1.01
        with pytest.raises(ValidationError, match="confidence"):
            TradeSignal(**kwargs)

    def test_confidence_below_zero_raises(self) -> None:
        """confidence < 0.0 is rejected by Pydantic validation."""
        kwargs = self._valid_kwargs()
        kwargs["confidence"] = -0.01
        with pytest.raises(ValidationError, match="confidence"):
            TradeSignal(**kwargs)

    def test_quantity_pct_boundary_min(self) -> None:
        """quantity_pct=0.01 is the valid lower bound."""
        kwargs = self._valid_kwargs()
        kwargs["quantity_pct"] = 0.01
        sig = TradeSignal(**kwargs)
        assert sig.quantity_pct == 0.01

    def test_quantity_pct_boundary_max(self) -> None:
        """quantity_pct=0.10 is the valid upper bound."""
        kwargs = self._valid_kwargs()
        kwargs["quantity_pct"] = 0.10
        sig = TradeSignal(**kwargs)
        assert sig.quantity_pct == 0.10

    def test_quantity_pct_below_min_raises(self) -> None:
        """quantity_pct below 0.01 is rejected."""
        kwargs = self._valid_kwargs()
        kwargs["quantity_pct"] = 0.009
        with pytest.raises(ValidationError, match="quantity_pct"):
            TradeSignal(**kwargs)

    def test_quantity_pct_above_max_raises(self) -> None:
        """quantity_pct above 0.10 is rejected."""
        kwargs = self._valid_kwargs()
        kwargs["quantity_pct"] = 0.11
        with pytest.raises(ValidationError, match="quantity_pct"):
            TradeSignal(**kwargs)

    def test_frozen_immutability(self) -> None:
        """Assigning to a field on a frozen model raises an error."""
        sig = TradeSignal(**self._valid_kwargs())
        with pytest.raises(Exception):
            sig.symbol = "ETHUSDT"  # type: ignore[misc]

    def test_missing_required_field_raises(self) -> None:
        """Omitting a required field raises ValidationError."""
        kwargs = self._valid_kwargs()
        del kwargs["reasoning"]
        with pytest.raises(ValidationError, match="reasoning"):
            TradeSignal(**kwargs)

    def test_signal_accepts_string_coercion(self) -> None:
        """signal field accepts plain string values that match enum members."""
        kwargs = self._valid_kwargs()
        kwargs["signal"] = "sell"
        sig = TradeSignal(**kwargs)
        assert sig.signal == SignalType.SELL


# ---------------------------------------------------------------------------
# MarketAnalysis
# ---------------------------------------------------------------------------


class TestMarketAnalysis:
    """Tests for agent/models/analysis.py :: MarketAnalysis."""

    def _valid_kwargs(self) -> dict:
        return {
            "symbol": "ETHUSDT",
            "trend": "bullish",
            "support_level": "2900.00",
            "resistance_level": "3200.00",
            "indicators": {"rsi_14": 58.3, "sma_20": 3050.12},
            "summary": "ETH holding above 20-SMA with RSI in healthy territory.",
        }

    def test_construct_valid(self) -> None:
        """Happy path: all fields valid."""
        ma = MarketAnalysis(**self._valid_kwargs())
        assert ma.symbol == "ETHUSDT"
        assert ma.trend == "bullish"
        assert ma.support_level == "2900.00"
        assert ma.resistance_level == "3200.00"
        assert ma.indicators["rsi_14"] == 58.3

    def test_indicators_default_empty_dict(self) -> None:
        """indicators defaults to an empty dict when not supplied."""
        kwargs = self._valid_kwargs()
        del kwargs["indicators"]
        ma = MarketAnalysis(**kwargs)
        assert ma.indicators == {}

    def test_round_trip(self) -> None:
        """model_dump() + model_validate() restores an equal object."""
        original = MarketAnalysis(**self._valid_kwargs())
        restored = MarketAnalysis.model_validate(original.model_dump())
        assert restored == original

    def test_frozen_immutability(self) -> None:
        """Frozen model rejects field assignment."""
        ma = MarketAnalysis(**self._valid_kwargs())
        with pytest.raises(Exception):
            ma.trend = "bearish"  # type: ignore[misc]

    def test_missing_required_field_raises(self) -> None:
        """Omitting summary raises ValidationError."""
        kwargs = self._valid_kwargs()
        del kwargs["summary"]
        with pytest.raises(ValidationError, match="summary"):
            MarketAnalysis(**kwargs)

    def test_nested_indicator_dict(self) -> None:
        """indicators can hold nested dicts (e.g. MACD sub-dict)."""
        kwargs = self._valid_kwargs()
        kwargs["indicators"] = {"macd": {"macd": 12.5, "signal": 10.0, "hist": 2.5}}
        ma = MarketAnalysis(**kwargs)
        assert ma.indicators["macd"]["hist"] == 2.5


# ---------------------------------------------------------------------------
# BacktestAnalysis
# ---------------------------------------------------------------------------


class TestBacktestAnalysis:
    """Tests for agent/models/analysis.py :: BacktestAnalysis."""

    def _valid_kwargs(self) -> dict:
        return {
            "session_id": "a1b2c3d4-0000-0000-0000-000000000000",
            "sharpe_ratio": 1.42,
            "max_drawdown": 0.08,
            "win_rate": 0.61,
            "total_trades": 34,
            "pnl": "182.40",
            "improvement_plan": ["Tighten stop-loss to 1.5 %", "Add volume filter"],
        }

    def test_construct_valid(self) -> None:
        """Happy path: all fields valid."""
        ba = BacktestAnalysis(**self._valid_kwargs())
        assert ba.session_id == "a1b2c3d4-0000-0000-0000-000000000000"
        assert ba.sharpe_ratio == 1.42
        assert ba.max_drawdown == 0.08
        assert ba.win_rate == 0.61
        assert ba.total_trades == 34
        assert ba.pnl == "182.40"
        assert len(ba.improvement_plan) == 2

    def test_round_trip(self) -> None:
        """model_dump() + model_validate() returns equal object."""
        original = BacktestAnalysis(**self._valid_kwargs())
        restored = BacktestAnalysis.model_validate(original.model_dump())
        assert restored == original

    def test_max_drawdown_boundary_zero(self) -> None:
        """max_drawdown=0.0 is valid."""
        kwargs = self._valid_kwargs()
        kwargs["max_drawdown"] = 0.0
        ba = BacktestAnalysis(**kwargs)
        assert ba.max_drawdown == 0.0

    def test_max_drawdown_boundary_one(self) -> None:
        """max_drawdown=1.0 is valid (total loss)."""
        kwargs = self._valid_kwargs()
        kwargs["max_drawdown"] = 1.0
        ba = BacktestAnalysis(**kwargs)
        assert ba.max_drawdown == 1.0

    def test_max_drawdown_above_one_raises(self) -> None:
        """max_drawdown > 1.0 is rejected."""
        kwargs = self._valid_kwargs()
        kwargs["max_drawdown"] = 1.01
        with pytest.raises(ValidationError, match="max_drawdown"):
            BacktestAnalysis(**kwargs)

    def test_win_rate_boundary(self) -> None:
        """win_rate 0.0 and 1.0 are both valid boundaries."""
        for val in (0.0, 1.0):
            kwargs = self._valid_kwargs()
            kwargs["win_rate"] = val
            ba = BacktestAnalysis(**kwargs)
            assert ba.win_rate == val

    def test_win_rate_out_of_range_raises(self) -> None:
        """win_rate outside [0, 1] raises ValidationError."""
        for val in (-0.01, 1.01):
            kwargs = self._valid_kwargs()
            kwargs["win_rate"] = val
            with pytest.raises(ValidationError, match="win_rate"):
                BacktestAnalysis(**kwargs)

    def test_total_trades_zero_valid(self) -> None:
        """total_trades=0 is valid (no trades executed)."""
        kwargs = self._valid_kwargs()
        kwargs["total_trades"] = 0
        ba = BacktestAnalysis(**kwargs)
        assert ba.total_trades == 0

    def test_total_trades_negative_raises(self) -> None:
        """Negative total_trades is rejected."""
        kwargs = self._valid_kwargs()
        kwargs["total_trades"] = -1
        with pytest.raises(ValidationError, match="total_trades"):
            BacktestAnalysis(**kwargs)

    def test_improvement_plan_defaults_empty(self) -> None:
        """improvement_plan defaults to empty list when not supplied."""
        kwargs = self._valid_kwargs()
        del kwargs["improvement_plan"]
        ba = BacktestAnalysis(**kwargs)
        assert ba.improvement_plan == []

    def test_frozen_immutability(self) -> None:
        """Frozen model rejects field assignment."""
        ba = BacktestAnalysis(**self._valid_kwargs())
        with pytest.raises(Exception):
            ba.pnl = "999.99"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# WorkflowResult
# ---------------------------------------------------------------------------


class TestWorkflowResult:
    """Tests for agent/models/report.py :: WorkflowResult."""

    def _valid_kwargs(self) -> dict:
        return {
            "workflow_name": "smoke_test",
            "status": "pass",
            "steps_completed": 5,
            "steps_total": 5,
            "findings": ["API responded within 200 ms"],
            "bugs_found": [],
            "suggestions": ["Expose Sortino in /results"],
            "metrics": {"avg_latency_ms": 180},
        }

    def test_construct_pass_status(self) -> None:
        """status='pass' is a valid value."""
        wr = WorkflowResult(**self._valid_kwargs())
        assert wr.status == "pass"
        assert wr.steps_completed == 5

    def test_status_fail(self) -> None:
        """status='fail' is a valid value."""
        kwargs = self._valid_kwargs()
        kwargs["status"] = "fail"
        wr = WorkflowResult(**kwargs)
        assert wr.status == "fail"

    def test_status_partial(self) -> None:
        """status='partial' is a valid value."""
        kwargs = self._valid_kwargs()
        kwargs["status"] = "partial"
        wr = WorkflowResult(**kwargs)
        assert wr.status == "partial"

    def test_invalid_status_raises(self) -> None:
        """A status value outside pass/fail/partial is rejected by the pattern."""
        kwargs = self._valid_kwargs()
        kwargs["status"] = "unknown"
        with pytest.raises(ValidationError, match="status"):
            WorkflowResult(**kwargs)

    def test_empty_status_raises(self) -> None:
        """An empty status string is rejected."""
        kwargs = self._valid_kwargs()
        kwargs["status"] = ""
        with pytest.raises(ValidationError, match="status"):
            WorkflowResult(**kwargs)

    def test_lists_default_to_empty(self) -> None:
        """findings, bugs_found, suggestions, and metrics default when omitted."""
        wr = WorkflowResult(
            workflow_name="minimal",
            status="pass",
            steps_completed=1,
            steps_total=1,
        )
        assert wr.findings == []
        assert wr.bugs_found == []
        assert wr.suggestions == []
        assert wr.metrics == {}

    def test_round_trip(self) -> None:
        """model_dump() + model_validate() returns equal object."""
        original = WorkflowResult(**self._valid_kwargs())
        restored = WorkflowResult.model_validate(original.model_dump())
        assert restored == original

    def test_frozen_immutability(self) -> None:
        """Frozen model rejects field assignment."""
        wr = WorkflowResult(**self._valid_kwargs())
        with pytest.raises(Exception):
            wr.status = "fail"  # type: ignore[misc]

    def test_steps_completed_zero_valid(self) -> None:
        """steps_completed=0 is valid (no steps finished)."""
        kwargs = self._valid_kwargs()
        kwargs["steps_completed"] = 0
        wr = WorkflowResult(**kwargs)
        assert wr.steps_completed == 0

    def test_negative_steps_raises(self) -> None:
        """Negative steps values are rejected."""
        for field in ("steps_completed", "steps_total"):
            kwargs = self._valid_kwargs()
            kwargs[field] = -1
            with pytest.raises(ValidationError, match=field):
                WorkflowResult(**kwargs)


# ---------------------------------------------------------------------------
# PlatformValidationReport
# ---------------------------------------------------------------------------


class TestPlatformValidationReport:
    """Tests for agent/models/report.py :: PlatformValidationReport."""

    def _make_workflow_result(self, name: str = "smoke_test", status: str = "pass") -> WorkflowResult:
        return WorkflowResult(
            workflow_name=name,
            status=status,
            steps_completed=3,
            steps_total=3,
        )

    def _valid_kwargs(self) -> dict:
        return {
            "session_id": "sess_001",
            "model_used": "openrouter:anthropic/claude-sonnet-4-5",
            "workflows_run": [self._make_workflow_result()],
            "platform_health": "healthy",
            "summary": "All workflows passed. Platform is healthy.",
        }

    def test_construct_valid(self) -> None:
        """Happy path: all fields valid."""
        report = PlatformValidationReport(**self._valid_kwargs())
        assert report.session_id == "sess_001"
        assert report.platform_health == "healthy"
        assert len(report.workflows_run) == 1

    def test_platform_health_degraded(self) -> None:
        """platform_health='degraded' is valid."""
        kwargs = self._valid_kwargs()
        kwargs["platform_health"] = "degraded"
        report = PlatformValidationReport(**kwargs)
        assert report.platform_health == "degraded"

    def test_platform_health_broken(self) -> None:
        """platform_health='broken' is valid."""
        kwargs = self._valid_kwargs()
        kwargs["platform_health"] = "broken"
        report = PlatformValidationReport(**kwargs)
        assert report.platform_health == "broken"

    def test_invalid_platform_health_raises(self) -> None:
        """A platform_health value outside the allowed set is rejected."""
        kwargs = self._valid_kwargs()
        kwargs["platform_health"] = "ok"
        with pytest.raises(ValidationError, match="platform_health"):
            PlatformValidationReport(**kwargs)

    def test_workflows_run_defaults_empty(self) -> None:
        """workflows_run defaults to an empty list when omitted."""
        kwargs = self._valid_kwargs()
        del kwargs["workflows_run"]
        report = PlatformValidationReport(**kwargs)
        assert report.workflows_run == []

    def test_multiple_workflow_results(self) -> None:
        """workflows_run can hold multiple WorkflowResult objects."""
        kwargs = self._valid_kwargs()
        kwargs["workflows_run"] = [
            self._make_workflow_result("smoke_test", "pass"),
            self._make_workflow_result("trading_workflow", "partial"),
            self._make_workflow_result("backtest_workflow", "fail"),
        ]
        report = PlatformValidationReport(**kwargs)
        assert len(report.workflows_run) == 3
        assert report.workflows_run[1].status == "partial"

    def test_round_trip(self) -> None:
        """model_dump() + model_validate() returns equal object."""
        original = PlatformValidationReport(**self._valid_kwargs())
        restored = PlatformValidationReport.model_validate(original.model_dump())
        assert restored == original

    def test_frozen_immutability(self) -> None:
        """Frozen model rejects field assignment."""
        report = PlatformValidationReport(**self._valid_kwargs())
        with pytest.raises(Exception):
            report.platform_health = "degraded"  # type: ignore[misc]

    def test_nested_workflow_round_trip(self) -> None:
        """Nested WorkflowResult objects survive serialisation round-trip."""
        original = PlatformValidationReport(**self._valid_kwargs())
        dumped = original.model_dump()
        # The nested WorkflowResult should serialise to a plain dict
        assert isinstance(dumped["workflows_run"][0], dict)
        assert dumped["workflows_run"][0]["workflow_name"] == "smoke_test"
        restored = PlatformValidationReport.model_validate(dumped)
        assert restored.workflows_run[0].workflow_name == "smoke_test"
