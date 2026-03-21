---
task_id: 02
title: "Alembic migration for agent ecosystem tables"
type: task
agent: "migration-helper"
phase: 1
depends_on: [1]
status: "pending"
board: "[[agent-ecosystem/README]]"
priority: "high"
files: ["alembic/versions/017_agent_ecosystem_tables.py"]
tags:
  - task
  - agent
  - ecosystem
---

# Task 02: Alembic migration for agent ecosystem tables

## Assigned Agent: `migration-helper`

## Objective
Generate an Alembic migration that creates all 10 agent ecosystem tables. Must handle TimescaleDB hypertable for `agent_observations`, proper FK constraints, and indexes.

## Tables to Create
All 10 tables from Task 01's models:
- `agent_sessions`, `agent_messages`, `agent_decisions`, `agent_journal`
- `agent_learnings`, `agent_feedback`, `agent_permissions`, `agent_budgets`
- `agent_performance`, `agent_observations`

## Files to Create/Modify
- `alembic/versions/017_agent_ecosystem_tables.py` — new migration file

## Acceptance Criteria
- [ ] Migration creates all 10 tables with correct types
- [ ] All FKs reference existing tables (`agents`, `orders`, `accounts`) correctly
- [ ] `agent_observations` converted to TimescaleDB hypertable via `SELECT create_hypertable()`
- [ ] Composite PK on `agent_observations` includes `time` column (hypertable requirement)
- [ ] Indexes on `(agent_id, created_at)` for all relevant tables
- [ ] GIN index on JSONB columns that will be queried (e.g., `agent_learnings.embedding`)
- [ ] Downgrade function drops all tables in reverse order
- [ ] Migration runs without errors on a fresh DB with existing tables present
- [ ] No destructive operations on existing tables

## Dependencies
- Task 01 (models must exist for autogenerate)

## Agent Instructions
1. Read `alembic/CLAUDE.md` for migration conventions
2. Read the latest migration in `alembic/versions/` for naming pattern
3. Use `op.create_table()` for each table (not autogenerate — be explicit)
4. After creating `agent_observations`, execute raw SQL: `SELECT create_hypertable('agent_observations', 'time', if_not_exists => TRUE)`
5. Add `op.create_index()` calls for performance-critical lookups
6. Downgrade: `op.drop_table()` in reverse dependency order (messages before sessions, etc.)

## Estimated Complexity
Medium — straightforward migration but many tables and a hypertable conversion.
