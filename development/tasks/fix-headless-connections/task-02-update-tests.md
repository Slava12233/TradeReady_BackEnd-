---
task_id: 2
title: "Update and add headless env connection tests"
type: task
agent: "test-runner"
phase: 1
depends_on: [1]
status: "done"
priority: "high"
board: "[[fix-headless-connections/README]]"
files:
  - "tradeready-gym/tests/test_headless_env.py"
tags:
  - task
  - testing
  - gymnasium
  - connection-pool
---

# Task 02: Update and Add Headless Env Connection Tests

## Assigned Agent: `test-runner`

## Objective
Update existing 52 headless env tests and add new tests for connection management lifecycle.

## Context
Task 1 changes the session lifecycle in `headless_env.py`. Existing tests that mock session creation may need updates. New tests needed for multi-episode lifecycle and connection pool behavior.

## Files to Modify/Create
- `tradeready-gym/tests/test_headless_env.py` — Update existing + add new tests

## New Tests to Add

1. **Multi-episode lifecycle:** `reset() -> step(0) x 10 -> reset() -> step(0) x 10 -> close()`
   - Assert no exceptions
   - Assert `env._episode_session is None` after close()

2. **Close-then-reset (SB3 Monitor pattern):** `reset() -> step(0) x 5 -> close() -> reset() -> step(0) x 5 -> close()`
   - Assert no exceptions
   - Assert pool recreated after close()

3. **Episode cleanup cancels active session:**
   - After first reset(), check engine has active session
   - After second reset(), check previous session was cleaned up

4. **Connection pool not exhausted:**
   - Run 5 consecutive `reset() -> step(0) x 50` cycles
   - Assert no QueuePool errors

## Acceptance Criteria
- [x] All 52 existing tests still pass (no mock updates needed — Task 1 already updated them)
- [x] Multi-episode lifecycle test passes
- [x] Close-then-reset test passes
- [x] Cleanup cancellation test passes
- [x] Pool exhaustion test passes (5 episodes × 20 steps)
- [x] `ruff check` passes

## Agent Instructions
1. Run existing tests first to see which break
2. Fix broken tests (likely need to mock `_episode_session` instead of per-call sessions)
3. Add the 4 new tests from the plan's Testing Strategy section
4. Note: tests that use mocks may need the mock session to NOT auto-close

## Estimated Complexity
Medium — updating mocks for new session pattern + 4 new tests.
