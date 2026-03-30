---
task_id: R2-04
title: "Persist allow audit events to agent_audit_log table"
type: task
agent: "security-reviewer"
phase: 2
depends_on: ["R1-03"]
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["src/database/models.py", "alembic/versions/020_add_agent_audit_log.py", "src/database/repositories/agent_audit_log_repo.py", "agent/permissions/enforcement.py"]
tags:
  - task
  - security
  - database
  - migration
  - audit
---

# Task R2-04: Persist "Allow" Audit Events to `agent_audit_log` Table

## Assigned Agent: `security-reviewer`

## Objective
Create an `agent_audit_log` table and persist both "allow" and "deny" permission check outcomes for complete audit trail.

## Context
HIGH-4 from security review: "allow" audit events are not persisted to DB; only "deny" events are. Post-restart, no durable trail of authorized trades exists.

## Files to Modify/Create
- `src/database/models.py` — add `AgentAuditLog` model
- `alembic/versions/020_add_agent_audit_log.py` — new migration
- `src/database/repositories/agent_audit_log_repo.py` — new repository
- `agent/permissions/enforcement.py` — persist allow events using batch pattern

## Acceptance Criteria
- [ ] `agent_audit_log` table created with fields: `id` (UUID PK), `agent_id`, `action`, `outcome` (allow/deny), `reason`, `trade_value` (Decimal), `metadata` (JSONB), `created_at`
- [ ] Migration 020 is safe and reversible
- [ ] Both "allow" and "deny" events appear in table after running a trade workflow
- [ ] Batch-flush pattern used (100 entries or 30 seconds) to avoid write amplification
- [ ] Configurable `audit_allow_events: bool = True` flag

## Dependencies
- R1-03 (DB must be running for migration)

## Agent Instructions
1. Read `alembic/CLAUDE.md` for migration naming: `020_add_agent_audit_log.py`
2. Model uses `NUMERIC(20,8)` for `trade_value` (project convention)
3. Use existing batch-flush pattern from enforcement.py deny events
4. Delegate migration generation to `migration-helper` agent for validation
5. "Allow" events are much higher volume — consider sampling flag

## Estimated Complexity
High — new table, migration, repository, and enforcement changes
