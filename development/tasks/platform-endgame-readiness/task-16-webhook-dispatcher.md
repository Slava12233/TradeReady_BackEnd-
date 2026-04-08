---
task_id: 16
title: "Create webhook dispatcher + Celery task with HMAC signing"
type: task
agent: "backend-developer"
phase: 2
depends_on: [15]
status: "pending"
priority: "high"
board: "[[platform-endgame-readiness/README]]"
files:
  - "src/webhooks/__init__.py"
  - "src/webhooks/dispatcher.py"
  - "src/tasks/webhook_tasks.py"
  - "src/tasks/celery_app.py"
tags:
  - task
  - webhooks
  - celery
  - security
  - phase-2
---

# Task 16: Create webhook dispatcher + Celery task with HMAC signing

## Assigned Agent: `backend-developer`

## Objective
Create the webhook dispatcher module (`fire_event()`) and the Celery task that delivers webhooks with HMAC-SHA256 signatures and retry logic.

## Context
Improvement 6: The dispatcher is the core of the webhook system. When an event occurs, `fire_event()` queries active subscriptions and enqueues a Celery task for each. The task signs the payload with HMAC-SHA256 and sends it with retries.

## Files to Modify/Create
- `src/webhooks/__init__.py` — Package marker with `fire_event` export
- `src/webhooks/dispatcher.py` — `fire_event(account_id, event_name, payload, db)` function: queries active WebhookSubscription rows where event in events array, enqueues `dispatch_webhook` Celery task for each
- `src/tasks/webhook_tasks.py` — `dispatch_webhook` Celery task: HMAC-SHA256 signing with `X-Webhook-Signature` header, 10s HTTP timeout, 3 retries with exponential backoff (10s, 30s, 60s), increment failure_count, auto-disable after 10 consecutive failures
- `src/tasks/celery_app.py` — Register `src.tasks.webhook_tasks` module

## Acceptance Criteria
- [ ] `fire_event(account_id, "backtest.completed", payload, db)` queries matching subscriptions
- [ ] Only fires to subscriptions where `active=True` and event in `events` array
- [ ] Each match enqueues a `dispatch_webhook` Celery task
- [ ] Celery task computes HMAC-SHA256 of JSON payload using subscription's `secret`
- [ ] Signature sent in `X-Webhook-Signature` header
- [ ] 10-second HTTP timeout on POST
- [ ] 3 retries with exponential backoff (10s, 30s, 60s)
- [ ] `failure_count` incremented on final failure
- [ ] Subscription auto-disabled (`active=False`) after 10 consecutive failures
- [ ] `failure_count` reset to 0 on successful delivery
- [ ] Task module registered in Celery app
- [ ] `ruff check` passes

## Dependencies
- **Task 15** (WebhookSubscription model) must exist first

## Agent Instructions
1. Read `src/tasks/CLAUDE.md` for Celery task patterns
2. Read `src/webhooks/` — this is a new package, create `__init__.py`
3. Use `hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()` for signing
4. Use `httpx` (already a project dependency) for async HTTP POST
5. The retry logic should use Celery's built-in retry mechanism (`self.retry(countdown=...)`)
6. Payload should be JSON-serialized with `json.dumps(payload, default=str)` to handle datetimes/Decimals

## Estimated Complexity
High — HMAC signing, retry logic, failure counting, and auto-disable require careful implementation.
