---
task_id: R5-03
title: "Wire DriftDetector into live TradingLoop with retrain trigger"
type: task
agent: "backend-developer"
phase: 4
depends_on: ["R5-01"]
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["agent/trading/loop.py", "agent/strategies/drift.py", "agent/strategies/retrain.py"]
tags:
  - task
  - retraining
  - drift-detection
  - trading
---

# Task R5-03: Wire DriftDetector into Live TradingLoop

## Assigned Agent: `backend-developer`

## Objective
Verify and complete the wiring between `DriftDetector` in `TradingLoop._observe()` and `RetrainOrchestrator.trigger_drift_retrain()`. Add cooldown to prevent retrain storms.

## Files to Modify/Create
- `agent/trading/loop.py` — verify drift callback triggers retrain
- `agent/strategies/drift.py` — verify `detect()` returns drift events
- `agent/strategies/retrain.py` — verify `trigger_drift_retrain()` accepts strategy name

## Acceptance Criteria
- [ ] When `DriftDetector.detect()` returns drift, retrain task is enqueued
- [ ] Cooldown: minimum 1 hour between drift-triggered retrains per strategy
- [ ] Cooldown tracked in Redis: `retrain:cooldown:{strategy_name}` with 3600s TTL
- [ ] Test: simulated drift event triggers retrain; second event within cooldown is ignored

## Dependencies
- R5-01 (Celery retrain tasks must exist)

## Estimated Complexity
Medium — integration wiring + cooldown logic
