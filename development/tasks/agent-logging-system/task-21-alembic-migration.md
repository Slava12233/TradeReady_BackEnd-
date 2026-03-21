---
task_id: 21
title: "Generate Alembic migration for new logging tables"
type: task
agent: "migration-helper"
phase: 3
depends_on: [19, 20]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["alembic/versions/"]
tags:
  - task
  - agent
  - logging
---

# Task 21: Generate Alembic Migration

## Assigned Agent: `migration-helper`

## Objective
Generate and validate an Alembic migration for the 2 new tables (`agent_api_calls`, `agent_strategy_signals`) and the new `trace_id` column on `agent_decisions`.

## Changes to Migrate

### New Tables
1. `agent_api_calls` — 11 columns, 2 indexes, FK to agents
2. `agent_strategy_signals` — 10 columns, 2 indexes, FK to agents

### Altered Tables
3. `agent_decisions` — add `trace_id VARCHAR(32)` column (nullable, no default)

## Migration Requirements
- **Additive only** — no destructive operations
- `trace_id` column on `agent_decisions` must be nullable (existing rows have no trace_id)
- Both new tables are regular PostgreSQL tables (NOT hypertables)
- Downgrade path must drop the new tables and remove the column
- Migration naming: `018_add_agent_logging_tables.py`

## Acceptance Criteria
- [ ] Migration file generated in `alembic/versions/`
- [ ] `alembic upgrade head` succeeds (test against dev DB if available)
- [ ] `alembic downgrade -1` cleanly reverses all changes
- [ ] No destructive operations
- [ ] Indexes created as specified in Task 19 and Task 20
- [ ] FK constraints with `ON DELETE CASCADE`

## Agent Instructions
- Read `alembic/CLAUDE.md` for migration conventions
- Use `alembic revision --autogenerate -m "add agent logging tables"` if models are in place
- Validate the generated migration manually — autogenerate sometimes misses indexes
- Check that the migration revision chain is correct (depends on the latest existing migration)

## Estimated Complexity
Low — standard additive migration, well-defined schema
