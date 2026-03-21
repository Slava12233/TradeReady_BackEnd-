"""Signal generator — wraps the EnsembleRunner to produce per-symbol trading signals.

:class:`SignalGenerator` is a thin adapter between the agent trading loop and the
existing :class:`~agent.strategies.ensemble.run.EnsembleRunner`.  It fetches recent
candles for each requested symbol, runs a single :meth:`~EnsembleRunner.step` of the
ensemble pipeline, and converts the resulting :class:`~agent.strategies.ensemble.run.StepResult`
into a flat list of :class:`TradingSignal` objects that the trading loop can reason over.

The design intentionally delegates all strategy logic to ``EnsembleRunner`` so there
is no duplication of RL / evolutionary / regime / risk logic in this file.

Architecture::

    SignalGenerator.generate(symbols)
           │
           ├── fetch candles concurrently (asyncio.gather)
           │       REST: GET /api/v1/market/candles/{symbol}
           │
           └── EnsembleRunner.step(candles_by_symbol)
                   │
                   └── [ConsensusSignal per symbol] → list[TradingSignal]

Usage::

    from agent.config import AgentConfig
    from agent.strategies.ensemble.config import EnsembleConfig
    from agent.strategies.ensemble.run import EnsembleRunner
    from agent.trading.signal_generator import SignalGenerator

    ensemble_config = EnsembleConfig()
    runner = EnsembleRunner(config=ensemble_config, sdk_client=sdk, rest_client=None)
    await runner.initialize()

    generator = SignalGenerator(runner=runner, config=config, rest_client=rest)
    signals = await generator.generate(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, Field

from agent.config import AgentConfig

logger = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

# Number of 1-minute candles to fetch per symbol for indicator computation.
# 50 candles = ~50 min lookback, sufficient for SMA-20, RSI-14, MACD-26.
_CANDLE_LIMIT: int = 50

# Candle interval in seconds (1-minute candles match EnsembleRunner default).
_CANDLE_INTERVAL: int = 60


# ── TradingSignal ──────────────────────────────────────────────────────────────


class TradingSignal(BaseModel):
    """Per-symbol signal produced by the signal generator for the trading loop.

    Wraps the ensemble :class:`~agent.strategies.ensemble.run.ConsensusSignal` result
    into a plain, loop-friendly container.  The trading loop uses :attr:`action` and
    :attr:`confidence` to decide whether to pass the signal to the LLM decision step.

    Attributes:
        symbol: Trading pair the signal targets (e.g. ``"BTCUSDT"``).
        action: Ensemble consensus direction: ``"buy"``, ``"sell"``, or ``"hold"``.
        confidence: Combined weighted confidence from the MetaLearner in ``[0.0, 1.0]``.
        agreement_rate: Fraction of active strategy sources that agreed with the
            winning action (``[0.0, 1.0]``).
        source_contributions: Per-source signal details keyed by source name
            (``"rl"``, ``"evolved"``, ``"regime"``).  Values are dicts with
            ``action``, ``confidence``, and ``enabled`` keys.
        regime: Market regime label at signal time (``"trending"``,
            ``"mean_reverting"``, etc.).  ``None`` when the regime source is
            disabled or insufficient candles are available.
        indicators: Snapshot of key indicator values at signal time (RSI, MACD
            histogram, SMA fast/slow).  ``None`` when candle data was unavailable.
        generated_at: UTC timestamp when the signal was produced.

    Example::

        sig = TradingSignal(
            symbol="BTCUSDT",
            action="buy",
            confidence=0.72,
            agreement_rate=0.67,
            source_contributions={"rl": {"action": "buy", "confidence": 0.8}},
            regime="trending",
            indicators={"rsi": 38.2, "macd_hist": 0.003},
            generated_at=datetime.utcnow(),
        )
    """

    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Trading pair symbol, e.g. 'BTCUSDT'.")
    action: str = Field(
        ...,
        description="Ensemble consensus direction: 'buy', 'sell', or 'hold'.",
        pattern=r"^(buy|sell|hold)$",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Combined weighted confidence from the MetaLearner.",
    )
    agreement_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Fraction of active strategy sources agreeing with the winner.",
    )
    source_contributions: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-source breakdown (action, confidence, enabled) keyed by source name.",
    )
    regime: str | None = Field(
        default=None,
        description="Market regime label at signal time.",
    )
    indicators: dict[str, Any] | None = Field(
        default=None,
        description="Key indicator snapshot: rsi, macd_hist, sma_fast, sma_slow.",
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="UTC timestamp when this signal was generated.",
    )


# ── SignalGenerator ────────────────────────────────────────────────────────────


class SignalGenerator:
    """Wraps :class:`~agent.strategies.ensemble.run.EnsembleRunner` to produce signals.

    :meth:`generate` fetches fresh candles for all requested symbols concurrently
    (``asyncio.gather``), feeds them into the ensemble runner, and converts the
    resulting :class:`~agent.strategies.ensemble.run.StepResult` into
    :class:`TradingSignal` objects.

    One failed symbol fetch does not abort the others — partial results with
    ``confidence=0`` and ``action="hold"`` are returned for symbols that errored.

    Args:
        runner: An already-:meth:`~EnsembleRunner.initialize`-d
            :class:`~agent.strategies.ensemble.run.EnsembleRunner` instance.
        config: :class:`~agent.config.AgentConfig` for connectivity parameters
            (base URL, API key, minimum confidence threshold).
        rest_client: An :class:`~httpx.AsyncClient` pointed at the platform REST
            API.  Used to fetch live candles for each symbol.  If ``None``,
            ``generate()`` returns HOLD signals with ``confidence=0`` for all
            symbols (useful in tests).

    Example::

        runner = EnsembleRunner(config=EnsembleConfig(), sdk_client=sdk, rest_client=None)
        await runner.initialize()
        generator = SignalGenerator(runner=runner, config=config, rest_client=rest)

        signals = await generator.generate(["BTCUSDT", "ETHUSDT"])
        for sig in signals:
            if sig.action != "hold" and sig.confidence >= 0.6:
                print(f"{sig.symbol}: {sig.action} @ {sig.confidence:.2%}")
    """

    def __init__(
        self,
        runner: Any,  # noqa: ANN401  # agent.strategies.ensemble.run.EnsembleRunner
        config: AgentConfig,
        rest_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._runner = runner
        self._config = config
        self._rest = rest_client
        self._log = logger.bind(component="signal_generator")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(self, symbols: list[str]) -> list[TradingSignal]:
        """Generate ensemble signals for a list of symbols.

        Pipeline:
          1. Fetch recent candles for all symbols concurrently (``asyncio.gather``).
          2. Feed the candle map into :meth:`~EnsembleRunner.step`.
          3. Convert the :class:`~StepResult` into :class:`TradingSignal` objects.

        One failed candle fetch produces a HOLD signal with ``confidence=0`` for
        that symbol; it does not prevent signals for other symbols.

        Args:
            symbols: Trading pairs to generate signals for.
                Must contain at least one entry.

        Returns:
            A list of :class:`TradingSignal` objects, one per symbol, ordered
            in the same order as ``symbols``.  Returns all-HOLD signals when no
            candle data is available (e.g. ``rest_client`` is ``None``).
        """
        if not symbols:
            self._log.warning("signal_generator.generate.no_symbols")
            return []

        # ── Step 1: Fetch candles concurrently ──────────────────────────
        candles_by_symbol = await self._fetch_all_candles(symbols)

        # If we could not fetch candles at all, return all-HOLD signals.
        if not candles_by_symbol:
            self._log.warning(
                "signal_generator.generate.no_candles",
                symbols=symbols,
            )
            return [self._hold_signal(sym, reason="no_candles") for sym in symbols]

        # ── Step 2: Run ensemble step ────────────────────────────────────
        try:
            step_result = await self._runner.step(candles_by_symbol)
        except Exception as exc:  # noqa: BLE001
            self._log.error(
                "signal_generator.generate.ensemble_step_failed",
                error=str(exc),
            )
            return [self._hold_signal(sym, reason="ensemble_error") for sym in symbols]

        # ── Step 3: Convert to TradingSignal objects ─────────────────────
        signals = self._convert_step_result(step_result, symbols, candles_by_symbol)

        self._log.info(
            "signal_generator.generate.complete",
            symbols=symbols,
            total=len(signals),
            non_hold=sum(1 for s in signals if s.action != "hold"),
        )
        return signals

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_all_candles(
        self,
        symbols: list[str],
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch recent candles for all symbols concurrently.

        Uses ``asyncio.gather(return_exceptions=True)`` so one failed fetch
        does not cancel others.

        Args:
            symbols: Trading pairs to fetch candles for.

        Returns:
            Mapping from symbol to candle list (oldest to newest).
            Symbols whose fetch failed are absent from the returned dict.
        """
        if self._rest is None:
            self._log.debug("signal_generator.fetch_candles.no_rest_client")
            return {}

        async def _fetch_one(sym: str) -> tuple[str, list[dict[str, Any]] | Exception]:
            try:
                resp = await self._rest.get(  # type: ignore[union-attr]
                    f"/api/v1/market/candles/{sym}",
                    params={"interval": _CANDLE_INTERVAL, "limit": _CANDLE_LIMIT},
                )
                resp.raise_for_status()
                body = resp.json()
                # The endpoint returns {"candles": [...]} or a flat list.
                candles: list[dict[str, Any]] = (
                    body.get("candles", body) if isinstance(body, dict) else body
                )
                return sym, candles
            except httpx.HTTPStatusError as exc:
                return sym, exc
            except httpx.RequestError as exc:
                return sym, exc

        tasks = [_fetch_one(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        candles_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for item in results:
            if isinstance(item, Exception):
                self._log.warning(
                    "signal_generator.fetch_candles.gather_exception",
                    error=str(item),
                )
                continue
            sym, payload = item
            if isinstance(payload, Exception):
                self._log.warning(
                    "signal_generator.fetch_candles.fetch_failed",
                    symbol=sym,
                    error=str(payload),
                )
            elif isinstance(payload, list):
                candles_by_symbol[sym] = payload

        return candles_by_symbol

    def _convert_step_result(
        self,
        step_result: Any,  # noqa: ANN401  # agent.strategies.ensemble.run.StepResult
        symbols: list[str],
        candles_by_symbol: dict[str, list[dict[str, Any]]],
    ) -> list[TradingSignal]:
        """Convert a :class:`StepResult` into :class:`TradingSignal` objects.

        Preserves the order of ``symbols`` and inserts a HOLD signal for any
        symbol missing from ``step_result.symbol_results``.

        Args:
            step_result: The :class:`~agent.strategies.ensemble.run.StepResult`
                returned by :meth:`~EnsembleRunner.step`.
            symbols: Original requested symbol list (preserves order in output).
            candles_by_symbol: Symbol → candle list mapping used to compute
                supplemental indicator snapshots.

        Returns:
            Ordered list of :class:`TradingSignal` instances.
        """
        # Build a fast lookup from symbol → SymbolStepResult.
        result_map: dict[str, Any] = {sr.symbol: sr for sr in step_result.symbol_results}
        now = datetime.now(UTC)
        signals: list[TradingSignal] = []

        for sym in symbols:
            sr = result_map.get(sym)
            if sr is None:
                # Symbol was not processed by the ensemble runner.
                signals.append(self._hold_signal(sym, reason="not_in_step_result"))
                continue

            # Extract per-source contributions.
            contributions: dict[str, Any] = {}
            regime_label: str | None = None
            for contrib in sr.contributions:
                contributions[contrib.source] = {
                    "action": contrib.action,
                    "confidence": contrib.confidence,
                    "enabled": contrib.enabled,
                }
                # Extract regime label from the REGIME source metadata.
                if contrib.source == "regime" and contrib.enabled:
                    regime_label = contrib.metadata.get("regime_type")

            # Compute lightweight indicator snapshot from candles.
            indicators = self._compute_indicators(candles_by_symbol.get(sym, []))

            signals.append(
                TradingSignal(
                    symbol=sym,
                    action=sr.consensus_action.lower(),
                    confidence=sr.consensus_confidence,
                    agreement_rate=sr.agreement_rate,
                    source_contributions=contributions,
                    regime=regime_label,
                    indicators=indicators,
                    generated_at=now,
                )
            )

        return signals

    def _compute_indicators(
        self,
        candles: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Compute a lightweight indicator snapshot from raw candles.

        Computes RSI-14, a MACD histogram proxy, and fast/slow SMAs from the
        provided candles.  Returns ``None`` when fewer than 26 candles are
        available (the minimum for a meaningful MACD slow period).

        Args:
            candles: Chronologically ordered OHLCV candle dicts, each with a
                ``"close"`` key.

        Returns:
            Dict with keys ``rsi``, ``macd_hist``, ``sma_fast``, ``sma_slow``
            (all ``float | None``), or ``None`` when data is insufficient.
        """
        closes: list[float] = []
        for c in candles:
            raw = c.get("close")
            if raw is not None:
                try:
                    closes.append(float(raw))
                except (ValueError, TypeError):
                    pass

        if len(closes) < 26:
            return None

        def _sma(prices: list[float], n: int) -> float | None:
            if len(prices) < n:
                return None
            return sum(prices[-n:]) / n

        def _rsi(prices: list[float], period: int = 14) -> float | None:
            if len(prices) < period + 1:
                return None
            deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices[-(period + 1):]) + 1)]
            # Recalculate with correct slice.
            recent = prices[-(period + 1):]
            gains: list[float] = []
            losses: list[float] = []
            for i in range(1, len(recent)):
                d = recent[i] - recent[i - 1]
                gains.append(d if d > 0 else 0.0)
                losses.append(-d if d < 0 else 0.0)
            del deltas  # not used after recompute
            avg_gain = sum(gains) / period
            avg_loss = sum(losses) / period
            if avg_loss == 0:
                return 100.0
            rs = avg_gain / avg_loss
            return round(100.0 - (100.0 / (1.0 + rs)), 4)

        def _ema(prices: list[float], n: int) -> float:
            k = 2.0 / (n + 1)
            ema = prices[0]
            for p in prices[1:]:
                ema = p * k + ema * (1 - k)
            return ema

        def _macd_hist(prices: list[float], fast: int = 12, slow: int = 26) -> float | None:
            if len(prices) < slow:
                return None
            return round(_ema(prices[-fast:], fast) - _ema(prices[-slow:], slow), 6)

        return {
            "rsi": _rsi(closes),
            "macd_hist": _macd_hist(closes),
            "sma_fast": _sma(closes, 5),
            "sma_slow": _sma(closes, 20),
        }

    @staticmethod
    def _hold_signal(symbol: str, *, reason: str = "") -> TradingSignal:
        """Build a zero-confidence HOLD signal for a symbol.

        Args:
            symbol: Trading pair symbol.
            reason: Optional human-readable reason stored in metadata.

        Returns:
            A :class:`TradingSignal` with ``action="hold"`` and
            ``confidence=0.0``.
        """
        meta: dict[str, Any] = {}
        if reason:
            meta["reason"] = reason
        return TradingSignal(
            symbol=symbol,
            action="hold",
            confidence=0.0,
            agreement_rate=0.0,
            source_contributions=meta,
            regime=None,
            indicators=None,
            generated_at=datetime.now(UTC),
        )
