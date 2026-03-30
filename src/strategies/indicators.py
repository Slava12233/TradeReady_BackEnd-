"""Technical indicator engine for strategy evaluation.

Pure numpy implementations — no TA-Lib dependency. Each indicator method
operates on numpy arrays and returns scalar values. The engine maintains
a rolling OHLCV history per symbol via fixed-size deques.
"""

from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np


class IndicatorEngine:
    """Computes technical indicators from streaming OHLCV data.

    Args:
        max_history: Maximum number of candles to retain per symbol.
    """

    def __init__(self, max_history: int = 200) -> None:
        self._max_history = max_history
        self._highs: dict[str, deque[float]] = {}
        self._lows: dict[str, deque[float]] = {}
        self._closes: dict[str, deque[float]] = {}
        self._volumes: dict[str, deque[float]] = {}

    def update(self, symbol: str, ohlcv: dict[str, Any]) -> None:
        """Append one OHLCV bar for a symbol.

        Args:
            symbol: Trading pair (e.g. ``"BTCUSDT"``).
            ohlcv: Dict with keys ``high``, ``low``, ``close``, ``volume``.
                   ``open`` is accepted but not stored.
        """
        if symbol not in self._closes:
            self._highs[symbol] = deque(maxlen=self._max_history)
            self._lows[symbol] = deque(maxlen=self._max_history)
            self._closes[symbol] = deque(maxlen=self._max_history)
            self._volumes[symbol] = deque(maxlen=self._max_history)

        self._highs[symbol].append(float(ohlcv.get("high", ohlcv.get("close", 0))))
        self._lows[symbol].append(float(ohlcv.get("low", ohlcv.get("close", 0))))
        self._closes[symbol].append(float(ohlcv["close"]))
        self._volumes[symbol].append(float(ohlcv.get("volume", 0)))

    def compute(self, symbol: str) -> dict[str, float | None]:
        """Compute all indicators for a symbol.

        Returns:
            Dict of indicator values. Missing values are ``None``.
        """
        if symbol not in self._closes or len(self._closes[symbol]) == 0:
            return self._empty_result()

        closes = np.array(self._closes[symbol], dtype=np.float64)
        highs = np.array(self._highs[symbol], dtype=np.float64)
        lows = np.array(self._lows[symbol], dtype=np.float64)
        volumes = np.array(self._volumes[symbol], dtype=np.float64)

        macd_line, macd_signal, macd_hist = self._macd_components(closes, 12, 26, 9)
        bb_upper, bb_middle, bb_lower = self._bollinger(closes, 20, 2.0)

        return {
            "rsi_14": self._rsi(closes, 14),
            "macd_line": macd_line,
            "macd_signal": macd_signal,
            "macd_hist": macd_hist,
            "sma_20": self._sma(closes, 20),
            "sma_50": self._sma(closes, 50),
            "ema_12": self._ema(closes, 12),
            "ema_26": self._ema(closes, 26),
            "bb_upper": bb_upper,
            "bb_middle": bb_middle,
            "bb_lower": bb_lower,
            "adx": self._adx(highs, lows, closes, 14),
            "atr": self._atr(highs, lows, closes, 14),
            "volume_ma_20": self._sma(volumes, 20),
            "current_price": float(closes[-1]),
            "current_volume": float(volumes[-1]) if len(volumes) > 0 else None,
        }

    def has_data(self, symbol: str) -> bool:
        """Check if there is any data for a symbol."""
        return symbol in self._closes and len(self._closes[symbol]) > 0

    def data_length(self, symbol: str) -> int:
        """Return the number of data points for a symbol."""
        return len(self._closes.get(symbol, []))

    # ------------------------------------------------------------------
    # Indicator implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _sma(data: np.ndarray, period: int) -> float | None:
        """Simple moving average."""
        if len(data) < period:
            return None
        return float(np.mean(data[-period:]))

    @staticmethod
    def _ema(data: np.ndarray, period: int) -> float | None:
        """Exponential moving average using the standard formula."""
        if len(data) < period:
            return None
        multiplier = 2.0 / (period + 1)
        ema = float(np.mean(data[:period]))
        for price in data[period:]:
            ema = (float(price) - ema) * multiplier + ema
        return ema

    @staticmethod
    def _rsi(prices: np.ndarray, period: int = 14) -> float | None:
        """Relative Strength Index using Wilder's smoothing."""
        if len(prices) < period + 1:
            return None
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = float(np.mean(gains[:period]))
        avg_loss = float(np.mean(losses[:period]))

        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + float(gains[i])) / period
            avg_loss = (avg_loss * (period - 1) + float(losses[i])) / period

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def _macd_components(
        prices: np.ndarray,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> tuple[float | None, float | None, float | None]:
        """MACD line, signal line, histogram."""
        if len(prices) < slow:
            return None, None, None

        def _ema_array(data: np.ndarray, period: int) -> np.ndarray:
            multiplier = 2.0 / (period + 1)
            result = np.empty(len(data))
            result[0] = float(np.mean(data[:period])) if len(data) >= period else float(data[0])
            for i in range(1, len(data)):
                result[i] = (float(data[i]) - result[i - 1]) * multiplier + result[i - 1]
            return result

        fast_ema = _ema_array(prices, fast)
        slow_ema = _ema_array(prices, slow)
        macd_line = fast_ema - slow_ema

        if len(macd_line) < signal:
            return float(macd_line[-1]), None, None

        signal_ema = _ema_array(macd_line, signal)
        histogram = macd_line - signal_ema

        return float(macd_line[-1]), float(signal_ema[-1]), float(histogram[-1])

    @staticmethod
    def _bollinger(
        prices: np.ndarray,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> tuple[float | None, float | None, float | None]:
        """Bollinger Bands: upper, middle, lower."""
        if len(prices) < period:
            return None, None, None
        window = prices[-period:]
        middle = float(np.mean(window))
        std = float(np.std(window, ddof=0))
        return middle + std_dev * std, middle, middle - std_dev * std

    @staticmethod
    def _adx(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        period: int = 14,
    ) -> float | None:
        """Average Directional Index."""
        if len(closes) < period + 1:
            return None
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )
        plus_dm = np.where(
            (highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
            np.maximum(highs[1:] - highs[:-1], 0),
            0,
        )
        minus_dm = np.where(
            (lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
            np.maximum(lows[:-1] - lows[1:], 0),
            0,
        )

        if len(tr) < period:
            return None

        atr = float(np.mean(tr[:period]))
        plus_di_sum = float(np.mean(plus_dm[:period]))
        minus_di_sum = float(np.mean(minus_dm[:period]))

        dx_values = []
        for i in range(period, len(tr)):
            atr = (atr * (period - 1) + float(tr[i])) / period
            plus_di_sum = (plus_di_sum * (period - 1) + float(plus_dm[i])) / period
            minus_di_sum = (minus_di_sum * (period - 1) + float(minus_dm[i])) / period

            if atr == 0:
                continue
            plus_di = 100 * plus_di_sum / atr
            minus_di = 100 * minus_di_sum / atr
            di_sum = plus_di + minus_di
            if di_sum == 0:
                continue
            dx_values.append(abs(plus_di - minus_di) / di_sum * 100)

        if not dx_values:
            return None
        return float(np.mean(dx_values[-period:])) if len(dx_values) >= period else float(np.mean(dx_values))

    @staticmethod
    def _atr(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        period: int = 14,
    ) -> float | None:
        """Average True Range."""
        if len(closes) < period + 1:
            return None
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )
        if len(tr) < period:
            return None
        atr = float(np.mean(tr[:period]))
        for i in range(period, len(tr)):
            atr = (atr * (period - 1) + float(tr[i])) / period
        return atr

    @staticmethod
    def _empty_result() -> dict[str, float | None]:
        """Return a result dict with all values set to None."""
        return {
            "rsi_14": None,
            "macd_line": None,
            "macd_signal": None,
            "macd_hist": None,
            "sma_20": None,
            "sma_50": None,
            "ema_12": None,
            "ema_26": None,
            "bb_upper": None,
            "bb_middle": None,
            "bb_lower": None,
            "adx": None,
            "atr": None,
            "volume_ma_20": None,
            "current_price": None,
            "current_volume": None,
        }
