"""Market regime classifier.

Trains and serves a multi-class classifier (XGBoost preferred, sklearn
RandomForest as fallback) that predicts the current market regime from a
6-feature indicator vector.

Usage (as a module):

    python -m agent.strategies.regime.classifier \\
        --train \\
        --data-url http://localhost:8000 \\
        --seed 42

This fetches 12 months of 1-hour BTC candles, labels them with the
auto-labeler, trains an 80/20 temporal split, saves the model, and prints
accuracy + confusion matrix.

Usage (programmatic):

    from agent.strategies.regime.classifier import RegimeClassifier
    from agent.strategies.regime.labeler import generate_training_data

    clf = RegimeClassifier(seed=42)
    clf.train(features, labels)
    prediction, confidence = clf.predict(single_row_df)
    metrics = clf.evaluate(test_features, test_labels)
    clf.save(Path("agent/strategies/regime/models/agent.strategy.regime.classifier.joblib"))

    loaded = RegimeClassifier.load(Path("agent/strategies/regime/models/agent.strategy.regime.classifier.joblib"))
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import structlog

from agent.strategies.regime.labeler import RegimeType, generate_training_data

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants — every magic number here has a corresponding docstring.
# ---------------------------------------------------------------------------

# Default model save path, relative to the repo root.
DEFAULT_MODEL_PATH = Path("agent/strategies/regime/models/agent.strategy.regime.classifier.joblib")

# XGBoost hyperparameters.
# n_estimators=300: enough trees to generalise on ~5k samples without
#   over-fitting; training completes in ~5 s on a modern CPU.
# max_depth=6: standard XGBoost default; deeper trees over-fit on regime data
#   because regime boundaries are relatively smooth.
# learning_rate=0.05: conservative rate that works well with 300 estimators;
#   lowers variance at the cost of a few extra trees.
# subsample=0.8 / colsample_bytree=0.8: standard bagging fractions that
#   reduce variance without hurting accuracy on a 5-feature dataset.
XGB_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 6,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "objective": "multi:softprob",
    "eval_metric": "mlogloss",
    "use_label_encoder": False,
    "verbosity": 0,
}

# RandomForest fallback hyperparameters.
# n_estimators=300: same count as XGBoost for fair comparison.
# max_depth=10: deeper than XGBoost default because RF uses bagging; 10
#   balances expressiveness and generalisation.
RF_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 10,
    "min_samples_leaf": 5,
}

# Fraction of data reserved for testing.  Temporal split: first 80% trains,
# last 20% tests — no data leakage.
TRAIN_SPLIT = 0.8

# API endpoint for fetching historical candles.
CANDLES_ENDPOINT = "/api/v1/market/candles/{symbol}"

# Default symbol and period for the CLI training run.
DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_TIMEFRAME = "1h"
# 12 months × ~720 candles/month ≈ 8760 rows of 1h data.
DEFAULT_CANDLE_LIMIT = 8760


class RegimeClassifier:
    """Multi-class market regime classifier.

    Wraps either ``xgboost.XGBClassifier`` or
    ``sklearn.ensemble.RandomForestClassifier`` with a common interface for
    training, prediction, evaluation, and serialisation.

    Args:
        seed: Random seed for reproducibility.  Passed to both the classifier
              constructor and numpy.  Default 42.
        use_xgboost: Force XGBoost (True) or RandomForest (False).  When
                     None (default), tries XGBoost and falls back automatically
                     if the package is unavailable.
    """

    def __init__(self, seed: int = 42, use_xgboost: bool | None = None) -> None:
        self.seed = seed
        np.random.seed(seed)
        self._model: Any = None
        self._label_encoder: dict[str, int] = {}
        self._label_decoder: dict[int, str] = {}
        self._use_xgboost = self._resolve_backend(use_xgboost)
        # 6-feature input vector. Order is significant — must match the column
        # order produced by generate_training_data() in labeler.py.
        # Feature 1: adx         — trend strength (ADX indicator)
        # Feature 2: atr_ratio   — normalised volatility (ATR / close)
        # Feature 3: bb_width    — Bollinger Band width relative to middle band
        # Feature 4: rsi         — momentum oscillator (RSI-14)
        # Feature 5: macd_hist   — MACD histogram (momentum divergence)
        # Feature 6: volume_ratio — current volume / 20-period SMA of volume;
        #   captures volume-driven regime transitions (breakouts, accumulation)
        #   that price-only indicators cannot detect
        self._feature_names: list[str] = [
            "adx",
            "atr_ratio",
            "bb_width",
            "rsi",
            "macd_hist",
            "volume_ratio",
        ]

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, features: pd.DataFrame, labels: pd.Series) -> None:
        """Fit the classifier on labelled training data.

        Args:
            features: DataFrame with columns ``adx``, ``atr_ratio``,
                      ``bb_width``, ``rsi``, ``macd_hist``, ``volume_ratio``.
                      Must not contain NaN values.
            labels: Series of RegimeType string values (e.g. ``"trending"``).
                    Must have the same index as ``features``.

        Raises:
            ValueError: If features contain NaN, shapes mismatch, or fewer
                        than 2 distinct classes are present.
        """
        if features.isnull().any().any():
            raise ValueError("features must not contain NaN values before training")
        if len(features) != len(labels):
            raise ValueError(
                f"features and labels must have the same length "
                f"(got {len(features)} and {len(labels)})"
            )
        unique_classes = sorted(labels.unique())
        if len(unique_classes) < 2:
            raise ValueError(
                f"At least 2 distinct classes required for training, got: {unique_classes}"
            )

        # Build label encoder: string → int index.
        self._label_encoder = {cls: idx for idx, cls in enumerate(unique_classes)}
        self._label_decoder = {idx: cls for cls, idx in self._label_encoder.items()}

        y_int = labels.map(self._label_encoder).to_numpy(dtype=np.int64)
        X = features[self._feature_names].to_numpy(dtype=np.float32)

        logger.info(
            "agent.strategy.regime.classifier.training_start",
            n_samples=len(X),
            n_classes=len(unique_classes),
            classes=unique_classes,
            backend="xgboost" if self._use_xgboost else "random_forest",
            seed=self.seed,
        )

        if self._use_xgboost:
            from xgboost import XGBClassifier  # noqa: PLC0415

            self._model = XGBClassifier(
                **XGB_PARAMS,
                random_state=self.seed,
                num_class=len(unique_classes),
            )
        else:
            from sklearn.ensemble import RandomForestClassifier  # noqa: PLC0415

            self._model = RandomForestClassifier(
                **RF_PARAMS,
                random_state=self.seed,
                n_jobs=-1,
            )

        self._model.fit(X, y_int)
        logger.info("agent.strategy.regime.classifier.training_complete", n_samples=len(X))

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, features: pd.DataFrame) -> tuple[RegimeType, float]:
        """Predict the regime for a single observation.

        Args:
            features: DataFrame with one row and the same 6 feature columns
                      used during training.  Can contain extra columns which
                      are silently ignored.

        Returns:
            A tuple of (predicted_regime, confidence) where confidence is the
            probability of the predicted class (0.0–1.0).

        Raises:
            RuntimeError: If the model has not been trained or loaded yet.
            ValueError: If required feature columns are missing.
        """
        self._assert_fitted()
        missing = set(self._feature_names) - set(features.columns)
        if missing:
            raise ValueError(f"Missing feature columns: {missing}")

        X = features[self._feature_names].to_numpy(dtype=np.float32)

        # predict_proba returns shape (n_samples, n_classes).
        proba = self._model.predict_proba(X)
        predicted_idx = int(np.argmax(proba[0]))
        confidence = float(proba[0][predicted_idx])
        regime_str = self._label_decoder[predicted_idx]
        return RegimeType(regime_str), confidence

    def predict_batch(self, features: pd.DataFrame) -> list[tuple[RegimeType, float]]:
        """Predict regimes for multiple observations.

        Args:
            features: DataFrame with N rows.

        Returns:
            List of (regime, confidence) tuples, one per row.
        """
        self._assert_fitted()
        missing = set(self._feature_names) - set(features.columns)
        if missing:
            raise ValueError(f"Missing feature columns: {missing}")

        X = features[self._feature_names].to_numpy(dtype=np.float32)
        proba = self._model.predict_proba(X)
        results = []
        for row_proba in proba:
            idx = int(np.argmax(row_proba))
            results.append((RegimeType(self._label_decoder[idx]), float(row_proba[idx])))
        return results

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self, features: pd.DataFrame, labels: pd.Series) -> dict[str, Any]:
        """Evaluate the classifier on a held-out test set.

        Args:
            features: Feature DataFrame (same schema as ``train``).
            labels: Ground-truth RegimeType string Series.

        Returns:
            Dict containing:
            - ``accuracy`` (float): overall accuracy
            - ``confusion_matrix`` (list[list[int]]): per-class confusion matrix
            - ``classes`` (list[str]): row/column labels for the confusion matrix
            - ``per_class_f1`` (dict[str, float]): F1 score per regime class
            - ``n_samples`` (int): number of test samples

        Raises:
            RuntimeError: If model is not yet fitted.
        """
        from sklearn.metrics import (  # noqa: PLC0415
            confusion_matrix,
            f1_score,
        )

        self._assert_fitted()

        X = features[self._feature_names].to_numpy(dtype=np.float32)
        y_true_str = labels.to_numpy(dtype=str)

        proba = self._model.predict_proba(X)
        y_pred_idx = np.argmax(proba, axis=1).astype(int)
        y_pred_str = np.array([self._label_decoder[i] for i in y_pred_idx])

        # Filter to classes that appear in both true and predicted.
        all_classes = sorted(set(y_true_str) | set(y_pred_str))
        accuracy = float(np.mean(y_pred_str == y_true_str))

        cm = confusion_matrix(y_true_str, y_pred_str, labels=all_classes).tolist()

        # Per-class F1 (zero_division=0 silences warnings for absent classes).
        f1_values = f1_score(y_true_str, y_pred_str, labels=all_classes, average=None, zero_division=0)
        per_class_f1 = {cls: float(f1) for cls, f1 in zip(all_classes, f1_values)}

        metrics = {
            "accuracy": accuracy,
            "confusion_matrix": cm,
            "classes": all_classes,
            "per_class_f1": per_class_f1,
            "n_samples": len(X),
        }

        logger.info(
            "agent.strategy.regime.classifier.evaluation",
            accuracy=round(accuracy, 4),
            per_class_f1={k: round(v, 4) for k, v in per_class_f1.items()},
            n_samples=len(X),
        )
        return metrics

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: Path) -> None:
        """Serialise the model and metadata to a joblib file.

        Args:
            path: Destination file path.  Parent directories are created
                  automatically.

        Raises:
            RuntimeError: If the model has not been trained or loaded yet.
        """
        import joblib  # noqa: PLC0415

        self._assert_fitted()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "model": self._model,
            "label_encoder": self._label_encoder,
            "label_decoder": self._label_decoder,
            "feature_names": self._feature_names,
            "seed": self.seed,
            "backend": "xgboost" if self._use_xgboost else "random_forest",
        }
        joblib.dump(payload, path)
        logger.info("agent.strategy.regime.classifier.saved", path=str(path))

        # Save SHA-256 sidecar for integrity verification on subsequent loads.
        try:
            from agent.strategies.checksum import save_checksum  # noqa: PLC0415

            save_checksum(path)
        except Exception as exc_cs:  # noqa: BLE001
            logger.warning(
                "agent.strategy.regime.classifier.checksum_save_failed",
                path=str(path),
                error=str(exc_cs),
            )

    @classmethod
    def load(cls, path: Path) -> RegimeClassifier:
        """Deserialise a classifier from a joblib file.

        Args:
            path: Source file path.

        Returns:
            A fully initialised RegimeClassifier ready for prediction.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        import joblib  # noqa: PLC0415

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        # Verify SHA-256 integrity before deserializing the joblib payload.
        try:
            from agent.strategies.checksum import SecurityError, verify_checksum  # noqa: PLC0415

            verify_checksum(path)
        except SecurityError as exc_sec:
            logger.error(
                "agent.strategy.regime.classifier.checksum_mismatch",
                path=str(path),
                error=str(exc_sec),
            )
            raise
        except Exception as exc_cs:  # noqa: BLE001
            logger.warning(
                "agent.strategy.regime.classifier.checksum_check_failed",
                path=str(path),
                error=str(exc_cs),
            )

        payload = joblib.load(path)

        # Validate payload structure before accessing keys to guard against
        # a maliciously crafted .joblib that passes checksum but has wrong shape.
        if not isinstance(payload, dict):
            raise ValueError(
                f"Unexpected joblib payload type for {path}: "
                f"expected dict, got {type(payload).__name__}"
            )
        required_keys = {"model", "label_encoder", "label_decoder", "feature_names", "seed", "backend"}
        missing = required_keys - payload.keys()
        if missing:
            raise ValueError(
                f"joblib payload for {path} is missing required keys: {missing}"
            )

        instance = cls(seed=payload["seed"])
        instance._model = payload["model"]
        instance._label_encoder = payload["label_encoder"]
        instance._label_decoder = payload["label_decoder"]
        instance._feature_names = payload["feature_names"]
        instance._use_xgboost = payload["backend"] == "xgboost"

        logger.info(
            "agent.strategy.regime.classifier.loaded",
            path=str(path),
            backend=payload["backend"],
            n_classes=len(payload["label_encoder"]),
        )
        return instance

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assert_fitted(self) -> None:
        if self._model is None:
            raise RuntimeError(
                "RegimeClassifier has not been trained. Call train() or load() first."
            )

    @staticmethod
    def _resolve_backend(use_xgboost: bool | None) -> bool:
        """Return True if XGBoost should be used, False for RandomForest."""
        if use_xgboost is True:
            return True
        if use_xgboost is False:
            return False
        # Auto-detect.
        try:
            import xgboost  # noqa: F401, PLC0415

            return True
        except ImportError:
            logger.warning(
                "agent.strategy.regime.classifier.xgboost_unavailable",
                fallback="sklearn.RandomForestClassifier",
            )
            return False


# ---------------------------------------------------------------------------
# CLI — fetch candles, train, evaluate, save
# ---------------------------------------------------------------------------


async def _fetch_candles(base_url: str, api_key: str, symbol: str, limit: int, timeframe: str) -> list[dict]:  # type: ignore[type-arg]
    """Fetch historical candles from the platform REST API.

    Paginates automatically since the API caps at 1000 candles per request.

    Args:
        base_url: Platform base URL (e.g. ``http://localhost:8000``).
        api_key: ``ak_live_...`` API key.
        symbol: Trading pair (e.g. ``BTCUSDT``).
        limit: Total number of candles to fetch.
        timeframe: Candle interval (e.g. ``1h``).

    Returns:
        List of OHLCV dicts ordered oldest to newest.
    """
    import httpx  # noqa: PLC0415

    url = f"{base_url.rstrip('/')}/api/v1/market/candles/{symbol}"
    headers = {"X-API-Key": api_key}
    page_size = 1000
    all_candles: list[dict] = []  # type: ignore[type-arg]

    async with httpx.AsyncClient(timeout=30.0) as client:
        remaining = limit
        end_time = None
        while remaining > 0:
            fetch = min(remaining, page_size)
            params: dict[str, Any] = {"interval": timeframe, "limit": fetch}
            if end_time:
                params["end_time"] = end_time
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

            # Extract candle list from response
            candles: list[dict] = []  # type: ignore[type-arg]
            if isinstance(data, list):
                candles = data
            elif isinstance(data, dict):
                for key in ("candles", "data", "results"):
                    if key in data:
                        candles = data[key]
                        break

            if not candles:
                break

            all_candles = candles + all_candles  # prepend older candles
            remaining -= len(candles)

            # Move end_time window backwards for next page
            oldest_time = candles[0].get("time") or candles[0].get("timestamp")
            if oldest_time:
                end_time = oldest_time
            else:
                break

            # If we got fewer than requested, no more data
            if len(candles) < fetch:
                break

    return all_candles


def _log_evaluation(metrics: dict[str, Any], split_name: str = "test") -> None:
    """Log evaluation metrics via structlog."""
    logger.info(
        "classifier.evaluation",
        split=split_name,
        accuracy=round(metrics["accuracy"], 4),
        n_samples=metrics["n_samples"],
        per_class_f1={cls: round(f1, 4) for cls, f1 in sorted(metrics["per_class_f1"].items())},
    )


def _print_evaluation(metrics: dict[str, Any], split_name: str = "test") -> None:
    """Print evaluation metrics to stdout (human-readable tabular format).

    Used by the CLI training script and in tests to verify formatted output.
    Complements ``_log_evaluation`` which writes structured JSON to the log.

    Args:
        metrics: Dict returned by ``RegimeClassifier.evaluate()``.  Expected
                 keys: ``accuracy``, ``n_samples``, ``classes``,
                 ``per_class_f1``, ``confusion_matrix``.
        split_name: Label prefix for the printed header (e.g. ``"test"``).
    """
    accuracy = metrics["accuracy"]
    n_samples = metrics["n_samples"]
    classes = metrics["classes"]
    per_class_f1 = metrics["per_class_f1"]
    confusion_matrix = metrics["confusion_matrix"]

    print(f"\n=== {split_name.upper()} Evaluation ({n_samples} samples) ===")
    print(f"  Accuracy : {accuracy * 100:.2f}%")
    print("\n  Per-class F1:")
    for cls in sorted(per_class_f1):
        print(f"    {cls:<20s}: {per_class_f1[cls]:.4f}")
    print("\n  Confusion matrix (rows = true, cols = predicted):")
    header = "  " + " ".join(f"{c[:8]:>8}" for c in classes)
    print(header)
    for cls, row in zip(classes, confusion_matrix):
        row_str = " ".join(f"{v:>8d}" for v in row)
        print(f"  {cls[:8]:<8s} {row_str}")
    print()


async def _train_cli(args: argparse.Namespace, *, api_key: str = "") -> None:
    """CLI training entrypoint."""
    logger.info(
        "classifier.fetching_candles",
        limit=args.limit,
        timeframe=args.timeframe,
        symbol=args.symbol,
    )
    candles = await _fetch_candles(
        base_url=args.data_url,
        api_key=api_key,
        symbol=args.symbol,
        limit=args.limit,
        timeframe=args.timeframe,
    )
    logger.info("agent.strategy.regime.classifier.candles_fetched", count=len(candles))

    if len(candles) < 100:
        raise RuntimeError(
            f"Only {len(candles)} candles fetched. Need at least 100. "
            "Check --data-url and PLATFORM_API_KEY."
        )

    logger.info("agent.strategy.regime.classifier.generating_features")
    features, labels = generate_training_data(candles, window=args.window)
    label_dist = {str(lbl): int(count) for lbl, count in labels.value_counts().items()}
    logger.info(
        "classifier.dataset_ready",
        n_rows=len(features),
        label_distribution=label_dist,
    )

    # Temporal train/test split (no shuffling — preserves temporal order).
    split_idx = int(len(features) * TRAIN_SPLIT)
    X_train = features.iloc[:split_idx].reset_index(drop=True)
    y_train = labels.iloc[:split_idx].reset_index(drop=True)
    X_test = features.iloc[split_idx:].reset_index(drop=True)
    y_test = labels.iloc[split_idx:].reset_index(drop=True)
    logger.info("agent.strategy.regime.classifier.split_ready", train=len(X_train), test=len(X_test))

    clf = RegimeClassifier(seed=args.seed)
    backend = "xgboost" if clf._use_xgboost else "random_forest"
    logger.info("agent.strategy.regime.classifier.training_started", backend=backend)
    clf.train(X_train, y_train)

    metrics = clf.evaluate(X_test, y_test)
    _log_evaluation(metrics, split_name="test")

    accuracy = metrics["accuracy"]
    if accuracy < 0.70:
        logger.warning(
            "classifier.accuracy_below_threshold",
            accuracy=round(accuracy, 4),
            threshold=0.70,
            hint="Consider increasing data volume or tuning hyperparameters.",
        )

    model_path = Path(args.model_path)
    clf.save(model_path)
    logger.info("agent.strategy.regime.classifier.model_saved", path=str(model_path.resolve()))


def main() -> None:
    """CLI entry point for training the regime classifier."""
    parser = argparse.ArgumentParser(
        description="Train the market regime classifier.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--train",
        action="store_true",
        required=True,
        help="Fetch candles, train, evaluate, and save the classifier.",
    )
    parser.add_argument(
        "--data-url",
        default="http://localhost:8000",
        help="Platform REST API base URL.",
    )
    parser.add_argument(
        "--symbol",
        default=DEFAULT_SYMBOL,
        help="Trading pair symbol to fetch candles for.",
    )
    parser.add_argument(
        "--timeframe",
        default=DEFAULT_TIMEFRAME,
        help="Candle interval (1m, 5m, 15m, 1h, 4h, 1d).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_CANDLE_LIMIT,
        help="Number of candles to fetch (~12 months of 1h data = 8760).",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=20,
        help="Rolling lookback window for ADX and ATR indicators.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )
    parser.add_argument(
        "--model-path",
        default=str(DEFAULT_MODEL_PATH),
        help="Output path for the joblib model artefact.",
    )

    args = parser.parse_args()

    import os  # noqa: PLC0415

    api_key = os.environ.get("PLATFORM_API_KEY", "")

    asyncio.run(_train_cli(args, api_key=api_key))


if __name__ == "__main__":
    main()
