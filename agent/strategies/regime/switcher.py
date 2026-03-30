"""Market regime switcher — orchestration layer for regime-aware trading.

Detects the current market regime from incoming candle data using a trained
``RegimeClassifier``, enforces a confidence threshold and a cooldown period
before switching, and returns the active strategy ID to the caller's decision
loop.

Usage (programmatic):

    from agent.strategies.regime.classifier import RegimeClassifier
    from agent.strategies.regime.switcher import RegimeSwitcher
    from agent.strategies.regime.labeler import RegimeType

    clf = RegimeClassifier.load(Path("agent/strategies/regime/models/regime_classifier.joblib"))
    strategy_map = {
        RegimeType.TRENDING: "uuid-strategy-trending",
        RegimeType.MEAN_REVERTING: "uuid-strategy-mean-reverting",
        RegimeType.HIGH_VOLATILITY: "uuid-strategy-high-vol",
        RegimeType.LOW_VOLATILITY: "uuid-strategy-low-vol",
    }
    switcher = RegimeSwitcher(classifier=clf, strategy_map=strategy_map)

    # Feed candles one step at a time in the agent's decision loop:
    regime, strategy_id, switched = switcher.step(recent_candles)

Usage (CLI demo):

    python -m agent.strategies.regime.switcher --demo
    python -m agent.strategies.regime.switcher --demo --seed 7 --candles 300
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
import structlog

from agent.strategies.regime.classifier import RegimeClassifier
from agent.strategies.regime.labeler import RegimeType, generate_training_data

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants — every value has a docstring explaining why it was chosen.
# ---------------------------------------------------------------------------

# Minimum classifier confidence (0–1) to accept a regime prediction.
# Below this threshold the switcher ignores the new prediction and keeps the
# current regime.  0.7 corresponds to a moderately high confidence level that
# avoids acting on ambiguous or noisy regime signals while still reacting
# promptly to clear regime changes.
CONFIDENCE_THRESHOLD: float = 0.7

# Number of new candles that must arrive after a regime switch before another
# switch is permitted.  5 candles on a 1-hour timeframe = 5 hours of cooldown.
# This prevents the strategy from thrashing between regimes when the classifier
# oscillates at a regime boundary — a common issue with rolling-window features.
SWITCH_COOLDOWN_CANDLES: int = 5

# Minimum number of candles required before the switcher will attempt a
# classification.  Matches the warm-up period for the slowest indicator
# (ADX at period=20 needs ~40 candles before the value stabilises).  Providing
# fewer candles returns the current regime unchanged.
MIN_CANDLES_REQUIRED: int = 50


# ---------------------------------------------------------------------------
# Regime history record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegimeRecord:
    """A single entry in the regime history log.

    Args:
        timestamp: UTC datetime when this regime was detected.
        regime: The detected ``RegimeType``.
        confidence: Classifier confidence at detection time (0.0–1.0).
        strategy_id: The strategy ID that was activated for this regime.
        candle_index: The position in the candle feed when this record was
            created.  Useful for replaying or analysing regime change timing.
    """

    timestamp: datetime
    regime: RegimeType
    confidence: float
    strategy_id: str
    candle_index: int


# ---------------------------------------------------------------------------
# RegimeSwitcher
# ---------------------------------------------------------------------------


class RegimeSwitcher:
    """Orchestrates regime detection and strategy activation.

    On each call to :meth:`step` the switcher:
    1. Extracts features from the provided candles.
    2. Calls the classifier to predict the current regime and confidence.
    3. Applies the confidence threshold and cooldown guard.
    4. If a switch is approved, updates internal state and logs the event.
    5. Returns the active regime, active strategy ID, and a ``switched`` flag.

    The switcher is stateful — it tracks the current regime, the number of
    candles elapsed since the last switch, and a full history of regime changes.

    Args:
        classifier: A fitted ``RegimeClassifier`` instance.  Must have been
            trained or loaded before being passed here; otherwise
            ``RuntimeError`` is raised on the first prediction call.
        strategy_map: A mapping from each ``RegimeType`` to the platform
            strategy ID (UUID string) that should be activated for that regime.
            All four ``RegimeType`` values should be present; any missing key
            causes ``KeyError`` at switch time.
        initial_regime: The regime to assume before any candles have been
            processed.  Defaults to ``MEAN_REVERTING`` as a conservative
            neutral posture.
        confidence_threshold: Minimum classifier probability required to
            accept a regime switch.  Defaults to :data:`CONFIDENCE_THRESHOLD`.
        cooldown_candles: Number of new candles that must pass after a switch
            before the next switch is allowed.  Defaults to
            :data:`SWITCH_COOLDOWN_CANDLES`.
    """

    def __init__(
        self,
        classifier: RegimeClassifier,
        strategy_map: dict[RegimeType, str],
        initial_regime: RegimeType = RegimeType.MEAN_REVERTING,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        cooldown_candles: int = SWITCH_COOLDOWN_CANDLES,
    ) -> None:
        self._classifier = classifier
        self._strategy_map = strategy_map
        self._confidence_threshold = confidence_threshold
        self._cooldown_candles = cooldown_candles

        # --- Mutable state ---
        # Current active regime.
        self.current_regime: RegimeType = initial_regime
        # How many candles have been processed since the last switch.
        # Starts at cooldown_candles so a switch is immediately permitted
        # on the very first step if confidence is high enough.
        self.candles_since_switch: int = cooldown_candles
        # Full ordered history of regime records (capped at 500 entries).
        self.regime_history: deque[RegimeRecord] = deque(maxlen=500)
        # Running candle counter incremented on every step() call.
        self._total_candles_processed: int = 0

        # --- Indicator cache for detect_regime() ---
        # Stores the last candle's timestamp and the resulting
        # (regime, confidence) so repeated calls with the same candle
        # window skip redundant indicator recomputation.
        self._cached_last_candle_ts: Any = None
        self._cached_regime_result: tuple[RegimeType, float] | None = None

        logger.info(
            "agent.strategy.regime.switcher.initialised",
            initial_regime=initial_regime.value,
            confidence_threshold=confidence_threshold,
            cooldown_candles=cooldown_candles,
            strategy_map={r.value: sid for r, sid in strategy_map.items()},
        )

    # ------------------------------------------------------------------
    # Core public API
    # ------------------------------------------------------------------

    def detect_regime(self, candles: list[dict]) -> tuple[RegimeType, float]:  # type: ignore[type-arg]
        """Compute features from ``candles`` and call the classifier.

        Args:
            candles: List of OHLCV dicts (same schema as :func:`label_candles`).
                Must have at least :data:`MIN_CANDLES_REQUIRED` entries for a
                meaningful prediction.

        Returns:
            A ``(regime, confidence)`` tuple.  If there are too few candles
            for feature computation, returns ``(current_regime, 0.0)`` so the
            caller can safely ignore the result.

        Raises:
            RuntimeError: If the underlying classifier has not been trained or
                loaded.
        """
        if len(candles) < MIN_CANDLES_REQUIRED:
            logger.debug(
                "agent.strategy.regime.switcher.detect_skipped_insufficient_candles",
                n_candles=len(candles),
                min_required=MIN_CANDLES_REQUIRED,
            )
            return self.current_regime, 0.0

        # Cache check: if the last candle's timestamp hasn't changed since
        # the previous call, return the already-computed result to avoid
        # recomputing all 5 indicators over the full window from scratch.
        last_candle_ts = candles[-1].get("timestamp")
        if (
            last_candle_ts is not None
            and last_candle_ts == self._cached_last_candle_ts
            and self._cached_regime_result is not None
        ):
            logger.debug(
                "agent.strategy.regime.switcher.detect_cache_hit",
                last_candle_ts=last_candle_ts,
            )
            return self._cached_regime_result

        try:
            features, _ = generate_training_data(candles, window=20)
        except ValueError:
            # All rows dropped as NaN — indicator warm-up not yet complete.
            logger.debug(
                "agent.strategy.regime.switcher.detect_skipped_nan_features",
                n_candles=len(candles),
            )
            return self.current_regime, 0.0

        if len(features) == 0:
            return self.current_regime, 0.0

        # Use only the most recent valid feature row for the prediction.
        latest_row = features.iloc[[-1]].reset_index(drop=True)
        regime, confidence = self._classifier.predict(latest_row)

        # Populate cache for this candle timestamp.
        self._cached_last_candle_ts = last_candle_ts
        self._cached_regime_result = (regime, confidence)

        logger.debug(
            "agent.strategy.regime.switcher.detected",
            regime=regime.value,
            confidence=round(confidence, 4),
            n_candles=len(candles),
        )
        return regime, confidence

    def should_switch(self, new_regime: RegimeType, confidence: float) -> bool:
        """Decide whether to switch to ``new_regime`` given ``confidence``.

        A switch is approved only when **all** of the following are true:

        1. ``new_regime`` differs from :attr:`current_regime`.
        2. ``confidence`` >= :attr:`_confidence_threshold`.
        3. :attr:`candles_since_switch` >= :attr:`_cooldown_candles` (cooldown
           expired).

        Args:
            new_regime: The regime predicted by the classifier.
            confidence: The classifier's probability for ``new_regime``.

        Returns:
            ``True`` if the switch should proceed; ``False`` otherwise.
        """
        if new_regime == self.current_regime:
            return False

        if confidence < self._confidence_threshold:
            logger.debug(
                "agent.strategy.regime.switcher.switch_rejected_low_confidence",
                new_regime=new_regime.value,
                confidence=round(confidence, 4),
                threshold=self._confidence_threshold,
            )
            return False

        if self.candles_since_switch < self._cooldown_candles:
            logger.debug(
                "agent.strategy.regime.switcher.switch_rejected_cooldown",
                new_regime=new_regime.value,
                candles_since_switch=self.candles_since_switch,
                cooldown=self._cooldown_candles,
            )
            return False

        return True

    def get_active_strategy(self) -> str:
        """Return the strategy ID mapped to the current regime.

        Returns:
            Platform strategy UUID string for :attr:`current_regime`.

        Raises:
            KeyError: If :attr:`current_regime` is not in
                :attr:`_strategy_map`.
        """
        return self._strategy_map[self.current_regime]

    def step(self, candles: list[dict]) -> tuple[RegimeType, str, bool]:  # type: ignore[type-arg]
        """Process a new batch of candles, switching regime if criteria are met.

        This is the primary entry point for the agent's decision loop.  Call
        it on every candle (or batch of candles) with the most-recent window
        of candle history.

        Args:
            candles: List of recent OHLCV dicts, ordered oldest to newest.
                Pass a rolling window (e.g. the last 100 candles) so that
                indicator warm-up is always satisfied.

        Returns:
            A three-tuple ``(regime, strategy_id, switched)``:

            - ``regime``: The :class:`RegimeType` that is now active.
            - ``strategy_id``: The platform strategy UUID for the active
              regime (from :attr:`_strategy_map`).
            - ``switched``: ``True`` if the regime changed on this step.

        """
        self._total_candles_processed += 1
        self.candles_since_switch += 1

        # Detect the current regime from the provided candles.
        new_regime, confidence = self.detect_regime(candles)

        switched = False
        if self.should_switch(new_regime, confidence):
            old_regime = self.current_regime
            self.current_regime = new_regime
            self.candles_since_switch = 0

            record = RegimeRecord(
                timestamp=datetime.now(tz=UTC),
                regime=new_regime,
                confidence=confidence,
                strategy_id=self._strategy_map[new_regime],
                candle_index=self._total_candles_processed,
            )
            self.regime_history.append(record)

            switched = True
            logger.info(
                "agent.strategy.regime.switcher.switched",
                old_regime=old_regime.value,
                new_regime=new_regime.value,
                confidence=round(confidence, 4),
                candle_index=self._total_candles_processed,
                strategy_id=record.strategy_id,
            )

        strategy_id = self.get_active_strategy()
        return self.current_regime, strategy_id, switched

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def get_history(self) -> list[dict[str, Any]]:
        """Return regime history as a list of plain dicts for serialisation.

        Returns:
            Each entry contains ``timestamp`` (ISO-8601 string), ``regime``
            (string value), ``confidence`` (float), ``strategy_id`` (string),
            and ``candle_index`` (int).
        """
        return [
            {
                "timestamp": record.timestamp.isoformat(),
                "regime": record.regime.value,
                "confidence": record.confidence,
                "strategy_id": record.strategy_id,
                "candle_index": record.candle_index,
            }
            for record in self.regime_history
        ]

    def reset(self) -> None:
        """Reset switcher state to initial conditions.

        Useful for running multiple backtests through the same switcher
        instance without creating a new object.  The classifier and
        strategy_map are preserved; only the runtime state is cleared.
        """
        self.current_regime = RegimeType.MEAN_REVERTING
        self.candles_since_switch = self._cooldown_candles
        self.regime_history = deque(maxlen=500)
        self._total_candles_processed = 0
        self._cached_last_candle_ts = None
        self._cached_regime_result = None
        logger.debug("agent.strategy.regime.switcher.reset")


# ---------------------------------------------------------------------------
# CLI demo helpers
# ---------------------------------------------------------------------------


def _make_synthetic_candles(n: int, seed: int = 42) -> list[dict]:  # type: ignore[type-arg]
    """Generate a synthetic OHLCV candle stream with regime variation.

    The stream is divided into four equal segments, each mimicking a different
    regime:
    - Segment 1: Strongly trending (large upward drift, tight spread).
    - Segment 2: High volatility (large random swings).
    - Segment 3: Low volatility / mean-reverting (tiny noise).
    - Segment 4: Return to trending (downward drift).

    Args:
        n: Total number of candles to generate.
        seed: Random seed for reproducibility.

    Returns:
        List of OHLCV dicts ordered oldest to newest.
    """
    rng = np.random.default_rng(seed)
    candles: list[dict] = []  # type: ignore[type-arg]
    close = 50000.0
    segment_size = n // 4

    for i in range(n):
        segment = i // segment_size
        if segment == 0:
            # Strong uptrend.
            trend, noise, spread = 30.0, 10.0, 40.0
        elif segment == 1:
            # High volatility — large swings.
            trend, noise, spread = 0.0, 200.0, 400.0
        elif segment == 2:
            # Low volatility — tight price action.
            trend, noise, spread = 0.0, 5.0, 8.0
        else:
            # Downtrend.
            trend, noise, spread = -30.0, 10.0, 40.0

        close = max(close + trend + float(rng.normal(0, noise)), 1.0)
        high = close + abs(float(rng.normal(0, spread * 0.5)))
        low = close - abs(float(rng.normal(0, spread * 0.5)))
        low = min(low, close - 0.01)
        candles.append(
            {
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": float(rng.integers(100, 10000)),
                "timestamp": i,  # logical candle index as timestamp
            }
        )
    return candles


def _train_demo_classifier(candles: list[dict], seed: int = 42) -> RegimeClassifier:  # type: ignore[type-arg]
    """Train a RegimeClassifier on the provided candles for the demo.

    Uses the first 80% of candles for training and the rest for evaluation.

    Args:
        candles: List of OHLCV dicts.
        seed: Random seed for the classifier.

    Returns:
        A fitted RegimeClassifier.
    """
    features, labels = generate_training_data(candles, window=20)

    split_idx = int(len(features) * 0.8)
    X_train = features.iloc[:split_idx].reset_index(drop=True)
    y_train = labels.iloc[:split_idx].reset_index(drop=True)
    X_test = features.iloc[split_idx:].reset_index(drop=True)
    y_test = labels.iloc[split_idx:].reset_index(drop=True)

    clf = RegimeClassifier(seed=seed, use_xgboost=False)
    logger.info("agent.strategy.regime.switcher.demo_classifier_training", n_train=len(X_train))
    clf.train(X_train, y_train)

    metrics = clf.evaluate(X_test, y_test)
    logger.info(
        "switcher.demo_classifier_ready",
        accuracy=round(metrics["accuracy"], 4),
        n_samples=metrics["n_samples"],
    )
    return clf


def _run_demo(n_candles: int = 400, seed: int = 42, window_size: int = 100) -> None:
    """Run the regime switcher against synthetic historical data and print results.

    Simulates a rolling-window decision loop: at each step the switcher
    receives the most recent ``window_size`` candles and decides whether to
    switch strategy.

    Args:
        n_candles: Total number of synthetic candles to generate.
        seed: Random seed (affects both candle generation and classifier).
        window_size: Number of candles in the rolling context window passed
            to the switcher on each step.  Must be >= :data:`MIN_CANDLES_REQUIRED`.
    """
    logger.info("agent.strategy.regime.switcher.demo_starting", n_candles=n_candles, seed=seed, window_size=window_size)

    # Generate synthetic candle stream.
    all_candles = _make_synthetic_candles(n=n_candles, seed=seed)

    # Train a classifier on the full stream (demo only — in production train on
    # historical data separate from the live feed).
    clf = _train_demo_classifier(all_candles, seed=seed)

    # Dummy strategy map: regime → strategy ID.
    strategy_map: dict[RegimeType, str] = {
        RegimeType.TRENDING: "strategy-trending-001",
        RegimeType.MEAN_REVERTING: "strategy-mean-reverting-001",
        RegimeType.HIGH_VOLATILITY: "strategy-high-vol-001",
        RegimeType.LOW_VOLATILITY: "strategy-low-vol-001",
    }

    switcher = RegimeSwitcher(
        classifier=clf,
        strategy_map=strategy_map,
        confidence_threshold=CONFIDENCE_THRESHOLD,
        cooldown_candles=SWITCH_COOLDOWN_CANDLES,
    )

    logger.info(
        "switcher.demo_initialized",
        initial_regime=switcher.current_regime.value,
        confidence_threshold=switcher._confidence_threshold,
        cooldown_candles=switcher._cooldown_candles,
        steps=n_candles - window_size,
    )

    switch_log: list[dict[str, Any]] = []

    # Rolling window: start once enough candles exist for the window.
    for i in range(window_size, n_candles + 1):
        window = all_candles[i - window_size : i]
        regime, strategy_id, switched = switcher.step(window)

        if switched:
            record = switcher.regime_history[-1]
            switch_log.append(
                {
                    "candle": i,
                    "regime": regime.value,
                    "strategy_id": strategy_id,
                    "confidence": record.confidence,
                    "timestamp": record.timestamp.strftime("%H:%M:%S"),
                }
            )
            logger.info(
                "switcher.demo_switch",
                candle=i,
                regime=regime.value,
                confidence=round(record.confidence, 3),
                strategy=strategy_id,
            )

    # Summary.
    logger.info(
        "switcher.demo_complete",
        candles_processed=switcher._total_candles_processed,
        total_switches=len(switcher.regime_history),
        final_regime=switcher.current_regime.value,
        active_strategy=switcher.get_active_strategy(),
        regime_history=[
            {
                "candle": r.candle_index,
                "regime": r.regime.value,
                "confidence": round(r.confidence, 3),
                "strategy": r.strategy_id,
            }
            for r in switcher.regime_history
        ],
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for the regime switcher demo."""
    parser = argparse.ArgumentParser(
        description="Regime switcher demo — trains a classifier on synthetic candles and runs the switcher.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        required=True,
        help="Run the demo against synthetic candle data.",
    )
    parser.add_argument(
        "--candles",
        type=int,
        default=400,
        help="Number of synthetic candles to generate (must be > --window).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for candle generation and classifier training.",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=100,
        help=(
            f"Rolling window size: number of candles passed to the switcher on "
            f"each step.  Must be >= {MIN_CANDLES_REQUIRED}."
        ),
    )

    args = parser.parse_args()

    if args.window < MIN_CANDLES_REQUIRED:
        parser.error(f"--window must be >= {MIN_CANDLES_REQUIRED} (got {args.window})")
    if args.candles <= args.window:
        parser.error(f"--candles must be > --window (candles={args.candles}, window={args.window})")

    _run_demo(n_candles=args.candles, seed=args.seed, window_size=args.window)


if __name__ == "__main__":
    main()
