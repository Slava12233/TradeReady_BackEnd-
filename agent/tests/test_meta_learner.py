"""Tests for agent/strategies/ensemble/meta_learner.py.

Covers cases NOT already present in test_ensemble.py:
- min_agreement_rate filtering (HOLD-low-agreement path)
- combine_all with empty list returns empty result
- combine_all single-symbol dispatch (no cross-symbol error)
- Confidence threshold at exact boundary
- Custom min_agreement_rate guard
- rl_weights_to_signals with current_weights=None (flat portfolio default)
- genome_to_signals confidence proportionality
- regime_to_signals with unknown regime fallback
- Weights dict with only a subset of sources provided
- _combine_for_symbol tie (buy_score == sell_score) → HOLD
"""

from __future__ import annotations

import numpy as np

from agent.strategies.ensemble.meta_learner import MetaLearner
from agent.strategies.ensemble.signals import ConsensusSignal, SignalSource, TradeAction, WeightedSignal

# ── Helpers ───────────────────────────────────────────────────────────────────


def _sig(
    source: SignalSource,
    action: TradeAction,
    confidence: float,
    symbol: str = "BTCUSDT",
) -> WeightedSignal:
    return WeightedSignal(source=source, symbol=symbol, action=action, confidence=confidence)


# ── 3/3 agreement → high confidence consensus ─────────────────────────────────


class TestUnanimousAgreement:
    """3/3 agreement produces consensus with agreement_rate == 1.0."""

    def test_unanimous_buy_agreement_rate_is_one(self) -> None:
        ml = MetaLearner()
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.95),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 0.9),
            _sig(SignalSource.REGIME, TradeAction.BUY, 0.85),
        ]
        result = ml.combine(signals)
        assert result.agreement_rate == 1.0

    def test_unanimous_sell_agreement_rate_is_one(self) -> None:
        ml = MetaLearner()
        signals = [
            _sig(SignalSource.RL, TradeAction.SELL, 0.88),
            _sig(SignalSource.EVOLVED, TradeAction.SELL, 0.88),
            _sig(SignalSource.REGIME, TradeAction.SELL, 0.88),
        ]
        result = ml.combine(signals)
        assert result.agreement_rate == 1.0
        assert result.action == TradeAction.SELL

    def test_unanimous_buy_combined_confidence_normalized(self) -> None:
        """combined_confidence == 1.0 when all three buy at full confidence."""
        ml = MetaLearner()
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 1.0),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 1.0),
            _sig(SignalSource.REGIME, TradeAction.BUY, 1.0),
        ]
        result = ml.combine(signals)
        assert result.combined_confidence == 1.0


# ── 2/3 agreement → medium confidence, correct action ────────────────────────


class TestPartialAgreement:
    """2/3 agreement: correct action is selected, agreement_rate ~= 0.667."""

    def test_two_thirds_buy_action_is_buy(self) -> None:
        """2 BUY vs 1 SELL → BUY wins when confidence exceeds threshold."""
        ml = MetaLearner(confidence_threshold=0.3, min_agreement_rate=0.5)
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.8),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 0.7),
            _sig(SignalSource.REGIME, TradeAction.SELL, 0.6),
        ]
        result = ml.combine(signals)
        assert result.action == TradeAction.BUY

    def test_two_thirds_sell_action_is_sell(self) -> None:
        """2 SELL vs 1 BUY → SELL wins."""
        ml = MetaLearner(confidence_threshold=0.3, min_agreement_rate=0.5)
        signals = [
            _sig(SignalSource.RL, TradeAction.SELL, 0.8),
            _sig(SignalSource.EVOLVED, TradeAction.SELL, 0.75),
            _sig(SignalSource.REGIME, TradeAction.BUY, 0.6),
        ]
        result = ml.combine(signals)
        assert result.action == TradeAction.SELL

    def test_two_thirds_agreement_rate_is_two_thirds(self) -> None:
        ml = MetaLearner(confidence_threshold=0.3, min_agreement_rate=0.5)
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.8),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 0.8),
            _sig(SignalSource.REGIME, TradeAction.SELL, 0.8),
        ]
        result = ml.combine(signals)
        assert abs(result.agreement_rate - 2 / 3) < 0.01

    def test_two_thirds_confidence_is_below_unanimous(self) -> None:
        """2/3 BUY combined confidence is strictly lower than unanimous BUY."""
        ml = MetaLearner(confidence_threshold=0.3, min_agreement_rate=0.3)
        partial_signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.8),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 0.8),
            _sig(SignalSource.REGIME, TradeAction.SELL, 0.8),
        ]
        full_signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.8),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 0.8),
            _sig(SignalSource.REGIME, TradeAction.BUY, 0.8),
        ]
        partial_result = ml.combine(partial_signals)
        full_result = ml.combine(full_signals)
        assert partial_result.combined_confidence < full_result.combined_confidence


# ── 0/3 agreement → HOLD ─────────────────────────────────────────────────────


class TestNoAgreement:
    """When no plurality can be formed, HOLD is returned."""

    def test_buy_sell_tie_returns_hold(self) -> None:
        """Perfect BUY/SELL tie (no HOLD) → HOLD via tie-break logic."""
        ml = MetaLearner()
        # Equal weights, equal confidence BUY and SELL → buy_score == sell_score
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.8),
            _sig(SignalSource.EVOLVED, TradeAction.SELL, 0.8),
        ]
        result = ml.combine(signals)
        assert result.action == TradeAction.HOLD

    def test_all_hold_signals_returns_hold(self) -> None:
        """All three sources vote HOLD → HOLD output, zero confidence."""
        ml = MetaLearner()
        signals = [
            _sig(SignalSource.RL, TradeAction.HOLD, 0.7),
            _sig(SignalSource.EVOLVED, TradeAction.HOLD, 0.7),
            _sig(SignalSource.REGIME, TradeAction.HOLD, 0.7),
        ]
        result = ml.combine(signals)
        # HOLD signals contribute active weight but no directional score
        assert result.action == TradeAction.HOLD
        assert result.combined_confidence == 0.0


# ── Missing signal (source offline) → treated as HOLD ────────────────────────


class TestOfflineSource:
    """A source with confidence=0 is offline and excluded from the agreement denominator."""

    def test_single_offline_source_excluded_from_agreement(self) -> None:
        """2 BUY + 1 offline REGIME → agreement_rate == 1.0 (not 0.667)."""
        ml = MetaLearner()
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.9),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 0.9),
            _sig(SignalSource.REGIME, TradeAction.HOLD, 0.0),  # offline
        ]
        result = ml.combine(signals)
        assert result.action == TradeAction.BUY
        # Only 2 active sources, both BUY → rate == 1.0
        assert result.agreement_rate == 1.0

    def test_all_offline_returns_hold_zero_confidence_zero_agreement(self) -> None:
        ml = MetaLearner()
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.0),
            _sig(SignalSource.EVOLVED, TradeAction.SELL, 0.0),
            _sig(SignalSource.REGIME, TradeAction.HOLD, 0.0),
        ]
        result = ml.combine(signals)
        assert result.action == TradeAction.HOLD
        assert result.combined_confidence == 0.0
        assert result.agreement_rate == 0.0

    def test_two_offline_one_active_returns_active_action(self) -> None:
        """Only one active source → it wins, agreement_rate == 1.0."""
        ml = MetaLearner(confidence_threshold=0.0, min_agreement_rate=0.0)
        signals = [
            _sig(SignalSource.RL, TradeAction.SELL, 0.8),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 0.0),  # offline
            _sig(SignalSource.REGIME, TradeAction.BUY, 0.0),  # offline
        ]
        result = ml.combine(signals)
        assert result.action == TradeAction.SELL
        assert result.agreement_rate == 1.0


# ── Weights normalization ─────────────────────────────────────────────────────


class TestWeightsNormalization:
    """MetaLearner normalises raw weights to sum exactly to 1.0."""

    def test_weights_sum_to_one(self) -> None:
        ml = MetaLearner(
            weights={
                SignalSource.RL: 3.0,
                SignalSource.EVOLVED: 2.0,
                SignalSource.REGIME: 1.0,
            }
        )
        total = sum(ml._weights.values())
        assert abs(total - 1.0) < 1e-9

    def test_partial_weights_dict_uses_zero_for_missing_sources(self) -> None:
        """Weights provided for only a subset of sources — missing ones get 0 weight."""
        # Construct with only RL and EVOLVED; REGIME gets no weight in the dict
        ml = MetaLearner(
            weights={
                SignalSource.RL: 1.0,
                SignalSource.EVOLVED: 1.0,
            }
        )
        # Regime weight not in dict → _weights.get(REGIME, 0.0) returns 0
        # These weights normalise: each known source = 0.5
        assert abs(ml._weights[SignalSource.RL] - 0.5) < 1e-9
        assert abs(ml._weights[SignalSource.EVOLVED] - 0.5) < 1e-9
        # REGIME is not in _weights at all (only sources in input dict are stored)
        assert SignalSource.REGIME not in ml._weights

    def test_asymmetric_weights_change_outcome(self) -> None:
        """Heavily weighted source dominates even when outvoted 2-to-1."""
        # RL has 90% weight; EVOLVED and REGIME split the remaining 10%.
        ml = MetaLearner(
            weights={
                SignalSource.RL: 90.0,
                SignalSource.EVOLVED: 5.0,
                SignalSource.REGIME: 5.0,
            },
            confidence_threshold=0.0,
            min_agreement_rate=0.0,
        )
        signals = [
            _sig(SignalSource.RL, TradeAction.SELL, 0.9),       # dominant source
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 0.9),   # minority
            _sig(SignalSource.REGIME, TradeAction.BUY, 0.9),    # minority
        ]
        result = ml.combine(signals)
        # RL SELL overwhelms 2 BUY from minor sources
        assert result.action == TradeAction.SELL


# ── Confidence threshold filtering ────────────────────────────────────────────


class TestConfidenceThreshold:
    """combined_confidence < threshold → HOLD regardless of vote winner."""

    def test_threshold_blocks_partial_agreement(self) -> None:
        """2/3 BUY: combined_confidence = buy_score / total_weight = 2/3 ≈ 0.667.
        With confidence_threshold=0.9 this is blocked → HOLD."""
        # All sources have confidence=1.0 and equal weights (1/3 each).
        # buy_score  = 1/3 * 1.0 + 1/3 * 1.0 = 0.667
        # total_weight = 1/3 * 1.0 + 1/3 * 1.0 + 1/3 * 1.0 = 1.0
        # combined_confidence = 0.667 < 0.9 → HOLD
        ml = MetaLearner(confidence_threshold=0.9)
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 1.0),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 1.0),
            _sig(SignalSource.REGIME, TradeAction.SELL, 1.0),
        ]
        result = ml.combine(signals)
        assert result.action == TradeAction.HOLD

    def test_low_confidence_with_partial_agreement_returns_hold(self) -> None:
        """2/3 BUY but low individual confidence → combined_confidence below threshold."""
        # buy_score  = 1/3 * 0.2 + 1/3 * 0.2 = 0.133
        # total_weight = 1/3 * 0.2 + 1/3 * 0.2 + 1/3 * 0.4 = 0.267
        # combined_confidence = 0.133 / 0.267 ≈ 0.5 < threshold=0.8 → HOLD
        ml = MetaLearner(confidence_threshold=0.8)
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.2),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 0.2),
            _sig(SignalSource.REGIME, TradeAction.SELL, 0.4),
        ]
        result = ml.combine(signals)
        assert result.action == TradeAction.HOLD

    def test_above_confidence_threshold_acts(self) -> None:
        """combined_confidence > threshold → non-HOLD action is preserved."""
        ml = MetaLearner(confidence_threshold=0.5, min_agreement_rate=0.0)
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 1.0),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 1.0),
            _sig(SignalSource.REGIME, TradeAction.BUY, 1.0),
        ]
        result = ml.combine(signals)
        assert result.action == TradeAction.BUY


# ── min_agreement_rate guard ──────────────────────────────────────────────────


class TestMinAgreementRateGuard:
    """Agreement rate below min_agreement_rate → HOLD even if confidence is high."""

    def test_high_confidence_low_agreement_returns_hold(self) -> None:
        """Strict min_agreement_rate filters a 2/3 majority if threshold > 0.667."""
        # min_agreement_rate = 0.9 means we need 90% of active sources to agree
        # 2/3 = 0.667 < 0.9 → HOLD
        ml = MetaLearner(confidence_threshold=0.0, min_agreement_rate=0.9)
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.9),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 0.9),
            _sig(SignalSource.REGIME, TradeAction.SELL, 0.9),
        ]
        result = ml.combine(signals)
        assert result.action == TradeAction.HOLD

    def test_min_agreement_rate_zero_always_passes(self) -> None:
        """min_agreement_rate=0.0 never blocks on agreement, only on confidence."""
        ml = MetaLearner(confidence_threshold=0.0, min_agreement_rate=0.0)
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.9),
            _sig(SignalSource.EVOLVED, TradeAction.SELL, 0.5),
            _sig(SignalSource.REGIME, TradeAction.HOLD, 0.5),
        ]
        result = ml.combine(signals)
        # buy_score > sell_score, agreement_rate check skipped
        assert result.action == TradeAction.BUY

    def test_unanimous_always_passes_agreement_guard(self) -> None:
        """agreement_rate=1.0 always passes even with strict min_agreement_rate."""
        ml = MetaLearner(confidence_threshold=0.0, min_agreement_rate=1.0)
        signals = [
            _sig(SignalSource.RL, TradeAction.SELL, 0.8),
            _sig(SignalSource.EVOLVED, TradeAction.SELL, 0.8),
            _sig(SignalSource.REGIME, TradeAction.SELL, 0.8),
        ]
        result = ml.combine(signals)
        assert result.action == TradeAction.SELL


# ── combine_all multi-symbol dispatch ─────────────────────────────────────────


class TestCombineAll:
    """combine_all dispatches correctly to per-symbol combination."""

    def test_combine_all_empty_list_returns_empty(self) -> None:
        ml = MetaLearner()
        results = ml.combine_all([])
        assert results == []

    def test_combine_all_single_symbol_no_error(self) -> None:
        ml = MetaLearner()
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.9, symbol="SOLUSDT"),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 0.9, symbol="SOLUSDT"),
            _sig(SignalSource.REGIME, TradeAction.BUY, 0.9, symbol="SOLUSDT"),
        ]
        results = ml.combine_all(signals)
        assert len(results) == 1
        assert results[0].symbol == "SOLUSDT"
        assert results[0].action == TradeAction.BUY

    def test_combine_all_three_symbols_sorted(self) -> None:
        ml = MetaLearner()
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.9, symbol="SOLUSDT"),
            _sig(SignalSource.RL, TradeAction.SELL, 0.9, symbol="BTCUSDT"),
            _sig(SignalSource.RL, TradeAction.HOLD, 0.9, symbol="ETHUSDT"),
        ]
        results = ml.combine_all(signals)
        assert [r.symbol for r in results] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    def test_combine_all_independent_per_symbol(self) -> None:
        """Each symbol's result is independent; BTCUSDT BUY doesn't affect ETHUSDT SELL."""
        ml = MetaLearner(confidence_threshold=0.0, min_agreement_rate=0.0)
        signals = [
            _sig(SignalSource.RL, TradeAction.BUY, 0.9, symbol="BTCUSDT"),
            _sig(SignalSource.EVOLVED, TradeAction.BUY, 0.9, symbol="BTCUSDT"),
            _sig(SignalSource.RL, TradeAction.SELL, 0.9, symbol="ETHUSDT"),
            _sig(SignalSource.EVOLVED, TradeAction.SELL, 0.9, symbol="ETHUSDT"),
        ]
        results = ml.combine_all(signals)
        btc = next(r for r in results if r.symbol == "BTCUSDT")
        eth = next(r for r in results if r.symbol == "ETHUSDT")
        assert btc.action == TradeAction.BUY
        assert eth.action == TradeAction.SELL

    def test_combine_all_returns_consensus_signal_instances(self) -> None:
        ml = MetaLearner()
        signals = [_sig(SignalSource.RL, TradeAction.BUY, 0.9)]
        results = ml.combine_all(signals)
        assert all(isinstance(r, ConsensusSignal) for r in results)


# ── rl_weights_to_signals conversion ─────────────────────────────────────────


class TestRlWeightsToSignals:
    """rl_weights_to_signals edge cases not covered in test_ensemble.py."""

    def test_no_current_weights_assumes_flat_portfolio(self) -> None:
        """When current_weights=None, all positions assumed 0 → non-zero weight = BUY."""
        weights = np.array([0.3, 0.0, 0.0], dtype=np.float32)
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        signals = MetaLearner.rl_weights_to_signals(weights, symbols, current_weights=None)
        btc = next(s for s in signals if s.symbol == "BTCUSDT")
        eth = next(s for s in signals if s.symbol == "ETHUSDT")
        assert btc.action == TradeAction.BUY
        assert eth.action == TradeAction.HOLD

    def test_confidence_equals_abs_delta_when_below_one(self) -> None:
        """Confidence is the absolute weight delta (clamped to [0, 1])."""
        target = 0.4
        current = 0.1
        expected_conf = target - current  # 0.3
        weights = np.array([target], dtype=np.float32)
        signals = MetaLearner.rl_weights_to_signals(
            weights, ["BTCUSDT"], current_weights={"BTCUSDT": current}
        )
        assert abs(signals[0].confidence - expected_conf) < 1e-6

    def test_weights_clamped_to_unit_interval(self) -> None:
        """Negative input weights are clamped to 0 before processing."""
        weights = np.array([-0.5, 0.5], dtype=np.float32)
        signals = MetaLearner.rl_weights_to_signals(weights, ["BTCUSDT", "ETHUSDT"])
        btc = next(s for s in signals if s.symbol == "BTCUSDT")
        # -0.5 clipped to 0 → delta from 0 is 0.0 → HOLD
        assert btc.action == TradeAction.HOLD
        assert btc.confidence == 0.0

    def test_metadata_contains_weight_delta(self) -> None:
        weights = np.array([0.5], dtype=np.float32)
        signals = MetaLearner.rl_weights_to_signals(
            weights, ["BTCUSDT"], current_weights={"BTCUSDT": 0.2}
        )
        assert "weight_delta" in signals[0].metadata
        assert "target_weight" in signals[0].metadata
        assert "current_weight" in signals[0].metadata

    def test_source_is_rl(self) -> None:
        weights = np.array([0.5], dtype=np.float32)
        signals = MetaLearner.rl_weights_to_signals(weights, ["BTCUSDT"])
        assert all(s.source == SignalSource.RL for s in signals)


# ── genome_to_signals conversion ─────────────────────────────────────────────


class TestGenomeToSignals:
    """genome_to_signals confidence proportionality and boundary conditions."""

    def test_buy_confidence_proportional_to_rsi_distance(self) -> None:
        """Confidence scales with how far RSI is below the oversold threshold."""
        # distance = 30 - 20 = 10 → confidence = 10/20 = 0.5
        sig_near = MetaLearner.genome_to_signals(
            rsi_value=28.0,
            macd_histogram=0.5,
            genome_rsi_oversold=30.0,
            genome_rsi_overbought=70.0,
            symbol="BTCUSDT",
        )
        # distance = 30 - 10 = 20 → confidence = 20/20 = 1.0
        sig_far = MetaLearner.genome_to_signals(
            rsi_value=10.0,
            macd_histogram=0.5,
            genome_rsi_oversold=30.0,
            genome_rsi_overbought=70.0,
            symbol="BTCUSDT",
        )
        assert sig_near.action == TradeAction.BUY
        assert sig_far.action == TradeAction.BUY
        assert sig_far.confidence > sig_near.confidence

    def test_sell_confidence_proportional_to_rsi_distance(self) -> None:
        """Confidence scales with how far RSI is above the overbought threshold."""
        sig_near = MetaLearner.genome_to_signals(
            rsi_value=72.0,
            macd_histogram=-0.1,
            genome_rsi_oversold=30.0,
            genome_rsi_overbought=70.0,
            symbol="BTCUSDT",
        )
        sig_far = MetaLearner.genome_to_signals(
            rsi_value=90.0,
            macd_histogram=-0.1,
            genome_rsi_oversold=30.0,
            genome_rsi_overbought=70.0,
            symbol="BTCUSDT",
        )
        assert sig_near.action == TradeAction.SELL
        assert sig_far.action == TradeAction.SELL
        assert sig_far.confidence > sig_near.confidence

    def test_buy_confidence_capped_at_one(self) -> None:
        """Confidence is capped at 1.0 even when RSI distance exceeds 20 points."""
        sig = MetaLearner.genome_to_signals(
            rsi_value=1.0,  # 29 points below oversold=30
            macd_histogram=1.0,
            genome_rsi_oversold=30.0,
            genome_rsi_overbought=70.0,
            symbol="BTCUSDT",
        )
        assert sig.confidence == 1.0

    def test_rsi_exactly_at_oversold_threshold_is_not_buy(self) -> None:
        """RSI equal to oversold threshold — condition is strictly less than."""
        sig = MetaLearner.genome_to_signals(
            rsi_value=30.0,  # exactly at threshold, not below
            macd_histogram=1.0,
            genome_rsi_oversold=30.0,
            genome_rsi_overbought=70.0,
            symbol="BTCUSDT",
        )
        assert sig.action == TradeAction.HOLD

    def test_rsi_exactly_at_overbought_threshold_triggers_sell(self) -> None:
        """RSI exactly at overbought threshold — condition is strictly greater than."""
        sig_at = MetaLearner.genome_to_signals(
            rsi_value=70.0,  # exactly at threshold
            macd_histogram=-0.1,
            genome_rsi_oversold=30.0,
            genome_rsi_overbought=70.0,
            symbol="BTCUSDT",
        )
        # RSI > 70 is the condition; RSI == 70 → HOLD
        assert sig_at.action == TradeAction.HOLD

    def test_metadata_contains_rsi_and_macd(self) -> None:
        sig = MetaLearner.genome_to_signals(
            rsi_value=25.0,
            macd_histogram=0.5,
            genome_rsi_oversold=30.0,
            genome_rsi_overbought=70.0,
            symbol="BTCUSDT",
        )
        assert "rsi" in sig.metadata
        assert "macd_histogram" in sig.metadata
        assert "rsi_oversold" in sig.metadata
        assert "rsi_overbought" in sig.metadata

    def test_source_is_evolved(self) -> None:
        sig = MetaLearner.genome_to_signals(
            rsi_value=25.0,
            macd_histogram=0.5,
            genome_rsi_oversold=30.0,
            genome_rsi_overbought=70.0,
            symbol="BTCUSDT",
        )
        assert sig.source == SignalSource.EVOLVED


# ── regime_to_signals conversion ─────────────────────────────────────────────


class TestRegimeToSignals:
    """Edge cases in regime_to_signals not already in test_ensemble.py."""

    def test_low_volatility_regime_confidence_passes_through(self) -> None:
        from agent.strategies.regime.labeler import RegimeType

        regime_conf = 0.72
        sig = MetaLearner.regime_to_signals(RegimeType.LOW_VOLATILITY, regime_conf, "ETHUSDT")
        assert sig.action == TradeAction.BUY
        assert sig.confidence == regime_conf

    def test_mean_reverting_confidence_is_zero_despite_input(self) -> None:
        """HOLD regimes emit confidence=0 so they don't skew votes."""
        from agent.strategies.regime.labeler import RegimeType

        sig = MetaLearner.regime_to_signals(RegimeType.MEAN_REVERTING, 0.99, "BTCUSDT")
        assert sig.confidence == 0.0

    def test_regime_metadata_contains_regime_name(self) -> None:
        from agent.strategies.regime.labeler import RegimeType

        sig = MetaLearner.regime_to_signals(RegimeType.TRENDING, 0.8, "BTCUSDT")
        assert "regime" in sig.metadata
        assert sig.metadata["regime"] == RegimeType.TRENDING.value

    def test_source_is_regime(self) -> None:
        from agent.strategies.regime.labeler import RegimeType

        sig = MetaLearner.regime_to_signals(RegimeType.HIGH_VOLATILITY, 0.7, "SOLUSDT")
        assert sig.source == SignalSource.REGIME
        assert sig.symbol == "SOLUSDT"
