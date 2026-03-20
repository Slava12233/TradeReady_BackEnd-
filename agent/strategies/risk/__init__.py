"""agent/strategies/risk — Portfolio-level risk monitoring agent.

Provides portfolio-level exposure, correlation, and drawdown checks that sit
ON TOP of the platform's built-in per-order risk manager.  The platform
already validates individual orders through an 8-step chain (position limits,
daily loss circuit-breaker, rate limits, etc.).  This agent adds a higher
layer that continuously monitors the aggregate portfolio state and decides
whether the strategy should trade, reduce exposure, or halt entirely.

Public API:
    RiskConfig       - Configurable thresholds for all risk checks
    RiskAssessment   - Result of a full portfolio assessment
    TradeApproval    - Result of a pre-trade approval check
    RiskAgent        - Stateful agent that performs assessments and approvals

    TradeSignal      - Proposed trade signal for the veto pipeline (risk layer)
    VetoDecision     - Result of running a signal through VetoPipeline
    VetoPipeline     - Sequential gate-checking pipeline (6 checks)

    SizerConfig      - Configuration bounds for the dynamic position sizer
    DynamicSizer     - Volatility- and drawdown-adjusted position sizer

    ExecutionDecision - Full audit record for one signal through the middleware
    RiskMiddleware    - Wires RiskAgent + VetoPipeline + DynamicSizer + SDK
"""

from agent.strategies.risk.middleware import ExecutionDecision, RiskMiddleware
from agent.strategies.risk.risk_agent import RiskAgent, RiskAssessment, RiskConfig, TradeApproval
from agent.strategies.risk.sizing import DynamicSizer, SizerConfig
from agent.strategies.risk.veto import TradeSignal, VetoDecision, VetoPipeline

__all__ = [
    # Core risk agent
    "RiskConfig",
    "RiskAssessment",
    "TradeApproval",
    "RiskAgent",
    # Veto pipeline
    "TradeSignal",
    "VetoDecision",
    "VetoPipeline",
    # Dynamic sizer
    "SizerConfig",
    "DynamicSizer",
    # Middleware
    "ExecutionDecision",
    "RiskMiddleware",
]
