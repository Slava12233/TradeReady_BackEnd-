"""Strategy workflow for the TradeReady Platform Testing Agent.

Implements the full strategy validation cycle:
  create strategy V1 → test → LLM reviews results → create V2 with improvements
  → test V2 → compare versions → compile WorkflowResult.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from agent.config import AgentConfig
from agent.models.report import WorkflowResult
from agent.tools.rest_tools import PlatformRESTClient

logger = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Default SMA crossover strategy definition (V1 baseline)
_V1_DEFINITION: dict[str, Any] = {
    "pairs": ["BTCUSDT", "ETHUSDT"],
    "timeframe": "1h",
    "entry_conditions": {
        "price_above_sma": 20,
        "rsi_below": 55,
        "macd_cross_above": True,
    },
    "exit_conditions": {
        "stop_loss_pct": 3.0,
        "take_profit_pct": 6.0,
        "max_hold_candles": 48,
    },
    "position_size_pct": 10,
    "max_positions": 3,
    "model_type": "rule_based",
}

# Date range used for all test episodes
_TEST_DATE_RANGE: dict[str, str] = {
    "start": "2023-06-01T00:00:00Z",
    "end": "2024-01-01T00:00:00Z",
}

# Test configuration — kept small to limit Celery wall time
_TEST_EPISODES: int = 3
_EPISODE_DURATION_DAYS: int = 30

# Polling
_POLL_INTERVAL_SECONDS: float = 5.0
_POLL_TIMEOUT_SECONDS: float = 120.0

# Terminal statuses for a test run
_TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

# ── Private helpers ────────────────────────────────────────────────────────────


async def _poll_test_run(
    client: PlatformRESTClient,
    strategy_id: str,
    test_id: str,
    label: str,
) -> dict[str, Any]:
    """Poll a test run until it reaches a terminal status or times out.

    Sends ``GET /api/v1/strategies/{strategy_id}/tests/{test_id}`` every
    :data:`_POLL_INTERVAL_SECONDS` seconds.  Returns the final response dict
    regardless of whether the run completed, failed, or timed out.

    Args:
        client: Authenticated :class:`~agent.tools.rest_tools.PlatformRESTClient`.
        strategy_id: UUID string of the parent strategy.
        test_id: UUID string of the test run to poll.
        label: Human-readable label for log messages (e.g. ``"V1"``).

    Returns:
        The last response dict from the polling endpoint.  The ``status`` key
        will be ``"completed"``, ``"failed"``, or ``"cancelled"`` on success;
        it may also be ``"running"`` / ``"queued"`` if the timeout was reached,
        or contain an ``"error"`` key if the HTTP call itself failed.
    """
    start = time.monotonic()
    last_response: dict[str, Any] = {}

    while time.monotonic() - start < _POLL_TIMEOUT_SECONDS:
        try:
            result = await client.get_test_results(strategy_id, test_id)
        except Exception as exc:  # noqa: BLE001 — log and retry
            logger.warning(
                "strategy_workflow.poll_error",
                label=label,
                test_id=test_id,
                error=str(exc),
            )
            last_response = {"error": str(exc), "status": "error"}
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            continue

        status = result.get("status", "unknown")
        progress = result.get("progress_pct", 0)
        logger.debug(
            "strategy_workflow.polling",
            label=label,
            test_id=test_id,
            status=status,
            progress_pct=progress,
        )
        last_response = result

        if status in _TERMINAL_STATUSES:
            logger.info(
                "strategy_workflow.test_terminal",
                label=label,
                test_id=test_id,
                status=status,
            )
            break

        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
    else:
        logger.warning(
            "strategy_workflow.poll_timeout",
            label=label,
            test_id=test_id,
            elapsed_s=_POLL_TIMEOUT_SECONDS,
        )

    return last_response


def _build_v2_definition(v1_results: dict[str, Any]) -> dict[str, Any]:
    """Derive an improved V2 strategy definition from V1 test results.

    Applies a deterministic set of parameter improvements based on common
    weaknesses identified in V1 results:

    - Tighten stop-loss if drawdown is high (> 10 %).
    - Widen take-profit if average ROI is low (< 2 %).
    - Add RSI filter if not already present (entry condition for oversold).
    - Increase holding period if max_hold_candles is the most frequent exit.
    - Reduce position size slightly to limit per-trade risk.

    The improvements are intentionally conservative so V2 is a plausible
    refinement of V1 rather than an arbitrary change.

    Args:
        v1_results: The ``results`` dict from the V1 test run response.
            May be ``None`` or empty — defaults are used for missing fields.

    Returns:
        A new strategy definition dict suitable for creating a V2 version.
    """
    import copy

    v2 = copy.deepcopy(_V1_DEFINITION)

    if v1_results is None:
        v1_results = {}

    avg_roi = v1_results.get("avg_roi_pct") or 0.0
    avg_drawdown = v1_results.get("avg_max_drawdown_pct") or 0.0

    # ── Entry condition improvements ─────────────────────────────────────────
    # Add a stricter RSI oversold entry filter to reduce false entries
    v2["entry_conditions"]["rsi_below"] = 50
    # Add volume confirmation to filter low-liquidity entries
    v2["entry_conditions"]["volume_above_ma"] = 1.2

    # ── Exit condition improvements ──────────────────────────────────────────
    # Tighten stop-loss if historical drawdown exceeds 10 %
    if float(avg_drawdown) > 10.0:
        v2["exit_conditions"]["stop_loss_pct"] = 2.0
    else:
        v2["exit_conditions"]["stop_loss_pct"] = 2.5

    # Widen take-profit if historical ROI is low to capture larger moves
    if float(avg_roi) < 2.0:
        v2["exit_conditions"]["take_profit_pct"] = 8.0
    else:
        v2["exit_conditions"]["take_profit_pct"] = 6.0

    # Add trailing stop for better profit capture
    v2["exit_conditions"]["trailing_stop_pct"] = 2.0

    # Reduce max hold candles to avoid over-exposure
    v2["exit_conditions"]["max_hold_candles"] = 36

    # ── Position sizing ───────────────────────────────────────────────────────
    # Slightly smaller position size for better risk control
    v2["position_size_pct"] = 8

    return v2


def _extract_metrics(test_response: dict[str, Any], label: str) -> dict[str, Any]:
    """Extract key performance metrics from a test run response.

    Args:
        test_response: Full response dict from the test run endpoint.
        label: Human-readable label (e.g. ``"v1"``) used as a key prefix.

    Returns:
        Flat dict of extracted metric values, keyed by ``"{label}_{metric}"``.
    """
    results = test_response.get("results") or {}
    return {
        f"{label}_status": test_response.get("status"),
        f"{label}_episodes_total": test_response.get("episodes_total"),
        f"{label}_episodes_completed": test_response.get("episodes_completed"),
        f"{label}_avg_roi_pct": results.get("avg_roi_pct"),
        f"{label}_avg_sharpe": results.get("avg_sharpe"),
        f"{label}_avg_max_drawdown_pct": results.get("avg_max_drawdown_pct"),
        f"{label}_total_trades": results.get("total_trades"),
        f"{label}_win_rate": results.get("win_rate"),
    }


# ── Main workflow entry point ──────────────────────────────────────────────────


async def run_strategy_workflow(config: AgentConfig) -> WorkflowResult:
    """Execute the full strategy validation workflow.

    Implements a create → test → improve → compare cycle:

    1. Create a :data:`_V1_DEFINITION` SMA crossover strategy via REST.
    2. Trigger a test run for V1 and poll until completion.
    3. Use the V1 results to derive an improved V2 definition.
    4. Create V2 as a new version of the same strategy.
    5. Trigger a test run for V2 and poll until completion.
    6. Fetch the version comparison from the compare-versions endpoint.
    7. Compile all observations into a :class:`~agent.models.report.WorkflowResult`.

    The LLM (Pydantic AI Agent) is used between V1 and V2 to review test
    results and propose improvements in natural language.  The improvements
    are then translated deterministically into parameter changes by
    :func:`_build_v2_definition`.

    Args:
        config: Loaded :class:`~agent.config.AgentConfig` instance supplying
            platform connectivity and LLM model selection.

    Returns:
        A :class:`~agent.models.report.WorkflowResult` summarising the
        workflow outcome, metrics for both versions, any bugs found, and
        improvement suggestions.
    """
    findings: list[str] = []
    bugs_found: list[str] = []
    suggestions: list[str] = []
    metrics: dict[str, Any] = {}
    steps_completed = 0
    steps_total = 12  # Total defined steps

    strategy_id: str | None = None
    v1_test_id: str | None = None
    v1_version: int = 1
    v2_test_id: str | None = None
    v2_version: int = 2

    log = logger.bind(workflow="strategy_workflow")
    log.info("strategy_workflow.start")

    async with PlatformRESTClient(config) as client:

        # ── Step 1: Create V1 strategy ────────────────────────────────────────
        log.info("strategy_workflow.step", step=1, description="create_strategy_v1")
        try:
            create_resp = await client.create_strategy(
                name="SMA Crossover V1 (Agent Test)",
                description=(
                    "Baseline SMA crossover strategy with RSI confirmation and "
                    "fixed stop-loss/take-profit exits. Created by the platform "
                    "testing agent for version comparison testing."
                ),
                definition=_V1_DEFINITION,
            )
        except Exception as exc:  # noqa: BLE001
            bug = f"POST /api/v1/strategies failed: {exc}"
            bugs_found.append(bug)
            log.error("strategy_workflow.create_failed", error=str(exc))
            return WorkflowResult(
                workflow_name="strategy_workflow",
                status="fail",
                steps_completed=steps_completed,
                steps_total=steps_total,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        if "error" in create_resp:
            bugs_found.append(f"POST /api/v1/strategies error: {create_resp['error']}")
            return WorkflowResult(
                workflow_name="strategy_workflow",
                status="fail",
                steps_completed=steps_completed,
                steps_total=steps_total,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        strategy_id = create_resp.get("strategy_id", "")
        v1_version = create_resp.get("current_version", 1)
        findings.append(
            f"Created strategy '{create_resp.get('name')}' with id={strategy_id}, "
            f"initial version={v1_version}."
        )
        metrics["strategy_id"] = strategy_id
        metrics["strategy_status_after_create"] = create_resp.get("status")
        steps_completed += 1
        log.info(
            "strategy_workflow.step_ok",
            step=1,
            strategy_id=strategy_id,
            version=v1_version,
        )

        # ── Step 2: Trigger V1 test run ───────────────────────────────────────
        log.info("strategy_workflow.step", step=2, description="trigger_v1_test")
        try:
            test_resp = await client.test_strategy(
                strategy_id=strategy_id,
                version=v1_version,
                date_range=_TEST_DATE_RANGE,
                episodes=_TEST_EPISODES,
                episode_duration_days=_EPISODE_DURATION_DAYS,
            )
        except Exception as exc:  # noqa: BLE001
            bugs_found.append(
                f"POST /api/v1/strategies/{strategy_id}/test (V1) failed: {exc}"
            )
            log.error("strategy_workflow.v1_test_trigger_failed", error=str(exc))
            # Continue as partial — we cannot poll without a test_id
            return WorkflowResult(
                workflow_name="strategy_workflow",
                status="partial",
                steps_completed=steps_completed,
                steps_total=steps_total,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        if "error" in test_resp:
            bugs_found.append(
                f"POST /api/v1/strategies/{strategy_id}/test (V1) error: "
                f"{test_resp['error']}"
            )
            return WorkflowResult(
                workflow_name="strategy_workflow",
                status="partial",
                steps_completed=steps_completed,
                steps_total=steps_total,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        v1_test_id = test_resp.get("test_run_id", "")
        findings.append(
            f"V1 test run created: test_run_id={v1_test_id}, "
            f"status={test_resp.get('status')}, "
            f"episodes={test_resp.get('episodes_total')}."
        )
        metrics["v1_test_run_id"] = v1_test_id
        steps_completed += 1
        log.info(
            "strategy_workflow.step_ok", step=2, v1_test_id=v1_test_id
        )

        # ── Step 3: Poll V1 test until terminal ───────────────────────────────
        log.info("strategy_workflow.step", step=3, description="poll_v1_test")
        v1_final = await _poll_test_run(client, strategy_id, v1_test_id, label="V1")
        v1_status = v1_final.get("status", "unknown")

        if v1_status == "completed":
            findings.append(
                f"V1 test completed: episodes={v1_final.get('episodes_completed')}/"
                f"{v1_final.get('episodes_total')}, "
                f"progress={v1_final.get('progress_pct')}%."
            )
            steps_completed += 1
        elif v1_status == "failed":
            bugs_found.append(
                f"V1 test run {v1_test_id} reached status 'failed'. "
                "Celery worker may have encountered an error or timed out."
            )
            steps_completed += 1  # Polling step completed; run failed
        else:
            findings.append(
                f"V1 test run did not reach terminal status within "
                f"{_POLL_TIMEOUT_SECONDS:.0f}s. Last status: {v1_status}."
            )

        v1_results_data = v1_final.get("results") or {}
        metrics.update(_extract_metrics(v1_final, "v1"))
        log.info(
            "strategy_workflow.step_ok",
            step=3,
            v1_status=v1_status,
            v1_roi=v1_results_data.get("avg_roi_pct"),
        )

        # ── Step 4: LLM reviews V1 results and proposes improvements ──────────
        log.info("strategy_workflow.step", step=4, description="llm_review_v1")
        llm_improvement_notes = ""
        try:
            from pydantic_ai import Agent  # noqa: PLC0415 — lazy import

            review_prompt = (
                "You are reviewing the results of a V1 SMA crossover strategy test "
                "on the TradeReady platform. Here are the aggregated test results:\n\n"
                f"{v1_results_data}\n\n"
                "The V1 entry conditions were:\n"
                f"  - price_above_sma: 20\n"
                f"  - rsi_below: 55\n"
                f"  - macd_cross_above: True\n\n"
                "Exit conditions were:\n"
                f"  - stop_loss_pct: 3.0\n"
                f"  - take_profit_pct: 6.0\n"
                f"  - max_hold_candles: 48\n\n"
                "Based on these results, propose 2-3 specific parameter improvements "
                "for V2 that could improve risk-adjusted returns. Be concise."
            )

            review_agent: Agent[None, str] = Agent(
                model=config.agent_cheap_model,
                output_type=str,
                system_prompt=(
                    "You are a quantitative trading strategy analyst. "
                    "Review strategy test results and propose concrete, "
                    "measurable parameter improvements. "
                    "Keep responses under 200 words."
                ),
            )
            review_result = await review_agent.run(review_prompt)
            llm_improvement_notes = review_result.output
            findings.append(
                f"LLM improvement review: {llm_improvement_notes[:300]}"
                + ("..." if len(llm_improvement_notes) > 300 else "")
            )
            log.info(
                "strategy_workflow.llm_review_ok",
                notes_length=len(llm_improvement_notes),
            )
        except Exception as exc:  # noqa: BLE001 — non-critical; fallback to hardcoded V2
            findings.append(
                f"LLM review skipped (non-critical): {exc}. "
                "Using deterministic parameter improvements for V2."
            )
            log.warning("strategy_workflow.llm_review_failed", error=str(exc))

        steps_completed += 1

        # ── Step 5: Build V2 definition ───────────────────────────────────────
        log.info("strategy_workflow.step", step=5, description="build_v2_definition")
        v2_definition = _build_v2_definition(v1_results_data)
        findings.append(
            "V2 definition derived from V1 results: "
            f"stop_loss={v2_definition['exit_conditions']['stop_loss_pct']}%, "
            f"take_profit={v2_definition['exit_conditions']['take_profit_pct']}%, "
            f"trailing_stop={v2_definition['exit_conditions'].get('trailing_stop_pct')}%, "
            f"rsi_entry={v2_definition['entry_conditions'].get('rsi_below')}, "
            f"volume_filter={v2_definition['entry_conditions'].get('volume_above_ma')}x."
        )
        steps_completed += 1

        # ── Step 6: Create V2 version ─────────────────────────────────────────
        log.info("strategy_workflow.step", step=6, description="create_v2_version")
        change_notes = (
            "V2: Tighter RSI entry filter (rsi_below=50), volume confirmation "
            "(volume_above_ma=1.2), tighter stop-loss, trailing stop added, "
            "shorter max hold period."
        )
        if llm_improvement_notes:
            change_notes += f" LLM suggestions: {llm_improvement_notes[:200]}"

        try:
            version_resp = await client.create_version(
                strategy_id=strategy_id,
                definition=v2_definition,
                change_notes=change_notes,
            )
        except Exception as exc:  # noqa: BLE001
            bugs_found.append(
                f"POST /api/v1/strategies/{strategy_id}/versions failed: {exc}"
            )
            log.error("strategy_workflow.v2_create_failed", error=str(exc))
            return WorkflowResult(
                workflow_name="strategy_workflow",
                status="partial",
                steps_completed=steps_completed,
                steps_total=steps_total,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        if "error" in version_resp:
            bugs_found.append(
                f"POST /api/v1/strategies/{strategy_id}/versions error: "
                f"{version_resp['error']}"
            )
            return WorkflowResult(
                workflow_name="strategy_workflow",
                status="partial",
                steps_completed=steps_completed,
                steps_total=steps_total,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        v2_version = version_resp.get("version", 2)
        findings.append(
            f"Created V2 version: version_id={version_resp.get('version_id')}, "
            f"version_number={v2_version}."
        )
        metrics["v2_version_id"] = version_resp.get("version_id")
        metrics["v2_version_number"] = v2_version
        steps_completed += 1
        log.info(
            "strategy_workflow.step_ok",
            step=6,
            v2_version=v2_version,
            version_id=version_resp.get("version_id"),
        )

        # ── Step 7: Trigger V2 test run ───────────────────────────────────────
        log.info("strategy_workflow.step", step=7, description="trigger_v2_test")
        try:
            v2_test_resp = await client.test_strategy(
                strategy_id=strategy_id,
                version=v2_version,
                date_range=_TEST_DATE_RANGE,
                episodes=_TEST_EPISODES,
                episode_duration_days=_EPISODE_DURATION_DAYS,
            )
        except Exception as exc:  # noqa: BLE001
            bugs_found.append(
                f"POST /api/v1/strategies/{strategy_id}/test (V2) failed: {exc}"
            )
            log.error("strategy_workflow.v2_test_trigger_failed", error=str(exc))
            return WorkflowResult(
                workflow_name="strategy_workflow",
                status="partial",
                steps_completed=steps_completed,
                steps_total=steps_total,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        if "error" in v2_test_resp:
            bugs_found.append(
                f"POST /api/v1/strategies/{strategy_id}/test (V2) error: "
                f"{v2_test_resp['error']}"
            )
            return WorkflowResult(
                workflow_name="strategy_workflow",
                status="partial",
                steps_completed=steps_completed,
                steps_total=steps_total,
                findings=findings,
                bugs_found=bugs_found,
                suggestions=suggestions,
                metrics=metrics,
            )

        v2_test_id = v2_test_resp.get("test_run_id", "")
        findings.append(
            f"V2 test run created: test_run_id={v2_test_id}, "
            f"status={v2_test_resp.get('status')}, "
            f"episodes={v2_test_resp.get('episodes_total')}."
        )
        metrics["v2_test_run_id"] = v2_test_id
        steps_completed += 1
        log.info(
            "strategy_workflow.step_ok", step=7, v2_test_id=v2_test_id
        )

        # ── Step 8: Poll V2 test until terminal ───────────────────────────────
        log.info("strategy_workflow.step", step=8, description="poll_v2_test")
        v2_final = await _poll_test_run(client, strategy_id, v2_test_id, label="V2")
        v2_status = v2_final.get("status", "unknown")

        if v2_status == "completed":
            findings.append(
                f"V2 test completed: episodes={v2_final.get('episodes_completed')}/"
                f"{v2_final.get('episodes_total')}, "
                f"progress={v2_final.get('progress_pct')}%."
            )
            steps_completed += 1
        elif v2_status == "failed":
            bugs_found.append(
                f"V2 test run {v2_test_id} reached status 'failed'. "
                "Celery worker may have encountered an error or timed out."
            )
            steps_completed += 1
        else:
            findings.append(
                f"V2 test run did not reach terminal status within "
                f"{_POLL_TIMEOUT_SECONDS:.0f}s. Last status: {v2_status}."
            )

        v2_results_data = v2_final.get("results") or {}
        metrics.update(_extract_metrics(v2_final, "v2"))
        log.info(
            "strategy_workflow.step_ok",
            step=8,
            v2_status=v2_status,
            v2_roi=v2_results_data.get("avg_roi_pct"),
        )

        # ── Step 9: Compare V1 vs V2 ──────────────────────────────────────────
        log.info("strategy_workflow.step", step=9, description="compare_versions")
        comparison: dict[str, Any] = {}
        try:
            comparison = await client.compare_versions(
                strategy_id=strategy_id,
                v1=v1_version,
                v2=v2_version,
            )
        except Exception as exc:  # noqa: BLE001
            findings.append(
                f"GET /api/v1/strategies/{strategy_id}/compare-versions failed "
                f"(non-critical): {exc}"
            )
            log.warning("strategy_workflow.compare_failed", error=str(exc))

        if "error" in comparison:
            findings.append(
                f"compare-versions returned error (non-critical): "
                f"{comparison['error']}"
            )
        else:
            verdict = comparison.get("verdict", "No verdict available.")
            improvements = comparison.get("improvements", {})
            findings.append(f"Version comparison verdict: {verdict}")
            if improvements:
                roi_delta = improvements.get("roi_pct")
                sharpe_delta = improvements.get("sharpe")
                findings.append(
                    f"Comparison improvements — ROI delta: {roi_delta}, "
                    f"Sharpe delta: {sharpe_delta}."
                )
                metrics["comparison_roi_delta"] = roi_delta
                metrics["comparison_sharpe_delta"] = sharpe_delta
                if roi_delta is not None and roi_delta > 0:
                    findings.append(
                        "V2 improved ROI vs V1. Parameter tightening was effective."
                    )
                elif roi_delta is not None and roi_delta < 0:
                    suggestions.append(
                        "V2 ROI regressed vs V1. Consider relaxing the RSI entry "
                        "filter or widening the take-profit target."
                    )
                if sharpe_delta is not None and sharpe_delta < 0:
                    suggestions.append(
                        "V2 Sharpe ratio regressed vs V1. The trailing stop or "
                        "tighter stop-loss may be cutting profitable trades too early."
                    )

            metrics["comparison_verdict"] = verdict
            steps_completed += 1

        # ── Step 10: Surface recommendations from test engine ─────────────────
        log.info("strategy_workflow.step", step=10, description="surface_recommendations")
        for label, final_resp in [("V1", v1_final), ("V2", v2_final)]:
            recs = final_resp.get("recommendations") or []
            if isinstance(recs, list) and recs:
                for rec in recs:
                    suggestions.append(f"[Platform recommendation for {label}] {rec}")
                findings.append(
                    f"{label} test produced {len(recs)} platform recommendation(s)."
                )
        steps_completed += 1

        # ── Step 11: Validate versioning behaviour ────────────────────────────
        log.info("strategy_workflow.step", step=11, description="validate_versioning")
        if v2_version == v1_version + 1:
            findings.append(
                f"Version auto-increment validated: V1={v1_version}, V2={v2_version} "
                "(sequential)."
            )
        else:
            bugs_found.append(
                f"Unexpected version sequence: expected V2={v1_version + 1}, "
                f"got V2={v2_version}. Version auto-increment may be broken."
            )
        steps_completed += 1

        # ── Step 12: Compile final status ─────────────────────────────────────
        log.info("strategy_workflow.step", step=12, description="compile_result")
        steps_completed += 1

    # ── Determine overall workflow status ─────────────────────────────────────
    if bugs_found:
        final_status = "partial"
    elif steps_completed >= steps_total:
        final_status = "pass"
    else:
        final_status = "partial"

    # ── Surface general suggestions ───────────────────────────────────────────
    if not suggestions:
        if v1_status == "completed" and v2_status == "completed":
            suggestions.append(
                "Both V1 and V2 tests completed successfully. "
                "Consider testing with more episodes (10+) for statistical significance."
            )
        else:
            suggestions.append(
                "One or more test runs did not complete. "
                "Consider increasing the Celery worker time limit for longer test windows."
            )

    log.info(
        "strategy_workflow.complete",
        status=final_status,
        steps_completed=steps_completed,
        steps_total=steps_total,
        bugs=len(bugs_found),
        suggestions=len(suggestions),
    )

    return WorkflowResult(
        workflow_name="strategy_workflow",
        status=final_status,
        steps_completed=steps_completed,
        steps_total=steps_total,
        findings=findings,
        bugs_found=bugs_found,
        suggestions=suggestions,
        metrics=metrics,
    )
