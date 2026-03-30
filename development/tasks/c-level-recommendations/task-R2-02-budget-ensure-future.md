---
task_id: R2-02
title: "Track and await ensure_future tasks in BudgetManager"
type: task
agent: "security-reviewer"
phase: 2
depends_on: []
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["agent/permissions/budget.py", "agent/server.py"]
tags:
  - task
  - security
  - permissions
  - async
---

# Task R2-02: Track and Await `ensure_future` Tasks in BudgetManager

## Assigned Agent: `security-reviewer`

## Objective
Prevent budget counter data loss on shutdown by tracking fire-and-forget persistence tasks and awaiting them during graceful shutdown.

## Context
HIGH-2 from security review: `asyncio.ensure_future(_maybe_persist)` in `record_trade`/`record_loss` (lines ~902, ~986) can be cancelled on shutdown, losing the last counter snapshot.

## Files to Modify/Create
- `agent/permissions/budget.py` — add task tracking and `close()` method
- `agent/server.py` — wire `BudgetManager.close()` into shutdown sequence

## Acceptance Criteria
- [ ] `BudgetManager.__init__` creates `self._pending_persists: set[asyncio.Task]`
- [ ] `asyncio.ensure_future` replaced with `asyncio.create_task` + tracking
- [ ] `close()` method awaits all pending tasks with `asyncio.gather(..., return_exceptions=True)`
- [ ] `AgentServer._shutdown()` calls `await budget_manager.close()`
- [ ] Test verifies no pending tasks after `close()`

## Dependencies
None — pure code change

## Agent Instructions
1. Read `agent/permissions/CLAUDE.md` for BudgetManager architecture
2. In `__init__`, add `self._pending_persists: set[asyncio.Task] = set()`
3. Replace each `asyncio.ensure_future(self._maybe_persist(agent_id))` with:
   ```python
   task = asyncio.create_task(self._maybe_persist(agent_id))
   self._pending_persists.add(task)
   task.add_done_callback(self._pending_persists.discard)
   ```
4. Add `async def close(self)` that gathers all pending tasks
5. Wire into `AgentServer._shutdown()`

## Estimated Complexity
Medium — async task lifecycle management
