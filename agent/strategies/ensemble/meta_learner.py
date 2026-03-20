"""Meta-learner ensemble signal combiner.

Combines BUY / SELL / HOLD signals from up to three strategy sources
(RL, EVOLVED, REGIME) into a single ConsensusSignal using per-source
weights and a confidence threshold.

Voting algorithm
----------------
For each symbol:
1. Group all WeightedSignal instances by symbol.
2. Compute a weighted vote score per action:
       score(action) = sum(signal.confidence * weight[source])
       for all signals where signal.action == action
3. The action with the highest score wins.
4. combined_confidence = winning_score / total_active_weight  (normalised).
5. If combined_confidence < confidence_threshold → override to HOLD.
6. If every active source disagrees (all different actions, no majority)
   → HOLD.

Signal conversion helpers
--------------------------
Three static helper methods translate source-specific outputs into
WeightedSignal instances so callers do not need to know the action mapping:

- ``rl_weights_to_signals``   — PPO portfolio weight array → BUY/SELL/HOLD
- ``genome_to_signals``       — StrategyGenome RSI/MACD state → BUY/SELL/HOLD
- ``regime_to_signals``       — RegimeType → BUY/SELL/HOLD
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from agent.strategies.ensemble.signals import ConsensusSignal, SignalSource, TradeAction, WeightedSignal

if TYPE_CHECKING:
    pass

# Import lazily at module level to avoid a hard dependency on the regime
# package when the ensemble is imported without the regime extra installed.
# The dict is populated on first use of regime_to_signals().
_REGIME_ACTION_MAP: dict[Any, TradeAction] | None = None


def _get_regime_action_map() -> dict[Any, TradeAction]:
    """Return the module-level regime-to-action mapping, building it on first call.

    Returns:
        Dict mapping ``RegimeType`` values to ``TradeAction`` values.
    """
    global _REGIME_ACTION_MAP
    if _REGIME_ACTION_MAP is None:
        from agent.strategies.regime.labeler import RegimeType  # noqa: PLC0415

        _REGIME_ACTION_MAP = {
            RegimeType.TRENDING: TradeAction.BUY,
            RegimeType.MEAN_REVERTING: TradeAction.HOLD,
            RegimeType.HIGH_VOLATILITY: TradeAction.SELL,
            RegimeType.LOW_VOLATILITY: TradeAction.BUY,
        }
    return _REGIME_ACTION_MAP

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Default confidence threshold: the combined weighted confidence must exceed
# this value before a BUY or SELL is emitted.  Below this, HOLD is returned.
# 0.6 provides a balance between acting on moderate agreement and filtering
# out noisy or split signals.
_DEFAULT_CONFIDENCE_THRESHOLD: float = 0.6

# Minimum fraction of active sources that must share the winning action for
# the signal to be considered valid.  0.5 means at least half of the active
# sources must agree; otherwise HOLD is returned.
_DEFAULT_MIN_AGREEMENT_RATE: float = 0.5

# Numeric encoding used internally for the voting accumulator.
# HOLD = 0 so it contributes neither positive nor negative pressure.
_ACTION_SCORE: dict[TradeAction, float] = {
    TradeAction.BUY: 1.0,
    TradeAction.SELL: -1.0,
    TradeAction.HOLD: 0.0,
}


# ── MetaLearner ───────────────────────────────────────────────────────────────


class MetaLearner:
    """Weighted ensemble combiner for RL, EVOLVED, and REGIME signals.

    Args:
        weights: Per-source weight mapping.  Keys must be ``SignalSource``
            members; values are non-negative floats.  The weights are
            normalised to sum to 1.0 on construction.  Defaults to equal
            weights across all three sources if ``None``.
        confidence_threshold: Minimum combined confidence required to act.
            Signals below this threshold are overridden to HOLD.  Default
            :data:`_DEFAULT_CONFIDENCE_THRESHOLD` (0.6).
        min_agreement_rate: Minimum fraction of active sources that must
            agree with the winning action.  Default
            :data:`_DEFAULT_MIN_AGREEMENT_RATE` (0.5).
    """

    def __init__(
        self,
        weights: dict[SignalSource, float] | None = None,
        confidence_threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
        min_agreement_rate: float = _DEFAULT_MIN_AGREEMENT_RATE,
    ) -> None:
        if weights is None:
            weights = {s: 1.0 for s in SignalSource}

        # Normalise weights so they sum to 1.0.
        total = sum(weights.values())
        if total <= 0:
            raise ValueError("Sum of source weights must be positive.")
        self._weights: dict[SignalSource, float] = {
            source: w / total for source, w in weights.items()
        }

        self._confidence_threshold = confidence_threshold
        self._min_agreement_rate = min_agreement_rate

        log.debug(
            "meta_learner.initialised",
            weights={s.value: round(w, 4) for s, w in self._weights.items()},
            confidence_threshold=confidence_threshold,
            min_agreement_rate=min_agreement_rate,
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def confidence_threshold(self) -> float:
        """Minimum combined confidence required to emit a non-HOLD action."""
        return self._confidence_threshold

    @property
    def min_agreement_rate(self) -> float:
        """Minimum fraction of active sources that must agree with the winner."""
        return self._min_agreement_rate

    # ── Core combination logic ────────────────────────────────────────────────

    def combine(self, signals: list[WeightedSignal]) -> ConsensusSignal:
        """Combine a list of weighted signals into a single consensus signal.

        Signals are grouped by symbol.  If signals for more than one symbol
        are provided, only the first symbol encountered (alphabetically sorted)
        is processed.  Use :meth:`combine_all` for multi-symbol batches.

        Args:
            signals: Signals from any combination of sources.  Missing
                sources are treated as HOLD with confidence 0.

        Returns:
            A :class:`ConsensusSignal` for the symbol.

        Raises:
            ValueError: If ``signals`` is empty.
        """
        if not signals:
            raise ValueError("signals list must not be empty.")

        # Use the symbol from the first signal; validate all match.
        symbol = signals[0].symbol
        for sig in signals:
            if sig.symbol != symbol:
                raise ValueError(
                    f"combine() received signals for multiple symbols "
                    f"({symbol!r} and {sig.symbol!r}).  "
                    "Use combine_all() for multi-symbol inputs."
                )

        return self._combine_for_symbol(symbol, signals)

    def combine_all(self, signals: list[WeightedSignal]) -> list[ConsensusSignal]:
        """Combine signals for multiple symbols in one call.

        Args:
            signals: Mixed list of signals, potentially covering several
                trading pairs.

        Returns:
            One :class:`ConsensusSignal` per unique symbol, sorted
            alphabetically by symbol.
        """
        by_symbol: dict[str, list[WeightedSignal]] = {}
        for sig in signals:
            by_symbol.setdefault(sig.symbol, []).append(sig)

        return [self._combine_for_symbol(sym, sigs) for sym, sigs in sorted(by_symbol.items())]

    def _combine_for_symbol(
        self,
        symbol: str,
        signals: list[WeightedSignal],
    ) -> ConsensusSignal:
        """Internal: compute the consensus for a single symbol.

        Args:
            symbol: The trading pair.
            signals: All signals for this symbol.

        Returns:
            :class:`ConsensusSignal` for the symbol.
        """
        # Accumulate weighted vote score and confidence per action.
        buy_score: float = 0.0
        sell_score: float = 0.0
        total_active_weight: float = 0.0

        for sig in signals:
            w = self._weights.get(sig.source, 0.0)
            weighted_conf = sig.confidence * w
            total_active_weight += weighted_conf

            if sig.action == TradeAction.BUY:
                buy_score += weighted_conf
            elif sig.action == TradeAction.SELL:
                sell_score += weighted_conf
            # HOLD signals contribute weight but no directional score.

        # Determine the winning action and normalised combined confidence.
        if total_active_weight <= 0:
            # All sources are offline (confidence = 0).
            return ConsensusSignal(
                symbol=symbol,
                action=TradeAction.HOLD,
                combined_confidence=0.0,
                contributing_signals=signals,
                agreement_rate=0.0,
            )

        if buy_score > sell_score:
            winning_action = TradeAction.BUY
            winning_score = buy_score
        elif sell_score > buy_score:
            winning_action = TradeAction.SELL
            winning_score = sell_score
        else:
            # Perfect tie → HOLD.
            winning_action = TradeAction.HOLD
            winning_score = 0.0

        combined_confidence = min(winning_score / total_active_weight, 1.0) if winning_score > 0 else 0.0

        # Compute agreement rate and apply guards.
        rate = self.agreement_rate(signals)
        final_action = winning_action

        if combined_confidence < self._confidence_threshold:
            log.debug(
                "meta_learner.hold_low_confidence",
                symbol=symbol,
                combined_confidence=round(combined_confidence, 4),
                threshold=self._confidence_threshold,
            )
            final_action = TradeAction.HOLD

        elif rate < self._min_agreement_rate:
            log.debug(
                "meta_learner.hold_low_agreement",
                symbol=symbol,
                agreement_rate=round(rate, 4),
                min_agreement_rate=self._min_agreement_rate,
            )
            final_action = TradeAction.HOLD

        log.debug(
            "meta_learner.consensus",
            symbol=symbol,
            action=final_action.value,
            combined_confidence=round(combined_confidence, 4),
            agreement_rate=round(rate, 4),
        )

        return ConsensusSignal(
            symbol=symbol,
            action=final_action,
            combined_confidence=round(combined_confidence, 4),
            contributing_signals=signals,
            agreement_rate=round(rate, 4),
        )

    # ── Agreement rate ────────────────────────────────────────────────────────

    def agreement_rate(self, signals: list[WeightedSignal]) -> float:
        """Fraction of active sources that agree with the plurality action.

        An "active" source is one whose signal has confidence > 0.  A source
        with confidence == 0 is considered offline and excluded from the
        denominator.  HOLD signals are counted as active (a deliberate no-op
        is a valid opinion).

        Args:
            signals: Signals for a single symbol.

        Returns:
            Float in [0, 1].  Returns 0.0 if there are no active signals.
        """
        active = [s for s in signals if s.confidence > 0]
        if not active:
            return 0.0

        # Count actions among active signals.
        counts: dict[TradeAction, int] = {}
        for sig in active:
            counts[sig.action] = counts.get(sig.action, 0) + 1

        plurality_count = max(counts.values())
        return round(plurality_count / len(active), 4)

    # ── Signal conversion helpers ─────────────────────────────────────────────

    @staticmethod
    def rl_weights_to_signals(
        target_weights: Any,
        symbols: list[str],
        current_weights: dict[str, float] | None = None,
        weight_delta_threshold: float = 0.01,
    ) -> list[WeightedSignal]:
        """Convert PPO portfolio weights to WeightedSignal instances.

        A weight significantly above the current holding → BUY.
        A weight significantly below the current holding → SELL.
        Within the dead-band → HOLD.

        The confidence for each signal is the absolute normalised weight
        delta clamped to [0, 1], giving stronger signals more influence.

        Args:
            target_weights: Float32 numpy array of shape ``(n_assets,)`` from
                ``model.predict()``.  Values are clamped to [0, 1] and
                normalised to sum <= 1.0 before comparison.
            symbols: Asset symbols in the same order as ``target_weights``.
            current_weights: Symbol → current portfolio weight dict.  If
                ``None``, all current weights are assumed to be 0 (flat
                portfolio, i.e. every non-zero target weight → BUY).
            weight_delta_threshold: Minimum absolute weight delta to register
                as a directional signal.  Smaller deltas → HOLD.

        Returns:
            One WeightedSignal per symbol.
        """
        import numpy as np  # noqa: PLC0415

        weights = np.clip(target_weights, 0.0, 1.0).astype(float)
        total_w = float(weights.sum())
        if total_w > 1.0:
            weights = weights / total_w

        if current_weights is None:
            current_weights = {}

        signals: list[WeightedSignal] = []
        for i, symbol in enumerate(symbols):
            target = float(weights[i])
            current = current_weights.get(symbol, 0.0)
            delta = target - current
            abs_delta = abs(delta)

            if abs_delta < weight_delta_threshold:
                action = TradeAction.HOLD
                confidence = 0.0
            elif delta > 0:
                action = TradeAction.BUY
                confidence = min(abs_delta, 1.0)
            else:
                action = TradeAction.SELL
                confidence = min(abs_delta, 1.0)

            signals.append(
                WeightedSignal(
                    source=SignalSource.RL,
                    symbol=symbol,
                    action=action,
                    confidence=confidence,
                    metadata={
                        "target_weight": round(target, 6),
                        "current_weight": round(current, 6),
                        "weight_delta": round(delta, 6),
                    },
                )
            )

        return signals

    @staticmethod
    def genome_to_signals(
        rsi_value: float,
        macd_histogram: float,
        genome_rsi_oversold: float,
        genome_rsi_overbought: float,
        symbol: str,
    ) -> WeightedSignal:
        """Convert StrategyGenome RSI/MACD conditions to a WeightedSignal.

        Entry rule (BUY):  RSI < rsi_oversold  AND  macd_histogram > 0
        Exit rule (SELL):  RSI > rsi_overbought
        Default:           HOLD

        Confidence is proportional to how far the indicator is from the
        threshold, scaled to [0, 1] using a 20-point normalisation range.

        Args:
            rsi_value: Current RSI indicator value (0–100).
            macd_histogram: Current MACD histogram value (positive = bullish).
            genome_rsi_oversold: RSI threshold below which BUY is triggered.
                Read from ``StrategyGenome.rsi_oversold``.
            genome_rsi_overbought: RSI threshold above which SELL is triggered.
                Read from ``StrategyGenome.rsi_overbought``.
            symbol: Trading pair this signal applies to.

        Returns:
            One WeightedSignal for the symbol.
        """
        _NORM_RANGE = 20.0  # RSI points used as normalisation denominator

        if rsi_value < genome_rsi_oversold and macd_histogram > 0:
            distance = genome_rsi_oversold - rsi_value
            confidence = min(distance / _NORM_RANGE, 1.0)
            action = TradeAction.BUY
        elif rsi_value > genome_rsi_overbought:
            distance = rsi_value - genome_rsi_overbought
            confidence = min(distance / _NORM_RANGE, 1.0)
            action = TradeAction.SELL
        else:
            action = TradeAction.HOLD
            confidence = 0.0

        return WeightedSignal(
            source=SignalSource.EVOLVED,
            symbol=symbol,
            action=action,
            confidence=confidence,
            metadata={
                "rsi": round(rsi_value, 2),
                "macd_histogram": round(macd_histogram, 6),
                "rsi_oversold": genome_rsi_oversold,
                "rsi_overbought": genome_rsi_overbought,
            },
        )

    @staticmethod
    def regime_to_signals(
        regime_type: Any,
        regime_confidence: float,
        symbol: str,
    ) -> WeightedSignal:
        """Convert a RegimeSwitcher output to a WeightedSignal.

        Regime bias mapping:
            TRENDING        → BUY   (trend-following: lean long)
            MEAN_REVERTING  → HOLD  (no structural directional bias)
            HIGH_VOLATILITY → SELL  (risk-off: reduce exposure)
            LOW_VOLATILITY  → BUY   (accumulate in calm markets)

        The regime confidence from the classifier is passed through directly
        as the signal confidence.

        Args:
            regime_type: A ``RegimeType`` enum value from
                ``agent.strategies.regime.labeler``.
            regime_confidence: Classifier probability for the regime (0–1).
            symbol: Trading pair this signal applies to.

        Returns:
            One WeightedSignal for the symbol.
        """
        action = _get_regime_action_map().get(regime_type, TradeAction.HOLD)
        # HOLD regime contributes no directional confidence.
        confidence = regime_confidence if action != TradeAction.HOLD else 0.0

        return WeightedSignal(
            source=SignalSource.REGIME,
            symbol=symbol,
            action=action,
            confidence=confidence,
            metadata={"regime": regime_type.value, "regime_confidence": round(regime_confidence, 4)},
        )
