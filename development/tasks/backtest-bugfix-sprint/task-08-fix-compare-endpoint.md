---
task_id: 8
title: "Fix compare: missing sessions + minimum 2"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "medium"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "src/api/routes/backtest.py"
tags:
  - task
  - backtesting
  - p2
---

# Task 08: Fix BT-08 + BT-09 — Compare Endpoint Edge Cases

## Assigned Agent: `backend-developer`

## Objective
Fix two compare endpoint bugs:
1. **BT-08:** Non-existent session IDs are silently ignored (should error)
2. **BT-09:** Single session ID accepted (should require minimum 2)

## Files to Modify

### `src/api/routes/backtest.py` — `compare_backtests()`:

**After parsing session IDs (~line 770):**
```python
if len(session_ids) < 2:
    raise InputValidationError(
        field="sessions",
        details={"message": "At least 2 session IDs required for comparison"}
    )
```

**After fetching sessions (~line 771):**
```python
found_ids = {s.id for s in bt_sessions}
missing = [str(sid) for sid in session_ids if sid not in found_ids]
if missing:
    raise BacktestNotFoundError(f"Sessions not found: {', '.join(missing)}")
```

## Acceptance Criteria
- [ ] Single session ID → 422 with "at least 2 required"
- [ ] Mix of valid + invalid IDs → error listing missing IDs
- [ ] All valid IDs → works as before
- [ ] Empty sessions param → 422

## Dependencies
None.

## Agent Instructions
Check `src/utils/exceptions.py` for `InputValidationError` and `BacktestNotFoundError`. Use the existing exception classes. The compare endpoint currently returns 200 for these edge cases, so this changes the API contract — make sure it's a clean 4xx error.

## Estimated Complexity
Low — two guard clauses.
