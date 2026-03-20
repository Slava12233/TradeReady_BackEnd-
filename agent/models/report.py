"""Report output models for the TradeReady Platform Testing Agent."""

from pydantic import BaseModel, ConfigDict, Field


class WorkflowResult(BaseModel):
    """Result of a single test workflow execution.

    Each workflow (smoke test, trading, backtest, strategy) produces one
    ``WorkflowResult`` instance that summarises what happened, what was
    discovered, and any issues found.  Multiple ``WorkflowResult`` objects
    are collected into a :class:`PlatformValidationReport` at the end of a
    full test session.

    Attributes:
        workflow_name: Human-readable identifier for the workflow that ran
            (e.g. ``"smoke_test"``, ``"trading_workflow"``).
        status: Overall outcome of the workflow: ``"pass"`` (all steps
            completed successfully), ``"fail"`` (a critical step failed),
            or ``"partial"`` (some steps completed but others were skipped
            or failed non-critically).
        steps_completed: Number of individual steps that finished
            successfully.
        steps_total: Total number of steps defined for this workflow.
            ``steps_completed / steps_total`` gives a completion ratio.
        findings: Observations about platform behaviour gathered during the
            workflow run.  These are informational — not necessarily errors.
        bugs_found: Confirmed platform bugs or unexpected error responses
            encountered during the run.  Each entry should include enough
            context to reproduce the issue (endpoint, payload, error message).
        suggestions: Platform improvement ideas identified during the run.
            These are constructive proposals, not bug reports.
        metrics: Arbitrary key-value performance data collected during the
            workflow (e.g. response times, trade PnL, Sharpe ratio).  Values
            must be JSON-serialisable.

    Example::

        result = WorkflowResult(
            workflow_name="backtest_workflow",
            status="pass",
            steps_completed=8,
            steps_total=8,
            findings=["Backtest step endpoint averaged 45 ms"],
            bugs_found=[],
            suggestions=["Expose Sortino ratio in /results response"],
            metrics={"sharpe": 1.2, "total_trades": 42},
        )
    """

    model_config = ConfigDict(frozen=True)

    workflow_name: str = Field(..., description="Identifier for the workflow that ran.")
    status: str = Field(
        ...,
        description="Overall outcome: 'pass', 'fail', or 'partial'.",
        pattern=r"^(pass|fail|partial)$",
    )
    steps_completed: int = Field(..., ge=0, description="Steps that finished successfully.")
    steps_total: int = Field(..., ge=0, description="Total steps defined for this workflow.")
    findings: list[str] = Field(
        default_factory=list,
        description="Informational observations about platform behaviour.",
    )
    bugs_found: list[str] = Field(
        default_factory=list,
        description="Confirmed bugs or unexpected errors encountered.",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="Platform improvement ideas identified during the run.",
    )
    metrics: dict = Field(
        default_factory=dict,
        description="Arbitrary JSON-serialisable performance data collected.",
    )


class PlatformValidationReport(BaseModel):
    """Complete validation report from a full platform test session.

    Aggregates the results of every workflow that ran during a single agent
    session into a top-level health verdict and narrative summary.  This is
    the primary ``output_type`` used at the end of ``agent.main all`` runs
    and is serialised to disk under ``agent/reports/``.

    Attributes:
        session_id: Unique identifier for this test session.  Typically a
            UUID generated at session start so reports can be correlated with
            logs.
        model_used: OpenRouter model string that was active for this session
            (e.g. ``"openrouter:anthropic/claude-sonnet-4-5"``).  Useful for
            comparing results across model runs.
        workflows_run: Ordered list of :class:`WorkflowResult` objects, one
            per workflow executed during the session.
        platform_health: Top-level health verdict derived from the workflow
            results: ``"healthy"`` (all workflows passed), ``"degraded"``
            (some failures but core functions work), or ``"broken"`` (critical
            failures that prevent normal operation).
        summary: Human-readable narrative summarising the session outcome,
            key findings, bugs, and recommendations.

    Example::

        report = PlatformValidationReport(
            session_id="sess_20260319_001",
            model_used="openrouter:anthropic/claude-sonnet-4-5",
            workflows_run=[smoke_result, trade_result, backtest_result],
            platform_health="healthy",
            summary="All 3 workflows passed. Platform responding normally. "
                    "One suggestion: expose Sortino in backtest results.",
        )
    """

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(..., description="Unique identifier for this test session.")
    model_used: str = Field(
        ...,
        description="OpenRouter model string active during the session.",
    )
    workflows_run: list[WorkflowResult] = Field(
        default_factory=list,
        description="Ordered results of each workflow executed.",
    )
    platform_health: str = Field(
        ...,
        description="Top-level verdict: 'healthy', 'degraded', or 'broken'.",
        pattern=r"^(healthy|degraded|broken)$",
    )
    summary: str = Field(
        ...,
        description="Human-readable narrative of the session outcome.",
    )
