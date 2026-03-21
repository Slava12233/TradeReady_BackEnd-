"""Agent long-term memory package.

Provides the :class:`MemoryType` enum, the :class:`Memory` Pydantic model,
the abstract :class:`MemoryStore` interface, the :class:`MemoryNotFoundError`
exception, the production Postgres implementation
:class:`PostgresMemoryStore`, the Redis hot-cache layer
:class:`RedisMemoryCache`, and the unified retrieval engine
:class:`MemoryRetriever` with its result model :class:`RetrievalResult`.

Public API::

    from agent.memory import (
        MemoryType,
        Memory,
        MemoryStore,
        MemoryNotFoundError,
        PostgresMemoryStore,
        RedisMemoryCache,
        MemoryRetriever,
        RetrievalResult,
    )
"""

from agent.memory.postgres_store import PostgresMemoryStore
from agent.memory.redis_cache import RedisMemoryCache
from agent.memory.retrieval import MemoryRetriever, RetrievalResult
from agent.memory.store import Memory, MemoryNotFoundError, MemoryStore, MemoryType

__all__ = [
    "Memory",
    "MemoryNotFoundError",
    "MemoryRetriever",
    "MemoryStore",
    "MemoryType",
    "PostgresMemoryStore",
    "RedisMemoryCache",
    "RetrievalResult",
]
