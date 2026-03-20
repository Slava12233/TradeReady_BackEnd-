"""Ensemble runner — full multi-signal pipeline orchestrator.

Wires the three strategy signal sources (RL, EVOLVED, REGIME) through the
MetaLearner and optional risk overlay to produce a single consolidated trade
decision per symbol per step.

Pipeline (per step)::

    candles
        │
        ├─► RL signal    : PPODeployBridge.predict(obs) → weights → WeightedSignal
        ├─► EVOLVED signal: StrategyGenome RSI/MACD state → WeightedSignal
        ├─► REGIME signal : RegimeSwitcher.step(candles) → WeightedSignal
        │
        ▼
    MetaLearner.combine_all(signals) → ConsensusSignal per symbol
        │
        ├─► [if enable_risk_overlay]
        │       ConsensusSignal → TradeSignal → RiskMiddleware.process_signal()
        │                                     → ExecutionDecision
        │       [if approved] → execute_if_approved() → placed order
        │
        ▼
    StepResult

Modes
-----
- ``backtest``: Creates and drives a platform backtest session.  No real
  orders.  Calls ``run_backtest(start, end)`` to iterate over historical data.
- ``live``: Queries live prices and places real sandbox orders.  Call
  ``step(candles)`` in an external trading loop.

CLI::

    python -m agent.strategies.ensemble.run \\
        --mode backtest \\
        --base-url http://localhost:8000 \\
        [--seed 42] \\
        [--symbols BTCUSDT ETHUSDT] \\
        [--days 7]
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field

from agent.strategies.ensemble.config import EnsembleConfig
from agent.strategies.ensemble.meta_learner import MetaLearner
from agent.strategies.ensemble.signals import (
    ConsensusSignal,
    SignalSource,
    TradeAction,
    WeightedSignal,
)

log = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Candle interval in seconds used for all backtest sessions created by this runner.
_CANDLE_INTERVAL: int = 60  # 1-minute candles

# Starting balance for any backtest session created by the runner.
_STARTING_BALANCE: str = "10000"

# Per-symbol default order quantities.  Small test sizes that stay well inside
# platform risk limits while validating the full pipeline end-to-end.
_ORDER_QTY: dict[str, str] = {
    "BTCUSDT": "0.0001",
    "ETHUSDT": "0.001",
    "SOLUSDT": "0.01",
}
_DEFAULT_QTY: str = "0.001"

# MA windows for the candle-based feature extraction used by evolved/regime signals.
_MA_FAST: int = 5
_MA_SLOW: int = 20


# ── Pydantic output models ────────────────────────────────────────────────────


class SignalContribution(BaseModel):
    """Per-source signal summary for a single step and symbol.

    Args:
        source: Which strategy system produced this signal.
        action: The discrete direction emitted (BUY, SELL, HOLD).
        confidence: Signal confidence (0.0–1.0).
        enabled: Whether this source was enabled for this step.
        metadata: Source-specific context carried through from the signal.
    """

    model_config = ConfigDict(frozen=True)

    source: str
    action: str
    confidence: float = Field(ge=0.0, le=1.0)
    enabled: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class StepResult(BaseModel):
    """Full audit record for one ensemble decision step.

    Args:
        step_number: Zero-based step counter within a backtest or live session.
        timestamp: ISO-8601 UTC timestamp when this step was processed.
        symbol_results: Per-symbol breakdown of signals, consensus, and execution.
        total_signals: Total number of WeightedSignal instances generated.
        signals_acted_on: Number of symbols where a non-HOLD action was approved.
        orders_placed: Number of orders successfully submitted to the platform.
        orders_vetoed: Number of orders blocked by the risk overlay.
        error: Non-None if an unrecoverable error occurred during this step.
    """

    model_config = ConfigDict(frozen=True)

    step_number: int
    timestamp: str
    symbol_results: list["SymbolStepResult"]
    total_signals: int
    signals_acted_on: int
    orders_placed: int
    orders_vetoed: int
    error: str | None = None


class SymbolStepResult(BaseModel):
    """Signals, consensus, and execution result for one symbol in one step.

    Args:
        symbol: Trading pair.
        contributions: Per-source signal details.
        consensus_action: Final action after MetaLearner voting.
        consensus_confidence: Combined weighted confidence.
        agreement_rate: Fraction of active sources that agreed with the winner.
        risk_action: 'APPROVED', 'RESIZED', 'VETOED', or 'SKIPPED' (risk disabled).
        final_size_pct: Position size fraction after risk overlay (0 if vetoed/skipped).
        order_placed: True if an order was successfully placed.
        order_id: Platform order ID if placed.
        error: Non-None if an error occurred for this symbol.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    contributions: list[SignalContribution]
    consensus_action: str
    consensus_confidence: float = Field(ge=0.0, le=1.0)
    agreement_rate: float = Field(ge=0.0, le=1.0)
    risk_action: str = "SKIPPED"
    final_size_pct: float = Field(default=0.0, ge=0.0, le=1.0)
    order_placed: bool = False
    order_id: str | None = None
    error: str | None = None


class SourceStats(BaseModel):
    """Aggregated performance statistics for one signal source over a session.

    Args:
        source: Signal source name (rl, evolved, regime).
        total_steps: Number of steps this source was active.
        buy_signals: Number of BUY actions emitted.
        sell_signals: Number of SELL actions emitted.
        hold_signals: Number of HOLD actions emitted.
        mean_confidence: Mean confidence across all non-HOLD signals.
        agreement_with_consensus: Fraction of steps where this source agreed
            with the final consensus action.
    """

    model_config = ConfigDict(frozen=False)

    source: str
    total_steps: int = 0
    buy_signals: int = 0
    sell_signals: int = 0
    hold_signals: int = 0
    mean_confidence: float = 0.0
    agreement_with_consensus: float = 0.0


class EnsembleReport(BaseModel):
    """Summary of a complete ensemble backtest or live session.

    Args:
        session_id: Backtest session UUID or 'live'.
        mode: 'backtest' or 'live'.
        start_time: ISO-8601 session start timestamp.
        end_time: ISO-8601 session end timestamp.
        total_steps: Total steps executed.
        total_orders_placed: Orders successfully submitted.
        total_orders_vetoed: Orders blocked by the risk overlay.
        overall_agreement_rate: Mean agreement rate across all steps and symbols.
        source_stats: Per-source contribution statistics.
        config_summary: Snapshot of active config flags for this session.
    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    mode: str
    start_time: str
    end_time: str
    total_steps: int
    total_orders_placed: int
    total_orders_vetoed: int
    overall_agreement_rate: float = Field(ge=0.0, le=1.0)
    source_stats: list[SourceStats]
    config_summary: dict[str, Any]


# ── Internal helpers ──────────────────────────────────────────────────────────


def _sma(closes: list[float], window: int) -> float | None:
    """Return the simple moving average of the last *window* close prices.

    Args:
        closes: Chronologically ordered close prices.
        window: Window length.

    Returns:
        SMA value, or None when fewer than *window* values are available.
    """
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _extract_closes(candles: list[dict[str, Any]]) -> list[float]:
    """Extract close prices from a list of OHLCV dicts.

    Args:
        candles: List of candle dicts with a 'close' key.

    Returns:
        Chronologically ordered close prices.  Empty list on bad input.
    """
    closes: list[float] = []
    for c in candles:
        raw = c.get("close")
        if raw is not None:
            try:
                closes.append(float(raw))
            except (ValueError, TypeError):
                pass
    return closes


def _compute_rsi(closes: list[float], period: int = 14) -> float | None:
    """Compute the Relative Strength Index for the most recent period.

    Uses a simple average of gains and losses (non-smoothed Wilder's RSI).

    Args:
        closes: Chronologically ordered close prices.
        period: RSI look-back period.

    Returns:
        RSI value in [0, 100], or None if insufficient data.
    """
    if len(closes) < period + 1:
        return None
    recent = closes[-(period + 1):]
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(recent)):
        delta = recent[i] - recent[i - 1]
        if delta > 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-delta)
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_macd_histogram(
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
) -> float | None:
    """Compute the MACD histogram (MACD line - signal line).

    Uses a simple proxy of EMA(fast) - EMA(slow) without a full 9-period
    signal EMA, which is adequate for a directional bias check.

    Args:
        closes: Chronologically ordered close prices.
        fast: Fast EMA period.
        slow: Slow EMA period.

    Returns:
        MACD histogram value, or None if insufficient data.
    """
    if len(closes) < slow:
        return None
    # Compute EMAs using the standard multiplier k = 2/(period+1).
    def _ema(prices: list[float], period: int) -> float:
        k = 2.0 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = p * k + ema * (1 - k)
        return ema

    ema_fast = _ema(closes[-fast:], fast)
    ema_slow = _ema(closes[-slow:], slow)
    return ema_fast - ema_slow


# ── EnsembleRunner ────────────────────────────────────────────────────────────


class EnsembleRunner:
    """Orchestrates three signal sources into a single ensemble trade decision.

    Wires PPODeployBridge (RL), StrategyGenome (EVOLVED), and RegimeSwitcher
    (REGIME) through MetaLearner weighted voting and an optional RiskMiddleware
    gate into a complete, auditable trade decision per step.

    Args:
        config: :class:`~agent.strategies.ensemble.config.EnsembleConfig`
            instance with all hyperparameters, paths, and enable flags.
        sdk_client: An ``AsyncAgentExchangeClient`` instance (or compatible
            async client).  Required when ``enable_risk_overlay=True`` (the
            RiskMiddleware uses it to fetch portfolio state and place orders).
            Can be ``None`` in backtest mode when risk overlay is disabled.
        rest_client: An ``httpx.AsyncClient`` pointed at the platform REST API.
            Used for backtest session management (create, start, step, results)
            and candle fetching.  Can be ``None`` in live mode.

    Example::

        config = EnsembleConfig(mode="backtest", enable_risk_overlay=False)
        async with httpx.AsyncClient(base_url="http://localhost:8000",
                                     headers={"X-API-Key": "ak_live_..."}) as rest:
            runner = EnsembleRunner(config=config, sdk_client=None, rest_client=rest)
            await runner.initialize()
            report = await runner.run_backtest(start="2024-02-23T00:00:00Z",
                                               end="2024-03-01T00:00:00Z")
    """

    def __init__(
        self,
        config: EnsembleConfig,
        sdk_client: Any,
        rest_client: Any,
    ) -> None:
        self._config = config
        self._sdk = sdk_client
        self._rest = rest_client

        # Parsed weights keyed by SignalSource enum for MetaLearner.
        self._signal_source_weights: dict[SignalSource, float] = {}

        # Loaded component references (populated in initialize()).
        self._rl_model: Any = None         # SB3 PPO model
        self._evolved_genome: Any = None   # StrategyGenome champion
        self._regime_switcher: Any = None  # RegimeSwitcher instance
        self._risk_middleware: Any = None  # RiskMiddleware instance
        self._meta_learner: MetaLearner | None = None

        # Runtime state.
        self._step_counter: int = 0
        self._step_history: deque[StepResult] = deque(maxlen=500)
        self._session_start_time: str = datetime.now(UTC).isoformat()

        # Per-symbol current portfolio weights for RL signal conversion.
        self._current_weights: dict[str, dict[str, float]] = {}

    # ── Initialisation ────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Load all enabled ML components and wire the MetaLearner.

        Must be called once before any call to :meth:`step` or
        :meth:`run_backtest`.  Safe to call multiple times — re-initialises
        only when state is clean.

        Raises:
            RuntimeError: If a required model file does not exist and no
                fallback is available.
        """
        log.info(
            "ensemble_runner.initialize",
            mode=self._config.mode,
            enable_rl=self._config.enable_rl_signal,
            enable_evolved=self._config.enable_evolved_signal,
            enable_regime=self._config.enable_regime_signal,
            enable_risk=self._config.enable_risk_overlay,
        )

        # Build source weights from config (raw — MetaLearner normalises).
        raw_weights = self._config.weights
        self._signal_source_weights = {}
        for source in SignalSource:
            w = raw_weights.get(source.value, 1.0 / len(SignalSource))
            self._signal_source_weights[source] = w

        # Construct MetaLearner.
        self._meta_learner = MetaLearner(
            weights=self._signal_source_weights,
            confidence_threshold=self._config.confidence_threshold,
            min_agreement_rate=self._config.min_agreement_rate,
        )
        log.info(
            "ensemble_runner.meta_learner_ready",
            weights={s.value: round(w, 4) for s, w in self._signal_source_weights.items()},
        )

        # Load RL model.
        if self._config.enable_rl_signal:
            self._rl_model = await self._load_rl_model()

        # Load evolved champion genome.
        if self._config.enable_evolved_signal:
            self._evolved_genome = self._load_evolved_genome()

        # Load regime switcher.
        if self._config.enable_regime_signal:
            self._regime_switcher = await self._load_regime_switcher()

        # Wire risk middleware.
        if self._config.enable_risk_overlay and self._sdk is not None:
            self._risk_middleware = self._build_risk_middleware()

        log.info("ensemble_runner.initialized")

    async def _load_rl_model(self) -> Any:
        """Load the SB3 PPO model from disk.

        Tries the configured path first, then auto-discovers ppo_seed*.zip
        files in the default RL models directory.

        Returns:
            Loaded SB3 PPO model or None if no model file is found.
        """
        try:
            from stable_baselines3 import PPO  # noqa: PLC0415
        except ImportError:
            log.warning(
                "ensemble_runner.rl_model_skipped",
                reason="stable-baselines3 not installed",
            )
            return None

        model_path_str = self._config.rl_model_path.strip()

        if not model_path_str:
            # Auto-discover: check default RL models directory.
            default_dir = Path(__file__).parent.parent / "rl" / "models"
            candidate = default_dir / "ppo_seed42.zip"
            if candidate.exists():
                model_path_str = str(candidate)
            else:
                found = sorted(default_dir.glob("ppo_seed*.zip"))
                if found:
                    model_path_str = str(found[0])

        if not model_path_str or not Path(model_path_str).exists():
            log.warning(
                "ensemble_runner.rl_model_not_found",
                hint="Train a model with: python -m agent.strategies.rl.runner",
            )
            return None

        log.info("ensemble_runner.loading_rl_model", path=model_path_str)
        # Verify SHA-256 integrity before deserializing the pickle-based .zip.
        try:
            from agent.strategies.checksum import SecurityError, verify_checksum  # noqa: PLC0415

            verify_checksum(Path(model_path_str))
        except SecurityError as exc_sec:
            log.error(
                "ensemble_runner.rl_model_checksum_mismatch",
                path=model_path_str,
                error=str(exc_sec),
            )
            return None
        except Exception as exc_cs:  # noqa: BLE001
            log.warning(
                "ensemble_runner.rl_model_checksum_check_failed",
                path=model_path_str,
                error=str(exc_cs),
            )
        model = PPO.load(model_path_str)
        log.info("ensemble_runner.rl_model_loaded", path=model_path_str)
        return model

    def _load_evolved_genome(self) -> Any:
        """Load the evolved champion genome from a JSON file or use a default.

        Returns:
            A :class:`~agent.strategies.evolutionary.genome.StrategyGenome`
            instance representing the champion strategy.
        """
        from agent.strategies.evolutionary.genome import StrategyGenome  # noqa: PLC0415

        genome_path_str = self._config.evolved_genome_path.strip()

        if genome_path_str and Path(genome_path_str).exists():
            log.info("ensemble_runner.loading_evolved_genome", path=genome_path_str)
            try:
                genome_data = json.loads(Path(genome_path_str).read_text(encoding="utf-8"))
                genome = StrategyGenome(**genome_data)
                log.info("ensemble_runner.evolved_genome_loaded", path=genome_path_str)
                return genome
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "ensemble_runner.evolved_genome_load_failed",
                    path=genome_path_str,
                    error=str(exc),
                    fallback="random_seed42",
                )

        # Fallback: deterministic default genome with seed 42.
        log.info("ensemble_runner.evolved_genome_fallback", seed=42)
        return StrategyGenome.from_random(seed=42)

    async def _load_regime_switcher(self) -> Any:
        """Load the regime classifier and construct a RegimeSwitcher.

        Tries the configured .joblib path first.  Falls back to training a
        lightweight RandomForest on synthetic candles if no model file exists.

        Returns:
            A :class:`~agent.strategies.regime.switcher.RegimeSwitcher` instance.
        """
        from agent.strategies.regime.classifier import RegimeClassifier  # noqa: PLC0415
        from agent.strategies.regime.labeler import RegimeType  # noqa: PLC0415
        from agent.strategies.regime.switcher import RegimeSwitcher  # noqa: PLC0415

        # Default strategy map: every regime maps to an empty string because
        # the EnsembleRunner uses the regime as a signal source, not to dispatch
        # to separate platform strategy IDs.  Callers that need the strategy ID
        # can override this via a custom RegimeSwitcher passed in externally.
        strategy_map: dict[RegimeType, str] = {
            RegimeType.TRENDING: "regime-trending",
            RegimeType.MEAN_REVERTING: "regime-mean-reverting",
            RegimeType.HIGH_VOLATILITY: "regime-high-vol",
            RegimeType.LOW_VOLATILITY: "regime-low-vol",
        }

        regime_path_str = self._config.regime_model_path.strip()
        clf: RegimeClassifier | None = None

        if regime_path_str and Path(regime_path_str).exists():
            log.info("ensemble_runner.loading_regime_classifier", path=regime_path_str)
            try:
                clf = RegimeClassifier.load(Path(regime_path_str))
                log.info("ensemble_runner.regime_classifier_loaded", path=regime_path_str)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "ensemble_runner.regime_classifier_load_failed",
                    path=regime_path_str,
                    error=str(exc),
                    fallback="synthetic_training",
                )

        if clf is None:
            # Fallback: train on synthetic data.  This is adequate for
            # smoke-testing the pipeline without a pre-trained model.
            log.info(
                "ensemble_runner.regime_classifier_fallback",
                reason="no model file found or load failed",
            )
            clf = await self._train_fallback_regime_classifier()

        switcher = RegimeSwitcher(
            classifier=clf,
            strategy_map=strategy_map,
        )
        return switcher

    async def _train_fallback_regime_classifier(self) -> Any:
        """Train a lightweight RandomForest on synthetic candles.

        Used when no regime model file is available.  Provides a functional
        (though not optimal) regime signal for end-to-end pipeline testing.

        The ``clf.train()`` call blocks the CPU for 1-3 seconds (RandomForest
        fitting on 480 synthetic samples).  It is offloaded to a thread pool
        via ``asyncio.to_thread()`` to avoid freezing the event loop.

        Returns:
            A fitted :class:`~agent.strategies.regime.classifier.RegimeClassifier`.
        """
        from agent.strategies.regime.classifier import RegimeClassifier  # noqa: PLC0415
        from agent.strategies.regime.labeler import generate_training_data  # noqa: PLC0415
        from agent.strategies.regime.switcher import _make_synthetic_candles  # noqa: PLC0415

        log.info("ensemble_runner.training_fallback_regime_classifier")
        candles = _make_synthetic_candles(n=600, seed=42)
        features, labels = generate_training_data(candles, window=20)

        split_idx = int(len(features) * 0.8)
        clf = RegimeClassifier(seed=42, use_xgboost=False)
        await asyncio.to_thread(
            clf.train,
            features.iloc[:split_idx].reset_index(drop=True),
            labels.iloc[:split_idx].reset_index(drop=True),
        )
        log.info("ensemble_runner.fallback_regime_classifier_trained")
        return clf

    def _build_risk_middleware(self) -> Any:
        """Construct the RiskMiddleware from platform defaults.

        Returns:
            A :class:`~agent.strategies.risk.middleware.RiskMiddleware` instance.
        """
        from agent.strategies.risk import (  # noqa: PLC0415
            DynamicSizer,
            RiskAgent,
            RiskConfig,
            SizerConfig,
            VetoPipeline,
        )

        risk_config = RiskConfig()
        sizer_config = SizerConfig()

        middleware = RiskMiddleware(
            risk_agent=RiskAgent(config=risk_config),
            veto_pipeline=VetoPipeline(config=risk_config, existing_positions=[]),
            dynamic_sizer=DynamicSizer(config=sizer_config),
            sdk_client=self._sdk,
        )
        log.info("ensemble_runner.risk_middleware_ready")
        return middleware

    # ── Signal generation ─────────────────────────────────────────────────────

    async def _get_rl_signals(
        self,
        candles_by_symbol: dict[str, list[dict[str, Any]]],
    ) -> list[WeightedSignal]:
        """Generate RL WeightedSignals from the loaded PPO model.

        Uses a simplified zero-padded observation (matches deploy.py logic).
        Falls back to HOLD signals with zero confidence if the model is
        unavailable or prediction fails.

        The ``model.predict()`` call runs PyTorch inference (5-50 ms) on the
        CPU and is offloaded to a thread pool via ``asyncio.to_thread()`` to
        avoid blocking the event loop during each ensemble step.

        Args:
            candles_by_symbol: Symbol to recent candle list mapping.

        Returns:
            One WeightedSignal per symbol from SignalSource.RL.
        """
        import numpy as np  # noqa: PLC0415

        symbols = self._config.symbols

        if self._rl_model is None:
            # Source disabled or model not loaded — emit offline HOLD signals.
            return [
                WeightedSignal(
                    source=SignalSource.RL,
                    symbol=sym,
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    metadata={"reason": "model_unavailable"},
                )
                for sym in symbols
            ]

        # Build a simplified observation from the available data.
        # We use the same zero-padded approach as deploy.py._build_observation_from_platform.
        n_assets = len(symbols)
        lookback = 30  # matches RLConfig default
        candle_features = 9
        fe_periods = 3
        fe_features_per_period = 2
        scalar_features = 2
        candle_dim = lookback * candle_features * n_assets
        fe_dim = fe_periods * fe_features_per_period * n_assets
        obs_dim = candle_dim + fe_dim + scalar_features
        obs = np.zeros(obs_dim, dtype=np.float32)
        # Scalar features: approximate balance ratio = 0.5 (no live data here)
        obs[-2] = 0.5
        obs[-1] = 0.5

        try:
            target_weights, _ = await asyncio.to_thread(
                self._rl_model.predict, obs, deterministic=True
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("ensemble_runner.rl_predict_failed", error=str(exc))
            return [
                WeightedSignal(
                    source=SignalSource.RL,
                    symbol=sym,
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    metadata={"error": str(exc)},
                )
                for sym in symbols
            ]

        # Retrieve current portfolio weights (default 0 if unavailable).
        current_weights = self._current_weights.get("portfolio", {})

        return MetaLearner.rl_weights_to_signals(
            target_weights=target_weights,
            symbols=symbols,
            current_weights=current_weights,
        )

    def _get_evolved_signals(
        self,
        candles_by_symbol: dict[str, list[dict[str, Any]]],
    ) -> list[WeightedSignal]:
        """Generate EVOLVED WeightedSignals from the champion genome.

        Computes RSI and MACD histogram from the most recent candles for each
        symbol and applies the genome's entry/exit thresholds.

        Args:
            candles_by_symbol: Symbol to recent candle list mapping.

        Returns:
            One WeightedSignal per symbol from SignalSource.EVOLVED.
        """
        if self._evolved_genome is None:
            return [
                WeightedSignal(
                    source=SignalSource.EVOLVED,
                    symbol=sym,
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    metadata={"reason": "genome_unavailable"},
                )
                for sym in self._config.symbols
            ]

        signals: list[WeightedSignal] = []
        for sym in self._config.symbols:
            candles = candles_by_symbol.get(sym, [])
            closes = _extract_closes(candles)

            rsi = _compute_rsi(closes, period=14)
            macd_hist = _compute_macd_histogram(
                closes,
                fast=self._evolved_genome.macd_fast,
                slow=self._evolved_genome.macd_slow,
            )

            if rsi is None or macd_hist is None:
                signals.append(
                    WeightedSignal(
                        source=SignalSource.EVOLVED,
                        symbol=sym,
                        action=TradeAction.HOLD,
                        confidence=0.0,
                        metadata={"reason": "insufficient_candles", "n_candles": len(candles)},
                    )
                )
            else:
                signals.append(
                    MetaLearner.genome_to_signals(
                        rsi_value=rsi,
                        macd_histogram=macd_hist,
                        genome_rsi_oversold=self._evolved_genome.rsi_oversold,
                        genome_rsi_overbought=self._evolved_genome.rsi_overbought,
                        symbol=sym,
                    )
                )

        return signals

    def _get_regime_signals(
        self,
        candles_by_symbol: dict[str, list[dict[str, Any]]],
    ) -> list[WeightedSignal]:
        """Generate REGIME WeightedSignals from the regime switcher.

        Uses the candles for the first available symbol to detect the current
        regime (regime detection is market-wide, not per-symbol), then maps
        the same regime signal to all configured symbols.

        Args:
            candles_by_symbol: Symbol to recent candle list mapping.

        Returns:
            One WeightedSignal per symbol from SignalSource.REGIME.
        """
        if self._regime_switcher is None:
            return [
                WeightedSignal(
                    source=SignalSource.REGIME,
                    symbol=sym,
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    metadata={"reason": "switcher_unavailable"},
                )
                for sym in self._config.symbols
            ]

        # Use the first symbol's candles for regime detection (BTC is canonical).
        reference_sym = self._config.symbols[0]
        reference_candles = candles_by_symbol.get(reference_sym, [])

        if len(reference_candles) < 50:
            # Insufficient candles for classifier warm-up.
            return [
                WeightedSignal(
                    source=SignalSource.REGIME,
                    symbol=sym,
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    metadata={
                        "reason": "insufficient_candles",
                        "n_candles": len(reference_candles),
                    },
                )
                for sym in self._config.symbols
            ]

        try:
            regime, confidence = self._regime_switcher.detect_regime(reference_candles)
        except Exception as exc:  # noqa: BLE001
            log.warning("ensemble_runner.regime_detect_failed", error=str(exc))
            return [
                WeightedSignal(
                    source=SignalSource.REGIME,
                    symbol=sym,
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    metadata={"error": str(exc)},
                )
                for sym in self._config.symbols
            ]

        signals: list[WeightedSignal] = []
        for sym in self._config.symbols:
            signals.append(
                MetaLearner.regime_to_signals(
                    regime_type=regime,
                    regime_confidence=confidence,
                    symbol=sym,
                )
            )
        return signals

    # ── Core step logic ───────────────────────────────────────────────────────

    async def step(
        self,
        candles_by_symbol: dict[str, list[dict[str, Any]]],
    ) -> StepResult:
        """Run the full ensemble pipeline for one decision step.

        Pipeline:
          1. Generate RL signal (PPO weights → WeightedSignal per symbol).
          2. Generate EVOLVED signal (genome RSI/MACD → WeightedSignal per symbol).
          3. Generate REGIME signal (regime switcher → WeightedSignal per symbol).
          4. Combine all signals per symbol via MetaLearner.
          5. For each non-HOLD consensus: optionally apply risk overlay.
          6. Execute approved orders.
          7. Return StepResult.

        Args:
            candles_by_symbol: Mapping from symbol to a recent OHLCV candle list
                (ordered oldest to newest).  Must contain at least
                ``config.candle_window`` entries for meaningful regime/evolved signals.

        Returns:
            :class:`StepResult` with full per-symbol audit trail.
        """
        assert self._meta_learner is not None, (
            "EnsembleRunner.initialize() must be called before step()."
        )

        ts = datetime.now(UTC).isoformat()
        step_num = self._step_counter
        self._step_counter += 1

        log.debug(
            "ensemble_runner.step.start",
            step=step_num,
            symbols=self._config.symbols,
        )

        # ── 1–3. Collect signals from all enabled sources ──────────────────
        all_signals: list[WeightedSignal] = []

        if self._config.enable_rl_signal:
            rl_signals = await self._get_rl_signals(candles_by_symbol)
            all_signals.extend(rl_signals)
        else:
            all_signals.extend(
                WeightedSignal(
                    source=SignalSource.RL,
                    symbol=sym,
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    metadata={"reason": "source_disabled"},
                )
                for sym in self._config.symbols
            )

        if self._config.enable_evolved_signal:
            evolved_signals = self._get_evolved_signals(candles_by_symbol)
            all_signals.extend(evolved_signals)
        else:
            all_signals.extend(
                WeightedSignal(
                    source=SignalSource.EVOLVED,
                    symbol=sym,
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    metadata={"reason": "source_disabled"},
                )
                for sym in self._config.symbols
            )

        if self._config.enable_regime_signal:
            regime_signals = self._get_regime_signals(candles_by_symbol)
            all_signals.extend(regime_signals)
        else:
            all_signals.extend(
                WeightedSignal(
                    source=SignalSource.REGIME,
                    symbol=sym,
                    action=TradeAction.HOLD,
                    confidence=0.0,
                    metadata={"reason": "source_disabled"},
                )
                for sym in self._config.symbols
            )

        # ── 4. Combine signals via MetaLearner ─────────────────────────────
        consensus_signals: list[ConsensusSignal] = self._meta_learner.combine_all(all_signals)

        # ── 5–6. Risk overlay and execution ───────────────────────────────
        symbol_results: list[SymbolStepResult] = []
        total_placed = 0
        total_vetoed = 0

        for consensus in consensus_signals:
            sym = consensus.symbol

            # Build per-source contribution records.
            contributions: list[SignalContribution] = []
            sym_signals = [s for s in all_signals if s.symbol == sym]
            for sig in sym_signals:
                enabled = (
                    (sig.source == SignalSource.RL and self._config.enable_rl_signal)
                    or (sig.source == SignalSource.EVOLVED and self._config.enable_evolved_signal)
                    or (sig.source == SignalSource.REGIME and self._config.enable_regime_signal)
                )
                contributions.append(
                    SignalContribution(
                        source=sig.source.value,
                        action=sig.action.value,
                        confidence=sig.confidence,
                        enabled=enabled,
                        metadata=sig.metadata,
                    )
                )

            # Default: HOLD — no execution.
            risk_action = "SKIPPED"
            final_size_pct: float = 0.0
            order_placed = False
            order_id: str | None = None
            sym_error: str | None = None

            if consensus.action != TradeAction.HOLD:
                if self._config.enable_risk_overlay and self._risk_middleware is not None:
                    risk_action, final_size_pct, order_placed, order_id, sym_error = (
                        await self._route_through_risk(consensus)
                    )
                    if risk_action == "APPROVED" or risk_action == "RESIZED":
                        if order_placed:
                            total_placed += 1
                        else:
                            total_vetoed += 1
                    elif risk_action == "VETOED":
                        total_vetoed += 1
                else:
                    # Risk overlay disabled — optimistically mark as approved.
                    risk_action = "APPROVED"
                    final_size_pct = self._config.risk_base_size_pct

            symbol_results.append(
                SymbolStepResult(
                    symbol=sym,
                    contributions=contributions,
                    consensus_action=consensus.action.value,
                    consensus_confidence=consensus.combined_confidence,
                    agreement_rate=consensus.agreement_rate,
                    risk_action=risk_action,
                    final_size_pct=final_size_pct,
                    order_placed=order_placed,
                    order_id=order_id,
                    error=sym_error,
                )
            )

        signals_acted_on = sum(
            1 for sr in symbol_results if sr.consensus_action != TradeAction.HOLD.value
        )

        result = StepResult(
            step_number=step_num,
            timestamp=ts,
            symbol_results=symbol_results,
            total_signals=len(all_signals),
            signals_acted_on=signals_acted_on,
            orders_placed=total_placed,
            orders_vetoed=total_vetoed,
        )
        self._step_history.append(result)

        log.info(
            "ensemble_runner.step.complete",
            step=step_num,
            acted_on=signals_acted_on,
            placed=total_placed,
            vetoed=total_vetoed,
        )
        return result

    async def _route_through_risk(
        self,
        consensus: ConsensusSignal,
    ) -> tuple[str, float, bool, str | None, str | None]:
        """Pass a non-HOLD ConsensusSignal through the RiskMiddleware.

        Converts the ConsensusSignal to a TradeSignal, processes it through
        the full risk pipeline, and optionally executes the order.

        Args:
            consensus: A non-HOLD :class:`ConsensusSignal` for one symbol.

        Returns:
            Tuple of (risk_action, final_size_pct, order_placed, order_id, error).
        """
        from agent.strategies.risk.veto import TradeSignal  # noqa: PLC0415

        side = "buy" if consensus.action == TradeAction.BUY else "sell"
        signal = TradeSignal(
            symbol=consensus.symbol,
            side=side,
            size_pct=self._config.risk_base_size_pct,
            confidence=consensus.combined_confidence,
        )

        try:
            decision = await self._risk_middleware.process_signal(signal)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "ensemble_runner.risk_process_failed",
                symbol=consensus.symbol,
                error=str(exc),
            )
            return "VETOED", 0.0, False, None, str(exc)

        if decision.veto_decision.action == "VETOED":
            return "VETOED", 0.0, False, None, None

        # Execute the approved/resized order.
        try:
            final_decision = await self._risk_middleware.execute_if_approved(decision)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "ensemble_runner.risk_execute_failed",
                symbol=consensus.symbol,
                error=str(exc),
            )
            return decision.veto_decision.action, decision.final_size_pct, False, None, str(exc)

        return (
            decision.veto_decision.action,
            final_decision.final_size_pct,
            final_decision.executed,
            final_decision.order_id,
            final_decision.error,
        )

    # ── Backtest orchestration ────────────────────────────────────────────────

    async def run_backtest(
        self,
        start: str,
        end: str,
    ) -> "EnsembleReport":
        """Drive a complete backtest using the ensemble pipeline.

        Creates and starts a backtest session, iterates through up to
        ``config.max_iterations`` trading decisions, then returns an
        :class:`EnsembleReport`.

        Args:
            start: ISO-8601 UTC start timestamp (e.g. ``"2024-02-23T00:00:00Z"``).
            end: ISO-8601 UTC end timestamp.

        Returns:
            :class:`EnsembleReport` with full performance and source statistics.

        Raises:
            RuntimeError: If the backtest REST client is not available.
        """
        assert self._meta_learner is not None, (
            "EnsembleRunner.initialize() must be called before run_backtest()."
        )
        if self._rest is None:
            raise RuntimeError("rest_client is required for backtest mode.")

        session_start_ts = datetime.now(UTC).isoformat()
        self._step_history.clear()
        self._step_counter = 0

        log.info(
            "ensemble_runner.backtest.start",
            start=start,
            end=end,
            symbols=self._config.symbols,
        )

        # ── Create and start backtest session ──────────────────────────────
        session_id: str | None = None
        try:
            create_resp = await self._rest.post(
                "/api/v1/backtest/create",
                json={
                    "start_time": start,
                    "end_time": end,
                    "pairs": self._config.symbols,
                    "candle_interval": _CANDLE_INTERVAL,
                    "starting_balance": _STARTING_BALANCE,
                    "strategy_label": "ensemble_runner",
                },
            )
            create_resp.raise_for_status()
            session_id = create_resp.json().get("session_id")
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            log.error("ensemble_runner.backtest.create_failed", error=str(exc))
            return self._build_report(
                session_id="error",
                start_time=session_start_ts,
                end_time=datetime.now(UTC).isoformat(),
            )

        if not session_id:
            log.error("ensemble_runner.backtest.no_session_id")
            return self._build_report(
                session_id="error",
                start_time=session_start_ts,
                end_time=datetime.now(UTC).isoformat(),
            )

        try:
            start_resp = await self._rest.post(f"/api/v1/backtest/{session_id}/start")
            start_resp.raise_for_status()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            log.error(
                "ensemble_runner.backtest.start_failed",
                session_id=session_id,
                error=str(exc),
            )
            return self._build_report(
                session_id=session_id,
                start_time=session_start_ts,
                end_time=datetime.now(UTC).isoformat(),
            )

        log.info("ensemble_runner.backtest.session_started", session_id=session_id)

        # ── Trading loop ───────────────────────────────────────────────────
        loop_done = False
        for _iteration in range(self._config.max_iterations):
            if loop_done:
                break

            # Fetch current candles for all symbols concurrently.
            # return_exceptions=True ensures one failed symbol does not cancel others.
            async def _fetch_candles(sym: str) -> tuple[str, list[dict[str, Any]] | Exception]:
                try:
                    candles_resp = await self._rest.get(
                        f"/api/v1/backtest/{session_id}/market/candles/{sym}",
                        params={"interval": _CANDLE_INTERVAL, "limit": self._config.candle_window},
                    )
                    candles_resp.raise_for_status()
                    return sym, candles_resp.json().get("candles", [])
                except httpx.HTTPStatusError as exc:
                    return sym, exc
                except httpx.RequestError as exc:
                    return sym, exc

            fetch_tasks = [_fetch_candles(sym) for sym in self._config.symbols]
            fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            candles_by_symbol: dict[str, list[dict[str, Any]]] = {}
            for fetch_result in fetch_results:
                # asyncio.gather with return_exceptions=True wraps coroutine-level
                # exceptions; inner tuple exceptions are returned by the coroutine.
                if isinstance(fetch_result, Exception):
                    log.warning(
                        "ensemble_runner.backtest.candle_gather_error",
                        error=str(fetch_result),
                    )
                    continue

                sym, payload = fetch_result
                if isinstance(payload, httpx.HTTPStatusError):
                    if payload.response.status_code in (404, 409, 410):
                        loop_done = True
                        break
                    log.warning(
                        "ensemble_runner.backtest.candle_fetch_failed",
                        sym=sym,
                        error=str(payload),
                    )
                elif isinstance(payload, httpx.RequestError):
                    log.warning(
                        "ensemble_runner.backtest.candle_request_failed",
                        sym=sym,
                        error=str(payload),
                    )
                else:
                    candles_by_symbol[sym] = payload

            if loop_done:
                break

            # Run ensemble step.
            step_result = await self.step(candles_by_symbol)

            # Execute non-HOLD, risk-approved orders through the backtest API.
            # (When risk overlay is disabled we still place orders manually.)
            if not self._config.enable_risk_overlay:
                await self._place_backtest_orders(session_id, step_result)

            # Advance the backtest clock.
            try:
                step_resp = await self._rest.post(
                    f"/api/v1/backtest/{session_id}/step/batch",
                    json={"steps": self._config.batch_size},
                )
                step_resp.raise_for_status()
                if step_resp.json().get("is_complete"):
                    loop_done = True
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (404, 409, 410):
                    loop_done = True
                else:
                    log.warning(
                        "ensemble_runner.backtest.step_failed",
                        session_id=session_id,
                        error=str(exc),
                    )
                    break
            except httpx.RequestError as exc:
                log.warning(
                    "ensemble_runner.backtest.step_request_failed",
                    session_id=session_id,
                    error=str(exc),
                )
                break

        log.info(
            "ensemble_runner.backtest.complete",
            session_id=session_id,
            steps=self._step_counter,
        )

        return self._build_report(
            session_id=session_id,
            start_time=session_start_ts,
            end_time=datetime.now(UTC).isoformat(),
        )

    async def _place_backtest_orders(
        self,
        session_id: str,
        step_result: StepResult,
    ) -> None:
        """Place approved orders into the backtest session via the REST API.

        Called only when ``enable_risk_overlay=False`` — in that case the
        step() method marks risk_action as 'APPROVED' but does not actually
        submit orders (no SDK available).  This method submits them.

        Args:
            session_id: Active backtest session UUID.
            step_result: The step result containing per-symbol decisions.
        """
        if self._rest is None:
            return

        for sr in step_result.symbol_results:
            if sr.consensus_action == TradeAction.HOLD.value:
                continue
            qty = _ORDER_QTY.get(sr.symbol, _DEFAULT_QTY)
            try:
                resp = await self._rest.post(
                    f"/api/v1/backtest/{session_id}/trade/order",
                    json={
                        "symbol": sr.symbol,
                        "side": sr.consensus_action,
                        "type": "market",
                        "quantity": qty,
                    },
                )
                resp.raise_for_status()
                log.debug(
                    "ensemble_runner.backtest.order_placed",
                    symbol=sr.symbol,
                    side=sr.consensus_action,
                    qty=qty,
                )
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                log.warning(
                    "ensemble_runner.backtest.order_failed",
                    symbol=sr.symbol,
                    side=sr.consensus_action,
                    error=str(exc),
                )

    # ── Reporting ─────────────────────────────────────────────────────────────

    def generate_report(self) -> "EnsembleReport":
        """Build an EnsembleReport from the accumulated step history.

        Can be called at any time after at least one call to :meth:`step`.
        Calling before :meth:`initialize` returns an empty report.

        Returns:
            :class:`EnsembleReport` with per-source stats and agreement rates.
        """
        return self._build_report(
            session_id="live" if self._config.mode == "live" else "unknown",
            start_time=self._session_start_time,
            end_time=datetime.now(UTC).isoformat(),
        )

    def _build_report(
        self,
        session_id: str,
        start_time: str,
        end_time: str,
    ) -> "EnsembleReport":
        """Internal: assemble an EnsembleReport from step history.

        Args:
            session_id: Backtest session UUID or 'live' / 'error'.
            start_time: ISO-8601 session start timestamp.
            end_time: ISO-8601 session end timestamp.

        Returns:
            :class:`EnsembleReport`.
        """
        total_placed = sum(sr.orders_placed for sr in self._step_history)
        total_vetoed = sum(sr.orders_vetoed for sr in self._step_history)

        # Collect all agreement rates for the overall mean.
        all_agreement_rates: list[float] = []
        for step in self._step_history:
            for sym_res in step.symbol_results:
                all_agreement_rates.append(sym_res.agreement_rate)

        overall_agreement = (
            sum(all_agreement_rates) / len(all_agreement_rates)
            if all_agreement_rates
            else 0.0
        )

        # Compute per-source stats.
        source_stats_map: dict[str, SourceStats] = {
            src.value: SourceStats(source=src.value) for src in SignalSource
        }

        for step in self._step_history:
            for sym_res in step.symbol_results:
                consensus_action = sym_res.consensus_action
                for contrib in sym_res.contributions:
                    stats = source_stats_map[contrib.source]
                    stats.total_steps += 1
                    if contrib.action == TradeAction.BUY.value:
                        stats.buy_signals += 1
                    elif contrib.action == TradeAction.SELL.value:
                        stats.sell_signals += 1
                    else:
                        stats.hold_signals += 1

                    # Track confidence mean (running sum, divide at report build).
                    if contrib.action != TradeAction.HOLD.value:
                        # Accumulate into mean_confidence (we'll compute properly below).
                        pass

                    # Agreement: source agrees with consensus if actions match.
                    if contrib.action == consensus_action:
                        stats.agreement_with_consensus += 1

        # Finalise agreement fractions.
        for stats in source_stats_map.values():
            if stats.total_steps > 0:
                stats.agreement_with_consensus = round(
                    stats.agreement_with_consensus / stats.total_steps, 4
                )

        # Recompute mean_confidence properly.
        conf_sums: dict[str, list[float]] = {src.value: [] for src in SignalSource}
        for step in self._step_history:
            for sym_res in step.symbol_results:
                for contrib in sym_res.contributions:
                    if contrib.action != TradeAction.HOLD.value and contrib.confidence > 0:
                        conf_sums[contrib.source].append(contrib.confidence)
        for src_val, vals in conf_sums.items():
            if vals:
                source_stats_map[src_val].mean_confidence = round(
                    sum(vals) / len(vals), 4
                )

        config_summary = {
            "mode": self._config.mode,
            "enable_rl_signal": self._config.enable_rl_signal,
            "enable_evolved_signal": self._config.enable_evolved_signal,
            "enable_regime_signal": self._config.enable_regime_signal,
            "enable_risk_overlay": self._config.enable_risk_overlay,
            "confidence_threshold": self._config.confidence_threshold,
            "min_agreement_rate": self._config.min_agreement_rate,
            "symbols": self._config.symbols,
            "weights": self._config.weights,
        }

        return EnsembleReport(
            session_id=session_id,
            mode=self._config.mode,
            start_time=start_time,
            end_time=end_time,
            total_steps=len(self._step_history),
            total_orders_placed=total_placed,
            total_orders_vetoed=total_vetoed,
            overall_agreement_rate=round(overall_agreement, 4),
            source_stats=list(source_stats_map.values()),
            config_summary=config_summary,
        )


# ── Backtest date-range resolution ────────────────────────────────────────────


async def _resolve_backtest_dates(
    base_url: str,
    api_key: str,
    days: int,
) -> tuple[str, str]:
    """Resolve a backtest date range from the platform or use a fallback.

    Args:
        base_url: Platform REST API base URL.
        api_key: Platform API key.
        days: Number of days for the backtest window.

    Returns:
        Tuple of (start_iso, end_iso) strings.
    """
    try:
        async with httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=10.0,
        ) as client:
            resp = await client.get("/api/v1/market/data-range")
            resp.raise_for_status()
            latest_str: str | None = resp.json().get("latest")
            if latest_str:
                latest_str = latest_str.replace("Z", "+00:00")
                end_dt = datetime.fromisoformat(latest_str).astimezone(UTC)
                start_dt = end_dt - timedelta(days=days)
                return (
                    start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                )
    except (httpx.HTTPStatusError, httpx.RequestError):
        pass

    # Fallback
    end_dt = datetime(2024, 3, 1, 0, 0, 0, tzinfo=UTC)
    start_dt = end_dt - timedelta(days=days)
    return (
        start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


# ── CLI ────────────────────────────────────────────────────────────────────────


async def _cli_main(
    mode: str,
    base_url: str,
    api_key: str,
    symbols: list[str],
    days: int,
    seed: int,
    output_dir: Path,
    no_rl: bool,
    no_evolved: bool,
    no_regime: bool,
    no_risk: bool,
) -> None:
    """Async CLI entry point.

    Args:
        mode: 'backtest' or 'live'.
        base_url: Platform REST API base URL.
        api_key: Platform API key.
        symbols: Trading symbols.
        days: Backtest window length in days.
        seed: Random seed (forwarded to structlog setup; models use their own seeds).
        output_dir: Output directory for the JSON report.
        no_rl: Disable the RL signal source.
        no_evolved: Disable the EVOLVED signal source.
        no_regime: Disable the REGIME signal source.
        no_risk: Disable the risk overlay.
    """
    import logging  # noqa: PLC0415

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ]
    )

    config = EnsembleConfig(
        mode=mode,  # type: ignore[arg-type]
        symbols=symbols,
        backtest_days=days,
        platform_api_key=api_key,
        platform_base_url=base_url,
        enable_rl_signal=not no_rl,
        enable_evolved_signal=not no_evolved,
        enable_regime_signal=not no_regime,
        enable_risk_overlay=not no_risk,
    )

    if mode == "backtest":
        start, end = await _resolve_backtest_dates(base_url, api_key, days)
        log.info("cli.ensemble_run.backtest_period", start=start, end=end)

        async with httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-Key": api_key},
            timeout=30.0,
        ) as rest_client:
            runner = EnsembleRunner(
                config=config,
                sdk_client=None,
                rest_client=rest_client,
            )
            await runner.initialize()
            report = await runner.run_backtest(start=start, end=end)
    else:
        # Live mode: would require an SDK client.  For CLI we skip risk overlay.
        config = config.model_copy(update={"enable_risk_overlay": False})
        runner = EnsembleRunner(
            config=config,
            sdk_client=None,
            rest_client=None,
        )
        await runner.initialize()
        report = runner.generate_report()

    # Save report.
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"ensemble-report-{mode}-{ts}.json"
    output_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    print(f"\n=== Ensemble Run Report ===")
    print(f"Mode              : {report.mode}")
    print(f"Session           : {report.session_id}")
    print(f"Steps             : {report.total_steps}")
    print(f"Orders placed     : {report.total_orders_placed}")
    print(f"Orders vetoed     : {report.total_orders_vetoed}")
    print(f"Agreement rate    : {report.overall_agreement_rate:.2%}")
    print(f"\nPer-source stats:")
    for stats in report.source_stats:
        print(
            f"  {stats.source:<10}  buy={stats.buy_signals:>4}  "
            f"sell={stats.sell_signals:>4}  hold={stats.hold_signals:>4}  "
            f"agreement={stats.agreement_with_consensus:.2%}"
        )
    print(f"\nReport saved to: {output_path}")


def main() -> None:
    """CLI entry point for the ensemble runner.

    Usage::

        python -m agent.strategies.ensemble.run \\
            --mode backtest \\
            --base-url http://localhost:8000 \\
            [--symbols BTCUSDT ETHUSDT] \\
            [--days 7] \\
            [--seed 42] \\
            [--output-dir agent/reports] \\
            [--no-rl] [--no-evolved] [--no-regime] [--no-risk]
    """
    parser = argparse.ArgumentParser(
        prog="python -m agent.strategies.ensemble.run",
        description=(
            "Ensemble runner — combines RL, EVOLVED, and REGIME signals "
            "through MetaLearner + risk overlay into a single trade decision."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["backtest", "live"],
        default="backtest",
        help="Execution mode: 'backtest' steps a historical session; 'live' uses real-time data.",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Platform REST API base URL.",
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTCUSDT", "ETHUSDT"],
        help="Trading symbols to include in the ensemble.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Backtest window length in calendar days.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent.parent / "reports",
        help="Output directory for the JSON report.",
    )
    parser.add_argument(
        "--no-rl",
        action="store_true",
        help="Disable the RL (PPO) signal source.",
    )
    parser.add_argument(
        "--no-evolved",
        action="store_true",
        help="Disable the EVOLVED (genetic algorithm) signal source.",
    )
    parser.add_argument(
        "--no-regime",
        action="store_true",
        help="Disable the REGIME (classifier) signal source.",
    )
    parser.add_argument(
        "--no-risk",
        action="store_true",
        help="Disable the risk overlay (RiskMiddleware).",
    )

    args = parser.parse_args()

    import os  # noqa: PLC0415

    api_key = os.environ.get("ENSEMBLE_PLATFORM_API_KEY", "") or os.environ.get("PLATFORM_API_KEY", "")
    if not api_key:
        parser.error(
            "Platform API key not set. "
            "Set ENSEMBLE_PLATFORM_API_KEY or PLATFORM_API_KEY in agent/.env or as environment variable."
        )

    asyncio.run(
        _cli_main(
            mode=args.mode,
            base_url=args.base_url,
            api_key=api_key,
            symbols=args.symbols,
            days=args.days,
            seed=args.seed,
            output_dir=args.output_dir,
            no_rl=args.no_rl,
            no_evolved=args.no_evolved,
            no_regime=args.no_regime,
            no_risk=args.no_risk,
        )
    )


if __name__ == "__main__":
    main()
