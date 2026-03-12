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

import asyncio
from typing import Self

import redis.asyncio as aioredis
from redis.asyncio.connection import ConnectionPool
from redis.exceptions import RedisError
import structlog

logger = structlog.get_logger(__name__)

_MAX_CONNECTIONS: int = 50

# Module-level singleton with an async lock for safe concurrent first-call
# initialisation (C1-3: guards the check-then-set against concurrent coroutines).
_redis_singleton: aioredis.Redis | None = None  # type: ignore[type-arg]
_redis_lock: asyncio.Lock = asyncio.Lock()


async def get_redis_client() -> aioredis.Redis:  # type: ignore[type-arg]
    """Return a module-level Redis client, creating it on first call (async-safe).

    Uses the ``REDIS_URL`` from application settings.  Suitable for use in
    health checks and FastAPI dependencies — not for the ingestion service
    which manages its own :class:`RedisClient` lifecycle.

    Returns:
        A connected async Redis client with ``decode_responses=True``.
    """
    global _redis_singleton
    if _redis_singleton is None:
        async with _redis_lock:
            # Double-checked locking: re-test after acquiring the lock in case
            # another coroutine already completed initialisation while we waited.
            if _redis_singleton is None:
                from src.config import get_settings  # noqa: PLC0415

                settings = get_settings()
                _redis_singleton = aioredis.from_url(
                    settings.redis_url,
                    max_connections=_MAX_CONNECTIONS,
                    decode_responses=True,
                )
    return _redis_singleton


async def close_redis_client() -> None:
    """Close the module-level singleton connection pool and reset it to ``None``.

    Call this from the application ``lifespan`` shutdown handler to ensure
    TCP connections are released before the process exits and to allow tests
    to clean up between test cases.
    """
    global _redis_singleton
    async with _redis_lock:
        if _redis_singleton is not None:
            await _redis_singleton.aclose()  # type: ignore[attr-defined]
            _redis_singleton = None
            logger.info("redis_singleton_closed")


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
        self._pool: ConnectionPool | None = None  # type: ignore[type-arg]
        self._redis: aioredis.Redis | None = None  # type: ignore[type-arg]

    async def connect(self) -> None:
        """Create the connection pool and verify the server is reachable.

        If the initial PING fails, all partially-initialised resources are
        cleaned up before re-raising so that a subsequent ``connect()`` call
        starts from a clean state (C1-5).

        Raises:
            RedisError: If the initial PING fails or the connection cannot be
                established.
        """
        self._pool = ConnectionPool.from_url(
            self._url,
            max_connections=self._max_connections,
            decode_responses=True,
        )
        self._redis = aioredis.Redis(connection_pool=self._pool)
        try:
            await self._ping()
        except Exception:
            # Clean up partial state before propagating so the caller can
            # safely retry without leaking pool resources (C1-5).
            await self.disconnect()
            raise
        logger.info("redis_connected", pool_max=self._max_connections, url=self._url)

    async def disconnect(self) -> None:
        """Close all pooled connections gracefully.

        Closing the ``Redis`` instance is sufficient — it already drains and
        closes the underlying pool.  The redundant ``pool.aclose()`` call has
        been removed to avoid double-close confusion (C1-6).
        """
        if self._redis is not None:
            await self._redis.aclose()  # type: ignore[attr-defined]
            self._redis = None
        # Pool is already closed by redis.aclose(); just drop the reference.
        if self._pool is not None:
            self._pool = None
        logger.info("redis_disconnected")

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

        Catches all ``redis.exceptions.RedisError`` subtypes — including
        ``ResponseError``, ``AuthenticationError``, ``BusyLoadingError``, and
        ``DataError`` — in addition to ``RuntimeError`` for the not-connected
        case (C1-2).

        Returns:
            ``True`` on a successful PING, ``False`` on any Redis or runtime
            error.
        """
        try:
            return await self._ping()
        except (RedisError, RuntimeError):
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
