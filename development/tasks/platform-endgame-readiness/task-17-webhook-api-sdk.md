---
task_id: 17
title: "Create webhook REST endpoints + SDK methods + wire triggers"
type: task
agent: "backend-developer"
phase: 2
depends_on: [15, 16]
status: "pending"
priority: "high"
board: "[[platform-endgame-readiness/README]]"
files:
  - "src/api/routes/webhooks.py"
  - "src/api/schemas/webhooks.py"
  - "src/main.py"
  - "src/backtesting/engine.py"
  - "src/tasks/strategy_tasks.py"
  - "src/strategies/service.py"
  - "sdk/agentexchange/client.py"
  - "sdk/agentexchange/async_client.py"
tags:
  - task
  - webhooks
  - api
  - sdk
  - phase-2
---

# Task 17: Create webhook REST endpoints + SDK methods + wire triggers

## Assigned Agent: `backend-developer`

## Objective
Create the 6 webhook CRUD REST endpoints, Pydantic schemas, wire event triggers into existing code, and add SDK methods.

## Context
Tasks 15-16 create the model and dispatcher. This task builds the REST API for managing subscriptions, wires `fire_event()` calls into the backtest engine, strategy tasks, and strategy service, and adds SDK convenience methods.

## Files to Modify/Create
- `src/api/routes/webhooks.py` — 6 endpoints: POST (create, returns secret once), GET list, GET detail, PUT update, DELETE, POST test
- `src/api/schemas/webhooks.py` — Request/response schemas for all endpoints
- `src/main.py` — Register webhooks router
- `src/backtesting/engine.py` — Fire `backtest.completed` in `complete()` method
- `src/tasks/strategy_tasks.py` — Fire `strategy.test.completed` in aggregation task
- `src/strategies/service.py` — Fire `strategy.deployed` in `deploy()` method
- `sdk/agentexchange/client.py` — Add webhook CRUD methods
- `sdk/agentexchange/async_client.py` — Add async webhook CRUD methods

## Acceptance Criteria
- [ ] `POST /api/v1/webhooks` creates subscription, returns HMAC secret (shown only once)
- [ ] `GET /api/v1/webhooks` lists user's subscriptions (secret NOT returned)
- [ ] `GET /api/v1/webhooks/{id}` returns detail (secret NOT returned)
- [ ] `PUT /api/v1/webhooks/{id}` updates url, events, active, description
- [ ] `DELETE /api/v1/webhooks/{id}` deletes subscription
- [ ] `POST /api/v1/webhooks/{id}/test` sends a test event payload
- [ ] All endpoints require auth (account_id from JWT)
- [ ] Supported events: `backtest.completed`, `strategy.test.completed`, `strategy.deployed`, `battle.completed`
- [ ] `fire_event()` called in backtest engine `complete()`, strategy task aggregation, strategy deploy
- [ ] SDK has: `create_webhook()`, `list_webhooks()`, `get_webhook()`, `update_webhook()`, `delete_webhook()`, `test_webhook()`
- [ ] Router registered in `src/main.py`
- [ ] `ruff check` passes

## Dependencies
- **Task 15** (model) and **Task 16** (dispatcher) must complete first

## Agent Instructions
1. Read `src/api/routes/CLAUDE.md` for route patterns
2. Read `src/api/schemas/CLAUDE.md` for schema patterns
3. The secret is generated server-side (use `secrets.token_urlsafe(32)`) and returned ONLY in the create response
4. Supported events should be validated against an enum/set
5. The test endpoint should fire a `webhook.test` event with a sample payload
6. Wire `fire_event()` carefully — it needs a DB session, so pass `db` from the calling context

## Estimated Complexity
High — 6 endpoints, schema design, wiring triggers into 3 different files, plus SDK methods.
