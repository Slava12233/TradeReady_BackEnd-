---
task_id: 3
title: "Remove webhook secret from Celery task arguments"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[v003-next-steps/README]]"
files:
  - "src/webhooks/dispatcher.py"
  - "src/tasks/webhook_tasks.py"
tags:
  - task
  - security
  - webhooks
  - celery
---

# Task 03: Remove webhook secret from Celery task arguments

## Assigned Agent: `backend-developer`

## Objective
Stop passing the HMAC signing secret as a Celery task argument. Instead, fetch it from DB at dispatch time.

## Context
Security audit finding [HIGH]: `dispatch_webhook.delay(secret=sub.secret, ...)` stores the secret in the Redis result backend as plaintext JSON for 1 hour. Any process with Redis read access can extract secrets and forge webhook signatures.

## Files to Modify/Create
- `src/webhooks/dispatcher.py` — Remove `secret=sub.secret` from `dispatch_webhook.delay()` call
- `src/tasks/webhook_tasks.py` — Remove `secret` from function signature; query DB for secret using `subscription_id` inside `_async_dispatch`; set `ignore_result=True` on the task

## Acceptance Criteria
- [ ] `dispatch_webhook.delay()` no longer passes `secret`
- [ ] `_async_dispatch` queries DB for secret using `subscription_id`
- [ ] `ignore_result=True` set on the task decorator
- [ ] `secret` removed from task function parameters
- [ ] HMAC signing still works correctly (uses DB-fetched secret)
- [ ] If subscription not found in DB, task logs warning and returns without delivery
- [ ] Existing webhook tests updated to match new signature
- [ ] `ruff check` passes

## Dependencies
None — can run in parallel with Tasks 1 and 2.

## Agent Instructions
1. Read `src/webhooks/dispatcher.py` — find `dispatch_webhook.delay()` call
2. Read `src/tasks/webhook_tasks.py` — find `_async_dispatch` and the existing DB session pattern in `_record_failure`/`_record_success`
3. Follow the same DB session pattern: open a session, query `WebhookSubscription` by ID, get `secret`
4. If subscription is deleted between enqueue and dispatch, log a warning and return early
5. Update `tests/unit/test_webhook_dispatcher.py` and `tests/unit/test_webhook_task.py` to match

## Estimated Complexity
Medium — refactoring the task signature and adding a DB query, but follows existing patterns.
