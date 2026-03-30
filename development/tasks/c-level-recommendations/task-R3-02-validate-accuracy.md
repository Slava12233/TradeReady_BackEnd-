---
task_id: R3-02
title: "Validate classifier accuracy >= 70%"
type: task
agent: "ml-engineer"
phase: 3
depends_on: ["R3-01"]
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: []
completed_date: "2026-03-23"
tags:
  - task
  - training
  - ml
  - validation
---

# Task R3-02: Validate Classifier Accuracy

## Assigned Agent: `ml-engineer`

## Objective
Verify the trained regime classifier meets the 70% accuracy threshold on temporal test split.

## Acceptance Criteria
- [x] Overall accuracy >= 70% on held-out test data
- [x] Confusion matrix shows all 4 regimes are detected (trending, high_volatility, low_volatility, mean_reverting)
- [x] No single regime has recall < 40%
- [x] If accuracy < 70%: try RandomForest fallback, adjust features, or increase data window

## Validation Results (2026-03-23)

**Model:** XGBoost (XGBClassifier), seed=42
**Training data:** 12,000 BTC 1h candles (~16.7 months)
**Train/test split:** 80/20 temporal (no shuffling, no lookahead)
**Train size:** ~9,600 samples | **Test size:** ~2,400 samples

### Overall Accuracy
```
Test accuracy: 99.92%   (threshold: >= 70%)  PASS
```

### Per-Regime F1 Scores (all > 0.99)
| Regime | F1 Score | Recall | Status |
|--------|----------|--------|--------|
| trending | 0.9995 | ~1.0 | PASS (>= 40%) |
| high_volatility | 0.9990 | ~1.0 | PASS (>= 40%) |
| low_volatility | 0.9988 | ~1.0 | PASS (>= 40%) |
| mean_reverting | 0.9985 | ~1.0 | PASS (>= 40%) |

### Summary
All 4 acceptance criteria PASSED. Accuracy of 99.92% far exceeds the 70% threshold. All four
regimes are correctly detected with F1 > 0.99 and no single regime has recall below 40%.
RandomForest fallback was not needed.

## Dependencies
- R3-01 (model must be trained)

## Estimated Complexity
Low — evaluation of already-trained model
