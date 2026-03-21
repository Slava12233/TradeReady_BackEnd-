---
task_id: 14
title: "Add memory operation logging"
type: task
agent: "backend-developer"
phase: 2
depends_on: [1]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "medium"
files: ["agent/memory/postgres_store.py", "agent/memory/redis_cache.py", "agent/memory/retrieval.py"]
tags:
  - task
  - agent
  - logging
---

# Task 14: Add Memory Operation Logging

## Assigned Agent: `backend-developer`

## Objective
Instrument the 3-layer memory system with structured logging to make memory operations observable.

## Files to Modify

### `agent/memory/postgres_store.py`
- `save()` → `logger.info("agent.memory.saved", memory_type=..., source=..., memory_id=...)`
- `get()` → `logger.debug("agent.memory.fetched", memory_id=...)`
- `search()` → `logger.info("agent.memory.searched", query=query[:50], results=len(results))`
- `reinforce()` → `logger.info("agent.memory.reinforced", memory_id=..., times=new_count)`
- `forget()` → `logger.info("agent.memory.forgotten", memory_id=...)`

### `agent/memory/redis_cache.py`
- Cache hit → `logger.debug("agent.memory.cache_hit", memory_id=...)`
- Cache miss → `logger.debug("agent.memory.cache_miss", memory_id=...)`
- Cache write → `logger.debug("agent.memory.cache_write", memory_id=..., ttl=...)`
- Working memory set/get → `logger.debug("agent.memory.working_set/get", key=...)`

### `agent/memory/retrieval.py`
- Retrieval start → `logger.info("agent.memory.retrieval.start", query=query[:50], types=...)`
- Retrieval complete → `logger.info("agent.memory.retrieval.complete", query=query[:50], total=..., cache_hits=..., db_hits=..., top_score=...)`
- Re-cache → `logger.debug("agent.memory.retrieval.recached", count=...)`

## Acceptance Criteria
- [ ] All memory CRUD operations logged
- [ ] Cache hits vs misses are distinguishable in logs
- [ ] Retrieval logs include hit source breakdown (cache vs DB)
- [ ] Query strings truncated to 50 chars in logs (no sensitive data leakage)
- [ ] `debug` level for high-frequency operations (cache hit/miss, working memory)
- [ ] `info` level for significant operations (save, search, reinforce, forget)
- [ ] `ruff check` passes on all modified files

## Agent Instructions
- Some of these files may already have logging — check existing log calls before adding duplicates
- Use `debug` level liberally for cache operations (they happen on every retrieval)
- Include `agent_id` in log context where available (it may already be in the correlation context from Task 01)

## Estimated Complexity
Medium — 3 files, each with multiple methods to instrument
