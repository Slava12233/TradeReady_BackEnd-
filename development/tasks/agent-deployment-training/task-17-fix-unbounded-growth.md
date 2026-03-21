---
task_id: 17
title: "Fix unbounded growth & add caching"
type: task
agent: "backend-developer"
phase: 9
depends_on: []
status: "completed"
board: "[[agent-deployment-training/README]]"
priority: "medium"
files: ["agent/strategies/ensemble/run.py", "agent/strategies/regime/switcher.py", "agent/strategies/evolutionary/evolve.py", "agent/strategies/ensemble/meta_learner.py"]
tags:
  - task
  - deployment
  - training
---

# Task 17: Fix unbounded growth & add caching

## Assigned Agent: `backend-developer`

## Objective
Cap unbounded lists with `collections.deque(maxlen=...)` and add indicator caching.

## Fixes
1. `run.py` — `_step_history` grows unbounded → `deque(maxlen=500)`
2. `switcher.py` — `regime_history` unbounded → `deque(maxlen=500)`
3. `switcher.py:194` — `detect_regime()` recomputes all 5 indicators from scratch every call → cache by last candle timestamp
4. `evolve.py:231` — mutable function attribute `_strategy_id` → move to instance variable
5. `meta_learner.py:453` — `_REGIME_ACTION` dict recreated per call → module-level constant

## Acceptance Criteria
- [ ] `_step_history` and `regime_history` use `deque(maxlen=500)`
- [ ] Regime detection caches features by candle timestamp
- [ ] Mutable function attribute moved to instance
- [ ] Module-level constant for regime action mapping
- [ ] Existing tests pass

## Dependencies
None — can start immediately.

## Estimated Complexity
Low — straightforward fixes.
