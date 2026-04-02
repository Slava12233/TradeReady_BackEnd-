---
task_id: 05
title: "Investigate & fix battle creation INTERNAL_ERROR (BUG-003)"
type: task
agent: "backend-developer"
phase: 2
depends_on: [1]
status: "pending"
priority: "high"
board: "[[qa-bugfix-sprint/README]]"
files: ["src/battles/service.py", "src/api/routes/battles.py"]
tags:
  - task
  - battles
  - P0
---

# Task 05: Investigate & fix battle creation INTERNAL_ERROR (BUG-003)

## Assigned Agent: `backend-developer`

## Objective
Debug and fix the battle creation endpoint which returns `INTERNAL_ERROR` for ALL battle creation attempts (live, historical, and preset-based). The entire battle system is broken.

## Context
This is a P0 bug — battles are a headline feature. `POST /api/v1/battles` returns HTTP 500 with generic `INTERNAL_ERROR` for every payload format. The presets endpoint works (`GET /battles/presets`), but no battles can actually be created. The root cause is likely an unhandled exception in `BattleService.create_battle()` — possibly a DB constraint, JSONB serialization issue, or missing prerequisite data.

## Files to Modify/Create
- `src/battles/service.py` — fix `create_battle()` (lines ~106-153), add proper error handling
- `src/api/routes/battles.py` — fix create endpoint handler (lines ~125-140)
- `src/api/schemas/battles.py` — verify request schema matches what clients send

## Acceptance Criteria
- [ ] `POST /battles` with live battle config returns `battle_id` (HTTP 201)
- [ ] `POST /battles` with historical battle config returns `battle_id`
- [ ] `POST /battles` with preset name returns `battle_id`
- [ ] Invalid battle requests return HTTP 400/422 with specific error, NOT HTTP 500
- [ ] Battle appears in `GET /battles` after creation
- [ ] Regression tests added for all three creation modes

## Dependencies
- Task 01 should be done first (agents need valid balances for battles)

## Agent Instructions
1. Read `src/battles/CLAUDE.md` first for architecture context
2. Read `src/battles/service.py` — focus on `create_battle()` method
3. Read `src/api/routes/battles.py` — the create endpoint handler
4. Read `src/api/schemas/battles.py` — the request/response schemas
5. **Investigation phase:** Add temporary logging to `create_battle()` to capture the actual exception:
   ```python
   import traceback
   try:
       # existing create logic
   except Exception as e:
       logger.error(f"Battle creation failed: {traceback.format_exc()}")
       raise
   ```
6. Common causes to check:
   - `model_dump(mode="json")` needed for datetime/UUID/Decimal in JSONB columns
   - Missing `battle_config` or `backtest_config` fields
   - Agent validation (do agents exist? do they have active sessions?)
   - DB constraint violations (check the Battle model's required fields)
7. Fix the root cause, then add proper `try/except` with specific error types
8. Ensure the global handler never shows `INTERNAL_ERROR` for known failure modes

## Estimated Complexity
High — requires investigation to find the actual exception before coding the fix. Multiple possible root causes.
