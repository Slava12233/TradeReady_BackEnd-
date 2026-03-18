"""Unit tests for the Price Ingestion Service.

Tests that the service correctly initializes dependencies, processes ticks,
handles errors, and shuts down cleanly.

After the CCXT migration, ``service.py`` no longer imports
``BinanceWebSocketClient`` at module level — tick source creation is delegated
to ``_create_tick_source()``.  Tests patch that function to inject a mock
tick generator, keeping them independent of CCXT availability.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cache.types import Tick


def _make_tick(symbol="BTCUSDT", price="50000.00", quantity="0.01") -> Tick:
    """Create a Tick for testing."""
    return Tick(
        symbol=symbol,
        price=Decimal(price),
        quantity=Decimal(quantity),
        timestamp=datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC),
        is_buyer_maker=False,
        trade_id=123456,
    )


def _mock_tick_source(ticks: list[Tick], pairs: list[str] | None = None):
    """Create a mock return value for ``_create_tick_source``.

    Returns a tuple of (async_generator, pair_list, mock_client) matching
    the real function's signature.
    """

    async def _gen():
        for t in ticks:
            yield t

    mock_client = MagicMock()
    mock_client.close = AsyncMock()
    return _gen(), pairs or [t.symbol for t in ticks], mock_client


class TestServiceRun:
    @patch("src.price_ingestion.service.close_db", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.init_db", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.get_asyncpg_pool", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.RedisClient")
    @patch("src.price_ingestion.service.PriceCache")
    @patch("src.price_ingestion.service.PriceBroadcaster")
    @patch("src.price_ingestion.service.TickBuffer")
    @patch("src.price_ingestion.service._create_tick_source", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.get_settings")
    async def test_service_initializes_dependencies(
        self,
        mock_settings,
        mock_create_source,
        mock_buffer_cls,
        mock_broadcaster_cls,
        mock_cache_cls,
        mock_redis_cls,
        mock_get_pool,
        mock_init_db,
        mock_close_db,
    ) -> None:
        """run() creates tick source, cache, buffer, and broadcaster."""
        from src.price_ingestion import service

        settings = MagicMock()
        settings.exchange_id = "binance"
        settings.tick_flush_interval = 1.0
        settings.tick_buffer_max_size = 100
        settings.redis_url = "redis://localhost:6379"
        settings.binance_ws_url = "wss://stream.binance.com"
        mock_settings.return_value = settings

        mock_redis_instance = MagicMock()
        mock_redis_instance.connect = AsyncMock()
        mock_redis_instance.get_client = MagicMock(return_value=AsyncMock())
        mock_redis_instance.disconnect = AsyncMock()
        mock_redis_cls.return_value = mock_redis_instance

        tick = _make_tick()
        mock_create_source.return_value = _mock_tick_source([tick])

        mock_buffer = MagicMock()
        mock_buffer.add = AsyncMock()
        mock_buffer.shutdown = AsyncMock()
        mock_buffer.start_periodic_flush = AsyncMock()
        mock_buffer_cls.return_value = mock_buffer

        mock_cache = MagicMock()
        mock_cache.set_price = AsyncMock()
        mock_cache.update_ticker = AsyncMock()
        mock_cache_cls.return_value = mock_cache

        original = service._shutdown_requested
        service._shutdown_requested = False

        try:
            await service.run()
        finally:
            service._shutdown_requested = original

        # Verify dependencies were initialized
        mock_init_db.assert_awaited_once()
        mock_get_pool.assert_awaited_once()
        mock_redis_instance.connect.assert_awaited_once()
        mock_create_source.assert_awaited_once()

    @patch("src.price_ingestion.service.close_db", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.init_db", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.get_asyncpg_pool", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.RedisClient")
    @patch("src.price_ingestion.service.PriceCache")
    @patch("src.price_ingestion.service.PriceBroadcaster")
    @patch("src.price_ingestion.service.TickBuffer")
    @patch("src.price_ingestion.service._create_tick_source", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.get_settings")
    async def test_processes_tick_message(
        self,
        mock_settings,
        mock_create_source,
        mock_buffer_cls,
        mock_broadcaster_cls,
        mock_cache_cls,
        mock_redis_cls,
        mock_get_pool,
        mock_init_db,
        mock_close_db,
    ) -> None:
        """Incoming tick triggers cache update + buffer append."""
        from src.price_ingestion import service

        settings = MagicMock()
        settings.exchange_id = "binance"
        settings.tick_flush_interval = 1.0
        settings.tick_buffer_max_size = 100
        settings.redis_url = "redis://localhost:6379"
        settings.binance_ws_url = "wss://stream.binance.com"
        mock_settings.return_value = settings

        mock_redis_instance = MagicMock()
        mock_redis_instance.connect = AsyncMock()
        mock_redis_instance.get_client = MagicMock(return_value=AsyncMock())
        mock_redis_instance.disconnect = AsyncMock()
        mock_redis_cls.return_value = mock_redis_instance

        tick = _make_tick()
        mock_create_source.return_value = _mock_tick_source([tick])

        mock_buffer = MagicMock()
        mock_buffer.add = AsyncMock()
        mock_buffer.shutdown = AsyncMock()
        mock_buffer.start_periodic_flush = AsyncMock()
        mock_buffer_cls.return_value = mock_buffer

        mock_cache = MagicMock()
        mock_cache.set_price = AsyncMock()
        mock_cache.update_ticker = AsyncMock()
        mock_cache_cls.return_value = mock_cache

        original = service._shutdown_requested
        service._shutdown_requested = False
        try:
            await service.run()
        finally:
            service._shutdown_requested = original

        # Verify tick was processed: cache updated and buffer received tick
        mock_cache.set_price.assert_awaited_once_with(tick.symbol, tick.price, tick.timestamp)
        mock_cache.update_ticker.assert_awaited_once_with(tick)
        mock_buffer.add.assert_awaited_once_with(tick)

    @patch("src.price_ingestion.service.close_db", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.init_db", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.get_asyncpg_pool", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.RedisClient")
    @patch("src.price_ingestion.service.PriceCache")
    @patch("src.price_ingestion.service.PriceBroadcaster")
    @patch("src.price_ingestion.service.TickBuffer")
    @patch("src.price_ingestion.service._create_tick_source", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.get_settings")
    async def test_shutdown_flushes_buffer(
        self,
        mock_settings,
        mock_create_source,
        mock_buffer_cls,
        mock_broadcaster_cls,
        mock_cache_cls,
        mock_redis_cls,
        mock_get_pool,
        mock_init_db,
        mock_close_db,
    ) -> None:
        """Shutdown calls buffer.shutdown() to flush pending ticks."""
        from src.price_ingestion import service

        settings = MagicMock()
        settings.exchange_id = "binance"
        settings.tick_flush_interval = 1.0
        settings.tick_buffer_max_size = 100
        settings.redis_url = "redis://localhost:6379"
        settings.binance_ws_url = "wss://stream.binance.com"
        mock_settings.return_value = settings

        mock_redis_instance = MagicMock()
        mock_redis_instance.connect = AsyncMock()
        mock_redis_instance.get_client = MagicMock(return_value=AsyncMock())
        mock_redis_instance.disconnect = AsyncMock()
        mock_redis_cls.return_value = mock_redis_instance

        mock_create_source.return_value = _mock_tick_source([], pairs=[])

        mock_buffer = MagicMock()
        mock_buffer.add = AsyncMock()
        mock_buffer.shutdown = AsyncMock()
        mock_buffer.start_periodic_flush = AsyncMock()
        mock_buffer_cls.return_value = mock_buffer

        mock_cache = MagicMock()
        mock_cache_cls.return_value = mock_cache

        original = service._shutdown_requested
        service._shutdown_requested = False
        try:
            await service.run()
        finally:
            service._shutdown_requested = original

        mock_buffer.shutdown.assert_awaited_once()

    @patch("src.price_ingestion.service.close_db", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.init_db", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.get_asyncpg_pool", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.RedisClient")
    @patch("src.price_ingestion.service.PriceCache")
    @patch("src.price_ingestion.service.PriceBroadcaster")
    @patch("src.price_ingestion.service.TickBuffer")
    @patch("src.price_ingestion.service._create_tick_source", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.get_settings")
    async def test_shutdown_closes_connections(
        self,
        mock_settings,
        mock_create_source,
        mock_buffer_cls,
        mock_broadcaster_cls,
        mock_cache_cls,
        mock_redis_cls,
        mock_get_pool,
        mock_init_db,
        mock_close_db,
    ) -> None:
        """Shutdown closes Redis and DB connections cleanly."""
        from src.price_ingestion import service

        settings = MagicMock()
        settings.exchange_id = "binance"
        settings.tick_flush_interval = 1.0
        settings.tick_buffer_max_size = 100
        settings.redis_url = "redis://localhost:6379"
        settings.binance_ws_url = "wss://stream.binance.com"
        mock_settings.return_value = settings

        mock_redis_instance = MagicMock()
        mock_redis_instance.connect = AsyncMock()
        mock_redis_instance.get_client = MagicMock(return_value=AsyncMock())
        mock_redis_instance.disconnect = AsyncMock()
        mock_redis_cls.return_value = mock_redis_instance

        mock_create_source.return_value = _mock_tick_source([], pairs=[])

        mock_buffer = MagicMock()
        mock_buffer.shutdown = AsyncMock()
        mock_buffer.start_periodic_flush = AsyncMock()
        mock_buffer_cls.return_value = mock_buffer

        mock_cache = MagicMock()
        mock_cache_cls.return_value = mock_cache

        original = service._shutdown_requested
        service._shutdown_requested = False
        try:
            await service.run()
        finally:
            service._shutdown_requested = original

        mock_redis_instance.disconnect.assert_awaited_once()
        mock_close_db.assert_awaited_once()

    @patch("src.price_ingestion.service.close_db", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.init_db", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.get_asyncpg_pool", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.RedisClient")
    @patch("src.price_ingestion.service.PriceCache")
    @patch("src.price_ingestion.service.PriceBroadcaster")
    @patch("src.price_ingestion.service.TickBuffer")
    @patch("src.price_ingestion.service._create_tick_source", new_callable=AsyncMock)
    @patch("src.price_ingestion.service.get_settings")
    async def test_handles_fatal_error_in_loop(
        self,
        mock_settings,
        mock_create_source,
        mock_buffer_cls,
        mock_broadcaster_cls,
        mock_cache_cls,
        mock_redis_cls,
        mock_get_pool,
        mock_init_db,
        mock_close_db,
    ) -> None:
        """Fatal error in ingestion loop still runs cleanup, then re-raises."""
        from src.price_ingestion import service

        settings = MagicMock()
        settings.exchange_id = "binance"
        settings.tick_flush_interval = 1.0
        settings.tick_buffer_max_size = 100
        settings.redis_url = "redis://localhost:6379"
        settings.binance_ws_url = "wss://stream.binance.com"
        mock_settings.return_value = settings

        mock_redis_instance = MagicMock()
        mock_redis_instance.connect = AsyncMock()
        mock_redis_instance.get_client = MagicMock(return_value=AsyncMock())
        mock_redis_instance.disconnect = AsyncMock()
        mock_redis_cls.return_value = mock_redis_instance

        tick = _make_tick()

        async def _exploding_gen():
            yield tick
            raise RuntimeError("Connection exploded")

        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        mock_create_source.return_value = (_exploding_gen(), ["BTCUSDT"], mock_client)

        mock_buffer = MagicMock()
        mock_buffer.add = AsyncMock()
        mock_buffer.shutdown = AsyncMock()
        mock_buffer.start_periodic_flush = AsyncMock()
        mock_buffer_cls.return_value = mock_buffer

        mock_cache = MagicMock()
        mock_cache.set_price = AsyncMock()
        mock_cache.update_ticker = AsyncMock()
        mock_cache_cls.return_value = mock_cache

        original = service._shutdown_requested
        service._shutdown_requested = False
        try:
            with pytest.raises(RuntimeError, match="Connection exploded"):
                await service.run()
        finally:
            service._shutdown_requested = original

        # Cleanup still ran despite the error
        mock_buffer.shutdown.assert_awaited_once()
        mock_redis_instance.disconnect.assert_awaited_once()
        mock_close_db.assert_awaited_once()


class TestSignalHandler:
    def test_request_shutdown_sets_flag(self) -> None:
        """_request_shutdown sets the module-level flag."""
        import signal as signal_mod

        import src.price_ingestion.service as svc
        from src.price_ingestion.service import _request_shutdown

        original = svc._shutdown_requested
        try:
            svc._shutdown_requested = False
            _request_shutdown(signal_mod.SIGINT, None)
            assert svc._shutdown_requested is True
        finally:
            svc._shutdown_requested = original
