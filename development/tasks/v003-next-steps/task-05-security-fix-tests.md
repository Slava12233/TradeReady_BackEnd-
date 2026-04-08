---
task_id: 5
title: "Write tests for all security fixes"
type: task
agent: "test-runner"
phase: 1
depends_on: [1, 2, 3, 4]
status: "done"
priority: "high"
board: "[[v003-next-steps/README]]"
files:
  - "tests/unit/test_webhook_dispatcher.py"
  - "tests/unit/test_webhook_task.py"
  - "tests/integration/test_webhooks_api.py"
  - "tests/integration/test_metrics_api.py"
  - "tests/unit/test_strategy_comparison.py"
  - "tests/unit/test_batch_step_fast.py"
tags:
  - task
  - testing
  - security
---

# Task 05: Write tests for all security fixes

## Assigned Agent: `test-runner`

## Objective
Update and add tests covering all security fixes from Tasks 1-4.

## Context
Tasks 1-4 implement security fixes. This task ensures they're all tested and existing tests still pass.

## Files to Modify/Create
- Update existing test files to cover new validation behavior
- Add new test cases for SSRF blocking, array bounds, secret removal, webhook limits

## Acceptance Criteria
- [x] SSRF tests: `http://` rejected, `https://localhost` rejected, private IPs rejected, valid HTTPS accepted
- [x] Returns bound tests: 10,001 returns rejected, 10,000 accepted
- [x] Secret tests: task no longer receives `secret` param, DB query for secret works
- [x] Webhook limit tests: 26th subscription rejected with 422
- [x] Session ID tests: invalid UUID returns 422, valid UUID works
- [x] Auth tests: metrics endpoint now requires auth (401 without key)
- [x] ALL existing tests still pass
- [x] `ruff check` passes

## Dependencies
- **All security fix tasks (1-4)** must complete first

## Agent Instructions
1. Run existing test suite first to establish baseline
2. Update tests that broke due to auth changes on metrics endpoint
3. Add targeted test cases for each security fix
4. Run full suite at the end to verify zero regressions

## Estimated Complexity
Medium — updating existing tests + adding new security-specific test cases.
