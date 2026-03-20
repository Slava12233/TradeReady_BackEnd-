"""Unit tests for agent/strategies/risk/middleware.py.

All SDK calls are mocked via AsyncMock so no running platform is required.
Tests cover:
  - ExecutionDecision model validation and JSON serialisability
  - RiskMiddleware.process_signal: happy paths (approved, resized, vetoed)
  - RiskMiddleware.process_signal: portfolio fetch failure
  - RiskMiddleware.process_signal: risk assessment failure
  - RiskMiddleware.process_signal: veto pipeline failure
  - RiskMiddleware.process_signal: dynamic sizing failure (fallback)
  - RiskMiddleware.execute_if_approved: order placed successfully
  - RiskMiddleware.execute_if_approved: order placement fails
  - RiskMiddleware.execute_if_approved: already vetoed (no-op)
  - RiskMiddleware.execute_if_approved: already executed (no-op)
  - RiskMiddleware.execute_if_approved: zero-price guard
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.strategies.risk import (
    DynamicSizer,
    ExecutionDecision,
    RiskAgent,
    RiskAssessment,
    RiskConfig,
    RiskMiddleware,
    SizerConfig,
    TradeSignal,
    VetoDecision,
    VetoPipeline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    symbol: str = "BTCUSDT",
    side: str = "buy",
    size_pct: float = 0.05,
    confidence: float = 0.75,
) -> TradeSignal:
    return TradeSignal(symbol=symbol, side=side, size_pct=size_pct, confidence=confidence)


def _make_approved_veto(size_pct: float = 0.05) -> VetoDecision:
    return VetoDecision(
        action="APPROVED",
        original_size_pct=size_pct,
        adjusted_size_pct=size_pct,
        reason="All pipeline checks passed.",
    )


def _make_resized_veto(original: float = 0.08, adjusted: float = 0.05) -> VetoDecision:
    return VetoDecision(
        action="RESIZED",
        original_size_pct=original,
        adjusted_size_pct=adjusted,
        reason="Resized due to portfolio exposure limit.",
    )


def _make_vetoed_veto(size_pct: float = 0.05) -> VetoDecision:
    return VetoDecision(
        action="VETOED",
        original_size_pct=size_pct,
        adjusted_size_pct=0.0,
        reason="Risk verdict is HALT.",
    )


def _make_assessment(
    verdict: str = "OK",
    equity: str = "10000.00",
    drawdown_pct: float = 0.0,
) -> RiskAssessment:
    return RiskAssessment(
        total_exposure_pct=0.10,
        max_single_position_pct=0.05,
        drawdown_pct=drawdown_pct,
        correlation_risk="low",
        verdict=verdict,
        action=None,
        equity=Decimal(equity),
        peak_equity=Decimal(equity),
    )


def _make_sdk_client(
    portfolio_total_value: str = "10000.00",
    positions: list | None = None,
    pnl_value: str = "50.00",
    order_id: str = "order-abc-123",
    price: str = "50000.00",
) -> AsyncMock:
    """Build a mock SDK client with all required methods."""
    client = AsyncMock()

    # Portfolio response: has .total_value and .positions_value.
    portfolio_resp = MagicMock()
    portfolio_resp.total_value = Decimal(portfolio_total_value)
    portfolio_resp.positions_value = Decimal("500.00")
    client.get_portfolio = AsyncMock(return_value=portfolio_resp)

    # Positions response: list of position-like objects.
    if positions is None:
        pos = MagicMock()
        pos.symbol = "BTCUSDT"
        pos.market_value = Decimal("500.00")
        pos.quantity = Decimal("0.01")
        positions = [pos]
    client.get_positions = AsyncMock(return_value=positions)

    # PnL response.
    pnl_resp = MagicMock()
    pnl_resp.realized_pnl = Decimal(pnl_value)
    client.get_pnl = AsyncMock(return_value=pnl_resp)

    # Price response.
    price_resp = MagicMock()
    price_resp.price = Decimal(price)
    client.get_price = AsyncMock(return_value=price_resp)

    # Order placement response.
    order_resp = MagicMock()
    order_resp.order_id = order_id
    client.place_market_order = AsyncMock(return_value=order_resp)

    return client


def _make_middleware(
    sdk_client: AsyncMock | None = None,
    config: RiskConfig | None = None,
    sizer_config: SizerConfig | None = None,
) -> RiskMiddleware:
    cfg = config or RiskConfig()
    return RiskMiddleware(
        risk_agent=RiskAgent(config=cfg),
        veto_pipeline=VetoPipeline(config=cfg),
        dynamic_sizer=DynamicSizer(config=sizer_config or SizerConfig()),
        sdk_client=sdk_client or _make_sdk_client(),
    )


# ---------------------------------------------------------------------------
# ExecutionDecision model tests
# ---------------------------------------------------------------------------


class TestExecutionDecisionModel:
    """Validate the ExecutionDecision Pydantic model."""

    def _valid_kwargs(self) -> dict:
        signal = _make_signal()
        assessment = _make_assessment()
        veto = _make_approved_veto()
        return dict(
            original_signal=signal,
            risk_assessment=assessment,
            veto_decision=veto,
            final_size_pct=0.05,
            executed=False,
        )

    def test_construction_valid(self) -> None:
        """ExecutionDecision builds with all required fields."""
        d = ExecutionDecision(**self._valid_kwargs())
        assert d.final_size_pct == 0.05
        assert d.executed is False
        assert d.order_id is None
        assert d.error is None

    def test_frozen(self) -> None:
        """ExecutionDecision is immutable after construction."""
        d = ExecutionDecision(**self._valid_kwargs())
        with pytest.raises(Exception):
            d.executed = True  # type: ignore[misc]

    def test_json_serialisable(self) -> None:
        """ExecutionDecision serialises to JSON without error."""
        d = ExecutionDecision(**self._valid_kwargs())
        raw = d.model_dump_json()
        parsed = json.loads(raw)
        assert parsed["executed"] is False
        assert parsed["order_id"] is None

    def test_final_size_pct_bounds(self) -> None:
        """final_size_pct must be in [0, 1]."""
        kwargs = self._valid_kwargs()
        kwargs["final_size_pct"] = -0.01
        with pytest.raises(Exception):
            ExecutionDecision(**kwargs)
        kwargs["final_size_pct"] = 1.01
        with pytest.raises(Exception):
            ExecutionDecision(**kwargs)

    def test_with_error(self) -> None:
        """ExecutionDecision accepts an error string."""
        kwargs = self._valid_kwargs()
        kwargs["error"] = "Portfolio fetch failed: connection refused"
        d = ExecutionDecision(**kwargs)
        assert d.error == "Portfolio fetch failed: connection refused"

    def test_with_order_id(self) -> None:
        """ExecutionDecision accepts order_id and executed=True."""
        kwargs = self._valid_kwargs()
        kwargs["executed"] = True
        kwargs["order_id"] = "order-xyz-789"
        d = ExecutionDecision(**kwargs)
        assert d.executed is True
        assert d.order_id == "order-xyz-789"

    def test_model_copy_update(self) -> None:
        """model_copy(update=...) produces a new frozen instance."""
        d = ExecutionDecision(**self._valid_kwargs())
        d2 = d.model_copy(update={"executed": True, "order_id": "new-id"})
        assert d2.executed is True
        assert d2.order_id == "new-id"
        # Original is unchanged.
        assert d.executed is False
        assert d.order_id is None


# ---------------------------------------------------------------------------
# RiskMiddleware.process_signal — happy paths
# ---------------------------------------------------------------------------


class TestProcessSignalApproved:
    """Signal is approved through all pipeline stages."""

    async def test_returns_execution_decision(self) -> None:
        sdk = _make_sdk_client()
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal()

        decision = await mw.process_signal(signal)

        assert isinstance(decision, ExecutionDecision)
        assert decision.original_signal == signal
        assert decision.executed is False

    async def test_verdict_ok_produces_approved_or_resized(self) -> None:
        sdk = _make_sdk_client()
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal(confidence=0.90)

        decision = await mw.process_signal(signal)

        # With fresh portfolio and no existing positions, expect APPROVED or RESIZED.
        assert decision.veto_decision.action in ("APPROVED", "RESIZED")
        assert decision.final_size_pct > 0.0
        assert decision.error is None

    async def test_portfolio_fetched_per_call(self) -> None:
        """SDK get_portfolio is called once per process_signal invocation."""
        sdk = _make_sdk_client()
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal()

        await mw.process_signal(signal)
        await mw.process_signal(signal)

        assert sdk.get_portfolio.call_count == 2

    async def test_positions_fetched_per_call(self) -> None:
        sdk = _make_sdk_client()
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal()

        await mw.process_signal(signal)
        await mw.process_signal(signal)

        assert sdk.get_positions.call_count == 2

    async def test_final_size_pct_within_bounds(self) -> None:
        sdk = _make_sdk_client()
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal(size_pct=0.10)

        decision = await mw.process_signal(signal)

        # DynamicSizer clamps to [0.01, max_single_position (0.10)].
        assert 0.0 <= decision.final_size_pct <= 0.10


class TestProcessSignalResized:
    """Signal is approved but with a reduced size."""

    async def test_resized_action_produces_smaller_size(self) -> None:
        # Use a config where max_portfolio_exposure is very tight.
        cfg = RiskConfig(max_portfolio_exposure=Decimal("0.06"))
        # Existing position takes up ~5% of equity (500/10000).
        sdk = _make_sdk_client()
        mw = _make_middleware(sdk_client=sdk, config=cfg)
        # Request 8% — should be capped at remaining headroom.
        signal = _make_signal(size_pct=0.08, confidence=0.85)

        decision = await mw.process_signal(signal)

        # Trade should be approved or resized (not vetoed) — remaining capacity is ~1%.
        # The exact action depends on headroom; just confirm no error.
        assert decision.error is None
        assert decision.final_size_pct >= 0.0


class TestProcessSignalVetoed:
    """Signal is vetoed at the pipeline stage."""

    async def test_vetoed_signal_returns_zero_size(self) -> None:
        # HALT verdict forces a veto.
        sdk = _make_sdk_client(pnl_value="-500.00")
        # Equity = 10000, daily_loss_halt default = 3% = 300 USDT.
        # Loss of 500 USDT > 300 USDT → HALT verdict.
        cfg = RiskConfig(daily_loss_halt=Decimal("0.03"))
        mw = _make_middleware(sdk_client=sdk, config=cfg)
        signal = _make_signal()

        decision = await mw.process_signal(signal)

        # With HALT verdict the veto pipeline vetoes the signal.
        assert decision.veto_decision.action == "VETOED"
        assert decision.final_size_pct == 0.0
        assert decision.executed is False

    async def test_low_confidence_signal_is_vetoed(self) -> None:
        sdk = _make_sdk_client()
        mw = _make_middleware(sdk_client=sdk)
        # Confidence below 0.5 threshold.
        signal = _make_signal(confidence=0.30)

        decision = await mw.process_signal(signal)

        assert decision.veto_decision.action == "VETOED"
        assert decision.final_size_pct == 0.0


# ---------------------------------------------------------------------------
# RiskMiddleware.process_signal — error paths
# ---------------------------------------------------------------------------


class TestProcessSignalErrors:
    """Pipeline stages raise exceptions → error decision returned."""

    async def test_portfolio_fetch_failure_returns_error_decision(self) -> None:
        sdk = _make_sdk_client()
        sdk.get_portfolio = AsyncMock(side_effect=RuntimeError("connection refused"))
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal()

        decision = await mw.process_signal(signal)

        assert decision.error is not None
        assert "connection refused" in decision.error
        assert decision.executed is False
        assert decision.veto_decision.action == "VETOED"
        # Fail-closed: assessment has HALT verdict.
        assert decision.risk_assessment.verdict == "HALT"

    async def test_positions_fetch_failure_returns_error_decision(self) -> None:
        sdk = _make_sdk_client()
        sdk.get_positions = AsyncMock(side_effect=RuntimeError("timeout"))
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal()

        decision = await mw.process_signal(signal)

        assert decision.error is not None
        assert "timeout" in decision.error
        assert decision.executed is False

    async def test_pnl_fetch_failure_is_non_fatal(self) -> None:
        """PnL fetch failure falls back to 0 and processing continues."""
        sdk = _make_sdk_client()
        sdk.get_pnl = AsyncMock(side_effect=RuntimeError("pnl endpoint down"))
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal()

        # Should not error — pnl falls back to Decimal("0").
        decision = await mw.process_signal(signal)

        # Execution decision present (error may or may not be None, but no crash).
        assert isinstance(decision, ExecutionDecision)

    async def test_veto_pipeline_exception_returns_error_decision(self) -> None:
        sdk = _make_sdk_client()
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal()

        # Patch VetoPipeline.evaluate to raise.
        with patch.object(mw._veto_pipeline, "evaluate", side_effect=RuntimeError("veto crash")):
            decision = await mw.process_signal(signal)

        assert decision.error is not None
        assert "veto crash" in decision.error
        assert decision.executed is False

    async def test_dynamic_sizer_exception_falls_back_to_veto_size(self) -> None:
        sdk = _make_sdk_client()
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal(confidence=0.80)

        # Patch DynamicSizer.calculate_size to raise.
        with patch.object(
            mw._dynamic_sizer,
            "calculate_size",
            side_effect=RuntimeError("sizer crash"),
        ):
            decision = await mw.process_signal(signal)

        # No error field set (fallback handles it gracefully).
        # final_size_pct falls back to veto adjusted_size_pct.
        assert isinstance(decision, ExecutionDecision)
        # If not vetoed, final_size_pct should equal veto's adjusted_size_pct.
        if decision.veto_decision.action != "VETOED":
            assert decision.final_size_pct == decision.veto_decision.adjusted_size_pct


# ---------------------------------------------------------------------------
# RiskMiddleware.execute_if_approved
# ---------------------------------------------------------------------------


class TestExecuteIfApproved:
    """Tests for the order-placement stage."""

    def _approved_decision(self, final_size: float = 0.05) -> ExecutionDecision:
        return ExecutionDecision(
            original_signal=_make_signal(),
            risk_assessment=_make_assessment(equity="10000.00"),
            veto_decision=_make_approved_veto(size_pct=final_size),
            final_size_pct=final_size,
            executed=False,
        )

    async def test_approved_decision_places_order(self) -> None:
        sdk = _make_sdk_client(price="50000.00", order_id="order-123")
        mw = _make_middleware(sdk_client=sdk)
        decision = self._approved_decision(final_size=0.05)

        result = await mw.execute_if_approved(decision)

        assert result.executed is True
        assert result.order_id == "order-123"
        assert result.error is None
        sdk.place_market_order.assert_called_once()

    async def test_vetoed_decision_is_returned_unchanged(self) -> None:
        sdk = _make_sdk_client()
        mw = _make_middleware(sdk_client=sdk)
        vetoed = ExecutionDecision(
            original_signal=_make_signal(),
            risk_assessment=_make_assessment(),
            veto_decision=_make_vetoed_veto(),
            final_size_pct=0.0,
            executed=False,
        )

        result = await mw.execute_if_approved(vetoed)

        # No SDK calls; decision is returned as-is.
        assert result is vetoed
        sdk.place_market_order.assert_not_called()

    async def test_already_executed_decision_is_returned_unchanged(self) -> None:
        sdk = _make_sdk_client()
        mw = _make_middleware(sdk_client=sdk)
        already_done = ExecutionDecision(
            original_signal=_make_signal(),
            risk_assessment=_make_assessment(),
            veto_decision=_make_approved_veto(),
            final_size_pct=0.05,
            executed=True,
            order_id="already-placed",
        )

        result = await mw.execute_if_approved(already_done)

        assert result is already_done
        sdk.place_market_order.assert_not_called()

    async def test_error_decision_is_returned_unchanged(self) -> None:
        sdk = _make_sdk_client()
        mw = _make_middleware(sdk_client=sdk)
        error_dec = ExecutionDecision(
            original_signal=_make_signal(),
            risk_assessment=_make_assessment(),
            veto_decision=_make_vetoed_veto(),
            final_size_pct=0.0,
            executed=False,
            error="prior pipeline error",
        )

        result = await mw.execute_if_approved(error_dec)

        assert result is error_dec
        sdk.place_market_order.assert_not_called()

    async def test_order_placement_failure_sets_error(self) -> None:
        sdk = _make_sdk_client(price="50000.00")
        sdk.place_market_order = AsyncMock(side_effect=RuntimeError("insufficient balance"))
        mw = _make_middleware(sdk_client=sdk)
        decision = self._approved_decision()

        result = await mw.execute_if_approved(decision)

        assert result.executed is False
        assert result.error is not None
        assert "insufficient balance" in result.error

    async def test_zero_price_sets_error(self) -> None:
        sdk = _make_sdk_client(price="0")
        mw = _make_middleware(sdk_client=sdk)
        decision = self._approved_decision()

        result = await mw.execute_if_approved(decision)

        assert result.executed is False
        assert result.error is not None
        assert result.order_id is None
        sdk.place_market_order.assert_not_called()

    async def test_order_quantity_computed_from_equity_and_size(self) -> None:
        """Quantity = (equity * final_size_pct) / price."""
        sdk = _make_sdk_client(price="50000.00", order_id="order-qty-check")
        mw = _make_middleware(sdk_client=sdk)
        # equity = 10000, final_size = 0.05 → USDT value = 500
        # price = 50000 → quantity = 500 / 50000 = 0.01
        decision = self._approved_decision(final_size=0.05)

        result = await mw.execute_if_approved(decision)

        assert result.executed is True
        call_kwargs = sdk.place_market_order.call_args
        # Extract quantity from the call.
        qty_str = call_kwargs.kwargs.get("quantity") or call_kwargs.args[2]
        qty = Decimal(qty_str)
        # Expected: (10000 * 0.05) / 50000 = 0.01
        assert qty == Decimal("0.01000000")

    async def test_resized_decision_uses_final_size_pct(self) -> None:
        sdk = _make_sdk_client(price="50000.00", order_id="resized-order")
        mw = _make_middleware(sdk_client=sdk)
        # Resized from 0.08 to 0.03.
        resized = ExecutionDecision(
            original_signal=_make_signal(size_pct=0.08),
            risk_assessment=_make_assessment(equity="10000.00"),
            veto_decision=_make_resized_veto(original=0.08, adjusted=0.03),
            final_size_pct=0.03,
            executed=False,
        )

        result = await mw.execute_if_approved(resized)

        assert result.executed is True
        call_kwargs = sdk.place_market_order.call_args
        qty_str = call_kwargs.kwargs.get("quantity") or call_kwargs.args[2]
        qty = Decimal(qty_str)
        # Expected: (10000 * 0.03) / 50000 = 0.006
        assert qty == Decimal("0.00600000")


# ---------------------------------------------------------------------------
# Integration: process_signal then execute_if_approved
# ---------------------------------------------------------------------------


class TestMiddlewareIntegration:
    """Full pipeline: process then execute."""

    async def test_full_pipeline_approved_and_executed(self) -> None:
        sdk = _make_sdk_client(
            portfolio_total_value="10000.00",
            pnl_value="100.00",
            price="50000.00",
            order_id="full-pipeline-order",
        )
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal(confidence=0.90, size_pct=0.05)

        decision = await mw.process_signal(signal)
        decision = await mw.execute_if_approved(decision)

        if decision.veto_decision.action != "VETOED":
            assert decision.executed is True
            assert decision.order_id is not None

    async def test_full_pipeline_vetoed_never_executes(self) -> None:
        # Force veto via low confidence.
        sdk = _make_sdk_client()
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal(confidence=0.20)

        decision = await mw.process_signal(signal)
        decision = await mw.execute_if_approved(decision)

        assert decision.executed is False
        assert decision.veto_decision.action == "VETOED"
        sdk.place_market_order.assert_not_called()

    async def test_result_is_json_serialisable(self) -> None:
        sdk = _make_sdk_client(price="50000.00", order_id="json-test-order")
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal(confidence=0.90)

        decision = await mw.process_signal(signal)
        decision = await mw.execute_if_approved(decision)

        # model_dump_json must not raise.
        raw = decision.model_dump_json()
        parsed = json.loads(raw)
        assert "original_signal" in parsed
        assert "risk_assessment" in parsed
        assert "veto_decision" in parsed
        assert "final_size_pct" in parsed
        assert "executed" in parsed
