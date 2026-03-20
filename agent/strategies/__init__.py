"""agent/strategies — Strategy optimisation and risk management primitives.

Public API (rl):
    RLConfig             - All hyperparameters for PPO training (Pydantic settings)

Public API (evolutionary):
    StrategyGenome       - Parameter vector for a single trading strategy candidate
    Population           - Collection of genomes with evolution operators
    tournament_select    - Fitness-proportional parent selection
    crossover            - Single-point genome crossover
    mutate               - Gaussian parameter mutation
    clip_genome          - Enforce all parameter bounds in-place

Public API (risk):
    RiskConfig           - Configurable thresholds for portfolio-level risk checks
    RiskAssessment       - Result of a full portfolio risk assessment
    TradeApproval        - Result of a pre-trade approval check
    RiskAgent            - Stateful agent for portfolio-level risk monitoring

Public API (regime):
    RegimeType               - Enum: TRENDING, MEAN_REVERTING, HIGH_VOLATILITY, LOW_VOLATILITY
    label_candles            - Assign RegimeType to each candle in a list
    generate_training_data   - Build feature DataFrame + label Series for training
    RegimeClassifier         - Train, predict, evaluate, save, and load the classifier
    TRENDING_STRATEGY        - StrategyDefinition dict for trending regimes
    MEAN_REVERTING_STRATEGY  - StrategyDefinition dict for mean-reverting regimes
    HIGH_VOLATILITY_STRATEGY - StrategyDefinition dict for high-volatility regimes
    LOW_VOLATILITY_STRATEGY  - StrategyDefinition dict for low-volatility regimes
    STRATEGY_BY_REGIME       - Dict mapping RegimeType to its strategy definition dict
    create_regime_strategies - Create all 4 strategies via REST API; returns strategy_ids

Public API (ensemble):
    SignalSource         - Enum: RL, EVOLVED, REGIME
    TradeAction          - Enum: BUY, SELL, HOLD
    WeightedSignal       - Per-source signal with action, confidence, and metadata
    ConsensusSignal      - Combined output from MetaLearner across all sources
    MetaLearner          - Weighted ensemble combiner; converts any mix of signals to
                           ConsensusSignal; includes rl/genome/regime conversion helpers
"""

from agent.strategies.evolutionary.battle_runner import BattleRunner
from agent.strategies.evolutionary.genome import StrategyGenome
from agent.strategies.evolutionary.operators import clip_genome, crossover, mutate, tournament_select
from agent.strategies.evolutionary.population import Population
from agent.strategies.regime import (
    HIGH_VOLATILITY_STRATEGY,
    LOW_VOLATILITY_STRATEGY,
    MEAN_REVERTING_STRATEGY,
    STRATEGY_BY_REGIME,
    TRENDING_STRATEGY,
    RegimeClassifier,
    RegimeType,
    create_regime_strategies,
    generate_training_data,
    label_candles,
)
from agent.strategies.ensemble.meta_learner import MetaLearner
from agent.strategies.ensemble.signals import ConsensusSignal, SignalSource, TradeAction, WeightedSignal
from agent.strategies.risk.risk_agent import RiskAgent, RiskAssessment, RiskConfig, TradeApproval
from agent.strategies.rl.config import RLConfig

__all__ = [
    # RL
    "RLConfig",
    # Evolutionary
    "StrategyGenome",
    "Population",
    "tournament_select",
    "crossover",
    "mutate",
    "clip_genome",
    "BattleRunner",
    # Risk
    "RiskConfig",
    "RiskAssessment",
    "TradeApproval",
    "RiskAgent",
    # Regime
    "RegimeType",
    "label_candles",
    "generate_training_data",
    "RegimeClassifier",
    "TRENDING_STRATEGY",
    "MEAN_REVERTING_STRATEGY",
    "HIGH_VOLATILITY_STRATEGY",
    "LOW_VOLATILITY_STRATEGY",
    "STRATEGY_BY_REGIME",
    "create_regime_strategies",
    # Ensemble
    "SignalSource",
    "TradeAction",
    "WeightedSignal",
    "ConsensusSignal",
    "MetaLearner",
]
