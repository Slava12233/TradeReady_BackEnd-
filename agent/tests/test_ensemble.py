"""Unit tests for the ensemble meta-learner signal combiner.

Tests cover:
- SignalSource and TradeAction enums
- WeightedSignal and ConsensusSignal Pydantic models
- MetaLearner weight normalisation
- 3/3 agreement → high confidence (>0.8)
- 2/3 agreement → medium confidence
- 0/3 agreement (all different) → HOLD
- Missing / offline sources (confidence=0) → HOLD
- Confidence threshold guard
- Agreement rate calculation
- rl_weights_to_signals conversion
- genome_to_signals conversion
- regime_to_signals conversion
- combine_all multi-symbol dispatch
"""

from __future__ import annotations

import numpy as np
import pytest

from agent.strategies.ensemble.meta_learner import MetaLearner
from agent.strategies.ensemble.signals import ConsensusSignal, SignalSource, TradeAction, WeightedSignal


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_signal(
    source: SignalSource,
    action: TradeAction,
    confidence: float,
    symbol: str = "BTCUSDT",
) -> WeightedSignal:
    return WeightedSignal(source=source, symbol=symbol, action=action, confidence=confidence)


# ── Enum and model tests ──────────────────────────────────────────────────────


def test_signal_source_values() -> None:
    assert SignalSource.RL.value == "rl"
    assert SignalSource.EVOLVED.value == "evolved"
    assert SignalSource.REGIME.value == "regime"


def test_trade_action_values() -> None:
    assert TradeAction.BUY.value == "buy"
    assert TradeAction.SELL.value == "sell"
    assert TradeAction.HOLD.value == "hold"


def test_weighted_signal_frozen() -> None:
    sig = _make_signal(SignalSource.RL, TradeAction.BUY, 0.8)
    with pytest.raises(Exception):
        sig.confidence = 0.5  # type: ignore[misc]


def test_weighted_signal_confidence_bounds() -> None:
    with pytest.raises(Exception):
        WeightedSignal(source=SignalSource.RL, symbol="X", action=TradeAction.BUY, confidence=1.5)
    with pytest.raises(Exception):
        WeightedSignal(source=SignalSource.RL, symbol="X", action=TradeAction.BUY, confidence=-0.1)


def test_consensus_signal_frozen() -> None:
    cs = ConsensusSignal(
        symbol="BTCUSDT",
        action=TradeAction.HOLD,
        combined_confidence=0.0,
        contributing_signals=[],
        agreement_rate=0.0,
    )
    with pytest.raises(Exception):
        cs.action = TradeAction.BUY  # type: ignore[misc]


# ── MetaLearner weight normalisation ─────────────────────────────────────────


def test_equal_weights_normalise_to_one_third() -> None:
    ml = MetaLearner()
    for w in ml._weights.values():
        assert abs(w - 1 / 3) < 1e-9


def test_custom_weights_normalise() -> None:
    ml = MetaLearner(weights={SignalSource.RL: 2.0, SignalSource.EVOLVED: 1.0, SignalSource.REGIME: 1.0})
    assert abs(ml._weights[SignalSource.RL] - 0.5) < 1e-9
    assert abs(ml._weights[SignalSource.EVOLVED] - 0.25) < 1e-9
    total = sum(ml._weights.values())
    assert abs(total - 1.0) < 1e-9


def test_zero_sum_weights_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        MetaLearner(weights={SignalSource.RL: 0.0, SignalSource.EVOLVED: 0.0, SignalSource.REGIME: 0.0})


# ── 3/3 unanimous agreement → high combined confidence ───────────────────────


def test_unanimous_buy_high_confidence() -> None:
    ml = MetaLearner()
    signals = [
        _make_signal(SignalSource.RL, TradeAction.BUY, 0.9),
        _make_signal(SignalSource.EVOLVED, TradeAction.BUY, 0.9),
        _make_signal(SignalSource.REGIME, TradeAction.BUY, 0.9),
    ]
    result = ml.combine(signals)
    assert result.action == TradeAction.BUY
    assert result.combined_confidence > 0.8
    assert result.agreement_rate == 1.0


def test_unanimous_sell_high_confidence() -> None:
    ml = MetaLearner()
    signals = [
        _make_signal(SignalSource.RL, TradeAction.SELL, 0.85),
        _make_signal(SignalSource.EVOLVED, TradeAction.SELL, 0.85),
        _make_signal(SignalSource.REGIME, TradeAction.SELL, 0.85),
    ]
    result = ml.combine(signals)
    assert result.action == TradeAction.SELL
    assert result.combined_confidence > 0.8


# ── 2/3 agreement → medium confidence ────────────────────────────────────────


def test_two_thirds_buy_medium_confidence() -> None:
    ml = MetaLearner(confidence_threshold=0.4)  # lower threshold to allow medium-conf signals
    signals = [
        _make_signal(SignalSource.RL, TradeAction.BUY, 0.7),
        _make_signal(SignalSource.EVOLVED, TradeAction.BUY, 0.7),
        _make_signal(SignalSource.REGIME, TradeAction.SELL, 0.7),
    ]
    result = ml.combine(signals)
    # 2/3 BUY → BUY should win
    assert result.action == TradeAction.BUY
    # Combined confidence should be < unanimous (0.85+) but > threshold
    assert 0.4 <= result.combined_confidence < 0.85
    # Agreement rate: 2 of 3 agree
    assert abs(result.agreement_rate - 2 / 3) < 0.01


# ── 0/3 agreement (all different) → HOLD ─────────────────────────────────────


def test_three_way_split_returns_hold() -> None:
    ml = MetaLearner()
    signals = [
        _make_signal(SignalSource.RL, TradeAction.BUY, 0.8),
        _make_signal(SignalSource.EVOLVED, TradeAction.SELL, 0.8),
        _make_signal(SignalSource.REGIME, TradeAction.HOLD, 0.8),
    ]
    result = ml.combine(signals)
    # BUY score = 1/3 * 0.8, SELL score = 1/3 * 0.8 — tied or below threshold
    # Low agreement rate triggers HOLD guard or confidence threshold
    assert result.action == TradeAction.HOLD


# ── Offline source (confidence=0) → treated as absent ────────────────────────


def test_offline_source_confidence_zero() -> None:
    """Source with confidence=0 contributes no vote weight."""
    ml = MetaLearner()
    signals = [
        _make_signal(SignalSource.RL, TradeAction.BUY, 0.9),
        _make_signal(SignalSource.EVOLVED, TradeAction.BUY, 0.9),
        _make_signal(SignalSource.REGIME, TradeAction.HOLD, 0.0),  # offline
    ]
    result = ml.combine(signals)
    assert result.action == TradeAction.BUY


def test_all_offline_returns_hold() -> None:
    """All sources offline → HOLD with confidence 0."""
    ml = MetaLearner()
    signals = [
        _make_signal(SignalSource.RL, TradeAction.BUY, 0.0),
        _make_signal(SignalSource.EVOLVED, TradeAction.BUY, 0.0),
        _make_signal(SignalSource.REGIME, TradeAction.BUY, 0.0),
    ]
    result = ml.combine(signals)
    assert result.action == TradeAction.HOLD
    assert result.combined_confidence == 0.0
    assert result.agreement_rate == 0.0


# ── Confidence threshold guard ────────────────────────────────────────────────


def test_below_confidence_threshold_returns_hold() -> None:
    ml = MetaLearner(confidence_threshold=0.8)
    signals = [
        _make_signal(SignalSource.RL, TradeAction.BUY, 0.5),
        _make_signal(SignalSource.EVOLVED, TradeAction.BUY, 0.5),
        _make_signal(SignalSource.REGIME, TradeAction.SELL, 0.5),
    ]
    result = ml.combine(signals)
    # Even with 2/3 BUY, combined confidence is ~0.5 → below 0.8 threshold
    assert result.action == TradeAction.HOLD


# ── Agreement rate ────────────────────────────────────────────────────────────


def test_agreement_rate_all_agree() -> None:
    ml = MetaLearner()
    signals = [
        _make_signal(SignalSource.RL, TradeAction.BUY, 0.9),
        _make_signal(SignalSource.EVOLVED, TradeAction.BUY, 0.7),
        _make_signal(SignalSource.REGIME, TradeAction.BUY, 0.8),
    ]
    assert ml.agreement_rate(signals) == 1.0


def test_agreement_rate_two_of_three() -> None:
    ml = MetaLearner()
    signals = [
        _make_signal(SignalSource.RL, TradeAction.BUY, 0.9),
        _make_signal(SignalSource.EVOLVED, TradeAction.BUY, 0.7),
        _make_signal(SignalSource.REGIME, TradeAction.SELL, 0.8),
    ]
    rate = ml.agreement_rate(signals)
    assert abs(rate - 2 / 3) < 0.01


def test_agreement_rate_empty_signals_returns_zero() -> None:
    ml = MetaLearner()
    assert ml.agreement_rate([]) == 0.0


def test_agreement_rate_excludes_zero_confidence() -> None:
    """Signals with confidence=0 are excluded from the agreement denominator."""
    ml = MetaLearner()
    signals = [
        _make_signal(SignalSource.RL, TradeAction.BUY, 0.9),
        _make_signal(SignalSource.EVOLVED, TradeAction.BUY, 0.7),
        _make_signal(SignalSource.REGIME, TradeAction.SELL, 0.0),  # offline
    ]
    rate = ml.agreement_rate(signals)
    # Only 2 active signals, both BUY → rate = 1.0
    assert rate == 1.0


# ── combine() validation ──────────────────────────────────────────────────────


def test_combine_empty_raises() -> None:
    ml = MetaLearner()
    with pytest.raises(ValueError):
        ml.combine([])


def test_combine_mixed_symbols_raises() -> None:
    ml = MetaLearner()
    signals = [
        _make_signal(SignalSource.RL, TradeAction.BUY, 0.9, symbol="BTCUSDT"),
        _make_signal(SignalSource.EVOLVED, TradeAction.BUY, 0.9, symbol="ETHUSDT"),
    ]
    with pytest.raises(ValueError, match="multiple symbols"):
        ml.combine(signals)


# ── combine_all multi-symbol dispatch ────────────────────────────────────────


def test_combine_all_returns_one_per_symbol() -> None:
    ml = MetaLearner()
    signals = [
        _make_signal(SignalSource.RL, TradeAction.BUY, 0.9, symbol="BTCUSDT"),
        _make_signal(SignalSource.EVOLVED, TradeAction.BUY, 0.9, symbol="BTCUSDT"),
        _make_signal(SignalSource.REGIME, TradeAction.BUY, 0.9, symbol="BTCUSDT"),
        _make_signal(SignalSource.RL, TradeAction.SELL, 0.85, symbol="ETHUSDT"),
        _make_signal(SignalSource.EVOLVED, TradeAction.SELL, 0.85, symbol="ETHUSDT"),
        _make_signal(SignalSource.REGIME, TradeAction.SELL, 0.85, symbol="ETHUSDT"),
    ]
    results = ml.combine_all(signals)
    assert len(results) == 2
    symbols = [r.symbol for r in results]
    assert "BTCUSDT" in symbols
    assert "ETHUSDT" in symbols

    btc = next(r for r in results if r.symbol == "BTCUSDT")
    eth = next(r for r in results if r.symbol == "ETHUSDT")
    assert btc.action == TradeAction.BUY
    assert eth.action == TradeAction.SELL


def test_combine_all_sorted_alphabetically() -> None:
    ml = MetaLearner()
    signals = [
        _make_signal(SignalSource.RL, TradeAction.BUY, 0.9, symbol="SOLUSDT"),
        _make_signal(SignalSource.RL, TradeAction.SELL, 0.9, symbol="BTCUSDT"),
    ]
    results = ml.combine_all(signals)
    assert [r.symbol for r in results] == ["BTCUSDT", "SOLUSDT"]


# ── rl_weights_to_signals conversion ─────────────────────────────────────────


def test_rl_weights_buy_signal() -> None:
    weights = np.array([0.5, 0.0], dtype=np.float32)
    symbols = ["BTCUSDT", "ETHUSDT"]
    signals = MetaLearner.rl_weights_to_signals(weights, symbols, current_weights={"BTCUSDT": 0.0, "ETHUSDT": 0.0})
    btc = next(s for s in signals if s.symbol == "BTCUSDT")
    eth = next(s for s in signals if s.symbol == "ETHUSDT")
    assert btc.action == TradeAction.BUY
    assert btc.confidence > 0
    assert eth.action == TradeAction.HOLD


def test_rl_weights_sell_signal() -> None:
    weights = np.array([0.1, 0.0], dtype=np.float32)
    symbols = ["BTCUSDT", "ETHUSDT"]
    signals = MetaLearner.rl_weights_to_signals(
        weights, symbols, current_weights={"BTCUSDT": 0.5, "ETHUSDT": 0.0}
    )
    btc = next(s for s in signals if s.symbol == "BTCUSDT")
    assert btc.action == TradeAction.SELL


def test_rl_weights_hold_within_deadband() -> None:
    weights = np.array([0.3, 0.3], dtype=np.float32)
    symbols = ["BTCUSDT", "ETHUSDT"]
    signals = MetaLearner.rl_weights_to_signals(
        weights, symbols,
        current_weights={"BTCUSDT": 0.295, "ETHUSDT": 0.295},
        weight_delta_threshold=0.01,
    )
    for sig in signals:
        assert sig.action == TradeAction.HOLD


def test_rl_weights_normalise_over_one() -> None:
    weights = np.array([0.8, 0.8], dtype=np.float32)
    signals = MetaLearner.rl_weights_to_signals(weights, ["BTCUSDT", "ETHUSDT"])
    # After normalisation each is 0.4 — both above 0, both from 0 → BUY
    for sig in signals:
        assert sig.action == TradeAction.BUY
        assert sig.source == SignalSource.RL


# ── genome_to_signals conversion ─────────────────────────────────────────────


def test_genome_buy_signal_rsi_oversold() -> None:
    sig = MetaLearner.genome_to_signals(
        rsi_value=25.0,
        macd_histogram=0.5,
        genome_rsi_oversold=30.0,
        genome_rsi_overbought=70.0,
        symbol="BTCUSDT",
    )
    assert sig.action == TradeAction.BUY
    assert sig.confidence > 0
    assert sig.source == SignalSource.EVOLVED


def test_genome_buy_requires_positive_macd() -> None:
    """RSI oversold but negative MACD → HOLD (no entry confirmation)."""
    sig = MetaLearner.genome_to_signals(
        rsi_value=25.0,
        macd_histogram=-0.5,
        genome_rsi_oversold=30.0,
        genome_rsi_overbought=70.0,
        symbol="BTCUSDT",
    )
    assert sig.action == TradeAction.HOLD


def test_genome_sell_signal_rsi_overbought() -> None:
    sig = MetaLearner.genome_to_signals(
        rsi_value=78.0,
        macd_histogram=-0.1,
        genome_rsi_oversold=30.0,
        genome_rsi_overbought=70.0,
        symbol="BTCUSDT",
    )
    assert sig.action == TradeAction.SELL
    assert sig.confidence > 0


def test_genome_hold_neutral_rsi() -> None:
    sig = MetaLearner.genome_to_signals(
        rsi_value=50.0,
        macd_histogram=0.1,
        genome_rsi_oversold=30.0,
        genome_rsi_overbought=70.0,
        symbol="BTCUSDT",
    )
    assert sig.action == TradeAction.HOLD
    assert sig.confidence == 0.0


# ── regime_to_signals conversion ─────────────────────────────────────────────


def test_regime_trending_returns_buy() -> None:
    from agent.strategies.regime.labeler import RegimeType

    sig = MetaLearner.regime_to_signals(RegimeType.TRENDING, 0.85, "BTCUSDT")
    assert sig.action == TradeAction.BUY
    assert sig.confidence == 0.85
    assert sig.source == SignalSource.REGIME


def test_regime_high_volatility_returns_sell() -> None:
    from agent.strategies.regime.labeler import RegimeType

    sig = MetaLearner.regime_to_signals(RegimeType.HIGH_VOLATILITY, 0.75, "BTCUSDT")
    assert sig.action == TradeAction.SELL
    assert sig.confidence == 0.75


def test_regime_mean_reverting_returns_hold_zero_confidence() -> None:
    from agent.strategies.regime.labeler import RegimeType

    sig = MetaLearner.regime_to_signals(RegimeType.MEAN_REVERTING, 0.9, "BTCUSDT")
    assert sig.action == TradeAction.HOLD
    # HOLD regime emits confidence=0 so it doesn't skew the vote
    assert sig.confidence == 0.0


def test_regime_low_volatility_returns_buy() -> None:
    from agent.strategies.regime.labeler import RegimeType

    sig = MetaLearner.regime_to_signals(RegimeType.LOW_VOLATILITY, 0.8, "BTCUSDT")
    assert sig.action == TradeAction.BUY
    assert sig.confidence == 0.8


# ── Full integration: all three sources together ──────────────────────────────


def test_full_pipeline_all_buy() -> None:
    """All three sources agree on BUY with high confidence → BUY output."""
    from agent.strategies.regime.labeler import RegimeType

    ml = MetaLearner()

    rl_sigs = MetaLearner.rl_weights_to_signals(
        np.array([0.5], dtype=np.float32),
        ["BTCUSDT"],
        current_weights={"BTCUSDT": 0.0},
    )
    genome_sig = MetaLearner.genome_to_signals(
        rsi_value=22.0,
        macd_histogram=1.0,
        genome_rsi_oversold=30.0,
        genome_rsi_overbought=70.0,
        symbol="BTCUSDT",
    )
    regime_sig = MetaLearner.regime_to_signals(RegimeType.TRENDING, 0.9, "BTCUSDT")

    all_signals = rl_sigs + [genome_sig, regime_sig]
    result = ml.combine(all_signals)

    assert result.action == TradeAction.BUY
    assert result.combined_confidence > 0.8
    assert result.agreement_rate == 1.0
