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

Dynamic weight adaptation
--------------------------
:meth:`update_weights` accepts a list of :class:`TradeOutcome` records from
recent trades and recomputes per-source weights using a rolling Sharpe ratio
over the last 50 outcomes.  Regime-conditional modifiers are then applied on
top:

- TRENDING:        RL +30 %, EVOLVED −10 %
- MEAN_REVERTING:  EVOLVED +30 %, RL −10 %
- HIGH_VOLATILITY: all sizes −50 % across the board, REGIME +20 %
- LOW_VOLATILITY:  RL +20 %

After adjustment the weights are normalised to sum to 1.0.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
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

# ── Trade outcome record ───────────────────────────────────────────────────────


@dataclass
class TradeOutcome:
    """A single completed trade outcome used to update rolling Sharpe estimates.

    Args:
        source: The :class:`~agent.strategies.ensemble.signals.SignalSource`
            that originated this trade's signal.
        pnl_pct: Realised profit-and-loss as a fraction of position value
            (e.g. ``0.02`` for +2 %, ``-0.01`` for -1 %).
        symbol: Trading pair the trade was executed on.
        regime: Optional current :class:`~agent.strategies.regime.labeler.RegimeType`
            value at the time of the outcome.  When provided, regime-conditional
            weight modifiers are applied after the Sharpe-based reweight.
    """

    source: SignalSource
    pnl_pct: float
    symbol: str = "UNKNOWN"
    regime: Any = None  # RegimeType | None; typed as Any to avoid hard dep


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

# ── Dynamic weight adaptation constants ───────────────────────────────────────

# Rolling window size for per-source Sharpe estimation.
# 50 trades gives enough history to estimate mean/stddev reliably while
# staying sensitive to recent performance changes.
_SHARPE_WINDOW: int = 50

# Annualisation factor placeholder.  Since we compute a ratio of
# mean/stddev over a rolling window (dimensionless), no time-scaling is
# applied — the "Sharpe" here is an unscaled reward-to-risk ratio that
# captures the sign and magnitude of recent per-source performance.
_SHARPE_MIN_OBSERVATIONS: int = 2  # need at least 2 to compute stddev

# Regime-conditional weight modifiers: regime → {source → multiplier}.
# Multipliers are applied **additively** on top of base Sharpe-adjusted
# weights before final normalisation.  A modifier of +0.3 means the
# source's pre-normalisation weight is increased by 30 % of the base weight.
# Signs are intentional (negative = slight penalty).
_REGIME_WEIGHT_MODIFIERS: dict[str, dict[SignalSource, float]] = {
    "trending": {
        SignalSource.RL: 0.30,
        SignalSource.EVOLVED: -0.10,
        SignalSource.REGIME: 0.0,
    },
    "mean_reverting": {
        SignalSource.RL: -0.10,
        SignalSource.EVOLVED: 0.30,
        SignalSource.REGIME: 0.0,
    },
    "high_volatility": {
        # Global −50 % encoded as a −0.50 modifier on every source, REGIME
        # gets an additional +20 % (net −30 %).
        SignalSource.RL: -0.50,
        SignalSource.EVOLVED: -0.50,
        SignalSource.REGIME: -0.30,
    },
    "low_volatility": {
        SignalSource.RL: 0.20,
        SignalSource.EVOLVED: 0.0,
        SignalSource.REGIME: 0.0,
    },
}


# ── MetaLearner ───────────────────────────────────────────────────────────────


class MetaLearner:
    """Weighted ensemble combiner for RL, EVOLVED, and REGIME signals.

    Weights start from the caller-supplied mapping and are dynamically
    adjusted via :meth:`update_weights` as trade outcomes arrive.  Each
    source maintains an independent rolling window of PnL observations
    (default 50) from which a Sharpe-like reward-to-risk ratio is derived.
    Regime-conditional multipliers are applied on top before renormalisation.

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
        sharpe_window: Rolling window length for per-source Sharpe estimation.
            Defaults to :data:`_SHARPE_WINDOW` (50).
    """

    def __init__(
        self,
        weights: dict[SignalSource, float] | None = None,
        confidence_threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
        min_agreement_rate: float = _DEFAULT_MIN_AGREEMENT_RATE,
        sharpe_window: int = _SHARPE_WINDOW,
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

        # Retain the original base weights so regime modifiers are applied
        # relative to a stable reference rather than accumulating drift.
        self._base_weights: dict[SignalSource, float] = dict(self._weights)

        self._confidence_threshold = confidence_threshold
        self._min_agreement_rate = min_agreement_rate
        self._sharpe_window = sharpe_window

        # Per-source rolling PnL deque — bounded to *sharpe_window* entries.
        self._pnl_history: dict[SignalSource, deque[float]] = {
            source: deque(maxlen=sharpe_window) for source in SignalSource
        }

        log.debug(
            "agent.strategy.ensemble.meta_learner.initialised",
            weights={s.value: round(w, 4) for s, w in self._weights.items()},
            confidence_threshold=confidence_threshold,
            min_agreement_rate=min_agreement_rate,
            sharpe_window=sharpe_window,
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

    @property
    def weights(self) -> dict[SignalSource, float]:
        """Current normalised per-source weights (read-only snapshot).

        Returns:
            Dict mapping each :class:`~agent.strategies.ensemble.signals.SignalSource`
            to its current weight.  Values always sum to 1.0.
        """
        return dict(self._weights)

    @property
    def pnl_history(self) -> dict[SignalSource, list[float]]:
        """Snapshot of rolling PnL observations per source (read-only).

        Returns:
            Dict mapping each source to a list of recent PnL values in
            chronological order (oldest first).
        """
        return {source: list(dq) for source, dq in self._pnl_history.items()}

    # ── Dynamic weight adaptation ─────────────────────────────────────────────

    @staticmethod
    def _rolling_sharpe(pnl_values: list[float]) -> float:
        """Compute a rolling Sharpe-like ratio from a list of PnL observations.

        The ratio is defined as ``mean(pnl) / stddev(pnl)``.  When stddev is
        zero (all returns identical) the sign of the mean determines the
        outcome: positive mean → 1.0, negative mean → -1.0, zero → 0.0.
        The result is **not** annualised — it is a dimensionless reward-to-risk
        ratio suitable for comparing relative source quality.

        Args:
            pnl_values: List of realised PnL fractions (e.g. 0.02 = +2 %).
                Must have at least :data:`_SHARPE_MIN_OBSERVATIONS` entries;
                fewer entries return 0.0.

        Returns:
            Sharpe-like ratio in the range approximately (−∞, +∞).
        """
        if len(pnl_values) < _SHARPE_MIN_OBSERVATIONS:
            return 0.0

        n = len(pnl_values)
        mean = sum(pnl_values) / n
        variance = sum((x - mean) ** 2 for x in pnl_values) / n
        stddev = math.sqrt(variance)

        if stddev == 0.0:
            # All returns are identical; use sign of mean as tiebreaker.
            if mean > 0:
                return 1.0
            if mean < 0:
                return -1.0
            return 0.0

        return mean / stddev

    def update_weights(
        self,
        recent_outcomes: list[TradeOutcome],
        current_regime: Any = None,
    ) -> dict[SignalSource, float]:
        """Recompute per-source weights from recent trade outcomes.

        The algorithm:

        1. Append each outcome's PnL to the corresponding source's rolling
           deque (capped at ``sharpe_window`` entries).
        2. Compute a Sharpe-like ratio per source over its full rolling window.
        3. Derive new raw weights:
               weight[source] = base_weight * (1 + source_sharpe) / norm_factor
           where ``norm_factor`` ensures the ratio term stays positive.
        4. Apply regime-conditional modifiers when ``current_regime`` is known.
        5. Clamp each weight to a minimum of ``1e-6`` (never zero).
        6. Normalise so all weights sum to 1.0.
        7. Store the result in ``self._weights`` and log the change.

        Args:
            recent_outcomes: List of :class:`TradeOutcome` records from the
                most recently completed trades.  May be empty (no-op).
            current_regime: Optional
                :class:`~agent.strategies.regime.labeler.RegimeType` value
                describing the current market state.  When provided, regime-
                conditional modifiers are applied after Sharpe reweighting.
                Accepts the regime value from either ``recent_outcomes[-1].regime``
                or a separately supplied classifier output.  ``None`` disables
                regime modifiers.

        Returns:
            The new normalised weight dict (same as ``self.weights`` after
            the update).
        """
        if not recent_outcomes:
            return dict(self._weights)

        # ── Step 1: append outcomes to per-source rolling windows ──────────
        for outcome in recent_outcomes:
            self._pnl_history[outcome.source].append(outcome.pnl_pct)

        # Derive regime from the most recent outcome if not supplied explicitly.
        effective_regime = current_regime
        if effective_regime is None and recent_outcomes[-1].regime is not None:
            effective_regime = recent_outcomes[-1].regime

        # ── Step 2: compute per-source Sharpe ratio ────────────────────────
        sharpes: dict[SignalSource, float] = {}
        for source in SignalSource:
            sharpes[source] = self._rolling_sharpe(list(self._pnl_history[source]))

        log.debug(
            "agent.strategy.ensemble.meta_learner.sharpe_computed",
            sharpes={s.value: round(v, 4) for s, v in sharpes.items()},
        )

        # ── Step 3: compute Sharpe-adjusted raw weights ────────────────────
        # weight = base_weight * (1 + sharpe)
        # We shift by adding 1 so that a Sharpe of 0 preserves the base weight
        # and a negative Sharpe reduces (but does not zero) the weight.
        raw: dict[SignalSource, float] = {}
        for source in SignalSource:
            base = self._base_weights.get(source, 1.0 / len(SignalSource))
            adjusted = base * (1.0 + sharpes[source])
            raw[source] = max(adjusted, 1e-6)

        # ── Step 4: apply regime-conditional modifiers ─────────────────────
        if effective_regime is not None:
            # Resolve regime string value regardless of whether it is a
            # RegimeType enum or a plain string.
            regime_key: str = (
                effective_regime.value
                if hasattr(effective_regime, "value")
                else str(effective_regime)
            )
            modifiers = _REGIME_WEIGHT_MODIFIERS.get(regime_key)
            if modifiers is not None:
                for source, modifier in modifiers.items():
                    base = self._base_weights.get(source, 1.0 / len(SignalSource))
                    raw[source] = max(raw[source] + base * modifier, 1e-6)

                log.debug(
                    "agent.strategy.ensemble.meta_learner.regime_modifiers_applied",
                    regime=regime_key,
                    modifiers={s.value: round(m, 4) for s, m in modifiers.items()},
                )

        # ── Step 5–6: clamp and normalise ──────────────────────────────────
        total = sum(raw.values())
        if total <= 0:
            # Defensive: fall back to equal weights.
            n = len(SignalSource)
            self._weights = {s: 1.0 / n for s in SignalSource}
        else:
            self._weights = {source: raw[source] / total for source in SignalSource}

        log.info(
            "agent.strategy.ensemble.meta_learner.weights_updated",
            weights={s.value: round(w, 4) for s, w in self._weights.items()},
            regime=getattr(effective_regime, "value", effective_regime),
            outcomes_processed=len(recent_outcomes),
        )
        return dict(self._weights)

    # ── Attribution-driven weight update ─────────────────────────────────────

    def apply_attribution_weights(
        self,
        attribution_pnl: dict[str, float],
        *,
        min_weight: float = 0.05,
    ) -> dict[SignalSource, float]:
        """Adjust source weights proportionally to 7-day attributed PnL.

        Called once at the start of each trading session after reading
        ``AgentPerformance`` rows (``period="attribution"``) from the database.
        Each strategy's current normalised weight is multiplied by
        ``max(1.0 + pnl_pct, min_weight)`` where ``pnl_pct`` is its trailing
        7-day PnL fraction.  Weights are then clamped to ``min_weight`` from
        below and renormalised to sum to 1.0.

        This provides a session-level boost/penalisation that runs on top of
        (and before) the per-step Sharpe-based :meth:`update_weights` path.
        The effect resets each session because ``initialize()`` re-constructs
        the :class:`MetaLearner`; calling this method early in the session
        seeds the starting weights with recent attribution signal.

        Mapping from ``agent_strategy_signals.strategy_name`` to
        :class:`~agent.strategies.ensemble.signals.SignalSource`:

        * ``"rl"``      → :attr:`SignalSource.RL`
        * ``"evolved"`` → :attr:`SignalSource.EVOLVED`
        * ``"regime"``  → :attr:`SignalSource.REGIME`

        Unknown keys in ``attribution_pnl`` are silently ignored.

        Args:
            attribution_pnl: Mapping from strategy name (as stored in
                ``agent_strategy_signals.strategy_name``) to its trailing 7-day
                attributed PnL fraction (e.g. ``{"rl": 0.03,
                "evolved": -0.02, "regime": 0.01}``).
            min_weight: Floor applied to each pre-normalisation weight.
                Prevents any source from being silenced by a run of bad
                attribution data.  Default ``0.05``.  Must be in [0.0, 1.0).

        Returns:
            The updated normalised weight dict (a copy).

        Raises:
            ValueError: If ``min_weight`` is not in [0.0, 1.0).
        """
        if not 0.0 <= min_weight < 1.0:
            raise ValueError(f"min_weight must be in [0.0, 1.0); got {min_weight!r}")

        new_weights: dict[SignalSource, float] = {}
        for source, base_weight in self._weights.items():
            pnl = attribution_pnl.get(source.value, 0.0)
            # Multiplicative adjustment: positive PnL boosts, negative shrinks.
            # Clamp so a single bad period cannot drive a weight to zero.
            adjusted = base_weight * max(1.0 + pnl, min_weight)
            new_weights[source] = max(adjusted, min_weight)

        # Renormalise so weights sum to 1.0.
        total = sum(new_weights.values())
        if total <= 0:
            # Defensive — cannot happen with min_weight > 0.
            log.warning(
                "agent.strategy.ensemble.meta_learner.apply_attribution.zero_total",
                attribution_pnl=attribution_pnl,
            )
            return dict(self._weights)

        self._weights = {s: w / total for s, w in new_weights.items()}
        # Also update base weights so that subsequent Sharpe-based update_weights
        # calls operate relative to the attribution-adjusted baseline.
        self._base_weights = dict(self._weights)

        log.info(
            "agent.strategy.ensemble.meta_learner.attribution_weights_applied",
            new_weights={s.value: round(w, 4) for s, w in self._weights.items()},
            attribution_pnl={k: round(v, 6) for k, v in attribution_pnl.items()},
        )
        return dict(self._weights)

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
                "agent.strategy.ensemble.meta_learner.hold_low_confidence",
                symbol=symbol,
                combined_confidence=round(combined_confidence, 4),
                threshold=self._confidence_threshold,
            )
            final_action = TradeAction.HOLD

        elif rate < self._min_agreement_rate:
            log.debug(
                "agent.strategy.ensemble.meta_learner.hold_low_agreement",
                symbol=symbol,
                agreement_rate=round(rate, 4),
                min_agreement_rate=self._min_agreement_rate,
            )
            final_action = TradeAction.HOLD

        log.debug(
            "agent.strategy.ensemble.meta_learner.consensus",
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
