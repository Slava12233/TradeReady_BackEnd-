---
task_id: 8
title: "Verify migration safety (no destructive ops)"
type: task
agent: "migration-helper"
phase: 4
depends_on: [7]
status: "pending"
priority: "medium"
board: "[[deployment-v002/README]]"
files: ["alembic/versions/018_add_agent_logging_tables.py", "alembic/versions/019_add_feedback_lifecycle_columns.py", "alembic/versions/020_add_agent_audit_log.py"]
tags:
  - task
  - migration
  - safety
  - deployment
---

# Task 08: Verify migration safety

## Assigned Agent: `migration-helper`

## Objective
Confirm all three migrations (018, 019, 020) are additive-only with no destructive operations.

## Acceptance Criteria
- [ ] No DROP TABLE, DROP COLUMN, or DROP INDEX operations
- [ ] No NOT NULL constraints added to columns with existing data
- [ ] No hypertable modifications
- [ ] All new columns are nullable or have defaults
- [ ] Downgrade functions exist and are safe (drop what was added)
- [ ] All three migrations have "Safe for zero-downtime" in docstrings

## Agent Instructions
1. Read each migration file fully
2. Check upgrade() for destructive operations
3. Check downgrade() for completeness (must reverse all upgrade changes)
4. Verify existing data tables (candles_backfill, ticks, trading_pairs) are NOT touched

## Estimated Complexity
Low — read-only verification
