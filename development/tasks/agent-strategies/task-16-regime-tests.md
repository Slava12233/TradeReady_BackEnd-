---
task_id: 16
title: "Regime system tests"
type: task
agent: "test-runner"
phase: C
depends_on: [12, 14]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "medium"
files: ["agent/tests/test_regime_labeler.py", "agent/tests/test_regime_switcher.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 16: Regime system tests

## Assigned Agent: `test-runner`

## Objective
Write tests for the regime labeler, classifier, and switcher.

## Files to Create
- `agent/tests/test_regime_labeler.py`:
  - ADX > 25 → TRENDING
  - ATR > 2x median → HIGH_VOLATILITY
  - Both low → MEAN_REVERTING
  - Consistent labeling (same input → same output)

- `agent/tests/test_regime_switcher.py`:
  - Cooldown prevents switching within 5 candles
  - Low confidence (< 0.7) prevents switching
  - High confidence (> 0.7) after cooldown triggers switch
  - Regime history tracks all changes
  - Active strategy matches current regime

## Acceptance Criteria
- [ ] All tests pass
- [ ] Labeler tests cover all 4 regime types
- [ ] Switcher tests cover cooldown, confidence threshold, and state transitions

## Dependencies
- Task 12: labeler code
- Task 14: switcher code

## Estimated Complexity
Low — focused unit tests.
