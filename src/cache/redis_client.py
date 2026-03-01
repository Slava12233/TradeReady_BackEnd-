"""Redis client with async connection pool for the AiTradingAgent platform.

Provides a singleton-style ``RedisClient`` that wraps ``redis.asyncio`` with a
capped connection pool (max 50).  All other modules obtain a Redis handle
exclusively through this class — never create ad-hoc ``redis.asyncio.Redis``
instances elsewhere.

Example::

    client = RedisClient(settings.redis_url)
    await client.connect()
    r = client.get_client()
    await r.ping()
    await client.disconnect()
"""

import logging
from typing import Self

import redis.asyncio as aioredis
from redis.asyncio.connection import ConnectionPool
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

logger = logging.getLogger(__name__)

_MAX_CONNECTIONS: int = 50

# Module-level singleton used by the health probe and other lightweight callers
# that don't go through the full RedisClient lifecycle (connect/disconnect).
_redis_singleton: aioredis.Redis | None = None  # type: ignore[type-arg]


async def get_redis_client() -> aioredis.Redis:  # type: ignore[type-arg]
    """Return a module-level Redis client, creating it on first call.

    Uses the ``REDIS_URL`` from application settings.  Suitable for use in
    health checks and FastAPI dependencies — not for the ingestion service
    which manages its own :class:`RedisClient` lifecycle.

    Returns:
        A connected async Redis client with ``decode_responses=True``.
    """
    global _redis_singleton
    if _redis_singleton is None:
        from src.config import get_settings  # noqa: PLC0415

        settings = get_settings()
        _redis_singleton = aioredis.from_url(
            settings.redis_url,
            max_connections=_MAX_CONNECTIONS,
            decode_responses=True,
        )
    return _redis_singleton


class RedisClient:
    """Async Redis connection pool wrapper.

    Args:
        url: Redis connection URL, e.g. ``redis://redis:6379/0``.
        max_connections: Upper bound on pool size.  Defaults to 50.

    Example::

        client = RedisClient("redis://localhost:6379/0")
        await client.connect()
        r = client.get_client()
        await r.set("key", "value")
        await client.disconnect()
    """

    def __init__(self, url: str, max_connections: int = _MAX_CONNECTIONS) -> None:
        self._url = url
        self._max_connections = max_connections
        self._pool: ConnectionPool | None = None
        self._redis: aioredis.Redis | None = None  # type: ignore[type-arg]

    async def connect(self) -> None:
        """Create the connection pool and verify the server is reachable.

        Raises:
            RedisConnectionError: If the initial PING fails.
        """
        self._pool = ConnectionPool.from_url(
            self._url,
            max_connections=self._max_connections,
            decode_responses=True,
        )
        self._redis = aioredis.Redis(connection_pool=self._pool)
        await self._ping()
        logger.info("Redis connected (pool max=%d url=%s)", self._max_connections, self._url)

    async def disconnect(self) -> None:
        """Close all pooled connections gracefully."""
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
        logger.info("Redis disconnected")

    def get_client(self) -> aioredis.Redis:  # type: ignore[type-arg]
        """Return the underlying async Redis client.

        Raises:
            RuntimeError: If ``connect()`` has not been called yet.
        """
        if self._redis is None:
            raise RuntimeError("RedisClient is not connected. Call connect() first.")
        return self._redis

    async def ping(self) -> bool:
        """Return ``True`` if Redis responds to PING, ``False`` otherwise.

        This is a safe, non-raising health-check wrapper used by the
        ``/health`` endpoint.
        """
        try:
            return await self._ping()
        except (RedisConnectionError, RedisTimeoutError, RuntimeError):
            return False

    # ── private ───────────────────────────────────────────────────────────────

    async def _ping(self) -> bool:
        """Send PING and return ``True``; propagates exceptions to the caller."""
        if self._redis is None:
            raise RuntimeError("RedisClient is not connected.")
        await self._redis.ping()
        return True

    # ── context manager support ───────────────────────────────────────────────

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.disconnect()
