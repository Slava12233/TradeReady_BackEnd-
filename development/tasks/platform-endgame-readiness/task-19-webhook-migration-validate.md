---
task_id: 19
title: "Validate webhook migration safety"
type: task
agent: "migration-helper"
phase: 2
depends_on: [15]
status: "pending"
priority: "high"
board: "[[platform-endgame-readiness/README]]"
files:
  - "alembic/versions/023_add_webhook_subscriptions.py"
tags:
  - task
  - migration
  - webhooks
  - phase-2
---

# Task 19: Validate webhook migration safety

## Assigned Agent: `migration-helper`

## Objective
Validate the webhook subscription migration for production safety: no destructive operations, proper rollback, compatible with live database.

## Context
Task 15 creates the migration. This task validates it before it's applied to production.

## Files to Modify/Create
- `alembic/versions/023_add_webhook_subscriptions.py` — Review and validate (may edit if issues found)

## Acceptance Criteria
- [ ] Migration creates table without destructive operations
- [ ] `downgrade()` drops table cleanly
- [ ] No NOT NULL columns without defaults on existing tables
- [ ] FK constraints are correct
- [ ] Indexes are appropriate
- [ ] Migration is safe for live database (no table locks on existing data)

## Dependencies
- **Task 15** must complete first (creates the migration)

## Agent Instructions
1. Read `alembic/CLAUDE.md` for migration safety rules
2. Check for: two-phase NOT NULL, hypertable PK rules, rollback paths
3. Verify the migration head chain is correct

## Estimated Complexity
Low — standard migration review.
