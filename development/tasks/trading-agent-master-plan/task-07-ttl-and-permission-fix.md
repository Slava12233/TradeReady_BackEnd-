---
task_id: 07
title: "Add TTL to working memory and fix PermissionDenied exception handling"
type: task
agent: "backend-developer"
phase: 0
depends_on: []
status: "completed"
priority: "medium"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/memory/redis_cache.py", "agent/permissions/enforcement.py", "src/utils/exceptions.py", "src/main.py"]
tags:
  - task
  - bugfix
  - foundation
---

# Task 07: TTL + PermissionDenied fixes

## Assigned Agent: `backend-developer`

## Objective
1. Add 24-hour TTL to `agent:working:{agent_id}` Redis hash as crash safety net
2. Make `PermissionDenied` a proper subclass of `TradingPlatformError` so it's auto-serialized by the global exception handler

## Context
Working memory hash has NO TTL — if the process crashes mid-session, stale state persists forever. `PermissionDenied` exception is not caught by the global handler in `src/main.py`, causing raw 500 errors instead of structured error responses.

## Files to Modify
- `agent/memory/redis_cache.py` — add `EXPIRE` after `HSET` on working memory
- `agent/permissions/enforcement.py` — change `PermissionDenied` to inherit from `TradingPlatformError`
- `src/utils/exceptions.py` — or add it here for consistency
- `src/main.py` — verify global handler catches it

## Acceptance Criteria
- [ ] `agent:working:{agent_id}` keys auto-expire after 24 hours
- [ ] `PermissionDenied` returns structured `{"error": {"code": "permission_denied", ...}}` response
- [ ] HTTP status code is 403 for permission denials
- [ ] Tests verify TTL is set on working memory operations

## Estimated Complexity
Low — two small fixes.
