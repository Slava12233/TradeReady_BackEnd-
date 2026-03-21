"""Pydantic output models for agent workflows and reports.

All models use Pydantic v2 ``BaseModel`` with ``ConfigDict(frozen=True)`` so
that instances are immutable and can safely be used as ``output_type`` values
in Pydantic AI agents.

Public API::

    from agent.models import (
        # Original workflow models
        SignalType,
        TradeSignal,
        MarketAnalysis,
        BacktestAnalysis,
        WorkflowResult,
        PlatformValidationReport,
        # Ecosystem models — trading decisions
        TradeDecision,
        TradeReflection,
        PortfolioReview,
        # Ecosystem models — opportunity scanning
        Opportunity,
        # Ecosystem models — journal and feedback
        JournalEntry,
        FeedbackEntry,
        # Ecosystem models — permission and budget
        BudgetCheckResult,
        BudgetStatus,
        EnforcementResult,
        AuditEntry,
        # Ecosystem models — strategy management
        DegradationAlert,
        Adjustment,
        StrategyPerformance,
        StrategyComparison,
        ABTestResult,
        # Ecosystem models — trading loop runtime
        TradingCycleResult,
        ExecutionResult,
        PositionAction,
        # Ecosystem models — health monitoring
        HealthStatus,
    )
"""

from agent.models.analysis import BacktestAnalysis, MarketAnalysis
from agent.models.ecosystem import (
    ABTestResult,
    Adjustment,
    AuditEntry,
    BudgetCheckResult,
    BudgetStatus,
    DegradationAlert,
    EnforcementResult,
    ExecutionResult,
    FeedbackEntry,
    HealthStatus,
    JournalEntry,
    Opportunity,
    PortfolioReview,
    PositionAction,
    StrategyComparison,
    StrategyPerformance,
    TradeDecision,
    TradeReflection,
    TradingCycleResult,
)
from agent.models.report import PlatformValidationReport, WorkflowResult
from agent.models.trade_signal import SignalType, TradeSignal

__all__ = [
    # Original workflow models
    "SignalType",
    "TradeSignal",
    "MarketAnalysis",
    "BacktestAnalysis",
    "WorkflowResult",
    "PlatformValidationReport",
    # Ecosystem models — trading decisions
    "TradeDecision",
    "TradeReflection",
    "PortfolioReview",
    # Ecosystem models — opportunity scanning
    "Opportunity",
    # Ecosystem models — journal and feedback
    "JournalEntry",
    "FeedbackEntry",
    # Ecosystem models — permission and budget
    "BudgetCheckResult",
    "BudgetStatus",
    "EnforcementResult",
    "AuditEntry",
    # Ecosystem models — strategy management
    "DegradationAlert",
    "Adjustment",
    "StrategyPerformance",
    "StrategyComparison",
    "ABTestResult",
    # Ecosystem models — trading loop runtime
    "TradingCycleResult",
    "ExecutionResult",
    "PositionAction",
    # Ecosystem models — health monitoring
    "HealthStatus",
]
