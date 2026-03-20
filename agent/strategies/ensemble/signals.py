"""Signal data models for the ensemble meta-learner.

Defines the three source types, the per-source WeightedSignal, and the
combined ConsensusSignal that the MetaLearner produces.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SignalSource(str, Enum):
    """The strategy system that produced a signal.

    Values:
        RL:      PPO reinforcement-learning model (portfolio weight outputs).
        EVOLVED: Genetic-algorithm-optimised strategy genome (RSI/MACD rules).
        REGIME:  Market-regime classifier (regime → directional bias mapping).
    """

    RL = "rl"
    EVOLVED = "evolved"
    REGIME = "regime"


class TradeAction(str, Enum):
    """Discrete trading direction.

    Values:
        BUY:  Increase position — allocate or open long.
        SELL: Reduce position — deallocate or open short.
        HOLD: No action — maintain current allocation.
    """

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class WeightedSignal(BaseModel):
    """A single directional signal emitted by one strategy source.

    Args:
        source: Which strategy system produced this signal.
        symbol: Trading pair this signal applies to (e.g. ``"BTCUSDT"``).
        action: Discrete direction — BUY, SELL, or HOLD.
        confidence: Classifier or model confidence in this signal (0.0–1.0).
            A confidence of 0 means the source is offline or has no opinion.
        metadata: Optional source-specific context (e.g. weight delta for RL,
            RSI value for EVOLVED, regime name for REGIME).
    """

    model_config = ConfigDict(frozen=True)

    source: SignalSource
    symbol: str
    action: TradeAction
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConsensusSignal(BaseModel):
    """Combined directional signal produced by the MetaLearner.

    Args:
        symbol: Trading pair this consensus covers.
        action: Final decision after weighted voting across all sources.
        combined_confidence: Weighted sum of contributing confidences (0.0–1.0).
            Values below the MetaLearner's ``confidence_threshold`` result in a
            HOLD action.
        contributing_signals: All WeightedSignal instances that participated
            in the vote (including HOLD signals from offline sources).
        agreement_rate: Fraction of active (non-zero confidence) sources that
            agree with the final action (0.0–1.0).  A value of 1.0 means
            unanimous agreement across all active sources.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    action: TradeAction
    combined_confidence: float = Field(ge=0.0, le=1.0)
    contributing_signals: list[WeightedSignal]
    agreement_rate: float = Field(ge=0.0, le=1.0)
