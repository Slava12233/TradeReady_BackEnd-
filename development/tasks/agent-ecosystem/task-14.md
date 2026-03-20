---
task_id: 14
title: "Celery beat tasks for agent scheduled work"
agent: "backend-developer"
phase: 1
depends_on: [13]
status: "pending"
priority: "medium"
files: ["agent/tasks.py"]
---

# Task 14: Celery beat tasks for agent scheduled work

## Assigned Agent: `backend-developer`

## Objective
Create Celery tasks for agent scheduled activities: morning market review, daily budget reset, memory cleanup, and performance snapshot.

## Files to Create/Modify
- `agent/tasks.py` — new Celery task definitions
- `src/tasks/celery_app.py` — register agent tasks in beat schedule (modify)

## Tasks to Define
1. `agent_morning_review` — daily at market open: scan market, generate summary
2. `agent_budget_reset` — daily at midnight UTC: reset daily trade counters
3. `agent_memory_cleanup` — daily: expire old low-confidence memories
4. `agent_performance_snapshot` — hourly: calculate and save rolling performance stats

## Acceptance Criteria
- [ ] All 4 tasks defined as Celery tasks
- [ ] Tasks registered in Celery beat schedule
- [ ] Budget reset is atomic (no partial resets)
- [ ] Memory cleanup respects `expires_at` and confidence thresholds
- [ ] Performance snapshot uses existing metrics calculator from `src/metrics/`
- [ ] Each task has proper error handling and logging

## Dependencies
- Task 13 (agent server for context)

## Agent Instructions
1. Read `src/tasks/CLAUDE.md` for Celery task patterns
2. Read `src/tasks/celery_app.py` for existing beat schedule
3. Tasks should work independently of whether the agent server is running
4. Use structlog for consistent logging
5. Budget reset: use `agent_budget_repo.reset_daily()` method from Task 03

## Estimated Complexity
Low — standard Celery tasks following existing patterns.
