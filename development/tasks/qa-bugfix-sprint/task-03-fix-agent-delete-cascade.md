---
task_id: 03
title: "Fix agent deletion CASCADE (BUG-004)"
type: task
agent: "migration-helper"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[qa-bugfix-sprint/README]]"
files: ["alembic/versions/", "src/database/models.py", "src/agents/service.py"]
tags:
  - task
  - agents
  - migration
  - P1
---

# Task 03: Fix agent deletion DATABASE_ERROR via CASCADE migration (BUG-004)

## Assigned Agent: `migration-helper`

## Objective
Create an Alembic migration that adds `ON DELETE CASCADE` to all FK references from agent ecosystem tables to `agents.id`, then verify that `DELETE /agents/{agent_id}` works.

## Context
Agent deletion fails with `DATABASE_ERROR` because newer tables added in migrations 018/019/020 (`agent_sessions`, `agent_messages`, `agent_decisions`, `agent_journal`, `agent_api_calls`, `agent_strategy_signals`) have FK references to `agents.id` WITHOUT `ON DELETE CASCADE`. When `hard_delete()` tries to remove an agent row, the FK constraints block it.

## Files to Modify/Create
- New Alembic migration file in `alembic/versions/` — drop + recreate FK constraints with `ondelete='CASCADE'`
- `src/database/models.py` — update model definitions to include `ondelete="CASCADE"` on the relationship FKs
- Optionally `src/agents/service.py` — if soft delete is preferred as a fallback

## Acceptance Criteria
- [ ] New Alembic migration created and validated
- [ ] Migration has both `upgrade()` and `downgrade()` functions
- [ ] No destructive data operations (only constraint changes)
- [ ] `DELETE /agents/{agent_id}` succeeds after migration
- [ ] Child rows in agent ecosystem tables are cascade-deleted
- [ ] Existing agent CRUD (create, list, clone, reset, archive) still works
- [ ] Migration is safe for production (no table locks beyond brief ALTER)

## Dependencies
None — can run in parallel with Tasks 01/02.

## Agent Instructions
1. Read `alembic/CLAUDE.md` for migration conventions
2. Read `src/database/models.py` — find all models with `agent_id` FK to `agents.id`
3. Identify which FKs are missing `ondelete="CASCADE"`. Expected tables:
   - `agent_sessions` (migration 018)
   - `agent_messages` (migration 018)
   - `agent_decisions` (migration 018)
   - `agent_journal` (migration 019)
   - `agent_api_calls` (migration 019)
   - `agent_strategy_signals` (migration 019)
4. Also check: `orders`, `trades`, `positions`, `balances`, `trading_sessions` — these may already have CASCADE
5. Generate migration: `alembic revision --autogenerate -m "add_cascade_delete_agent_fks"`
6. Review the auto-generated migration — ensure it only modifies FK constraints, no data loss
7. Update the ORM models in `models.py` to include `ondelete="CASCADE"` for consistency
8. Test: create an agent, add some data, delete the agent — verify no FK errors

## Estimated Complexity
Medium — migration itself is straightforward (drop + recreate FK), but must verify all affected tables and ensure safe rollback.
