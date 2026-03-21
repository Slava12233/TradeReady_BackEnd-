---
task_id: 10
title: "Redis memory cache layer"
type: task
agent: "backend-developer"
phase: 1
depends_on: [9]
status: "pending"
board: "[[agent-ecosystem/README]]"
priority: "medium"
files: ["agent/memory/redis_cache.py"]
tags:
  - task
  - agent
  - ecosystem
---

# Task 10: Redis memory cache layer

## Assigned Agent: `backend-developer`

## Objective
Create a Redis-backed cache layer for frequently accessed memories and working memory (current session context). Wraps the `MemoryStore` interface with caching.

## Files to Create
- `agent/memory/redis_cache.py` — `RedisMemoryCache` class

## Key Design
```python
class RedisMemoryCache:
    """Redis hot cache for agent memory.

    Keys:
    - agent:memory:{agent_id}:recent — sorted set of recent memory IDs by access time
    - agent:memory:{agent_id}:{memory_id} — cached memory JSON
    - agent:working:{agent_id} — current session working memory (hash)
    - agent:last_regime:{agent_id} — current market regime
    - agent:signals:{agent_id} — latest signals JSON
    """

    async def get_cached(self, memory_id: str) -> Memory | None: ...
    async def cache_memory(self, memory: Memory, ttl: int = 3600) -> None: ...
    async def invalidate(self, memory_id: str) -> None: ...

    # Working memory (session-scoped, volatile)
    async def set_working(self, agent_id: str, key: str, value: str) -> None: ...
    async def get_working(self, agent_id: str, key: str) -> str | None: ...
    async def clear_working(self, agent_id: str) -> None: ...

    # Hot state shortcuts
    async def set_regime(self, agent_id: str, regime: str) -> None: ...
    async def get_regime(self, agent_id: str) -> str | None: ...
    async def set_signals(self, agent_id: str, signals: dict) -> None: ...
    async def get_signals(self, agent_id: str) -> dict | None: ...
```

## Acceptance Criteria
- [ ] Cache layer uses existing Redis connection from `src/cache/`
- [ ] Cached memories have configurable TTL (default 1 hour)
- [ ] Working memory is per-agent and cleared on session end
- [ ] Hot state methods for regime and signals work correctly
- [ ] Cache invalidation on memory update/delete
- [ ] Follows Redis key patterns documented in CLAUDE.md

## Dependencies
- Task 09 (memory store interface)

## Agent Instructions
1. Read `src/cache/CLAUDE.md` for Redis patterns
2. Use the existing Redis pool — do not create a new connection
3. Serialize Memory objects to JSON for storage
4. Use Redis sorted sets for recent memory tracking (score = timestamp)
5. All methods must handle Redis connection failures gracefully (log + return None)

## Estimated Complexity
Medium — Redis integration with proper TTL management and error handling.
