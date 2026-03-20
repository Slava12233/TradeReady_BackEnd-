"""Market regime detection package.

Provides a label-based regime classifier trained on historical OHLCV candles.
The labeler assigns regimes based on ADX (trend strength) and ATR/close ratio
(volatility), and the classifier learns to predict regimes from indicator
features using XGBoost (or sklearn RandomForest as fallback).

Also provides four platform-ready strategy definitions — one per regime —
``create_regime_strategies()`` for creating them all via the REST API, and
``RegimeSwitcher`` for orchestrating live regime detection and strategy
activation in the agent's decision loop.

Public API:
    RegimeType              - Enum: TRENDING, MEAN_REVERTING, HIGH_VOLATILITY, LOW_VOLATILITY
    label_candles           - Assign RegimeType to each candle in a list
    generate_training_data  - Build feature DataFrame + label Series for training
    RegimeClassifier        - Train, predict, evaluate, save, and load the classifier
    TRENDING_STRATEGY       - StrategyDefinition dict for trending regimes
    MEAN_REVERTING_STRATEGY - StrategyDefinition dict for mean-reverting regimes
    HIGH_VOLATILITY_STRATEGY - StrategyDefinition dict for high-volatility regimes
    LOW_VOLATILITY_STRATEGY - StrategyDefinition dict for low-volatility regimes
    STRATEGY_BY_REGIME      - Dict mapping RegimeType to its strategy definition dict
    create_regime_strategies - Create all 4 strategies via REST API; returns strategy_ids
    RegimeSwitcher          - Detect regime changes and activate the correct strategy
    RegimeRecord            - Immutable snapshot of a single regime-switch event
    CONFIDENCE_THRESHOLD    - Default minimum confidence to accept a regime switch (0.7)
    SWITCH_COOLDOWN_CANDLES - Default cooldown period between switches (5 candles)
"""

from agent.strategies.regime.classifier import RegimeClassifier
from agent.strategies.regime.labeler import (
    RegimeType,
    generate_training_data,
    label_candles,
)
from agent.strategies.regime.strategy_definitions import (
    HIGH_VOLATILITY_STRATEGY,
    LOW_VOLATILITY_STRATEGY,
    MEAN_REVERTING_STRATEGY,
    STRATEGY_BY_REGIME,
    TRENDING_STRATEGY,
    create_regime_strategies,
)
from agent.strategies.regime.switcher import (
    CONFIDENCE_THRESHOLD,
    SWITCH_COOLDOWN_CANDLES,
    RegimeRecord,
    RegimeSwitcher,
)

__all__ = [
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
    "RegimeSwitcher",
    "RegimeRecord",
    "CONFIDENCE_THRESHOLD",
    "SWITCH_COOLDOWN_CANDLES",
]
