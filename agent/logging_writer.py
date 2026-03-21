"""Async batch writer for persisting log events to database tables.

This module provides :class:`LogBatchWriter`, a background-flushing writer that
buffers :class:`~src.database.models.AgentApiCall` and
:class:`~src.database.models.AgentStrategySignal` records in memory and writes
them to the database in bulk batches to amortise per-row commit overhead.

Typical usage::

    from src.database.session import get_session_factory
    from agent.logging_writer import LogBatchWriter

    writer = LogBatchWriter(session_factory=get_session_factory())
    await writer.start()

    # In agent decision loops:
    await writer.add_api_call({
        "trace_id": "abc123",
        "agent_id": uuid.UUID("..."),
        "channel": "rest",
        "endpoint": "/api/v1/market/prices",
        "method": "GET",
        "status_code": 200,
        "latency_ms": Decimal("42.50"),
    })

    # On shutdown:
    await writer.stop()  # drains remaining events before returning
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class LogBatchWriter:
    """Buffers log events and flushes them to the database in batches.

    Two independent bounded deques hold API-call and strategy-signal records
    respectively.  Each deque has a hard ``maxlen`` of 10 000 — once full, the
    oldest item is silently discarded (preventing unbounded memory growth).

    Flush is triggered by any of:

    - The buffer reaching *max_batch_size* items (default: 50).
    - The periodic background task firing every *flush_interval* seconds
      (default: 10.0).
    - An explicit :meth:`flush` call (e.g. during graceful shutdown via
      :meth:`stop`).

    Concurrent flush calls are serialised by an :class:`asyncio.Lock` so that
    two co-routines draining the same deque simultaneously is not possible.

    Failures during a flush are logged and swallowed — records in a failed
    batch are **not** re-queued.  This "accept the loss" policy prevents
    infinite retry loops from blocking the agent's primary trading path.

    Args:
        session_factory: An ``async_sessionmaker[AsyncSession]`` (or any
            async callable) that returns an async context manager yielding a
            database session when called with no arguments.  The writer calls
            ``async with session_factory() as session:`` for every batch.
        max_batch_size: Maximum number of records flushed per batch per table.
            When a buffer reaches this size, an immediate flush is triggered.
            Defaults to 50.
        flush_interval: Seconds between periodic background flushes.
            Defaults to 10.0.
    """

    def __init__(
        self,
        session_factory: Any,  # noqa: ANN401  # async_sessionmaker[AsyncSession] or compatible
        max_batch_size: int = 50,
        flush_interval: float = 10.0,
    ) -> None:
        self._session_factory = session_factory
        self._max_batch_size = max_batch_size
        self._flush_interval = flush_interval
        # Bounded deques: once full, oldest item is dropped automatically
        self._api_call_buffer: deque[dict[str, Any]] = deque(maxlen=10_000)
        self._signal_buffer: deque[dict[str, Any]] = deque(maxlen=10_000)
        self._flush_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the periodic background flush task.

        Safe to call multiple times — subsequent calls while the writer is
        already running are silently ignored.  The background task will
        continue running until :meth:`stop` is called.
        """
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(
            self._periodic_flush(),
            name="log_batch_writer_periodic_flush",
        )
        logger.info(
            "agent.logging_writer.started",
            flush_interval=self._flush_interval,
            max_batch_size=self._max_batch_size,
        )

    async def stop(self) -> None:
        """Cancel the periodic flush task and drain any remaining events.

        Blocks until the final flush completes so that no buffered records are
        lost on graceful shutdown.  After :meth:`stop` returns, the writer is
        in a stopped state and :meth:`add_api_call` / :meth:`add_signal` will
        still accept records (they are just never flushed automatically until
        :meth:`start` is called again or :meth:`flush` is called manually).
        """
        self._running = False
        if self._flush_task is not None:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        # Final drain — must happen outside the lock held by the cancelled task
        await self.flush()
        logger.info("agent.logging_writer.stopped")

    # ------------------------------------------------------------------
    # Public write interface
    # ------------------------------------------------------------------

    async def add_api_call(self, record: dict[str, Any]) -> None:
        """Add an API call record to the buffer.

        If the buffer reaches *max_batch_size* after this insert, an immediate
        flush is triggered before returning.

        Args:
            record: A dict whose keys must match the column names of
                :class:`~src.database.models.AgentApiCall` (excluding
                server-generated ``id`` and ``created_at``).  Required keys:
                ``trace_id``, ``agent_id``, ``channel``, ``endpoint``.
        """
        self._api_call_buffer.append(record)
        if len(self._api_call_buffer) >= self._max_batch_size:
            await self.flush()

    async def add_signal(self, record: dict[str, Any]) -> None:
        """Add a strategy signal record to the buffer.

        If the buffer reaches *max_batch_size* after this insert, an immediate
        flush is triggered before returning.

        Args:
            record: A dict whose keys must match the column names of
                :class:`~src.database.models.AgentStrategySignal` (excluding
                server-generated ``id`` and ``created_at``).  Required keys:
                ``trace_id``, ``agent_id``, ``strategy_name``, ``symbol``,
                ``action``.
        """
        self._signal_buffer.append(record)
        if len(self._signal_buffer) >= self._max_batch_size:
            await self.flush()

    # ------------------------------------------------------------------
    # Flush logic
    # ------------------------------------------------------------------

    async def flush(self) -> None:
        """Drain both buffers into the database via bulk inserts.

        Acquires the internal lock so that concurrent flush calls (e.g. a
        periodic flush racing with a size-triggered flush) do not double-drain
        the same records.  Each table is flushed in its own transaction so that
        a failure in one does not roll back the other.
        """
        async with self._lock:
            await self._flush_api_calls()
            await self._flush_signals()

    async def _flush_api_calls(self) -> None:
        """Drain up to *max_batch_size* API call records into the database.

        Must only be called while the flush lock is held.
        """
        if not self._api_call_buffer:
            return

        batch: list[dict[str, Any]] = []
        while self._api_call_buffer and len(batch) < self._max_batch_size:
            batch.append(self._api_call_buffer.popleft())

        try:
            from src.database.models import AgentApiCall  # noqa: PLC0415

            async with self._session_factory() as session:
                rows = [AgentApiCall(**record) for record in batch]
                session.add_all(rows)
                await session.commit()
            logger.debug(
                "agent.logging_writer.api_calls_flushed",
                count=len(batch),
            )
        except Exception:
            logger.exception(
                "agent.logging_writer.api_calls_flush_failed",
                count=len(batch),
            )
            # Do not re-queue — accept the loss to prevent infinite retry loops

    async def _flush_signals(self) -> None:
        """Drain up to *max_batch_size* strategy signal records into the database.

        Must only be called while the flush lock is held.
        """
        if not self._signal_buffer:
            return

        batch: list[dict[str, Any]] = []
        while self._signal_buffer and len(batch) < self._max_batch_size:
            batch.append(self._signal_buffer.popleft())

        try:
            from src.database.models import AgentStrategySignal  # noqa: PLC0415

            async with self._session_factory() as session:
                rows = [AgentStrategySignal(**record) for record in batch]
                session.add_all(rows)
                await session.commit()
            logger.debug(
                "agent.logging_writer.signals_flushed",
                count=len(batch),
            )
        except Exception:
            logger.exception(
                "agent.logging_writer.signals_flush_failed",
                count=len(batch),
            )

    async def _periodic_flush(self) -> None:
        """Background loop that flushes at regular intervals.

        Runs until :attr:`_running` is set to ``False`` by :meth:`stop`.
        Each iteration sleeps first so that a freshly started writer does not
        flush an empty buffer immediately.  Exceptions from :meth:`flush` are
        caught and logged rather than propagated, because a crash here would
        silently stop all future automatic flushes.
        """
        while self._running:
            await asyncio.sleep(self._flush_interval)
            try:
                await self.flush()
            except Exception:
                logger.exception("agent.logging_writer.periodic_flush_failed")
