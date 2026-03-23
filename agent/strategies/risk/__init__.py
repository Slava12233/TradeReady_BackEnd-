"""agent/strategies/risk — Portfolio-level risk monitoring agent.

Provides portfolio-level exposure, correlation, and drawdown checks that sit
ON TOP of the platform's built-in per-order risk manager.  The platform
already validates individual orders through an 8-step chain (position limits,
daily loss circuit-breaker, rate limits, etc.).  This agent adds a higher
layer that continuously monitors the aggregate portfolio state and decides
whether the strategy should trade, reduce exposure, or halt entirely.

Public API:
    DrawdownTier     - Single drawdown tier (threshold → multiplier)
    DrawdownProfile  - Per-agent configurable drawdown response profile
    AGGRESSIVE_PROFILE  - Preset for Momentum/Evolved strategies
    MODERATE_PROFILE    - Preset for Balanced/Regime strategies (default)
    CONSERVATIVE_PROFILE - Tightest drawdown response preset

    RiskConfig       - Configurable thresholds for all risk checks
    RiskAssessment   - Result of a full portfolio assessment (includes scale_factor)
    TradeApproval    - Result of a pre-trade approval check
    RiskAgent        - Stateful agent that performs assessments and approvals

    TradeSignal      - Proposed trade signal for the veto pipeline (risk layer)
    VetoDecision     - Result of running a signal through VetoPipeline (includes scale_factor)
    VetoPipeline     - Sequential gate-checking pipeline (6 checks)

    SizingMethod     - Enum to select the active sizing algorithm
    SizerConfig      - Configuration bounds for the dynamic position sizer
    DynamicSizer     - Volatility- and drawdown-adjusted position sizer

    KellyConfig      - Configuration for the fractional Kelly sizer
    KellyFractionalSizer - Half/Quarter-Kelly position sizer

    HybridConfig     - Configuration for the hybrid Kelly + ATR sizer
    HybridSizer      - ATR-adjusted Kelly position sizer

    ExecutionDecision - Full audit record for one signal through the middleware
    RiskMiddleware    - Wires RiskAgent + VetoPipeline + DynamicSizer + SDK

    RecoveryState    - Enum: RECOVERING | SCALING_UP | FULL
    RecoveryConfig   - Tuning parameters for the recovery manager
    RecoverySnapshot - Point-in-time snapshot of recovery machine state
    RecoveryManager  - Graduated drawdown recovery with Redis persistence
"""

from agent.strategies.risk.middleware import ExecutionDecision, RiskMiddleware
from agent.strategies.risk.recovery import (
    RecoveryConfig,
    RecoveryManager,
    RecoverySnapshot,
    RecoveryState,
)
from agent.strategies.risk.risk_agent import (
    AGGRESSIVE_PROFILE,
    CONSERVATIVE_PROFILE,
    MODERATE_PROFILE,
    DrawdownProfile,
    DrawdownTier,
    RiskAgent,
    RiskAssessment,
    RiskConfig,
    TradeApproval,
)
from agent.strategies.risk.sizing import (
    DynamicSizer,
    HybridConfig,
    HybridSizer,
    KellyConfig,
    KellyFractionalSizer,
    SizerConfig,
    SizingMethod,
)
from agent.strategies.risk.veto import TradeSignal, VetoDecision, VetoPipeline

__all__ = [
    # Drawdown profile
    "DrawdownTier",
    "DrawdownProfile",
    "AGGRESSIVE_PROFILE",
    "MODERATE_PROFILE",
    "CONSERVATIVE_PROFILE",
    # Core risk agent
    "RiskConfig",
    "RiskAssessment",
    "TradeApproval",
    "RiskAgent",
    # Veto pipeline
    "TradeSignal",
    "VetoDecision",
    "VetoPipeline",
    # Sizing method selector
    "SizingMethod",
    # Dynamic sizer (original)
    "SizerConfig",
    "DynamicSizer",
    # Kelly fractional sizer
    "KellyConfig",
    "KellyFractionalSizer",
    # Hybrid Kelly + ATR sizer
    "HybridConfig",
    "HybridSizer",
    # Middleware
    "ExecutionDecision",
    "RiskMiddleware",
    # Recovery manager
    "RecoveryState",
    "RecoveryConfig",
    "RecoverySnapshot",
    "RecoveryManager",
]
