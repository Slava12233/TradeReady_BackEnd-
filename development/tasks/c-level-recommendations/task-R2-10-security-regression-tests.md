---
task_id: R2-10
title: "Write regression tests for all security fixes"
type: task
agent: "test-runner"
phase: 2
depends_on: ["R2-01", "R2-02", "R2-03", "R2-04", "R2-05", "R2-06", "R2-07", "R2-08"]
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["agent/tests/test_security_regressions.py"]
tags:
  - task
  - testing
  - security
  - regression
---

# Task R2-10: Write Regression Tests for Security Fixes

## Assigned Agent: `test-runner`

## Objective
Write targeted regression tests ensuring all 7 fixed HIGH security issues cannot regress.

## Context
Security fixes without regression tests can be accidentally reverted. Each fix needs at least 2 test cases (positive + negative).

## Files to Modify/Create
- `agent/tests/test_security_regressions.py` (new)

## Acceptance Criteria
- [x] Test: non-ADMIN cannot call `grant_capability()` → raises `PermissionDenied` (R2-01)
- [x] Test: ADMIN CAN call `grant_capability()` → succeeds (R2-01)
- [x] Test: `BudgetManager.close()` awaits all pending tasks (R2-02)
- [x] Test: `verify_checksum()` blocks load on mismatch (R2-05)
- [x] Test: `verify_checksum()` blocks load on missing sidecar in strict mode (R2-05)
- [x] Test: `joblib.load()` with structure check rejects invalid payload (R2-06)
- [x] Test: audit log persists both "allow" and "deny" events (R2-04)
- [x] 15+ test functions covering all 7 issues (20 tests written)
- [x] All tests pass

## Dependencies
- R2-01 through R2-08 (fixes must be implemented to test)

## Agent Instructions
1. Read `tests/CLAUDE.md` for test conventions (async fixtures, mock patterns)
2. Follow `agent/tests/CLAUDE.md` for agent-specific test patterns
3. Use `pytest.raises(PermissionDenied)` for denial tests
4. Mock Redis and DB for unit-level regression tests

## Estimated Complexity
Medium — 15+ tests, each testing a specific security invariant
