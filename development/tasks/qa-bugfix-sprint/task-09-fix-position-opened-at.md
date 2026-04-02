---
task_id: 09
title: "Fix position opened_at epoch zero (BUG-017)"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "pending"
priority: "low"
board: "[[qa-bugfix-sprint/README]]"
files: ["src/api/routes/account.py", "src/portfolio/tracker.py"]
tags:
  - task
  - accounts
  - positions
  - P3
---

# Task 09: Fix position `opened_at` epoch zero (BUG-017)

## Assigned Agent: `backend-developer`

## Objective
Fix all positions showing `"opened_at": "1970-01-01T00:00:00Z"` instead of the actual trade timestamp.

## Context
The `Position` ORM model has `opened_at` with `server_default=func.now()` — the DB value is correct. But `_position_view_to_item()` in `account.py:108-122` hardcodes `opened_at = datetime.fromtimestamp(0, tz=UTC)` because `PositionView` (a lightweight dataclass from `tracker.py`) doesn't include this field. There's a TODO comment acknowledging this gap.

## Files to Modify/Create
- `src/api/routes/account.py` — fix `_position_view_to_item()` (lines ~108-122)
- `src/portfolio/tracker.py` — optionally add `opened_at` to `PositionView`

## Acceptance Criteria
- [ ] `GET /account/positions` returns real `opened_at` timestamps (not epoch zero)
- [ ] `GET /account/portfolio` positions also have correct timestamps
- [ ] Timestamps match the first trade's `filled_at` for each position
- [ ] Regression test added

## Dependencies
None.

## Agent Instructions
1. Read `src/api/routes/account.py` — find `_position_view_to_item()` at lines ~108-122
2. **Simplest fix (Option B from plan):** In the route handler, after getting position views, query the `positions` table to get `opened_at`:
   ```python
   from sqlalchemy import select
   from src.database.models import Position
   
   result = await db.execute(select(Position).where(Position.agent_id == agent_id))
   opened_at_map = {p.symbol: p.opened_at for p in result.scalars()}
   ```
   Then pass `opened_at_map` to `_position_view_to_item()` and use `opened_at_map.get(symbol, datetime.now(UTC))`.
3. **Alternative (Option A):** Add `opened_at: datetime | None` to the `PositionView` dataclass in `tracker.py` and populate it when building views.
4. Remove the TODO comment and epoch-zero sentinel

## Estimated Complexity
Low — straightforward DB query addition.
