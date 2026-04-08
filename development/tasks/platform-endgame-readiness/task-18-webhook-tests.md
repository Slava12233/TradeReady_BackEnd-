---
task_id: 18
title: "Write tests for webhook system (unit + integration)"
type: task
agent: "test-runner"
phase: 2
depends_on: [15, 16, 17]
status: "pending"
priority: "high"
board: "[[platform-endgame-readiness/README]]"
files:
  - "tests/unit/test_webhook_dispatcher.py"
  - "tests/unit/test_webhook_task.py"
  - "tests/integration/test_webhooks_api.py"
tags:
  - task
  - testing
  - webhooks
  - phase-2
---

# Task 18: Write tests for webhook system (unit + integration)

## Assigned Agent: `test-runner`

## Objective
Write comprehensive tests for the webhook dispatcher, Celery task, and API endpoints.

## Context
Tasks 15-17 implement the full webhook system. This task validates all components.

## Files to Modify/Create
- `tests/unit/test_webhook_dispatcher.py` — Unit tests for `fire_event()` logic
- `tests/unit/test_webhook_task.py` — Unit tests for HMAC signing, retry logic, failure counting
- `tests/integration/test_webhooks_api.py` — Integration tests for all 6 endpoints

## Acceptance Criteria
- [ ] Dispatcher tests: fires to matching subscriptions only, skips inactive, skips non-matching events
- [ ] Task tests: HMAC signature is correct, retry on HTTP failure, failure_count incremented, auto-disable after 10 failures, failure_count reset on success
- [ ] API tests: CRUD lifecycle (create → list → get → update → delete), test endpoint works, secret only in create response, auth required
- [ ] All tests pass

## Dependencies
- **Tasks 15, 16, 17** must all complete first

## Agent Instructions
1. Read `tests/CLAUDE.md` for conventions
2. For HMAC tests: compute expected signature manually and compare
3. Mock HTTP calls in task tests (don't hit real URLs)
4. Use `httpx_mock` or `respx` if available, otherwise `unittest.mock.patch`

## Estimated Complexity
Medium — multiple test files but each follows standard patterns.
