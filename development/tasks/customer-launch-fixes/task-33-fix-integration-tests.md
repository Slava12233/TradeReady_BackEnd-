---
task_id: 33
title: "Fix 27 pre-existing integration test failures"
type: task
agent: "test-runner"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: ["tests/integration/"]
tags:
  - task
  - testing
  - integration
  - P2
---

# Task 33: Fix 27 pre-existing integration test failures

## Assigned Agent: `test-runner`

## Objective
27 integration tests fail in CI (marked `continue-on-error: true`). These should either be fixed or removed if they test deprecated functionality.

## Context
Code quality audit (SR-03) flagged this. `continue-on-error` masks real regressions. These failures need triage: fix, skip with reason, or remove.

## Files to Modify
- `tests/integration/` — Various test files with failures
- `.github/workflows/test.yml` — Eventually remove `continue-on-error: true` after fixes

## Acceptance Criteria
- [ ] Each of the 27 failures is triaged: fix / skip with `@pytest.mark.skip(reason=...)` / remove
- [ ] At least 20 of 27 are fixed (not just skipped)
- [ ] Remaining skips have clear reasons
- [ ] `continue-on-error` can be removed from CI integration test job
- [ ] No new test failures introduced

## Agent Instructions
1. Read `tests/integration/CLAUDE.md` for integration test patterns
2. Run integration tests in CI to get the full list of 27 failures
3. Categorize: fixture issues, schema changes, missing test data, real bugs
4. Fix systematically by category
5. Tests that need Docker services can be marked with `@pytest.mark.integration`

## Estimated Complexity
High — 27 individual test failures to triage and fix
