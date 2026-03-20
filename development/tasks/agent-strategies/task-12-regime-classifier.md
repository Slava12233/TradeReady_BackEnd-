---
task_id: 12
title: "Regime classifier training"
agent: "ml-engineer"
phase: C
depends_on: []
status: "completed"
priority: "medium"
files: ["agent/strategies/regime/__init__.py", "agent/strategies/regime/classifier.py", "agent/strategies/regime/labeler.py"]
---

# Task 12: Regime classifier training

## Assigned Agent: `ml-engineer`

## Objective
Build the market regime detection system: auto-label historical periods into 4 regimes, train a gradient-boosted classifier, and provide a `predict_regime(candles)` function.

## Files to Create
- `agent/strategies/regime/__init__.py`
- `agent/strategies/regime/labeler.py`:
  - `RegimeType` enum: TRENDING, MEAN_REVERTING, HIGH_VOLATILITY, LOW_VOLATILITY
  - `label_candles(candles: list[dict], window: int = 20)` → list[RegimeType]:
    - Compute ADX over window: > 25 = trending
    - Compute ATR ratio (ATR / close): > 2x median = high_vol, < 0.5x median = low_vol
    - Remaining = mean_reverting
  - `generate_training_data(candles, window)` → features (DataFrame) + labels (Series)
  - Features per candle: ADX, ATR/close, Bollinger width, RSI, MACD histogram

- `agent/strategies/regime/classifier.py`:
  - `RegimeClassifier` class:
    - `train(features, labels)` → fit XGBoost classifier
    - `predict(features)` → RegimeType + confidence (probability)
    - `save(path)` / `load(path)` → model persistence (joblib)
    - `evaluate(features, labels)` → accuracy, confusion matrix, per-class F1
  - CLI: `python -m agent.strategies.regime.classifier --train --data-url http://localhost:8000`
    - Fetches 12 months of 1h candles for BTC
    - Labels with auto-labeler
    - Trains classifier (80/20 train/test split)
    - Saves model to `agent/strategies/regime/models/regime_classifier.joblib`
    - Prints accuracy and confusion matrix

## Acceptance Criteria
- [ ] Auto-labeler assigns regimes consistently (same input → same labels)
- [ ] Classifier achieves > 70% accuracy on test set
- [ ] Prediction includes confidence score (probability of predicted class)
- [ ] Model saves/loads correctly (joblib round-trip)
- [ ] Features use the platform's IndicatorEngine indicators (ADX, ATR, BB, RSI, MACD)
- [ ] Training completes in < 2 minutes (XGBoost is fast)
- [ ] No data leakage (train/test split is temporal, not random)

## Dependencies
None — can start immediately. Uses platform API for candle data only.

## Agent Instructions
Read `src/strategies/indicators.py` to understand the exact indicator implementations. Use the same computation for consistency (or call the platform API to get pre-computed indicators). XGBoost is the recommended classifier (`xgboost` package), but LightGBM or even sklearn RandomForest are acceptable alternatives.

## Estimated Complexity
Medium — ML pipeline with data preprocessing, training, and evaluation.
