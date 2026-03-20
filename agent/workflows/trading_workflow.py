"""Trading workflow: analyze → signal → execute → monitor → close → evaluate.

Runs the full live-trading lifecycle using the TradeReady platform:

1. Fetch 1 h OHLCV candles for BTC, ETH, and SOL (last 100 each) via the SDK.
2. Ask a Pydantic AI agent (output_type=TradeSignal) to analyse the candles and
   produce a structured trade signal with reasoning and confidence.
3. Validate the signal against the confidence threshold and ``max_trade_pct``.
4. Execute the entry trade directly via the SDK client.
5. Monitor the open position three times (10-second intervals) via the SDK.
6. Close the position with an opposite-side market order.
7. Check account performance via the SDK ``get_performance()`` method.
8. Ask a second Pydantic AI agent (output_type=MarketAnalysis) to evaluate the
   completed trade in context.
9. Return a :class:`~agent.models.report.WorkflowResult` capturing all findings.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

from agent.config import AgentConfig
from agent.models.analysis import MarketAnalysis
from agent.models.report import WorkflowResult
from agent.models.trade_signal import SignalType, TradeSignal
from agent.prompts.system import SYSTEM_PROMPT
from agent.tools.sdk_tools import get_sdk_tools

logger = structlog.get_logger(__name__)

# Total defined steps in this workflow (used for WorkflowResult accounting).
_TOTAL_STEPS = 9


async def run_trading_workflow(config: AgentConfig) -> WorkflowResult:
    """Execute the full trading lifecycle and return a structured result.

    The workflow progresses through nine numbered steps.  Each step is
    completed atomically; any non-critical failure is recorded in
    ``findings`` or ``bugs_found`` and the workflow continues.  A critical
    failure (e.g., unable to fetch candle data or execute the entry trade)
    sets ``status="partial"`` but never raises an exception — the caller
    always receives a valid :class:`~agent.models.report.WorkflowResult`.

    Args:
        config: Resolved :class:`~agent.config.AgentConfig` providing
                platform connectivity settings, LLM model selection, and
                trading risk parameters.

    Returns:
        :class:`~agent.models.report.WorkflowResult` with ``workflow_name``
        set to ``"trading_workflow"``, ``status`` one of ``"pass"``,
        ``"fail"``, or ``"partial"``, and populated ``findings``,
        ``bugs_found``, ``suggestions``, and ``metrics`` fields.
    """
    from agentexchange.async_client import AsyncAgentExchangeClient
    from agentexchange.exceptions import AgentExchangeError
    from pydantic_ai import Agent

    findings: list[str] = []
    bugs_found: list[str] = []
    suggestions: list[str] = []
    metrics: dict[str, Any] = {}
    steps_completed = 0

    log = logger.bind(workflow="trading_workflow")
    log.info("workflow_start", symbols=config.symbols)

    client = AsyncAgentExchangeClient(
        api_key=config.platform_api_key,
        api_secret=config.platform_api_secret,
        base_url=config.platform_base_url,
    )

    try:
        # ------------------------------------------------------------------
        # Step 1: Fetch 1 h candles for BTC, ETH, SOL (100 candles each)
        # ------------------------------------------------------------------
        log.info("step_start", step=1, description="fetch_candles")
        candle_data: dict[str, Any] = {}

        target_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        for sym in target_symbols:
            try:
                candles = await client.get_candles(sym, interval="1h", limit=100)
                candle_data[sym] = [
                    {
                        "time": c.time.isoformat(),
                        "open": str(c.open),
                        "high": str(c.high),
                        "low": str(c.low),
                        "close": str(c.close),
                        "volume": str(c.volume),
                    }
                    for c in candles
                ]
                findings.append(
                    f"Fetched {len(candle_data[sym])} 1h candles for {sym}."
                )
                log.info("candles_fetched", symbol=sym, count=len(candle_data[sym]))
            except AgentExchangeError as exc:
                bugs_found.append(f"Failed to fetch candles for {sym}: {exc}")
                log.warning("candle_fetch_failed", symbol=sym, error=str(exc))

        if not candle_data:
            log.error("no_candle_data_available")
            return WorkflowResult(
                workflow_name="trading_workflow",
                status="fail",
                steps_completed=0,
                steps_total=_TOTAL_STEPS,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        steps_completed += 1

        # ------------------------------------------------------------------
        # Step 2: Run LLM agent to generate a TradeSignal
        # ------------------------------------------------------------------
        log.info("step_start", step=2, description="generate_trade_signal")

        trading_agent: Agent[None, TradeSignal] = Agent(
            config.agent_model,
            output_type=TradeSignal,
            system_prompt=SYSTEM_PROMPT,
            tools=get_sdk_tools(config),
        )

        candle_summary = "\n".join(
            f"{sym}: {len(bars)} 1h bars, latest close = {bars[-1]['close']}"
            for sym, bars in candle_data.items()
        )
        signal_prompt = (
            "Analyse the following 1-hour OHLCV candle data for the listed symbols "
            "and generate a single trade signal for the symbol you judge to have the "
            "strongest setup right now.  Pick the symbol with the clearest directional "
            "momentum and the best risk/reward profile.\n\n"
            f"{candle_summary}\n\n"
            "Full candle data (JSON):\n"
            f"{candle_data}"
        )

        try:
            signal_result = await trading_agent.run(signal_prompt)
            signal: TradeSignal = signal_result.output
            log.info(
                "signal_generated",
                symbol=signal.symbol,
                direction=signal.signal.value,
                confidence=signal.confidence,
                quantity_pct=signal.quantity_pct,
                reasoning=signal.reasoning[:120],
            )
            findings.append(
                f"Signal: {signal.signal.value.upper()} {signal.symbol} "
                f"(confidence={signal.confidence:.2f}, qty_pct={signal.quantity_pct:.3f}). "
                f"Reasoning: {signal.reasoning[:200]}"
            )
            metrics["signal_symbol"] = signal.symbol
            metrics["signal_direction"] = signal.signal.value
            metrics["signal_confidence"] = signal.confidence
        except Exception as exc:  # noqa: BLE001 — Pydantic AI may raise various types
            bugs_found.append(f"LLM agent failed to generate TradeSignal: {exc}")
            log.error("signal_generation_failed", error=str(exc))
            return WorkflowResult(
                workflow_name="trading_workflow",
                status="partial",
                steps_completed=steps_completed,
                steps_total=_TOTAL_STEPS,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        steps_completed += 1

        # ------------------------------------------------------------------
        # Step 3: Validate signal — confidence threshold + position size cap
        # ------------------------------------------------------------------
        log.info("step_start", step=3, description="validate_signal")

        if signal.signal == SignalType.HOLD:
            findings.append(
                "Agent produced HOLD signal — no trade will be placed.  "
                "Marking workflow as partial."
            )
            log.info("hold_signal_received", symbol=signal.symbol)
            return WorkflowResult(
                workflow_name="trading_workflow",
                status="partial",
                steps_completed=steps_completed,
                steps_total=_TOTAL_STEPS,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        if signal.confidence <= 0.5:
            findings.append(
                f"Signal confidence {signal.confidence:.2f} is below the 0.5 threshold. "
                "Trade skipped."
            )
            log.info(
                "signal_rejected_low_confidence",
                symbol=signal.symbol,
                confidence=signal.confidence,
            )
            return WorkflowResult(
                workflow_name="trading_workflow",
                status="partial",
                steps_completed=steps_completed,
                steps_total=_TOTAL_STEPS,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        effective_qty_pct = min(signal.quantity_pct, config.max_trade_pct)
        if effective_qty_pct < signal.quantity_pct:
            findings.append(
                f"Signal quantity_pct {signal.quantity_pct:.3f} exceeds "
                f"max_trade_pct {config.max_trade_pct:.3f}; clamped to "
                f"{effective_qty_pct:.3f}."
            )

        steps_completed += 1

        # ------------------------------------------------------------------
        # Step 4: Execute the entry trade via the SDK client
        # ------------------------------------------------------------------
        log.info("step_start", step=4, description="execute_entry_trade")

        # Fetch current price and USDT balance to size the order
        entry_price: Decimal | None = None
        usdt_balance: Decimal = Decimal("0")
        try:
            price_obj = await client.get_price(signal.symbol)
            entry_price = price_obj.price
            balances = await client.get_balance()
            for bal in balances:
                if bal.asset == "USDT":
                    usdt_balance = bal.available
                    break
        except AgentExchangeError as exc:
            bugs_found.append(
                f"Failed to fetch price or balance before entry: {exc}"
            )
            log.error("pre_trade_fetch_failed", error=str(exc))

        entry_order: dict[str, Any] | None = None
        trade_quantity: Decimal | None = None

        if entry_price is not None and entry_price > Decimal("0") and usdt_balance > Decimal("0"):
            # Max trade quantity = balance × effective_qty_pct / current_price
            raw_quantity = (usdt_balance * Decimal(str(effective_qty_pct))) / entry_price
            # Round to 6 dp to stay within typical exchange precision
            trade_quantity = raw_quantity.quantize(Decimal("0.000001"))
            if trade_quantity <= Decimal("0"):
                bugs_found.append(
                    "Computed trade quantity is zero or negative — skipping entry trade."
                )
                log.warning(
                    "zero_quantity",
                    balance=str(usdt_balance),
                    qty_pct=effective_qty_pct,
                    price=str(entry_price),
                )
            else:
                try:
                    order = await client.place_market_order(
                        signal.symbol,
                        signal.signal.value,  # "buy" or "sell"
                        trade_quantity,
                    )
                    entry_order = {
                        "order_id": str(order.order_id),
                        "status": order.status,
                        "symbol": order.symbol,
                        "side": order.side,
                        "executed_price": str(order.executed_price)
                        if order.executed_price is not None
                        else None,
                        "executed_quantity": str(order.executed_quantity)
                        if order.executed_quantity is not None
                        else None,
                        "fee": str(order.fee) if order.fee is not None else None,
                    }
                    metrics["entry_order_id"] = entry_order["order_id"]
                    metrics["entry_status"] = entry_order["status"]
                    metrics["entry_price"] = entry_order["executed_price"]
                    findings.append(
                        f"Entry order placed: {order.side.upper()} {trade_quantity} "
                        f"{signal.symbol} @ {order.executed_price} "
                        f"(order_id={order.order_id}, status={order.status})."
                    )
                    log.info(
                        "entry_order_placed",
                        order_id=str(order.order_id),
                        status=order.status,
                        executed_price=str(order.executed_price),
                        quantity=str(trade_quantity),
                    )
                except AgentExchangeError as exc:
                    bugs_found.append(
                        f"Entry market order failed for {signal.symbol}: {exc}"
                    )
                    log.error(
                        "entry_order_failed",
                        symbol=signal.symbol,
                        side=signal.signal.value,
                        quantity=str(trade_quantity),
                        error=str(exc),
                    )
        else:
            findings.append(
                "Could not size entry trade: price or balance unavailable. "
                "Skipping execution steps."
            )

        steps_completed += 1

        # ------------------------------------------------------------------
        # Step 5: Monitor position — check price 3× with 10 s between checks
        # ------------------------------------------------------------------
        log.info("step_start", step=5, description="monitor_position")

        price_checks: list[str] = []
        for check_num in range(1, 4):
            try:
                current_price = await client.get_price(signal.symbol)
                price_checks.append(
                    f"Check {check_num}: {signal.symbol} = {current_price.price} USDT "
                    f"at {current_price.timestamp.isoformat()}"
                )
                log.info(
                    "price_check",
                    check=check_num,
                    symbol=signal.symbol,
                    price=str(current_price.price),
                )
            except AgentExchangeError as exc:
                price_checks.append(f"Check {check_num}: price fetch failed — {exc}")
                bugs_found.append(
                    f"Price monitoring check {check_num} failed for "
                    f"{signal.symbol}: {exc}"
                )

            if check_num < 3:
                await asyncio.sleep(10)

        findings.extend(price_checks)
        metrics["price_checks"] = price_checks

        steps_completed += 1

        # ------------------------------------------------------------------
        # Step 6: Close position with an opposite-side market order
        # ------------------------------------------------------------------
        log.info("step_start", step=6, description="close_position")

        close_order: dict[str, Any] | None = None

        if entry_order is not None and entry_order.get("status") == "filled":
            close_side = "sell" if signal.signal == SignalType.BUY else "buy"

            # Use executed quantity from the entry order; fall back to computed qty
            qty_to_close: Decimal | None = None
            raw_exec_qty = entry_order.get("executed_quantity")
            if raw_exec_qty is not None:
                try:
                    qty_to_close = Decimal(raw_exec_qty)
                except InvalidOperation:
                    pass

            if qty_to_close is None:
                qty_to_close = trade_quantity  # type: ignore[assignment]

            if qty_to_close is not None and qty_to_close > Decimal("0"):
                try:
                    close = await client.place_market_order(
                        signal.symbol,
                        close_side,
                        qty_to_close,
                    )
                    close_order = {
                        "order_id": str(close.order_id),
                        "status": close.status,
                        "executed_price": str(close.executed_price)
                        if close.executed_price is not None
                        else None,
                        "executed_quantity": str(close.executed_quantity)
                        if close.executed_quantity is not None
                        else None,
                    }
                    metrics["close_order_id"] = close_order["order_id"]
                    metrics["close_status"] = close_order["status"]
                    metrics["close_price"] = close_order["executed_price"]
                    findings.append(
                        f"Position closed: {close_side.upper()} {qty_to_close} "
                        f"{signal.symbol} @ {close.executed_price} "
                        f"(order_id={close.order_id}, status={close.status})."
                    )
                    log.info(
                        "position_closed",
                        order_id=str(close.order_id),
                        status=close.status,
                        executed_price=str(close.executed_price),
                        quantity=str(qty_to_close),
                    )
                except AgentExchangeError as exc:
                    bugs_found.append(
                        f"Close order failed for {signal.symbol} ({close_side}): {exc}"
                    )
                    log.error(
                        "close_order_failed",
                        symbol=signal.symbol,
                        side=close_side,
                        quantity=str(qty_to_close),
                        error=str(exc),
                    )
            else:
                findings.append(
                    "Could not determine close quantity — position may remain open."
                )
                bugs_found.append(
                    f"Unable to determine close quantity for {signal.symbol}; "
                    "account may have an unclosed position."
                )
        else:
            findings.append(
                "Entry order was not filled (or was not placed) — no close order needed."
            )

        steps_completed += 1

        # ------------------------------------------------------------------
        # Step 7: Check PnL via get_performance()
        # ------------------------------------------------------------------
        log.info("step_start", step=7, description="check_performance")

        try:
            perf = await client.get_performance(period="all")
            metrics["sharpe_ratio"] = str(perf.sharpe_ratio)
            metrics["max_drawdown_pct"] = str(perf.max_drawdown_pct)
            metrics["win_rate"] = str(perf.win_rate)
            metrics["profit_factor"] = str(perf.profit_factor)
            metrics["total_trades"] = perf.total_trades
            findings.append(
                f"Performance after workflow — "
                f"Sharpe: {perf.sharpe_ratio}, "
                f"Win rate: {perf.win_rate}, "
                f"Max drawdown: {perf.max_drawdown_pct}, "
                f"Total trades: {perf.total_trades}."
            )
            log.info(
                "performance_fetched",
                sharpe=str(perf.sharpe_ratio),
                win_rate=str(perf.win_rate),
                total_trades=perf.total_trades,
            )
        except AgentExchangeError as exc:
            bugs_found.append(f"get_performance() failed: {exc}")
            log.warning("performance_fetch_failed", error=str(exc))

        steps_completed += 1

        # ------------------------------------------------------------------
        # Step 8: Evaluate results with a MarketAnalysis agent
        # ------------------------------------------------------------------
        log.info("step_start", step=8, description="evaluate_results")

        evaluation_agent: Agent[None, MarketAnalysis] = Agent(
            config.agent_model,
            output_type=MarketAnalysis,
            system_prompt=SYSTEM_PROMPT,
            tools=get_sdk_tools(config),
        )

        perf_summary = (
            f"Sharpe ratio: {metrics.get('sharpe_ratio', 'N/A')}, "
            f"Win rate: {metrics.get('win_rate', 'N/A')}, "
            f"Max drawdown: {metrics.get('max_drawdown_pct', 'N/A')}, "
            f"Total trades: {metrics.get('total_trades', 'N/A')}."
        )
        trade_summary = (
            f"Entry order: {entry_order}\n"
            f"Close order: {close_order}\n"
            f"Price checks: {price_checks}"
        )
        evaluation_prompt = (
            f"You have just completed a live trading workflow for {signal.symbol}.  "
            f"The original signal was: {signal.signal.value.upper()} with confidence "
            f"{signal.confidence:.2f}.  Reasoning: {signal.reasoning}\n\n"
            f"Trade execution summary:\n{trade_summary}\n\n"
            f"Post-trade account performance:\n{perf_summary}\n\n"
            f"Analyse the {signal.symbol} market conditions at the time of this trade "
            "and produce a MarketAnalysis capturing trend, support/resistance levels, "
            "key indicator readings, and a plain-language summary of what happened and "
            "what could be improved next time."
        )

        market_analysis: MarketAnalysis | None = None
        try:
            eval_result = await evaluation_agent.run(evaluation_prompt)
            market_analysis = eval_result.output
            findings.append(
                f"Post-trade analysis for {market_analysis.symbol}: "
                f"trend={market_analysis.trend}, "
                f"support={market_analysis.support_level}, "
                f"resistance={market_analysis.resistance_level}. "
                f"Summary: {market_analysis.summary[:300]}"
            )
            metrics["market_trend"] = market_analysis.trend
            metrics["support_level"] = market_analysis.support_level
            metrics["resistance_level"] = market_analysis.resistance_level
            log.info(
                "evaluation_complete",
                symbol=market_analysis.symbol,
                trend=market_analysis.trend,
            )
        except Exception as exc:  # noqa: BLE001 — Pydantic AI may raise various types
            bugs_found.append(
                f"Evaluation agent (MarketAnalysis) failed: {exc}"
            )
            log.error("evaluation_failed", error=str(exc))

        steps_completed += 1

        # ------------------------------------------------------------------
        # Step 9: Build and return WorkflowResult
        # ------------------------------------------------------------------
        log.info("step_start", step=9, description="build_result")

        if bugs_found:
            status = "partial" if steps_completed >= _TOTAL_STEPS // 2 else "fail"
        else:
            status = "pass"

        steps_completed += 1
        log.info(
            "workflow_complete",
            status=status,
            steps_completed=steps_completed,
            bugs=len(bugs_found),
            findings=len(findings),
        )

        return WorkflowResult(
            workflow_name="trading_workflow",
            status=status,
            steps_completed=steps_completed,
            steps_total=_TOTAL_STEPS,
            findings=findings,
            bugs_found=bugs_found,
            suggestions=suggestions,
            metrics=metrics,
        )

    finally:
        await client.aclose()
        log.debug("sdk_client_closed")
