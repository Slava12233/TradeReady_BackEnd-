---
task_id: 15
title: "Add WebhookSubscription DB model + migration"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "pending"
priority: "high"
board: "[[platform-endgame-readiness/README]]"
files:
  - "src/database/models.py"
  - "alembic/versions/023_add_webhook_subscriptions.py"
tags:
  - task
  - database
  - webhooks
  - migration
  - phase-2
---

# Task 15: Add WebhookSubscription DB model + migration

## Assigned Agent: `backend-developer`

## Objective
Add the `WebhookSubscription` SQLAlchemy model and create the Alembic migration.

## Context
Improvement 6: Full webhook system needs a database model to store subscriptions. This is the foundation task — all other webhook tasks depend on it.

## Files to Modify/Create
- `src/database/models.py` — Add `WebhookSubscription` model with columns: id (UUID PK), account_id (UUID FK → accounts), url (str, max 2048), events (JSONB array), secret (str, HMAC-SHA256 signing key), description (Optional[str]), active (bool, default True), failure_count (int, default 0), created_at, updated_at, last_triggered_at (Optional)
- `alembic/versions/023_add_webhook_subscriptions.py` — Migration to create the table

## Acceptance Criteria
- [ ] `WebhookSubscription` model in `src/database/models.py` with all specified columns
- [ ] FK relationship to `accounts` table with cascade delete
- [ ] Index on `account_id` for efficient lookups
- [ ] Index on `active` for filtering
- [ ] Migration creates table correctly
- [ ] Migration has a `downgrade()` that drops the table
- [ ] `ruff check` passes

## Dependencies
None — can start immediately.

## Agent Instructions
1. Read `src/database/CLAUDE.md` for model patterns (Base class, Mapped types, naming)
2. Read `alembic/CLAUDE.md` for migration conventions (naming, async env)
3. Check current migration head — the plan says 023 but verify the actual next number
4. Follow existing model patterns in `models.py` (timestamps, UUID PKs, etc.)
5. Use `Mapped[list]` with `mapped_column(JSONB)` for the events array
6. **Important:** After writing the model, generate the migration with `alembic revision --autogenerate`

## Estimated Complexity
Low — standard model + migration following existing patterns.
