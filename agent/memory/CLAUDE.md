# agent/memory/ — Memory Store, Postgres Persistence, Redis Cache, and Retrieval

<!-- last-updated: 2026-03-21 -->

> Four-layer memory system for agent learning: an abstract store interface, a Postgres-backed production store, a Redis hot cache, and a scored retrieval engine.

## What This Module Does

The `agent/memory/` package provides persistent memory for trading agents — the ability to store observations, learn from outcomes, and retrieve relevant past experience during context assembly. It provides:

- **Abstract interface** (`MemoryStore`, `Memory`, `MemoryType`) — defines the contract all storage implementations must satisfy; callers depend on the abstract type, never the concrete implementation.
- **Postgres persistence** (`PostgresMemoryStore`) — durable storage via `AgentLearningRepository`; supports create, retrieve, search, reinforce, soft-delete, and recent-memories queries.
- **Redis hot cache** (`RedisMemoryCache`) — sub-millisecond access to frequently used memories and working state; transparent to callers (the retriever uses it internally).
- **Scored retrieval** (`MemoryRetriever`, `RetrievalResult`) — two-phase cache-first/DB-fallback lookup with a four-factor relevance score; produces curated memory sets for LLM context injection.

## Key Files

| File | Purpose |
|------|---------|
| `store.py` | `MemoryStore` ABC, `Memory` Pydantic model, `MemoryType` StrEnum, `MemoryNotFoundError` |
| `postgres_store.py` | `PostgresMemoryStore` — production `MemoryStore` via `AgentLearningRepository` |
| `redis_cache.py` | `RedisMemoryCache` — hot cache, working memory, last-regime, and signal state in Redis |
| `retrieval.py` | `MemoryRetriever`, `RetrievalResult` — scored two-phase retrieval with LLM context assembly |
| `__init__.py` | Re-exports all 8 public names |

## Public API

### `MemoryType`, `Memory`, `MemoryStore`, `MemoryNotFoundError` — `store.py`

```python
from agent.memory import MemoryType, Memory, MemoryStore, MemoryNotFoundError
```

**`MemoryType` (StrEnum):**

| Value | Meaning |
|-------|---------|
| `EPISODIC` | A specific past event (trade outcome, market moment) |
| `SEMANTIC` | General knowledge (market facts, strategy rules) |
| `PROCEDURAL` | Action patterns (when to enter, when to exit) |

**`Memory` (Pydantic model, `ConfigDict(frozen=True)`):**

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | UUID string of the memory |
| `agent_id` | `str` | UUID string of the owning agent |
| `memory_type` | `MemoryType` | Classification of memory |
| `content` | `str` | The memory text |
| `source` | `str` | Where the memory came from (e.g. `"trade_reflection"`, `"daily_summary"`) |
| `confidence` | `Decimal` | Score in `[0, 1]`; `1.0000` when unknown |
| `times_reinforced` | `int` | How many times this memory has been re-encountered |
| `created_at` | `datetime` | UTC creation timestamp |
| `last_accessed_at` | `datetime` | UTC timestamp of last retrieval |

**`MemoryStore` (abstract base class):**

All implementations must provide these async methods:

| Method | Returns | Description |
|--------|---------|-------------|
| `save(agent_id, memory_type, content, source, confidence=Decimal("1.0"))` | `Memory` | Create and persist a new memory |
| `get(memory_id)` | `Memory` | Fetch one memory by ID; raises `MemoryNotFoundError` if missing |
| `search(agent_id, query, memory_type=None, limit=10)` | `list[Memory]` | Keyword search across memories for an agent |
| `reinforce(memory_id)` | `Memory` | Increment `times_reinforced` and update `last_accessed_at` |
| `forget(memory_id)` | `None` | Soft-delete a memory (sets `expires_at = now()`) |
| `get_recent(agent_id, limit=20)` | `list[Memory]` | Most recently accessed memories across all types |

**`MemoryNotFoundError`:**

Has a `memory_id: str` attribute. Raised by `get()` and `reinforce()` when the ID does not exist.

---

### `PostgresMemoryStore` — `postgres_store.py`

```python
from agent.memory import PostgresMemoryStore

store = PostgresMemoryStore(session_factory=my_async_sessionmaker)
memory = await store.save(
    agent_id="550e8400-...",
    memory_type=MemoryType.PROCEDURAL,
    content="Always check RSI before entering BTC long positions.",
    source="trade_reflection",
    confidence=Decimal("0.85"),
)
```

**Constructor:** `PostgresMemoryStore(session_factory)`

Production `MemoryStore` implementation. Uses `AgentLearningRepository` for all database operations. The caller owns the transaction boundary — `PostgresMemoryStore` never calls `session.commit()`.

**Additional method:**

| Method | Returns | Description |
|--------|---------|-------------|
| `prune_expired(agent_id)` | `int` | Physically delete memories where `expires_at <= now()`; returns deleted count |

**Internal details:**
- `_orm_to_memory()` converts ORM rows to `Memory` instances; defaults `confidence` to `Decimal("1.0000")` when the DB column is NULL.
- `get_recent()` fetches all three types with three separate queries and merges them sorted by `last_accessed_at` descending.
- `forget()` is a soft delete (sets `expires_at`). Physical cleanup requires calling `prune_expired()` separately.

---

### `RedisMemoryCache` — `redis_cache.py`

```python
from agent.memory import RedisMemoryCache

cache = RedisMemoryCache(redis_client=my_redis)
await cache.cache_memory(memory)
recent = await cache.get_recent_memories(agent_id, limit=20)
```

**Constructor:** `RedisMemoryCache(redis_client)`

Hot cache layer in front of `PostgresMemoryStore`. All methods catch `RedisError` internally and return safe defaults — callers never see cache exceptions.

**Redis key patterns:**

| Key | Type | TTL | Contents |
|-----|------|-----|----------|
| `agent:memory:{agent_id}:recent` | Sorted set | 1 hour | Member = memory JSON, score = `last_accessed_at` epoch |
| `agent:memory:{agent_id}:{memory_id}` | String (JSON) | 1 hour | Serialised `Memory` object |
| `agent:working:{agent_id}` | Hash | No TTL | Arbitrary key-value working state (must clear explicitly) |
| `agent:last_regime:{agent_id}` | String | 1 hour | Last detected market regime string |
| `agent:signals:{agent_id}` | String (JSON) | 1 hour | Cached signal dict from last scan |

Constants: `_RECENT_SET_MAX_SIZE = 100` (oldest entries evicted when exceeded), `_HOT_STATE_TTL = 3600`.

**Memory cache methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `cache_memory(memory)` | `None` | Store one memory; add to recent sorted set |
| `get_memory(memory_id, agent_id)` | `Memory \| None` | Retrieve by ID |
| `get_recent_memories(agent_id, limit=20)` | `list[Memory]` | Newest-first from sorted set |
| `invalidate_memory(memory_id, agent_id)` | `None` | Remove from cache and recent set |

**Working memory methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `set_working_memory(agent_id, key, value)` | `None` | Store one key-value pair in working state hash |
| `get_working_memory(agent_id)` | `dict[str, str]` | Get full working state |
| `clear_working_memory(agent_id)` | `None` | Delete the entire working hash |

**Hot state methods:**

| Method | Returns | Description |
|--------|---------|-------------|
| `set_last_regime(agent_id, regime)` | `None` | Store last detected regime string |
| `get_last_regime(agent_id)` | `str \| None` | Retrieve last regime; `None` if not cached |
| `cache_signals(agent_id, signals)` | `None` | Store signal dict as JSON |
| `get_cached_signals(agent_id)` | `dict \| None` | Retrieve signal dict; `None` if not cached |

---

### `MemoryRetriever` and `RetrievalResult` — `retrieval.py`

```python
from agent.memory import MemoryRetriever, RetrievalResult

retriever = MemoryRetriever(
    store=postgres_store,
    cache=redis_cache,
)
results = await retriever.retrieve(
    agent_id="550e8400-...",
    query="BTC breakout",
    limit=10,
)
context = await retriever.get_context_memories(agent_id, max_memories=5)
```

**Constructor:** `MemoryRetriever(store, cache=None)`

Two-phase retrieval: cache first, then DB. If `cache` is `None`, goes directly to `store`.

**`RetrievalResult` (Pydantic model, `ConfigDict(frozen=True)`):**

| Field | Type | Description |
|-------|------|-------------|
| `memory` | `Memory` | The retrieved memory |
| `relevance_score` | `float` | Score in `[0.0, 1.0]` (see formula below) |
| `source` | `str` | `"cache"` or `"db"` |

**Relevance scoring formula:**

```
score = keyword_score * 0.4
      + recency_score * 0.3
      + float(confidence) * 0.2
      + reinforcement_score * 0.1
```

- `keyword_score` — 1.0 if query in `content` (case-insensitive), else 0.0
- `recency_score` — `exp(-hours_since_access / 168)` (168 = 1 week half-life)
- `confidence` — from `memory.confidence`
- `reinforcement_score` — `min(1.0, times_reinforced / 10.0)`

**`retrieve(agent_id, query, memory_type=None, limit=10) -> list[RetrievalResult]`**

Full scored search: check cache for recent memories → filter/score → if fewer than `limit`, fetch from DB → merge, deduplicate, re-score, sort descending. Top results are written back to cache with `_RETRIEVAL_CACHE_TTL = 300` (5 minutes).

**`get_context_memories(agent_id, max_memories=5, memory_types=None) -> list[Memory]`**

Returns a curated list for LLM context injection. When called with an empty query, ranks by `(recency + confidence + reinforcement)` only (no keyword matching). Returns PROCEDURAL first, then SEMANTIC, then EPISODIC. Calls `reinforce()` on each returned memory.

**`get_by_type(agent_id, memory_type, limit=10) -> list[Memory]`**

Fetch memories of a single type; cache-first then DB. Sorted newest-first.

---

## Dependency Direction

```
agent.memory
    │
    ├── src.database.repositories.agent_learning_repo (PostgresMemoryStore only)
    ├── src.database.models (AgentLearning ORM model — lazy import)
    └── redis.asyncio (RedisMemoryCache only)
```

All `src.database` imports are lazy (inside methods) to keep the module importable without a running database.

## Patterns

- **Abstract-first design**: All callers accept `MemoryStore`, never `PostgresMemoryStore`. This allows injecting mock stores in tests without any patching.
- **Cache is optional**: `MemoryRetriever` works correctly with `cache=None` — all methods fall through to the `store`. Pass a `RedisMemoryCache` in production.
- **Caller owns transactions**: `PostgresMemoryStore` never commits. Wrap calls in a transaction in the service layer if you need atomic multi-memory operations.
- **Soft delete**: `forget()` sets `expires_at` rather than deleting rows. This preserves audit history and allows undeletion. Call `prune_expired()` in a Celery cleanup task to reclaim space.
- **Score-then-reinforce**: `get_context_memories()` calls `reinforce()` on every returned memory. This means frequently retrieved memories accumulate `times_reinforced` count, which increases their future score. High-value learnings naturally surface more often over time.
- **Working memory has no TTL**: `set_working_memory()` stores data in a Redis hash without expiry. Always call `clear_working_memory()` at the end of a session to prevent stale state from leaking into future sessions.

## Gotchas

- **`Memory` is frozen**: Do not attempt to mutate fields after creation. To update `times_reinforced` or `last_accessed_at`, call `reinforce()` which returns a new `Memory` instance.
- **`prune_expired()` is not automatic**: Soft-deleted memories accumulate in the database until `prune_expired()` is called explicitly. Wire it to a Celery beat task or run it periodically.
- **`get_recent()` issues 3 DB queries**: One per `MemoryType`. For agents with large memory stores this is fine, but avoid calling it in tight loops.
- **Cache sorted set eviction**: When the recent sorted set exceeds `_RECENT_SET_MAX_SIZE = 100`, the lowest-scored (oldest) entries are evicted automatically. Memories evicted from cache are still in Postgres.
- **`RedisMemoryCache` never raises**: All methods catch `RedisError` and return safe defaults (`None`, `[]`, `{}`). A Redis outage degrades to DB-only retrieval without crashing the agent.
- **Working memory survives crashes**: Because there is no TTL, a crash mid-session leaves working memory in Redis. The next session start should call `clear_working_memory()` before populating new state.
- **Confidence is `Decimal`, not `float`**: Always pass `Decimal("0.85")` not `0.85`. The model validator rejects values outside `[0, 1]`.
