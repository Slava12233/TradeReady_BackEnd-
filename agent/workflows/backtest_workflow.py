"""Backtest workflow for the TradeReady Platform Testing Agent.

Runs a complete 7-day backtest lifecycle:
  1. Health check
  2. Discover available data range
  3. Create and start a BTC+ETH backtest session
  4. Trade using a simple moving-average crossover signal (no LLM in the loop)
  5. Advance the simulation in batches of configurable size
  6. Fetch final results
  7. Use Pydantic AI to produce a structured BacktestAnalysis with an improvement plan
  8. Return a WorkflowResult wrapping all observations

The trading loop is deliberately LLM-free — every decision is computed locally
from two simple moving averages over the last N closes — keeping run-times fast
and deterministic.  The LLM is invoked exactly once at the end to analyse the
completed results and propose improvements.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from agent.config import AgentConfig
from agent.models.analysis import BacktestAnalysis
from agent.models.report import WorkflowResult
from agent.prompts.system import SYSTEM_PROMPT
from agent.tools.rest_tools import PlatformRESTClient

logger = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

_WORKFLOW_NAME = "backtest_workflow"
_BACKTEST_SYMBOLS = ["BTCUSDT", "ETHUSDT"]
_BACKTEST_DAYS = 7
_CANDLE_INTERVAL = 60  # 1-minute candles
_STARTING_BALANCE = "10000"
_STRATEGY_LABEL = "agent_ma_crossover"

# Moving-average crossover parameters
_MA_FAST = 5   # fast SMA window (candles)
_MA_SLOW = 20  # slow SMA window (candles)

# Per-symbol order sizes: small test quantities that stay well within risk limits
_ORDER_QTY: dict[str, str] = {
    "BTCUSDT": "0.0001",
    "ETHUSDT": "0.001",
}

# Default to this quantity for any symbol not in the map
_DEFAULT_QTY = "0.001"


# ── Moving-average signal ─────────────────────────────────────────────────────


def _sma(closes: list[float], window: int) -> float | None:
    """Compute a simple moving average over the last *window* values.

    Args:
        closes: Chronologically ordered list of close prices as floats.
        window: Number of most-recent candles to average over.

    Returns:
        The SMA value, or ``None`` if there are fewer values than *window*.
    """
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _ma_signal(closes: list[float]) -> str:
    """Return ``"buy"``, ``"sell"``, or ``"hold"`` from a dual-SMA crossover.

    Uses a fast SMA (period ``_MA_FAST``) and a slow SMA (period ``_MA_SLOW``).
    Signal rules:
    - fast > slow → bullish crossover → ``"buy"``
    - fast < slow → bearish crossover → ``"sell"``
    - otherwise → ``"hold"``

    Args:
        closes: Chronologically ordered close prices (must contain at least
            ``_MA_SLOW`` values to generate a non-hold signal).

    Returns:
        One of ``"buy"``, ``"sell"``, or ``"hold"``.
    """
    fast = _sma(closes, _MA_FAST)
    slow = _sma(closes, _MA_SLOW)
    if fast is None or slow is None:
        return "hold"
    if fast > slow:
        return "buy"
    if fast < slow:
        return "sell"
    return "hold"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_closes(candles_response: dict[str, Any]) -> list[float]:
    """Extract a list of close prices from a ``get_backtest_candles`` response.

    Args:
        candles_response: Raw API response dict from
            :meth:`~agent.tools.rest_tools.PlatformRESTClient.get_backtest_candles`.

    Returns:
        Chronologically ordered list of close prices as ``float``.  Returns an
        empty list if the response is missing the expected shape.
    """
    candles: list[dict[str, Any]] = candles_response.get("candles", [])
    closes: list[float] = []
    for c in candles:
        raw = c.get("close")
        if raw is not None:
            try:
                closes.append(float(raw))
            except (ValueError, TypeError):
                pass
    return closes


def _safe_float(value: Any, default: float = 0.0) -> float:  # noqa: ANN401
    """Convert a value to ``float``, returning *default* on failure.

    Args:
        value: Any value to convert.
        default: Fallback when conversion fails.

    Returns:
        Float representation of *value* or *default*.
    """
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


# ── Workflow ──────────────────────────────────────────────────────────────────


async def run_backtest_workflow(
    config: AgentConfig,
    *,
    max_iterations: int = 20,
    batch_size: int = 5,
) -> WorkflowResult:
    """Execute the full backtest workflow and return a structured result.

    Steps performed:

    1. Health check — ``GET /api/v1/health``
    2. Data-range discovery — ``GET /api/v1/market/data-range``
    3. Create a 7-day backtest session for BTC + ETH
    4. Start the session (bulk preloads candle data)
    5. Trading loop — up to *max_iterations* iterations:

       a. Fetch recent candles for each symbol
       b. Compute dual-SMA signal locally (no LLM)
       c. If signal → place market order
       d. Advance *batch_size* candles via ``step_backtest_batch``
       e. Stop early when ``is_complete`` is returned

    6. Fetch backtest results
    7. Run Pydantic AI LLM analysis → ``BacktestAnalysis``
    8. Build and return ``WorkflowResult``

    Args:
        config: Loaded :class:`~agent.config.AgentConfig` with platform
            connectivity settings and LLM model identifier.
        max_iterations: Maximum number of trade-decision + step iterations.
            Defaults to 20.  Can be reduced for quick smoke tests.
        batch_size: Number of candle steps to advance per iteration.
            Defaults to 5.

    Returns:
        :class:`~agent.models.report.WorkflowResult` with status ``"pass"``,
        ``"partial"``, or ``"fail"``, plus populated *findings*, *bugs_found*,
        *suggestions*, and *metrics*.
    """
    log = logger.bind(workflow=_WORKFLOW_NAME)

    findings: list[str] = []
    bugs_found: list[str] = []
    suggestions: list[str] = []
    metrics: dict[str, Any] = {}
    steps_completed = 0
    steps_total = 7  # health, data-range, create, start, loop, results, analysis

    session_id: str | None = None
    # Track open positions so we can avoid stacking orders on the same symbol
    open_positions: dict[str, str] = {}  # symbol → side

    async with PlatformRESTClient(config) as client:
        # ── Step 1: Health check ──────────────────────────────────────────────
        log.info("agent.workflow.backtest.step.health_check")
        try:
            health_response = await client._get("/api/v1/health")
            status_val = health_response.get("status", "unknown")
            findings.append(f"Platform health: {status_val}")
            log.info("agent.workflow.backtest.health_check.ok", status=status_val)
            steps_completed += 1
        except httpx.HTTPStatusError as exc:
            bug = f"Health check HTTP error {exc.response.status_code}: {exc.response.text[:200]}"
            bugs_found.append(bug)
            log.error("agent.workflow.backtest.health_check.failed", error=bug)
            return WorkflowResult(
                workflow_name=_WORKFLOW_NAME,
                status="fail",
                steps_completed=steps_completed,
                steps_total=steps_total,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )
        except httpx.RequestError as exc:
            bug = f"Health check network error: {exc}"
            bugs_found.append(bug)
            log.error("agent.workflow.backtest.health_check.network_error", error=bug)
            return WorkflowResult(
                workflow_name=_WORKFLOW_NAME,
                status="fail",
                steps_completed=steps_completed,
                steps_total=steps_total,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        # ── Step 2: Discover available data range ─────────────────────────────
        log.info("agent.workflow.backtest.step.data_range")
        end_time: datetime | None = None
        start_time: datetime | None = None

        try:
            data_range = await client._get("/api/v1/market/data-range")
            earliest_str: str | None = data_range.get("earliest")
            latest_str: str | None = data_range.get("latest")

            if latest_str:
                # Parse ISO-8601 timestamp; the API may omit the trailing 'Z'
                latest_str_normalized = latest_str.replace("Z", "+00:00")
                end_time = datetime.fromisoformat(latest_str_normalized).astimezone(UTC)
                # Use a 7-day window ending at latest available data
                start_time = end_time - timedelta(days=_BACKTEST_DAYS)
                findings.append(
                    f"Data range: earliest={earliest_str} latest={latest_str}"
                )
                log.info("agent.workflow.backtest.data_range.ok", earliest=earliest_str, latest=latest_str)
            else:
                findings.append("Data range endpoint returned no 'latest' timestamp; using fallback dates.")
                log.warning("agent.workflow.backtest.data_range.no_latest")

            steps_completed += 1
        except httpx.HTTPStatusError as exc:
            bug = (
                f"Data-range HTTP error {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            )
            bugs_found.append(bug)
            log.warning("agent.workflow.backtest.data_range.http_error", error=bug)
            # Non-fatal — fall through to use a hard-coded fallback window
        except httpx.RequestError as exc:
            bugs_found.append(f"Data-range network error: {exc}")
            log.warning("agent.workflow.backtest.data_range.network_error", error=str(exc))

        # Fallback dates if the data-range call failed or returned no data
        if end_time is None or start_time is None:
            end_time = datetime(2024, 3, 1, 0, 0, 0, tzinfo=UTC)
            start_time = end_time - timedelta(days=_BACKTEST_DAYS)
            findings.append(
                f"Using fallback date range: {start_time.isoformat()} → {end_time.isoformat()}"
            )

        start_iso = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = end_time.strftime("%Y-%m-%dT%H:%M:%SZ")

        # ── Step 3: Create backtest session ───────────────────────────────────
        log.info("agent.workflow.backtest.step.create", start=start_iso, end=end_iso)
        try:
            create_resp = await client.create_backtest(
                start_time=start_iso,
                end_time=end_iso,
                symbols=_BACKTEST_SYMBOLS,
                interval=_CANDLE_INTERVAL,
                starting_balance=_STARTING_BALANCE,
                strategy_label=_STRATEGY_LABEL,
            )
            session_id = create_resp.get("session_id")
            total_steps_api = create_resp.get("total_steps", "unknown")
            estimated_pairs = create_resp.get("estimated_pairs", "unknown")

            if not session_id:
                bugs_found.append(
                    f"create_backtest returned no session_id: {create_resp}"
                )
                log.error("agent.workflow.backtest.create.no_session_id", response=create_resp)
                return WorkflowResult(
                    workflow_name=_WORKFLOW_NAME,
                    status="fail",
                    steps_completed=steps_completed,
                    steps_total=steps_total,
                    findings=findings,
                    bugs_found=bugs_found,
                    suggestions=suggestions,
                    metrics=metrics,
                )

            findings.append(
                f"Backtest session created: id={session_id} "
                f"total_steps={total_steps_api} estimated_pairs={estimated_pairs}"
            )
            metrics["session_id"] = session_id
            log.info("agent.workflow.backtest.create.ok", session_id=session_id, total_steps=total_steps_api)
            steps_completed += 1
        except httpx.HTTPStatusError as exc:
            bug = (
                f"create_backtest HTTP {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            )
            bugs_found.append(bug)
            log.error("agent.workflow.backtest.create.failed", error=bug)
            return WorkflowResult(
                workflow_name=_WORKFLOW_NAME,
                status="fail",
                steps_completed=steps_completed,
                steps_total=steps_total,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        # ── Step 4: Start backtest session ────────────────────────────────────
        log.info("agent.workflow.backtest.step.start", session_id=session_id)
        try:
            start_resp = await client.start_backtest(session_id)
            session_status = start_resp.get("status", "unknown")
            findings.append(f"Backtest session started: status={session_status}")
            log.info("agent.workflow.backtest.start.ok", status=session_status)

            if session_status != "running":
                bugs_found.append(
                    f"start_backtest returned unexpected status='{session_status}' "
                    f"(expected 'running'). Full response: {start_resp}"
                )
                return WorkflowResult(
                    workflow_name=_WORKFLOW_NAME,
                    status="partial",
                    steps_completed=steps_completed,
                    steps_total=steps_total,
                    findings=findings,
                    bugs_found=bugs_found,
                    suggestions=suggestions,
                    metrics=metrics,
                )

            steps_completed += 1
        except httpx.HTTPStatusError as exc:
            bug = (
                f"start_backtest HTTP {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            )
            bugs_found.append(bug)
            log.error("agent.workflow.backtest.start.failed", error=bug)
            return WorkflowResult(
                workflow_name=_WORKFLOW_NAME,
                status="partial",
                steps_completed=steps_completed,
                steps_total=steps_total,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        # ── Step 5: Trading loop ──────────────────────────────────────────────
        log.info(
            "agent.workflow.backtest.step.trading_loop",
            session_id=session_id,
            max_iterations=max_iterations,
            batch_size=batch_size,
        )
        trades_placed = 0
        loop_complete = False

        for iteration in range(max_iterations):
            log.debug("agent.workflow.backtest.loop.iteration", iteration=iteration, session_id=session_id)

            # ── 5a: Fetch candles for each symbol and decide ──────────────────
            for symbol in _BACKTEST_SYMBOLS:
                try:
                    candles_resp = await client.get_backtest_candles(
                        session_id=session_id,
                        symbol=symbol,
                        interval=_CANDLE_INTERVAL,
                        limit=max(_MA_SLOW + 5, 30),
                    )
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    # 404 / 409 after completion is expected — treat as terminal
                    if status_code in (404, 409, 410):
                        log.info(
                            "agent.workflow.backtest.loop.candles_not_found",
                            symbol=symbol,
                            status_code=status_code,
                        )
                        loop_complete = True
                        break
                    bugs_found.append(
                        f"get_backtest_candles({symbol}) HTTP {status_code}: "
                        f"{exc.response.text[:200]}"
                    )
                    continue
                except httpx.RequestError as exc:
                    bugs_found.append(f"get_backtest_candles({symbol}) network error: {exc}")
                    continue

                closes = _extract_closes(candles_resp)
                signal = _ma_signal(closes)

                log.debug(
                    "agent.workflow.backtest.loop.signal",
                    symbol=symbol,
                    signal=signal,
                    closes_count=len(closes),
                )

                # ── 5b/5c: Place order when signal is actionable ──────────────
                if signal in ("buy", "sell"):
                    # Avoid stacking positions: skip if we already hold the same side
                    current_side = open_positions.get(symbol)
                    if current_side == signal:
                        log.debug(
                            "agent.workflow.backtest.loop.skip_duplicate",
                            symbol=symbol,
                            signal=signal,
                        )
                        continue
                    # If we hold the opposite side, also skip (keep it simple)
                    if current_side is not None and current_side != signal:
                        log.debug(
                            "agent.workflow.backtest.loop.skip_opposite",
                            symbol=symbol,
                            current_side=current_side,
                            signal=signal,
                        )
                        continue

                    qty = _ORDER_QTY.get(symbol, _DEFAULT_QTY)
                    try:
                        order_resp = await client.backtest_trade(
                            session_id=session_id,
                            symbol=symbol,
                            side=signal,
                            quantity=qty,
                            order_type="market",
                        )
                        order_status = order_resp.get("status", "unknown")
                        exec_price = order_resp.get("executed_price", "?")
                        findings.append(
                            f"Order placed: {signal.upper()} {qty} {symbol} "
                            f"@ {exec_price} → {order_status}"
                        )
                        open_positions[symbol] = signal
                        trades_placed += 1
                        log.info(
                            "agent.workflow.backtest.loop.order_placed",
                            symbol=symbol,
                            side=signal,
                            qty=qty,
                            status=order_status,
                        )
                    except httpx.HTTPStatusError as exc:
                        status_code = exc.response.status_code
                        if status_code in (404, 409, 410):
                            loop_complete = True
                            break
                        # 422 / 400 → risk rejection, record as finding not bug
                        if status_code in (400, 422):
                            findings.append(
                                f"Order rejected for {symbol} ({signal}): "
                                f"HTTP {status_code} {exc.response.text[:200]}"
                            )
                        else:
                            bugs_found.append(
                                f"backtest_trade({symbol}, {signal}) HTTP {status_code}: "
                                f"{exc.response.text[:200]}"
                            )
                    except httpx.RequestError as exc:
                        bugs_found.append(
                            f"backtest_trade({symbol}, {signal}) network error: {exc}"
                        )

            if loop_complete:
                findings.append("Backtest completed before loop exhausted all iterations.")
                break

            # ── 5d: Advance N candles ─────────────────────────────────────────
            try:
                step_resp = await client.step_backtest_batch(
                    session_id=session_id,
                    steps=batch_size,
                )
                is_complete: bool = step_resp.get("is_complete", False)
                progress_pct = step_resp.get("progress_pct", "?")
                step_num = step_resp.get("step", "?")

                log.debug(
                    "agent.workflow.backtest.loop.stepped",
                    step=step_num,
                    progress_pct=progress_pct,
                    is_complete=is_complete,
                )

                if is_complete:
                    findings.append(
                        f"Backtest auto-completed at step {step_num} "
                        f"({progress_pct}% progress)."
                    )
                    loop_complete = True
                    break

            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code
                if status_code in (404, 409, 410):
                    # Session already completed — exit loop gracefully
                    findings.append(
                        f"Backtest session already completed (HTTP {status_code} on step)."
                    )
                    loop_complete = True
                    break
                bugs_found.append(
                    f"step_backtest_batch HTTP {status_code}: "
                    f"{exc.response.text[:200]}"
                )
                break
            except httpx.RequestError as exc:
                bugs_found.append(f"step_backtest_batch network error: {exc}")
                break

        metrics["trades_placed"] = trades_placed
        metrics["loop_complete"] = loop_complete
        steps_completed += 1  # count the trading loop as one composite step

        # ── Step 6: Fetch results ─────────────────────────────────────────────
        log.info("agent.workflow.backtest.step.get_results", session_id=session_id)
        results: dict[str, Any] = {}
        try:
            results = await client.get_backtest_results(session_id)
            result_status = results.get("status", "unknown")
            summary = results.get("summary", {}) or {}
            bt_metrics = results.get("metrics", {}) or {}

            final_equity = summary.get("final_equity", "?")
            roi_pct = summary.get("roi_pct", "?")
            total_trades = summary.get("total_trades", 0)

            findings.append(
                f"Backtest results: status={result_status} "
                f"final_equity={final_equity} roi_pct={roi_pct} "
                f"total_trades={total_trades}"
            )

            sharpe = bt_metrics.get("sharpe_ratio")
            max_dd = bt_metrics.get("max_drawdown_pct")
            win_rate = bt_metrics.get("win_rate")

            if sharpe is not None:
                findings.append(f"Metrics — sharpe={sharpe} max_dd={max_dd} win_rate={win_rate}")

            metrics.update(
                {
                    "final_equity": str(final_equity),
                    "roi_pct": str(roi_pct),
                    "total_trades": total_trades,
                    "sharpe_ratio": sharpe,
                    "max_drawdown_pct": max_dd,
                    "win_rate": win_rate,
                }
            )

            if not bt_metrics and total_trades == 0:
                suggestions.append(
                    "No trades were executed — consider increasing batch_size or "
                    "lowering the MA windows so signals fire more frequently."
                )

            log.info(
                "agent.workflow.backtest.get_results.ok",
                status=result_status,
                roi_pct=roi_pct,
                total_trades=total_trades,
            )
            steps_completed += 1
        except httpx.HTTPStatusError as exc:
            bug = (
                f"get_backtest_results HTTP {exc.response.status_code}: "
                f"{exc.response.text[:200]}"
            )
            bugs_found.append(bug)
            log.error("agent.workflow.backtest.get_results.failed", error=bug)
            # Fall through to analysis with empty results dict

    # ── Step 7: LLM analysis ──────────────────────────────────────────────────
    log.info("agent.workflow.backtest.step.llm_analysis", session_id=session_id)
    analysis: BacktestAnalysis | None = None
    try:
        from pydantic_ai import Agent as PydanticAIAgent  # noqa: PLC0415

        analysis_agent = PydanticAIAgent(
            config.agent_model,
            output_type=BacktestAnalysis,
            system_prompt=SYSTEM_PROMPT,
        )

        results_json = json.dumps(results, indent=2, default=str)
        prompt = (
            f"Analyse these backtest results for a {_BACKTEST_DAYS}-day "
            f"MA-crossover strategy on {_BACKTEST_SYMBOLS}.\n\n"
            f"Session ID: {session_id}\n\n"
            f"Results:\n{results_json}\n\n"
            f"Findings so far:\n"
            + "\n".join(f"- {f}" for f in findings)
            + "\n\nProvide a BacktestAnalysis with a concrete improvement_plan."
        )

        from agent.logging_middleware import estimate_llm_cost  # noqa: PLC0415

        _llm_start = time.monotonic()
        ai_result = await analysis_agent.run(prompt)
        _llm_latency_ms = round((time.monotonic() - _llm_start) * 1000, 2)

        analysis = ai_result.output
        _input_tokens: int | None = getattr(
            getattr(ai_result, "usage", None), "input_tokens", None
        )
        _output_tokens: int | None = getattr(
            getattr(ai_result, "usage", None), "output_tokens", None
        )
        log.info(
            "agent.llm.completed",
            model=config.agent_model,
            purpose="backtest_analysis",
            input_tokens=_input_tokens,
            output_tokens=_output_tokens,
            latency_ms=_llm_latency_ms,
            cost_estimate_usd=estimate_llm_cost(
                config.agent_model,
                _input_tokens or 0,
                _output_tokens or 0,
            ),
        )

        metrics["llm_sharpe"] = analysis.sharpe_ratio
        metrics["llm_max_drawdown"] = analysis.max_drawdown
        metrics["llm_win_rate"] = analysis.win_rate
        metrics["llm_pnl"] = analysis.pnl
        metrics["improvement_plan"] = analysis.improvement_plan

        suggestions.extend(analysis.improvement_plan)
        findings.append(
            f"LLM analysis complete — sharpe={analysis.sharpe_ratio:.3f} "
            f"win_rate={analysis.win_rate:.2%} pnl={analysis.pnl}"
        )
        log.info(
            "agent.workflow.backtest.llm_analysis.ok",
            sharpe=analysis.sharpe_ratio,
            win_rate=analysis.win_rate,
        )
        steps_completed += 1
    except Exception as exc:  # noqa: BLE001
        # LLM errors should not kill the overall workflow — record and continue
        bugs_found.append(f"LLM analysis failed: {type(exc).__name__}: {exc}")
        log.error("agent.workflow.backtest.llm_analysis.failed", error=str(exc))
        log.error(
            "agent.llm.failed",
            model=config.agent_model,
            purpose="backtest_analysis",
            error=str(exc),
        )

    # ── Determine overall status ──────────────────────────────────────────────
    if bugs_found:
        # Any bugs push the status to at least "partial"
        overall_status = "partial" if steps_completed >= steps_total - 2 else "fail"
    else:
        overall_status = "pass" if steps_completed == steps_total else "partial"

    log.info(
        "agent.workflow.backtest.complete",
        status=overall_status,
        steps_completed=steps_completed,
        steps_total=steps_total,
        bugs=len(bugs_found),
        trades=trades_placed,
    )

    return WorkflowResult(
        workflow_name=_WORKFLOW_NAME,
        status=overall_status,
        steps_completed=steps_completed,
        steps_total=steps_total,
        findings=findings,
        bugs_found=bugs_found,
        suggestions=suggestions,
        metrics=metrics,
    )
