"""Concept drift detection for strategy performance monitoring.

Implements the Page-Hinkley (PH) test to detect statistically significant
degradation in per-strategy Sharpe ratio, win rate, and average PnL.  When
drift is detected the detector:

1. Emits a ``agent.strategy.drift.detected`` structlog event.
2. Sets the ``drift_active`` flag on the affected strategy.
3. Returns a ``position_size_multiplier`` of ``0.5`` so callers halve their
   position sizes automatically.
4. Increases the REGIME source weight in the returned ``ensemble_weight_hints``
   dict so the ``MetaLearner`` leans on the regime strategy during turbulence.

Recovery happens automatically when the cumulative PH sum resets below
``recovery_threshold`` for ``recovery_steps`` consecutive steps.  The flag is
cleared and normal sizing resumes.

Usage::

    from agent.strategies.drift import DriftDetector, DriftConfig

    detector = DriftDetector()
    update = detector.update(
        strategy_name="ensemble_v1",
        sharpe=1.2,
        win_rate=0.55,
        avg_pnl=42.50,
    )
    if update.drift_active:
        size_multiplier = update.position_size_multiplier   # 0.5
        weights = update.ensemble_weight_hints              # {"REGIME": 0.6, ...}

See also ``agent/strategies/ensemble/meta_learner.py`` and
``agent/trading/strategy_manager.py`` for integration points.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default Page-Hinkley sensitivity (δ).  A smaller value makes the detector
# more sensitive to small persistent shifts; a larger value reduces false
# positives in noisy environments.  0.005 works well for normalised metrics
# (Sharpe, win rate, avg_pnl z-scored) in typical trading conditions.
DEFAULT_PH_DELTA: float = 0.005

# Default detection threshold (λ).  The PH sum must exceed this value for
# drift to be declared.  Higher values require a larger or more sustained
# shift to trigger.  50.0 gives a good trade-off for daily trading metrics.
DEFAULT_PH_THRESHOLD: float = 50.0

# Minimum number of samples before the detector can fire.  Prevents spurious
# early detections during the warm-up period when the rolling mean is unstable.
DEFAULT_WARMUP_STEPS: int = 30

# Number of consecutive below-threshold steps required before the drift flag
# is cleared (recovery confirmation window).
DEFAULT_RECOVERY_STEPS: int = 10

# Position size multiplier applied when drift is active.
DRIFT_SIZE_MULTIPLIER: float = 0.5

# REGIME weight boost applied to ensemble weight hints when drift is active.
# The other sources (RL, EVOLVED) are down-weighted proportionally.
DRIFT_REGIME_WEIGHT: float = 0.6
DRIFT_RL_WEIGHT: float = 0.25
DRIFT_EVOLVED_WEIGHT: float = 0.15

# Normal ensemble weight hints (used when drift is inactive).
NORMAL_REGIME_WEIGHT: float = 0.33
NORMAL_RL_WEIGHT: float = 0.34
NORMAL_EVOLVED_WEIGHT: float = 0.33

# Maximum history entries per strategy (bounded deque).
METRIC_HISTORY_MAXLEN: int = 500


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DriftConfig:
    """Configuration for the Page-Hinkley drift detector.

    Args:
        ph_delta: Allowable mean deviation before the PH sum starts
            accumulating (δ parameter).  Smaller → more sensitive.
        ph_threshold: PH sum value at which drift is declared (λ parameter).
            Larger → requires a more sustained shift.
        warmup_steps: Number of samples required before drift can be declared.
            During warm-up the detector accumulates statistics but never fires.
        recovery_steps: Number of consecutive below-threshold steps needed to
            clear the drift flag.
    """

    ph_delta: float = DEFAULT_PH_DELTA
    ph_threshold: float = DEFAULT_PH_THRESHOLD
    warmup_steps: int = DEFAULT_WARMUP_STEPS
    recovery_steps: int = DEFAULT_RECOVERY_STEPS


@dataclass(frozen=True)
class DriftUpdate:
    """Result returned by :meth:`DriftDetector.update`.

    Args:
        strategy_name: Name of the strategy that was updated.
        drift_active: ``True`` when the PH test has declared drift for this
            strategy and the drift flag has not yet been cleared by recovery.
        drift_detected_this_step: ``True`` only on the exact step when drift
            transitions from ``False`` → ``True``.  Useful for one-shot
            alerting without re-firing on every subsequent step.
        recovery_detected_this_step: ``True`` only on the step when drift
            transitions from ``True`` → ``False``.
        position_size_multiplier: ``0.5`` when ``drift_active`` is ``True``,
            ``1.0`` otherwise.  Callers should multiply their computed position
            size by this value.
        ensemble_weight_hints: Dict mapping signal source names to suggested
            weights.  When drift is active, the REGIME weight is elevated to
            improve stability.  Callers may use these as soft suggestions rather
            than hard overrides.
        ph_sum: Current Page-Hinkley cumulative sum for diagnostic purposes.
        step_count: Total number of update calls for this strategy.
    """

    strategy_name: str
    drift_active: bool
    drift_detected_this_step: bool
    recovery_detected_this_step: bool
    position_size_multiplier: float
    ensemble_weight_hints: dict[str, float]
    ph_sum: float
    step_count: int


@dataclass
class _StrategyState:
    """Internal mutable state per tracked strategy.

    Attributes:
        step_count: Total samples received so far.
        running_mean: Exponential moving average of the composite metric used
            as the reference baseline for the PH test.
        ph_sum: Accumulated Page-Hinkley sum (``Σ (x - μ_n - δ)``).
        ph_min: Running minimum of ``ph_sum``.  Used to detect upward drift
            (performance degradation mapped to positive PH sum direction).
        drift_active: Whether drift is currently declared for this strategy.
        recovery_counter: Number of consecutive steps the PH sum has been
            below ``ph_threshold`` since drift was first detected.  Resets
            to 0 whenever the sum exceeds the threshold again.
        metric_history: Bounded deque of recent composite metric values.
    """

    step_count: int = 0
    running_mean: float = 0.0
    ph_sum: float = 0.0
    ph_min: float = 0.0
    drift_active: bool = False
    recovery_counter: int = 0
    metric_history: deque[float] = field(default_factory=lambda: deque(maxlen=METRIC_HISTORY_MAXLEN))


# ---------------------------------------------------------------------------
# DriftDetector
# ---------------------------------------------------------------------------


class DriftDetector:
    """Monitors per-strategy performance and detects concept drift via the
    Page-Hinkley test.

    The detector maintains independent state per strategy name.  On each call
    to :meth:`update` it:

    1. Computes a composite metric from the three provided performance signals
       (Sharpe, win rate, avg PnL) using a simple weighted average.
    2. Negates the metric so that performance *degradation* maps to a
       positive upward shift that the PH test detects.
    3. Updates the running mean and PH accumulated sum.
    4. Declares drift when ``ph_sum - ph_min > ph_threshold`` and
       ``step_count >= warmup_steps``.
    5. Clears drift when the composite metric returns above the running mean
       for ``recovery_steps`` consecutive steps (simpler than waiting for the
       large accumulated PH sum to decay below threshold).
    6. Returns a :class:`DriftUpdate` with actionable multipliers and hints.

    Args:
        config: :class:`DriftConfig` controlling sensitivity and recovery.
            Defaults to production-tuned values.

    Example::

        detector = DriftDetector()

        # Feed strategy outcomes one by one
        for pnl, win, sharpe in trade_outcomes:
            result = detector.update(
                strategy_name="ensemble_v1",
                sharpe=sharpe,
                win_rate=float(win),
                avg_pnl=pnl,
            )
            if result.drift_active:
                position_size *= result.position_size_multiplier
    """

    # Weights used to combine the three performance signals into a single
    # scalar for the PH test.  These weights reflect the relative importance
    # of each metric for regime-adaptive trading strategies.
    _SHARPE_WEIGHT: float = 0.4
    _WIN_RATE_WEIGHT: float = 0.35
    _AVG_PNL_WEIGHT: float = 0.25

    # Normalisation scale for avg_pnl — assumes typical per-trade PnL is in
    # the range ±200 USDT.  Scales avg_pnl to a similar range as Sharpe and
    # win_rate (both already in 0–2 range) before combining.
    _AVG_PNL_SCALE: float = 200.0

    def __init__(self, config: DriftConfig | None = None) -> None:
        """Initialise the drift detector.

        Args:
            config: Optional :class:`DriftConfig`.  Defaults to
                :class:`DriftConfig()` (production-tuned parameters).
        """
        self._config: DriftConfig = config or DriftConfig()
        self._states: dict[str, _StrategyState] = {}

        logger.info(
            "agent.strategy.drift.initialised",
            ph_delta=self._config.ph_delta,
            ph_threshold=self._config.ph_threshold,
            warmup_steps=self._config.warmup_steps,
            recovery_steps=self._config.recovery_steps,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        strategy_name: str,
        sharpe: float,
        win_rate: float,
        avg_pnl: float,
    ) -> DriftUpdate:
        """Record a new performance observation for ``strategy_name``.

        Computes the composite metric, runs one step of the Page-Hinkley test,
        and returns actionable drift information.

        Args:
            strategy_name: Unique identifier for the strategy being monitored.
                New strategies are automatically tracked on first call.
            sharpe: Current Sharpe ratio (typically in the range −2 to +3).
                Computed over a rolling window by the caller (e.g.
                ``StrategyManager``).
            win_rate: Fraction of trades that were profitable (0.0–1.0).
            avg_pnl: Average per-trade PnL in USDT.  May be negative during
                drawdown periods.

        Returns:
            :class:`DriftUpdate` describing current drift status and
            recommended position size multiplier and ensemble weight hints.
        """
        state = self._get_or_create_state(strategy_name)

        composite = self._composite_metric(sharpe, win_rate, avg_pnl)
        state.metric_history.append(composite)
        state.step_count += 1

        # Use the negated metric so that *lower* performance → positive PH sum.
        negated = -composite

        # Update running mean (simple cumulative mean up to warmup, then EMA).
        self._update_mean(state, composite)

        # Page-Hinkley accumulation step.
        # PH sum = Σ (x_i − μ̄_n − δ)  where x_i is the negated metric.
        increment = negated - state.running_mean - self._config.ph_delta
        state.ph_sum += increment
        state.ph_min = min(state.ph_min, state.ph_sum)

        # PH detection condition: sum − min > threshold, after warmup.
        ph_test_value = state.ph_sum - state.ph_min
        in_drift = (
            state.step_count >= self._config.warmup_steps
            and ph_test_value > self._config.ph_threshold
        )

        # Recovery criterion: composite metric is meaningfully above the running
        # mean.  A small tolerance (1e-9) avoids floating-point false positives
        # when the EMA running_mean and composite are nominally equal — a common
        # artefact when the same metric is fed repeatedly.
        _RECOVERY_EPSILON: float = 1e-9
        recovering = composite > state.running_mean + _RECOVERY_EPSILON

        # Compute drift flag transitions.
        was_drifting = state.drift_active
        drift_detected_this_step = False
        recovery_detected_this_step = False

        if not was_drifting:
            # Not currently in drift — check for initial detection.
            if in_drift:
                state.drift_active = True
                drift_detected_this_step = True
                state.recovery_counter = 0
                self._log_drift_detected(strategy_name, state, ph_test_value)
        else:
            # Already in drift — track recovery progress.
            if recovering:
                state.recovery_counter += 1
                if state.recovery_counter >= self._config.recovery_steps:
                    # Confirmed recovery: performance has normalised for
                    # recovery_steps consecutive steps.
                    state.drift_active = False
                    recovery_detected_this_step = True
                    self._reset_ph(state)
                    self._log_drift_recovered(strategy_name, state)
            else:
                # Degradation still present — reset recovery counter.
                state.recovery_counter = 0

        size_multiplier = DRIFT_SIZE_MULTIPLIER if state.drift_active else 1.0
        weight_hints = self._ensemble_weight_hints(state.drift_active)

        return DriftUpdate(
            strategy_name=strategy_name,
            drift_active=state.drift_active,
            drift_detected_this_step=drift_detected_this_step,
            recovery_detected_this_step=recovery_detected_this_step,
            position_size_multiplier=size_multiplier,
            ensemble_weight_hints=weight_hints,
            ph_sum=state.ph_sum,
            step_count=state.step_count,
        )

    def is_drifting(self, strategy_name: str) -> bool:
        """Return whether the named strategy is currently in a drift state.

        Args:
            strategy_name: Strategy identifier.

        Returns:
            ``True`` if drift is currently active, ``False`` if the strategy
            is not yet tracked or drift has not been declared.
        """
        state = self._states.get(strategy_name)
        return state.drift_active if state is not None else False

    def reset(self, strategy_name: str) -> None:
        """Reset all drift state for the named strategy.

        Useful when a strategy is retrained or when a new trading session
        starts and the historical drift signal is no longer relevant.

        Args:
            strategy_name: Strategy identifier.  No-op if not tracked.
        """
        if strategy_name in self._states:
            self._states[strategy_name] = _StrategyState()
            logger.info("agent.strategy.drift.reset", strategy_name=strategy_name)

    def reset_all(self) -> None:
        """Reset drift state for all tracked strategies.

        Called at the start of a new trading session to ensure stale drift
        signals from the previous session do not pollute the new one.
        """
        count = len(self._states)
        self._states.clear()
        logger.info("agent.strategy.drift.reset_all", strategies_cleared=count)

    def get_state_summary(self, strategy_name: str) -> dict[str, Any]:
        """Return a plain dict snapshot of the detector state for a strategy.

        Intended for diagnostics and dashboard reporting.

        Args:
            strategy_name: Strategy identifier.

        Returns:
            Dict with ``step_count``, ``drift_active``, ``ph_sum``,
            ``ph_min``, ``recovery_counter``, ``running_mean``, and
            ``recent_metrics`` (list of last 10 composite values).  Returns
            an empty dict if the strategy is not tracked.
        """
        state = self._states.get(strategy_name)
        if state is None:
            return {}
        return {
            "strategy_name": strategy_name,
            "step_count": state.step_count,
            "drift_active": state.drift_active,
            "ph_sum": round(state.ph_sum, 6),
            "ph_min": round(state.ph_min, 6),
            "ph_test_value": round(state.ph_sum - state.ph_min, 6),
            "recovery_counter": state.recovery_counter,
            "running_mean": round(state.running_mean, 6),
            "recent_metrics": list(state.metric_history)[-10:],
        }

    @property
    def tracked_strategies(self) -> list[str]:
        """Return the names of all currently tracked strategies.

        Returns:
            Sorted list of strategy name strings.
        """
        return sorted(self._states.keys())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_or_create_state(self, strategy_name: str) -> _StrategyState:
        """Return existing state or initialise and register a new one.

        Args:
            strategy_name: Strategy identifier.

        Returns:
            The :class:`_StrategyState` for this strategy.
        """
        if strategy_name not in self._states:
            self._states[strategy_name] = _StrategyState()
            logger.debug(
                "agent.strategy.drift.strategy_registered",
                strategy_name=strategy_name,
            )
        return self._states[strategy_name]

    def _composite_metric(self, sharpe: float, win_rate: float, avg_pnl: float) -> float:
        """Combine three performance signals into a single scalar.

        The composite is a weighted average of normalised signals.  ``avg_pnl``
        is divided by ``_AVG_PNL_SCALE`` to bring it into a similar magnitude
        as Sharpe (0–3) and win_rate (0–1) before combining.

        Args:
            sharpe: Strategy Sharpe ratio.
            win_rate: Win rate fraction (0.0–1.0).
            avg_pnl: Average per-trade PnL in USDT.

        Returns:
            Weighted composite scalar.
        """
        normalised_pnl = avg_pnl / self._AVG_PNL_SCALE
        return (
            self._SHARPE_WEIGHT * sharpe
            + self._WIN_RATE_WEIGHT * win_rate
            + self._AVG_PNL_WEIGHT * normalised_pnl
        )

    def _update_mean(self, state: _StrategyState, composite: float) -> None:
        """Update the running reference mean for the PH test.

        During the warmup period uses a simple cumulative mean.  After warmup,
        switches to an exponential moving average (α = 2/(warmup+1)) for
        smoother adaptation to slow distributional shifts that are NOT drift
        (e.g. gradual market improvement over weeks).

        Args:
            state: Mutable strategy state.
            composite: Latest composite metric value.
        """
        if state.step_count <= 1:
            # Bootstrap the mean on the first sample (step_count was just
            # incremented before this call, so step_count == 1 is the first).
            state.running_mean = composite
        elif state.step_count <= self._config.warmup_steps:
            # Cumulative mean during warm-up: μ_n = μ_{n-1} + (x_n - μ_{n-1}) / n
            n = state.step_count
            state.running_mean += (composite - state.running_mean) / n
        else:
            # EMA after warmup to track slow baseline drift without inflating
            # the PH statistic for gradual improvements.
            alpha = 2.0 / (self._config.warmup_steps + 1)
            state.running_mean = alpha * composite + (1.0 - alpha) * state.running_mean

    def _reset_ph(self, state: _StrategyState) -> None:
        """Reset PH accumulation state after confirmed recovery.

        Resets ``ph_sum`` and ``ph_min`` to 0 so the test starts fresh.
        The running mean is preserved — it reflects the post-recovery baseline.

        Args:
            state: Mutable strategy state.
        """
        state.ph_sum = 0.0
        state.ph_min = 0.0
        state.recovery_counter = 0

    @staticmethod
    def _ensemble_weight_hints(drift_active: bool) -> dict[str, float]:
        """Return ensemble source weight hints based on drift status.

        When drift is active the REGIME strategy weight is elevated because
        regime-based strategies are more robust to sudden market-structure
        changes than data-hungry RL or heavily-tuned evolved strategies.

        Args:
            drift_active: Whether drift is currently declared.

        Returns:
            Dict mapping signal source names (``"RL"``, ``"EVOLVED"``,
            ``"REGIME"``) to suggested weight values summing to 1.0.
        """
        if drift_active:
            return {
                "RL": DRIFT_RL_WEIGHT,
                "EVOLVED": DRIFT_EVOLVED_WEIGHT,
                "REGIME": DRIFT_REGIME_WEIGHT,
            }
        return {
            "RL": NORMAL_RL_WEIGHT,
            "EVOLVED": NORMAL_EVOLVED_WEIGHT,
            "REGIME": NORMAL_REGIME_WEIGHT,
        }

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log_drift_detected(
        self,
        strategy_name: str,
        state: _StrategyState,
        ph_test_value: float,
    ) -> None:
        """Emit the ``REGIME_DRIFT_DETECTED`` structlog event.

        Args:
            strategy_name: Name of the affected strategy.
            state: Current strategy state.
            ph_test_value: Current PH test value (``ph_sum - ph_min``).
        """
        logger.warning(
            "agent.strategy.drift.detected",
            strategy_name=strategy_name,
            step_count=state.step_count,
            ph_test_value=round(ph_test_value, 4),
            ph_threshold=self._config.ph_threshold,
            running_mean=round(state.running_mean, 4),
            position_size_multiplier=DRIFT_SIZE_MULTIPLIER,
            regime_weight_boost=DRIFT_REGIME_WEIGHT,
        )

    def _log_drift_recovered(self, strategy_name: str, state: _StrategyState) -> None:
        """Emit the drift-recovered structlog event.

        Args:
            strategy_name: Name of the recovered strategy.
            state: Current strategy state (after recovery flag cleared).
        """
        logger.info(
            "agent.strategy.drift.recovered",
            strategy_name=strategy_name,
            step_count=state.step_count,
            recovery_steps=self._config.recovery_steps,
        )
