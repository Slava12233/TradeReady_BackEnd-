"""Tests for agent/memory/redis_cache.py :: RedisMemoryCache."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from redis.exceptions import RedisError

from agent.config import AgentConfig
from agent.memory.redis_cache import (
    RedisMemoryCache,
    _working_key,
)
from agent.memory.store import Memory, MemoryType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _make_memory(
    agent_id: str | None = None,
    memory_type: MemoryType = MemoryType.EPISODIC,
    content: str = "BTC regime trending upward.",
    confidence: str = "0.9000",
) -> Memory:
    now = datetime(2026, 3, 20, 10, 0, 0, tzinfo=UTC)
    return Memory(
        id=str(uuid4()),
        agent_id=agent_id or str(uuid4()),
        memory_type=memory_type,
        content=content,
        source="test",
        confidence=Decimal(confidence),
        times_reinforced=1,
        created_at=now,
        last_accessed_at=now,
    )


def _make_mock_redis() -> AsyncMock:
    """Return a fully-wired mock redis.asyncio.Redis instance."""
    mock = AsyncMock()

    # Pipeline context manager
    mock_pipe = MagicMock()
    mock_pipe.set = MagicMock()
    mock_pipe.zadd = MagicMock()
    mock_pipe.zremrangebyrank = MagicMock()
    mock_pipe.delete = MagicMock()
    mock_pipe.zrem = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[True, 1, 0])
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)
    mock.pipeline = MagicMock(return_value=mock_pipe)

    return mock


def _make_cache(monkeypatch: pytest.MonkeyPatch, mock_redis: AsyncMock | None = None) -> tuple:
    """Return (cache, mock_redis, config)."""
    config = _make_config(monkeypatch)
    redis = mock_redis or _make_mock_redis()
    cache = RedisMemoryCache(config=config, redis=redis)
    return cache, redis, config


# ---------------------------------------------------------------------------
# TestGetCachedForAgent
# ---------------------------------------------------------------------------


class TestGetCachedForAgent:
    """Tests for RedisMemoryCache.get_cached_for_agent()."""

    async def test_hit_returns_deserialized_memory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_cached_for_agent() returns a Memory on a cache hit."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mem = _make_memory()

        from agent.memory.redis_cache import _memory_to_json

        mock_redis.get.return_value = _memory_to_json(mem)
        mock_redis.zadd.return_value = 1

        result = await cache.get_cached_for_agent(mem.agent_id, mem.id)

        assert result is not None
        assert result.id == mem.id
        assert result.content == mem.content

    async def test_miss_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_cached_for_agent() returns None when the key is absent."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mock_redis.get.return_value = None

        result = await cache.get_cached_for_agent(str(uuid4()), str(uuid4()))

        assert result is None

    async def test_redis_error_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_cached_for_agent() swallows RedisError and returns None."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mock_redis.get.side_effect = RedisError("connection refused")

        result = await cache.get_cached_for_agent(str(uuid4()), str(uuid4()))

        assert result is None

    async def test_corrupt_json_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_cached_for_agent() swallows deserialization errors and returns None."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mock_redis.get.return_value = "this is not valid json {"

        result = await cache.get_cached_for_agent(str(uuid4()), str(uuid4()))

        assert result is None


# ---------------------------------------------------------------------------
# TestCacheMemory
# ---------------------------------------------------------------------------


class TestCacheMemory:
    """Tests for RedisMemoryCache.cache_memory()."""

    async def test_cache_memory_stores_via_pipeline(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cache_memory() uses a Redis pipeline to write the key and update the sorted set."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mem = _make_memory()

        await cache.cache_memory(mem)

        mock_redis.pipeline.assert_called_once()
        pipe = mock_redis.pipeline.return_value.__aenter__.return_value
        pipe.set.assert_called_once()
        pipe.zadd.assert_called_once()
        pipe.zremrangebyrank.assert_called_once()
        pipe.execute.assert_called_once()

    async def test_cache_memory_uses_custom_ttl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cache_memory() forwards the custom ttl to the pipeline set command."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mem = _make_memory()

        await cache.cache_memory(mem, ttl=300)

        pipe = mock_redis.pipeline.return_value.__aenter__.return_value
        # First call to pipe.set should have ex=300
        args, kwargs = pipe.set.call_args
        assert kwargs.get("ex") == 300 or (len(args) > 2 and args[2] == 300)

    async def test_cache_memory_uses_config_ttl_when_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cache_memory() uses config.memory_cache_ttl when ttl is not provided."""
        cache, mock_redis, config = _make_cache(monkeypatch)
        mem = _make_memory()

        await cache.cache_memory(mem)

        pipe = mock_redis.pipeline.return_value.__aenter__.return_value
        args, kwargs = pipe.set.call_args
        assert kwargs.get("ex") == config.memory_cache_ttl

    async def test_cache_memory_swallows_redis_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """cache_memory() does NOT raise when Redis is unavailable."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        pipe = mock_redis.pipeline.return_value.__aenter__.return_value
        pipe.execute.side_effect = RedisError("timeout")

        # Should not raise; Redis failures are swallowed.
        await cache.cache_memory(_make_memory())


# ---------------------------------------------------------------------------
# TestInvalidate
# ---------------------------------------------------------------------------


class TestInvalidate:
    """Tests for RedisMemoryCache.invalidate()."""

    async def test_invalidate_deletes_key_and_removes_from_sorted_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """invalidate() issues delete and zrem via a pipeline."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        agent_id = str(uuid4())
        memory_id = str(uuid4())

        await cache.invalidate(memory_id=memory_id, agent_id=agent_id)

        pipe = mock_redis.pipeline.return_value.__aenter__.return_value
        pipe.delete.assert_called_once()
        pipe.zrem.assert_called_once()

    async def test_invalidate_swallows_redis_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """invalidate() does not raise on Redis failure."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        pipe = mock_redis.pipeline.return_value.__aenter__.return_value
        pipe.execute.side_effect = RedisError("offline")

        await cache.invalidate(memory_id=str(uuid4()), agent_id=str(uuid4()))


# ---------------------------------------------------------------------------
# TestGetRecentIds
# ---------------------------------------------------------------------------


class TestGetRecentIds:
    """Tests for RedisMemoryCache.get_recent_ids()."""

    async def test_returns_ids_from_sorted_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_recent_ids() returns the list of memory IDs from the sorted set."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        expected_ids = [str(uuid4()), str(uuid4())]
        mock_redis.zrevrange.return_value = expected_ids

        result = await cache.get_recent_ids(agent_id=str(uuid4()))

        assert result == expected_ids

    async def test_returns_empty_list_on_redis_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_recent_ids() returns [] on Redis failure."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mock_redis.zrevrange.side_effect = RedisError("down")

        result = await cache.get_recent_ids(agent_id=str(uuid4()))

        assert result == []


# ---------------------------------------------------------------------------
# TestWorkingMemory
# ---------------------------------------------------------------------------


class TestWorkingMemory:
    """Tests for set_working / get_working / get_all_working / clear_working."""

    async def test_set_and_get_working_memory(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """set_working() stores a value; get_working() retrieves it via hset/hget."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        agent_id = str(uuid4())
        mock_redis.hget.return_value = "BUY"

        await cache.set_working(agent_id, "last_action", "BUY")
        result = await cache.get_working(agent_id, "last_action")

        mock_redis.hset.assert_called_once_with(_working_key(agent_id), "last_action", "BUY")
        mock_redis.hget.assert_called_once_with(_working_key(agent_id), "last_action")
        assert result == "BUY"

    async def test_get_working_returns_none_on_miss(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_working() returns None when the key is absent."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mock_redis.hget.return_value = None

        result = await cache.get_working(str(uuid4()), "missing_key")

        assert result is None

    async def test_set_working_swallows_redis_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """set_working() does not raise on Redis failure."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mock_redis.hset.side_effect = RedisError("conn refused")

        await cache.set_working(str(uuid4()), "key", "value")

    async def test_get_all_working_returns_full_hash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_all_working() returns the full hash dict from Redis."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        expected = {"action": "SELL", "symbol": "ETHUSDT"}
        mock_redis.hgetall.return_value = expected

        result = await cache.get_all_working(str(uuid4()))

        assert result == expected

    async def test_get_all_working_returns_empty_on_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_all_working() returns {} on Redis failure."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mock_redis.hgetall.side_effect = RedisError("down")

        result = await cache.get_all_working(str(uuid4()))

        assert result == {}

    async def test_clear_working_deletes_hash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """clear_working() calls redis.delete() on the working memory key."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        agent_id = str(uuid4())

        await cache.clear_working(agent_id)

        mock_redis.delete.assert_called_once_with(_working_key(agent_id))


# ---------------------------------------------------------------------------
# TestHotState
# ---------------------------------------------------------------------------


class TestHotState:
    """Tests for set_regime / get_regime / set_signals / get_signals."""

    async def test_set_regime_stores_value_with_ttl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """set_regime() calls redis.set() with the regime label and TTL."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        agent_id = str(uuid4())

        await cache.set_regime(agent_id, "TRENDING")

        mock_redis.set.assert_called_once()
        args, kwargs = mock_redis.set.call_args
        assert "TRENDING" in args or "TRENDING" in kwargs.values()
        assert kwargs.get("ex") is not None

    async def test_get_regime_returns_label(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_regime() deserializes and returns the stored regime label."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mock_redis.get.return_value = "SIDEWAYS"

        result = await cache.get_regime(str(uuid4()))

        assert result == "SIDEWAYS"

    async def test_get_regime_returns_none_on_miss(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_regime() returns None when no regime is stored."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mock_redis.get.return_value = None

        result = await cache.get_regime(str(uuid4()))

        assert result is None

    async def test_get_regime_returns_none_on_redis_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_regime() swallows RedisError and returns None."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mock_redis.get.side_effect = RedisError("connection lost")

        result = await cache.get_regime(str(uuid4()))

        assert result is None

    async def test_set_signals_serialises_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """set_signals() serialises the signals dict to JSON before storing."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        agent_id = str(uuid4())
        signals = {"BTCUSDT": "buy", "ETHUSDT": "hold"}

        await cache.set_signals(agent_id, signals)

        mock_redis.set.assert_called_once()
        args, _ = mock_redis.set.call_args
        stored_payload = args[1]
        assert json.loads(stored_payload) == signals

    async def test_get_signals_deserialises_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_signals() deserializes and returns the stored dict."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        signals = {"BTCUSDT": "sell"}
        mock_redis.get.return_value = json.dumps(signals)

        result = await cache.get_signals(str(uuid4()))

        assert result == signals

    async def test_get_signals_returns_none_on_corrupt_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """get_signals() returns None when the stored value is not valid JSON."""
        cache, mock_redis, _ = _make_cache(monkeypatch)
        mock_redis.get.return_value = "{corrupt json"

        result = await cache.get_signals(str(uuid4()))

        assert result is None
