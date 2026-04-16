---
task_id: 02
title: "Apply migration 024 (email_verified)"
type: task
agent: "migration-helper"
phase: 1
depends_on: [1]
status: "pending"
priority: "high"
board: "[[production-deployment/README]]"
files: ["alembic/versions/024_add_email_verified_to_accounts.py"]
tags:
  - task
  - migration
  - database
  - pre-deploy
---

# Task 02: Apply migration 024 (email_verified)

## Assigned Agent: `migration-helper`

## Objective
Apply Alembic migration 024 which adds the `email_verified` boolean column to the `accounts` table. This is required before starting services because the ORM model expects the column to exist.

## Context
Migration 024 was created for Task 35 (email verification). It adds `email_verified BOOLEAN NOT NULL DEFAULT FALSE` to the `accounts` table. Zero-downtime safe — existing rows get `false` via server default.

## Files to Modify/Create
- `alembic/versions/024_add_email_verified_to_accounts.py` — already exists, will be applied

## Acceptance Criteria
- [ ] `alembic current` shows current revision (likely 023) BEFORE running upgrade
- [ ] Capture the current revision for rollback: `export ROLLBACK_REV=$(alembic current | head -1 | awk '{print $1}')`
- [ ] `alembic upgrade head` succeeds
- [ ] `alembic current` shows 024 AFTER upgrade
- [ ] `SELECT column_name FROM information_schema.columns WHERE table_name='accounts' AND column_name='email_verified'` returns one row
- [ ] Existing account rows have `email_verified = false`
- [ ] No rows were altered/deleted (check `SELECT COUNT(*) FROM accounts` before/after)

## Dependencies
Task 01 — code must be pulled so migration file is present.

## Agent Instructions
1. Read migration 024: `alembic/versions/024_add_email_verified_to_accounts.py`
2. Verify it has `op.add_column` with `server_default=sa.false()` (zero-downtime safe)
3. Verify `down_revision = "023"` (clean chain)
4. Capture current revision before upgrade (for rollback)
5. Run `alembic upgrade head`
6. Verify column exists and has expected default

## Estimated Complexity
Low — single additive column with server default
