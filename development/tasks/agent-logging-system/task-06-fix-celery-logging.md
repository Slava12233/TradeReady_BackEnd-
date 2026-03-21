---
task_id: 06
title: "Fix Celery task logging to use structlog"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/tasks.py"]
tags:
  - task
  - agent
  - logging
---

# Task 06: Fix Celery Task Logging

## Assigned Agent: `backend-developer`

## Objective
Migrate `agent/tasks.py` from stdlib `logging` to `structlog`. Celery workers run as separate processes, so they need their own `configure_agent_logging()` call.

## Files to Modify
- `agent/tasks.py` — replace `logging.getLogger` with `structlog.get_logger`, add config call

## Implementation Details
1. Replace `import logging` / `logging.getLogger(__name__)` with `import structlog` / `structlog.get_logger(__name__)`
2. Add `configure_agent_logging()` call at module level (guarded: only if structlog not already configured)
3. Rename all log event strings to follow the `agent.task.*` convention
4. Ensure per-agent isolation pattern (`for agent_id in agent_ids: try/except`) still works with structlog
5. Use `logger.exception()` for caught exceptions (preserves traceback in JSON)

## Acceptance Criteria
- [ ] No `import logging` in `agent/tasks.py` (except stdlib_logging if needed for level constants)
- [ ] All 4 Celery tasks produce JSON log output
- [ ] Per-agent error isolation is preserved
- [ ] Event names follow `agent.task.{task_name}.{outcome}` pattern
- [ ] `ruff check agent/tasks.py` passes

## Agent Instructions
- Read `agent/tasks.py` fully first
- The 4 tasks are: `agent_morning_review`, `agent_budget_reset`, `agent_memory_cleanup`, `agent_performance_snapshot`
- Celery workers are separate processes — `configure_agent_logging()` must be called before any logger is used
- Consider using a module-level guard: `if not structlog.is_configured(): configure_agent_logging()`

## Estimated Complexity
Low — single file, straightforward migration
