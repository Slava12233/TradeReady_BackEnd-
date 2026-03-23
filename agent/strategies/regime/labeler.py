"""Market regime labeler.

Assigns one of four RegimeTypes to each OHLCV candle using rule-based logic:

1. Compute ADX over a rolling window:
   - ADX > 25 → TRENDING

2. Compute ATR / close (normalised volatility ratio) for non-trending candles:
   - ratio > 2x median → HIGH_VOLATILITY
   - ratio < 0.5x median → LOW_VOLATILITY

3. All remaining candles → MEAN_REVERTING

The labeler is deterministic: identical inputs always produce identical outputs.
It mirrors the indicator implementations in ``src/strategies/indicators.py``
(pure-numpy, no TA-Lib) so the feature set is consistent with the rest of the
platform's strategy engine.
"""

from __future__ import annotations

import enum
from collections import deque

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# ADX threshold for classifying a window as "trending".
ADX_TREND_THRESHOLD = 25.0

# ATR/close ratio multipliers relative to the median for volatility regimes.
HIGH_VOLATILITY_MULTIPLIER = 2.0
LOW_VOLATILITY_MULTIPLIER = 0.5

# Minimum number of candles required before labelling begins.
# Determined by the slowest indicator (ADX requires period + 1 candles).
MIN_CANDLES_FOR_LABELLING = 30


class RegimeType(str, enum.Enum):
    """Market regime categories.

    Values are lowercase strings so they serialise cleanly to JSON and are
    human-readable in logs and model artefacts.
    """

    TRENDING = "trending"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"


# ---------------------------------------------------------------------------
# Indicator helpers (mirror of src/strategies/indicators.py — standalone)
# ---------------------------------------------------------------------------

def _atr_series(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> np.ndarray:
    """Compute ATR for every position using a Wilder-smoothed rolling TR.

    Returns an array of the same length as ``closes`` with ``nan`` for
    positions that do not have enough history.
    """
    n = len(closes)
    result = np.full(n, np.nan)
    if n < period + 1:
        return result

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )

    # First ATR value = simple average of first `period` true ranges.
    atr = float(np.mean(tr[:period]))
    result[period] = atr  # index period corresponds to tr[period-1]

    for i in range(period, len(tr)):
        atr = (atr * (period - 1) + float(tr[i])) / period
        result[i + 1] = atr

    return result


def _adx_series(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Compute ADX for every position, returning a same-length float array.

    Positions without enough history are ``nan``.
    """
    n = len(closes)
    result = np.full(n, np.nan)
    if n < period + 1:
        return result

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1]),
        ),
    )
    plus_dm = np.where(
        (highs[1:] - highs[:-1]) > (lows[:-1] - lows[1:]),
        np.maximum(highs[1:] - highs[:-1], 0.0),
        0.0,
    )
    minus_dm = np.where(
        (lows[:-1] - lows[1:]) > (highs[1:] - highs[:-1]),
        np.maximum(lows[:-1] - lows[1:], 0.0),
        0.0,
    )

    m = len(tr)
    if m < period:
        return result

    # Initialise smoothed values using simple mean of first `period` bars.
    atr_s = float(np.mean(tr[:period]))
    plus_s = float(np.mean(plus_dm[:period]))
    minus_s = float(np.mean(minus_dm[:period]))

    dx_queue: deque[float] = deque()

    for i in range(period, m):
        atr_s = (atr_s * (period - 1) + float(tr[i])) / period
        plus_s = (plus_s * (period - 1) + float(plus_dm[i])) / period
        minus_s = (minus_s * (period - 1) + float(minus_dm[i])) / period

        if atr_s == 0:
            continue

        plus_di = 100.0 * plus_s / atr_s
        minus_di = 100.0 * minus_s / atr_s
        di_sum = plus_di + minus_di
        if di_sum == 0:
            continue

        dx = abs(plus_di - minus_di) / di_sum * 100.0
        dx_queue.append(dx)

        if len(dx_queue) >= period:
            # ADX = average of the last `period` DX values.
            adx_val = float(np.mean(list(dx_queue)[-period:]))
            # i in tr corresponds to candle index i+1 (because tr starts at
            # index 1 of the closes array).
            result[i + 1] = adx_val

    return result


def _bb_width_series(closes: np.ndarray, period: int = 20, std_dev: float = 2.0) -> np.ndarray:
    """Bollinger Band width ((upper - lower) / middle) for each position.

    Positions without enough history are ``nan``.
    """
    n = len(closes)
    result = np.full(n, np.nan)
    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        middle = float(np.mean(window))
        if middle == 0:
            continue
        std = float(np.std(window, ddof=0))
        upper = middle + std_dev * std
        lower = middle - std_dev * std
        result[i] = (upper - lower) / middle
    return result


def _rsi_series(closes: np.ndarray, period: int = 14) -> np.ndarray:
    """RSI using Wilder's smoothing for each position.

    Returns same-length float array; ``nan`` where not enough history.
    """
    n = len(closes)
    result = np.full(n, np.nan)
    if n < period + 1:
        return result

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    for i in range(period, n - 1):
        avg_gain = (avg_gain * (period - 1) + float(gains[i])) / period
        avg_loss = (avg_loss * (period - 1) + float(losses[i])) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return result


def _volume_ratio_series(volumes: np.ndarray, period: int = 20) -> np.ndarray:
    """Volume ratio (current volume / SMA of volume over `period` bars).

    A ratio > 1 means above-average volume; < 1 means below-average.  This
    feature captures volume-driven regime transitions (e.g. breakout on
    high volume, accumulation on low volume) that price-only indicators miss.

    Returns same-length float array; ``nan`` for the first ``period - 1``
    positions where the rolling SMA cannot be computed.

    Args:
        volumes: Array of per-candle volume values.
        period: Rolling window length for the volume SMA (default 20).

    Returns:
        Float array of length ``len(volumes)``.  Positions where the SMA is
        zero (all-zero volume window) are returned as ``nan`` to avoid
        division-by-zero artefacts.
    """
    n = len(volumes)
    result = np.full(n, np.nan)
    for i in range(period - 1, n):
        window = volumes[i - period + 1 : i + 1]
        sma = float(np.mean(window))
        if sma == 0.0:
            continue
        result[i] = float(volumes[i]) / sma
    return result


def _macd_hist_series(
    closes: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> np.ndarray:
    """MACD histogram for each position.

    Returns same-length float array; ``nan`` where not enough history.
    """
    n = len(closes)
    result = np.full(n, np.nan)
    if n < slow:
        return result

    def _ema_arr(data: np.ndarray, p: int) -> np.ndarray:
        mult = 2.0 / (p + 1)
        out = np.empty(len(data))
        out[0] = float(np.mean(data[:p])) if len(data) >= p else float(data[0])
        for j in range(1, len(data)):
            out[j] = (float(data[j]) - out[j - 1]) * mult + out[j - 1]
        return out

    fast_ema = _ema_arr(closes, fast)
    slow_ema = _ema_arr(closes, slow)
    macd_line = fast_ema - slow_ema

    if len(macd_line) < signal:
        return result

    signal_ema = _ema_arr(macd_line, signal)
    hist = macd_line - signal_ema

    # Align: hist[i] corresponds to closes[i].
    result[: len(hist)] = hist
    return result


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def label_candles(candles: list[dict], window: int = 20) -> list[RegimeType]:
    """Assign a RegimeType to each candle based on ADX and ATR/close ratio.

    Args:
        candles: List of OHLCV dicts with at least ``high``, ``low``,
                 ``close`` keys. ``open`` and ``volume`` are accepted but
                 not used for labelling.
        window: Lookback period for ADX and ATR computation (default 20).
                Must be >= 2.

    Returns:
        List of RegimeType values, one per input candle. Candles that do not
        yet have enough history for the indicators are labelled
        MEAN_REVERTING (conservative default).

    Raises:
        ValueError: If ``candles`` is empty or ``window`` < 2.
    """
    if not candles:
        raise ValueError("candles list must not be empty")
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")

    n = len(candles)
    highs = np.array([float(c.get("high", c.get("close", 0))) for c in candles], dtype=np.float64)
    lows = np.array([float(c.get("low", c.get("close", 0))) for c in candles], dtype=np.float64)
    closes = np.array([float(c["close"]) for c in candles], dtype=np.float64)

    adx_arr = _adx_series(highs, lows, closes, period=window)
    atr_arr = _atr_series(highs, lows, closes, period=window)

    # Compute ATR/close ratio; protect against zero close prices.
    with np.errstate(invalid="ignore", divide="ignore"):
        atr_ratio = np.where(closes > 0, atr_arr / closes, np.nan)

    # Global median of valid ATR ratios for volatility thresholds.
    valid_ratios = atr_ratio[~np.isnan(atr_ratio)]
    if len(valid_ratios) == 0:
        # Not enough data — return all MEAN_REVERTING.
        logger.warning("agent.strategy.regime.labeler.insufficient_data", n_candles=n, window=window)
        return [RegimeType.MEAN_REVERTING] * n

    median_ratio = float(np.median(valid_ratios))
    high_vol_threshold = HIGH_VOLATILITY_MULTIPLIER * median_ratio
    low_vol_threshold = LOW_VOLATILITY_MULTIPLIER * median_ratio

    labels: list[RegimeType] = []
    for i in range(n):
        adx_val = adx_arr[i]
        ratio_val = atr_ratio[i]

        # Priority 1: Trending (ADX threshold).
        if not np.isnan(adx_val) and adx_val > ADX_TREND_THRESHOLD:
            labels.append(RegimeType.TRENDING)
            continue

        # Priority 2: Volatility (ATR/close vs median).
        if not np.isnan(ratio_val):
            if ratio_val > high_vol_threshold:
                labels.append(RegimeType.HIGH_VOLATILITY)
                continue
            if ratio_val < low_vol_threshold:
                labels.append(RegimeType.LOW_VOLATILITY)
                continue

        # Default: mean-reverting / insufficient data.
        labels.append(RegimeType.MEAN_REVERTING)

    logger.debug(
        "agent.strategy.regime.labeler.labelled",
        n_candles=n,
        window=window,
        trending=labels.count(RegimeType.TRENDING),
        mean_reverting=labels.count(RegimeType.MEAN_REVERTING),
        high_volatility=labels.count(RegimeType.HIGH_VOLATILITY),
        low_volatility=labels.count(RegimeType.LOW_VOLATILITY),
    )
    return labels


def generate_training_data(
    candles: list[dict],
    window: int = 20,
) -> tuple[pd.DataFrame, pd.Series]:
    """Build feature matrix and label series for classifier training.

    Drops rows with any NaN features so the classifier receives a clean
    dataset. Because of rolling-window warm-up, the first ``window + 25``
    or so rows are typically dropped.

    Features per candle:
    - ``adx``: Average Directional Index (trend strength)
    - ``atr_ratio``: ATR / close (normalised volatility)
    - ``bb_width``: Bollinger Band width relative to middle band
    - ``rsi``: Relative Strength Index
    - ``macd_hist``: MACD histogram
    - ``volume_ratio``: Current volume / 20-period SMA of volume — captures
      volume-driven regime transitions (breakouts, accumulation) that
      price-only indicators cannot detect

    Args:
        candles: List of OHLCV dicts (same format as ``label_candles``).
                 Each dict must contain a ``volume`` key for ``volume_ratio``
                 to be computed; candles without a ``volume`` key are treated
                 as having zero volume (``volume_ratio`` will be NaN for those
                 rows and they will be dropped from the output).
        window: Rolling period for ADX and ATR (default 20). RSI uses 14,
                Bollinger Bands use 20, and volume SMA uses 20 regardless of
                this parameter.

    Returns:
        A tuple of (features_df, labels_series). Both have the same integer
        index aligned to the surviving (non-NaN) candle positions. The
        labels_series values are RegimeType string values.

    Raises:
        ValueError: If ``candles`` is empty, ``window`` < 2, or no rows
                    remain after dropping NaN features.
    """
    if not candles:
        raise ValueError("candles list must not be empty")
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")

    n = len(candles)
    highs = np.array([float(c.get("high", c.get("close", 0))) for c in candles], dtype=np.float64)
    lows = np.array([float(c.get("low", c.get("close", 0))) for c in candles], dtype=np.float64)
    closes = np.array([float(c["close"]) for c in candles], dtype=np.float64)
    volumes = np.array([float(c.get("volume", 0.0)) for c in candles], dtype=np.float64)

    # Compute all features as same-length arrays (nan where insufficient).
    adx_arr = _adx_series(highs, lows, closes, period=window)
    atr_arr = _atr_series(highs, lows, closes, period=window)
    with np.errstate(invalid="ignore", divide="ignore"):
        atr_ratio_arr = np.where(closes > 0, atr_arr / closes, np.nan)
    bb_width_arr = _bb_width_series(closes, period=20)
    rsi_arr = _rsi_series(closes, period=14)
    macd_hist_arr = _macd_hist_series(closes, fast=12, slow=26, signal=9)
    # volume_ratio = current volume / 20-period SMA of volume.
    # Captures volume-driven regime transitions (breakouts, accumulation phases)
    # that price-only indicators cannot detect.  A ratio > 1 indicates
    # above-average activity; < 1 indicates below-average activity.
    volume_ratio_arr = _volume_ratio_series(volumes, period=20)

    features_df = pd.DataFrame(
        {
            "adx": adx_arr,
            "atr_ratio": atr_ratio_arr,
            "bb_width": bb_width_arr,
            "rsi": rsi_arr,
            "macd_hist": macd_hist_arr,
            "volume_ratio": volume_ratio_arr,
        },
        index=range(n),
    )

    # Generate labels for all candles.
    all_labels = label_candles(candles, window=window)
    labels_series = pd.Series(
        [lbl.value for lbl in all_labels],
        index=range(n),
        name="regime",
        dtype="object",
    )

    # Drop rows where any feature is NaN.
    valid_mask = features_df.notna().all(axis=1)
    features_df = features_df[valid_mask].reset_index(drop=True)
    labels_series = labels_series[valid_mask].reset_index(drop=True)

    if len(features_df) == 0:
        raise ValueError(
            f"No valid rows after dropping NaN features. "
            f"Input had {n} candles but none survived the warm-up period. "
            f"Increase the number of candles or reduce window={window}."
        )

    logger.info(
        "agent.strategy.regime.labeler.training_data_generated",
        input_candles=n,
        valid_rows=len(features_df),
        dropped_rows=n - len(features_df),
        label_distribution=labels_series.value_counts().to_dict(),
    )
    return features_df, labels_series
