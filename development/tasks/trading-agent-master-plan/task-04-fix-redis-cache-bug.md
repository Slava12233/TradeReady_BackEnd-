---
task_id: 04
title: "Fix RedisMemoryCache.get_cached() glob bug"
type: task
agent: "backend-developer"
phase: 0
depends_on: []
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/memory/redis_cache.py"]
tags:
  - task
  - bugfix
  - foundation
---

# Task 04: Fix RedisMemoryCache glob bug

## Assigned Agent: `backend-developer`

## Objective
Fix the `get_cached()` method in `agent/memory/redis_cache.py` which uses `redis.get(f"agent:memory:*:{memory_id}")`. Redis `GET` does not support glob patterns — this always returns None.

## Context
The Redis memory cache has a bug where `get_cached(memory_id)` constructs a key with `*` wildcard, but `GET` requires an exact key. The correct agent-scoped lookup already exists as `get_cached_for_agent(memory_id, agent_id)`.

## Files to Modify
- `agent/memory/redis_cache.py` — fix `get_cached()` method

## Fix
Either: (a) Remove `get_cached()` entirely and update all callers to use `get_cached_for_agent()`, or (b) change `get_cached()` to accept `agent_id` parameter and construct the exact key.

## Acceptance Criteria
- [ ] `get_cached()` no longer uses glob pattern in Redis key
- [ ] Cache hits work correctly (write then read returns the same data)
- [ ] Existing tests pass
- [ ] New test: `test_get_cached_returns_stored_memory`

## Estimated Complexity
Low — single method fix.
