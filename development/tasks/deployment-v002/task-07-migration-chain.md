---
task_id: 7
title: "Verify migration chain integrity"
type: task
agent: "migration-helper"
phase: 4
depends_on: []
status: "pending"
priority: "medium"
board: "[[deployment-v002/README]]"
files: ["alembic/versions/018_add_agent_logging_tables.py", "alembic/versions/019_add_feedback_lifecycle_columns.py", "alembic/versions/020_add_agent_audit_log.py"]
tags:
  - task
  - migration
  - deployment
---

# Task 07: Verify migration chain integrity

## Assigned Agent: `migration-helper`

## Objective
Verify the migration chain 017→018→019→020 is unbroken and all down_revision pointers are correct.

## Acceptance Criteria
- [ ] Migration 018 `down_revision` is "017"
- [ ] Migration 019 `down_revision` is "018"
- [ ] Migration 020 `down_revision` is "019"
- [ ] No orphaned or missing migrations in the chain
- [ ] Note: migration 011 is intentionally missing (chain goes 010→012)

## Agent Instructions
1. Read `alembic/CLAUDE.md` for migration conventions
2. Grep for `down_revision` in each migration file
3. Verify the chain is unbroken from current head (017 on prod) to new head (020)

## Estimated Complexity
Low — verification only, no code changes
