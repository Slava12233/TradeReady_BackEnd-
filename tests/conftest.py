"""Shared pytest fixtures for unit and integration tests.

Provides:
- ``mock_asyncpg_pool`` — mock asyncpg connection pool for TickBuffer tests.
- ``mock_redis`` — mock redis.asyncio.Redis instance for PriceCache tests.
- ``sample_tick`` / ``sample_ticks`` — pre-built Tick namedtuples.
- ``test_settings`` — Settings with safe defaults for tests (no real services).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.cache.price_cache import Tick


# ---------------------------------------------------------------------------
# pytest-asyncio configuration
# ---------------------------------------------------------------------------

pytest_plugins = ("pytest_asyncio",)


# ---------------------------------------------------------------------------
# Settings fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_settings():
    """Return a Settings instance with test-safe values (no real infra needed).

    Uses ``patch`` so the lru_cache on ``get_settings`` is bypassed.

    Example::

        def test_something(test_settings):
            assert test_settings.tick_buffer_max_size == 100
    """
    with patch("src.config.get_settings") as mock_get_settings:
        from src.config import Settings

        settings = Settings(
            jwt_secret="test_secret_that_is_at_least_32_characters_long",
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            redis_url="redis://localhost:6379/15",
            tick_flush_interval=1.0,
            tick_buffer_max_size=100,
        )
        mock_get_settings.return_value = settings
        yield settings


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


def make_tick(
    symbol: str = "BTCUSDT",
    price: str = "64521.30",
    quantity: str = "0.01200000",
    timestamp: datetime | None = None,
    is_buyer_maker: bool = False,
    trade_id: int = 123456789,
) -> Tick:
    """Factory function that returns a :class:`~src.cache.price_cache.Tick`.

    Args:
        symbol: Trading pair symbol.
        price: Price as a decimal string.
        quantity: Quantity as a decimal string.
        timestamp: UTC datetime; defaults to current UTC time.
        is_buyer_maker: Whether the buyer is the maker.
        trade_id: Binance trade ID integer.

    Returns:
        A fully populated :class:`Tick` namedtuple.
    """
    return Tick(
        symbol=symbol,
        price=Decimal(price),
        quantity=Decimal(quantity),
        timestamp=timestamp or datetime.now(UTC),
        is_buyer_maker=is_buyer_maker,
        trade_id=trade_id,
    )


@pytest.fixture()
def sample_tick() -> Tick:
    """Single BTCUSDT tick for use in tests."""
    return make_tick()


@pytest.fixture()
def sample_ticks() -> list[Tick]:
    """List of three ticks across two symbols."""
    ts = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    return [
        make_tick("BTCUSDT", "64000.00", "0.01", ts, False, 1),
        make_tick("ETHUSDT", "3400.00", "0.50", ts, True, 2),
        make_tick("BTCUSDT", "64100.00", "0.02", ts, False, 3),
    ]


# ---------------------------------------------------------------------------
# Mock asyncpg pool
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_asyncpg_pool() -> MagicMock:
    """Return a mock asyncpg Pool whose ``acquire()`` context manager succeeds.

    The inner connection exposes a ``copy_records_to_table`` coroutine mock so
    that :class:`~src.price_ingestion.tick_buffer.TickBuffer` can call it
    without a real database.

    Example::

        async def test_flush(mock_asyncpg_pool):
            buffer = TickBuffer(db_pool=mock_asyncpg_pool)
            ...
    """
    mock_conn = AsyncMock()
    mock_conn.copy_records_to_table = AsyncMock(return_value=None)

    # asyncpg pool.acquire() is used as an async context manager
    mock_acquire = MagicMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=mock_acquire)

    return pool


# ---------------------------------------------------------------------------
# Mock Redis client
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_redis() -> AsyncMock:
    """Return a mock ``redis.asyncio.Redis`` instance.

    All Redis commands (hset, hget, hgetall, publish, pipeline) are
    pre-wired as AsyncMock objects so tests can inspect call arguments
    or inject return values.

    Example::

        async def test_get_price(mock_redis):
            mock_redis.hget.return_value = "64521.30"
            cache = PriceCache(mock_redis)
            price = await cache.get_price("BTCUSDT")
            assert price == Decimal("64521.30")
    """
    redis = AsyncMock()
    redis.hset = AsyncMock(return_value=1)
    redis.hget = AsyncMock(return_value=None)
    redis.hgetall = AsyncMock(return_value={})
    redis.publish = AsyncMock(return_value=1)

    # Pipeline mock — supports async context manager usage.
    # hset/publish are synchronous inside a pipeline (only execute() is awaited).
    mock_pipe = MagicMock()
    mock_pipe.hset = MagicMock()
    mock_pipe.publish = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 1])
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)

    redis.pipeline = MagicMock(return_value=mock_pipe)


    return redis


# ---------------------------------------------------------------------------
# Async event loop
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use the default asyncio event loop policy for the test session."""
    return asyncio.DefaultEventLoopPolicy()
