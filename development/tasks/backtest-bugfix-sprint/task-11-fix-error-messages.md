---
task_id: 11
title: "Fix step error message + agent_id fallback docs"
type: task
agent: "backend-developer"
phase: 4
depends_on: []
status: "completed"
priority: "low"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "src/api/routes/backtest.py"
  - "src/api/schemas/backtest.py"
tags:
  - task
  - backtesting
  - p3
---

# Task 11: Fix BT-15 + BT-16 — Error Messages + agent_id Fallback

## Assigned Agent: `backend-developer`

## Objective
1. **BT-15:** Stepping a completed backtest says "is not active" — should say "already completed"
2. **BT-16:** Missing `agent_id` silently defaults to auth context agent — document or make explicit

## Files to Modify

### `src/api/routes/backtest.py` — `step_backtest()`:

**BT-15:** Catch `BacktestNotFoundError` and re-query DB for actual status:
```python
try:
    result = await engine.step(session_id, steps, db)
except BacktestNotFoundError:
    session = await repo.get_session(session_id)
    if session and session.status == "completed":
        raise BacktestInvalidStateError("Backtest has already completed", current_status="completed")
    elif session and session.status in ("failed", "cancelled"):
        raise BacktestInvalidStateError(f"Backtest was {session.status}", current_status=session.status)
    raise  # genuinely not found
```

### `src/api/schemas/backtest.py` — `BacktestCreateRequest`:

**BT-16:** Add `description` to the `agent_id` field documenting the fallback behavior:
```python
agent_id: str | None = Field(
    default=None,
    description="Agent ID. If omitted, uses the agent from the authenticated API key."
)
```

## Acceptance Criteria
- [ ] `POST /backtest/{completed_id}/step` → "Backtest has already completed" (not "is not active")
- [ ] `POST /backtest/{failed_id}/step` → "Backtest was failed"
- [ ] `POST /backtest/{cancelled_id}/step` → "Backtest was cancelled"
- [ ] `agent_id` field has clear documentation about fallback behavior

## Dependencies
None.

## Estimated Complexity
Low — error handling improvement + docs update.
