---
task_id: 4
title: "Add time fields to battle live route handler"
type: task
agent: "backend-developer"
phase: 2
depends_on: [3]
status: "pending"
priority: "high"
board: "[[fix-battle-live-crash/README]]"
files:
  - "src/api/routes/battles.py"
tags:
  - task
  - battles
  - backend
  - api
---

# Task 04: Add time fields to battle live route handler

## Assigned Agent: `backend-developer`

## Objective
Add `elapsed_minutes`, `remaining_minutes`, and `updated_at` to the `BattleLiveResponse` construction in the route handler.

## Context
The route handler at `src/api/routes/battles.py:413-418` currently constructs `BattleLiveResponse` with only `battle_id`, `status`, `timestamp`, and `participants`. The frontend expects `elapsed_minutes` and `remaining_minutes` to show a live countdown/timer. The battle model has `started_at` and `duration_minutes` fields.

## Files to Modify
- `src/api/routes/battles.py` — Update the `get_live_snapshot` endpoint (lines 400-418)

## Specific Changes

In the `get_live_snapshot` function (line 400+), compute time fields before constructing the response:

```python
from datetime import UTC, datetime

# After getting the battle object (line 406):
elapsed = None
remaining = None
if battle.started_at:
    now = datetime.now(UTC)
    elapsed_td = now - battle.started_at
    elapsed = elapsed_td.total_seconds() / 60.0
    if battle.duration_minutes:
        remaining = max(0.0, battle.duration_minutes - elapsed)

# Update the response construction:
return BattleLiveResponse(
    battle_id=battle_id,
    status=battle.status,
    elapsed_minutes=elapsed,
    remaining_minutes=remaining,
    participants=participants,
    updated_at=datetime.now(UTC),
)
```

## Acceptance Criteria
- [ ] `elapsed_minutes` is computed from `battle.started_at` to now (in minutes as float)
- [ ] `remaining_minutes` is computed as `duration_minutes - elapsed` (clamped to 0), or `None` if no duration limit
- [ ] `updated_at` replaces the old `timestamp` field
- [ ] Both fields are `None` if the battle hasn't started yet
- [ ] `ruff check src/api/routes/battles.py` passes
- [ ] `mypy src/api/routes/battles.py` passes

## Dependencies
Task 03 must complete first — the updated `BattleLiveResponse` schema must have the new fields.

## Agent Instructions
Read `src/api/routes/CLAUDE.md` first. Check if `datetime` and `UTC` are already imported. The `battle` object is fetched on line 406 via `battle_service.get_battle(battle_id)` — check the Battle model to confirm `started_at` and `duration_minutes` field names. Use `datetime.now(UTC)` (not `utcnow()` which is deprecated).

## Estimated Complexity
Low — simple datetime arithmetic
