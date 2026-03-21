"""Memory retrieval engine for the agent long-term memory system.

Combines cache-first lookup with Postgres fallback, ranks results by a
composite relevance score, and caches the top results for 5 minutes after
every successful retrieval.

Scoring formula::

    score = keyword_score * 0.4
          + recency_score * 0.3
          + confidence    * 0.2
          + reinforcement_score * 0.1

Where:

- ``keyword_score`` — 1.0 if the query appears in the memory content
  (case-insensitive), 0.0 otherwise.  Extended to a partial TF-like score
  when the query contains multiple words (fraction of words matched).
- ``recency_score`` — 1.0 for memories accessed within the last 24 hours,
  decays linearly to 0.0 at 7 days, then stays 0.0 beyond 7 days.
- ``confidence`` — the ``Memory.confidence`` field cast to ``float``.
- ``reinforcement_score`` — normalised ``times_reinforced`` clamped to
  ``[0, 1]`` using a soft cap of 10 reinforcements as the maximum.

Dependency direction::

    MemoryRetriever → MemoryStore (interface) + RedisMemoryCache
    MemoryRetriever does NOT import PostgresMemoryStore directly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from pydantic import BaseModel, ConfigDict, Field

from agent.config import AgentConfig
from agent.memory.redis_cache import RedisMemoryCache
from agent.memory.store import Memory, MemoryStore, MemoryType

logger = structlog.get_logger(__name__)

# ── Module-level constants ─────────────────────────────────────────────────────

# Weight coefficients for the composite relevance score (must sum to 1.0).
_W_KEYWORD: float = 0.4
_W_RECENCY: float = 0.3
_W_CONFIDENCE: float = 0.2
_W_REINFORCEMENT: float = 0.1

# Recency decay window: full score within 24 h, linear decay to 0 at 7 days.
_RECENCY_FULL_HOURS: int = 24
_RECENCY_DECAY_DAYS: int = 7

# Soft cap used to normalise ``times_reinforced`` into [0, 1].
_REINFORCEMENT_CAP: int = 10

# TTL (seconds) applied when caching top retrieval results back to Redis.
_RETRIEVAL_CACHE_TTL: int = 300  # 5 minutes

# Maximum number of recent memory IDs to pull from the Redis sorted set when
# doing a cache-phase lookup.  Mirrors the cap set in RedisMemoryCache.
_RECENT_SET_MAX_SIZE: int = 100


# ── Public data models ─────────────────────────────────────────────────────────


class RetrievalResult(BaseModel):
    """A single memory retrieval result with its composite relevance score.

    Attributes:
        memory: The retrieved :class:`~agent.memory.store.Memory` record.
        relevance_score: Composite score in ``[0.0, 1.0]``; higher is better.
        source: Where this result was fetched from — either ``"cache"`` for a
            Redis hit or ``"db"`` for a Postgres hit.

    Example::

        result = RetrievalResult(
            memory=mem,
            relevance_score=0.82,
            source="cache",
        )
    """

    model_config = ConfigDict(frozen=True)

    memory: Memory
    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Composite relevance score in [0.0, 1.0].",
    )
    source: str = Field(
        ...,
        description='Fetch origin: "cache" or "db".',
    )


# ── Scoring helpers ────────────────────────────────────────────────────────────


def _keyword_score(content: str, query: str) -> float:
    """Compute a keyword relevance score for a memory's content.

    Single-word queries produce a binary score (1.0 / 0.0).  Multi-word
    queries produce the fraction of query words found in the content.

    Args:
        content: The memory content string.
        query: The search query (may contain multiple words).

    Returns:
        A float in ``[0.0, 1.0]``.
    """
    if not query.strip():
        return 0.0
    content_lower = content.lower()
    words = query.lower().split()
    if not words:
        return 0.0
    matched = sum(1 for w in words if w in content_lower)
    return matched / len(words)


def _recency_score(last_accessed_at: datetime) -> float:
    """Compute a recency score based on ``last_accessed_at``.

    - Memories accessed within the last 24 hours receive a score of 1.0.
    - Score decays linearly from 1.0 to 0.0 between 24 hours and 7 days.
    - Memories older than 7 days receive a score of 0.0.

    Args:
        last_accessed_at: UTC datetime of the most recent access.

    Returns:
        A float in ``[0.0, 1.0]``.
    """
    now = datetime.now(UTC)
    # Make sure last_accessed_at is timezone-aware before subtraction.
    if last_accessed_at.tzinfo is None:
        last_accessed_at = last_accessed_at.replace(tzinfo=UTC)

    age = now - last_accessed_at
    full_threshold = timedelta(hours=_RECENCY_FULL_HOURS)
    decay_threshold = timedelta(days=_RECENCY_DECAY_DAYS)

    if age <= full_threshold:
        return 1.0
    if age >= decay_threshold:
        return 0.0

    # Linear decay from full_threshold to decay_threshold.
    decay_range = (decay_threshold - full_threshold).total_seconds()
    elapsed_since_full = (age - full_threshold).total_seconds()
    return 1.0 - (elapsed_since_full / decay_range)


def _reinforcement_score(times_reinforced: int) -> float:
    """Normalise ``times_reinforced`` into ``[0.0, 1.0]`` using a soft cap.

    Uses :data:`_REINFORCEMENT_CAP` as the ceiling value; any count at or
    above the cap maps to 1.0.

    Args:
        times_reinforced: The raw reinforcement count from the memory record.

    Returns:
        A float in ``[0.0, 1.0]``.
    """
    return min(1.0, times_reinforced / _REINFORCEMENT_CAP)


def _score_memory(memory: Memory, query: str) -> float:
    """Compute the full composite relevance score for a memory.

    Applies the weighted formula::

        score = keyword_score   * 0.4
              + recency_score   * 0.3
              + confidence      * 0.2
              + reinforce_score * 0.1

    Args:
        memory: The :class:`~agent.memory.store.Memory` to score.
        query: The search query string.

    Returns:
        A float in ``[0.0, 1.0]``.
    """
    kw = _keyword_score(memory.content, query)
    rec = _recency_score(memory.last_accessed_at)
    conf = float(memory.confidence)
    reinf = _reinforcement_score(memory.times_reinforced)
    return kw * _W_KEYWORD + rec * _W_RECENCY + conf * _W_CONFIDENCE + reinf * _W_REINFORCEMENT


# ── MemoryRetriever ────────────────────────────────────────────────────────────


class MemoryRetriever:
    """Unified memory retrieval with cache-first lookup and relevance ranking.

    Orchestrates a two-phase retrieval strategy:

    1. **Cache phase** — for each memory ID in the agent's recent sorted set,
       attempt ``RedisMemoryCache.get_cached_for_agent()``.  Cache hits are
       scored and collected.
    2. **DB phase** — call ``MemoryStore.search()`` (once per requested
       memory type, or once for all types when ``memory_types`` is ``None``).
       DB results are deduplicated against cache hits by memory ID, scored,
       and merged.

    After merging, results are filtered by ``min_confidence``, sorted by
    ``relevance_score`` descending, and the top ``limit`` results are returned.
    The top results are also written back to the Redis cache with a 5-minute
    TTL so subsequent identical (or similar) queries are faster.

    Args:
        store: Any concrete :class:`~agent.memory.store.MemoryStore`
            implementation (typically :class:`~agent.memory.postgres_store.PostgresMemoryStore`).
        cache: A :class:`~agent.memory.redis_cache.RedisMemoryCache` instance.
        config: The agent configuration; used for ``memory_search_limit``.

    Example::

        retriever = MemoryRetriever(store=pg_store, cache=redis_cache, config=config)

        results = await retriever.retrieve(
            agent_id="550e8400-...",
            query="regime trending",
            memory_types=[MemoryType.PROCEDURAL, MemoryType.SEMANTIC],
            limit=5,
            min_confidence=0.4,
        )
        for r in results:
            print(r.relevance_score, r.memory.content, r.source)
    """

    def __init__(
        self,
        store: MemoryStore,
        cache: RedisMemoryCache,
        config: AgentConfig,
    ) -> None:
        self._store = store
        self._cache = cache
        self._config = config

    # ── Public interface ───────────────────────────────────────────────────────

    async def retrieve(
        self,
        agent_id: str,
        query: str,
        memory_types: list[MemoryType] | None = None,
        limit: int = 10,
        min_confidence: float = 0.3,
    ) -> list[RetrievalResult]:
        """Search memories by relevance with cache-first lookup.

        Combines keyword matching, recency decay, confidence weighting, and
        reinforcement count into a single composite score.  Results are
        deduplicated between the cache and DB layers, filtered by
        ``min_confidence``, and ranked by score descending.

        The top ``limit`` results are written back to the Redis cache with a
        5-minute TTL after every retrieval.

        Args:
            agent_id: UUID string of the agent whose memories to search.
            query: Search query — one or more keywords or a short phrase.
            memory_types: If provided, restrict results to memories of these
                types.  Pass ``None`` to search across all types.
            limit: Maximum number of results to return.  Capped internally at
                ``config.memory_search_limit``.
            min_confidence: Memories whose ``confidence`` is below this
                threshold are excluded from results.  Must be in ``[0.0, 1.0]``.

        Returns:
            A list of up to ``limit`` :class:`RetrievalResult` objects ordered
            by ``relevance_score`` descending.  Returns an empty list when no
            memories match or all matches fall below ``min_confidence``.

        Raises:
            DatabaseError: When the backing ``MemoryStore.search()`` fails in
                a non-recoverable way.  Cache failures are silent (they produce
                zero cache hits and fall through to the DB).
        """
        effective_limit = min(limit, self._config.memory_search_limit)

        # ── Phase 1: Cache lookup ──────────────────────────────────────────────
        cache_results = await self._fetch_from_cache(agent_id, query, memory_types)

        # Track IDs already retrieved from cache to deduplicate DB results.
        seen_ids: set[str] = {r.memory.id for r in cache_results}

        # ── Phase 2: DB lookup ────────────────────────────────────────────────
        db_results = await self._fetch_from_db(
            agent_id=agent_id,
            query=query,
            memory_types=memory_types,
            limit=effective_limit,
            seen_ids=seen_ids,
        )

        # ── Merge and filter ──────────────────────────────────────────────────
        all_results: list[RetrievalResult] = cache_results + db_results

        # Apply min_confidence filter.
        filtered = [
            r for r in all_results if float(r.memory.confidence) >= min_confidence
        ]

        # Sort by relevance score descending, stable for equal scores.
        filtered.sort(key=lambda r: r.relevance_score, reverse=True)

        top_results = filtered[:effective_limit]

        # ── Post-retrieval cache warm-up ──────────────────────────────────────
        await self._cache_top_results(top_results)

        logger.debug(
            "memory.retrieve.complete",
            agent_id=agent_id,
            query=query,
            cache_hits=len(cache_results),
            db_hits=len(db_results),
            returned=len(top_results),
        )

        return top_results

    async def get_context_memories(
        self,
        agent_id: str,
        limit: int = 5,
    ) -> list[Memory]:
        """Return a curated set of recent memories for LLM context injection.

        Fetches the most recently accessed memories across all memory types
        using ``MemoryStore.get_recent()``, then orders by composite score
        using an empty query (so only recency, confidence, and reinforcement
        drive the ranking — keyword weight is zero).

        This method is intended to provide the agent's LLM context window with
        a small set of high-quality, recent memories before each decision step.

        Args:
            agent_id: UUID string of the agent.
            limit: Maximum number of memories to return.  Default 5.

        Returns:
            A list of up to ``limit`` :class:`~agent.memory.store.Memory`
            objects ordered by composite relevance (recency + confidence +
            reinforcement).  Returns an empty list on any failure.
        """
        try:
            recent = await self._store.get_recent(
                agent_id=agent_id,
                memory_type=None,
                limit=max(limit * 3, 20),  # fetch more, then re-rank
            )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "memory.get_context.store_error",
                agent_id=agent_id,
                error=str(exc),
            )
            return []

        if not recent:
            return []

        # Re-rank by composite score with empty query (keyword weight is 0).
        scored = sorted(
            recent,
            key=lambda m: _score_memory(m, ""),
            reverse=True,
        )
        return scored[:limit]

    async def record_access(self, memory_id: str) -> None:
        """Record that a memory was accessed by reinforcing it in the store.

        Delegates to ``MemoryStore.reinforce()`` to atomically increment the
        reinforcement counter and update ``last_accessed_at``.  Failures are
        logged and swallowed — a failed access record must never crash the
        caller.

        Args:
            memory_id: UUID string of the memory that was accessed.
        """
        try:
            await self._store.reinforce(memory_id)
            logger.debug("memory.record_access", memory_id=memory_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "memory.record_access.failed",
                memory_id=memory_id,
                error=str(exc),
            )

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _fetch_from_cache(
        self,
        agent_id: str,
        query: str,
        memory_types: list[MemoryType] | None,
    ) -> list[RetrievalResult]:
        """Retrieve and score memories from the Redis cache.

        Reads the agent's recent sorted set to get candidate memory IDs, then
        fetches each one individually via
        ``RedisMemoryCache.get_cached_for_agent()``.  Results are filtered by
        ``memory_types`` (when provided) and scored using :func:`_score_memory`.

        Cache failures are silent — any ``RedisError`` is caught inside the
        cache layer and returns ``None``, which this method treats as a miss.

        Args:
            agent_id: UUID string of the owning agent.
            query: Search query string for scoring.
            memory_types: Optional type filter; ``None`` means all types.

        Returns:
            A list of :class:`RetrievalResult` with ``source="cache"``.
        """
        recent_ids = await self._cache.get_recent_ids(agent_id, limit=_RECENT_SET_MAX_SIZE)
        if not recent_ids:
            return []

        # Fetch all candidate memories concurrently.
        fetched: list[Memory | None] = await asyncio.gather(
            *[self._cache.get_cached_for_agent(agent_id, mid) for mid in recent_ids],
            return_exceptions=False,
        )

        results: list[RetrievalResult] = []
        for memory in fetched:
            if memory is None:
                continue
            if memory_types is not None and memory.memory_type not in memory_types:
                continue
            score = _score_memory(memory, query)
            results.append(
                RetrievalResult(memory=memory, relevance_score=score, source="cache")
            )

        return results

    async def _fetch_from_db(
        self,
        agent_id: str,
        query: str,
        memory_types: list[MemoryType] | None,
        limit: int,
        seen_ids: set[str],
    ) -> list[RetrievalResult]:
        """Retrieve and score memories from the Postgres store.

        Calls ``MemoryStore.search()`` — once per requested type when
        ``memory_types`` is a list, or once without a type filter when it is
        ``None``.  Memories whose ID is already in ``seen_ids`` (cache hits)
        are skipped to avoid duplicates.

        Args:
            agent_id: UUID string of the owning agent.
            query: Keyword query forwarded to ``MemoryStore.search()``.
            memory_types: Optional list of types to search.  ``None`` means
                all types in a single query.
            limit: Maximum results fetched from the DB per type.
            seen_ids: Set of memory IDs already retrieved from cache.

        Returns:
            A list of :class:`RetrievalResult` with ``source="db"``.
        """
        if memory_types is not None:
            # Run one search per requested type, concurrently.
            search_coros = [
                self._store.search(
                    agent_id=agent_id,
                    query=query,
                    memory_type=mt,
                    limit=limit,
                )
                for mt in memory_types
            ]
            results_per_type: list[list[Memory]] = await asyncio.gather(*search_coros)
            # Flatten, dedup by ID (keep first occurrence).
            all_memories: list[Memory] = []
            dedup_ids: set[str] = set()
            for batch in results_per_type:
                for m in batch:
                    if m.id not in dedup_ids:
                        dedup_ids.add(m.id)
                        all_memories.append(m)
        else:
            # Single search across all types (store handles filtering).
            all_memories = await self._store.search(
                agent_id=agent_id,
                query=query,
                memory_type=None,
                limit=limit,
            )

        results: list[RetrievalResult] = []
        for memory in all_memories:
            if memory.id in seen_ids:
                continue  # already returned from cache
            score = _score_memory(memory, query)
            results.append(
                RetrievalResult(memory=memory, relevance_score=score, source="db")
            )

        return results

    async def _cache_top_results(self, results: list[RetrievalResult]) -> None:
        """Write the top retrieval results back to the Redis cache.

        Caches each memory with a 5-minute TTL using
        ``RedisMemoryCache.cache_memory()``.  Cache write failures are
        swallowed — they must never affect the caller.

        Args:
            results: The ranked top-N results to warm into the cache.
        """
        if not results:
            return
        try:
            await asyncio.gather(
                *[
                    self._cache.cache_memory(r.memory, ttl=_RETRIEVAL_CACHE_TTL)
                    for r in results
                ],
                return_exceptions=True,  # swallow individual failures
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "memory.cache_top_results.error",
                error=str(exc),
            )
