"""Cache layer — Redis-backed price store and connection management.

Public API re-exported from this package:

* :class:`RedisClient` — async connection pool wrapper with lifecycle methods
* :func:`get_redis_client` — singleton accessor for FastAPI dependencies
* :func:`close_redis_client` — singleton teardown for lifespan shutdown
* :class:`PriceCache` — high-performance price and ticker store
* :class:`Tick` — canonical in-flight data carrier (ingestion → cache)
* :class:`TickerData` — 24-hour rolling statistics container
"""

from src.cache.price_cache import PriceCache
from src.cache.redis_client import RedisClient, close_redis_client, get_redis_client
from src.cache.types import Tick, TickerData

__all__ = [
    "RedisClient",
    "get_redis_client",
    "close_redis_client",
    "PriceCache",
    "Tick",
    "TickerData",
]
