---
task_id: 12
title: "Tests for memory system"
agent: "test-runner"
phase: 1
depends_on: [9, 10, 11]
status: "pending"
priority: "medium"
files: ["tests/unit/test_memory_store.py", "tests/unit/test_redis_memory_cache.py", "tests/unit/test_memory_retrieval.py"]
---

# Task 12: Tests for memory system

## Assigned Agent: `test-runner`

## Objective
Write unit tests for all three memory system components: store, cache, and retriever.

## Files to Create
- `tests/unit/test_memory_store.py` — test PostgresMemoryStore CRUD, search, reinforce, forget
- `tests/unit/test_redis_memory_cache.py` — test caching, TTL, working memory, hot state
- `tests/unit/test_memory_retrieval.py` — test retrieval pipeline, ranking, dedup, cache-first

## Acceptance Criteria
- [ ] At least 8 tests for PostgresMemoryStore
- [ ] At least 6 tests for RedisMemoryCache
- [ ] At least 8 tests for MemoryRetriever
- [ ] 22+ tests total
- [ ] Mock both DB repos and Redis
- [ ] Test relevance scoring produces correct ordering
- [ ] Test cache miss → DB fallback → cache population flow
- [ ] Test graceful degradation when Redis is down

## Dependencies
- Tasks 09, 10, 11 (all memory system components)

## Agent Instructions
1. Mock `agent_learning_repo` for store tests
2. Mock Redis client (use `fakeredis` if available, otherwise `AsyncMock`)
3. For retrieval tests, set up scenarios where cache and DB return overlapping results
4. Test edge case: empty memories, all expired, very old memories

## Estimated Complexity
Medium — comprehensive memory system test coverage.
