---
task_id: 8
title: "Run tests & validate API sync"
type: task
agent: "test-runner"
phase: 4
depends_on: [1, 2, 3, 4, 5, 6, 7]
status: "pending"
priority: "medium"
board: "[[fix-battle-live-crash/README]]"
files:
  - "tests/unit/test_battle_service.py"
  - "tests/unit/test_battle_routes.py"
  - "tests/integration/test_battles.py"
tags:
  - task
  - battles
  - testing
---

# Task 08: Run tests & validate API sync

## Assigned Agent: `test-runner`

## Objective
Run all battle-related tests to verify the changes don't break anything. Write new tests for the enriched live endpoint response. Validate frontend builds cleanly.

## Context
Tasks 01-07 modified the battle live endpoint (backend schema, service, route) and the frontend components that consume it. This task validates everything works together.

## Files to Check/Modify
- `tests/unit/test_battle_service.py` — Run existing tests, add test for enriched `get_live_snapshot()`
- `tests/unit/test_battle_routes.py` — Run existing tests, add test for time fields in live response
- `tests/integration/test_battles.py` — Run integration tests
- Frontend build validation

## Steps

1. **Run existing battle tests:**
   ```bash
   pytest tests/ -k battle -v
   ```

2. **Add test for enriched live snapshot:**
   - Test that `get_live_snapshot()` returns all 13 fields per participant
   - Test that `rank` is computed correctly (highest equity = rank 1)
   - Test that `total_trades` defaults to 0 when no trades exist
   - Test that `win_rate` is `None` when no trades exist
   - Test that `elapsed_minutes` and `remaining_minutes` are computed correctly

3. **Validate frontend build:**
   ```bash
   cd Frontend && pnpm build
   ```

4. **Run API sync check:**
   - Verify `BattleLiveParticipantSchema` fields match `BattleLiveParticipant` TypeScript interface
   - Verify `BattleLiveResponse` schema matches TypeScript interface

## Acceptance Criteria
- [ ] All existing battle tests pass (zero regressions)
- [ ] New tests cover the enriched live snapshot response
- [ ] Frontend builds with zero TypeScript errors
- [ ] API sync: Pydantic schema fields match TypeScript interface fields 1:1
- [ ] `ruff check src/battles/ src/api/routes/battles.py src/api/schemas/battles.py` passes
- [ ] `mypy src/battles/ src/api/routes/battles.py src/api/schemas/battles.py` passes

## Dependencies
All tasks 01-07 must be complete.

## Agent Instructions
Run `pytest tests/ -k battle -v` first to see baseline. Check for any existing tests that test the live snapshot response shape — they may need updating since the response shape changed. If tests are missing for the live endpoint, create them following patterns in `tests/CLAUDE.md`.

## Estimated Complexity
Medium — running tests + writing new coverage
