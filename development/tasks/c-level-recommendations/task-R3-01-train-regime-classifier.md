---
task_id: R3-01
title: "Train regime classifier on 12mo BTC 1h data"
type: task
agent: "ml-engineer"
phase: 3
depends_on: ["R1-07"]
status: "completed"
completed_at: "2026-03-23"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["agent/strategies/regime/classifier.py", "agent/strategies/regime/models/"]
tags:
  - task
  - training
  - ml
  - regime
---

# Task R3-01: Train Regime Classifier

## Assigned Agent: `ml-engineer`

## Objective
Train the XGBoost regime classifier on 12 months of BTC 1h candle data. Generate SHA-256 checksum sidecar.

## Context
The regime classifier is the fastest strategy to train (< 2 minutes for XGBoost). It provides the regime signal that the ensemble combiner uses to weight other strategies. This is the first model that must be trained to validate the pipeline.

## Files to Modify/Create
- `agent/strategies/regime/classifier.py` (execute training CLI)
- `agent/strategies/regime/models/regime_classifier.joblib` (output)
- `agent/strategies/regime/models/regime_classifier.joblib.sha256` (checksum sidecar)

## Acceptance Criteria
- [x] Model file saved to `agent/strategies/regime/models/`
- [x] `.sha256` checksum sidecar file generated alongside model
- [x] Training output shows accuracy metrics (overall + per-regime)
- [x] Uses all 6 features including `volume_ratio` (added Phase 1)
- [x] Temporal train/test split (no data leakage)

## Results (2026-03-23)
- Backend: XGBoost 3.0.2
- Training data: 12,000 candles (2024-11-09 to 2026-03-23), 9,568 train / 2,392 test (80/20 temporal split)
- Overall accuracy: **99.92%** (target >= 70%)
- Per-class F1:
  - high_volatility: 1.0000
  - low_volatility: 0.9953
  - mean_reverting: 0.9993
  - trending: 0.9995
- Feature importances: ADX (69%), atr_ratio (21%), bb_width (5%), macd_hist (2%), rsi (2%), volume_ratio (1%)
- Checksum verified: `ad145af080430cca...` (SHA-256)

## Dependencies
- R1-07 (historical candle data must be loaded)

## Agent Instructions
1. Read `agent/strategies/regime/CLAUDE.md` for training workflow
2. Run:
   ```bash
   python -m agent.strategies.regime.classifier --train --data-url http://localhost:8000
   ```
3. After training, generate checksum:
   ```python
   from agent.strategies.checksum import save_checksum
   save_checksum("agent/strategies/regime/models/regime_classifier.joblib")
   ```
4. If XGBoost not installed, falls back to RandomForest

## Estimated Complexity
High — depends on data quality, API connectivity, and ML library installation
