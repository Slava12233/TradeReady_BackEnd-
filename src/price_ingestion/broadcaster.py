"""Price Broadcaster — publishes tick data to the Redis ``price_updates`` pub/sub channel.

Downstream consumers (WebSocket manager, analytics services) subscribe to the
``price_updates`` channel and receive price updates in real time.

Message format (JSON)::

    {
        "symbol": "BTCUSDT",
        "price": "64521.30000000",
        "quantity": "0.01200000",
        "timestamp": 1708000000000,
        "is_buyer_maker": false,
        "trade_id": 123456789
    }

Example::

    broadcaster = PriceBroadcaster(redis_client)
    await broadcaster.broadcast(tick)
    await broadcaster.broadcast_batch([tick1, tick2, tick3])
"""

from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from src.cache.price_cache import Tick

logger = logging.getLogger(__name__)

_CHANNEL: str = "price_updates"


class PriceBroadcaster:
    """Publishes trade ticks to the Redis ``price_updates`` pub/sub channel.

    Args:
        redis: An already-connected ``redis.asyncio.Redis`` instance.

    Example::

        broadcaster = PriceBroadcaster(redis_client.get_client())
        await broadcaster.broadcast(tick)
    """

    def __init__(self, redis: aioredis.Redis) -> None:  # type: ignore[type-arg]
        self._redis = redis

    async def broadcast(self, tick: Tick) -> None:
        """Publish a single tick to the ``price_updates`` channel.

        Args:
            tick: A :class:`~src.cache.price_cache.Tick` namedtuple.
        """
        message = self._serialize(tick)
        try:
            await self._redis.publish(_CHANNEL, message)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to broadcast tick for %s: %s", tick.symbol, exc)

    async def broadcast_batch(self, ticks: list[Tick]) -> None:
        """Publish multiple ticks in a single Redis pipeline.

        Using a pipeline batches all PUBLISH commands into one round-trip,
        significantly reducing network overhead for high-throughput scenarios.

        Args:
            ticks: List of :class:`~src.cache.price_cache.Tick` namedtuples.
        """
        if not ticks:
            return
        try:
            async with self._redis.pipeline(transaction=False) as pipe:
                for tick in ticks:
                    pipe.publish(_CHANNEL, self._serialize(tick))
                await pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to broadcast batch of %d ticks: %s", len(ticks), exc)

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _serialize(tick: Tick) -> str:
        """Serialise a :class:`~src.cache.price_cache.Tick` to a JSON string.

        The ``timestamp`` is expressed as an integer millisecond epoch so
        downstream consumers can parse it without knowing the Python datetime
        format.

        Args:
            tick: A :class:`~src.cache.price_cache.Tick` namedtuple.

        Returns:
            JSON-encoded string suitable for ``PUBLISH``.
        """
        return json.dumps(
            {
                "symbol": tick.symbol,
                "price": str(tick.price),
                "quantity": str(tick.quantity),
                "timestamp": int(tick.timestamp.timestamp() * 1000),
                "is_buyer_maker": tick.is_buyer_maker,
                "trade_id": tick.trade_id,
            },
            separators=(",", ":"),
        )
