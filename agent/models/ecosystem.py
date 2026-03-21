"""Pydantic v2 output models for the agent ecosystem.

Defines all structured data contracts used across agent tools, trading workflows,
permission enforcement, strategy management, and health monitoring.  All models
use ``ConfigDict(frozen=True)`` for immutability and safety when passed as
``output_type`` values to Pydantic AI agents.

Monetary and price fields always use ``Decimal`` — never ``float`` — to avoid
floating-point precision loss in financial calculations.

Model groups
------------
- **Trading decisions**: TradeDecision, TradeReflection, PortfolioReview
- **Opportunity scanning**: Opportunity
- **Journal and feedback**: JournalEntry, FeedbackEntry
- **Permission and budget**: BudgetCheckResult, BudgetStatus, EnforcementResult, AuditEntry
- **Strategy management**: DegradationAlert, Adjustment, StrategyPerformance, StrategyComparison, ABTestResult
- **Trading loop runtime**: TradingCycleResult, ExecutionResult, PositionAction
- **Health monitoring**: HealthStatus
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Trading decisions
# ---------------------------------------------------------------------------


class TradeDecision(BaseModel):
    """A fully-reasoned trade decision produced by the agent's LLM core.

    Captures the symbol, direction, size, reasoning chain, and the signals
    that drove the decision.  Used as the input to :class:`TradeExecutor`
    and is recorded in ``agent_decisions`` for audit and replay.

    Attributes:
        symbol: Trading pair the decision targets (e.g. ``"BTCUSDT"``).
        action: Direction of the trade: ``"buy"``, ``"sell"``, or ``"hold"``.
        quantity_pct: Fraction of available equity to allocate.  Must be
            within ``[0.001, 0.10]`` to respect the agent's 10 % per-trade
            risk cap.
        confidence: Agent's confidence in the decision on a ``[0.0, 1.0]``
            scale.  Decisions with confidence below 0.5 are typically skipped
            by the trading loop.
        reasoning: Full chain-of-thought explanation used by the LLM to reach
            the decision.  Saved verbatim for human review.
        signals: Compact representation of the strategy signals that fed into
            the decision (e.g. ``{"ensemble": 0.72, "regime": "trending"}``).
        risk_notes: Adverse scenarios or tail risks that could invalidate the
            decision.  Required to force the agent to articulate downside.
        strategy_weights: Per-strategy contribution weights at decision time
            (e.g. ``{"rl": 0.3, "evolutionary": 0.2, "regime": 0.5}``).
            Defaults to empty dict when weight attribution is unavailable.

    Example::

        decision = TradeDecision(
            symbol="ETHUSDT",
            action="buy",
            quantity_pct=Decimal("0.04"),
            confidence=0.78,
            reasoning="Regime classifier indicates trending; ensemble score 0.72.",
            signals={"ensemble_score": 0.72, "regime": "trending_up"},
            risk_notes="Upcoming Fed statement could reverse momentum.",
            strategy_weights={"rl": 0.3, "evolutionary": 0.2, "regime": 0.5},
        )
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Trading pair symbol, e.g. 'BTCUSDT'.")
    action: str = Field(
        ...,
        description="Trade direction: 'buy', 'sell', or 'hold'.",
        pattern=r"^(buy|sell|hold)$",
    )
    quantity_pct: Decimal = Field(
        ...,
        ge=Decimal("0.001"),
        le=Decimal("0.10"),
        description="Fraction of available equity to allocate (0.1 %–10 %).",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Agent confidence in the decision, from 0.0 (none) to 1.0 (certain).",
    )
    reasoning: str = Field(
        ...,
        description="Full LLM reasoning chain that produced the decision.",
    )
    signals: dict = Field(
        default_factory=dict,
        description="Strategy signal values that fed into the decision.",
    )
    risk_notes: str = Field(
        ...,
        description="Adverse scenarios or tail risks that could invalidate the decision.",
    )
    strategy_weights: dict = Field(
        default_factory=dict,
        description="Per-strategy contribution weights at decision time.",
    )


class TradeReflection(BaseModel):
    """Post-trade analysis of a completed trade produced by the agent.

    Generated after a trade round-trip (entry + exit) to extract learnings
    about timing, execution quality, and what could be improved.  Stored in
    ``agent_journal`` and used to update the memory system.

    Attributes:
        trade_id: Platform-assigned trade identifier.
        symbol: Trading pair that was traded.
        entry_quality: Subjective rating of the entry timing as ``"good"``,
            ``"neutral"``, or ``"poor"``.
        exit_quality: Subjective rating of the exit timing as ``"good"``,
            ``"neutral"``, or ``"poor"``.
        pnl: Realised profit/loss for the trade stored as ``Decimal`` for
            precision.
        max_adverse_excursion: Largest unrealised loss during the trade
            (expressed as a positive ``Decimal`` representing the drawdown
            magnitude).
        learnings: Ordered list of concrete lessons extracted from this trade
            (e.g. ``["Entry was premature — wait for SMA confirmation"]``).
        would_take_again: Whether the agent would take this trade given the
            same conditions.  Helps calibrate confidence thresholds.
        improvement_notes: Free-form notes on what could be done differently
            next time.

    Example::

        reflection = TradeReflection(
            trade_id="trd_abc123",
            symbol="BTCUSDT",
            entry_quality="good",
            exit_quality="poor",
            pnl=Decimal("42.50"),
            max_adverse_excursion=Decimal("18.00"),
            learnings=["Exit too early; let winners run longer"],
            would_take_again=True,
            improvement_notes="Consider trailing stop instead of fixed TP.",
        )
    """

    model_config = ConfigDict(frozen=True)

    trade_id: str = Field(..., description="Platform-assigned trade identifier.")
    symbol: str = Field(..., description="Trading pair that was traded.")
    entry_quality: str = Field(
        ...,
        description="Entry timing quality: 'good', 'neutral', or 'poor'.",
        pattern=r"^(good|neutral|poor)$",
    )
    exit_quality: str = Field(
        ...,
        description="Exit timing quality: 'good', 'neutral', or 'poor'.",
        pattern=r"^(good|neutral|poor)$",
    )
    pnl: Decimal = Field(..., description="Realised profit/loss for this trade.")
    max_adverse_excursion: Decimal = Field(
        ...,
        ge=Decimal("0"),
        description="Largest unrealised loss during the trade (positive value).",
    )
    learnings: list[str] = Field(
        default_factory=list,
        description="Concrete lessons extracted from this trade.",
    )
    would_take_again: bool = Field(
        ...,
        description="Whether the agent would repeat this trade under the same conditions.",
    )
    improvement_notes: str = Field(
        default="",
        description="Free-form notes on what could be done differently.",
    )


class PortfolioReview(BaseModel):
    """Portfolio health assessment produced by the agent's review tool.

    Summarises concentration risk, unrealised P&L, budget headroom, and
    actionable recommendations.  Used as the output of ``review_portfolio``
    tool and stored in ``agent_journal``.

    Attributes:
        total_value: Total portfolio value in USDT at review time.
        unrealized_pnl: Current unrealised profit/loss across all open
            positions.  Can be negative.
        largest_position_pct: Fraction of portfolio held in the single
            largest position (concentration risk indicator).
        num_open_positions: Number of currently open positions.
        budget_utilization_pct: Fraction of the daily trade budget consumed
            so far today, in ``[0.0, 1.0]``.
        health_score: Composite health score from 0.0 (critical) to 1.0
            (optimal).  Computed from concentration, drawdown, and budget
            metrics.
        recommendations: Ordered list of concrete actions to improve
            portfolio health (e.g. ``"Reduce BTC exposure below 30 %"``).
        risk_flags: Active risk warnings that require attention
            (e.g. ``"High concentration in single asset"``).

    Example::

        review = PortfolioReview(
            total_value=Decimal("10342.88"),
            unrealized_pnl=Decimal("342.88"),
            largest_position_pct=0.38,
            num_open_positions=4,
            budget_utilization_pct=0.45,
            health_score=0.72,
            recommendations=["Reduce BTC to below 30 % of portfolio"],
            risk_flags=["High concentration in BTCUSDT (38 %)"],
        )
    """

    model_config = ConfigDict(frozen=True)

    total_value: Decimal = Field(
        ...,
        description="Total portfolio value in USDT at review time.",
    )
    unrealized_pnl: Decimal = Field(
        ...,
        description="Aggregate unrealised profit/loss across open positions.",
    )
    largest_position_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of portfolio in the single largest position.",
    )
    num_open_positions: int = Field(
        ...,
        ge=0,
        description="Number of currently open positions.",
    )
    budget_utilization_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of the daily trade budget consumed today.",
    )
    health_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Composite health score: 0.0 (critical) to 1.0 (optimal).",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Concrete actions to improve portfolio health.",
    )
    risk_flags: list[str] = Field(
        default_factory=list,
        description="Active risk warnings requiring attention.",
    )


# ---------------------------------------------------------------------------
# Opportunity scanning
# ---------------------------------------------------------------------------


class Opportunity(BaseModel):
    """A detected trading opportunity with entry and exit price suggestions.

    Produced by the ``scan_opportunities`` tool after applying criteria
    filters (trend, volume, proximity to support) to current market data.
    Opportunities are ranked by signal strength before being returned.

    Attributes:
        symbol: Trading pair with the detected opportunity.
        direction: Expected move direction: ``"long"`` or ``"short"``.
        signal_strength: Normalised signal strength in ``[0.0, 1.0]``.
            Higher values indicate stronger, more reliable setups.
        entry_price: Suggested entry price as a ``Decimal``.
        stop_loss_price: Suggested stop-loss level; defines the maximum
            acceptable loss per share/unit.
        take_profit_price: Suggested take-profit target.
        risk_reward_ratio: Take-profit distance divided by stop-loss distance.
            A ratio below 1.5 is generally considered too tight.
        criteria_matched: List of filter criteria that this opportunity
            satisfied (e.g. ``["trending_up", "near_support", "high_volume"]``).
        notes: Additional context about why this is considered an opportunity.

    Example::

        opp = Opportunity(
            symbol="SOLUSDT",
            direction="long",
            signal_strength=0.81,
            entry_price=Decimal("145.50"),
            stop_loss_price=Decimal("140.00"),
            take_profit_price=Decimal("160.00"),
            risk_reward_ratio=2.64,
            criteria_matched=["trending_up", "near_support"],
            notes="Bounced off 200-SMA with strong volume confirmation.",
        )
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Trading pair with the detected opportunity.")
    direction: str = Field(
        ...,
        description="Expected move direction: 'long' or 'short'.",
        pattern=r"^(long|short)$",
    )
    signal_strength: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Normalised signal strength; higher is more reliable.",
    )
    entry_price: Decimal = Field(..., description="Suggested entry price.")
    stop_loss_price: Decimal = Field(
        ...,
        description="Suggested stop-loss level defining maximum acceptable loss.",
    )
    take_profit_price: Decimal = Field(
        ...,
        description="Suggested take-profit target price.",
    )
    risk_reward_ratio: float = Field(
        ...,
        gt=0.0,
        description="Take-profit distance / stop-loss distance.",
    )
    criteria_matched: list[str] = Field(
        default_factory=list,
        description="Filter criteria this opportunity satisfied.",
    )
    notes: str = Field(
        default="",
        description="Additional context about why this is an opportunity.",
    )


# ---------------------------------------------------------------------------
# Journal and feedback
# ---------------------------------------------------------------------------


class JournalEntry(BaseModel):
    """An agent journal entry capturing a trading insight, reflection, or summary.

    Written to ``agent_journal`` by the ``journal_entry`` tool and the
    :class:`~agent.trading.journal.TradingJournal` reflection engine.

    Attributes:
        entry_id: Unique identifier for the entry (assigned by the DB layer).
            Empty string before persistence.
        entry_type: Category of the entry: ``"reflection"``, ``"daily_summary"``,
            ``"weekly_review"``, ``"observation"``, or ``"ab_test"``.
        content: Full text content of the journal entry.
        market_context: Snapshot of market conditions at the time of writing
            (e.g. top prices, active regime, portfolio state).  Stored as a
            dict for flexibility.
        tags: Auto-generated topic tags extracted from the content
            (e.g. ``["risk", "entry_timing", "momentum"]``).
        created_at: UTC timestamp when the entry was created.

    Example::

        entry = JournalEntry(
            entry_id="",
            entry_type="reflection",
            content="Today's BTCUSDT long was closed early; should have used trailing stop.",
            market_context={"btc_price": "67800.00", "regime": "trending"},
            tags=["exit_timing", "stop_loss"],
            created_at=datetime.utcnow(),
        )
    """

    model_config = ConfigDict(frozen=True)

    entry_id: str = Field(
        default="",
        description="DB-assigned entry identifier; empty before persistence.",
    )
    entry_type: str = Field(
        ...,
        description=(
            "Entry category: 'reflection', 'daily_summary', 'weekly_review', "
            "'observation', or 'ab_test'."
        ),
        pattern=r"^(reflection|daily_summary|weekly_review|observation|ab_test)$",
    )
    content: str = Field(..., description="Full text content of the journal entry.")
    market_context: dict = Field(
        default_factory=dict,
        description="Market conditions snapshot at the time of writing.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Topic tags auto-extracted from the content.",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the entry was created.",
    )


class FeedbackEntry(BaseModel):
    """A platform feedback item or feature request submitted by the agent.

    Saved to ``agent_feedback`` by the ``request_platform_feature`` tool.
    Duplicate detection is performed before persistence to avoid repeated
    requests for the same feature.

    Attributes:
        feedback_id: DB-assigned identifier; empty before persistence.
        description: Full description of the feedback or feature request.
        category: Broad category: ``"feature_request"``, ``"bug_report"``,
            ``"performance"``, or ``"ux"``.
        priority: Perceived urgency: ``"low"``, ``"medium"``, or ``"high"``.
        is_duplicate: Whether a similar existing request was detected.
        duplicate_of: ID of the existing feedback entry this duplicates,
            if ``is_duplicate`` is ``True``.
        created_at: UTC timestamp when the entry was created.

    Example::

        fb = FeedbackEntry(
            feedback_id="",
            description="Expose Sortino ratio in backtest /results response.",
            category="feature_request",
            priority="medium",
            is_duplicate=False,
            duplicate_of=None,
            created_at=datetime.utcnow(),
        )
    """

    model_config = ConfigDict(frozen=True)

    feedback_id: str = Field(
        default="",
        description="DB-assigned identifier; empty before persistence.",
    )
    description: str = Field(
        ...,
        description="Full description of the feedback or feature request.",
    )
    category: str = Field(
        ...,
        description="Category: 'feature_request', 'bug_report', 'performance', or 'ux'.",
        pattern=r"^(feature_request|bug_report|performance|ux)$",
    )
    priority: str = Field(
        ...,
        description="Perceived urgency: 'low', 'medium', or 'high'.",
        pattern=r"^(low|medium|high)$",
    )
    is_duplicate: bool = Field(
        default=False,
        description="True if a similar request already exists.",
    )
    duplicate_of: str | None = Field(
        default=None,
        description="ID of the existing entry this duplicates, if applicable.",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the feedback was submitted.",
    )


# ---------------------------------------------------------------------------
# Permission and budget
# ---------------------------------------------------------------------------


class BudgetCheckResult(BaseModel):
    """Response from the budget enforcement system for a proposed trade.

    Produced by :class:`~agent.permissions.budget.BudgetManager.check_budget`
    and consumed by the permission enforcer and trading loop before any trade
    is placed.

    Attributes:
        allowed: Whether the proposed trade is within budget limits.
        reason: Human-readable explanation of the decision.  Non-empty when
            ``allowed`` is ``False`` so the agent can understand the denial.
        remaining_trades: Number of trades still allowed today before the
            daily limit is reached.
        remaining_exposure: Maximum additional trade value (in USDT) that can
            be opened before the exposure cap is hit.
        remaining_loss_budget: Additional loss (in USDT) that can be absorbed
            today before the circuit breaker fires.

    Example::

        result = BudgetCheckResult(
            allowed=True,
            reason="",
            remaining_trades=7,
            remaining_exposure=Decimal("1200.00"),
            remaining_loss_budget=Decimal("450.00"),
        )
    """

    model_config = ConfigDict(frozen=True)

    allowed: bool = Field(..., description="Whether the proposed trade is permitted.")
    reason: str = Field(
        default="",
        description="Why the trade was denied (empty when allowed is True).",
    )
    remaining_trades: int = Field(
        ...,
        ge=0,
        description="Trades still allowed today before the daily limit is reached.",
    )
    remaining_exposure: Decimal = Field(
        ...,
        description="Additional trade value (USDT) allowed before the exposure cap.",
    )
    remaining_loss_budget: Decimal = Field(
        ...,
        description="Additional loss (USDT) absorbable today before circuit breaker fires.",
    )


class BudgetStatus(BaseModel):
    """Current budget utilisation for a single agent.

    Returned by :class:`~agent.permissions.budget.BudgetManager.get_budget_status`
    and used for monitoring dashboards and the portfolio review tool.

    Attributes:
        agent_id: The agent whose budget is being reported.
        trades_today: Number of trades executed today.
        trades_limit: Maximum trades allowed per day.
        trades_utilization_pct: ``trades_today / trades_limit`` as a fraction
            in ``[0.0, 1.0]``.
        exposure_used: Total open position value in USDT.
        exposure_limit: Maximum allowed open position value in USDT.
        exposure_utilization_pct: ``exposure_used / exposure_limit`` as a
            fraction in ``[0.0, 1.0]``.
        loss_today: Realised losses today in USDT (positive value).
        loss_limit: Maximum realised loss allowed today in USDT.
        loss_utilization_pct: ``loss_today / loss_limit`` as a fraction in
            ``[0.0, 1.0]``.
        reset_at: UTC datetime when daily counters will next reset.

    Example::

        status = BudgetStatus(
            agent_id="agent_xyz",
            trades_today=3,
            trades_limit=10,
            trades_utilization_pct=0.30,
            exposure_used=Decimal("2400.00"),
            exposure_limit=Decimal("5000.00"),
            exposure_utilization_pct=0.48,
            loss_today=Decimal("55.00"),
            loss_limit=Decimal("500.00"),
            loss_utilization_pct=0.11,
            reset_at=datetime(2026, 3, 21, 0, 0, 0),
        )
    """

    model_config = ConfigDict(frozen=True)

    agent_id: str = Field(..., description="Agent whose budget is being reported.")
    trades_today: int = Field(
        ...,
        ge=0,
        description="Number of trades executed today.",
    )
    trades_limit: int = Field(
        ...,
        ge=0,
        description="Maximum trades allowed per day.",
    )
    trades_utilization_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of the daily trade count limit consumed.",
    )
    exposure_used: Decimal = Field(
        ...,
        description="Total open position value in USDT.",
    )
    exposure_limit: Decimal = Field(
        ...,
        description="Maximum allowed open position value in USDT.",
    )
    exposure_utilization_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of the exposure limit currently used.",
    )
    loss_today: Decimal = Field(
        ...,
        ge=Decimal("0"),
        description="Realised losses today in USDT (positive value).",
    )
    loss_limit: Decimal = Field(
        ...,
        description="Maximum realised loss allowed today in USDT.",
    )
    loss_utilization_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of the daily loss budget consumed.",
    )
    reset_at: datetime = Field(
        ...,
        description="UTC datetime when daily counters will next reset.",
    )


class EnforcementResult(BaseModel):
    """Result of a permission check performed by the enforcement middleware.

    Produced by :class:`~agent.permissions.enforcement.PermissionEnforcer.check_action`
    for every agent action before it is executed.

    Attributes:
        allowed: Whether the action is permitted.
        action: The action name that was checked (e.g. ``"trade"``,
            ``"read_portfolio"``).
        agent_id: The agent the check was performed for.
        reason: Explanation of the decision.  Always non-empty for denied
            checks so the agent can understand why it was blocked.
        capability_check_passed: Whether the role/capability check passed.
        budget_check_passed: Whether the budget check passed (``True`` for
            non-financial actions where budget is not applicable).
        checked_at: UTC timestamp of the permission check.

    Example::

        result = EnforcementResult(
            allowed=False,
            action="trade",
            agent_id="agent_xyz",
            reason="Daily trade limit of 10 reached (trades_today=10).",
            capability_check_passed=True,
            budget_check_passed=False,
            checked_at=datetime.utcnow(),
        )
    """

    model_config = ConfigDict(frozen=True)

    allowed: bool = Field(..., description="Whether the action is permitted.")
    action: str = Field(..., description="Action name that was checked.")
    agent_id: str = Field(..., description="Agent the check was performed for.")
    reason: str = Field(
        default="",
        description="Explanation of the decision; always non-empty when denied.",
    )
    capability_check_passed: bool = Field(
        ...,
        description="Whether the role/capability check passed.",
    )
    budget_check_passed: bool = Field(
        ...,
        description="Whether the budget check passed (True for non-financial actions).",
    )
    checked_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of the permission check.",
    )


class AuditEntry(BaseModel):
    """Immutable audit log record for a single permission check.

    Written to the permission audit log (``agent_audit_log`` or a DB-side
    batch buffer) by the enforcement layer.  Every call to ``check_action``
    or ``require_action`` produces exactly one ``AuditEntry``.

    Attributes:
        audit_id: DB-assigned audit record identifier.
        agent_id: Agent the audit record is for.
        action: Action that was checked.
        result: Outcome: ``"allow"`` or ``"deny"``.
        reason: Denial reason (empty for allowed checks).
        context: Arbitrary context dict supplied by the caller
            (e.g. ``{"symbol": "BTCUSDT", "value": "500.00"}``).
        checked_at: UTC timestamp of the check.

    Example::

        entry = AuditEntry(
            audit_id="",
            agent_id="agent_xyz",
            action="trade",
            result="allow",
            reason="",
            context={"symbol": "BTCUSDT", "value": "250.00"},
            checked_at=datetime.utcnow(),
        )
    """

    model_config = ConfigDict(frozen=True)

    audit_id: str = Field(
        default="",
        description="DB-assigned audit record identifier; empty before persistence.",
    )
    agent_id: str = Field(..., description="Agent the audit record is for.")
    action: str = Field(..., description="Action that was checked.")
    result: str = Field(
        ...,
        description="Outcome of the permission check: 'allow' or 'deny'.",
        pattern=r"^(allow|deny)$",
    )
    reason: str = Field(
        default="",
        description="Denial reason; empty for allowed checks.",
    )
    context: dict = Field(
        default_factory=dict,
        description="Caller-supplied context for the check (e.g. symbol, value).",
    )
    checked_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of the permission check.",
    )


# ---------------------------------------------------------------------------
# Strategy management
# ---------------------------------------------------------------------------


class DegradationAlert(BaseModel):
    """A strategy degradation notification indicating performance below threshold.

    Generated by :class:`~agent.trading.strategy_manager.StrategyManager.detect_degradation`
    when a monitored metric drops below its configured threshold.  Alerts
    are used by the trading loop to reduce exposure or disable a strategy.

    Attributes:
        strategy_name: Name of the strategy that has degraded.
        metric: Which metric triggered the alert: ``"sharpe"``, ``"win_rate"``,
            ``"max_drawdown"``, or ``"consecutive_losses"``.
        current_value: Current (degraded) metric value.
        threshold_value: Threshold that was breached.
        severity: Severity level: ``"warning"`` (monitor), ``"critical"``
            (reduce exposure), or ``"disable"`` (stop trading with strategy).
        recommendation: Suggested action to address the degradation.
        detected_at: UTC timestamp when the degradation was detected.

    Example::

        alert = DegradationAlert(
            strategy_name="rl_strategy",
            metric="sharpe",
            current_value=0.32,
            threshold_value=0.5,
            severity="warning",
            recommendation="Reduce allocation to rl_strategy by 50 %.",
            detected_at=datetime.utcnow(),
        )
    """

    model_config = ConfigDict(frozen=True)

    strategy_name: str = Field(
        ...,
        description="Name of the strategy that has degraded.",
    )
    metric: str = Field(
        ...,
        description="Metric that triggered the alert: 'sharpe', 'win_rate', 'max_drawdown', or 'consecutive_losses'.",
        pattern=r"^(sharpe|win_rate|max_drawdown|consecutive_losses)$",
    )
    current_value: float = Field(
        ...,
        description="Current (degraded) metric value.",
    )
    threshold_value: float = Field(
        ...,
        description="Threshold that was breached.",
    )
    severity: str = Field(
        ...,
        description="Severity: 'warning' (monitor), 'critical' (reduce), or 'disable' (stop).",
        pattern=r"^(warning|critical|disable)$",
    )
    recommendation: str = Field(
        ...,
        description="Suggested action to address the degradation.",
    )
    detected_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the degradation was detected.",
    )


class Adjustment(BaseModel):
    """A suggested adjustment to a trading strategy's parameters or behaviour.

    Produced by :class:`~agent.trading.strategy_manager.StrategyManager.suggest_adjustments`
    after analysing recent trade outcomes.  Adjustments are always
    conservative — they reduce exposure or tighten thresholds rather than
    making radical changes.

    Attributes:
        strategy_name: Name of the strategy to adjust.
        parameter: Which parameter or behaviour to change (e.g.
            ``"position_size_pct"``, ``"confidence_threshold"``).
        current_value: The parameter's current value (as a string for
            flexibility with mixed types).
        suggested_value: The recommended new value (as a string).
        rationale: Why this adjustment is recommended.
        expected_impact: Expected effect of the adjustment on the strategy's
            performance (e.g. ``"Reduce max drawdown by ~2 %"``).
        priority: Implementation urgency: ``"low"``, ``"medium"``, or
            ``"high"``.

    Example::

        adj = Adjustment(
            strategy_name="evolutionary_strategy",
            parameter="position_size_pct",
            current_value="0.05",
            suggested_value="0.03",
            rationale="Win rate dropped to 38 % over last 50 trades.",
            expected_impact="Reduce daily loss exposure by ~40 %.",
            priority="high",
        )
    """

    model_config = ConfigDict(frozen=True)

    strategy_name: str = Field(
        ...,
        description="Name of the strategy to adjust.",
    )
    parameter: str = Field(
        ...,
        description="Parameter or behaviour to change.",
    )
    current_value: str = Field(
        ...,
        description="Current parameter value as a string.",
    )
    suggested_value: str = Field(
        ...,
        description="Recommended new parameter value as a string.",
    )
    rationale: str = Field(
        ...,
        description="Why this adjustment is recommended.",
    )
    expected_impact: str = Field(
        ...,
        description="Expected effect on strategy performance.",
    )
    priority: str = Field(
        ...,
        description="Implementation urgency: 'low', 'medium', or 'high'.",
        pattern=r"^(low|medium|high)$",
    )


class StrategyPerformance(BaseModel):
    """Rolling performance statistics for a single strategy over a given period.

    Produced by :class:`~agent.trading.strategy_manager.StrategyManager.get_performance`
    and used in :class:`StrategyComparison` and degradation detection.  All
    ratio and percentage fields use ``float`` because they are dimensionless;
    monetary P&L is ``Decimal``.

    Attributes:
        strategy_name: Name of the strategy being reported.
        period: The evaluation window: ``"daily"``, ``"weekly"``, or
            ``"monthly"``.
        total_signals: Number of signals generated by the strategy in the
            period.
        trades_taken: Signals that were converted into executed trades.
        win_rate: Fraction of taken trades that were profitable.
        sharpe_ratio: Annualised Sharpe ratio over the period.
        max_drawdown: Maximum peak-to-trough equity decline as a fraction.
        total_pnl: Total realised profit/loss in the period (can be negative).
        avg_pnl_per_trade: Average realised P&L per completed trade.
        consecutive_losses: Current streak of consecutive losing trades (0 if
            the last trade was profitable).

    Example::

        perf = StrategyPerformance(
            strategy_name="ensemble_strategy",
            period="weekly",
            total_signals=42,
            trades_taken=18,
            win_rate=0.61,
            sharpe_ratio=1.34,
            max_drawdown=0.07,
            total_pnl=Decimal("384.50"),
            avg_pnl_per_trade=Decimal("21.36"),
            consecutive_losses=0,
        )
    """

    model_config = ConfigDict(frozen=True)

    strategy_name: str = Field(..., description="Name of the strategy being reported.")
    period: str = Field(
        ...,
        description="Evaluation window: 'daily', 'weekly', or 'monthly'.",
        pattern=r"^(daily|weekly|monthly)$",
    )
    total_signals: int = Field(
        ...,
        ge=0,
        description="Signals generated by the strategy in the period.",
    )
    trades_taken: int = Field(
        ...,
        ge=0,
        description="Signals converted into executed trades.",
    )
    win_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of taken trades that were profitable.",
    )
    sharpe_ratio: float = Field(
        ...,
        description="Annualised Sharpe ratio over the period.",
    )
    max_drawdown: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Maximum peak-to-trough equity decline as a fraction.",
    )
    total_pnl: Decimal = Field(
        ...,
        description="Total realised profit/loss in the period.",
    )
    avg_pnl_per_trade: Decimal = Field(
        ...,
        description="Average realised P&L per completed trade.",
    )
    consecutive_losses: int = Field(
        ...,
        ge=0,
        description="Current streak of consecutive losing trades.",
    )


class StrategyComparison(BaseModel):
    """Head-to-head comparison of all active strategies over a common period.

    Produced by :class:`~agent.trading.strategy_manager.StrategyManager.compare_strategies`.
    Includes an ordered ranking, the best and worst performers, and a summary
    recommendation for ensemble weight adjustments.

    Attributes:
        period: The evaluation window used for all strategies in this
            comparison: ``"daily"``, ``"weekly"``, or ``"monthly"``.
        strategies: Performance stats for each strategy, keyed by strategy
            name.  Values are :class:`StrategyPerformance` objects.
        ranking: Strategy names ordered from best to worst by Sharpe ratio.
        best_strategy: Name of the top-ranked strategy.
        worst_strategy: Name of the bottom-ranked strategy.
        recommendation: Free-form guidance on how to adjust ensemble weights
            or disable underperformers.
        generated_at: UTC timestamp when the comparison was generated.

    Example::

        cmp = StrategyComparison(
            period="weekly",
            strategies={
                "ensemble": StrategyPerformance(...),
                "rl": StrategyPerformance(...),
            },
            ranking=["ensemble", "rl"],
            best_strategy="ensemble",
            worst_strategy="rl",
            recommendation="Increase ensemble weight; reduce rl allocation.",
            generated_at=datetime.utcnow(),
        )
    """

    model_config = ConfigDict(frozen=True)

    period: str = Field(
        ...,
        description="Evaluation window used for all strategies.",
        pattern=r"^(daily|weekly|monthly)$",
    )
    strategies: dict[str, StrategyPerformance] = Field(
        default_factory=dict,
        description="Performance stats keyed by strategy name.",
    )
    ranking: list[str] = Field(
        default_factory=list,
        description="Strategy names ordered best-to-worst by Sharpe ratio.",
    )
    best_strategy: str = Field(
        ...,
        description="Name of the top-ranked strategy.",
    )
    worst_strategy: str = Field(
        ...,
        description="Name of the bottom-ranked strategy.",
    )
    recommendation: str = Field(
        ...,
        description="Guidance on ensemble weight adjustments or strategy disabling.",
    )
    generated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when this comparison was generated.",
    )


class ABTestResult(BaseModel):
    """Evaluation result of a completed A/B test between two strategy variants.

    Produced by :class:`~agent.trading.ab_testing.ABTestRunner.evaluate`
    after both variants have reached ``min_trades``.  Includes the winning
    variant declaration and the statistical significance of the result.

    Attributes:
        test_id: Unique identifier for the A/B test.
        strategy_name: Name of the strategy under test.
        variant_a_performance: Performance metrics for variant A.
        variant_b_performance: Performance metrics for variant B.
        winner: Winning variant: ``"a"``, ``"b"``, or ``"inconclusive"`` if
            the difference is not statistically significant.
        p_value: p-value from the t-test comparing variant outcomes.  Values
            below 0.05 are conventionally considered statistically significant.
        is_significant: ``True`` when ``p_value < 0.05``.
        recommendation: Human-readable summary of what to do next
            (e.g. ``"Promote variant B; 15 % higher Sharpe with p=0.02."``).
        evaluated_at: UTC timestamp when the evaluation was performed.

    Example::

        result = ABTestResult(
            test_id="ab_001",
            strategy_name="evolutionary_strategy",
            variant_a_performance=StrategyPerformance(...),
            variant_b_performance=StrategyPerformance(...),
            winner="b",
            p_value=0.021,
            is_significant=True,
            recommendation="Promote variant B; 18 % better Sharpe at p=0.021.",
            evaluated_at=datetime.utcnow(),
        )
    """

    model_config = ConfigDict(frozen=True)

    test_id: str = Field(..., description="Unique identifier for the A/B test.")
    strategy_name: str = Field(..., description="Strategy under test.")
    variant_a_performance: StrategyPerformance = Field(
        ...,
        description="Performance metrics for variant A.",
    )
    variant_b_performance: StrategyPerformance = Field(
        ...,
        description="Performance metrics for variant B.",
    )
    winner: str = Field(
        ...,
        description="Winning variant: 'a', 'b', or 'inconclusive'.",
        pattern=r"^(a|b|inconclusive)$",
    )
    p_value: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="p-value from the significance test (t-test).",
    )
    is_significant: bool = Field(
        ...,
        description="True when p_value < 0.05 (conventionally significant).",
    )
    recommendation: str = Field(
        ...,
        description="What to do next based on test results.",
    )
    evaluated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the evaluation was performed.",
    )


# ---------------------------------------------------------------------------
# Trading loop runtime
# ---------------------------------------------------------------------------


class ExecutionResult(BaseModel):
    """Result of a single trade execution attempt through the SDK.

    Produced by :class:`~agent.trading.execution.TradeExecutor.execute` for
    every call to the platform order engine.  Captures the platform's order
    response alongside pre/post portfolio state for journaling.

    Attributes:
        success: Whether the order was accepted and filled by the platform.
        order_id: Platform-assigned order identifier.  Empty string when
            ``success`` is ``False``.
        symbol: Trading pair that was traded.
        side: Order side: ``"buy"`` or ``"sell"``.
        quantity: Executed quantity (in base asset units).
        fill_price: Actual fill price assigned by the order engine.  ``None``
            when ``success`` is ``False``.
        fee: Trading fee charged for the execution (USDT).
        error_message: Error description when ``success`` is ``False``.
        executed_at: UTC timestamp of the execution.

    Example::

        result = ExecutionResult(
            success=True,
            order_id="ord_7f8e9a",
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("0.001"),
            fill_price=Decimal("67850.00"),
            fee=Decimal("0.068"),
            error_message="",
            executed_at=datetime.utcnow(),
        )
    """

    model_config = ConfigDict(frozen=True)

    success: bool = Field(..., description="Whether the order was accepted and filled.")
    order_id: str = Field(
        default="",
        description="Platform-assigned order identifier; empty on failure.",
    )
    symbol: str = Field(..., description="Trading pair that was traded.")
    side: str = Field(
        ...,
        description="Order side: 'buy' or 'sell'.",
        pattern=r"^(buy|sell)$",
    )
    quantity: Decimal = Field(
        ...,
        gt=Decimal("0"),
        description="Executed quantity in base asset units.",
    )
    fill_price: Decimal | None = Field(
        default=None,
        description="Actual fill price; None when execution failed.",
    )
    fee: Decimal = Field(
        ...,
        ge=Decimal("0"),
        description="Trading fee charged for the execution in USDT.",
    )
    error_message: str = Field(
        default="",
        description="Error description when success is False.",
    )
    executed_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of the execution attempt.",
    )


class PositionAction(BaseModel):
    """Recommended action for a single open position from the position monitor.

    Produced by :class:`~agent.trading.monitor.PositionMonitor.check_positions`
    after evaluating each open position's P&L, stop-loss/take-profit levels,
    and maximum holding duration.

    Attributes:
        symbol: Trading pair of the open position.
        current_pnl: Current unrealised P&L for the position.
        action: Recommended action: ``"hold"``, ``"partial_exit"``, or
            ``"full_exit"``.
        exit_pct: Fraction of the position to close.  ``1.0`` for
            ``full_exit``, a value in ``(0.0, 1.0)`` for ``partial_exit``,
            and ``0.0`` for ``hold``.
        reason: Explanation of why this action is recommended (e.g.
            ``"Stop-loss level breached"``).
        urgency: How quickly the action should be executed: ``"immediate"``,
            ``"next_cycle"``, or ``"monitor"``.

    Example::

        action = PositionAction(
            symbol="ETHUSDT",
            current_pnl=Decimal("-120.00"),
            action="full_exit",
            exit_pct=1.0,
            reason="Stop-loss breached: price dropped below 2850.00.",
            urgency="immediate",
        )
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Trading pair of the open position.")
    current_pnl: Decimal = Field(
        ...,
        description="Current unrealised profit/loss for the position.",
    )
    action: str = Field(
        ...,
        description="Recommended action: 'hold', 'partial_exit', or 'full_exit'.",
        pattern=r"^(hold|partial_exit|full_exit)$",
    )
    exit_pct: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of the position to close (0.0 = hold, 1.0 = full exit).",
    )
    reason: str = Field(
        ...,
        description="Explanation of why this action is recommended.",
    )
    urgency: str = Field(
        ...,
        description="Execution urgency: 'immediate', 'next_cycle', or 'monitor'.",
        pattern=r"^(immediate|next_cycle|monitor)$",
    )


class TradingCycleResult(BaseModel):
    """Summary of one complete trading loop tick.

    Produced by :class:`~agent.trading.loop.TradingLoop.tick` and recorded
    to ``agent_decisions`` for monitoring, replay, and learning.  Each tick
    covers observe → analyse → decide → check → execute → record.

    Attributes:
        agent_id: Agent that executed the cycle.
        cycle_number: Sequential tick counter since loop start (1-indexed).
        symbols_observed: Trading pairs that were observed this tick.
        signals_generated: Number of signals produced by the signal generator.
        decisions_made: Number of final trade decisions (after LLM reasoning).
        trades_executed: Number of orders actually submitted to the platform.
        executions: Ordered list of execution results for trades placed this
            tick.  Empty when all decisions were ``"hold"``.
        position_actions: Position monitor actions evaluated this tick.
        errors: Any non-fatal errors encountered during the cycle.  The loop
            continues despite these — one failed symbol must not stop others.
        cycle_duration_ms: Wall-clock duration of the tick in milliseconds.
        completed_at: UTC timestamp when the tick completed.

    Example::

        cycle = TradingCycleResult(
            agent_id="agent_xyz",
            cycle_number=42,
            symbols_observed=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            signals_generated=3,
            decisions_made=1,
            trades_executed=1,
            executions=[ExecutionResult(...)],
            position_actions=[],
            errors=[],
            cycle_duration_ms=1240,
            completed_at=datetime.utcnow(),
        )
    """

    model_config = ConfigDict(frozen=True)

    agent_id: str = Field(..., description="Agent that executed this cycle.")
    cycle_number: int = Field(
        ...,
        ge=1,
        description="Sequential tick counter since loop start (1-indexed).",
    )
    symbols_observed: list[str] = Field(
        default_factory=list,
        description="Trading pairs observed this tick.",
    )
    signals_generated: int = Field(
        ...,
        ge=0,
        description="Number of signals produced by the signal generator.",
    )
    decisions_made: int = Field(
        ...,
        ge=0,
        description="Number of final trade decisions after LLM reasoning.",
    )
    trades_executed: int = Field(
        ...,
        ge=0,
        description="Number of orders actually submitted to the platform.",
    )
    executions: list[ExecutionResult] = Field(
        default_factory=list,
        description="Execution results for trades placed this tick.",
    )
    position_actions: list[PositionAction] = Field(
        default_factory=list,
        description="Position monitor actions evaluated this tick.",
    )
    errors: list[str] = Field(
        default_factory=list,
        description="Non-fatal errors encountered; loop continues despite these.",
    )
    cycle_duration_ms: int = Field(
        ...,
        ge=0,
        description="Wall-clock duration of the tick in milliseconds.",
    )
    completed_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the tick completed.",
    )


# ---------------------------------------------------------------------------
# Health monitoring
# ---------------------------------------------------------------------------


class HealthStatus(BaseModel):
    """Health and runtime status of the agent server process.

    Returned by :meth:`~agent.server.AgentServer.health_check` for monitoring
    dashboards and readiness probes.  All connection statuses use ``bool``
    so they can be evaluated in alerting rules.

    Attributes:
        agent_id: Identifier of the agent server instance being reported.
        status: Overall server status: ``"healthy"``, ``"degraded"``, or
            ``"unhealthy"``.
        uptime_seconds: Seconds since the server process started.
        active_session_id: ID of the currently active conversation session,
            or ``None`` if the server is idle.
        last_activity_at: UTC timestamp of the most recent agent action.
            ``None`` if no actions have been taken since startup.
        memory_entries: Total number of entries across all memory stores
            (short-term + long-term).
        db_connected: Whether the database connection pool is healthy.
        redis_connected: Whether the Redis connection is healthy.
        sdk_connected: Whether the platform SDK client is connected.
        trading_loop_running: Whether the autonomous trading loop is active.
        open_positions: Number of currently open trading positions.
        checked_at: UTC timestamp when the health check was performed.

    Example::

        health = HealthStatus(
            agent_id="agent_xyz",
            status="healthy",
            uptime_seconds=3600,
            active_session_id=None,
            last_activity_at=datetime.utcnow(),
            memory_entries=142,
            db_connected=True,
            redis_connected=True,
            sdk_connected=True,
            trading_loop_running=True,
            open_positions=3,
            checked_at=datetime.utcnow(),
        )
    """

    model_config = ConfigDict(frozen=True)

    agent_id: str = Field(..., description="Identifier of the agent server instance.")
    status: str = Field(
        ...,
        description="Overall status: 'healthy', 'degraded', or 'unhealthy'.",
        pattern=r"^(healthy|degraded|unhealthy)$",
    )
    uptime_seconds: int = Field(
        ...,
        ge=0,
        description="Seconds since the server process started.",
    )
    active_session_id: str | None = Field(
        default=None,
        description="Active conversation session ID; None when idle.",
    )
    last_activity_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of the most recent agent action.",
    )
    memory_entries: int = Field(
        ...,
        ge=0,
        description="Total entries across all memory stores.",
    )
    db_connected: bool = Field(..., description="Whether the DB connection pool is healthy.")
    redis_connected: bool = Field(..., description="Whether the Redis connection is healthy.")
    sdk_connected: bool = Field(
        ...,
        description="Whether the platform SDK client is connected.",
    )
    trading_loop_running: bool = Field(
        ...,
        description="Whether the autonomous trading loop is active.",
    )
    open_positions: int = Field(
        ...,
        ge=0,
        description="Number of currently open trading positions.",
    )
    checked_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp when the health check was performed.",
    )
