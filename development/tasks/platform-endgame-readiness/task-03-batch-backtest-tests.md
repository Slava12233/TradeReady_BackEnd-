---
task_id: 3
title: "Write tests for batch step fast (unit + integration)"
type: task
agent: "test-runner"
phase: 1
depends_on: [1, 2]
status: "pending"
priority: "high"
board: "[[platform-endgame-readiness/README]]"
files:
  - "tests/unit/test_batch_step_fast.py"
  - "tests/integration/test_batch_step_fast_api.py"
tags:
  - task
  - testing
  - backtesting
  - phase-1
---

# Task 03: Write tests for batch step fast (unit + integration)

## Assigned Agent: `test-runner`

## Objective
Write comprehensive unit and integration tests for the `step_batch_fast()` engine method and API endpoint.

## Context
Tasks 01-02 implement the batch fast stepping across engine, API, SDK, and gym. This task validates correctness.

## Files to Modify/Create
- `tests/unit/test_batch_step_fast.py` — Unit tests for engine method
- `tests/integration/test_batch_step_fast_api.py` — API endpoint integration tests

## Acceptance Criteria
- [ ] Unit tests cover: basic batch execution, fill accumulation, portfolio computed once at end, is_complete flag, include_intermediate_trades toggle
- [ ] Integration tests cover: endpoint returns correct response shape, error on invalid session_id, error on steps <= 0, batch completes session correctly
- [ ] All tests pass with `pytest`
- [ ] Tests follow `tests/CLAUDE.md` conventions (async fixtures, `create_app()` factory for integration)

## Dependencies
- **Task 01** and **Task 02** must complete first

## Agent Instructions
1. Read `tests/CLAUDE.md` for test patterns and fixtures
2. Read `tests/unit/CLAUDE.md` for unit test conventions (mock patterns)
3. Read `tests/integration/CLAUDE.md` for integration test setup (app factory, async)
4. Look at existing backtest tests for fixture patterns (session creation, sandbox setup)
5. Patch `get_settings()` before cached instance in unit tests

## Estimated Complexity
Medium — standard test writing following existing patterns.
