"""Integration tests for the price ingestion flow.

These tests wire together the real PriceCache, TickBuffer, PriceBroadcaster,
and a simulated BinanceWebSocketClient tick stream — all backed by mock
infrastructure (Redis + asyncpg pool) so no live services are required.

Test scenarios:
1. Tick processed through the ingestion loop updates Redis price cache.
2. Tick processed through the ingestion loop queues a DB insert via TickBuffer.
3. Tick processed through the ingestion loop publishes to Redis pub/sub channel.
4. Multiple ticks for the same symbol update ticker stats (open preserved).
5. Buffer retains ticks on flush failure; next flush retries successfully.
6. Broadcaster serialises tick fields correctly (JSON format check).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest

from src.cache.price_cache import PriceCache, Tick
from src.price_ingestion.broadcaster import PriceBroadcaster
from src.price_ingestion.tick_buffer import TickBuffer
from tests.conftest import make_tick


# ---------------------------------------------------------------------------
# Minimal ingestion pipeline helper
# ---------------------------------------------------------------------------


async def _process_tick(
    tick: Tick,
    price_cache: PriceCache,
    tick_buffer: TickBuffer,
    broadcaster: PriceBroadcaster,
) -> None:
    """Replicate the hot path from service.run() for a single tick.

    This mirrors the four operations performed inside the ingestion service
    main loop so tests exercise the integration of those components without
    starting a full service process.
    """
    await price_cache.set_price(tick.symbol, tick.price, tick.timestamp)
    await price_cache.update_ticker(tick)
    await tick_buffer.add(tick)
    await broadcaster.broadcast(tick)


# ---------------------------------------------------------------------------
# Test 1: Redis price cache is updated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_updates_redis_price(mock_redis: AsyncMock, mock_asyncpg_pool: MagicMock) -> None:
    """Processing a tick should store the current price in Redis."""
    price_cache = PriceCache(mock_redis)
    tick_buffer = TickBuffer(mock_asyncpg_pool, flush_interval=10.0, max_size=100)
    broadcaster = PriceBroadcaster(mock_redis)

    tick = make_tick("BTCUSDT", "64521.30", "0.01")
    await _process_tick(tick, price_cache, tick_buffer, broadcaster)

    pipe = mock_redis.pipeline.return_value.__aenter__.return_value
    pipe.hset.assert_any_call("prices", "BTCUSDT", "64521.30")


# ---------------------------------------------------------------------------
# Test 2: Tick is buffered for DB insert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_buffered_for_db_insert(mock_redis: AsyncMock, mock_asyncpg_pool: MagicMock) -> None:
    """Processing a tick should add it to the TickBuffer (no flush until threshold)."""
    price_cache = PriceCache(mock_redis)
    tick_buffer = TickBuffer(mock_asyncpg_pool, flush_interval=10.0, max_size=100)
    broadcaster = PriceBroadcaster(mock_redis)

    tick = make_tick("ETHUSDT", "3400.00", "0.50")
    await _process_tick(tick, price_cache, tick_buffer, broadcaster)

    assert len(tick_buffer._buffer) == 1
    assert tick_buffer._buffer[0].symbol == "ETHUSDT"
    mock_asyncpg_pool.acquire.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: Tick is published to pub/sub channel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_published_to_pubsub(mock_redis: AsyncMock, mock_asyncpg_pool: MagicMock) -> None:
    """Processing a tick should publish a JSON message to 'price_updates'."""
    price_cache = PriceCache(mock_redis)
    tick_buffer = TickBuffer(mock_asyncpg_pool, flush_interval=10.0, max_size=100)
    broadcaster = PriceBroadcaster(mock_redis)

    tick = make_tick("BNBUSDT", "400.00", "1.00", trade_id=99)
    await _process_tick(tick, price_cache, tick_buffer, broadcaster)

    mock_redis.publish.assert_awaited_once()
    channel, message = mock_redis.publish.call_args.args
    assert channel == "price_updates"

    payload = json.loads(message)
    assert payload["symbol"] == "BNBUSDT"
    assert payload["price"] == "400.00"
    assert payload["trade_id"] == 99
    assert payload["is_buyer_maker"] is False


# ---------------------------------------------------------------------------
# Test 4: Multiple ticks update ticker correctly (open preserved)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_ticks_ticker_open_preserved(mock_redis: AsyncMock, mock_asyncpg_pool: MagicMock) -> None:
    """After initial tick the 'open' price must not be overwritten by subsequent ticks."""
    price_cache = PriceCache(mock_redis)
    tick_buffer = TickBuffer(mock_asyncpg_pool, flush_interval=10.0, max_size=100)
    broadcaster = PriceBroadcaster(mock_redis)

    ts = datetime(2024, 1, 1, tzinfo=UTC)
    tick1 = make_tick("SOLUSDT", "200.00", "5.00", ts, False, 1)

    # First tick — hgetall returns empty dict (no existing ticker)
    mock_redis.hgetall.return_value = {}
    await _process_tick(tick1, price_cache, tick_buffer, broadcaster)

    # Capture what was written as the initial ticker
    first_hset_call = mock_redis.hset.call_args
    first_mapping = first_hset_call.kwargs.get("mapping") or first_hset_call.kwargs["mapping"]
    assert first_mapping["open"] == "200.00"

    # Second tick at a higher price; existing ticker simulated from first write
    tick2 = make_tick("SOLUSDT", "210.00", "3.00", ts, False, 2)
    mock_redis.hgetall.return_value = {
        "open": "200.00",
        "high": "200.00",
        "low": "200.00",
        "close": "200.00",
        "volume": "5.00",
        "change_pct": "0",
        "last_update": ts.isoformat(),
    }
    mock_redis.hset.reset_mock()
    await _process_tick(tick2, price_cache, tick_buffer, broadcaster)

    second_hset_call = mock_redis.hset.call_args
    second_mapping = second_hset_call.kwargs.get("mapping") or second_hset_call.kwargs["mapping"]
    # 'open' must NOT be in the update mapping (it stays at 200.00)
    assert "open" not in second_mapping
    assert second_mapping["high"] == "210.00"
    assert second_mapping["close"] == "210.00"


# ---------------------------------------------------------------------------
# Test 5: Buffer flush triggered at max_size
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_buffer_flushes_at_max_size(mock_redis: AsyncMock, mock_asyncpg_pool: MagicMock) -> None:
    """When the buffer reaches max_size all ticks must be written to the DB."""
    price_cache = PriceCache(mock_redis)
    tick_buffer = TickBuffer(mock_asyncpg_pool, flush_interval=60.0, max_size=3)
    broadcaster = PriceBroadcaster(mock_redis)

    for i in range(3):
        tick = make_tick("BTCUSDT", f"{50000 + i}.00", "0.01", trade_id=i)
        await _process_tick(tick, price_cache, tick_buffer, broadcaster)

    conn = mock_asyncpg_pool.acquire.return_value.__aenter__.return_value
    conn.copy_records_to_table.assert_awaited_once()
    assert len(tick_buffer._buffer) == 0
    assert tick_buffer._total_flushed == 3


# ---------------------------------------------------------------------------
# Test 6: Buffer retained on flush failure; retried next cycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_buffer_retained_then_retried(mock_redis: AsyncMock, mock_asyncpg_pool: MagicMock) -> None:
    """Ticks retained after a flush failure must be written on the next flush attempt."""
    conn = mock_asyncpg_pool.acquire.return_value.__aenter__.return_value
    conn.copy_records_to_table = AsyncMock(
        side_effect=[asyncpg.PostgresError("temp failure"), None]
    )

    price_cache = PriceCache(mock_redis)
    tick_buffer = TickBuffer(mock_asyncpg_pool, flush_interval=60.0, max_size=100)
    broadcaster = PriceBroadcaster(mock_redis)

    for i in range(2):
        tick = make_tick("ETHUSDT", "3400.00", "0.10", trade_id=i)
        await _process_tick(tick, price_cache, tick_buffer, broadcaster)

    # First flush attempt fails
    count_fail = await tick_buffer.flush()
    assert count_fail == 0
    assert len(tick_buffer._buffer) == 2

    # Second flush attempt succeeds
    count_ok = await tick_buffer.flush()
    assert count_ok == 2
    assert len(tick_buffer._buffer) == 0


# ---------------------------------------------------------------------------
# Test 7: Broadcaster serialises tick fields correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcaster_message_format(mock_redis: AsyncMock, mock_asyncpg_pool: MagicMock) -> None:
    """Broadcast message must include all required JSON fields with correct types."""
    broadcaster = PriceBroadcaster(mock_redis)
    ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    tick = make_tick("ADAUSDT", "0.55000000", "1000.00", ts, True, 555)

    await broadcaster.broadcast(tick)

    channel, raw_msg = mock_redis.publish.call_args.args
    payload = json.loads(raw_msg)

    assert payload["symbol"] == "ADAUSDT"
    assert payload["price"] == "0.55000000"
    assert payload["quantity"] == "1000.00"
    assert payload["is_buyer_maker"] is True
    assert payload["trade_id"] == 555
    assert isinstance(payload["timestamp"], int)
    # Timestamp should be millisecond epoch
    expected_ms = int(ts.timestamp() * 1000)
    assert payload["timestamp"] == expected_ms


# ---------------------------------------------------------------------------
# Test 8: Broadcast batch publishes multiple ticks in one pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_broadcaster_batch_uses_pipeline(mock_redis: AsyncMock) -> None:
    """broadcast_batch should publish all ticks via a single Redis pipeline."""
    broadcaster = PriceBroadcaster(mock_redis)
    ticks = [make_tick(trade_id=i) for i in range(5)]

    await broadcaster.broadcast_batch(ticks)

    pipe = mock_redis.pipeline.return_value.__aenter__.return_value
    pipe.execute.assert_awaited_once()
    assert pipe.publish.call_count == 5


@pytest.mark.asyncio
async def test_broadcaster_batch_empty_is_noop(mock_redis: AsyncMock) -> None:
    """broadcast_batch with an empty list should not touch Redis."""
    broadcaster = PriceBroadcaster(mock_redis)

    await broadcaster.broadcast_batch([])

    mock_redis.pipeline.assert_not_called()


# ---------------------------------------------------------------------------
# Test 9: Full pipeline — N ticks flow through all components
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_pipeline_n_ticks(mock_redis: AsyncMock, mock_asyncpg_pool: MagicMock) -> None:
    """N ticks should update Redis, accumulate in the buffer, and publish to pub/sub."""
    price_cache = PriceCache(mock_redis)
    tick_buffer = TickBuffer(mock_asyncpg_pool, flush_interval=60.0, max_size=100)
    broadcaster = PriceBroadcaster(mock_redis)

    n = 10
    for i in range(n):
        tick = make_tick("BTCUSDT", f"{60000 + i}.00", "0.001", trade_id=i)
        await _process_tick(tick, price_cache, tick_buffer, broadcaster)

    # All ticks are in the buffer (max_size not reached)
    assert len(tick_buffer._buffer) == n

    # Price cache pipeline was called n times (once per tick)
    pipe = mock_redis.pipeline.return_value.__aenter__.return_value
    assert pipe.execute.await_count == n

    # publish was called n times (once per tick via broadcast)
    assert mock_redis.publish.await_count == n
