"""Unit tests for src/cache/redis_client.py — Redis connection pool wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.cache.redis_client import RedisClient


class TestRedisClient:
    async def test_connect_creates_pool_and_pings(self):
        client = RedisClient("redis://localhost:6379/0")
        with (
            patch("src.cache.redis_client.ConnectionPool") as mock_pool_cls,
            patch("src.cache.redis_client.aioredis.Redis") as mock_redis_cls,
        ):
            mock_pool = MagicMock()
            mock_pool_cls.from_url.return_value = mock_pool
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_redis_cls.return_value = mock_redis

            await client.connect()

            mock_pool_cls.from_url.assert_called_once()
            mock_redis.ping.assert_called_once()

    async def test_connect_failure_cleans_up(self):
        client = RedisClient("redis://localhost:6379/0")
        with (
            patch("src.cache.redis_client.ConnectionPool") as mock_pool_cls,
            patch("src.cache.redis_client.aioredis.Redis") as mock_redis_cls,
        ):
            mock_pool = MagicMock()
            mock_pool_cls.from_url.return_value = mock_pool
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(side_effect=ConnectionError("fail"))
            mock_redis.aclose = AsyncMock()
            mock_redis_cls.return_value = mock_redis

            with pytest.raises(ConnectionError):
                await client.connect()

            # disconnect should have been called, cleaning up
            assert client._redis is None

    async def test_disconnect_closes_redis(self):
        client = RedisClient("redis://localhost:6379/0")
        mock_redis = AsyncMock()
        client._redis = mock_redis
        client._pool = MagicMock()

        await client.disconnect()

        mock_redis.aclose.assert_called_once()
        assert client._redis is None
        assert client._pool is None

    async def test_disconnect_idempotent(self):
        client = RedisClient("redis://localhost:6379/0")
        # Should not raise when already disconnected
        await client.disconnect()
        await client.disconnect()

    def test_get_client_before_connect_raises(self):
        client = RedisClient("redis://localhost:6379/0")
        with pytest.raises(RuntimeError, match="not connected"):
            client.get_client()

    def test_get_client_after_connect(self):
        client = RedisClient("redis://localhost:6379/0")
        mock_redis = MagicMock()
        client._redis = mock_redis
        assert client.get_client() is mock_redis

    async def test_ping_success(self):
        client = RedisClient("redis://localhost:6379/0")
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        client._redis = mock_redis

        assert await client.ping() is True

    async def test_ping_failure(self):
        from redis.exceptions import RedisError

        client = RedisClient("redis://localhost:6379/0")
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=RedisError("fail"))
        client._redis = mock_redis

        assert await client.ping() is False
