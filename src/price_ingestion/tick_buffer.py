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
from datetime import UTC
from typing import TYPE_CHECKING

import asyncpg
import structlog

from src.cache.types import Tick

if TYPE_CHECKING:
    from src.price_ingestion.broadcaster import PriceBroadcaster

log = structlog.get_logger(__name__)

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
        broadcaster: Optional :class:`~src.price_ingestion.broadcaster.PriceBroadcaster`
            used to publish ticks to Redis pub/sub after each successful DB
            flush.  When provided, ``broadcast_batch()`` is called with the
            same batch that was written to the database so that all ``PUBLISH``
            commands are sent in a single pipeline round-trip.

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
        broadcaster: PriceBroadcaster | None = None,
    ) -> None:
        self._pool = db_pool
        self._flush_interval = flush_interval
        self._max_size = max_size
        self._buffer: list[Tick] = []
        self._lock = asyncio.Lock()
        self._total_flushed: int = 0
        self._broadcaster = broadcaster

    # ── Public API ────────────────────────────────────────────────────────────

    async def add(self, tick: Tick) -> None:
        """Append *tick* to the buffer; trigger an immediate flush if full.

        The lock is released before the DB write so that callers are not
        blocked for the duration of the ``asyncpg`` COPY operation.

        Args:
            tick: A :class:`~src.cache.price_cache.Tick` namedtuple.
        """
        batch: list[Tick] = []
        async with self._lock:
            self._buffer.append(tick)
            if len(self._buffer) >= self._max_size:
                # Snapshot and clear inside the lock; write outside.
                batch = list(self._buffer)
                self._buffer.clear()
        # Lock is released — DB write (and broadcast) happen without blocking add().
        if batch:
            await self._write_batch(batch)

    async def flush(self) -> int:
        """Flush all buffered ticks to TimescaleDB now.

        On failure the buffer is retained so that the next call retries.

        Returns:
            Number of ticks actually written (0 on empty buffer or error).
        """
        async with self._lock:
            batch = list(self._buffer)
            self._buffer.clear()
        # Lock released — DB write happens outside the lock.
        return await self._write_batch(batch)

    async def start_periodic_flush(self) -> None:
        """Background task that flushes the buffer every ``flush_interval`` seconds.

        Runs indefinitely until cancelled; designed to be run via
        ``asyncio.create_task``.

        Example::

            task = asyncio.create_task(buffer.start_periodic_flush())
            # … later …
            task.cancel()
        """
        log.info(
            "TickBuffer periodic flush started",
            interval=self._flush_interval,
            max_size=self._max_size,
        )
        while True:
            try:
                await asyncio.sleep(self._flush_interval)
                await self.flush()
            except asyncio.CancelledError:
                log.info("TickBuffer periodic flush task cancelled")
                return
            except Exception as exc:  # noqa: BLE001
                log.error("Unexpected error in periodic flush loop", error=str(exc))

    async def shutdown(self) -> None:
        """Flush any remaining ticks before the process exits.

        Call this from the process shutdown handler *after* cancelling the
        :meth:`start_periodic_flush` task.

        Example::

            await buffer.shutdown()
        """
        log.info("TickBuffer shutting down — performing final flush…")
        flushed = await self.flush()
        log.info("TickBuffer shutdown complete", final_flush_count=flushed)

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _write_batch(self, batch: list[Tick]) -> int:
        """Write *batch* to TimescaleDB and broadcast via pub/sub.

        Called **without** the lock held so that :meth:`add` can continue
        accepting ticks while the ``asyncpg`` COPY round-trip is in progress.
        On failure the batch is prepended back into the buffer so that the
        next flush attempt retries those ticks.

        Args:
            batch: Snapshot of ticks to write.

        Returns:
            Number of ticks written, or 0 on empty batch / error.
        """
        if not batch:
            return 0

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
            self._total_flushed += count
            log.debug("Flushed ticks to TimescaleDB", count=count, total=self._total_flushed)

            # Broadcast the same batch in a single Redis pipeline round-trip,
            # co-located with the DB flush.  Failure here is non-fatal.
            if self._broadcaster is not None:
                await self._broadcaster.broadcast_batch(batch)

            return count
        except asyncpg.PostgresError as exc:
            log.error(
                "PostgreSQL error during tick flush — retaining batch",
                count=count,
                error=str(exc),
            )
            async with self._lock:
                self._buffer = batch + self._buffer
            return 0
        except Exception as exc:  # noqa: BLE001
            log.error(
                "Unexpected error during tick flush — retaining batch",
                count=count,
                error=str(exc),
            )
            async with self._lock:
                self._buffer = batch + self._buffer
            return 0
