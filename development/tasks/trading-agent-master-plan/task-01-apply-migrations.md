---
task_id: 01
title: "Apply Alembic migrations 018 and 019"
type: task
agent: "migration-helper"
phase: 0
depends_on: []
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["alembic/versions/018_add_agent_logging_tables.py", "alembic/versions/019_add_feedback_lifecycle_columns.py"]
tags:
  - task
  - migration
  - foundation
---

# Task 01: Apply Alembic migrations 018 and 019

## Assigned Agent: `migration-helper`

## Objective
Validate and apply migrations 018 (agent logging tables: `agent_api_calls`, `agent_strategy_signals`, `trace_id` on `agent_decisions`) and 019 (feedback lifecycle columns) to the live database.

## Context
These migrations add the observability tables required for the agent logging system. They must be applied before the agent can start recording decisions, API calls, and strategy signals.

## Files to Modify/Create
- `alembic/versions/018_add_agent_logging_tables.py` — validate safety
- `alembic/versions/019_add_feedback_lifecycle_columns.py` — validate safety

## Acceptance Criteria
- [ ] Both migrations pass safety validation (no destructive operations)
- [ ] `alembic upgrade head` succeeds
- [ ] New tables `agent_api_calls` and `agent_strategy_signals` exist
- [ ] `agent_decisions.trace_id` column exists
- [ ] Rollback path verified: `alembic downgrade -2` works cleanly

## Agent Instructions
Read `alembic/CLAUDE.md` first. Validate each migration for destructive operations, two-phase NOT NULL patterns, and hypertable PK rules. Then apply.

## Estimated Complexity
Low — migrations already written, just need validation and execution.
