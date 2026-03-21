"""CLI entry point for the TradeReady Platform Testing Agent.

Parses command-line arguments, configures structlog, dispatches to one or
more workflow runners, persists JSON reports to disk, and exits with an
appropriate code.

Usage::

    python -m agent.main smoke
    python -m agent.main trade --model openrouter:anthropic/claude-opus-4-5
    python -m agent.main all --output-dir /tmp/reports
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path

import structlog

from agent.config import AgentConfig
from agent.logging import configure_agent_logging
from agent.models.report import PlatformValidationReport, WorkflowResult
from agent.workflows import (
    run_backtest_workflow,
    run_smoke_test,
    run_strategy_workflow,
    run_trading_workflow,
)

# ── Workflow registry ──────────────────────────────────────────────────────────

WORKFLOWS: dict[str, Callable[[AgentConfig], Coroutine[None, None, WorkflowResult]]] = {
    "smoke": run_smoke_test,
    "trade": run_trading_workflow,
    "backtest": run_backtest_workflow,
    "strategy": run_strategy_workflow,
}

# Ordered sequence used when running all workflows in one session.
_ALL_ORDER: list[str] = ["smoke", "trade", "backtest", "strategy"]

# ── Helpers ────────────────────────────────────────────────────────────────────

log = structlog.get_logger(__name__)


def _timestamp_slug() -> str:
    """Return a filesystem-safe UTC timestamp string.

    Returns:
        Timestamp in the form ``YYYYMMDD_HHMMSS`` (UTC), e.g.
        ``"20260320_143022"``.
    """
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def _save_result(result: WorkflowResult, output_dir: Path) -> Path:
    """Serialise a :class:`~agent.models.report.WorkflowResult` to disk.

    The file name follows the pattern ``{workflow_name}-{timestamp}.json``.
    The output directory is created (including all parents) if it does not
    already exist.

    Args:
        result: The workflow result to persist.
        output_dir: Directory in which the file will be written.

    Returns:
        The resolved :class:`~pathlib.Path` of the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{result.workflow_name}-{_timestamp_slug()}.json"
    report_path = output_dir / filename
    report_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    log.info("report_saved", path=str(report_path), workflow=result.workflow_name)
    return report_path


def _save_validation_report(report: PlatformValidationReport, output_dir: Path) -> Path:
    """Serialise a :class:`~agent.models.report.PlatformValidationReport` to disk.

    The file name follows the pattern ``platform-validation-{timestamp}.json``.
    The output directory is created (including all parents) if it does not
    already exist.

    Args:
        report: The full validation report to persist.
        output_dir: Directory in which the file will be written.

    Returns:
        The resolved :class:`~pathlib.Path` of the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"platform-validation-{_timestamp_slug()}.json"
    report_path = output_dir / filename
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    log.info("validation_report_saved", path=str(report_path))
    return report_path


def _derive_platform_health(results: list[WorkflowResult]) -> str:
    """Derive a platform health verdict from a collection of workflow results.

    Rules (in priority order):

    - Any workflow with ``status="fail"`` → ``"broken"``
    - Any workflow with ``status="partial"`` → ``"degraded"``
    - All workflows with ``status="pass"`` → ``"healthy"``

    Args:
        results: Non-empty list of completed :class:`~agent.models.report.WorkflowResult`
            objects.

    Returns:
        One of ``"healthy"``, ``"degraded"``, or ``"broken"``.
    """
    statuses = {r.status for r in results}
    if "fail" in statuses:
        return "broken"
    if "partial" in statuses:
        return "degraded"
    return "healthy"


def _build_summary(results: list[WorkflowResult]) -> str:
    """Compose a human-readable summary from a list of workflow results.

    Args:
        results: List of completed workflow results to summarise.

    Returns:
        A multiline string suitable for the ``summary`` field of a
        :class:`~agent.models.report.PlatformValidationReport`.
    """
    lines: list[str] = []
    total_bugs = sum(len(r.bugs_found) for r in results)
    total_suggestions = sum(len(r.suggestions) for r in results)

    lines.append(
        f"Ran {len(results)} workflow(s). "
        f"Total bugs found: {total_bugs}. "
        f"Total suggestions: {total_suggestions}."
    )

    for result in results:
        completion = (
            f"{result.steps_completed}/{result.steps_total} steps"
        )
        lines.append(
            f"  [{result.status.upper()}] {result.workflow_name}: {completion}"
        )
        for bug in result.bugs_found:
            lines.append(f"    BUG: {bug}")
        for suggestion in result.suggestions:
            lines.append(f"    SUGGESTION: {suggestion}")

    return "\n".join(lines)


def _any_failure(results: list[WorkflowResult]) -> bool:
    """Return True if any result in the list has status ``"fail"``.

    Args:
        results: List of completed :class:`~agent.models.report.WorkflowResult`
            objects to inspect.

    Returns:
        ``True`` if at least one result has ``status="fail"``; ``False``
        otherwise.
    """
    return any(r.status == "fail" for r in results)


# ── Argument parsing ───────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser.

    Returns:
        Configured :class:`~argparse.ArgumentParser` with all supported
        arguments registered.
    """
    parser = argparse.ArgumentParser(
        prog="python -m agent.main",
        description=(
            "TradeReady Platform Testing Agent — exercise the AiTradingAgent "
            "platform end-to-end with an autonomous AI agent."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Workflow descriptions:\n"
            "  smoke     10-step connectivity validation (no LLM required)\n"
            "  trade     Full trading lifecycle: analyse → signal → execute → close\n"
            "  backtest  7-day MA-crossover backtest with LLM analysis\n"
            "  strategy  Create → test → improve → compare strategy versions\n"
            "  all       Run all four workflows in sequence\n"
        ),
    )

    parser.add_argument(
        "workflow",
        choices=list(WORKFLOWS.keys()) + ["all"],
        help="Workflow to run.  Use 'all' to run smoke → trade → backtest → strategy.",
    )

    parser.add_argument(
        "--model",
        metavar="MODEL_ID",
        default=None,
        help=(
            "Override the LLM model at runtime "
            "(e.g. 'openrouter:anthropic/claude-opus-4-5').  "
            "Defaults to the value of AGENT_MODEL in agent/.env."
        ),
    )

    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help=(
            "Directory to write JSON report files.  "
            "Defaults to agent/reports/ relative to the agent package root."
        ),
    )

    parser.add_argument(
        "--log-level",
        metavar="LEVEL",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=(
            "Minimum log level to emit (case-insensitive).  "
            "Defaults to INFO."
        ),
    )

    return parser


# ── Core async runner ──────────────────────────────────────────────────────────


async def _run_single(
    workflow_name: str,
    config: AgentConfig,
    output_dir: Path,
) -> WorkflowResult:
    """Run a single named workflow and save the result to disk.

    Args:
        workflow_name: Key in :data:`WORKFLOWS` identifying the workflow to run.
        config: Resolved agent configuration.
        output_dir: Directory in which to save the result JSON.

    Returns:
        The :class:`~agent.models.report.WorkflowResult` produced by the
        workflow.
    """
    fn = WORKFLOWS[workflow_name]
    log.info("workflow_dispatch", workflow=workflow_name, model=config.agent_model)

    result = await fn(config)

    _save_result(result, output_dir)

    log.info(
        "workflow_finished",
        workflow=workflow_name,
        status=result.status,
        steps_completed=result.steps_completed,
        steps_total=result.steps_total,
        bugs=len(result.bugs_found),
    )

    return result


async def _run_all(config: AgentConfig, output_dir: Path) -> list[WorkflowResult]:
    """Run all workflows in the canonical sequence and save individual results.

    The sequence is: smoke → trade → backtest → strategy.  Each workflow
    runs to completion before the next starts; a failure in one workflow does
    not prevent subsequent workflows from running.

    Args:
        config: Resolved agent configuration.
        output_dir: Directory in which to save individual result JSON files.

    Returns:
        Ordered list of :class:`~agent.models.report.WorkflowResult` objects,
        one per workflow.
    """
    results: list[WorkflowResult] = []
    for workflow_name in _ALL_ORDER:
        result = await _run_single(workflow_name, config, output_dir)
        results.append(result)
    return results


# ── Main entrypoint ────────────────────────────────────────────────────────────


async def main() -> None:
    """Parse CLI arguments, configure logging, run workflows, and exit.

    Exit codes:

    - ``0`` — all workflows passed or reached ``"partial"`` status
    - ``1`` — configuration error (missing .env or API key), platform
              unreachable, or at least one workflow reached ``"fail"`` status
    """
    parser = _build_parser()
    args = parser.parse_args()

    log_level: str = args.log_level.upper()
    configure_agent_logging(log_level)

    # ── Resolve output directory ───────────────────────────────────────────────
    if args.output_dir is not None:
        output_dir = Path(args.output_dir).resolve()
    else:
        # Default: <repo_root>/agent/reports/
        output_dir = Path(__file__).parent / "reports"

    log.info(
        "agent_start",
        workflow=args.workflow,
        output_dir=str(output_dir),
        model_override=args.model,
    )

    # ── Load configuration ─────────────────────────────────────────────────────
    try:
        config = AgentConfig()
    except Exception as exc:  # noqa: BLE001
        # pydantic-settings raises ValidationError when required fields are absent
        print(  # noqa: T201 — user-facing friendly message, not a log line
            f"ERROR: Failed to load agent configuration.\n"
            f"  Make sure agent/.env exists and contains OPENROUTER_API_KEY.\n"
            f"  Details: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    if not config.openrouter_api_key:
        print(  # noqa: T201
            "ERROR: OPENROUTER_API_KEY is not set in agent/.env.\n"
            "  Obtain a key from https://openrouter.ai and add it to agent/.env.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Pydantic AI's OpenRouterProvider reads the API key from the OS environment,
    # but AgentConfig loads it from agent/.env via pydantic-settings.  Bridge the
    # gap so the provider can find the key at Agent() instantiation time.
    if not os.environ.get("OPENROUTER_API_KEY"):
        os.environ["OPENROUTER_API_KEY"] = config.openrouter_api_key

    # ── Apply runtime overrides ────────────────────────────────────────────────
    if args.model is not None:
        # AgentConfig is an immutable Pydantic model; use model_copy to override.
        config = config.model_copy(update={"agent_model": args.model})
        log.info("model_override_applied", model=args.model)

    # ── Dispatch ───────────────────────────────────────────────────────────────
    try:
        if args.workflow == "all":
            results = await _run_all(config, output_dir)

            session_id = f"sess_{_timestamp_slug()}_{uuid.uuid4().hex[:8]}"
            platform_health = _derive_platform_health(results)
            summary = _build_summary(results)

            report = PlatformValidationReport(
                session_id=session_id,
                model_used=config.agent_model,
                workflows_run=results,
                platform_health=platform_health,
                summary=summary,
            )
            _save_validation_report(report, output_dir)

            log.info(
                "session_complete",
                session_id=session_id,
                platform_health=platform_health,
                workflows=len(results),
                total_bugs=sum(len(r.bugs_found) for r in results),
            )

            if _any_failure(results):
                sys.exit(1)

        else:
            result = await _run_single(args.workflow, config, output_dir)
            if result.status == "fail":
                sys.exit(1)

    except (ConnectionError, OSError) as exc:
        print(  # noqa: T201
            f"ERROR: Could not connect to the platform at {config.platform_base_url}.\n"
            f"  Make sure the backend is running and PLATFORM_BASE_URL is correct.\n"
            f"  Details: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        log.info("interrupted_by_user")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
