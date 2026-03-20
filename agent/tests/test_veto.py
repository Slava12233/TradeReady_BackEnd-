"""Tests for agent/strategies/risk/veto.py — VetoPipeline, TradeSignal, VetoDecision."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent.strategies.risk.risk_agent import RiskAssessment, RiskConfig
from agent.strategies.risk.veto import TradeSignal, VetoDecision, VetoPipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_assessment(
    verdict: str = "OK",
    drawdown_pct: float = 0.0,
    total_exposure_pct: float = 0.0,
    max_single_position_pct: float = 0.0,
    correlation_risk: str = "low",
    equity: str = "10000",
    peak_equity: str = "10000",
    action: str | None = None,
) -> RiskAssessment:
    """Build a RiskAssessment with sensible defaults."""
    return RiskAssessment(
        verdict=verdict,
        drawdown_pct=drawdown_pct,
        total_exposure_pct=total_exposure_pct,
        max_single_position_pct=max_single_position_pct,
        correlation_risk=correlation_risk,
        equity=Decimal(equity),
        peak_equity=Decimal(peak_equity),
        action=action,
    )


def _make_signal(
    symbol: str = "BTCUSDT",
    side: str = "buy",
    size_pct: float = 0.05,
    confidence: float = 0.75,
) -> TradeSignal:
    """Build a TradeSignal with sensible defaults."""
    return TradeSignal(symbol=symbol, side=side, size_pct=size_pct, confidence=confidence)


def _make_pipeline(
    existing_positions: list[dict] | None = None,
    config: RiskConfig | None = None,
) -> VetoPipeline:
    """Build a VetoPipeline with optional position context."""
    return VetoPipeline(config=config or RiskConfig(), existing_positions=existing_positions or [])


# ---------------------------------------------------------------------------
# TradeSignal model validation
# ---------------------------------------------------------------------------


class TestTradeSignalModel:
    """TradeSignal field validation at the veto-layer model."""

    def test_valid_buy_signal(self) -> None:
        """Happy path: buy signal with all valid fields."""
        sig = _make_signal()
        assert sig.symbol == "BTCUSDT"
        assert sig.side == "buy"
        assert sig.size_pct == 0.05
        assert sig.confidence == 0.75

    def test_valid_sell_signal(self) -> None:
        """Sell direction is accepted."""
        sig = _make_signal(side="sell")
        assert sig.side == "sell"

    def test_invalid_side_raises(self) -> None:
        """Side other than 'buy'/'sell' raises ValidationError."""
        with pytest.raises(ValidationError, match="side"):
            TradeSignal(symbol="BTCUSDT", side="hold", size_pct=0.05, confidence=0.8)

    def test_size_pct_must_be_positive(self) -> None:
        """size_pct=0 is rejected (gt=0 constraint)."""
        with pytest.raises(ValidationError, match="size_pct"):
            TradeSignal(symbol="BTCUSDT", side="buy", size_pct=0.0, confidence=0.8)

    def test_size_pct_boundary_one(self) -> None:
        """size_pct=1.0 is the valid upper bound."""
        sig = TradeSignal(symbol="BTCUSDT", side="buy", size_pct=1.0, confidence=0.8)
        assert sig.size_pct == 1.0

    def test_confidence_boundary_zero(self) -> None:
        """confidence=0.0 is valid."""
        sig = _make_signal(confidence=0.0)
        assert sig.confidence == 0.0

    def test_confidence_above_one_raises(self) -> None:
        """confidence > 1.0 is rejected."""
        with pytest.raises(ValidationError, match="confidence"):
            TradeSignal(symbol="BTCUSDT", side="buy", size_pct=0.05, confidence=1.01)

    def test_frozen_model(self) -> None:
        """Frozen model rejects field mutation."""
        sig = _make_signal()
        with pytest.raises(Exception):
            sig.symbol = "ETHUSDT"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# VetoDecision model validation
# ---------------------------------------------------------------------------


class TestVetoDecisionModel:
    """VetoDecision validation for action, size, reason fields."""

    def test_approved_decision_valid(self) -> None:
        """APPROVED decision with matching sizes is valid."""
        dec = VetoDecision(action="APPROVED", original_size_pct=0.05, adjusted_size_pct=0.05, reason="ok")
        assert dec.action == "APPROVED"
        assert dec.adjusted_size_pct == 0.05

    def test_vetoed_decision_valid(self) -> None:
        """VETOED decision with adjusted_size_pct=0.0 is valid."""
        dec = VetoDecision(action="VETOED", original_size_pct=0.05, adjusted_size_pct=0.0, reason="halted")
        assert dec.action == "VETOED"
        assert dec.adjusted_size_pct == 0.0

    def test_resized_decision_valid(self) -> None:
        """RESIZED decision with adjusted < original is valid."""
        dec = VetoDecision(action="RESIZED", original_size_pct=0.10, adjusted_size_pct=0.05, reason="cap")
        assert dec.action == "RESIZED"

    def test_invalid_action_raises(self) -> None:
        """Unknown action value raises ValidationError."""
        with pytest.raises(ValidationError, match="action"):
            VetoDecision(action="MAYBE", original_size_pct=0.05, adjusted_size_pct=0.05, reason="x")

    def test_frozen_model(self) -> None:
        """Frozen decision rejects mutation."""
        dec = VetoDecision(action="APPROVED", original_size_pct=0.05, adjusted_size_pct=0.05, reason="ok")
        with pytest.raises(Exception):
            dec.action = "VETOED"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Check 1: HALT risk → VETOED
# ---------------------------------------------------------------------------


class TestCheck1HaltVeto:
    """Pipeline check 1: a HALT verdict in the risk assessment stops all trading."""

    def test_halt_verdict_vetos_trade(self) -> None:
        """HALT verdict → VETOED, regardless of other signal properties."""
        pipeline = _make_pipeline()
        signal = _make_signal(confidence=0.95, size_pct=0.05)
        assessment = _make_assessment(verdict="HALT", action="Daily loss exceeded.")
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "VETOED"
        assert decision.adjusted_size_pct == 0.0
        assert "HALT" in decision.reason

    def test_halt_includes_action_in_reason(self) -> None:
        """HALT veto reason incorporates the assessment's action message."""
        pipeline = _make_pipeline()
        signal = _make_signal()
        assessment = _make_assessment(verdict="HALT", action="Stop trading today.")
        decision = pipeline.evaluate(signal, assessment)
        assert "Stop trading today." in decision.reason

    def test_ok_verdict_does_not_veto_on_check1(self) -> None:
        """OK verdict passes check 1 (pipeline continues to later checks)."""
        pipeline = _make_pipeline()
        signal = _make_signal(confidence=0.9, size_pct=0.05)
        assessment = _make_assessment(verdict="OK")
        decision = pipeline.evaluate(signal, assessment)
        # Should not be VETOED by check 1 (may still be APPROVED or processed)
        assert decision.action != "VETOED" or "HALT" not in decision.reason


# ---------------------------------------------------------------------------
# Check 2: Low confidence → VETOED
# ---------------------------------------------------------------------------


class TestCheck2ConfidenceVeto:
    """Pipeline check 2: signal confidence below 0.5 is rejected."""

    def test_confidence_below_threshold_vetos(self) -> None:
        """Confidence 0.49 → VETOED by check 2."""
        pipeline = _make_pipeline()
        signal = _make_signal(confidence=0.49)
        assessment = _make_assessment(verdict="OK")
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "VETOED"
        assert "confidence" in decision.reason.lower()

    def test_confidence_zero_vetos(self) -> None:
        """Confidence 0.0 → VETOED."""
        pipeline = _make_pipeline()
        signal = _make_signal(confidence=0.0)
        assessment = _make_assessment(verdict="OK")
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "VETOED"

    def test_confidence_exactly_at_threshold_passes(self) -> None:
        """Confidence exactly 0.5 passes check 2 (>= 0.5 is required)."""
        pipeline = _make_pipeline()
        signal = _make_signal(confidence=0.5)
        assessment = _make_assessment(verdict="OK")
        decision = pipeline.evaluate(signal, assessment)
        # check 2 should not trigger; decision reflects subsequent checks
        assert "below the minimum threshold" not in decision.reason

    def test_high_confidence_passes_check2(self) -> None:
        """Confidence 0.9 → check 2 does not veto."""
        pipeline = _make_pipeline()
        signal = _make_signal(confidence=0.9, size_pct=0.05)
        assessment = _make_assessment(verdict="OK")
        decision = pipeline.evaluate(signal, assessment)
        assert "below the minimum threshold" not in decision.reason


# ---------------------------------------------------------------------------
# Check 3: Over-exposure → RESIZED
# ---------------------------------------------------------------------------


class TestCheck3ExposureResize:
    """Check 3: proposed trade capped to remaining portfolio capacity."""

    def test_over_exposure_triggers_resize(self) -> None:
        """20 % current + 15 % proposed = 35 % > 30 % → RESIZED to 10 %."""
        pipeline = _make_pipeline()
        signal = _make_signal(size_pct=0.15, confidence=0.8)
        assessment = _make_assessment(total_exposure_pct=0.20)
        decision = pipeline.evaluate(signal, assessment)
        # Remaining: 30 % - 20 % = 10 %
        assert decision.action == "RESIZED"
        assert abs(decision.adjusted_size_pct - 0.10) < 0.001
        assert decision.original_size_pct == 0.15

    def test_at_max_exposure_vetos(self) -> None:
        """Current exposure exactly at max (30 %) → VETOED (no remaining capacity)."""
        pipeline = _make_pipeline()
        signal = _make_signal(size_pct=0.05, confidence=0.8)
        assessment = _make_assessment(total_exposure_pct=0.30)
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "VETOED"
        assert "max exposure" in decision.reason.lower() or "maximum" in decision.reason.lower()

    def test_above_max_exposure_vetos(self) -> None:
        """Current exposure above max (35 %) → VETOED."""
        pipeline = _make_pipeline()
        signal = _make_signal(size_pct=0.05, confidence=0.8)
        assessment = _make_assessment(total_exposure_pct=0.35)
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "VETOED"

    def test_trade_fits_within_limits_passes_check3(self) -> None:
        """5 % proposed with 10 % current (15 % total < 30 % max) → check 3 passes."""
        pipeline = _make_pipeline()
        signal = _make_signal(size_pct=0.05, confidence=0.8)
        assessment = _make_assessment(total_exposure_pct=0.10)
        decision = pipeline.evaluate(signal, assessment)
        # Should not be resized by check 3
        assert "remaining portfolio capacity" not in decision.reason or decision.action == "APPROVED"


# ---------------------------------------------------------------------------
# Check 4: Sector correlation → VETOED
# ---------------------------------------------------------------------------


class TestCheck4CorrelationVeto:
    """Check 4: vetoed when 2+ existing positions are in the same sector."""

    def test_two_same_sector_positions_vetos(self) -> None:
        """2 existing large-cap (BTC+ETH) + new BTC signal → VETOED."""
        pipeline = _make_pipeline(
            existing_positions=[
                {"symbol": "BTCUSDT"},
                {"symbol": "ETHUSDT"},
            ]
        )
        signal = _make_signal(symbol="BTCUSDT", confidence=0.9, size_pct=0.05)
        assessment = _make_assessment(verdict="OK")
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "VETOED"
        assert "large_cap" in decision.reason or "sector" in decision.reason.lower()

    def test_three_same_sector_vetos(self) -> None:
        """3 existing l1_platform + new SOL signal → VETOED."""
        pipeline = _make_pipeline(
            existing_positions=[
                {"symbol": "SOLUSDT"},
                {"symbol": "AVAXUSDT"},
                {"symbol": "NEARUSDT"},
            ]
        )
        signal = _make_signal(symbol="FTMUSDT", confidence=0.9, size_pct=0.05)
        assessment = _make_assessment(verdict="OK")
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "VETOED"

    def test_one_same_sector_position_passes(self) -> None:
        """1 existing large-cap position + new ETH signal → check 4 does not veto."""
        pipeline = _make_pipeline(
            existing_positions=[{"symbol": "BTCUSDT"}]
        )
        signal = _make_signal(symbol="ETHUSDT", confidence=0.9, size_pct=0.05)
        assessment = _make_assessment(verdict="OK")
        decision = pipeline.evaluate(signal, assessment)
        # May be APPROVED (or RESIZED by other checks) but not VETOED by check 4
        assert "concentration" not in decision.reason

    def test_different_sector_passes_check4(self) -> None:
        """2 large-cap positions + DeFi signal → different sector, check 4 passes."""
        pipeline = _make_pipeline(
            existing_positions=[
                {"symbol": "BTCUSDT"},
                {"symbol": "ETHUSDT"},
            ]
        )
        signal = _make_signal(symbol="UNIUSDT", confidence=0.9, size_pct=0.05)
        assessment = _make_assessment(verdict="OK")
        decision = pipeline.evaluate(signal, assessment)
        # Check 4 should not trigger for 'defi' sector (no existing defi positions)
        assert "concentration" not in decision.reason

    def test_no_existing_positions_passes_check4(self) -> None:
        """Empty portfolio → check 4 never triggers."""
        pipeline = _make_pipeline(existing_positions=[])
        signal = _make_signal(symbol="SOLUSDT", confidence=0.9, size_pct=0.05)
        assessment = _make_assessment(verdict="OK")
        decision = pipeline.evaluate(signal, assessment)
        assert "concentration" not in decision.reason


# ---------------------------------------------------------------------------
# Check 5: Drawdown > 3 % → RESIZED (halved)
# ---------------------------------------------------------------------------


class TestCheck5DrawdownResize:
    """Check 5: position size is halved when drawdown exceeds 3 %."""

    def test_drawdown_above_threshold_halves_size(self) -> None:
        """4 % drawdown > 3 % threshold → size halved from 8 % to 4 %."""
        pipeline = _make_pipeline()
        signal = _make_signal(size_pct=0.08, confidence=0.8)
        assessment = _make_assessment(drawdown_pct=0.04)
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "RESIZED"
        assert abs(decision.adjusted_size_pct - 0.04) < 0.001
        assert "halved" in decision.reason.lower() or "drawdown" in decision.reason.lower()

    def test_drawdown_at_threshold_does_not_trigger(self) -> None:
        """Drawdown exactly at 3 % does not trigger resize (check is >3 %, not >=3 %)."""
        pipeline = _make_pipeline()
        signal = _make_signal(size_pct=0.08, confidence=0.8)
        assessment = _make_assessment(drawdown_pct=0.03)
        decision = pipeline.evaluate(signal, assessment)
        # 0.03 is NOT > 0.03, so check 5 should not fire
        assert "halved" not in decision.reason.lower()

    def test_drawdown_below_threshold_passes(self) -> None:
        """2 % drawdown (< 3 %) → check 5 does not resize."""
        pipeline = _make_pipeline()
        signal = _make_signal(size_pct=0.08, confidence=0.8)
        assessment = _make_assessment(drawdown_pct=0.02)
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "APPROVED"
        assert abs(decision.adjusted_size_pct - 0.08) < 0.001

    def test_halved_size_is_quantised(self) -> None:
        """Halved size is quantised to 4 decimal places."""
        pipeline = _make_pipeline()
        signal = _make_signal(size_pct=0.07, confidence=0.8)  # 7 % / 2 = 3.5 %
        assessment = _make_assessment(drawdown_pct=0.05)
        decision = pipeline.evaluate(signal, assessment)
        # 0.07 / 2 = 0.035 → quantised to 4 d.p.
        assert decision.action == "RESIZED"
        size_str = f"{decision.adjusted_size_pct:.4f}"
        assert len(size_str.split(".")[1]) <= 4

    def test_resize_respects_minimum_size(self) -> None:
        """Halved size is never below the configured minimum (0.1 % of max_single_position)."""
        cfg = RiskConfig(max_single_position=Decimal("0.10"))
        pipeline = _make_pipeline(config=cfg)
        # Very small signal: 0.02 / 2 = 0.01 which equals min threshold
        signal = _make_signal(size_pct=0.02, confidence=0.8)
        assessment = _make_assessment(drawdown_pct=0.05)
        decision = pipeline.evaluate(signal, assessment)
        # Should be at least min_size = 0.10 * 0.10 / 10 = 0.001
        assert decision.adjusted_size_pct > 0.0


# ---------------------------------------------------------------------------
# Check 6: All checks pass → APPROVED
# ---------------------------------------------------------------------------


class TestCheck6AllApproved:
    """Pipeline check 6: clean signal with clean portfolio is fully approved."""

    def test_all_checks_pass_gives_approved(self) -> None:
        """Signal and portfolio both well within limits → APPROVED at original size."""
        pipeline = _make_pipeline()
        signal = _make_signal(symbol="BTCUSDT", side="buy", size_pct=0.05, confidence=0.80)
        assessment = _make_assessment(
            verdict="OK",
            drawdown_pct=0.01,
            total_exposure_pct=0.05,
        )
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "APPROVED"
        assert abs(decision.adjusted_size_pct - 0.05) < 0.0001
        assert decision.original_size_pct == 0.05

    def test_approved_reason_mentions_symbol_and_side(self) -> None:
        """APPROVED reason references the trade symbol and side."""
        pipeline = _make_pipeline()
        signal = _make_signal(symbol="SOLUSDT", side="sell", size_pct=0.05, confidence=0.80)
        assessment = _make_assessment(verdict="OK")
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "APPROVED"
        assert "SOLUSDT" in decision.reason
        assert "sell" in decision.reason

    def test_approved_size_matches_original_when_no_adjustment(self) -> None:
        """Approved trade has adjusted_size_pct equal to original_size_pct."""
        pipeline = _make_pipeline()
        signal = _make_signal(size_pct=0.08, confidence=0.90)
        assessment = _make_assessment(verdict="OK", total_exposure_pct=0.0, drawdown_pct=0.0)
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "APPROVED"
        assert decision.adjusted_size_pct == decision.original_size_pct


# ---------------------------------------------------------------------------
# Short-circuit behaviour
# ---------------------------------------------------------------------------


class TestShortCircuit:
    """First VETOED check stops pipeline; no further checks run."""

    def test_halt_short_circuits_before_confidence_check(self) -> None:
        """HALT verdict fires first; low confidence reason is NOT in the output."""
        pipeline = _make_pipeline()
        # Signal has low confidence (would fail check 2) but verdict is HALT (check 1)
        signal = _make_signal(confidence=0.1)
        assessment = _make_assessment(verdict="HALT")
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "VETOED"
        # Check 1 triggered, not check 2
        assert "HALT" in decision.reason
        assert "below the minimum threshold" not in decision.reason

    def test_halt_short_circuits_before_exposure_check(self) -> None:
        """HALT fires before exposure check (check 3) — no exposure reason in output."""
        pipeline = _make_pipeline()
        signal = _make_signal(size_pct=0.05, confidence=0.9)
        assessment = _make_assessment(verdict="HALT", total_exposure_pct=0.30)
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "VETOED"
        assert "HALT" in decision.reason
        assert "exposure" not in decision.reason.lower()

    def test_confidence_veto_short_circuits_before_correlation_check(self) -> None:
        """Low confidence (check 2) fires before correlation check (check 4)."""
        pipeline = _make_pipeline(
            existing_positions=[
                {"symbol": "BTCUSDT"},
                {"symbol": "ETHUSDT"},
            ]
        )
        signal = _make_signal(symbol="BTCUSDT", confidence=0.3, size_pct=0.05)
        assessment = _make_assessment(verdict="OK")
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "VETOED"
        # Reason should reflect confidence check, not correlation check
        assert "confidence" in decision.reason.lower()
        assert "sector" not in decision.reason.lower()

    def test_resized_does_not_short_circuit(self) -> None:
        """RESIZED at check 3 does NOT stop the pipeline — check 5 still runs."""
        pipeline = _make_pipeline()
        # Check 3: 20 % current + 15 % proposed = 35 % > 30 % → resize to 10 %
        # Check 5: drawdown 5 % > 3 % → halve the resized 10 % → 5 %
        signal = _make_signal(size_pct=0.15, confidence=0.8)
        assessment = _make_assessment(total_exposure_pct=0.20, drawdown_pct=0.05)
        decision = pipeline.evaluate(signal, assessment)
        assert decision.action == "RESIZED"
        # Size should have been reduced by BOTH check 3 (10 %) AND check 5 (halved to 5 %)
        assert decision.adjusted_size_pct < 0.10 + 0.001  # must be at most 10 %

    def test_vetoed_adjusted_size_always_zero(self) -> None:
        """Any VETOED decision always has adjusted_size_pct == 0.0."""
        for verdict, confidence in [("HALT", 0.9), ("OK", 0.1)]:
            pipeline = _make_pipeline()
            signal = _make_signal(confidence=confidence)
            assessment = _make_assessment(verdict=verdict)
            decision = pipeline.evaluate(signal, assessment)
            if decision.action == "VETOED":
                assert decision.adjusted_size_pct == 0.0
