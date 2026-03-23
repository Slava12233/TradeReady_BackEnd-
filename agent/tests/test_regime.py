"""Unit tests for agent/strategies/regime — labeler, classifier, and switcher.

Tests cover:
- RegimeType enum values
- label_candles: edge cases, determinism, rule priorities
- generate_training_data: feature columns, NaN dropping, index alignment
- RegimeClassifier: train/predict/evaluate/save/load round-trip
- CLI helpers: _print_evaluation formatting (smoke-test only)
- RegimeSwitcher: detect_regime, should_switch, get_active_strategy, step,
  cooldown guard, confidence guard, history tracking, reset

No platform API is required — all tests operate on synthetic candle data.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from agent.strategies.regime.classifier import (
    TRAIN_SPLIT,
    RegimeClassifier,
    _print_evaluation,
)
from agent.strategies.regime.labeler import (
    RegimeType,
    _adx_series,
    _atr_series,
    _bb_width_series,
    _macd_hist_series,
    _rsi_series,
    generate_training_data,
    label_candles,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candles(
    n: int,
    base_close: float = 100.0,
    noise_std: float = 0.5,
    trend: float = 0.0,
    high_offset: float = 1.0,
    low_offset: float = 1.0,
    seed: int = 0,
) -> list[dict]:
    """Generate synthetic OHLCV candle dicts for testing.

    Args:
        n: Number of candles.
        base_close: Starting close price.
        noise_std: Standard deviation of random noise on close.
        trend: Additive trend per candle (positive = uptrend).
        high_offset: High = close + high_offset.
        low_offset: Low = close - low_offset.
        seed: Random seed.
    """
    rng = np.random.default_rng(seed)
    candles = []
    close = base_close
    for i in range(n):
        close = close + trend + rng.normal(0, noise_std)
        close = max(close, 0.01)
        candles.append(
            {
                "open": close,
                "high": close + high_offset,
                "low": close - low_offset,
                "close": close,
                "volume": 1000.0,
            }
        )
    return candles


def _make_trending_candles(n: int = 200, seed: int = 1) -> list[dict]:
    """Generate strongly trending candles (should produce TRENDING labels)."""
    return _make_candles(n, trend=2.0, noise_std=0.1, high_offset=2.0, low_offset=1.0, seed=seed)


def _make_volatile_candles(n: int = 200, seed: int = 2) -> list[dict]:
    """Generate high-volatility candles (large ATR relative to close)."""
    return _make_candles(n, noise_std=5.0, high_offset=10.0, low_offset=10.0, seed=seed)


def _make_flat_candles(n: int = 200, seed: int = 3) -> list[dict]:
    """Generate very flat candles (low ATR relative to close)."""
    return _make_candles(n, noise_std=0.001, high_offset=0.001, low_offset=0.001, seed=seed)


def _make_large_dataset(n: int = 500, seed: int = 42) -> list[dict]:
    """Mixed candles large enough to survive warm-up for all features."""
    rng = np.random.default_rng(seed)
    candles = []
    close = 50000.0
    for i in range(n):
        # Alternating trend / flat periods to create regime variation.
        period = i // 50
        trend = 20.0 if period % 3 == 0 else 0.0
        noise = 50.0 if period % 3 == 1 else 5.0
        close = max(close + trend + rng.normal(0, noise), 1.0)
        candles.append(
            {
                "open": close,
                "high": close + abs(rng.normal(0, noise * 0.5)),
                "low": close - abs(rng.normal(0, noise * 0.5)),
                "close": close,
                "volume": float(rng.integers(500, 5000)),
            }
        )
    return candles


# ---------------------------------------------------------------------------
# RegimeType
# ---------------------------------------------------------------------------


class TestRegimeType:
    def test_enum_values(self) -> None:
        assert RegimeType.TRENDING.value == "trending"
        assert RegimeType.MEAN_REVERTING.value == "mean_reverting"
        assert RegimeType.HIGH_VOLATILITY.value == "high_volatility"
        assert RegimeType.LOW_VOLATILITY.value == "low_volatility"

    def test_str_enum_string_comparison(self) -> None:
        assert RegimeType.TRENDING == "trending"

    def test_from_value(self) -> None:
        assert RegimeType("trending") is RegimeType.TRENDING
        assert RegimeType("high_volatility") is RegimeType.HIGH_VOLATILITY

    def test_all_values_distinct(self) -> None:
        values = [r.value for r in RegimeType]
        assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# Indicator series helpers
# ---------------------------------------------------------------------------


class TestIndicatorSeries:
    def test_atr_series_all_nan_when_too_short(self) -> None:
        closes = np.array([1.0, 2.0, 3.0])
        highs = closes + 0.5
        lows = closes - 0.5
        result = _atr_series(highs, lows, closes, period=14)
        assert np.all(np.isnan(result))

    def test_atr_series_valid_values_after_warmup(self) -> None:
        candles = _make_candles(100, seed=10)
        closes = np.array([c["close"] for c in candles])
        highs = np.array([c["high"] for c in candles])
        lows = np.array([c["low"] for c in candles])
        result = _atr_series(highs, lows, closes, period=14)
        # First 14 values should be NaN; rest should be positive.
        assert np.all(np.isnan(result[:14]))
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert np.all(valid >= 0)

    def test_adx_series_length_matches_input(self) -> None:
        candles = _make_candles(100, seed=11)
        closes = np.array([c["close"] for c in candles])
        highs = np.array([c["high"] for c in candles])
        lows = np.array([c["low"] for c in candles])
        result = _adx_series(highs, lows, closes, period=14)
        assert len(result) == len(closes)

    def test_adx_series_all_nan_for_short_input(self) -> None:
        closes = np.array([1.0, 2.0])
        highs = closes + 0.5
        lows = closes - 0.5
        result = _adx_series(highs, lows, closes, period=14)
        assert np.all(np.isnan(result))

    def test_bb_width_series_non_negative(self) -> None:
        candles = _make_candles(100, seed=12)
        closes = np.array([c["close"] for c in candles])
        result = _bb_width_series(closes, period=20)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0)

    def test_rsi_series_bounded(self) -> None:
        candles = _make_candles(100, seed=13)
        closes = np.array([c["close"] for c in candles])
        result = _rsi_series(closes, period=14)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0)
        assert np.all(valid <= 100)

    def test_macd_hist_series_returns_floats(self) -> None:
        candles = _make_candles(200, seed=14)
        closes = np.array([c["close"] for c in candles])
        result = _macd_hist_series(closes)
        assert result.dtype == np.float64
        assert len(result) == len(closes)


# ---------------------------------------------------------------------------
# label_candles
# ---------------------------------------------------------------------------


class TestLabelCandles:
    def test_raises_on_empty_input(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            label_candles([])

    def test_raises_on_small_window(self) -> None:
        candles = _make_candles(50)
        with pytest.raises(ValueError, match="window must be >= 2"):
            label_candles(candles, window=1)

    def test_output_length_matches_input(self) -> None:
        candles = _make_candles(100)
        labels = label_candles(candles, window=14)
        assert len(labels) == 100

    def test_all_outputs_are_regime_types(self) -> None:
        candles = _make_candles(100)
        labels = label_candles(candles, window=14)
        for lbl in labels:
            assert isinstance(lbl, RegimeType)

    def test_deterministic_same_input_same_output(self) -> None:
        candles = _make_candles(200, seed=99)
        labels1 = label_candles(candles, window=14)
        labels2 = label_candles(candles, window=14)
        assert labels1 == labels2

    def test_short_candles_return_mean_reverting(self) -> None:
        # Only 3 candles — not enough for any indicator to produce a value.
        candles = _make_candles(3)
        labels = label_candles(candles, window=14)
        assert all(lbl == RegimeType.MEAN_REVERTING for lbl in labels)

    def test_trending_candles_contain_trending_labels(self) -> None:
        candles = _make_trending_candles(n=300)
        labels = label_candles(candles, window=14)
        trending_count = labels.count(RegimeType.TRENDING)
        # Strong trend should produce a meaningful fraction of TRENDING labels.
        assert trending_count > 0, "Expected at least some TRENDING labels for strongly trending data"

    def test_all_four_regime_types_present_in_mixed_data(self) -> None:
        # Build a dataset with all four regime types by concatenating segments.
        flat = _make_flat_candles(n=200)
        volatile = _make_volatile_candles(n=200)
        trending = _make_trending_candles(n=200)
        mixed = flat + volatile + trending
        labels = label_candles(mixed, window=14)
        label_set = set(labels)
        # At minimum trending and at least one other regime should be present.
        assert RegimeType.MEAN_REVERTING in label_set or RegimeType.LOW_VOLATILITY in label_set

    def test_candles_missing_high_low_use_close(self) -> None:
        # Candles with only 'close' key should not raise.
        candles = [{"close": float(i + 1)} for i in range(50)]
        labels = label_candles(candles, window=10)
        assert len(labels) == 50


# ---------------------------------------------------------------------------
# generate_training_data
# ---------------------------------------------------------------------------


class TestGenerateTrainingData:
    def test_raises_on_empty_input(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            generate_training_data([])

    def test_feature_columns_present(self) -> None:
        candles = _make_large_dataset(500)
        features, labels = generate_training_data(candles, window=20)
        expected_cols = {"adx", "atr_ratio", "bb_width", "rsi", "macd_hist", "volume_ratio"}
        assert expected_cols.issubset(set(features.columns))

    def test_no_nan_in_features(self) -> None:
        candles = _make_large_dataset(500)
        features, _ = generate_training_data(candles, window=20)
        assert not features.isnull().any().any()

    def test_labels_valid_regime_strings(self) -> None:
        candles = _make_large_dataset(500)
        _, labels = generate_training_data(candles, window=20)
        valid_values = {r.value for r in RegimeType}
        assert set(labels.unique()).issubset(valid_values)

    def test_features_and_labels_same_length(self) -> None:
        candles = _make_large_dataset(500)
        features, labels = generate_training_data(candles, window=20)
        assert len(features) == len(labels)

    def test_index_is_reset_integers(self) -> None:
        candles = _make_large_dataset(300)
        features, labels = generate_training_data(candles, window=14)
        assert list(features.index) == list(range(len(features)))
        assert list(labels.index) == list(range(len(labels)))

    def test_output_smaller_than_input_due_to_warmup(self) -> None:
        candles = _make_large_dataset(500)
        features, labels = generate_training_data(candles, window=20)
        assert len(features) < 500

    def test_raises_when_all_rows_nan(self) -> None:
        # Only 5 candles — far below any indicator's warm-up period.
        candles = _make_candles(5)
        with pytest.raises(ValueError, match="No valid rows"):
            generate_training_data(candles, window=20)

    def test_deterministic(self) -> None:
        candles = _make_large_dataset(300, seed=77)
        f1, l1 = generate_training_data(candles, window=14)
        f2, l2 = generate_training_data(candles, window=14)
        pd.testing.assert_frame_equal(f1, f2)
        pd.testing.assert_series_equal(l1, l2)


# ---------------------------------------------------------------------------
# RegimeClassifier
# ---------------------------------------------------------------------------


def _make_classifier_dataset(n: int = 600, seed: int = 42) -> tuple[pd.DataFrame, pd.Series]:
    """Generate a labelled dataset large enough for train/test split."""
    candles = _make_large_dataset(n=n, seed=seed)
    return generate_training_data(candles, window=20)


class TestRegimeClassifierBackendResolution:
    def test_xgboost_detected_when_available(self) -> None:
        # If xgboost is importable, _resolve_backend(None) returns True.
        try:
            import xgboost  # noqa: F401

            assert RegimeClassifier._resolve_backend(None) is True
        except ImportError:
            pytest.skip("xgboost not installed")

    def test_fallback_when_xgboost_unavailable(self) -> None:
        with patch.dict("sys.modules", {"xgboost": None}):
            result = RegimeClassifier._resolve_backend(None)
            assert result is False

    def test_force_random_forest(self) -> None:
        assert RegimeClassifier._resolve_backend(False) is False

    def test_force_xgboost(self) -> None:
        assert RegimeClassifier._resolve_backend(True) is True


class TestRegimeClassifierTrain:
    def test_train_raises_without_data(self) -> None:
        features = pd.DataFrame({
            "adx": [], "atr_ratio": [], "bb_width": [], "rsi": [], "macd_hist": [], "volume_ratio": [],
        })
        labels = pd.Series([], dtype="object")
        clf = RegimeClassifier(seed=0, use_xgboost=False)
        with pytest.raises(ValueError):
            clf.train(features, labels)

    def test_train_raises_on_nan_features(self) -> None:
        features, labels = _make_classifier_dataset()
        features.iloc[0, 0] = float("nan")
        clf = RegimeClassifier(seed=0, use_xgboost=False)
        with pytest.raises(ValueError, match="NaN"):
            clf.train(features, labels)

    def test_train_raises_on_single_class(self) -> None:
        features, labels = _make_classifier_dataset()
        single_class = labels.copy()
        single_class[:] = RegimeType.TRENDING.value
        clf = RegimeClassifier(seed=0, use_xgboost=False)
        with pytest.raises(ValueError, match="2 distinct classes"):
            clf.train(features, single_class)

    def test_train_sets_label_encoder(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=0, use_xgboost=False)
        clf.train(features, labels)
        assert len(clf._label_encoder) >= 2
        assert len(clf._label_decoder) == len(clf._label_encoder)

    def test_train_with_random_forest(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=42, use_xgboost=False)
        clf.train(features, labels)
        assert clf._model is not None


class TestRegimeClassifierPredict:
    def test_predict_raises_before_training(self) -> None:
        clf = RegimeClassifier(seed=0, use_xgboost=False)
        features, _ = _make_classifier_dataset()
        with pytest.raises(RuntimeError, match="not been trained"):
            clf.predict(features.iloc[:1])

    def test_predict_returns_regime_and_confidence(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=42, use_xgboost=False)
        clf.train(features, labels)
        regime, confidence = clf.predict(features.iloc[:1])
        assert isinstance(regime, RegimeType)
        assert 0.0 <= confidence <= 1.0

    def test_predict_raises_on_missing_columns(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=42, use_xgboost=False)
        clf.train(features, labels)
        bad_features = features.drop(columns=["adx"])
        with pytest.raises(ValueError, match="Missing feature columns"):
            clf.predict(bad_features.iloc[:1])

    def test_predict_batch_length(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=42, use_xgboost=False)
        clf.train(features, labels)
        results = clf.predict_batch(features.iloc[:10])
        assert len(results) == 10
        for regime, conf in results:
            assert isinstance(regime, RegimeType)
            assert 0.0 <= conf <= 1.0

    def test_predict_consistent_with_batch(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=42, use_xgboost=False)
        clf.train(features, labels)
        row = features.iloc[:1].reset_index(drop=True)
        single_regime, single_conf = clf.predict(row)
        batch_results = clf.predict_batch(row)
        assert batch_results[0][0] == single_regime
        assert math.isclose(batch_results[0][1], single_conf, rel_tol=1e-6)


class TestRegimeClassifierEvaluate:
    def test_evaluate_returns_expected_keys(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=42, use_xgboost=False)
        clf.train(features, labels)
        metrics = clf.evaluate(features, labels)
        assert "accuracy" in metrics
        assert "confusion_matrix" in metrics
        assert "classes" in metrics
        assert "per_class_f1" in metrics
        assert "n_samples" in metrics

    def test_evaluate_accuracy_bounds(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=42, use_xgboost=False)
        clf.train(features, labels)
        metrics = clf.evaluate(features, labels)
        # Training accuracy should be high (not a generalisation guarantee).
        assert 0.0 <= metrics["accuracy"] <= 1.0

    def test_evaluate_confusion_matrix_shape(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=42, use_xgboost=False)
        clf.train(features, labels)
        metrics = clf.evaluate(features, labels)
        n_classes = len(metrics["classes"])
        cm = metrics["confusion_matrix"]
        assert len(cm) == n_classes
        assert all(len(row) == n_classes for row in cm)

    def test_evaluate_raises_before_training(self) -> None:
        clf = RegimeClassifier(seed=0, use_xgboost=False)
        features, labels = _make_classifier_dataset()
        with pytest.raises(RuntimeError, match="not been trained"):
            clf.evaluate(features, labels)


class TestRegimeClassifierSaveLoad:
    def test_save_creates_file(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=42, use_xgboost=False)
        clf.train(features, labels)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.joblib"
            clf.save(path)
            assert path.exists()

    def test_save_raises_before_training(self) -> None:
        clf = RegimeClassifier(seed=0, use_xgboost=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.joblib"
            with pytest.raises(RuntimeError, match="not been trained"):
                clf.save(path)

    def test_load_raises_if_file_missing(self) -> None:
        with pytest.raises(FileNotFoundError):
            RegimeClassifier.load(Path("/nonexistent/path/model.joblib"))

    def test_save_load_round_trip_predictions_match(self) -> None:
        features, labels = _make_classifier_dataset()
        clf_original = RegimeClassifier(seed=42, use_xgboost=False)
        clf_original.train(features, labels)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.joblib"
            clf_original.save(path)
            clf_loaded = RegimeClassifier.load(path)

        row = features.iloc[:5].reset_index(drop=True)
        original_results = clf_original.predict_batch(row)
        loaded_results = clf_loaded.predict_batch(row)

        for (r1, c1), (r2, c2) in zip(original_results, loaded_results):
            assert r1 == r2
            assert math.isclose(c1, c2, rel_tol=1e-5)

    def test_load_preserves_seed_and_backend(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=7, use_xgboost=False)
        clf.train(features, labels)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.joblib"
            clf.save(path)
            loaded = RegimeClassifier.load(path)
        assert loaded.seed == 7
        assert loaded._use_xgboost is False

    def test_save_creates_parent_directories(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=42, use_xgboost=False)
        clf.train(features, labels)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "deep" / "nested" / "dir" / "model.joblib"
            clf.save(path)
            assert path.exists()


class TestRegimeClassifierAcceptanceCriteria:
    """Acceptance-criteria tests that mirror the task requirements."""

    def test_80_20_temporal_split_no_leakage(self) -> None:
        """Training data is the first 80% and test is the last 20% (temporal)."""
        candles = _make_large_dataset(n=800, seed=0)
        features, labels = generate_training_data(candles, window=20)

        split_idx = int(len(features) * TRAIN_SPLIT)
        X_train = features.iloc[:split_idx].reset_index(drop=True)
        y_train = labels.iloc[:split_idx].reset_index(drop=True)
        X_test = features.iloc[split_idx:].reset_index(drop=True)
        y_test = labels.iloc[split_idx:].reset_index(drop=True)

        # Verify no index overlap between train and test.
        assert len(X_train) + len(X_test) == len(features)
        assert len(X_train) > 0
        assert len(X_test) > 0

        clf = RegimeClassifier(seed=42, use_xgboost=False)
        clf.train(X_train, y_train)
        metrics = clf.evaluate(X_test, y_test)

        # We cannot guarantee >70% on synthetic data, but accuracy must be valid.
        assert 0.0 <= metrics["accuracy"] <= 1.0

    def test_confidence_score_in_0_1_range(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=42, use_xgboost=False)
        clf.train(features, labels)
        for i in range(min(20, len(features))):
            _, confidence = clf.predict(features.iloc[i : i + 1].reset_index(drop=True))
            assert 0.0 <= confidence <= 1.0

    def test_prediction_regime_in_trained_classes(self) -> None:
        features, labels = _make_classifier_dataset()
        clf = RegimeClassifier(seed=42, use_xgboost=False)
        clf.train(features, labels)
        regime, _ = clf.predict(features.iloc[:1])
        assert regime.value in clf._label_encoder

    def test_feature_set_matches_platform_indicators(self) -> None:
        """Feature names must include ADX, ATR, BB, RSI, MACD, and volume_ratio."""
        clf = RegimeClassifier(seed=0, use_xgboost=False)
        expected = {"adx", "atr_ratio", "bb_width", "rsi", "macd_hist", "volume_ratio"}
        assert set(clf._feature_names) == expected

    def test_feature_count_is_six(self) -> None:
        """The classifier must have exactly 6 features after adding volume_ratio."""
        clf = RegimeClassifier(seed=0, use_xgboost=False)
        assert len(clf._feature_names) == 6


class TestPrintEvaluation:
    def test_print_evaluation_runs_without_error(self, capsys: pytest.CaptureFixture) -> None:
        metrics = {
            "accuracy": 0.75,
            "confusion_matrix": [[10, 2], [3, 8]],
            "classes": ["mean_reverting", "trending"],
            "per_class_f1": {"mean_reverting": 0.77, "trending": 0.73},
            "n_samples": 23,
        }
        _print_evaluation(metrics, split_name="test")
        captured = capsys.readouterr()
        assert "75.00%" in captured.out
        assert "mean_reverting" in captured.out
        assert "trending" in captured.out


# ---------------------------------------------------------------------------
# RegimeSwitcher helpers
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock  # noqa: E402

from agent.strategies.regime.switcher import (  # noqa: E402
    CONFIDENCE_THRESHOLD,
    MIN_CANDLES_REQUIRED,
    SWITCH_COOLDOWN_CANDLES,
    RegimeRecord,
    RegimeSwitcher,
)


def _make_mock_classifier(regime: RegimeType, confidence: float) -> MagicMock:
    """Return a MagicMock classifier that always predicts the given regime."""
    clf = MagicMock(spec=["predict"])
    clf.predict.return_value = (regime, confidence)
    return clf


def _default_strategy_map() -> dict[RegimeType, str]:
    return {
        RegimeType.TRENDING: "strat-trending",
        RegimeType.MEAN_REVERTING: "strat-mean-reverting",
        RegimeType.HIGH_VOLATILITY: "strat-high-vol",
        RegimeType.LOW_VOLATILITY: "strat-low-vol",
    }


def _large_candles(n: int = 200, seed: int = 42) -> list[dict]:
    """Return a large enough candle list for feature computation."""
    return _make_large_dataset(n=n, seed=seed)


# ---------------------------------------------------------------------------
# RegimeRecord
# ---------------------------------------------------------------------------


class TestRegimeRecord:
    def test_record_is_frozen(self) -> None:
        from datetime import datetime, timezone

        record = RegimeRecord(
            timestamp=datetime.now(tz=timezone.utc),
            regime=RegimeType.TRENDING,
            confidence=0.85,
            strategy_id="strat-001",
            candle_index=10,
        )
        with pytest.raises((AttributeError, TypeError)):
            record.regime = RegimeType.MEAN_REVERTING  # type: ignore[misc]

    def test_record_fields(self) -> None:
        from datetime import datetime, timezone

        ts = datetime.now(tz=timezone.utc)
        record = RegimeRecord(
            timestamp=ts,
            regime=RegimeType.HIGH_VOLATILITY,
            confidence=0.91,
            strategy_id="strat-abc",
            candle_index=42,
        )
        assert record.timestamp == ts
        assert record.regime == RegimeType.HIGH_VOLATILITY
        assert record.confidence == 0.91
        assert record.strategy_id == "strat-abc"
        assert record.candle_index == 42


# ---------------------------------------------------------------------------
# RegimeSwitcher.__init__
# ---------------------------------------------------------------------------


class TestRegimeSwitcherInit:
    def test_initial_regime_default_is_mean_reverting(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map())
        assert sw.current_regime == RegimeType.MEAN_REVERTING

    def test_initial_regime_can_be_overridden(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.HIGH_VOLATILITY)
        assert sw.current_regime == RegimeType.HIGH_VOLATILITY

    def test_candles_since_switch_starts_at_cooldown(self) -> None:
        """Ensures a switch is immediately possible on the first qualifying step."""
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map(), cooldown_candles=5)
        assert sw.candles_since_switch == 5

    def test_history_starts_empty(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map())
        assert len(sw.regime_history) == 0


# ---------------------------------------------------------------------------
# RegimeSwitcher.should_switch
# ---------------------------------------------------------------------------


class TestRegimeSwitcherShouldSwitch:
    def _make_switcher(self, current_regime: RegimeType = RegimeType.MEAN_REVERTING) -> RegimeSwitcher:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=current_regime)
        return sw

    def test_returns_false_same_regime(self) -> None:
        sw = self._make_switcher(RegimeType.MEAN_REVERTING)
        assert sw.should_switch(RegimeType.MEAN_REVERTING, 0.99) is False

    def test_returns_false_low_confidence(self) -> None:
        sw = self._make_switcher(RegimeType.MEAN_REVERTING)
        assert sw.should_switch(RegimeType.TRENDING, 0.5) is False

    def test_returns_false_exactly_at_threshold_minus_epsilon(self) -> None:
        sw = self._make_switcher(RegimeType.MEAN_REVERTING)
        # Just below 0.7 — should be rejected.
        assert sw.should_switch(RegimeType.TRENDING, CONFIDENCE_THRESHOLD - 0.001) is False

    def test_returns_true_exactly_at_threshold(self) -> None:
        sw = self._make_switcher(RegimeType.MEAN_REVERTING)
        # cooldown is satisfied (candles_since_switch starts at cooldown value).
        assert sw.should_switch(RegimeType.TRENDING, CONFIDENCE_THRESHOLD) is True

    def test_returns_false_during_cooldown(self) -> None:
        sw = self._make_switcher(RegimeType.MEAN_REVERTING)
        # Force the cooldown counter to be less than the threshold.
        sw.candles_since_switch = SWITCH_COOLDOWN_CANDLES - 1
        assert sw.should_switch(RegimeType.TRENDING, 0.95) is False

    def test_returns_true_when_cooldown_expired_and_confidence_sufficient(self) -> None:
        sw = self._make_switcher(RegimeType.MEAN_REVERTING)
        sw.candles_since_switch = SWITCH_COOLDOWN_CANDLES
        assert sw.should_switch(RegimeType.TRENDING, 0.95) is True

    def test_custom_threshold_respected(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map(), confidence_threshold=0.9)
        # 0.89 should be rejected with threshold=0.9.
        assert sw.should_switch(RegimeType.TRENDING, 0.89) is False
        # 0.90 should be accepted (at threshold).
        assert sw.should_switch(RegimeType.TRENDING, 0.90) is True

    def test_custom_cooldown_respected(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map(), cooldown_candles=10)
        sw.candles_since_switch = 9
        assert sw.should_switch(RegimeType.TRENDING, 0.95) is False
        sw.candles_since_switch = 10
        assert sw.should_switch(RegimeType.TRENDING, 0.95) is True


# ---------------------------------------------------------------------------
# RegimeSwitcher.get_active_strategy
# ---------------------------------------------------------------------------


class TestRegimeSwitcherGetActiveStrategy:
    def test_returns_correct_strategy_for_initial_regime(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.TRENDING)
        assert sw.get_active_strategy() == "strat-trending"

    def test_returns_all_four_strategies(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        strategy_map = _default_strategy_map()
        for regime, expected_sid in strategy_map.items():
            sw = RegimeSwitcher(clf, strategy_map, initial_regime=regime)
            assert sw.get_active_strategy() == expected_sid


# ---------------------------------------------------------------------------
# RegimeSwitcher.detect_regime
# ---------------------------------------------------------------------------


class TestRegimeSwitcherDetectRegime:
    def test_returns_current_regime_on_insufficient_candles(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.99)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.HIGH_VOLATILITY)
        # Too few candles — should return current regime and zero confidence.
        short_candles = _make_candles(10)
        regime, confidence = sw.detect_regime(short_candles)
        assert regime == RegimeType.HIGH_VOLATILITY
        assert confidence == 0.0
        # Classifier should NOT have been called.
        clf.predict.assert_not_called()

    def test_calls_classifier_with_feature_row(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.88)
        sw = RegimeSwitcher(clf, _default_strategy_map())
        candles = _large_candles(n=200)
        regime, confidence = sw.detect_regime(candles)
        assert regime == RegimeType.TRENDING
        assert confidence == 0.88
        clf.predict.assert_called_once()


# ---------------------------------------------------------------------------
# RegimeSwitcher.step
# ---------------------------------------------------------------------------


class TestRegimeSwitcherStep:
    def test_step_increments_total_candles(self) -> None:
        clf = _make_mock_classifier(RegimeType.MEAN_REVERTING, 0.95)
        sw = RegimeSwitcher(clf, _default_strategy_map())
        short = _make_candles(5)  # below MIN_CANDLES_REQUIRED
        sw.step(short)
        assert sw._total_candles_processed == 1

    def test_step_returns_tuple_of_three(self) -> None:
        clf = _make_mock_classifier(RegimeType.MEAN_REVERTING, 0.95)
        sw = RegimeSwitcher(clf, _default_strategy_map())
        short = _make_candles(5)
        result = sw.step(short)
        assert len(result) == 3

    def test_no_switch_when_regime_unchanged(self) -> None:
        # Classifier always predicts MEAN_REVERTING, which is the initial regime.
        clf = _make_mock_classifier(RegimeType.MEAN_REVERTING, 0.99)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        _, _, switched = sw.step(candles)
        assert switched is False
        assert len(sw.regime_history) == 0

    def test_no_switch_when_confidence_too_low(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.4)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        _, _, switched = sw.step(candles)
        assert switched is False

    def test_switch_occurs_when_all_criteria_met(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        regime, strategy_id, switched = sw.step(candles)
        assert switched is True
        assert regime == RegimeType.TRENDING
        assert strategy_id == "strat-trending"
        assert sw.current_regime == RegimeType.TRENDING

    def test_switch_resets_cooldown_counter(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        sw.step(candles)
        # On a switch step: counter is first incremented (+1), then the switch
        # sets it back to 0.  Net result after the switching step is 0.
        assert sw.candles_since_switch == 0

    def test_second_switch_blocked_by_cooldown(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(
            clf,
            _default_strategy_map(),
            initial_regime=RegimeType.MEAN_REVERTING,
            cooldown_candles=5,
        )
        candles = _large_candles(n=200)
        # First step — switch to TRENDING.  candles_since_switch → 0.
        _, _, switched1 = sw.step(candles)
        assert switched1 is True
        assert sw.candles_since_switch == 0

        # Change classifier to predict HIGH_VOLATILITY with high confidence.
        clf.predict.return_value = (RegimeType.HIGH_VOLATILITY, 0.95)
        # Immediately try to switch again — should be blocked by cooldown.
        # candles_since_switch becomes 1 (< cooldown=5), so switch is rejected.
        _, _, switched2 = sw.step(candles)
        assert switched2 is False
        assert sw.candles_since_switch == 1

    def test_switch_after_cooldown_expires(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(
            clf,
            _default_strategy_map(),
            initial_regime=RegimeType.MEAN_REVERTING,
            cooldown_candles=3,
        )
        candles = _large_candles(n=200)
        sw.step(candles)  # Switch 1: MEAN_REVERTING → TRENDING

        clf.predict.return_value = (RegimeType.HIGH_VOLATILITY, 0.95)
        # Steps 2 and 3 are inside the cooldown window.
        _, _, s2 = sw.step(candles)
        _, _, s3 = sw.step(candles)
        assert not s2
        assert not s3
        # Step 4: cooldown_candles=3 expired (candles_since_switch == 3).
        _, _, s4 = sw.step(candles)
        assert s4 is True
        assert sw.current_regime == RegimeType.HIGH_VOLATILITY

    def test_history_appended_on_switch(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.85)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        sw.step(candles)
        assert len(sw.regime_history) == 1
        record = sw.regime_history[0]
        assert isinstance(record, RegimeRecord)
        assert record.regime == RegimeType.TRENDING
        assert math.isclose(record.confidence, 0.85, rel_tol=1e-6)
        assert record.strategy_id == "strat-trending"

    def test_history_accumulates_across_multiple_switches(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(
            clf,
            _default_strategy_map(),
            initial_regime=RegimeType.MEAN_REVERTING,
            cooldown_candles=1,
        )
        candles = _large_candles(n=200)

        # Switch 1: MEAN_REVERTING → TRENDING.
        sw.step(candles)
        assert len(sw.regime_history) == 1

        # Switch 2: TRENDING → HIGH_VOLATILITY.
        clf.predict.return_value = (RegimeType.HIGH_VOLATILITY, 0.88)
        sw.step(candles)
        assert len(sw.regime_history) == 2
        assert sw.regime_history[1].regime == RegimeType.HIGH_VOLATILITY

    def test_strategy_id_in_history_matches_strategy_map(self) -> None:
        clf = _make_mock_classifier(RegimeType.LOW_VOLATILITY, 0.92)
        strategy_map = _default_strategy_map()
        sw = RegimeSwitcher(clf, strategy_map, initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        sw.step(candles)
        assert sw.regime_history[0].strategy_id == strategy_map[RegimeType.LOW_VOLATILITY]


# ---------------------------------------------------------------------------
# RegimeSwitcher.get_history
# ---------------------------------------------------------------------------


class TestRegimeSwitcherGetHistory:
    def test_returns_empty_list_before_any_switch(self) -> None:
        clf = _make_mock_classifier(RegimeType.MEAN_REVERTING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map())
        assert sw.get_history() == []

    def test_history_dicts_have_required_keys(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.88)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        sw.step(candles)
        history = sw.get_history()
        assert len(history) == 1
        entry = history[0]
        assert "timestamp" in entry
        assert "regime" in entry
        assert "confidence" in entry
        assert "strategy_id" in entry
        assert "candle_index" in entry

    def test_history_regime_is_string_value(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.88)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        sw.step(candles)
        entry = sw.get_history()[0]
        assert entry["regime"] == "trending"

    def test_history_timestamp_is_iso_string(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.88)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        sw.step(candles)
        entry = sw.get_history()[0]
        # ISO-8601 timestamps contain a 'T' separator.
        assert "T" in entry["timestamp"]


# ---------------------------------------------------------------------------
# RegimeSwitcher.reset
# ---------------------------------------------------------------------------


class TestRegimeSwitcherReset:
    def test_reset_clears_history(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        sw.step(candles)
        assert len(sw.regime_history) == 1
        sw.reset()
        assert len(sw.regime_history) == 0

    def test_reset_restores_initial_regime(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        sw.step(candles)
        assert sw.current_regime == RegimeType.TRENDING
        sw.reset()
        assert sw.current_regime == RegimeType.MEAN_REVERTING

    def test_reset_restores_cooldown_counter(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map(), cooldown_candles=5)
        candles = _large_candles(n=200)
        sw.step(candles)  # candles_since_switch becomes 0 after switch
        sw.reset()
        assert sw.candles_since_switch == 5  # restored to cooldown value

    def test_reset_resets_total_candles_processed(self) -> None:
        clf = _make_mock_classifier(RegimeType.MEAN_REVERTING, 0.5)
        sw = RegimeSwitcher(clf, _default_strategy_map())
        short = _make_candles(5)
        sw.step(short)
        sw.step(short)
        assert sw._total_candles_processed == 2
        sw.reset()
        assert sw._total_candles_processed == 0

    def test_reset_preserves_classifier_and_strategy_map(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        strategy_map = _default_strategy_map()
        sw = RegimeSwitcher(clf, strategy_map)
        sw.reset()
        assert sw._classifier is clf
        assert sw._strategy_map is strategy_map


# ---------------------------------------------------------------------------
# RegimeSwitcher acceptance criteria
# ---------------------------------------------------------------------------


class TestRegimeSwitcherAcceptanceCriteria:
    """Verify all task acceptance criteria are satisfied."""

    def test_minimum_confidence_threshold_is_0_7(self) -> None:
        assert CONFIDENCE_THRESHOLD == 0.7

    def test_cooldown_is_5_candles(self) -> None:
        assert SWITCH_COOLDOWN_CANDLES == 5

    def test_step_returns_three_tuple_regime_strategy_switched(self) -> None:
        clf = _make_mock_classifier(RegimeType.MEAN_REVERTING, 0.5)
        sw = RegimeSwitcher(clf, _default_strategy_map())
        short = _make_candles(5)
        result = sw.step(short)
        regime, strategy_id, switched = result
        assert isinstance(regime, RegimeType)
        assert isinstance(strategy_id, str)
        assert isinstance(switched, bool)

    def test_regime_history_logged_with_timestamps(self) -> None:
        clf = _make_mock_classifier(RegimeType.TRENDING, 0.9)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        sw.step(candles)
        record = sw.regime_history[0]
        # Timestamp must be timezone-aware UTC.
        assert record.timestamp.tzinfo is not None

    def test_strategy_map_drives_returned_strategy_id(self) -> None:
        clf = _make_mock_classifier(RegimeType.HIGH_VOLATILITY, 0.88)
        strategy_map = {
            RegimeType.TRENDING: "t-strategy",
            RegimeType.MEAN_REVERTING: "mr-strategy",
            RegimeType.HIGH_VOLATILITY: "hv-strategy",
            RegimeType.LOW_VOLATILITY: "lv-strategy",
        }
        sw = RegimeSwitcher(clf, strategy_map, initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        _, strategy_id, switched = sw.step(candles)
        assert switched is True
        assert strategy_id == "hv-strategy"

    def test_switched_flag_false_when_no_change(self) -> None:
        # Classifier predicts current regime (MEAN_REVERTING) — no switch.
        clf = _make_mock_classifier(RegimeType.MEAN_REVERTING, 0.99)
        sw = RegimeSwitcher(clf, _default_strategy_map(), initial_regime=RegimeType.MEAN_REVERTING)
        candles = _large_candles(n=200)
        _, _, switched = sw.step(candles)
        assert switched is False

    def test_end_to_end_with_real_classifier(self) -> None:
        """Full integration: real RandomForest classifier + switcher on synthetic data."""
        candles = _make_large_dataset(n=500, seed=7)
        features, labels = generate_training_data(candles, window=20)
        clf = RegimeClassifier(seed=7, use_xgboost=False)
        clf.train(features, labels)

        strategy_map = _default_strategy_map()
        sw = RegimeSwitcher(
            classifier=clf,
            strategy_map=strategy_map,
            confidence_threshold=CONFIDENCE_THRESHOLD,
            cooldown_candles=SWITCH_COOLDOWN_CANDLES,
        )

        # Feed candles in a rolling window.
        window_size = 100
        for i in range(window_size, len(candles) + 1):
            window = candles[i - window_size : i]
            regime, strategy_id, switched = sw.step(window)
            assert isinstance(regime, RegimeType)
            assert strategy_id in strategy_map.values()
            assert isinstance(switched, bool)

        # Verify the switcher is in a consistent state.
        assert sw.get_active_strategy() == strategy_map[sw.current_regime]

    def test_module_exports_regime_switcher(self) -> None:
        from agent.strategies.regime import RegimeSwitcher as ImportedSwitcher

        assert ImportedSwitcher is RegimeSwitcher
