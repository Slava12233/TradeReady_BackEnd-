"""Health check endpoint for Phase 1 infrastructure.

Exposes ``GET /health`` which probes Redis, TimescaleDB, and the price
ingestion pipeline and returns a structured JSON status report.

Response shape::

    {
        "status": "ok" | "degraded" | "unhealthy",
        "redis_connected": true,
        "db_connected": true,
        "ingestion_active": true,
        "stale_pairs": ["XYZUSDT"],
        "total_pairs": 612,
        "checks": {
            "redis_latency_ms": 0.4,
            "db_latency_ms": 1.2
        }
    }

``status`` is:

- ``"ok"``        — all checks pass, zero stale pairs
- ``"degraded"``  — connected but some pairs are stale (>60 s without a tick)
- ``"unhealthy"`` — Redis or DB is unreachable

HTTP status codes:

- 200 for ``"ok"`` and ``"degraded"``
- 503 for ``"unhealthy"``
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# ---------------------------------------------------------------------------
# Internal probe helpers
# ---------------------------------------------------------------------------


async def _probe_redis() -> tuple[bool, float]:
    """Ping Redis and return (connected, latency_ms).

    Returns:
        A tuple of ``(True, latency_ms)`` on success or ``(False, -1.0)`` on
        any connection error.
    """
    try:
        from src.cache.redis_client import get_redis_client  # noqa: PLC0415

        client = await get_redis_client()
        t0 = time.perf_counter()
        await client.ping()
        latency_ms = (time.perf_counter() - t0) * 1000
        return True, round(latency_ms, 2)
    except Exception as exc:
        logger.warning("Redis health probe failed: %s", exc)
        return False, -1.0


async def _probe_db() -> tuple[bool, float]:
    """Execute a trivial SQL query and return (connected, latency_ms).

    Uses the SQLAlchemy async engine so that the probe exercises the same
    connection pool used by the application.

    Returns:
        A tuple of ``(True, latency_ms)`` on success or ``(False, -1.0)`` on
        any connection error.
    """
    try:
        from sqlalchemy import text  # noqa: PLC0415

        from src.database.session import get_engine  # noqa: PLC0415

        engine = get_engine()
        t0 = time.perf_counter()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency_ms = (time.perf_counter() - t0) * 1000
        return True, round(latency_ms, 2)
    except Exception as exc:
        logger.warning("Database health probe failed: %s", exc)
        return False, -1.0


async def _probe_ingestion() -> tuple[bool, list[str], int]:
    """Check ingestion liveness via the Redis price cache.

    A pair is considered *active* when its ``prices:meta`` timestamp is within
    the last 60 seconds.  If **any** pair is active, ingestion is considered
    live.

    Returns:
        A tuple of ``(ingestion_active, stale_pairs, total_pairs)``.
        ``stale_pairs`` is sorted alphabetically.
        ``total_pairs`` is the count of all pairs currently tracked in Redis.
        On any error all values are returned as degraded/empty.
    """
    try:
        from src.cache.redis_client import get_redis_client  # noqa: PLC0415
        from src.cache.price_cache import PriceCache  # noqa: PLC0415

        client = await get_redis_client()
        cache = PriceCache(client)

        all_prices = await cache.get_all_prices()
        total_pairs = len(all_prices)

        stale_pairs = await cache.get_stale_pairs(threshold_seconds=60)

        # Ingestion is active when at least one pair has a fresh tick, i.e. not
        # every tracked pair is stale (and there's at least one pair tracked).
        ingestion_active = total_pairs > 0 and len(stale_pairs) < total_pairs

        return ingestion_active, stale_pairs, total_pairs
    except Exception as exc:
        logger.warning("Ingestion health probe failed: %s", exc)
        return False, [], 0


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@router.get("/health")
async def health_check() -> JSONResponse:
    """Return the health status of all Phase 1 infrastructure components.

    Probes Redis, TimescaleDB, and the price ingestion pipeline in parallel
    and aggregates results into a single status response.

    Returns:
        200 with ``{"status": "ok" | "degraded"}`` when services are reachable.
        503 with ``{"status": "unhealthy"}`` when a critical service is down.

    Example::

        curl http://localhost:8000/health
    """
    import asyncio  # noqa: PLC0415

    (redis_ok, redis_ms), (db_ok, db_ms), (ingestion_active, stale_pairs, total_pairs) = (
        await asyncio.gather(
            _probe_redis(),
            _probe_db(),
            _probe_ingestion(),
        )
    )

    if not redis_ok or not db_ok:
        status = "unhealthy"
        http_status = 503
    elif stale_pairs:
        status = "degraded"
        http_status = 200
    else:
        status = "ok"
        http_status = 200

    body: dict = {
        "status": status,
        "redis_connected": redis_ok,
        "db_connected": db_ok,
        "ingestion_active": ingestion_active,
        "stale_pairs": stale_pairs,
        "total_pairs": total_pairs,
        "checks": {
            "redis_latency_ms": redis_ms,
            "db_latency_ms": db_ms,
        },
    }

    return JSONResponse(content=body, status_code=http_status)
