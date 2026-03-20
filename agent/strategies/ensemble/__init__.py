"""agent/strategies/ensemble — Meta-learner signal combiner and ensemble runner.

Combines signals from three strategy sources into a single consensus signal:

- RL (PPO): portfolio weight outputs converted to directional signals
- EVOLVED: genetic algorithm genome RSI/MACD conditions
- REGIME: market regime classifier directional bias

Public API:
    SignalSource        - Enum: RL, EVOLVED, REGIME
    WeightedSignal      - A single signal from one source with confidence
    ConsensusSignal     - Combined output across all contributing sources
    MetaLearner         - Combines WeightedSignal list into ConsensusSignal
    WeightConfig        - A named weight configuration for the optimizer
    ConfigResult        - Backtest outcome for one weight configuration
    OptimizationResult  - Full output of a weight optimisation run
    WeightOptimizer     - Runs backtests for 12 weight configs, ranks by Sharpe
    EnsembleConfig      - Pydantic-settings configuration for EnsembleRunner
    EnsembleRunner      - Full multi-signal pipeline orchestrator
    StepResult          - Per-step audit record (all signals, consensus, orders)
    SymbolStepResult    - Per-symbol breakdown within one step
    SignalContribution  - Per-source signal detail record
    EnsembleReport      - Aggregated session report with per-source stats
    SourceStats         - Per-source contribution statistics
"""

from agent.strategies.ensemble.config import EnsembleConfig
from agent.strategies.ensemble.meta_learner import MetaLearner
from agent.strategies.ensemble.optimize_weights import (
    ConfigResult,
    OptimizationResult,
    WeightConfig,
    WeightOptimizer,
)
from agent.strategies.ensemble.run import (
    EnsembleReport,
    EnsembleRunner,
    SignalContribution,
    SourceStats,
    StepResult,
    SymbolStepResult,
)
from agent.strategies.ensemble.signals import ConsensusSignal, SignalSource, TradeAction, WeightedSignal

__all__ = [
    # Signal primitives
    "SignalSource",
    "TradeAction",
    "WeightedSignal",
    "ConsensusSignal",
    # Meta-learner
    "MetaLearner",
    # Weight optimizer
    "WeightConfig",
    "ConfigResult",
    "OptimizationResult",
    "WeightOptimizer",
    # Ensemble runner
    "EnsembleConfig",
    "EnsembleRunner",
    "SignalContribution",
    "SymbolStepResult",
    "StepResult",
    "SourceStats",
    "EnsembleReport",
]
