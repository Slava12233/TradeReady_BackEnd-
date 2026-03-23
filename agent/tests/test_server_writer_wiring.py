"""Tests for LogBatchWriter wiring into AgentServer and log_api_call().

These tests verify:
- AgentServer instantiates LogBatchWriter when the DB is available.
- AgentServer.batch_writer property returns the writer.
- AgentServer._shutdown() calls writer.stop() before closing other resources.
- log_api_call() calls writer.add_api_call() on success and failure when provided.
- writer is None (not passed) when AgentServer has no DB session_factory.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog.testing

from agent.logging_middleware import log_api_call
from agent.logging_writer import LogBatchWriter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory(*, raise_on_commit: bool = False) -> tuple[MagicMock, AsyncMock]:
    """Return (session_factory, mock_session) pair for LogBatchWriter."""
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add_all = MagicMock()
    if raise_on_commit:
        mock_session.commit = AsyncMock(side_effect=RuntimeError("DB error"))
    mock_session_factory = MagicMock(return_value=mock_session)
    return mock_session_factory, mock_session


def _make_writer(max_batch_size: int = 50) -> LogBatchWriter:
    """Return a LogBatchWriter backed by a mock session factory."""
    factory, _ = _make_session_factory()
    return LogBatchWriter(session_factory=factory, max_batch_size=max_batch_size)


# ---------------------------------------------------------------------------
# log_api_call — writer parameter (success path)
# ---------------------------------------------------------------------------


class TestLogApiCallWriterSuccess:
    """Tests for log_api_call() when a writer is provided and the body succeeds."""

    async def test_writer_add_api_call_invoked_on_success(self) -> None:
        """writer.add_api_call() is called once when the body completes without error."""
        writer = _make_writer()
        writer.add_api_call = AsyncMock()

        with structlog.testing.capture_logs():
            async with log_api_call("sdk", "get_price", writer=writer) as ctx:
                ctx["response_status"] = 200

        writer.add_api_call.assert_awaited_once()

    async def test_writer_record_contains_channel(self) -> None:
        """The record passed to add_api_call contains the channel field."""
        writer = _make_writer()
        captured: list[dict] = []
        writer.add_api_call = AsyncMock(side_effect=lambda r: captured.append(r))

        with structlog.testing.capture_logs():
            async with log_api_call("rest", "/api/v1/orders", writer=writer):
                pass

        assert len(captured) == 1
        assert captured[0]["channel"] == "rest"

    async def test_writer_record_contains_endpoint(self) -> None:
        """The record passed to add_api_call contains the endpoint field."""
        writer = _make_writer()
        captured: list[dict] = []
        writer.add_api_call = AsyncMock(side_effect=lambda r: captured.append(r))

        with structlog.testing.capture_logs():
            async with log_api_call("sdk", "place_order", writer=writer):
                pass

        assert captured[0]["endpoint"] == "place_order"

    async def test_writer_record_contains_latency_ms(self) -> None:
        """The record passed to add_api_call includes a latency_ms value."""
        writer = _make_writer()
        captured: list[dict] = []
        writer.add_api_call = AsyncMock(side_effect=lambda r: captured.append(r))

        with structlog.testing.capture_logs():
            async with log_api_call("sdk", "get_balance", writer=writer):
                pass

        assert "latency_ms" in captured[0]
        assert isinstance(captured[0]["latency_ms"], float)

    async def test_writer_record_contains_method(self) -> None:
        """The record includes the method field when provided."""
        writer = _make_writer()
        captured: list[dict] = []
        writer.add_api_call = AsyncMock(side_effect=lambda r: captured.append(r))

        with structlog.testing.capture_logs():
            async with log_api_call("rest", "/api/v1/health", "GET", writer=writer):
                pass

        assert captured[0]["method"] == "GET"

    async def test_writer_error_does_not_propagate(self) -> None:
        """If writer.add_api_call() raises, the error is swallowed — body result unaffected."""
        writer = _make_writer()
        writer.add_api_call = AsyncMock(side_effect=RuntimeError("writer broke"))

        # Must not raise even though the writer fails
        with structlog.testing.capture_logs():
            async with log_api_call("sdk", "get_price", writer=writer) as ctx:
                ctx["response_status"] = 200

    async def test_no_writer_succeeds_without_call(self) -> None:
        """When writer=None (default), log_api_call works normally with no writer call."""
        with structlog.testing.capture_logs() as cap_logs:
            async with log_api_call("sdk", "get_price") as ctx:
                ctx["response_status"] = 200

        assert cap_logs[0]["event"] == "agent.api.completed"


# ---------------------------------------------------------------------------
# log_api_call — writer parameter (failure path)
# ---------------------------------------------------------------------------


class TestLogApiCallWriterFailure:
    """Tests for log_api_call() when the body raises and a writer is provided."""

    async def test_writer_add_api_call_invoked_on_failure(self) -> None:
        """writer.add_api_call() is called even when the body raises an exception."""
        writer = _make_writer()
        writer.add_api_call = AsyncMock()

        with structlog.testing.capture_logs():
            try:
                async with log_api_call("sdk", "place_order", writer=writer):
                    raise ValueError("order rejected")
            except ValueError:
                pass

        writer.add_api_call.assert_awaited_once()

    async def test_writer_failure_record_contains_error_key(self) -> None:
        """The record on failure includes the 'error' field."""
        writer = _make_writer()
        captured: list[dict] = []
        writer.add_api_call = AsyncMock(side_effect=lambda r: captured.append(r))

        with structlog.testing.capture_logs():
            try:
                async with log_api_call("rest", "/api/v1/orders", writer=writer):
                    raise ConnectionError("timeout")
            except ConnectionError:
                pass

        assert "error" in captured[0]

    async def test_exception_still_reraises_when_writer_provided(self) -> None:
        """The original exception is still re-raised even when a writer is provided."""
        writer = _make_writer()
        writer.add_api_call = AsyncMock()

        with structlog.testing.capture_logs():
            with pytest.raises(RuntimeError, match="unexpected"):
                async with log_api_call("sdk", "get_candles", writer=writer):
                    raise RuntimeError("unexpected")

    async def test_writer_error_on_failure_is_swallowed(self) -> None:
        """If writer.add_api_call() raises on the failure path, it is silently swallowed."""
        writer = _make_writer()
        writer.add_api_call = AsyncMock(side_effect=RuntimeError("writer down"))

        with structlog.testing.capture_logs():
            # The original ValueError should still be raised — writer failure must not mask it
            with pytest.raises(ValueError, match="original error"):
                async with log_api_call("sdk", "get_price", writer=writer):
                    raise ValueError("original error")


# ---------------------------------------------------------------------------
# AgentServer — batch_writer property and shutdown
# ---------------------------------------------------------------------------


class TestAgentServerBatchWriterProperty:
    """Tests for AgentServer.batch_writer property returning the LogBatchWriter."""

    def _make_minimal_server(self) -> tuple:
        """Return (AgentServer instance, mock config)."""
        from agent.server import AgentServer

        config = MagicMock()
        config.agent_server_host = "0.0.0.0"
        config.agent_server_port = 8001
        config.openrouter_api_key = "sk-test"
        config.platform_api_key = ""
        config.agent_model = "openrouter:anthropic/claude-sonnet-4-5"

        with patch("agent.server.set_agent_id"):
            server = AgentServer(agent_id="test-agent-001", config=config)

        return server, config

    def test_batch_writer_initially_none(self) -> None:
        """Before start(), batch_writer is None (not yet initialised)."""
        server, _ = self._make_minimal_server()
        assert server.batch_writer is None

    async def test_batch_writer_set_after_init_dependencies_with_db(self) -> None:
        """After _init_dependencies() with a working DB, batch_writer is a LogBatchWriter."""
        server, _ = self._make_minimal_server()

        mock_engine = MagicMock()
        mock_session_factory = MagicMock()

        # We need the session used inside _init_dependencies to succeed for
        # the connectivity check (async with self._session_factory() as session:)
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = mock_session

        mock_repo = MagicMock()
        mock_memory_store = MagicMock()

        with (
            patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine),
            patch("sqlalchemy.ext.asyncio.async_sessionmaker", return_value=mock_session_factory),
            patch("src.config.get_settings") as mock_get_settings,
            patch(
                "src.database.repositories.agent_learning_repo.AgentLearningRepository",
                return_value=mock_repo,
            ),
            patch("agent.memory.postgres_store.PostgresMemoryStore", return_value=mock_memory_store),
            patch.object(LogBatchWriter, "start", new_callable=AsyncMock),
        ):
            mock_settings = MagicMock()
            mock_settings.database_url = "postgresql+asyncpg://user:pw@localhost/db"
            mock_get_settings.return_value = mock_settings

            await server._init_dependencies()

        assert server.batch_writer is not None
        assert isinstance(server.batch_writer, LogBatchWriter)

    async def test_batch_writer_none_when_db_unavailable(self) -> None:
        """When DB is unreachable, _init_dependencies() sets batch_writer to None."""
        server, _ = self._make_minimal_server()

        with patch("sqlalchemy.ext.asyncio.create_async_engine", side_effect=RuntimeError("no DB")):
            await server._init_dependencies()

        assert server.batch_writer is None


class TestAgentServerShutdownFlushesWriter:
    """Tests for AgentServer._shutdown() calling writer.stop()."""

    def _make_server_with_writer(self) -> tuple:
        """Return (server, mock_writer) with the writer pre-wired."""
        from agent.server import AgentServer

        config = MagicMock()
        config.agent_server_host = "0.0.0.0"
        config.agent_server_port = 8001

        with patch("agent.server.set_agent_id"):
            server = AgentServer(agent_id="test-agent-001", config=config)

        mock_writer = AsyncMock(spec=LogBatchWriter)
        mock_writer.stop = AsyncMock()
        server._batch_writer = mock_writer
        return server, mock_writer

    async def test_shutdown_calls_writer_stop(self) -> None:
        """_shutdown() calls writer.stop() to drain buffered records."""
        server, writer = self._make_server_with_writer()
        server._is_running = True

        with (
            patch.object(server, "_persist_state", new_callable=AsyncMock),
            patch.object(server, "_redis_cache", None),
            patch.object(server, "_session", None),
        ):
            await server._shutdown()

        writer.stop.assert_awaited_once()

    async def test_shutdown_writer_stop_failure_does_not_raise(self) -> None:
        """If writer.stop() raises, _shutdown() swallows the error and continues."""
        server, writer = self._make_server_with_writer()
        writer.stop = AsyncMock(side_effect=RuntimeError("writer flush error"))
        server._is_running = True

        with (
            patch.object(server, "_persist_state", new_callable=AsyncMock),
            patch.object(server, "_redis_cache", None),
            patch.object(server, "_session", None),
        ):
            # Must not raise even though writer.stop() fails
            await server._shutdown()

    async def test_shutdown_with_no_writer_does_not_crash(self) -> None:
        """_shutdown() handles batch_writer=None gracefully (no DB mode)."""
        from agent.server import AgentServer

        config = MagicMock()
        with patch("agent.server.set_agent_id"):
            server = AgentServer(agent_id="test-agent-002", config=config)

        server._is_running = True
        # _batch_writer is already None from __init__

        with (
            patch.object(server, "_persist_state", new_callable=AsyncMock),
            patch.object(server, "_redis_cache", None),
            patch.object(server, "_session", None),
        ):
            await server._shutdown()  # must not raise


# ---------------------------------------------------------------------------
# LogBatchWriter — start / stop integration with AgentServer lifecycle
# ---------------------------------------------------------------------------


class TestWriterLifecycleIntegration:
    """Verify that the writer's background flush task is started and stopped correctly."""

    async def test_writer_is_running_after_start(self) -> None:
        """After start(), the writer's _running flag is True."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, flush_interval=999.0)
        await writer.start()
        try:
            assert writer._running is True
        finally:
            with (
                patch("src.database.models.AgentApiCall"),
                patch("src.database.models.AgentStrategySignal"),
            ):
                await writer.stop()

    async def test_writer_is_stopped_after_stop(self) -> None:
        """After stop(), the writer's _running flag is False."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, flush_interval=999.0)
        await writer.start()

        with (
            patch("src.database.models.AgentApiCall"),
            patch("src.database.models.AgentStrategySignal"),
        ):
            await writer.stop()

        assert writer._running is False

    async def test_buffered_records_persisted_on_stop(self) -> None:
        """Records buffered before stop() are flushed to the DB during stop()."""
        factory, session = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=50, flush_interval=999.0)
        await writer.start()

        await writer.add_api_call({"trace_id": "t1", "channel": "sdk", "endpoint": "get_price"})
        await writer.add_api_call({"trace_id": "t2", "channel": "rest", "endpoint": "/health"})

        assert len(writer._api_call_buffer) == 2

        with patch("src.database.models.AgentApiCall") as MockModel:
            MockModel.side_effect = lambda **kw: MagicMock(**kw)
            await writer.stop()

        # After stop(), buffer must be drained
        assert len(writer._api_call_buffer) == 0
