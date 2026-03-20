---
task_id: 05
title: "Train regime classifier"
agent: "ml-engineer"
phase: 5
depends_on: [3]
status: "completed"
priority: "high"
files: ["agent/strategies/regime/models/regime_classifier.joblib"]
---

# Task 05: Train regime classifier

## Assigned Agent: `ml-engineer`

## Objective
Train the XGBoost/RF market regime classifier on 12 months of BTC 1h candles. This is fast (<2 min) and provides the regime signal needed by the ensemble.

## Steps
1. Train: `python -m agent.strategies.regime.classifier --train --data-url http://localhost:8000`
2. Verify accuracy > 70% from output
3. Test regime switching demo: `python -m agent.strategies.regime.switcher --demo`

## Acceptance Criteria
- [ ] Classifier achieves > 70% accuracy on test set
- [ ] Model saved to `agent/strategies/regime/models/regime_classifier.joblib`
- [ ] Confusion matrix shows all 4 regimes represented
- [ ] Switcher demo runs without errors, shows regime changes
- [ ] Training completes in < 2 minutes

## Dependencies
- Task 03: 12 months of BTC 1h candle data loaded

## Agent Instructions
Read `agent/strategies/regime/CLAUDE.md` for classifier details. XGBoost is preferred; if not installed, falls back to sklearn RandomForest. The classifier uses temporal train/test split (80/20) to prevent data leakage.

## Estimated Complexity
Low — running existing training script.
