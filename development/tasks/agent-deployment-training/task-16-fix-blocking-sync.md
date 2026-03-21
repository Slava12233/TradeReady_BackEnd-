---
task_id: 16
title: "Fix blocking sync in async contexts"
type: task
agent: "backend-developer"
phase: 9
depends_on: []
status: "completed"
board: "[[agent-deployment-training/README]]"
priority: "high"
files: ["agent/strategies/rl/deploy.py", "agent/strategies/ensemble/run.py"]
tags:
  - task
  - deployment
  - training
---

# Task 16: Fix blocking sync in async contexts

## Assigned Agent: `backend-developer`

## Objective
Wrap blocking CPU-bound calls with `asyncio.to_thread()` or `loop.run_in_executor()` to prevent event loop freezing.

## Locations
1. `deploy.py:857` — `model.predict()` (PyTorch inference, 5-50ms)
2. `run.py:679` — `model.predict()` in ensemble step
3. `run.py:575` — `RandomForestClassifier.fit()` (1-3s) in `initialize()`

## Fix Pattern
```python
# Before
action, _ = self._model.predict(obs, deterministic=True)

# After
action, _ = await asyncio.to_thread(self._model.predict, obs, deterministic=True)
```

## Acceptance Criteria
- [ ] All 3 blocking calls wrapped with `asyncio.to_thread()`
- [ ] Event loop no longer freezes during inference
- [ ] Existing tests pass
- [ ] No performance regression (thread overhead < blocking time)

## Dependencies
None — can start immediately.

## Agent Instructions
Read the perf review at `development/code-reviews/perf-check-agent-strategies.md` for exact locations. Use `asyncio.to_thread()` (Python 3.12+) which is simpler than `loop.run_in_executor()`. For `model.predict()`, the overhead of thread scheduling (~0.1ms) is negligible compared to inference time (5-50ms).

## Estimated Complexity
Low — wrapping 3 calls.
