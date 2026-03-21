---
task_id: 04
title: "Unit tests for agent ecosystem repositories"
type: task
agent: "test-runner"
phase: 1
depends_on: [3]
status: "pending"
board: "[[agent-ecosystem/README]]"
priority: "high"
files: ["tests/unit/test_agent_session_repo.py", "tests/unit/test_agent_message_repo.py", "tests/unit/test_agent_decision_repo.py", "tests/unit/test_agent_learning_repo.py", "tests/unit/test_agent_budget_repo.py"]
tags:
  - task
  - agent
  - ecosystem
---

# Task 04: Unit tests for agent ecosystem repositories

## Assigned Agent: `test-runner`

## Objective
Write unit tests for the 5 most critical agent ecosystem repositories: sessions, messages, decisions, learnings, and budgets. Other repos will be tested in integration tests.

## Files to Create
- `tests/unit/test_agent_session_repo.py` — test CRUD, find active, list by agent
- `tests/unit/test_agent_message_repo.py` — test CRUD, pagination, count
- `tests/unit/test_agent_decision_repo.py` — test CRUD, outcome update, list by agent
- `tests/unit/test_agent_learning_repo.py` — test CRUD, search with keyword + recency
- `tests/unit/test_agent_budget_repo.py` — test CRUD, atomic increment, daily reset

## Acceptance Criteria
- [ ] At least 5 tests per repository (25+ total)
- [ ] Tests use async fixtures per `tests/CLAUDE.md` patterns
- [ ] Mock `AsyncSession` — do not require a real DB
- [ ] `agent_budget_repo` tests verify atomic increment behavior
- [ ] `agent_learning_repo` tests verify search relevance ordering
- [ ] All tests pass with `pytest tests/unit/test_agent_*_repo.py`

## Dependencies
- Task 03 (repositories must exist)

## Agent Instructions
1. Read `tests/CLAUDE.md` and `tests/unit/CLAUDE.md` for test conventions
2. Read existing repo tests for mock patterns
3. Use `AsyncMock` for session, `MagicMock` for query results
4. Test edge cases: empty results, not found, duplicate inserts

## Estimated Complexity
Medium — standard unit tests following established patterns.
