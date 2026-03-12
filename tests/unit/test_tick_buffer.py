"""Unit tests for :class:`~src.price_ingestion.tick_buffer.TickBuffer`.

Test coverage:
- Buffer accumulates ticks without flushing when under max_size.
- Immediate flush triggered when buffer reaches max_size.
- Manual flush clears buffer and returns written count.
- Buffer is retained (not cleared) when flush fails.
- Shutdown performs a final flush of remaining ticks.
- Periodic flush task calls flush on the given interval.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from src.price_ingestion.tick_buffer import TickBuffer
from tests.conftest import make_tick

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_buffer(
    pool: MagicMock,
    flush_interval: float = 10.0,
    max_size: int = 5,
) -> TickBuffer:
    """Create a TickBuffer with a short flush_interval for fast tests."""
    return TickBuffer(db_pool=pool, flush_interval=flush_interval, max_size=max_size)


# ---------------------------------------------------------------------------
# Basic add / buffer state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_single_tick_does_not_flush(mock_asyncpg_pool: MagicMock) -> None:
    """Adding one tick below max_size should not trigger a flush."""
    buffer = _make_buffer(mock_asyncpg_pool, max_size=5)
    tick = make_tick()

    await buffer.add(tick)

    assert len(buffer._buffer) == 1
    mock_asyncpg_pool.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_add_multiple_ticks_below_threshold(mock_asyncpg_pool: MagicMock) -> None:
    """Adding N-1 ticks should keep them all in the buffer."""
    buffer = _make_buffer(mock_asyncpg_pool, max_size=5)

    for i in range(4):
        await buffer.add(make_tick(trade_id=i))

    assert len(buffer._buffer) == 4
    mock_asyncpg_pool.acquire.assert_not_called()


# ---------------------------------------------------------------------------
# Size-threshold flush
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_triggered_at_max_size(mock_asyncpg_pool: MagicMock) -> None:
    """Adding the max_size-th tick must trigger an immediate flush."""
    buffer = _make_buffer(mock_asyncpg_pool, max_size=3)

    for i in range(3):
        await buffer.add(make_tick(trade_id=i))

    # After reaching max_size the buffer should have been cleared
    assert len(buffer._buffer) == 0
    assert buffer._total_flushed == 3


@pytest.mark.asyncio
async def test_flush_called_with_correct_records(mock_asyncpg_pool: MagicMock) -> None:
    """Records passed to copy_records_to_table should match the ticks added."""
    buffer = _make_buffer(mock_asyncpg_pool, max_size=2)
    ts = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
    t1 = make_tick("BTCUSDT", "64000.00", "0.01", ts, False, 10)
    t2 = make_tick("ETHUSDT", "3400.00", "0.50", ts, True, 20)

    await buffer.add(t1)
    await buffer.add(t2)  # triggers flush

    # Retrieve the connection mock from the pool
    conn = mock_asyncpg_pool.acquire.return_value.__aenter__.return_value
    conn.copy_records_to_table.assert_awaited_once()

    call_kwargs = conn.copy_records_to_table.call_args
    records = (
        call_kwargs.kwargs.get("records") or call_kwargs.args[1] if call_kwargs.args else call_kwargs.kwargs["records"]
    )
    assert len(records) == 2
    assert records[0][1] == "BTCUSDT"
    assert records[1][1] == "ETHUSDT"


# ---------------------------------------------------------------------------
# Manual flush
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manual_flush_returns_count(mock_asyncpg_pool: MagicMock) -> None:
    """flush() should return the number of ticks written."""
    buffer = _make_buffer(mock_asyncpg_pool, max_size=100)

    for i in range(7):
        await buffer.add(make_tick(trade_id=i))

    count = await buffer.flush()

    assert count == 7
    assert len(buffer._buffer) == 0
    assert buffer._total_flushed == 7


@pytest.mark.asyncio
async def test_manual_flush_empty_buffer_returns_zero(mock_asyncpg_pool: MagicMock) -> None:
    """flush() on an empty buffer should return 0 without hitting the DB."""
    buffer = _make_buffer(mock_asyncpg_pool, max_size=100)

    count = await buffer.flush()

    assert count == 0
    mock_asyncpg_pool.acquire.assert_not_called()


# ---------------------------------------------------------------------------
# Failure retention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_buffer_retained_on_postgres_error(mock_asyncpg_pool: MagicMock) -> None:
    """When copy_records_to_table raises PostgresError the buffer must be kept."""
    conn = mock_asyncpg_pool.acquire.return_value.__aenter__.return_value
    conn.copy_records_to_table = AsyncMock(side_effect=asyncpg.PostgresError("connection lost"))

    buffer = _make_buffer(mock_asyncpg_pool, max_size=100)
    for i in range(3):
        await buffer.add(make_tick(trade_id=i))

    count = await buffer.flush()

    assert count == 0
    assert len(buffer._buffer) == 3  # retained


@pytest.mark.asyncio
async def test_buffer_retained_on_unexpected_error(mock_asyncpg_pool: MagicMock) -> None:
    """When an unexpected exception occurs the buffer must not be cleared."""
    conn = mock_asyncpg_pool.acquire.return_value.__aenter__.return_value
    conn.copy_records_to_table = AsyncMock(side_effect=RuntimeError("boom"))

    buffer = _make_buffer(mock_asyncpg_pool, max_size=100)
    await buffer.add(make_tick(trade_id=99))

    count = await buffer.flush()

    assert count == 0
    assert len(buffer._buffer) == 1


@pytest.mark.asyncio
async def test_retry_after_failure(mock_asyncpg_pool: MagicMock) -> None:
    """After a failed flush the same ticks should be written on the next call."""
    conn = mock_asyncpg_pool.acquire.return_value.__aenter__.return_value
    # First call fails, second call succeeds
    conn.copy_records_to_table = AsyncMock(side_effect=[asyncpg.PostgresError("first failure"), None])

    buffer = _make_buffer(mock_asyncpg_pool, max_size=100)
    await buffer.add(make_tick(trade_id=1))

    first_count = await buffer.flush()  # fails
    assert first_count == 0
    assert len(buffer._buffer) == 1

    second_count = await buffer.flush()  # succeeds
    assert second_count == 1
    assert len(buffer._buffer) == 0


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shutdown_flushes_remaining_ticks(mock_asyncpg_pool: MagicMock) -> None:
    """shutdown() must flush all remaining buffered ticks."""
    buffer = _make_buffer(mock_asyncpg_pool, max_size=100)

    for i in range(5):
        await buffer.add(make_tick(trade_id=i))

    await buffer.shutdown()

    assert len(buffer._buffer) == 0
    assert buffer._total_flushed == 5


@pytest.mark.asyncio
async def test_shutdown_empty_buffer(mock_asyncpg_pool: MagicMock) -> None:
    """shutdown() on empty buffer should complete without errors."""
    buffer = _make_buffer(mock_asyncpg_pool, max_size=100)

    await buffer.shutdown()

    mock_asyncpg_pool.acquire.assert_not_called()


# ---------------------------------------------------------------------------
# Periodic flush task
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_periodic_flush_fires_on_interval(mock_asyncpg_pool: MagicMock) -> None:
    """start_periodic_flush should call flush after flush_interval seconds."""
    buffer = _make_buffer(mock_asyncpg_pool, flush_interval=0.05, max_size=100)

    for i in range(3):
        await buffer.add(make_tick(trade_id=i))

    task = asyncio.create_task(buffer.start_periodic_flush())

    # Wait slightly longer than the flush interval
    await asyncio.sleep(0.12)

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # After at least one periodic flush the buffer should be empty
    assert len(buffer._buffer) == 0
    assert buffer._total_flushed >= 3


@pytest.mark.asyncio
async def test_periodic_flush_cancellation(mock_asyncpg_pool: MagicMock) -> None:
    """Cancelling the periodic flush task should not raise an unhandled exception."""
    buffer = _make_buffer(mock_asyncpg_pool, flush_interval=10.0, max_size=100)

    task = asyncio.create_task(buffer.start_periodic_flush())
    await asyncio.sleep(0.01)
    task.cancel()

    # Should complete cleanly via CancelledError handling inside the method
    await asyncio.wait_for(asyncio.shield(task), timeout=1.0)


# ---------------------------------------------------------------------------
# total_flushed counter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_total_flushed_accumulates_across_flushes(mock_asyncpg_pool: MagicMock) -> None:
    """_total_flushed should accumulate across multiple successful flushes."""
    buffer = _make_buffer(mock_asyncpg_pool, max_size=100)

    for i in range(4):
        await buffer.add(make_tick(trade_id=i))
    await buffer.flush()

    for i in range(6):
        await buffer.add(make_tick(trade_id=100 + i))
    await buffer.flush()

    assert buffer._total_flushed == 10
