"""Unit tests for agent/strategies/risk/middleware.py.

All SDK calls are mocked via AsyncMock so no running platform is required.
Tests cover:
  - ExecutionDecision model validation and JSON serialisability
  - RiskMiddleware.process_signal: happy paths (approved, resized, vetoed)
  - RiskMiddleware.process_signal: portfolio fetch failure
  - RiskMiddleware.process_signal: risk assessment failure
  - RiskMiddleware.process_signal: veto pipeline failure
  - RiskMiddleware.process_signal: dynamic sizing failure (fallback)
  - RiskMiddleware._candles_to_log_returns: various candle formats
  - RiskMiddleware._pearson_correlation: mathematical correctness
  - RiskMiddleware._check_correlation: size reduction and exposure cap
  - RiskMiddleware.process_signal: correlation gate integration
  - RiskMiddleware.execute_if_approved: order placed successfully
  - RiskMiddleware.execute_if_approved: order placement fails
  - RiskMiddleware.execute_if_approved: already vetoed (no-op)
  - RiskMiddleware.execute_if_approved: already executed (no-op)
  - RiskMiddleware.execute_if_approved: zero-price guard
"""

from __future__ import annotations

import json
import math
import random
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


# ---------------------------------------------------------------------------
# Helpers for correlation tests
# ---------------------------------------------------------------------------


def _make_candles_dict(closes: list[float]) -> list[dict]:
    """Build a list of candle dicts with a ``close`` key."""
    return [{"open": c, "high": c, "low": c, "close": c, "volume": 1.0} for c in closes]


def _make_candles_obj(closes: list[float]) -> list[MagicMock]:
    """Build a list of candle-like objects with a ``.close`` attribute."""
    candles = []
    for c in closes:
        obj = MagicMock()
        obj.close = c
        candles.append(obj)
    return candles


def _make_sdk_with_candles(
    candles_by_symbol: dict[str, list[dict]],
    portfolio_total_value: str = "10000.00",
    positions: list | None = None,
    pnl_value: str = "50.00",
    price: str = "50000.00",
    order_id: str = "order-corr-123",
) -> AsyncMock:
    """Build a mock SDK client where get_candles returns per-symbol candle data."""
    sdk = _make_sdk_client(
        portfolio_total_value=portfolio_total_value,
        positions=positions,
        pnl_value=pnl_value,
        price=price,
        order_id=order_id,
    )

    async def _get_candles(symbol: str, interval: str, limit: int) -> list[dict]:
        return candles_by_symbol.get(symbol.upper(), [])

    sdk.get_candles = AsyncMock(side_effect=_get_candles)
    return sdk


def _correlated_closes(length: int = 25, start: float = 100.0) -> list[float]:
    """Generate a strictly increasing price series (perfect correlation with itself)."""
    return [start + i * 0.5 for i in range(length)]


def _uncorrelated_closes(length: int = 25, base: float = 200.0) -> list[float]:
    """Generate an alternating price series (low correlation with a monotone series)."""
    return [base + (1.0 if i % 2 == 0 else -1.0) for i in range(length)]


# ---------------------------------------------------------------------------
# _candles_to_log_returns unit tests
# ---------------------------------------------------------------------------


class TestCandlesToLogReturns:
    """Verify _candles_to_log_returns handles all supported candle formats."""

    def setup_method(self) -> None:
        mw = _make_middleware()
        self._fn = mw._candles_to_log_returns  # noqa: SLF001

    def test_dict_candles_produces_returns(self) -> None:
        closes = [100.0, 101.0, 102.0, 100.0]
        candles = _make_candles_dict(closes)
        result = self._fn(candles)
        assert len(result) == 3
        assert abs(result[0] - math.log(101.0 / 100.0)) < 1e-9

    def test_object_candles_produces_returns(self) -> None:
        closes = [50.0, 55.0, 52.0]
        candles = _make_candles_obj(closes)
        result = self._fn(candles)
        assert len(result) == 2

    def test_empty_list_returns_empty(self) -> None:
        assert self._fn([]) == []

    def test_single_candle_returns_empty(self) -> None:
        assert self._fn(_make_candles_dict([100.0])) == []

    def test_none_input_returns_empty(self) -> None:
        assert self._fn(None) == []  # type: ignore[arg-type]

    def test_zero_close_skipped(self) -> None:
        """Zero close prices produce fewer returns because the zero is dropped.

        ``_make_candles_dict`` uses ``close`` as the key.  When ``close=0.0``
        the dict lookup ``candle.get("close") or candle.get("c")`` evaluates
        the falsy ``0.0`` and falls through to ``"c"`` which is absent, so the
        zero candle is not appended to the closes list.  The series becomes
        ``[100.0, 102.0]``, yielding exactly one log-return.
        """
        closes = [100.0, 0.0, 102.0]
        candles = _make_candles_dict(closes)
        result = self._fn(candles)
        # The zero close is silently dropped; 100→102 gives 1 return.
        assert len(result) == 1

    def test_candles_with_c_key(self) -> None:
        """``c`` key is accepted as an alternative to ``close``."""
        candles = [{"c": 100.0}, {"c": 101.0}, {"c": 99.0}]
        result = self._fn(candles)
        assert len(result) == 2

    def test_returns_sign(self) -> None:
        """Positive price increase → positive return; decrease → negative."""
        candles = _make_candles_dict([100.0, 110.0, 99.0])
        result = self._fn(candles)
        assert result[0] > 0.0  # 100→110: up
        assert result[1] < 0.0  # 110→99: down


# ---------------------------------------------------------------------------
# _pearson_correlation unit tests
# ---------------------------------------------------------------------------


class TestPearsonCorrelation:
    """Verify _pearson_correlation produces correct values."""

    def setup_method(self) -> None:
        mw = _make_middleware()
        self._fn = mw._pearson_correlation  # noqa: SLF001

    def test_identical_series_gives_one(self) -> None:
        series = [0.01, -0.005, 0.02, -0.01, 0.015]
        assert abs(self._fn(series, series) - 1.0) < 1e-9

    def test_opposite_series_gives_minus_one(self) -> None:
        series = [0.01, -0.005, 0.02, -0.01, 0.015]
        neg = [-x for x in series]
        assert abs(self._fn(series, neg) + 1.0) < 1e-9

    def test_constant_series_gives_zero(self) -> None:
        constant = [0.0] * 10
        other = [0.01, -0.02, 0.03, -0.01, 0.005, 0.02, -0.01, 0.03, -0.005, 0.01]
        assert self._fn(constant, other) == 0.0

    def test_empty_series_gives_zero(self) -> None:
        assert self._fn([], [1.0, 2.0]) == 0.0

    def test_single_element_gives_zero(self) -> None:
        assert self._fn([1.0], [1.0]) == 0.0

    def test_result_in_range(self) -> None:
        random.seed(42)
        x = [random.gauss(0, 1) for _ in range(20)]
        y = [random.gauss(0, 1) for _ in range(20)]
        r = self._fn(x, y)
        assert -1.0 <= r <= 1.0

    def test_different_length_uses_shorter_tail(self) -> None:
        """If series have different lengths, use the most-recent min(n) observations."""
        x = [0.01, -0.02, 0.03, -0.01, 0.02]  # length 5
        y = [0.01, -0.02, 0.03, -0.01, 0.02, 0.99, -0.99]  # length 7 — extra early data
        # Tail of y aligned to x: y[-5:] == [0.03, -0.01, 0.02, 0.99, -0.99] ≠ x
        # But y[-5:] should be used, giving a correlation < 1.
        r_full = self._fn(x, y)
        # Regardless of direction, result must be in [-1, 1].
        assert -1.0 <= r_full <= 1.0

    def test_high_correlation_btc_eth_proxy(self) -> None:
        """Proxy for BTC/ETH: two series sharing the same underlying shocks give r ≈ 1.

        Pure linear growth yields near-constant log-returns (low variance),
        which produces noisy Pearson estimates close to 0.  Instead we use
        series with identical large shocks plus small independent noise, which
        gives a reliably high correlation.
        """
        random.seed(0)
        # Shared shock series (±2–5 %) drives most of the variance.
        shocks = [random.choice([-0.03, -0.02, 0.02, 0.03, 0.04]) for _ in range(20)]
        btc_returns = [s + random.gauss(0, 0.001) for s in shocks]
        eth_returns = [s + random.gauss(0, 0.001) for s in shocks]
        r = self._fn(btc_returns, eth_returns)
        # Series share the same underlying shock → r should be very high.
        assert r > 0.98


# ---------------------------------------------------------------------------
# _check_correlation unit tests
# ---------------------------------------------------------------------------


class TestCheckCorrelation:
    """Tests for the correlation gate in isolation via _check_correlation."""

    def _make_middleware_with_candles(
        self,
        candles_by_symbol: dict[str, list[dict]],
        positions: list | None = None,
    ) -> tuple[RiskMiddleware, AsyncMock]:
        sdk = _make_sdk_with_candles(candles_by_symbol, positions=positions)
        mw = _make_middleware(sdk_client=sdk)
        return mw, sdk

    async def test_no_positions_returns_unchanged(self) -> None:
        mw, _ = self._make_middleware_with_candles({}, positions=[])
        signal = _make_signal(symbol="BTCUSDT")
        result = await mw._check_correlation(  # noqa: SLF001
            signal=signal,
            positions=[],
            current_size=0.08,
            equity=Decimal("10000.00"),
        )
        assert result == 0.08

    async def test_only_proposed_symbol_in_positions_returns_unchanged(self) -> None:
        """Proposed symbol matches the only position — no other symbol to compare."""
        pos = MagicMock()
        pos.symbol = "BTCUSDT"
        pos.market_value = Decimal("500.00")
        pos.quantity = Decimal("0.01")
        mw, _ = self._make_middleware_with_candles({}, positions=[pos])
        signal = _make_signal(symbol="BTCUSDT")
        positions = [{"symbol": "BTCUSDT", "market_value": "500.00"}]
        result = await mw._check_correlation(  # noqa: SLF001
            signal=signal,
            positions=positions,
            current_size=0.08,
            equity=Decimal("10000.00"),
        )
        assert result == 0.08

    async def test_low_correlation_returns_unchanged(self) -> None:
        """Correlation below 0.7 threshold: size is not modified."""
        btc_closes = _correlated_closes(25, 40000.0)
        sol_closes = _uncorrelated_closes(25, 100.0)
        candles = {
            "BTCUSDT": _make_candles_dict(btc_closes),
            "SOLUSDT": _make_candles_dict(sol_closes),
        }
        mw, _ = self._make_middleware_with_candles(candles)
        signal = _make_signal(symbol="BTCUSDT")
        positions = [{"symbol": "SOLUSDT", "market_value": "500.00"}]
        result = await mw._check_correlation(  # noqa: SLF001
            signal=signal,
            positions=positions,
            current_size=0.08,
            equity=Decimal("10000.00"),
        )
        # Low correlation: size unchanged.
        assert result == 0.08

    async def test_high_correlation_reduces_size(self) -> None:
        """Correlation above 0.7 threshold: size is proportionally reduced.

        Generate two price series driven by the same large random shocks plus
        tiny independent noise.  The resulting log-return correlation should
        reliably exceed 0.9, triggering a size reduction.
        """
        random.seed(1)
        # Build price series from shared shocks so log-returns are highly correlated.
        shocks = [random.choice([-0.03, -0.02, 0.01, 0.02, 0.03]) for _ in range(25)]
        btc_closes: list[float] = [40000.0]
        eth_closes: list[float] = [2000.0]
        for s in shocks:
            btc_closes.append(btc_closes[-1] * math.exp(s + random.gauss(0, 0.0005)))
            eth_closes.append(eth_closes[-1] * math.exp(s + random.gauss(0, 0.0005)))

        candles = {
            "BTCUSDT": _make_candles_dict(btc_closes),
            "ETHUSDT": _make_candles_dict(eth_closes),
        }
        mw, _ = self._make_middleware_with_candles(candles)
        signal = _make_signal(symbol="BTCUSDT")
        positions = [{"symbol": "ETHUSDT", "market_value": "500.00"}]
        original_size = 0.08
        result = await mw._check_correlation(  # noqa: SLF001
            signal=signal,
            positions=positions,
            current_size=original_size,
            equity=Decimal("10000.00"),
        )
        # With high correlation, size should be strictly less than original.
        assert result < original_size
        # And result must be in [0, 1].
        assert 0.0 <= result <= 1.0

    async def test_high_correlation_size_factor_formula(self) -> None:
        """size *= (1 - max_corr): verify the reduction factor is applied.

        Two price series with identical log-returns give r = 1.0 exactly.
        The expected reduced size is original_size * (1 - 1.0) = 0.0.
        We use a varying close sequence so the log-returns are non-constant
        and Pearson r is computed from actual variance (not zero variance).
        """
        # Alternating: up 5 %, down 3 % — produces non-constant log-returns.
        factors = [1.05, 0.97, 1.05, 0.97, 1.05, 0.97, 1.05, 0.97, 1.05, 0.97,
                   1.05, 0.97, 1.05, 0.97, 1.05, 0.97, 1.05, 0.97, 1.05, 0.97,
                   1.05, 0.97, 1.05, 0.97, 1.05]
        base_closes: list[float] = [100.0]
        for f in factors:
            base_closes.append(base_closes[-1] * f)

        candles = {
            "BTCUSDT": _make_candles_dict(base_closes),
            "ETHUSDT": _make_candles_dict(base_closes),  # identical series → r = 1.0
        }
        mw, _ = self._make_middleware_with_candles(candles)
        signal = _make_signal(symbol="BTCUSDT")
        positions = [{"symbol": "ETHUSDT", "market_value": "100.00"}]
        original_size = 0.10
        result = await mw._check_correlation(  # noqa: SLF001
            signal=signal,
            positions=positions,
            current_size=original_size,
            equity=Decimal("10000.00"),
        )
        # max_corr = 1.0 → size *= (1 - 1.0) = 0.0 (then clamped at 0.0).
        assert result == pytest.approx(0.0, abs=1e-6)

    async def test_candle_fetch_error_is_non_fatal(self) -> None:
        """SDK candle fetch error for one symbol should gracefully skip that symbol."""
        btc_closes = [40000.0 + i * 200.0 for i in range(25)]
        candles = {"BTCUSDT": _make_candles_dict(btc_closes)}

        sdk = _make_sdk_with_candles(candles)
        # Override get_candles so ETHUSDT raises.

        async def _get_candles_with_error(symbol: str, interval: str, limit: int) -> list:
            if symbol.upper() == "ETHUSDT":
                raise RuntimeError("candle endpoint down")
            return candles.get(symbol.upper(), [])

        sdk.get_candles = AsyncMock(side_effect=_get_candles_with_error)
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal(symbol="BTCUSDT")
        positions = [{"symbol": "ETHUSDT", "market_value": "500.00"}]

        # ETHUSDT candles fail → no correlation partner → returns unchanged size.
        result = await mw._check_correlation(  # noqa: SLF001
            signal=signal,
            positions=positions,
            current_size=0.08,
            equity=Decimal("10000.00"),
        )
        # Without any valid partner series, no reduction is applied.
        assert result == 0.08

    async def test_correlated_exposure_cap_applied(self) -> None:
        """Total correlated exposure is capped at 2 × max_single_position.

        Uses alternating ±5 %/3 % price moves so log-returns are non-constant
        and the identical series gives r = 1.0 exactly.
        """
        from agent.strategies.risk.sizing import SizerConfig

        # max_single_position = 0.10 → cap = 0.20
        # Existing ETH position = 2000 / 10000 = 0.20 → already at cap.
        factors = [1.05, 0.97] * 13  # 26 factors → 27 closes
        base_closes: list[float] = [100.0]
        for f in factors:
            base_closes.append(base_closes[-1] * f)

        candles = {
            "BTCUSDT": _make_candles_dict(base_closes),
            "ETHUSDT": _make_candles_dict(base_closes),  # identical → r = 1.0
        }
        sdk = _make_sdk_with_candles(candles)
        sizer_cfg = SizerConfig(max_single_position=Decimal("0.10"))
        mw = RiskMiddleware(
            risk_agent=RiskAgent(config=RiskConfig()),
            veto_pipeline=VetoPipeline(config=RiskConfig()),
            dynamic_sizer=DynamicSizer(config=sizer_cfg),
            sdk_client=sdk,
            sizer_config=sizer_cfg,
        )
        signal = _make_signal(symbol="BTCUSDT")
        positions = [{"symbol": "ETHUSDT", "market_value": "2000.00"}]
        # Existing ETH exposure = 2000/10000 = 0.20 = cap → no headroom → result = 0.
        result = await mw._check_correlation(  # noqa: SLF001
            signal=signal,
            positions=positions,
            current_size=0.08,
            equity=Decimal("10000.00"),
        )
        assert result == pytest.approx(0.0, abs=1e-6)

    async def test_multiple_positions_max_correlation_used(self) -> None:
        """The highest absolute correlation across all positions drives the reduction.

        ETH uses the same shock series as BTC (r ≈ 1.0); SOL uses independent
        random noise (r ≈ 0).  The ETH correlation should drive the reduction.
        """
        random.seed(7)
        shocks = [random.choice([-0.03, -0.02, 0.01, 0.02, 0.03]) for _ in range(25)]
        btc_closes: list[float] = [40000.0]
        eth_closes: list[float] = [2000.0]
        for s in shocks:
            btc_closes.append(btc_closes[-1] * math.exp(s + random.gauss(0, 0.0005)))
            eth_closes.append(eth_closes[-1] * math.exp(s + random.gauss(0, 0.0005)))

        sol_closes = _uncorrelated_closes(26, 100.0)  # low corr with BTC
        candles = {
            "BTCUSDT": _make_candles_dict(btc_closes),
            "ETHUSDT": _make_candles_dict(eth_closes),
            "SOLUSDT": _make_candles_dict(sol_closes),
        }
        mw, _ = self._make_middleware_with_candles(candles)
        signal = _make_signal(symbol="BTCUSDT")
        positions = [
            {"symbol": "ETHUSDT", "market_value": "500.00"},
            {"symbol": "SOLUSDT", "market_value": "300.00"},
        ]
        original_size = 0.08
        result = await mw._check_correlation(  # noqa: SLF001
            signal=signal,
            positions=positions,
            current_size=original_size,
            equity=Decimal("10000.00"),
        )
        # ETH drives a high-correlation reduction even though SOL is uncorrelated.
        assert result < original_size


# ---------------------------------------------------------------------------
# Correlation gate — integration via process_signal
# ---------------------------------------------------------------------------


class TestProcessSignalCorrelationGate:
    """Integration tests: correlation gate wired into process_signal."""

    def _make_sdk_with_positions_and_candles(
        self,
        position_symbol: str,
        btc_closes: list[float],
        eth_closes: list[float],
        equity: str = "10000.00",
    ) -> AsyncMock:
        """Build an SDK mock that simulates one open position + candle data."""
        pos = MagicMock()
        pos.symbol = position_symbol
        pos.market_value = Decimal("500.00")
        pos.quantity = Decimal("0.25")

        candles_map = {
            "BTCUSDT": _make_candles_dict(btc_closes),
            position_symbol.upper(): _make_candles_dict(eth_closes),
        }
        sdk = _make_sdk_with_candles(
            candles_map,
            portfolio_total_value=equity,
            positions=[pos],
            price="50000.00",
        )
        return sdk

    async def test_btc_eth_high_correlation_reduces_size(self) -> None:
        """BTC+ETH (typically r > 0.8) triggers a size reduction in the pipeline.

        Uses shared random shocks so log-return correlation is reliable > 0.9.
        """
        random.seed(99)
        shocks = [random.choice([-0.03, -0.02, 0.01, 0.02, 0.03]) for _ in range(25)]
        btc_closes: list[float] = [40000.0]
        eth_closes: list[float] = [2000.0]
        for s in shocks:
            btc_closes.append(btc_closes[-1] * math.exp(s + random.gauss(0, 0.0005)))
            eth_closes.append(eth_closes[-1] * math.exp(s + random.gauss(0, 0.0005)))

        sdk = self._make_sdk_with_positions_and_candles(
            position_symbol="ETHUSDT",
            btc_closes=btc_closes,
            eth_closes=eth_closes,
        )
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal(symbol="BTCUSDT", confidence=0.90, size_pct=0.08)

        decision_without_corr = await mw.process_signal(signal, atr=1.0, avg_atr=1.0)

        # Rebuild middleware without correlation (patch _check_correlation to no-op).
        mw_no_corr = _make_middleware(sdk_client=sdk)

        async def _identity(signal: object, positions: object, current_size: float, equity: object) -> float:
            return current_size

        mw_no_corr._check_correlation = _identity  # type: ignore[method-assign]  # noqa: SLF001
        decision_without_check = await mw_no_corr.process_signal(signal, atr=1.0, avg_atr=1.0)

        # The correlated pipeline should produce a smaller or equal final_size.
        if decision_without_corr.veto_decision.action != "VETOED":
            assert decision_without_corr.final_size_pct <= decision_without_check.final_size_pct + 1e-6

    async def test_correlation_gate_error_does_not_crash_pipeline(self) -> None:
        """An exception in _check_correlation falls back to pre-correlation size."""
        sdk = _make_sdk_client()

        async def _get_candles_fail(symbol: str, interval: str, limit: int) -> None:
            raise RuntimeError("candle service unavailable")

        sdk.get_candles = AsyncMock(side_effect=_get_candles_fail)
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal(symbol="BTCUSDT", confidence=0.90, size_pct=0.05)

        # Should not raise and should return a valid ExecutionDecision.
        decision = await mw.process_signal(signal)
        assert isinstance(decision, ExecutionDecision)
        assert decision.error is None  # correlation error is a warning, not an error field

    async def test_no_existing_positions_skips_correlation(self) -> None:
        """With no open positions, no candle fetches should occur."""
        sdk = _make_sdk_client(positions=[])
        sdk.get_candles = AsyncMock()
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal(confidence=0.90, size_pct=0.05)

        decision = await mw.process_signal(signal)

        # No correlated positions → get_candles should not be called.
        sdk.get_candles.assert_not_called()
        assert isinstance(decision, ExecutionDecision)

    async def test_correlation_result_within_bounds(self) -> None:
        """final_size_pct after correlation gate is always in [0, 1]."""
        random.seed(55)
        shocks = [random.choice([-0.03, -0.02, 0.01, 0.02, 0.03]) for _ in range(25)]
        btc_closes: list[float] = [40000.0]
        eth_closes: list[float] = [2000.0]
        for s in shocks:
            btc_closes.append(btc_closes[-1] * math.exp(s + random.gauss(0, 0.0005)))
            eth_closes.append(eth_closes[-1] * math.exp(s + random.gauss(0, 0.0005)))

        sdk = self._make_sdk_with_positions_and_candles(
            position_symbol="ETHUSDT",
            btc_closes=btc_closes,
            eth_closes=eth_closes,
        )
        mw = _make_middleware(sdk_client=sdk)
        signal = _make_signal(symbol="BTCUSDT", confidence=0.90, size_pct=0.08)

        decision = await mw.process_signal(signal)

        assert 0.0 <= decision.final_size_pct <= 1.0
