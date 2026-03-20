---
task_id: 09
title: "Memory store interface and Postgres implementation"
agent: "backend-developer"
phase: 1
depends_on: [3]
status: "pending"
priority: "high"
files: ["agent/memory/__init__.py", "agent/memory/store.py", "agent/memory/postgres_store.py"]
---

# Task 09: Memory store interface and Postgres implementation

## Assigned Agent: `backend-developer`

## Objective
Create the abstract memory store interface and its Postgres-backed implementation. This is the persistence layer for the agent's long-term memory (learnings, episodic events, procedural knowledge).

## Files to Create
- `agent/memory/__init__.py` — export public classes
- `agent/memory/store.py` — abstract `MemoryStore` interface
- `agent/memory/postgres_store.py` — `PostgresMemoryStore` implementation

## Key Design
```python
class MemoryType(str, Enum):
    EPISODIC = "episodic"      # Specific events
    SEMANTIC = "semantic"      # Learned facts
    PROCEDURAL = "procedural"  # Learned behaviors

class Memory(BaseModel):
    id: str
    agent_id: str
    memory_type: MemoryType
    content: str
    source: str
    confidence: Decimal
    times_reinforced: int
    created_at: datetime
    last_accessed_at: datetime

class MemoryStore(ABC):
    @abstractmethod
    async def save(self, memory: Memory) -> str: ...

    @abstractmethod
    async def get(self, memory_id: str) -> Memory | None: ...

    @abstractmethod
    async def search(self, agent_id: str, query: str, memory_type: MemoryType | None = None, limit: int = 10) -> list[Memory]: ...

    @abstractmethod
    async def reinforce(self, memory_id: str) -> None:
        """Increment reinforcement count and update last_accessed_at."""

    @abstractmethod
    async def forget(self, memory_id: str) -> None:
        """Soft-delete or expire a memory."""

    @abstractmethod
    async def get_recent(self, agent_id: str, memory_type: MemoryType | None = None, limit: int = 20) -> list[Memory]: ...
```

## Acceptance Criteria
- [ ] Abstract `MemoryStore` interface with all CRUD + search methods
- [ ] `PostgresMemoryStore` implements all methods via `agent_learning_repo`
- [ ] Search combines keyword matching (ilike) with recency weighting
- [ ] `reinforce()` atomically increments counter
- [ ] `forget()` sets `expires_at` to now (soft delete)
- [ ] Pydantic models for `Memory` with proper validation

## Dependencies
- Task 03 (agent_learning_repo)

## Agent Instructions
1. Read `agent/models/` for existing Pydantic model patterns
2. Interface in `store.py` — implementation in `postgres_store.py`
3. Search relevance: score = keyword_match_weight * 0.6 + recency_weight * 0.4
4. Use `agent_learning_repo` for all DB operations — do not access session directly

## Estimated Complexity
Medium — clean interface + one implementation with relevance-scored search.
