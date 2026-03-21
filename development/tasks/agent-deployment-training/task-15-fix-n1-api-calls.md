---
task_id: 15
title: "Fix N+1 API call patterns (6 locations)"
type: task
agent: "backend-developer"
phase: 9
depends_on: []
status: "completed"
board: "[[agent-deployment-training/README]]"
priority: "high"
files: ["agent/strategies/evolutionary/battle_runner.py", "agent/strategies/rl/deploy.py", "agent/strategies/rl/data_prep.py", "agent/strategies/ensemble/run.py"]
tags:
  - task
  - deployment
  - training
---

# Task 15: Fix N+1 API call patterns (6 locations)

## Assigned Agent: `backend-developer`

## Objective
Replace sequential HTTP calls with `asyncio.gather` at 6 locations identified in the performance review.

## Locations (from `development/code-reviews/perf-check-agent-strategies.md`)
1. `battle_runner.py` — `setup_agents()`: 12 sequential agent creation calls
2. `battle_runner.py` — `reset_agents()`: 12 sequential reset calls per generation
3. `battle_runner.py` — `assign_strategies()`: 12 sequential strategy assignments
4. `battle_runner.py` — `_add_participants()`: 12 sequential participant registrations
5. `data_prep.py` — `validate_data()`: sequential per-asset validation
6. `deploy.py` / `run.py` — sequential per-symbol candle fetching

## Fix Pattern
Replace:
```python
for agent_id in self._agent_ids:
    await self._jwt_client.post(url, json=data)
```
With:
```python
tasks = [self._jwt_client.post(url, json=data) for agent_id in self._agent_ids]
results = await asyncio.gather(*tasks, return_exceptions=True)
```

## Acceptance Criteria
- [ ] All 6 locations use `asyncio.gather` instead of sequential loops
- [ ] Error handling preserved (individual failures don't crash the batch)
- [ ] Existing tests pass after changes
- [ ] Battle runner total setup time reduced from ~30s to ~3s

## Dependencies
None — can start immediately.

## Agent Instructions
Read `development/code-reviews/perf-check-agent-strategies.md` for exact line numbers. Keep error handling: `return_exceptions=True` and process results individually. Don't change the API contract — same inputs, same outputs.

## Estimated Complexity
Medium — 6 locations, each needs careful error handling.
