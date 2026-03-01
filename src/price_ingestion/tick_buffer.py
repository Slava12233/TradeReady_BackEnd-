"""In-memory tick buffer with timed and size-triggered bulk flushes to TimescaleDB.

Ticks accumulate in a list.  A flush is triggered whenever:
- The buffer grows to ``max_size`` ticks, **or**
- ``flush_interval`` seconds have elapsed since the last flush.

Bulk inserts use asyncpg's ``copy_records_to_table`` which is 10–50× faster
than row-by-row INSERTs.  On flush failure the buffer is *retained* so that
the next flush attempt includes the outstanding ticks.

Example::

    pool = await asyncpg.create_pool(dsn=...)
    buffer = TickBuffer(db_pool=pool)
    task = asyncio.create_task(buffer.start_periodic_flush())
    await buffer.add(tick)
    await buffer.shutdown()
    task.cancel()
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC

import asyncpg

from src.cache.price_cache import Tick

logger = logging.getLogger(__name__)

_TABLE_NAME: str = "ticks"
_COLUMNS: tuple[str, ...] = (
    "time",
    "symbol",
    "price",
    "quantity",
    "is_buyer_maker",
    "trade_id",
)


class TickBuffer:
    """Thread-safe (asyncio-safe) in-memory buffer for trade ticks.

    Args:
        db_pool: An open ``asyncpg.Pool`` used for bulk COPY inserts.
        flush_interval: Seconds between periodic flushes.  Default ``1.0``.
        max_size: Flush immediately when the buffer reaches this size.
            Default ``5000``.

    Example::

        buffer = TickBuffer(pool, flush_interval=1.0, max_size=5000)
        flush_task = asyncio.create_task(buffer.start_periodic_flush())
        await buffer.add(tick)
        await buffer.shutdown()
        flush_task.cancel()
    """

    def __init__(
        self,
        db_pool: asyncpg.Pool,  # type: ignore[type-arg]
        flush_interval: float = 1.0,
        max_size: int = 5000,
    ) -> None:
        self._pool = db_pool
        self._flush_interval = flush_interval
        self._max_size = max_size
        self._buffer: list[Tick] = []
        self._lock = asyncio.Lock()
        self._total_flushed: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    async def add(self, tick: Tick) -> None:
        """Append *tick* to the buffer; trigger an immediate flush if full.

        Args:
            tick: A :class:`~src.cache.price_cache.Tick` namedtuple.
        """
        async with self._lock:
            self._buffer.append(tick)
            if len(self._buffer) >= self._max_size:
                await self._do_flush()

    async def flush(self) -> int:
        """Flush all buffered ticks to TimescaleDB now.

        On failure the buffer is retained so that the next call retries.

        Returns:
            Number of ticks actually written (0 on empty buffer or error).
        """
        async with self._lock:
            return await self._do_flush()

    async def start_periodic_flush(self) -> None:
        """Background task that flushes the buffer every ``flush_interval`` seconds.

        Runs indefinitely until cancelled; designed to be run via
        ``asyncio.create_task``.

        Example::

            task = asyncio.create_task(buffer.start_periodic_flush())
            # … later …
            task.cancel()
        """
        logger.info(
            "TickBuffer periodic flush started (interval=%.1fs, max_size=%d)",
            self._flush_interval,
            self._max_size,
        )
        while True:
            try:
                await asyncio.sleep(self._flush_interval)
                await self.flush()
            except asyncio.CancelledError:
                logger.info("TickBuffer periodic flush task cancelled")
                return
            except Exception as exc:  # noqa: BLE001
                logger.error("Unexpected error in periodic flush loop: %s", exc)

    async def shutdown(self) -> None:
        """Flush any remaining ticks before the process exits.

        Call this from the process shutdown handler *after* cancelling the
        :meth:`start_periodic_flush` task.

        Example::

            await buffer.shutdown()
        """
        logger.info("TickBuffer shutting down — performing final flush…")
        flushed = await self.flush()
        logger.info("TickBuffer shutdown complete. Final flush wrote %d ticks.", flushed)

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _do_flush(self) -> int:
        """Perform the actual COPY insert.  Caller must hold :attr:`_lock`.

        Returns:
            Number of ticks written, or 0 on empty buffer / error.
        """
        if not self._buffer:
            return 0

        # Snapshot current buffer; keep the reference so we can restore on failure.
        batch = list(self._buffer)
        count = len(batch)

        records = [
            (
                tick.timestamp.astimezone(UTC),
                tick.symbol,
                tick.price,
                tick.quantity,
                tick.is_buyer_maker,
                tick.trade_id,
            )
            for tick in batch
        ]

        try:
            async with self._pool.acquire() as conn:
                await conn.copy_records_to_table(
                    _TABLE_NAME,
                    records=records,
                    columns=list(_COLUMNS),
                )
            # Clear only after successful write.
            self._buffer.clear()
            self._total_flushed += count
            logger.debug("Flushed %d ticks to TimescaleDB (total=%d)", count, self._total_flushed)
            return count
        except asyncpg.PostgresError as exc:
            logger.error(
                "PostgreSQL error during tick flush (%d ticks retained): %s",
                count,
                exc,
            )
            return 0
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Unexpected error during tick flush (%d ticks retained): %s",
                count,
                exc,
            )
            return 0
