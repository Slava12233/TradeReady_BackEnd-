---
task_id: 08
title: "Enhance regime classifier with 2 new features"
type: task
agent: "ml-engineer"
phase: 1
depends_on: [2]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/regime/labeler.py", "agent/strategies/regime/classifier.py"]
tags:
  - task
  - ml
  - regime
---

# Task 08: Enhance regime classifier features

## Assigned Agent: `ml-engineer`

## Objective
Add Bollinger Band width and volume ratio as features 6 and 7 to the regime classifier, improving regime transition detection.

## Current State
5-feature vector: ADX, ATR/close ratio, Bollinger width (already exists in labeler but only used for BB width), RSI-14, MACD histogram.

## Changes
1. In `labeler.py:generate_training_data()`: add `volume_ratio` feature (current volume / 20-period SMA of volume)
2. In `classifier.py`: update `FEATURE_NAMES` to include new features
3. Update feature extraction in `RegimeSwitcher` to provide 7 features
4. Retrain and verify accuracy doesn't drop (should improve)

## Acceptance Criteria
- [ ] Classifier uses 7 features instead of 5
- [ ] `volume_ratio` computed as current_volume / sma(volume, 20)
- [ ] Tests updated for new feature count
- [ ] Accuracy on test split ≥ 70%

## Estimated Complexity
Low — adding features to existing pipeline.
