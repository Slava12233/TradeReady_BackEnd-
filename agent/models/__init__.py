"""Pydantic output models for agent workflows and reports.

All models use Pydantic v2 ``BaseModel`` with ``ConfigDict(frozen=True)`` so
that instances are immutable and can safely be used as ``output_type`` values
in Pydantic AI agents.

Public API::

    from agent.models import (
        SignalType,
        TradeSignal,
        MarketAnalysis,
        BacktestAnalysis,
        WorkflowResult,
        PlatformValidationReport,
    )
"""

from agent.models.analysis import BacktestAnalysis, MarketAnalysis
from agent.models.report import PlatformValidationReport, WorkflowResult
from agent.models.trade_signal import SignalType, TradeSignal

__all__ = [
    "SignalType",
    "TradeSignal",
    "MarketAnalysis",
    "BacktestAnalysis",
    "WorkflowResult",
    "PlatformValidationReport",
]
