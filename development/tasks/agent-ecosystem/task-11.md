---
task_id: 11
title: "Memory retrieval engine"
agent: "backend-developer"
phase: 1
depends_on: [9, 10]
status: "pending"
priority: "medium"
files: ["agent/memory/retrieval.py"]
---

# Task 11: Memory retrieval engine

## Assigned Agent: `backend-developer`

## Objective
Create the memory retrieval engine that searches memories by relevance, combining keyword matching, recency scoring, and memory type filtering. Acts as the unified query interface for the memory system.

## Files to Create
- `agent/memory/retrieval.py` — `MemoryRetriever` class

## Key Design
```python
class RetrievalResult(BaseModel):
    memory: Memory
    relevance_score: float  # 0.0 - 1.0
    source: str  # "cache" or "db"

class MemoryRetriever:
    """Unified memory retrieval with cache-first lookup."""

    def __init__(self, store: MemoryStore, cache: RedisMemoryCache): ...

    async def retrieve(
        self,
        agent_id: str,
        query: str,
        memory_types: list[MemoryType] | None = None,
        limit: int = 10,
        min_confidence: float = 0.3,
    ) -> list[RetrievalResult]:
        """
        Search flow:
        1. Check Redis cache for recent/hot memories
        2. Search Postgres for keyword + recency matches
        3. Merge, deduplicate, and rank results
        4. Cache top results for future queries
        """

    async def get_context_memories(self, agent_id: str, limit: int = 5) -> list[Memory]:
        """Get most relevant memories for current context (recent + high confidence)."""

    async def record_access(self, memory_id: str) -> None:
        """Update access timestamp and reinforce memory."""
```

## Acceptance Criteria
- [ ] Cache-first retrieval with DB fallback
- [ ] Results ranked by combined relevance score
- [ ] Deduplication between cache and DB results
- [ ] Top results cached after retrieval
- [ ] `min_confidence` filter removes low-quality memories
- [ ] `get_context_memories()` returns a curated set for LLM context

## Dependencies
- Task 09 (store), Task 10 (cache)

## Agent Instructions
1. Relevance scoring: `keyword_score * 0.4 + recency_score * 0.3 + confidence * 0.2 + reinforcement_score * 0.1`
2. Recency: memories from last 24h get full recency score, decay linearly over 7 days
3. Cache results for 5 minutes after retrieval
4. Handle both cache miss and cache failure gracefully

## Estimated Complexity
Medium — search merging and relevance scoring logic.
