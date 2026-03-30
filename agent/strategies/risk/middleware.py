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
    5. Correlation check: _check_correlation()      → correlation-adjusted size
       • Fetches 20-period candle returns for the proposed asset and each open
         position via SDK get_candles()
       • Computes rolling Pearson correlation on log-returns
       • If max(|r|) > 0.7 with any existing position: size *= (1 - max_corr)
       • Caps total correlated exposure at 2× single-position risk budget
        │
        ▼
    6. (optional) SDK place_market_order(...)       → order_id
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

import asyncio
import math
from decimal import Decimal
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field

from agent.strategies.risk.risk_agent import RiskAgent, RiskAssessment
from agent.strategies.risk.sizing import DynamicSizer, SizerConfig
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
# Correlation gate constants.
# ---------------------------------------------------------------------------

# Number of candles fetched per symbol for the correlation calculation.
# 20 periods is the minimum for a statistically meaningful estimate.
_CORRELATION_LOOKBACK: int = 20

# Candle interval used when fetching returns data.
_CORRELATION_INTERVAL: str = "1h"

# Pearson |r| threshold above which position size is reduced.
_CORRELATION_THRESHOLD: float = 0.70

# Maximum total correlated exposure expressed as a multiple of the single-
# position risk budget (from SizerConfig.max_single_position).
# Example: if max_single_position = 10 %, correlated exposure cap = 20 %.
_CORRELATED_EXPOSURE_MULTIPLIER: float = 2.0


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
        sdk_client: Any,  # noqa: ANN401 — intentional: accepts any SDK-compatible client
        sizer_config: SizerConfig | None = None,
    ) -> None:
        self._risk_agent = risk_agent
        self._veto_pipeline = veto_pipeline
        self._dynamic_sizer = dynamic_sizer
        self._sdk = sdk_client
        self._sizer_config = sizer_config or SizerConfig()
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

        # ------------------------------------------------------------------
        # Step 5: Correlation check — reduce size when the proposed asset is
        # highly correlated with existing positions.  Errors are non-fatal:
        # the pre-correlation size is used as a safe fallback.
        # ------------------------------------------------------------------
        try:
            corr_size: Decimal = await self._check_correlation(
                signal=signal,
                positions=positions,
                current_size=final_size,
                equity=assessment.equity,
            )
            final_size = float(corr_size)  # float() required: ExecutionDecision.final_size_pct is float
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "agent.strategy.risk.middleware.correlation_check_error",
                error=str(exc),
                fallback_size=final_size,
            )

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

    async def _check_correlation(
        self,
        signal: TradeSignal,
        positions: list[dict[str, Any]],
        current_size: float,
        equity: Decimal,
    ) -> Decimal:
        """Reduce position size when the proposed asset is highly correlated with open positions.

        Fetches 20-period hourly candles for the proposed symbol and for each
        existing position, computes log-return series, and then calculates the
        rolling 20-period Pearson correlation between each pair.

        Size reduction logic:
            * If ``max(|r|) > CORRELATION_THRESHOLD`` (0.70): multiply
              ``current_size`` by ``(1 - max_corr)`` where ``max_corr`` is the
              highest absolute Pearson correlation found across all pairs.
            * After reduction, also enforce a cap: the resulting position must
              not cause total correlated exposure to exceed
              ``2 × max_single_position`` of equity.

        The method is **non-raising** when called from :meth:`process_signal`.
        Any exception bubbles up to the caller's try/except block, which logs a
        warning and falls back to the pre-correlation size.

        Args:
            signal: Proposed trade signal (provides the target symbol).
            positions: Current open positions as normalised dicts with a
                ``"symbol"`` key.  Each symbol's candles are fetched
                concurrently.
            current_size: Position size fraction after dynamic sizing, in
                ``(0, 1]``.
            equity: Current total portfolio equity in USDT (``Decimal``).

        Returns:
            Adjusted position size fraction as a ``float``.  Guaranteed to be
            in ``[0.0, 1.0]``.  Returns ``current_size`` unchanged when there
            are no existing positions to correlate against, or when all
            correlations are below the threshold.

        Example::

            adjusted = await middleware._check_correlation(
                signal=signal,
                positions=[{"symbol": "ETHUSDT"}],
                current_size=0.08,
                equity=Decimal("10000.00"),
            )
            # adjusted < 0.08 when BTC/ETH r > 0.70
        """
        if not positions:
            return Decimal(str(current_size))

        # Collect distinct symbols from existing positions (excluding the
        # proposed symbol itself to avoid self-correlation).
        position_symbols: list[str] = []
        seen: set[str] = set()
        for pos in positions:
            sym = str(pos.get("symbol", "")).upper()
            if sym and sym != signal.symbol.upper() and sym not in seen:
                position_symbols.append(sym)
                seen.add(sym)

        if not position_symbols:
            return Decimal(str(current_size))

        # ----------------------------------------------------------------
        # Fetch candles concurrently — one request per symbol + proposed.
        # ----------------------------------------------------------------
        all_symbols = [signal.symbol] + position_symbols
        candle_results: list[Any] = await asyncio.gather(
            *[
                self._sdk.get_candles(sym, _CORRELATION_INTERVAL, _CORRELATION_LOOKBACK + 1)
                for sym in all_symbols
            ],
            return_exceptions=True,
        )

        # Extract return series (log-returns of close prices).
        returns_by_symbol: dict[str, list[float]] = {}
        for sym, result in zip(all_symbols, candle_results):
            if isinstance(result, BaseException):
                self._log.warning(
                    "agent.strategy.risk.middleware.correlation_candle_error",
                    symbol=sym,
                    error=str(result),
                )
                continue
            series = self._candles_to_log_returns(result)
            if len(series) >= 2:
                returns_by_symbol[sym] = series

        # Need the proposed symbol's returns plus at least one position's.
        proposed_sym = signal.symbol.upper()
        if proposed_sym not in returns_by_symbol:
            self._log.debug(
                "agent.strategy.risk.middleware.correlation_skipped",
                reason="proposed symbol candles unavailable",
                symbol=proposed_sym,
            )
            return Decimal(str(current_size))

        proposed_returns = returns_by_symbol[proposed_sym]

        # ----------------------------------------------------------------
        # Compute rolling Pearson correlation for each position.
        # ----------------------------------------------------------------
        max_corr: float = 0.0
        for sym, pos_returns in returns_by_symbol.items():
            if sym == proposed_sym:
                continue
            corr = self._pearson_correlation(proposed_returns, pos_returns)
            abs_corr = abs(corr)
            if abs_corr > max_corr:
                max_corr = abs_corr
            self._log.debug(
                "agent.strategy.risk.middleware.correlation_pair",
                symbol_a=proposed_sym,
                symbol_b=sym,
                pearson_r=f"{corr:.4f}",
                abs_r=f"{abs_corr:.4f}",
            )

        if max_corr <= _CORRELATION_THRESHOLD:
            self._log.debug(
                "agent.strategy.risk.middleware.correlation_below_threshold",
                max_corr=f"{max_corr:.4f}",
                threshold=_CORRELATION_THRESHOLD,
            )
            return Decimal(str(current_size))

        # ----------------------------------------------------------------
        # Apply proportional size reduction: size *= (1 - max_corr).
        # ----------------------------------------------------------------
        reduction_factor = Decimal(str(1.0 - max_corr))
        reduced_size = Decimal(str(current_size)) * reduction_factor
        self._log.info(
            "agent.strategy.risk.middleware.correlation_size_reduced",
            proposed_symbol=proposed_sym,
            max_corr=f"{max_corr:.4f}",
            reduction_factor=f"{float(reduction_factor):.4f}",
            size_before=f"{current_size:.4f}",
            size_after=f"{float(reduced_size):.4f}",
        )

        # ----------------------------------------------------------------
        # Cap total correlated exposure at 2 × max_single_position.
        # ----------------------------------------------------------------
        max_single = self._sizer_config.max_single_position
        exposure_cap = max_single * Decimal(str(_CORRELATED_EXPOSURE_MULTIPLIER))

        # Sum existing correlated positions' exposure as a fraction of equity.
        if equity > Decimal("0"):
            correlated_exposure = Decimal("0")
            for pos in positions:
                sym = str(pos.get("symbol", "")).upper()
                pos_returns_sym = returns_by_symbol.get(sym)
                if pos_returns_sym is None:
                    continue
                corr = self._pearson_correlation(proposed_returns, pos_returns_sym)
                if abs(corr) > _CORRELATION_THRESHOLD:
                    pos_value = Decimal(str(pos.get("market_value", "0")))
                    correlated_exposure += pos_value / equity

            available_corr_cap = exposure_cap - correlated_exposure
            if available_corr_cap < reduced_size:
                capped = max(available_corr_cap, Decimal("0"))
                self._log.info(
                    "agent.strategy.risk.middleware.correlation_cap_applied",
                    exposure_cap=f"{float(exposure_cap):.4f}",
                    correlated_exposure=f"{float(correlated_exposure):.4f}",
                    size_before=f"{float(reduced_size):.4f}",
                    size_after=f"{float(capped):.4f}",
                )
                reduced_size = capped

        # Clamp to [0, 1].
        clamped_size: Decimal = max(Decimal("0"), min(Decimal("1"), reduced_size))
        return clamped_size

    @staticmethod
    def _candles_to_log_returns(candles: Any) -> list[float]:  # noqa: ANN401
        """Extract log-return series from a candle response.

        Accepts either a list of dicts (``{"close": ...}``) or a list of
        objects with a ``.close`` attribute, as returned by the SDK.

        Args:
            candles: Candle data from the SDK ``get_candles()`` call.  Can be
                a list of dicts or a list of Pydantic/dataclass objects.

        Returns:
            List of log-returns computed as ``ln(close[t] / close[t-1])``.
            Empty list when fewer than 2 close prices are extractable.
        """
        closes: list[float] = []
        try:
            for candle in candles:
                if isinstance(candle, dict):
                    raw = candle.get("close") or candle.get("c")
                else:
                    raw = getattr(candle, "close", None) or getattr(candle, "c", None)
                if raw is not None:
                    try:
                        closes.append(float(raw))
                    except (TypeError, ValueError):
                        continue
        except TypeError:
            return []

        if len(closes) < 2:
            return []

        log_returns: list[float] = []
        for i in range(1, len(closes)):
            prev = closes[i - 1]
            curr = closes[i]
            if prev > 0 and curr > 0:
                log_returns.append(math.log(curr / prev))
        return log_returns

    @staticmethod
    def _pearson_correlation(x: list[float], y: list[float]) -> float:
        """Compute the Pearson correlation coefficient between two return series.

        Uses only the overlapping tail of the two series (``min(len(x), len(y))``
        most recent observations) so comparisons between series of different
        lengths remain valid.  This mimics a rolling 20-period window
        aligned to the most recent candle.

        Args:
            x: First return series (e.g. proposed asset log-returns).
            y: Second return series (e.g. existing position log-returns).

        Returns:
            Pearson r in ``[-1.0, 1.0]``.  Returns ``0.0`` when either series
            is empty, when their overlap is fewer than 2 observations, or when
            the standard deviation of either series is zero (constant series).
        """
        n = min(len(x), len(y))
        if n < 2:
            return 0.0

        # Align to the most-recent n observations.
        xs = x[-n:]
        ys = y[-n:]

        mean_x = sum(xs) / n
        mean_y = sum(ys) / n

        cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(xs, ys)) / n
        var_x = sum((a - mean_x) ** 2 for a in xs) / n
        var_y = sum((b - mean_y) ** 2 for b in ys) / n

        denom = math.sqrt(var_x * var_y)
        if denom == 0.0:
            return 0.0
        return cov / denom

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
