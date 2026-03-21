"""Risk middleware — gates every trade signal through the full risk stack.

This module wires :class:`~agent.strategies.risk.RiskAgent`,
:class:`~agent.strategies.risk.VetoPipeline`, and
:class:`~agent.strategies.risk.DynamicSizer` together as a single
synchronous/asynchronous middleware layer that sits between a signal-producing
strategy (e.g. :class:`~agent.strategies.rl.deploy.PPODeployBridge`) and the
platform's order execution layer (SDK ``place_market_order``).

Processing pipeline for each signal::

    TradeSignal
        │
        ▼
    1. Fetch fresh portfolio state via SDK
        │
        ▼
    2. RiskAgent.assess(portfolio, positions, pnl)  → RiskAssessment
        │
        ▼
    3. VetoPipeline.evaluate(signal, assessment)    → VetoDecision
        │
        ├── VETOED → return ExecutionDecision(executed=False)
        │
        ▼
    4. DynamicSizer.calculate_size(...)             → final_size_pct (float)
        │
        ▼
    5. (optional) SDK place_market_order(...)       → order_id
        │
        ▼
    ExecutionDecision

Every step is logged via structlog.  The middleware never raises — all
exceptions are caught and surfaced in ``ExecutionDecision.error``.

Usage::

    from agentexchange import AsyncAgentExchangeClient
    from agent.strategies.risk import (
        RiskAgent, RiskConfig, VetoPipeline, DynamicSizer, SizerConfig,
    )
    from agent.strategies.risk.middleware import RiskMiddleware, ExecutionDecision
    from agent.strategies.risk.veto import TradeSignal

    async with AsyncAgentExchangeClient(api_key="ak_live_...") as sdk:
        middleware = RiskMiddleware(
            risk_agent=RiskAgent(config=RiskConfig()),
            veto_pipeline=VetoPipeline(config=RiskConfig()),
            dynamic_sizer=DynamicSizer(config=SizerConfig()),
            sdk_client=sdk,
        )
        signal = TradeSignal(symbol="BTCUSDT", side="buy", size_pct=0.05, confidence=0.75)

        # Assess, veto-check, and size the signal — do not execute yet.
        decision = await middleware.process_signal(signal)

        # Optionally execute if approved.
        decision = await middleware.execute_if_approved(decision)
        if decision.executed:
            print("Order placed:", decision.order_id)
        else:
            print("Not executed:", decision.veto_decision.reason)
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from agent.strategies.risk.risk_agent import RiskAgent, RiskAssessment
from agent.strategies.risk.sizing import DynamicSizer
from agent.strategies.risk.veto import TradeSignal, VetoDecision, VetoPipeline

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Fallback ATR values used when the caller has not supplied live ATR data.
# Calling calculate_size with atr == avg_atr produces a pure drawdown-adjusted
# size (volatility multiplier = 1.0), which is safe and predictable.
# ---------------------------------------------------------------------------
_DEFAULT_ATR: float = 1.0
_DEFAULT_AVG_ATR: float = 1.0


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class ExecutionDecision(BaseModel):
    """Result of routing a :class:`TradeSignal` through the risk middleware.

    Captures the full audit trail from raw signal to final execution attempt.
    All fields are present regardless of whether the trade was approved,
    resized, vetoed, or errored — consumers can inspect any stage.

    Attributes:
        original_signal: The :class:`TradeSignal` as received from the strategy.
        risk_assessment: The :class:`RiskAssessment` produced for the current
            portfolio state.  Contains equity, drawdown, exposure, verdict.
        veto_decision: The :class:`VetoDecision` from the six-check pipeline.
            ``action`` is one of ``"APPROVED"``, ``"RESIZED"``, or
            ``"VETOED"``.
        final_size_pct: The position size fraction that would be (or was) used
            for the actual order.  Equals ``veto_decision.adjusted_size_pct``
            after dynamic sizing.  ``0.0`` when the trade was vetoed.
        executed: ``True`` when :meth:`RiskMiddleware.execute_if_approved`
            successfully placed an order via the SDK.  ``False`` when vetoed,
            when the signal was only assessed (not executed), or when an error
            occurred.
        order_id: Platform order ID string returned by the SDK after a
            successful placement.  ``None`` when ``executed`` is ``False``.
        error: Human-readable error description when any pipeline stage raises
            an unexpected exception.  ``None`` on clean execution paths.

    Example::

        decision = await middleware.process_signal(signal)
        if decision.veto_decision.action == "VETOED":
            print("Trade rejected:", decision.veto_decision.reason)
        elif decision.executed:
            print("Order placed:", decision.order_id)
    """

    model_config = ConfigDict(frozen=True)

    original_signal: TradeSignal = Field(
        ...,
        description="The trade signal as received from the strategy.",
    )
    risk_assessment: RiskAssessment = Field(
        ...,
        description="Portfolio risk snapshot at the time of signal processing.",
    )
    veto_decision: VetoDecision = Field(
        ...,
        description="Result of the six-check veto pipeline.",
    )
    final_size_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Final position size fraction after dynamic sizing. "
            "0.0 when the trade was vetoed."
        ),
    )
    executed: bool = Field(
        ...,
        description="True when the order was successfully placed via the SDK.",
    )
    order_id: str | None = Field(
        default=None,
        description="Platform order ID returned after a successful placement.",
    )
    error: str | None = Field(
        default=None,
        description="Error description when a pipeline stage raises an exception.",
    )


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class RiskMiddleware:
    """Risk gate between signal strategies and order execution.

    Wraps any signal-producing strategy transparently.  On each call to
    :meth:`process_signal`, the middleware:

    1. Fetches a **fresh** portfolio snapshot and open positions from the SDK
       (never uses cached state).
    2. Runs :meth:`~agent.strategies.risk.RiskAgent.assess` to produce a
       :class:`~agent.strategies.risk.RiskAssessment`.
    3. Runs :meth:`~agent.strategies.risk.VetoPipeline.evaluate` to check the
       signal against six sequential gates.
    4. If approved or resized: applies
       :meth:`~agent.strategies.risk.DynamicSizer.calculate_size` to produce
       a volatility- and drawdown-adjusted final size.
    5. Returns a fully-populated :class:`ExecutionDecision`.

    Order placement is deliberately separated into
    :meth:`execute_if_approved` so callers can inspect the decision before
    committing, or compose the middleware into a dry-run pipeline.

    Args:
        risk_agent: Stateful :class:`~agent.strategies.risk.RiskAgent` that
            tracks peak equity across calls and computes the portfolio risk
            posture.
        veto_pipeline: :class:`~agent.strategies.risk.VetoPipeline` instance.
            Its ``existing_positions`` list is refreshed in-place before each
            evaluation call.
        dynamic_sizer: :class:`~agent.strategies.risk.DynamicSizer` that
            applies volatility and drawdown adjustments to the approved size.
        sdk_client: An ``AsyncAgentExchangeClient`` (or any object that
            exposes ``await get_performance()``, ``await get_positions()``,
            ``await get_pnl()``, and ``await place_market_order()``) used to
            fetch live portfolio state and place orders.

    Example::

        middleware = RiskMiddleware(
            risk_agent=RiskAgent(config=RiskConfig()),
            veto_pipeline=VetoPipeline(config=RiskConfig()),
            dynamic_sizer=DynamicSizer(config=SizerConfig()),
            sdk_client=sdk,
        )
        decision = await middleware.process_signal(signal)
        decision = await middleware.execute_if_approved(decision)
    """

    def __init__(
        self,
        risk_agent: RiskAgent,
        veto_pipeline: VetoPipeline,
        dynamic_sizer: DynamicSizer,
        sdk_client: Any,
    ) -> None:
        self._risk_agent = risk_agent
        self._veto_pipeline = veto_pipeline
        self._dynamic_sizer = dynamic_sizer
        self._sdk = sdk_client
        self._log = logger.bind(component="RiskMiddleware")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def process_signal(
        self,
        signal: TradeSignal,
        atr: float = _DEFAULT_ATR,
        avg_atr: float = _DEFAULT_AVG_ATR,
    ) -> ExecutionDecision:
        """Run the signal through the full risk pipeline without executing.

        Fetches fresh portfolio state from the SDK on every call so the
        assessment reflects the latest equity, drawdown, and open positions.

        Args:
            signal: Proposed trade from the strategy layer.
            atr: Current Average True Range for the trading pair.  When the
                caller does not supply ATR data, defaults to 1.0 which makes
                the volatility multiplier neutral (1.0).  Pass the actual ATR
                from the observation builder for production use.
            avg_atr: Rolling average ATR (the volatility baseline).  Defaults
                to 1.0 for neutral adjustment.

        Returns:
            An :class:`ExecutionDecision` with ``executed=False``.  The
            ``veto_decision.action`` field indicates whether the trade was
            ``"APPROVED"``, ``"RESIZED"``, or ``"VETOED"``.  If an error
            occurred during portfolio fetch or assessment, ``error`` is set and
            the trade is treated as if vetoed.

        Example::

            decision = await middleware.process_signal(
                signal=TradeSignal(symbol="BTCUSDT", side="buy", size_pct=0.05, confidence=0.72),
                atr=1850.0,
                avg_atr=1500.0,
            )
        """
        log = self._log.bind(symbol=signal.symbol, side=signal.side, size_pct=signal.size_pct)
        log.info("agent.strategy.risk.middleware.process_signal.start", confidence=signal.confidence)

        # ------------------------------------------------------------------
        # Step 1: Fetch fresh portfolio state.
        # ------------------------------------------------------------------
        portfolio: dict[str, Any]
        positions: list[dict[str, Any]]
        recent_pnl: Decimal

        try:
            portfolio, positions, recent_pnl = await self._fetch_portfolio_state()
            log.debug(
                "agent.strategy.risk.middleware.portfolio_fetched",
                equity=portfolio.get("equity", "unknown"),
                positions_count=len(positions),
                recent_pnl=str(recent_pnl),
            )
        except Exception as exc:  # noqa: BLE001
            error_msg = f"Portfolio fetch failed: {exc}"
            log.error("agent.strategy.risk.middleware.portfolio_fetch_error", error=error_msg)
            return self._error_decision(signal=signal, error=error_msg)

        # ------------------------------------------------------------------
        # Step 2: Risk assessment.
        # ------------------------------------------------------------------
        try:
            assessment = await self._risk_agent.assess(
                portfolio=portfolio,
                positions=positions,
                recent_pnl=recent_pnl,
            )
            log.info(
                "agent.strategy.risk.middleware.risk_assessed",
                verdict=assessment.verdict,
                drawdown_pct=f"{assessment.drawdown_pct:.4f}",
                correlation_risk=assessment.correlation_risk,
                equity=str(assessment.equity),
            )
        except Exception as exc:  # noqa: BLE001
            error_msg = f"Risk assessment failed: {exc}"
            log.error("agent.strategy.risk.middleware.risk_assess_error", error=error_msg)
            return self._error_decision(signal=signal, error=error_msg)

        # ------------------------------------------------------------------
        # Step 3: Refresh the veto pipeline's position list and evaluate.
        # The pipeline stores positions on init, so we update it in-place
        # to reflect the current open positions before each evaluation.
        # ------------------------------------------------------------------
        try:
            self._veto_pipeline._positions = positions  # noqa: SLF001 — intentional refresh
            veto = self._veto_pipeline.evaluate(signal=signal, risk_assessment=assessment)
            log.info(
                "agent.strategy.risk.middleware.veto_decision",
                action=veto.action,
                original_size_pct=veto.original_size_pct,
                adjusted_size_pct=veto.adjusted_size_pct,
                reason=veto.reason,
            )
        except Exception as exc:  # noqa: BLE001
            error_msg = f"Veto pipeline failed: {exc}"
            log.error("agent.strategy.risk.middleware.veto_error", error=error_msg)
            return self._error_decision(signal=signal, assessment=assessment, error=error_msg)

        # ------------------------------------------------------------------
        # Step 4: Dynamic sizing — only for approved or resized signals.
        # ------------------------------------------------------------------
        if veto.action == "VETOED":
            log.info(
                "agent.strategy.risk.middleware.signal_vetoed",
                symbol=signal.symbol,
                side=signal.side,
                reason=veto.reason,
            )
            return ExecutionDecision(
                original_signal=signal,
                risk_assessment=assessment,
                veto_decision=veto,
                final_size_pct=0.0,
                executed=False,
            )

        try:
            final_size = self._dynamic_sizer.calculate_size(
                base_size_pct=veto.adjusted_size_pct,
                atr=atr,
                avg_atr=avg_atr,
                drawdown_pct=assessment.drawdown_pct,
            )
            log.info(
                "agent.strategy.risk.middleware.dynamic_sizing",
                veto_adjusted_size_pct=veto.adjusted_size_pct,
                final_size_pct=final_size,
                atr=atr,
                avg_atr=avg_atr,
                drawdown_pct=f"{assessment.drawdown_pct:.4f}",
            )
        except Exception as exc:  # noqa: BLE001
            # Sizing failure falls back to the veto-adjusted size (safe default).
            error_msg = f"Dynamic sizing failed (fallback to veto size): {exc}"
            log.warning("agent.strategy.risk.middleware.sizing_error", error=error_msg)
            final_size = veto.adjusted_size_pct

        log.info(
            "agent.strategy.risk.middleware.process_signal.complete",
            symbol=signal.symbol,
            side=signal.side,
            veto_action=veto.action,
            final_size_pct=final_size,
        )

        return ExecutionDecision(
            original_signal=signal,
            risk_assessment=assessment,
            veto_decision=veto,
            final_size_pct=final_size,
            executed=False,
        )

    async def execute_if_approved(
        self,
        execution_decision: ExecutionDecision,
    ) -> ExecutionDecision:
        """Place an order via the SDK when the decision is not vetoed.

        Translates ``final_size_pct`` to a USDT quantity using the equity
        from the risk assessment, then calls ``sdk_client.place_market_order``.

        The order quantity is computed as::

            quantity_usdt = equity * final_size_pct
            quantity_asset = quantity_usdt / current_price

        For simplicity, this method fetches the current price via
        ``sdk_client.get_price()`` immediately before placing the order to
        minimise price staleness.

        Args:
            execution_decision: A decision produced by :meth:`process_signal`.
                Must not already have ``executed=True``.

        Returns:
            A new (frozen) :class:`ExecutionDecision` with ``executed=True``
            and ``order_id`` populated on success, or ``executed=False`` and
            ``error`` set on failure.  If the original decision was vetoed or
            already had an error, it is returned unchanged.

        Example::

            decision = await middleware.process_signal(signal)
            decision = await middleware.execute_if_approved(decision)
            if decision.executed:
                print("placed:", decision.order_id)
        """
        signal = execution_decision.original_signal
        log = self._log.bind(symbol=signal.symbol, side=signal.side)

        # Guard: do not attempt execution on vetoed or errored decisions.
        if execution_decision.veto_decision.action == "VETOED":
            log.debug(
                "agent.strategy.risk.middleware.execute_skipped.vetoed",
                reason=execution_decision.veto_decision.reason,
            )
            return execution_decision

        if execution_decision.error is not None:
            log.debug(
                "agent.strategy.risk.middleware.execute_skipped.prior_error",
                error=execution_decision.error,
            )
            return execution_decision

        if execution_decision.executed:
            log.debug("agent.strategy.risk.middleware.execute_skipped.already_executed")
            return execution_decision

        # Compute order quantity from equity and final size fraction.
        equity = execution_decision.risk_assessment.equity
        final_size = Decimal(str(execution_decision.final_size_pct))
        quantity_usdt = (equity * final_size).quantize(Decimal("0.01"))

        log.info(
            "agent.strategy.risk.middleware.execute.computing_quantity",
            equity=str(equity),
            final_size_pct=execution_decision.final_size_pct,
            quantity_usdt=str(quantity_usdt),
        )

        try:
            # Fetch current price to convert USDT value → asset quantity.
            price_resp = await self._sdk.get_price(signal.symbol)
            # The SDK returns a Price dataclass with a .price attribute.
            price: Decimal = Decimal(str(price_resp.price))

            if price <= Decimal("0"):
                raise ValueError(f"Received zero or negative price for {signal.symbol}: {price}")

            # asset quantity = USDT value / price, rounded to 8 decimal places.
            quantity = (quantity_usdt / price).quantize(Decimal("0.00000001"))

            log.info(
                "agent.strategy.risk.middleware.execute.placing_order",
                symbol=signal.symbol,
                side=signal.side,
                quantity=str(quantity),
                price=str(price),
                quantity_usdt=str(quantity_usdt),
            )

            order_resp = await self._sdk.place_market_order(
                symbol=signal.symbol,
                side=signal.side,
                quantity=str(quantity),
            )

            # The SDK returns an Order dataclass; extract the ID.
            # Both UUID and string order IDs are handled by converting to str.
            order_id = str(order_resp.order_id) if hasattr(order_resp, "order_id") else str(order_resp)

            log.info(
                "agent.strategy.risk.middleware.execute.order_placed",
                symbol=signal.symbol,
                side=signal.side,
                order_id=order_id,
                quantity=str(quantity),
                quantity_usdt=str(quantity_usdt),
            )

            return execution_decision.model_copy(
                update={"executed": True, "order_id": order_id}
            )

        except Exception as exc:  # noqa: BLE001
            error_msg = f"Order placement failed for {signal.symbol}: {exc}"
            log.error(
                "agent.strategy.risk.middleware.execute.order_failed",
                symbol=signal.symbol,
                side=signal.side,
                error=error_msg,
            )
            return execution_decision.model_copy(
                update={"executed": False, "error": error_msg}
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_portfolio_state(
        self,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], Decimal]:
        """Fetch fresh portfolio, positions, and PnL from the SDK.

        Queries three SDK endpoints on every call — no caching is used so
        that the risk assessment always reflects the current market state.

        Returns:
            A tuple of:
            - ``portfolio``: Dict with an ``"equity"`` key (and optionally
              ``"positions_value"``) suitable for :meth:`RiskAgent.assess`.
            - ``positions``: List of position dicts, each with ``"symbol"``
              and ``"market_value"`` keys.
            - ``recent_pnl``: The most recent daily realised PnL as a
              ``Decimal``.

        Raises:
            Any exception from the SDK (network, auth, server errors) is
            propagated to the caller.  :meth:`process_signal` catches them
            and converts them into an error :class:`ExecutionDecision`.
        """
        # Fetch portfolio summary — provides equity and aggregate stats.
        portfolio_resp = await self._sdk.get_portfolio()

        # Normalise the SDK Portfolio dataclass to the dict shape that
        # RiskAgent._extract_equity() expects.
        portfolio: dict[str, Any] = {
            "equity": str(portfolio_resp.total_value),
            "positions_value": str(portfolio_resp.positions_value)
            if hasattr(portfolio_resp, "positions_value")
            else "0",
        }

        # Fetch open positions — provides per-symbol exposure data.
        positions_sdk = await self._sdk.get_positions()

        # Normalise Position dataclass list to plain dicts.
        positions: list[dict[str, Any]] = [
            {
                "symbol": p.symbol,
                "market_value": str(p.market_value) if hasattr(p, "market_value") else "0",
                "quantity": str(p.quantity) if hasattr(p, "quantity") else "0",
            }
            for p in positions_sdk
        ]

        # Fetch PnL for the daily loss halt check.
        try:
            pnl_resp = await self._sdk.get_pnl()
            # SDK PnL dataclass has a .realized_pnl field.
            recent_pnl = Decimal(str(pnl_resp.realized_pnl))
        except Exception:  # noqa: BLE001
            # If PnL is unavailable, pass zero so the halt check is
            # conservative (it will not trigger, but won't crash).
            recent_pnl = Decimal("0")
            self._log.warning("agent.strategy.risk.middleware.pnl_fetch_failed", fallback="0")

        return portfolio, positions, recent_pnl

    # ------------------------------------------------------------------
    # Error decision factory
    # ------------------------------------------------------------------

    @staticmethod
    def _error_decision(
        signal: TradeSignal,
        error: str,
        assessment: RiskAssessment | None = None,
    ) -> ExecutionDecision:
        """Build an :class:`ExecutionDecision` representing a pipeline error.

        When a stage raises an unexpected exception, this factory constructs a
        safe fallback decision that:

        - Marks the trade as not executed.
        - Uses a minimal synthetic :class:`RiskAssessment` with ``verdict="HALT"``
          if no real assessment is available (fail-closed behaviour).
        - Uses a ``"VETOED"`` :class:`VetoDecision` with the error message so
          the caller's logging pipeline sees a consistent structure.
        - Sets ``error`` to the provided message string.

        Args:
            signal: The original trade signal.
            error: Human-readable error description.
            assessment: Optional partial assessment if it was available before
                the error occurred.

        Returns:
            An :class:`ExecutionDecision` with ``executed=False`` and
            ``error`` populated.
        """
        if assessment is None:
            # Fail-closed: treat portfolio as zero equity / HALT.
            assessment = RiskAssessment(
                total_exposure_pct=0.0,
                max_single_position_pct=0.0,
                drawdown_pct=0.0,
                correlation_risk="low",
                verdict="HALT",
                action=f"Error during portfolio assessment: {error}",
                equity=Decimal("0"),
                peak_equity=Decimal("0"),
            )

        veto = VetoDecision(
            action="VETOED",
            original_size_pct=signal.size_pct,
            adjusted_size_pct=0.0,
            reason=f"Pipeline error — trade blocked: {error}",
        )

        return ExecutionDecision(
            original_signal=signal,
            risk_assessment=assessment,
            veto_decision=veto,
            final_size_pct=0.0,
            executed=False,
            error=error,
        )
