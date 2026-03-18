"""Observation builder that converts API responses to numpy arrays."""

from __future__ import annotations

from typing import Any

import numpy as np
from gymnasium import spaces

# Feature definitions: (name, per_candle_dims)
_FEATURE_DIMS: dict[str, int] = {
    "ohlcv": 5,         # open, high, low, close, volume
    "rsi_14": 1,         # RSI value (from close prices)
    "macd": 3,           # macd_line, macd_signal, macd_histogram
    "bollinger": 3,      # upper, middle, lower
    "volume": 1,         # raw volume
    "adx": 1,            # ADX value
    "atr": 1,            # ATR value
}

# Non-windowed (scalar) features appended after candle features
_SCALAR_FEATURES: dict[str, int] = {
    "balance": 1,        # available cash / starting balance (normalized)
    "position": 1,       # position value / equity (normalized)
    "unrealized_pnl": 1, # unrealized PnL / equity (normalized)
}


class ObservationBuilder:
    """Builds numpy observation arrays from API candle + portfolio data.

    Args:
        features:        List of feature names to include.
        lookback_window: Number of historical candles.
        n_assets:        Number of trading pairs.
    """

    def __init__(
        self,
        features: list[str] | None = None,
        lookback_window: int = 30,
        n_assets: int = 1,
    ) -> None:
        self.features = features or ["ohlcv", "balance", "position"]
        self.lookback_window = lookback_window
        self.n_assets = n_assets

        # Calculate total observation dimensions
        candle_dims = 0
        for feat in self.features:
            if feat in _FEATURE_DIMS:
                candle_dims += _FEATURE_DIMS[feat]

        scalar_dims = 0
        for feat in self.features:
            if feat in _SCALAR_FEATURES:
                scalar_dims += _SCALAR_FEATURES[feat]

        total_dim = (lookback_window * candle_dims * n_assets) + scalar_dims
        if total_dim == 0:
            total_dim = lookback_window * 5 * n_assets  # fallback to OHLCV

        self._candle_dims = candle_dims
        self._scalar_dims = scalar_dims
        self._total_dim = total_dim

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(total_dim,), dtype=np.float32
        )

    def build(
        self,
        candle_data: dict[str, list[dict[str, Any]]],
        portfolio: dict[str, Any],
    ) -> np.ndarray:
        """Build a flat observation vector from candle and portfolio data.

        Args:
            candle_data: Dict mapping symbol to list of candle dicts.
            portfolio:   Portfolio dict from the backtest step response.

        Returns:
            Flat numpy array of shape ``(total_dim,)``.
        """
        parts: list[np.ndarray] = []

        for candles in candle_data.values():
            candle_features = self._extract_candle_features(candles)
            parts.append(candle_features.flatten())

        # Scalar features
        scalar_parts: list[float] = []
        equity = float(portfolio.get("total_equity", 1.0)) or 1.0
        starting = float(portfolio.get("starting_balance", 1.0)) or 1.0

        if "balance" in self.features:
            cash = float(portfolio.get("available_cash", 0.0))
            scalar_parts.append(cash / starting)

        if "position" in self.features:
            pos_value = float(portfolio.get("total_position_value", 0.0))
            scalar_parts.append(pos_value / equity if equity else 0.0)

        if "unrealized_pnl" in self.features:
            pnl = float(portfolio.get("unrealized_pnl", 0.0))
            scalar_parts.append(pnl / equity if equity else 0.0)

        if scalar_parts:
            parts.append(np.array(scalar_parts, dtype=np.float32))

        obs = np.concatenate(parts) if parts else np.zeros(self._total_dim, dtype=np.float32)

        # Pad or truncate to match expected dimension
        if len(obs) < self._total_dim:
            obs = np.pad(obs, (0, self._total_dim - len(obs)), constant_values=0.0)
        elif len(obs) > self._total_dim:
            obs = obs[: self._total_dim]

        return obs.astype(np.float32)

    def _extract_candle_features(
        self, candles: list[dict[str, Any]]
    ) -> np.ndarray:
        """Extract requested features from a list of candle dicts."""
        window = self.lookback_window
        if not candles:
            return np.zeros((window, self._candle_dims), dtype=np.float32)

        # Pad with zeros if fewer candles than window
        candles = candles[-window:]
        n = len(candles)
        result = np.zeros((window, self._candle_dims), dtype=np.float32)

        col = 0
        if "ohlcv" in self.features:
            for i, c in enumerate(candles):
                offset = window - n + i
                result[offset, col] = float(c.get("open", 0))
                result[offset, col + 1] = float(c.get("high", 0))
                result[offset, col + 2] = float(c.get("low", 0))
                result[offset, col + 3] = float(c.get("close", 0))
                result[offset, col + 4] = float(c.get("volume", 0))
            col += 5

        closes = [float(c.get("close", 0)) for c in candles]

        if "rsi_14" in self.features:
            rsi_values = self._compute_rsi(closes, 14)
            for i, v in enumerate(rsi_values):
                offset = window - len(rsi_values) + i
                if 0 <= offset < window:
                    result[offset, col] = v / 100.0  # normalize to [0, 1]
            col += 1

        if "macd" in self.features:
            macd_line, macd_signal, macd_hist = self._compute_macd(closes)
            for i in range(len(macd_line)):
                offset = window - len(macd_line) + i
                if 0 <= offset < window:
                    result[offset, col] = macd_line[i]
                    result[offset, col + 1] = macd_signal[i]
                    result[offset, col + 2] = macd_hist[i]
            col += 3

        if "bollinger" in self.features:
            upper, middle, lower = self._compute_bollinger(closes, 20)
            for i in range(len(upper)):
                offset = window - len(upper) + i
                if 0 <= offset < window:
                    result[offset, col] = upper[i]
                    result[offset, col + 1] = middle[i]
                    result[offset, col + 2] = lower[i]
            col += 3

        if "volume" in self.features:
            for i, c in enumerate(candles):
                offset = window - n + i
                result[offset, col] = float(c.get("volume", 0))
            col += 1

        if "adx" in self.features:
            # Simplified ADX placeholder using close price momentum
            for i in range(1, n):
                offset = window - n + i
                if closes[i - 1] != 0:
                    result[offset, col] = abs(closes[i] - closes[i - 1]) / closes[i - 1]
            col += 1

        if "atr" in self.features:
            highs = [float(c.get("high", 0)) for c in candles]
            lows = [float(c.get("low", 0)) for c in candles]
            atr_values = self._compute_atr(highs, lows, closes, 14)
            for i, v in enumerate(atr_values):
                offset = window - len(atr_values) + i
                if 0 <= offset < window:
                    result[offset, col] = v
            col += 1

        return result

    @staticmethod
    def _compute_rsi(prices: list[float], period: int = 14) -> list[float]:
        """Compute RSI from a list of close prices."""
        if len(prices) < period + 1:
            return [50.0] * len(prices)

        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        gains = [max(d, 0) for d in deltas]
        losses = [abs(min(d, 0)) for d in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        rsi_values: list[float] = []
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            rs = avg_gain / avg_loss if avg_loss != 0 else 100.0
            rsi_values.append(100.0 - (100.0 / (1.0 + rs)))

        return rsi_values

    @staticmethod
    def _compute_macd(
        prices: list[float], fast: int = 12, slow: int = 26, signal: int = 9
    ) -> tuple[list[float], list[float], list[float]]:
        """Compute MACD line, signal, and histogram."""
        if len(prices) < slow:
            n = len(prices)
            return [0.0] * n, [0.0] * n, [0.0] * n

        def _ema(data: list[float], period: int) -> list[float]:
            k = 2.0 / (period + 1)
            result = [data[0]]
            for v in data[1:]:
                result.append(v * k + result[-1] * (1.0 - k))
            return result

        ema_fast = _ema(prices, fast)
        ema_slow = _ema(prices, slow)
        macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
        signal_line = _ema(macd_line, signal)
        histogram = [m - s for m, s in zip(macd_line, signal_line)]
        return macd_line, signal_line, histogram

    @staticmethod
    def _compute_bollinger(
        prices: list[float], period: int = 20, std_dev: float = 2.0
    ) -> tuple[list[float], list[float], list[float]]:
        """Compute Bollinger Bands (upper, middle, lower)."""
        upper, middle, lower = [], [], []
        for i in range(len(prices)):
            start = max(0, i - period + 1)
            window = prices[start : i + 1]
            avg = sum(window) / len(window)
            std = (sum((x - avg) ** 2 for x in window) / len(window)) ** 0.5
            middle.append(avg)
            upper.append(avg + std_dev * std)
            lower.append(avg - std_dev * std)
        return upper, middle, lower

    @staticmethod
    def _compute_atr(
        highs: list[float],
        lows: list[float],
        closes: list[float],
        period: int = 14,
    ) -> list[float]:
        """Compute Average True Range."""
        if len(highs) < 2:
            return [0.0]
        tr_values: list[float] = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
            tr_values.append(tr)

        if len(tr_values) < period:
            return tr_values

        atr = sum(tr_values[:period]) / period
        result = [atr]
        for tr in tr_values[period:]:
            atr = (atr * (period - 1) + tr) / period
            result.append(atr)
        return result
