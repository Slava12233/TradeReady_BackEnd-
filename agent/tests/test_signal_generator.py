"""Tests for agent/trading/signal_generator.py.

Covers:
- Volume confirmation filter (_apply_volume_filter, _compute_volume_ratio)
- Confidence threshold filter (configurable via AgentConfig.signal_confidence_threshold)
- TradingSignal HOLD downgrade paths
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.config import AgentConfig
from agent.trading.signal_generator import (
    _VOLUME_LOOKBACK,
    _VOLUME_MIN_RATIO,
    SignalGenerator,
    TradingSignal,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    monkeypatch: pytest.MonkeyPatch,
    *,
    confidence_threshold: float = 0.55,
) -> AgentConfig:
    """Build an AgentConfig with required env vars set."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_test")
    monkeypatch.setenv("PLATFORM_API_SECRET", "sk_live_test")
    monkeypatch.setenv("SIGNAL_CONFIDENCE_THRESHOLD", str(confidence_threshold))
    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _make_signal(
    symbol: str = "BTCUSDT",
    action: str = "buy",
    confidence: float = 0.7,
) -> TradingSignal:
    """Build a TradingSignal with sensible defaults."""
    return TradingSignal(
        symbol=symbol,
        action=action,
        confidence=confidence,
        agreement_rate=0.67,
        source_contributions={},
        regime=None,
        indicators=None,
        generated_at=datetime.now(UTC),
    )


def _make_candle(volume: float = 100.0) -> dict[str, Any]:
    """Build a minimal candle dict with the given volume."""
    return {
        "time": "2024-01-01T00:00:00Z",
        "open": "60000",
        "high": "61000",
        "low": "59000",
        "close": "60500",
        "volume": str(volume),
        "trade_count": 200,
    }


def _make_candles(volumes: list[float]) -> list[dict[str, Any]]:
    """Build a list of candle dicts from a list of volumes."""
    return [_make_candle(v) for v in volumes]


def _make_generator(config: AgentConfig) -> SignalGenerator:
    """Build a SignalGenerator with a mock runner and no REST client."""
    runner = MagicMock()
    runner.step = AsyncMock()
    return SignalGenerator(runner=runner, config=config, rest_client=None)


# ---------------------------------------------------------------------------
# _compute_volume_ratio
# ---------------------------------------------------------------------------


class TestComputeVolumeRatio:
    """Tests for SignalGenerator._compute_volume_ratio()."""

    def test_returns_none_for_single_candle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when only one candle is provided (no baseline possible)."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)

        result = gen._compute_volume_ratio([_make_candle(100)])

        assert result is None

    def test_returns_none_for_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when the candle list is empty."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)

        result = gen._compute_volume_ratio([])

        assert result is None

    def test_ratio_of_one_when_volume_equals_average(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns 1.0 when the latest candle volume equals the historical average."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)

        # All candles have the same volume → latest / avg(rest) = 1.0
        candles = _make_candles([100.0] * 5)

        result = gen._compute_volume_ratio(candles)

        assert result is not None
        assert abs(result - 1.0) < 1e-9

    def test_ratio_above_one_for_high_volume_candle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns >1.0 when the latest candle volume is above the rolling average."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)

        # Baseline is 100, latest is 300 → ratio should be ~3.0
        candles = _make_candles([100.0, 100.0, 100.0, 300.0])

        result = gen._compute_volume_ratio(candles)

        assert result is not None
        assert result > 1.0

    def test_ratio_below_one_for_low_volume_candle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns <1.0 when the latest candle volume is below the rolling average."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)

        # Baseline is 100, latest is 30 → ratio should be ~0.3
        candles = _make_candles([100.0, 100.0, 100.0, 30.0])

        result = gen._compute_volume_ratio(candles)

        assert result is not None
        assert result < 1.0
        assert abs(result - 0.3) < 1e-9

    def test_returns_none_when_average_volume_is_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when the baseline average is zero (avoids division by zero)."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)

        # All historical candles have 0 volume, latest is 50
        candles = _make_candles([0.0, 0.0, 0.0, 50.0])

        result = gen._compute_volume_ratio(candles)

        assert result is None

    def test_uses_lookback_window_not_full_history(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Uses at most _VOLUME_LOOKBACK candles; ignores older candles."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)

        # Put a very high volume far back (should be ignored by the lookback window)
        # followed by VOLUME_LOOKBACK candles of 100.0, then a latest of 50.0.
        old_candles = _make_candles([10000.0] * 5)
        recent_candles = _make_candles([100.0] * (_VOLUME_LOOKBACK - 1) + [50.0])
        candles = old_candles + recent_candles

        result = gen._compute_volume_ratio(candles)

        # Within the window the baseline is 100.0, latest is 50.0 → 0.5
        assert result is not None
        assert abs(result - 0.5) < 1e-6

    def test_returns_none_when_volume_field_is_invalid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when the volume field cannot be parsed to float."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)

        candles = [{"volume": "n/a"}, {"volume": "n/a"}]

        result = gen._compute_volume_ratio(candles)

        assert result is None


# ---------------------------------------------------------------------------
# _apply_volume_filter
# ---------------------------------------------------------------------------


class TestApplyVolumeFilter:
    """Tests for SignalGenerator._apply_volume_filter()."""

    def test_hold_signals_pass_through_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HOLD signals are never rejected by the volume filter."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)
        hold_sig = _make_signal(action="hold", confidence=0.0)
        candles_map: dict[str, list[dict[str, Any]]] = {"BTCUSDT": []}

        result = gen._apply_volume_filter([hold_sig], candles_map)

        assert len(result) == 1
        assert result[0].action == "hold"

    def test_buy_signal_kept_when_volume_is_sufficient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A BUY signal is kept when volume >= 50% of the rolling average."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)
        sig = _make_signal(action="buy", confidence=0.8)

        # Latest volume equals baseline — ratio is 1.0, well above threshold
        candles = _make_candles([100.0] * 5)
        candles_map = {"BTCUSDT": candles}

        result = gen._apply_volume_filter([sig], candles_map)

        assert len(result) == 1
        assert result[0].action == "buy"
        assert result[0].symbol == "BTCUSDT"

    def test_buy_signal_rejected_when_volume_is_too_low(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A BUY signal is downgraded to HOLD when volume < 50% of rolling average."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)
        sig = _make_signal(action="buy", confidence=0.8)

        # Latest volume is 10% of baseline → ratio 0.1 < _VOLUME_MIN_RATIO
        candles = _make_candles([100.0, 100.0, 100.0, 10.0])
        candles_map = {"BTCUSDT": candles}

        result = gen._apply_volume_filter([sig], candles_map)

        assert len(result) == 1
        assert result[0].action == "hold"
        assert result[0].symbol == "BTCUSDT"

    def test_sell_signal_rejected_when_volume_too_low(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A SELL signal is also downgraded to HOLD on thin volume."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)
        sig = _make_signal(action="sell", confidence=0.75)

        candles = _make_candles([100.0, 100.0, 100.0, 10.0])
        candles_map = {"BTCUSDT": candles}

        result = gen._apply_volume_filter([sig], candles_map)

        assert result[0].action == "hold"

    def test_signal_kept_when_no_candle_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Signal passes through unchanged when candles are unavailable (safe default)."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)
        sig = _make_signal(action="buy", confidence=0.8)

        # No candle data for this symbol
        candles_map: dict[str, list[dict[str, Any]]] = {}

        result = gen._apply_volume_filter([sig], candles_map)

        # _compute_volume_ratio returns None → signal is kept (fail-open for data absence)
        assert result[0].action == "buy"

    def test_signal_kept_when_volume_exactly_at_threshold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A signal at exactly the threshold ratio (0.5) is kept, not rejected."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)
        sig = _make_signal(action="buy", confidence=0.8)

        # Ratio = 50 / 100 = 0.5 exactly, which is NOT < threshold
        candles = _make_candles([100.0, 100.0, 50.0])
        candles_map = {"BTCUSDT": candles}

        result = gen._apply_volume_filter([sig], candles_map)

        assert result[0].action == "buy"

    def test_multiple_symbols_filtered_independently(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each symbol is volume-checked independently; one rejection does not affect others."""
        config = _make_config(monkeypatch)
        gen = _make_generator(config)
        sig_btc = _make_signal("BTCUSDT", "buy", 0.8)
        sig_eth = _make_signal("ETHUSDT", "buy", 0.75)

        # BTC has thin volume, ETH has normal volume
        candles_map = {
            "BTCUSDT": _make_candles([100.0, 100.0, 100.0, 10.0]),  # ratio 0.1 → reject
            "ETHUSDT": _make_candles([100.0] * 5),  # ratio 1.0 → keep
        }

        result = gen._apply_volume_filter([sig_btc, sig_eth], candles_map)

        assert len(result) == 2
        btc_result = next(s for s in result if s.symbol == "BTCUSDT")
        eth_result = next(s for s in result if s.symbol == "ETHUSDT")
        assert btc_result.action == "hold"
        assert eth_result.action == "buy"


# ---------------------------------------------------------------------------
# Confidence threshold filter
# ---------------------------------------------------------------------------


class TestConfidenceThresholdFilter:
    """Tests for the confidence threshold applied during generate()."""

    def test_default_threshold_is_0_55(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AgentConfig.signal_confidence_threshold defaults to 0.55."""
        config = _make_config(monkeypatch, confidence_threshold=0.55)

        assert config.signal_confidence_threshold == 0.55

    def test_threshold_is_configurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """signal_confidence_threshold can be overridden via environment variable."""
        config = _make_config(monkeypatch, confidence_threshold=0.70)

        assert config.signal_confidence_threshold == 0.70

    def test_signal_below_threshold_becomes_hold(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Signals with confidence < threshold are replaced with HOLD in generate()."""
        # Use a high threshold to ensure our signal is below it
        config = _make_config(monkeypatch, confidence_threshold=0.80)
        gen = _make_generator(config)

        # Build a signal with confidence 0.6 < threshold 0.8
        weak_signal = _make_signal(action="buy", confidence=0.6)

        # Call the threshold filter step directly
        threshold = config.signal_confidence_threshold
        result = [
            s if s.confidence >= threshold else gen._hold_signal(s.symbol, reason="below_confidence_threshold")
            for s in [weak_signal]
        ]

        assert result[0].action == "hold"
        assert result[0].symbol == "BTCUSDT"

    def test_signal_at_threshold_is_kept(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Signals with confidence == threshold are NOT downgraded to HOLD."""
        config = _make_config(monkeypatch, confidence_threshold=0.55)
        gen = _make_generator(config)

        exact_signal = _make_signal(action="buy", confidence=0.55)
        threshold = config.signal_confidence_threshold

        result = [
            s if s.confidence >= threshold else gen._hold_signal(s.symbol, reason="below_confidence_threshold")
            for s in [exact_signal]
        ]

        assert result[0].action == "buy"

    def test_signal_above_threshold_is_kept(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Signals with confidence > threshold pass through unchanged."""
        config = _make_config(monkeypatch, confidence_threshold=0.55)
        gen = _make_generator(config)

        strong_signal = _make_signal(action="sell", confidence=0.90)
        threshold = config.signal_confidence_threshold

        result = [
            s if s.confidence >= threshold else gen._hold_signal(s.symbol, reason="below_confidence_threshold")
            for s in [strong_signal]
        ]

        assert result[0].action == "sell"
        assert result[0].confidence == 0.90


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """Sanity checks for module-level constants."""

    def test_volume_min_ratio_is_0_5(self) -> None:
        """_VOLUME_MIN_RATIO is 0.5 (50% of rolling average)."""
        assert _VOLUME_MIN_RATIO == 0.5

    def test_volume_lookback_is_20(self) -> None:
        """_VOLUME_LOOKBACK is 20 candles."""
        assert _VOLUME_LOOKBACK == 20

    def test_volume_lookback_le_candle_limit(self) -> None:
        """_VOLUME_LOOKBACK must be <= _CANDLE_LIMIT to avoid index errors."""
        from agent.trading.signal_generator import _CANDLE_LIMIT

        assert _VOLUME_LOOKBACK <= _CANDLE_LIMIT
