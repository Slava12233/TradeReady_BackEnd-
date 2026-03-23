"""Redis hot cache for agent memory and working session state.

Provides a fast, ephemeral caching layer in front of the Postgres-backed
:class:`~agent.memory.store.MemoryStore`.  Frequently-retrieved memories
are cached as JSON strings with configurable TTL; working memory is a
per-agent volatile hash; hot state shortcuts (regime, signals) are plain
string / JSON keys scoped by agent ID.

Redis key patterns managed by this module::

    agent:memory:{agent_id}:recent           sorted set  — recent memory IDs, score = epoch access time
    agent:memory:{agent_id}:{memory_id}      string      — JSON-encoded Memory, TTL-gated
    agent:working:{agent_id}                 hash        — current session working memory
    agent:last_regime:{agent_id}             string      — current market regime label, TTL-gated
    agent:signals:{agent_id}                 string      — latest signals JSON, TTL-gated

All methods catch :class:`~redis.exceptions.RedisError` and return safe
defaults (``None`` / ``False``) rather than propagating.  Callers must handle
``None`` returns gracefully, treating them as cache-miss events.

Never create ad-hoc ``redis.asyncio.Redis`` connections — this module obtains
its handle exclusively from :func:`~src.cache.redis_client.get_redis_client`.

Example::

    from agent.memory.redis_cache import RedisMemoryCache
    from agent.memory.store import Memory, MemoryType
    from agent.config import AgentConfig
    from decimal import Decimal
    from datetime import datetime

    config = AgentConfig()
    cache = RedisMemoryCache(config=config)

    # Cache a memory
    await cache.cache_memory(memory)

    # Retrieve from cache
    hit = await cache.get_cached(memory.id, memory.agent_id)

    # Working memory
    await cache.set_working("agent-123", "last_action", "BUY")
    val = await cache.get_working("agent-123", "last_action")

    # Hot state shortcuts
    await cache.set_regime("agent-123", "TRENDING")
    regime = await cache.get_regime("agent-123")
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import redis.asyncio as aioredis
import structlog
from redis.exceptions import RedisError

from agent.config import AgentConfig
from agent.memory.store import Memory, MemoryType

logger = structlog.get_logger(__name__)

# ── Key helpers ───────────────────────────────────────────────────────────────

_RECENT_SET_KEY = "agent:memory:{agent_id}:recent"
_MEMORY_KEY = "agent:memory:{agent_id}:{memory_id}"
_WORKING_KEY = "agent:working:{agent_id}"
_REGIME_KEY = "agent:last_regime:{agent_id}"
_SIGNALS_KEY = "agent:signals:{agent_id}"

# Maximum number of IDs retained in the recent sorted set per agent.
_RECENT_SET_MAX_SIZE: int = 100

# Default TTL applied to regime and signals keys (1 hour).
_HOT_STATE_TTL: int = 3600
_WORKING_MEMORY_TTL: int = 86_400  # 24 hours — crash safety net


def _memory_key(agent_id: str, memory_id: str) -> str:
    return _MEMORY_KEY.format(agent_id=agent_id, memory_id=memory_id)


def _recent_key(agent_id: str) -> str:
    return _RECENT_SET_KEY.format(agent_id=agent_id)


def _working_key(agent_id: str) -> str:
    return _WORKING_KEY.format(agent_id=agent_id)


def _regime_key(agent_id: str) -> str:
    return _REGIME_KEY.format(agent_id=agent_id)


def _signals_key(agent_id: str) -> str:
    return _SIGNALS_KEY.format(agent_id=agent_id)


# ── Serialisation helpers ─────────────────────────────────────────────────────


def _memory_to_json(memory: Memory) -> str:
    """Serialise a :class:`~agent.memory.store.Memory` to a JSON string.

    ``Decimal`` and ``datetime`` fields are converted to their string
    representations so the JSON roundtrip is lossless.

    Args:
        memory: A fully-populated :class:`Memory` model.

    Returns:
        A JSON string representation of the memory.
    """
    return json.dumps(
        {
            "id": memory.id,
            "agent_id": memory.agent_id,
            "memory_type": memory.memory_type.value,
            "content": memory.content,
            "source": memory.source,
            "confidence": str(memory.confidence),
            "times_reinforced": memory.times_reinforced,
            "created_at": memory.created_at.isoformat(),
            "last_accessed_at": memory.last_accessed_at.isoformat(),
        }
    )


def _json_to_memory(raw: str) -> Memory:
    """Deserialise a JSON string back to a :class:`~agent.memory.store.Memory`.

    Args:
        raw: A JSON string produced by :func:`_memory_to_json`.

    Returns:
        A fully-populated :class:`Memory` model.

    Raises:
        json.JSONDecodeError: If ``raw`` is not valid JSON.
        KeyError: If an expected field is missing from the JSON object.
        ValueError: If a field value fails Pydantic validation.
    """
    data: dict[str, Any] = json.loads(raw)
    return Memory(
        id=data["id"],
        agent_id=data["agent_id"],
        memory_type=MemoryType(data["memory_type"]),
        content=data["content"],
        source=data.get("source", ""),
        confidence=Decimal(data["confidence"]),
        times_reinforced=int(data["times_reinforced"]),
        created_at=datetime.fromisoformat(data["created_at"]),
        last_accessed_at=datetime.fromisoformat(data["last_accessed_at"]),
    )


# ── RedisMemoryCache ──────────────────────────────────────────────────────────


class RedisMemoryCache:
    """Redis hot cache for agent memory and working session state.

    Wraps :func:`~src.cache.redis_client.get_redis_client` to obtain the
    shared Redis connection pool.  Never creates its own connection.

    Cached memories are stored as JSON strings with a configurable TTL
    (default from ``AgentConfig.memory_cache_ttl``, typically 3600 s).
    Working memory is stored as a Redis hash with no TTL — it is intended to
    persist across process restarts within a session and must be cleared
    explicitly via :meth:`clear_working`.

    All public methods catch :class:`~redis.exceptions.RedisError` and return
    safe defaults so that a Redis outage degrades gracefully to a full cache-
    miss scenario without crashing the agent.

    Args:
        config: :class:`~agent.config.AgentConfig` instance.  Used for
            ``memory_cache_ttl`` (default TTL for cached memories) and
            ``platform_base_url`` (for logging context only).
        redis: Optional pre-built ``redis.asyncio.Redis`` instance.  When
            ``None`` (the default), the handle is fetched lazily on the first
            operation from :func:`~src.cache.redis_client.get_redis_client`.
            Pass an explicit instance in tests to inject a mock.

    Example::

        config = AgentConfig()
        cache = RedisMemoryCache(config=config)
        await cache.cache_memory(memory)
        hit = await cache.get_cached(memory.id, memory.agent_id)
    """

    def __init__(
        self,
        config: AgentConfig,
        redis: aioredis.Redis | None = None,  # type: ignore[type-arg]
    ) -> None:
        self._config = config
        self._redis: aioredis.Redis | None = redis  # type: ignore[type-arg]

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_redis(self) -> aioredis.Redis:  # type: ignore[type-arg]
        """Return the Redis client, initialising the singleton on first call.

        Returns:
            A connected ``redis.asyncio.Redis`` instance.
        """
        if self._redis is None:
            from src.cache.redis_client import get_redis_client  # noqa: PLC0415

            self._redis = await get_redis_client()
        return self._redis

    # ── Memory cache operations ───────────────────────────────────────────────

    async def get_cached(self, memory_id: str, agent_id: str) -> Memory | None:
        """Retrieve a cached memory by its ID and owning agent.

        Delegates to :meth:`get_cached_for_agent` which constructs the exact
        Redis key ``agent:memory:{agent_id}:{memory_id}``.

        Returns ``None`` on cache miss, connection failure, or deserialisation
        error.  A ``None`` return must be treated as a cache miss — the caller
        should fall back to the Postgres store.

        Args:
            memory_id: UUID string of the memory to look up.
            agent_id: UUID string of the owning agent.

        Returns:
            The cached :class:`~agent.memory.store.Memory`, or ``None``.
        """
        return await self.get_cached_for_agent(agent_id, memory_id)

    async def get_cached_for_agent(
        self, agent_id: str, memory_id: str
    ) -> Memory | None:
        """Retrieve a cached memory by agent ID and memory ID.

        This is the preferred lookup method because the full Redis key is
        known without any scanning.

        Args:
            agent_id: UUID string of the owning agent.
            memory_id: UUID string of the memory to look up.

        Returns:
            The cached :class:`~agent.memory.store.Memory`, or ``None``.
        """
        try:
            redis = await self._get_redis()
            key = _memory_key(agent_id, memory_id)
            raw: str | None = await redis.get(key)
            if raw is None:
                logger.debug("agent.memory.cache_miss", memory_id=memory_id)
                try:
                    from agent.logging import get_agent_id  # noqa: PLC0415
                    from agent.metrics import agent_memory_cache_misses  # noqa: PLC0415

                    agent_memory_cache_misses.labels(agent_id=get_agent_id() or agent_id).inc()
                except Exception:  # noqa: BLE001
                    pass
                return None
            memory = _json_to_memory(raw)
            logger.debug("agent.memory.cache_hit", memory_id=memory_id)
            try:
                from agent.logging import get_agent_id  # noqa: PLC0415
                from agent.metrics import agent_memory_cache_hits  # noqa: PLC0415

                agent_memory_cache_hits.labels(agent_id=get_agent_id() or agent_id).inc()
            except Exception:  # noqa: BLE001
                pass
            # Update the recent sorted set score on each access.
            score = datetime.now(UTC).timestamp()
            await redis.zadd(_recent_key(agent_id), {memory_id: score})
            return memory
        except RedisError as exc:
            logger.error(
                "agent.memory.get_cached_for_agent.redis_error",
                agent_id=agent_id,
                memory_id=memory_id,
                error=str(exc),
            )
            return None
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "agent.memory.get_cached_for_agent.deserialise_error",
                agent_id=agent_id,
                memory_id=memory_id,
                error=str(exc),
            )
            return None

    async def cache_memory(self, memory: Memory, ttl: int | None = None) -> None:
        """Store a memory in the Redis hot cache.

        Also updates the ``agent:memory:{agent_id}:recent`` sorted set so
        recently cached memories can be retrieved without iterating keys.  The
        sorted set is trimmed to :data:`_RECENT_SET_MAX_SIZE` entries on every
        write to prevent unbounded growth.

        Args:
            memory: The :class:`~agent.memory.store.Memory` to cache.
            ttl: TTL in seconds for the cached entry.  Defaults to
                ``config.memory_cache_ttl`` (typically 3600 s).
        """
        effective_ttl = ttl if ttl is not None else self._config.memory_cache_ttl
        try:
            redis = await self._get_redis()
            key = _memory_key(memory.agent_id, memory.id)
            payload = _memory_to_json(memory)
            score = datetime.now(UTC).timestamp()

            async with redis.pipeline(transaction=False) as pipe:
                pipe.set(key, payload, ex=effective_ttl)
                pipe.zadd(_recent_key(memory.agent_id), {memory.id: score})
                # Trim the recent sorted set to avoid unbounded growth.
                pipe.zremrangebyrank(
                    _recent_key(memory.agent_id), 0, -(_RECENT_SET_MAX_SIZE + 1)
                )
                await pipe.execute()

            logger.debug(
                "agent.memory.cache_write",
                memory_id=memory.id,
                ttl=effective_ttl,
            )
        except RedisError as exc:
            logger.error(
                "agent.memory.cache_memory.redis_error",
                agent_id=memory.agent_id,
                memory_id=memory.id,
                error=str(exc),
            )

    async def invalidate(self, memory_id: str, agent_id: str) -> None:
        """Remove a memory from the cache.

        Should be called after the backing Postgres record is updated or
        soft-deleted so stale data is not served from the cache.

        Args:
            memory_id: UUID string of the memory to evict.
            agent_id: UUID string of the owning agent.
        """
        try:
            redis = await self._get_redis()
            key = _memory_key(agent_id, memory_id)

            async with redis.pipeline(transaction=False) as pipe:
                pipe.delete(key)
                pipe.zrem(_recent_key(agent_id), memory_id)
                await pipe.execute()

            logger.debug(
                "agent.memory.invalidate.complete", agent_id=agent_id, memory_id=memory_id
            )
        except RedisError as exc:
            logger.error(
                "agent.memory.invalidate.redis_error",
                agent_id=agent_id,
                memory_id=memory_id,
                error=str(exc),
            )

    async def get_recent_ids(
        self, agent_id: str, limit: int = 20
    ) -> list[str]:
        """Return the most recently accessed memory IDs for an agent.

        Reads the ``agent:memory:{agent_id}:recent`` sorted set ordered by
        access timestamp (highest score = most recent).

        Args:
            agent_id: UUID string of the agent.
            limit: Maximum number of IDs to return.  Defaults to 20.

        Returns:
            A list of memory ID strings, newest first.  Returns an empty
            list on Redis failure.
        """
        try:
            redis = await self._get_redis()
            key = _recent_key(agent_id)
            # ZREVRANGE returns members from highest score to lowest.
            ids: list[str] = await redis.zrevrange(key, 0, limit - 1)
            return ids
        except RedisError as exc:
            logger.error(
                "agent.memory.get_recent_ids.redis_error", agent_id=agent_id, error=str(exc)
            )
            return []

    # ── Working memory (session-scoped, volatile) ─────────────────────────────

    async def set_working(
        self, agent_id: str, key: str, value: str
    ) -> None:
        """Store a key-value pair in the agent's working memory hash.

        Working memory has a 24-hour TTL as a crash safety net.  The TTL
        is refreshed on every write, so active sessions never expire.  Use
        :meth:`clear_working` to reset it when a session ends.

        Args:
            agent_id: UUID string of the agent.
            key: Arbitrary string key within the working memory hash.
            value: String value to store.
        """
        try:
            redis = await self._get_redis()
            working_key = _working_key(agent_id)
            async with redis.pipeline(transaction=True) as pipe:
                pipe.hset(working_key, key, value)
                pipe.expire(working_key, _WORKING_MEMORY_TTL)
                await pipe.execute()
            logger.debug("agent.memory.working_set", key=key)
        except RedisError as exc:
            logger.error(
                "agent.memory.set_working.redis_error",
                agent_id=agent_id,
                key=key,
                error=str(exc),
            )

    async def get_working(self, agent_id: str, key: str) -> str | None:
        """Retrieve a value from the agent's working memory hash.

        Args:
            agent_id: UUID string of the agent.
            key: Key within the working memory hash.

        Returns:
            The stored string value, or ``None`` if the key is absent or
            Redis is unavailable.
        """
        try:
            redis = await self._get_redis()
            value: str | None = await redis.hget(_working_key(agent_id), key)
            logger.debug("agent.memory.working_get", key=key)
            return value
        except RedisError as exc:
            logger.error(
                "agent.memory.get_working.redis_error",
                agent_id=agent_id,
                key=key,
                error=str(exc),
            )
            return None

    async def get_all_working(self, agent_id: str) -> dict[str, str]:
        """Return the entire working memory hash for an agent.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            A dict of all key-value pairs in the working memory hash, or an
            empty dict on Redis failure.
        """
        try:
            redis = await self._get_redis()
            return await redis.hgetall(_working_key(agent_id))
        except RedisError as exc:
            logger.error(
                "agent.memory.get_all_working.redis_error", agent_id=agent_id, error=str(exc)
            )
            return {}

    async def clear_working(self, agent_id: str) -> None:
        """Delete all working memory for an agent.

        Should be called when a trading session ends to prevent stale
        in-session state from leaking into the next session.

        Args:
            agent_id: UUID string of the agent.
        """
        try:
            redis = await self._get_redis()
            await redis.delete(_working_key(agent_id))
            logger.debug("agent.memory.clear_working.complete", agent_id=agent_id)
        except RedisError as exc:
            logger.error(
                "agent.memory.clear_working.redis_error", agent_id=agent_id, error=str(exc)
            )

    # ── Hot state shortcuts ───────────────────────────────────────────────────

    async def set_regime(
        self, agent_id: str, regime: str, ttl: int = _HOT_STATE_TTL
    ) -> None:
        """Store the current market regime label for an agent.

        Args:
            agent_id: UUID string of the agent.
            regime: Regime label string (e.g. ``"TRENDING"``).
            ttl: TTL in seconds.  Defaults to 3600 s.
        """
        try:
            redis = await self._get_redis()
            await redis.set(_regime_key(agent_id), regime, ex=ttl)
        except RedisError as exc:
            logger.error(
                "agent.memory.set_regime.redis_error",
                agent_id=agent_id,
                regime=regime,
                error=str(exc),
            )

    async def get_regime(self, agent_id: str) -> str | None:
        """Return the current market regime label for an agent.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            Regime label string, or ``None`` if not set or expired.
        """
        try:
            redis = await self._get_redis()
            return await redis.get(_regime_key(agent_id))
        except RedisError as exc:
            logger.error(
                "agent.memory.get_regime.redis_error", agent_id=agent_id, error=str(exc)
            )
            return None

    async def set_signals(
        self,
        agent_id: str,
        signals: dict[str, Any],
        ttl: int = _HOT_STATE_TTL,
    ) -> None:
        """Store the latest signals dict for an agent as a JSON string.

        Args:
            agent_id: UUID string of the agent.
            signals: Arbitrary dict of signal data.  Must be JSON-serialisable.
            ttl: TTL in seconds.  Defaults to 3600 s.
        """
        try:
            redis = await self._get_redis()
            payload = json.dumps(signals)
            await redis.set(_signals_key(agent_id), payload, ex=ttl)
        except RedisError as exc:
            logger.error(
                "agent.memory.set_signals.redis_error", agent_id=agent_id, error=str(exc)
            )
        except (TypeError, ValueError) as exc:
            logger.error(
                "agent.memory.set_signals.serialise_error", agent_id=agent_id, error=str(exc)
            )

    async def get_signals(self, agent_id: str) -> dict[str, Any] | None:
        """Return the latest signals dict for an agent.

        Args:
            agent_id: UUID string of the agent.

        Returns:
            Deserialised signals dict, or ``None`` if not set, expired, or
            on any error.
        """
        try:
            redis = await self._get_redis()
            raw: str | None = await redis.get(_signals_key(agent_id))
            if raw is None:
                return None
            return json.loads(raw)  # type: ignore[return-value]
        except RedisError as exc:
            logger.error(
                "agent.memory.get_signals.redis_error", agent_id=agent_id, error=str(exc)
            )
            return None
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "agent.memory.get_signals.deserialise_error", agent_id=agent_id, error=str(exc)
            )
            return None
