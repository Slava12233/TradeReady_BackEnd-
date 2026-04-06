---
task_id: 6
title: "Fix BT-05: fake agent_id returns INTERNAL_ERROR"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "high"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "src/backtesting/engine.py"
  - "src/api/routes/backtest.py"
tags:
  - task
  - backtesting
  - p1
---

# Task 06: Fix BT-05 — Fake agent_id Returns INTERNAL_ERROR

## Assigned Agent: `backend-developer`

## Objective
When a non-existent `agent_id` UUID is passed to `POST /backtest/create`, it triggers a PostgreSQL FK violation (`IntegrityError`) that surfaces as a generic 500 INTERNAL_ERROR. Should return a proper `AGENT_NOT_FOUND` error.

## Files to Modify

### `src/backtesting/engine.py` — `create_session()`:
Before inserting the session row, validate the agent exists:
```python
if config.agent_id:
    agent = await db.get(Agent, config.agent_id)
    if not agent:
        raise BacktestNoDataError(f"Agent {config.agent_id} not found")
```

Or wrap the `db.flush()` in a try/except for `IntegrityError` and raise a domain error.

### `src/api/routes/backtest.py` — `create_backtest()`:
Optionally validate agent ownership (agent belongs to the requesting account) before calling the engine.

## Acceptance Criteria
- [ ] `agent_id="00000000-0000-0000-0000-000000000000"` → 404 with `AGENT_NOT_FOUND` or similar
- [ ] Error message includes the invalid agent_id
- [ ] Valid agent_id still works
- [ ] Agent belonging to a different account is rejected (if agent scoping is enforced)

## Dependencies
None.

## Agent Instructions
Check `src/utils/exceptions.py` for existing error classes. Use an appropriate existing exception or the `BacktestNoDataError` with a descriptive message. Check `src/database/models/` for the `Agent` model import path.

## Estimated Complexity
Low — simple pre-validation check.
