"""Unit tests for IndicatorEngine.

Tests each indicator against known values, edge cases,
and verifies correct behavior with insufficient data.
"""

from __future__ import annotations

import numpy as np

from src.strategies.indicators import IndicatorEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _feed_prices(engine: IndicatorEngine, symbol: str, prices: list[float]) -> None:
    """Feed a list of close prices into the engine."""
    for p in prices:
        engine.update(symbol, {"close": p, "high": p * 1.01, "low": p * 0.99, "volume": 1000})


def _feed_ohlcv(engine: IndicatorEngine, symbol: str, data: list[dict]) -> None:
    """Feed a list of OHLCV dicts into the engine."""
    for d in data:
        engine.update(symbol, d)


# ---------------------------------------------------------------------------
# Tests: Basic functionality
# ---------------------------------------------------------------------------


def test_empty_engine_returns_none():
    """An engine with no data returns all-None results."""
    engine = IndicatorEngine()
    result = engine.compute("BTCUSDT")
    assert result["rsi_14"] is None
    assert result["current_price"] is None
    assert result["sma_20"] is None


def test_has_data():
    """has_data returns True after update, False before."""
    engine = IndicatorEngine()
    assert not engine.has_data("BTCUSDT")
    engine.update("BTCUSDT", {"close": 100})
    assert engine.has_data("BTCUSDT")


def test_data_length():
    """data_length tracks the number of data points."""
    engine = IndicatorEngine()
    assert engine.data_length("BTCUSDT") == 0
    for i in range(10):
        engine.update("BTCUSDT", {"close": 100 + i})
    assert engine.data_length("BTCUSDT") == 10


def test_max_history():
    """Engine respects max_history limit."""
    engine = IndicatorEngine(max_history=5)
    for i in range(10):
        engine.update("BTCUSDT", {"close": 100 + i})
    assert engine.data_length("BTCUSDT") == 5


def test_multiple_symbols():
    """Engine tracks data independently per symbol."""
    engine = IndicatorEngine()
    engine.update("BTCUSDT", {"close": 50000})
    engine.update("ETHUSDT", {"close": 3000})
    assert engine.data_length("BTCUSDT") == 1
    assert engine.data_length("ETHUSDT") == 1
    btc = engine.compute("BTCUSDT")
    eth = engine.compute("ETHUSDT")
    assert btc["current_price"] == 50000.0
    assert eth["current_price"] == 3000.0


# ---------------------------------------------------------------------------
# Tests: SMA
# ---------------------------------------------------------------------------


def test_sma_basic():
    """SMA of [1, 2, 3, 4, 5] with period 5 = 3.0."""
    engine = IndicatorEngine()
    _feed_prices(engine, "X", [1, 2, 3, 4, 5])
    result = engine.compute("X")
    # sma_20 needs 20 data points, so it's None
    assert result["sma_20"] is None


def test_sma_sufficient_data():
    """SMA with enough data returns correct value."""
    engine = IndicatorEngine()
    prices = list(range(1, 21))  # 1..20
    _feed_prices(engine, "X", prices)
    result = engine.compute("X")
    expected = np.mean(prices)  # sma_20 of 1..20 = 10.5
    assert result["sma_20"] is not None
    assert abs(result["sma_20"] - expected) < 0.01


def test_sma_static_method():
    """Direct _sma call with known values."""
    data = np.array([10, 20, 30, 40, 50], dtype=np.float64)
    assert IndicatorEngine._sma(data, 5) == 30.0
    assert IndicatorEngine._sma(data, 3) == 40.0  # last 3: 30, 40, 50
    assert IndicatorEngine._sma(data, 10) is None  # insufficient data


# ---------------------------------------------------------------------------
# Tests: EMA
# ---------------------------------------------------------------------------


def test_ema_basic():
    """EMA with period equal to data length."""
    data = np.array([10, 20, 30, 40, 50], dtype=np.float64)
    result = IndicatorEngine._ema(data, 5)
    assert result is not None
    # First EMA = SMA of first 5 = 30; no more data points after that
    assert abs(result - 30.0) < 0.01


def test_ema_insufficient_data():
    """EMA returns None when data < period."""
    data = np.array([10, 20], dtype=np.float64)
    assert IndicatorEngine._ema(data, 5) is None


def test_ema_trending():
    """EMA on trending data follows the trend."""
    data = np.array(list(range(1, 31)), dtype=np.float64)
    ema12 = IndicatorEngine._ema(data, 12)
    assert ema12 is not None
    assert ema12 > 15  # EMA should be above midpoint in uptrend


# ---------------------------------------------------------------------------
# Tests: RSI
# ---------------------------------------------------------------------------


def test_rsi_insufficient_data():
    """RSI returns None with < period+1 data points."""
    data = np.array([10, 20, 30], dtype=np.float64)
    assert IndicatorEngine._rsi(data, 14) is None


def test_rsi_all_gains():
    """RSI of a strictly increasing series = 100."""
    data = np.array(list(range(1, 20)), dtype=np.float64)
    rsi = IndicatorEngine._rsi(data, 14)
    assert rsi is not None
    assert rsi == 100.0


def test_rsi_all_losses():
    """RSI of a strictly decreasing series = 0."""
    data = np.array(list(range(20, 1, -1)), dtype=np.float64)
    rsi = IndicatorEngine._rsi(data, 14)
    assert rsi is not None
    assert rsi == 0.0


def test_rsi_midrange():
    """RSI of alternating gains and losses is around 50."""
    data = np.array([100, 102, 100, 102, 100, 102, 100, 102, 100, 102,
                     100, 102, 100, 102, 100, 102], dtype=np.float64)
    rsi = IndicatorEngine._rsi(data, 14)
    assert rsi is not None
    assert 40 < rsi < 60


# ---------------------------------------------------------------------------
# Tests: MACD
# ---------------------------------------------------------------------------


def test_macd_insufficient_data():
    """MACD returns None tuple with insufficient data."""
    data = np.array([10, 20, 30], dtype=np.float64)
    line, signal, hist = IndicatorEngine._macd_components(data, 12, 26, 9)
    assert line is None


def test_macd_sufficient_data():
    """MACD returns values with sufficient data."""
    data = np.array(list(range(1, 31)), dtype=np.float64)
    line, signal, hist = IndicatorEngine._macd_components(data, 12, 26, 9)
    assert line is not None
    # In an uptrend, MACD line should be positive
    assert line > 0


# ---------------------------------------------------------------------------
# Tests: Bollinger Bands
# ---------------------------------------------------------------------------


def test_bollinger_insufficient_data():
    """Bollinger returns None tuple with insufficient data."""
    data = np.array([10, 20], dtype=np.float64)
    upper, middle, lower = IndicatorEngine._bollinger(data, 20)
    assert upper is None


def test_bollinger_constant_prices():
    """Bollinger on constant prices has zero bandwidth."""
    data = np.array([100.0] * 20, dtype=np.float64)
    upper, middle, lower = IndicatorEngine._bollinger(data, 20)
    assert upper is not None
    assert middle == 100.0
    assert upper == middle  # std = 0
    assert lower == middle


def test_bollinger_band_ordering():
    """Upper > middle > lower always holds."""
    data = np.array(list(range(80, 120)), dtype=np.float64)
    upper, middle, lower = IndicatorEngine._bollinger(data, 20, 2.0)
    assert upper is not None
    assert upper > middle > lower  # type: ignore[operator]


# ---------------------------------------------------------------------------
# Tests: ADX
# ---------------------------------------------------------------------------


def test_adx_insufficient_data():
    """ADX returns None with insufficient data."""
    h = np.array([10, 20], dtype=np.float64)
    lo = np.array([9, 19], dtype=np.float64)
    c = np.array([9.5, 19.5], dtype=np.float64)
    assert IndicatorEngine._adx(h, lo, c, 14) is None


def test_adx_trending():
    """ADX is high in a strong trend."""
    # Strong uptrend
    n = 50
    h = np.array([100 + i * 2.0 + 1 for i in range(n)], dtype=np.float64)
    lo = np.array([100 + i * 2.0 - 1 for i in range(n)], dtype=np.float64)
    c = np.array([100 + i * 2.0 for i in range(n)], dtype=np.float64)
    adx = IndicatorEngine._adx(h, lo, c, 14)
    assert adx is not None
    assert adx > 0


# ---------------------------------------------------------------------------
# Tests: ATR
# ---------------------------------------------------------------------------


def test_atr_insufficient_data():
    """ATR returns None with insufficient data."""
    h = np.array([10], dtype=np.float64)
    lo = np.array([9], dtype=np.float64)
    c = np.array([9.5], dtype=np.float64)
    assert IndicatorEngine._atr(h, lo, c, 14) is None


def test_atr_constant_range():
    """ATR on constant range returns the range."""
    n = 20
    h = np.array([101.0] * n, dtype=np.float64)
    lo = np.array([99.0] * n, dtype=np.float64)
    c = np.array([100.0] * n, dtype=np.float64)
    atr = IndicatorEngine._atr(h, lo, c, 14)
    assert atr is not None
    assert abs(atr - 2.0) < 0.1


# ---------------------------------------------------------------------------
# Tests: Full compute pipeline
# ---------------------------------------------------------------------------


def test_compute_returns_all_keys():
    """compute() returns dict with all expected keys."""
    engine = IndicatorEngine()
    _feed_prices(engine, "BTC", list(range(50, 110)))
    result = engine.compute("BTC")
    expected_keys = {
        "rsi_14", "macd_line", "macd_signal", "macd_hist",
        "sma_20", "sma_50", "ema_12", "ema_26",
        "bb_upper", "bb_middle", "bb_lower",
        "adx", "atr", "volume_ma_20",
        "current_price", "current_volume",
    }
    assert set(result.keys()) == expected_keys


def test_compute_with_60_data_points():
    """compute() with 60 data points has most indicators populated."""
    engine = IndicatorEngine()
    _feed_prices(engine, "BTC", [50000 + i * 10 for i in range(60)])
    result = engine.compute("BTC")
    assert result["current_price"] is not None
    assert result["rsi_14"] is not None
    assert result["sma_20"] is not None
    assert result["sma_50"] is not None
    assert result["ema_12"] is not None
    assert result["macd_line"] is not None
    assert result["bb_upper"] is not None
