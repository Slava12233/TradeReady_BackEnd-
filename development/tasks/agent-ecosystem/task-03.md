---
task_id: 03
title: "Database repositories for agent ecosystem"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1, 2]
status: "pending"
board: "[[agent-ecosystem/README]]"
priority: "high"
files: ["src/database/repositories/agent_session_repo.py", "src/database/repositories/agent_message_repo.py", "src/database/repositories/agent_decision_repo.py", "src/database/repositories/agent_journal_repo.py", "src/database/repositories/agent_learning_repo.py", "src/database/repositories/agent_feedback_repo.py", "src/database/repositories/agent_permission_repo.py", "src/database/repositories/agent_budget_repo.py", "src/database/repositories/agent_performance_repo.py", "src/database/repositories/agent_observation_repo.py"]
tags:
  - task
  - agent
  - ecosystem
---

# Task 03: Database repositories for agent ecosystem

## Assigned Agent: `backend-developer`

## Objective
Create repository classes for all 10 agent ecosystem tables, following the existing repository pattern in `src/database/repositories/`.

## Files to Create
- `src/database/repositories/agent_session_repo.py` — CRUD + find active, list by agent
- `src/database/repositories/agent_message_repo.py` — CRUD + list by session (paginated), count by session
- `src/database/repositories/agent_decision_repo.py` — CRUD + list by agent, find unresolved, update outcome
- `src/database/repositories/agent_journal_repo.py` — CRUD + list by agent, search by tags
- `src/database/repositories/agent_learning_repo.py` — CRUD + search by type, find by relevance (keyword + recency)
- `src/database/repositories/agent_feedback_repo.py` — CRUD + list by status, list by category
- `src/database/repositories/agent_permission_repo.py` — get by agent, upsert, check capability
- `src/database/repositories/agent_budget_repo.py` — get by agent, upsert, increment counters, reset daily
- `src/database/repositories/agent_performance_repo.py` — CRUD + list by agent + period, latest per strategy
- `src/database/repositories/agent_observation_repo.py` — insert, query by time range + agent

## Acceptance Criteria
- [ ] All 10 repositories created following patterns in existing repos
- [ ] Async methods using `AsyncSession`
- [ ] Proper error handling with custom exceptions
- [ ] `agent_learning_repo` has a `search()` method combining keyword match + recency scoring
- [ ] `agent_budget_repo` has atomic increment methods (no race conditions)
- [ ] `agent_observation_repo` uses time-range queries optimized for hypertable
- [ ] All repos registered in `src/database/repositories/__init__.py`

## Dependencies
- Task 01 (models), Task 02 (tables exist)

## Agent Instructions
1. Read `src/database/repositories/CLAUDE.md` and existing repos for patterns
2. Read `src/database/CLAUDE.md` for session management patterns
3. Each repo takes `AsyncSession` in constructor
4. Use `select()` / `insert()` / `update()` SQLAlchemy 2.0 style
5. For `agent_learning_repo.search()`: combine `ilike` text search with `ORDER BY` weighting recency

## Estimated Complexity
High — 10 repositories with custom query logic. Core data access layer.
