"""Tests for agent/logging_writer.py — LogBatchWriter batch flush logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from agent.logging_writer import LogBatchWriter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session_factory(*, raise_on_commit: bool = False) -> tuple[MagicMock, AsyncMock]:
    """Return (session_factory, mock_session) pair.

    The session is wired as an async context manager so that
    ``async with session_factory() as session:`` works correctly.
    """
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.add_all = MagicMock()  # synchronous in SQLAlchemy
    if raise_on_commit:
        mock_session.commit = AsyncMock(side_effect=RuntimeError("DB unavailable"))
    mock_session_factory = MagicMock(return_value=mock_session)
    return mock_session_factory, mock_session


def _make_api_call_record(trace_id: str = "abc123") -> dict:
    """Return a minimal valid API call record dict."""
    return {
        "trace_id": trace_id,
        "channel": "rest",
        "endpoint": "/api/v1/market/prices",
        "method": "GET",
        "status_code": 200,
    }


def _make_signal_record(trace_id: str = "abc123") -> dict:
    """Return a minimal valid strategy signal record dict."""
    return {
        "trace_id": trace_id,
        "strategy_name": "ppo_rl",
        "symbol": "BTCUSDT",
        "action": "buy",
    }


# ---------------------------------------------------------------------------
# API call buffer tests
# ---------------------------------------------------------------------------


class TestBatchWriterAddApiCall:
    """Tests for add_api_call() buffering behaviour."""

    async def test_add_single_record_is_buffered(self) -> None:
        """A record added below max_batch_size is buffered, not flushed immediately."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=10)

        await writer.add_api_call(_make_api_call_record())

        assert len(writer._api_call_buffer) == 1
        # Session factory should not have been called yet (no flush triggered)
        factory.assert_not_called()

    async def test_add_multiple_records_all_buffered(self) -> None:
        """Multiple records below the batch limit accumulate in the buffer."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=10)

        for i in range(5):
            await writer.add_api_call(_make_api_call_record(trace_id=f"trace-{i}"))

        assert len(writer._api_call_buffer) == 5
        factory.assert_not_called()

    async def test_signal_buffer_stays_empty_when_only_api_calls_added(self) -> None:
        """Adding API call records does not populate the signal buffer."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=10)

        await writer.add_api_call(_make_api_call_record())

        assert len(writer._signal_buffer) == 0


# ---------------------------------------------------------------------------
# Auto-flush on size
# ---------------------------------------------------------------------------


class TestBatchWriterFlushOnSize:
    """Tests for size-triggered automatic flush."""

    async def test_flush_triggers_when_buffer_reaches_max_batch_size(self) -> None:
        """Adding max_batch_size records triggers an immediate flush."""
        factory, session = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=3)

        # Patch AgentApiCall so we don't need a real DB model
        with patch("src.database.models.AgentApiCall") as MockModel:
            MockModel.side_effect = lambda **kw: MagicMock(**kw)
            for _ in range(3):
                await writer.add_api_call(_make_api_call_record())

        # After auto-flush, the buffer should be drained
        assert len(writer._api_call_buffer) == 0
        # Session factory was called (at least one flush happened)
        factory.assert_called()

    async def test_buffer_empty_after_size_triggered_flush(self) -> None:
        """The buffer is drained to zero after a size-triggered flush."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=2)

        with patch("src.database.models.AgentApiCall") as MockModel:
            MockModel.side_effect = lambda **kw: MagicMock(**kw)
            await writer.add_api_call(_make_api_call_record(trace_id="t1"))
            await writer.add_api_call(_make_api_call_record(trace_id="t2"))

        assert len(writer._api_call_buffer) == 0

    async def test_records_beyond_batch_size_remain_in_buffer(self) -> None:
        """Records added after a flush cycle stay buffered until next flush."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=2)

        with patch("src.database.models.AgentApiCall") as MockModel:
            MockModel.side_effect = lambda **kw: MagicMock(**kw)
            # 2 triggers flush, 3rd goes into buffer
            for i in range(3):
                await writer.add_api_call(_make_api_call_record(trace_id=f"t{i}"))

        assert len(writer._api_call_buffer) == 1


# ---------------------------------------------------------------------------
# stop() drains remaining events
# ---------------------------------------------------------------------------


class TestBatchWriterStopDrains:
    """Tests for stop() draining the buffer before returning."""

    async def test_stop_flushes_remaining_api_calls(self) -> None:
        """stop() drains any buffered API call records via a final flush."""
        factory, session = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=50)
        await writer.start()

        await writer.add_api_call(_make_api_call_record(trace_id="pending-1"))
        await writer.add_api_call(_make_api_call_record(trace_id="pending-2"))

        # Buffer has 2 records before stop
        assert len(writer._api_call_buffer) == 2

        with patch("src.database.models.AgentApiCall") as MockModel:
            MockModel.side_effect = lambda **kw: MagicMock(**kw)
            await writer.stop()

        # Buffer should be drained after stop
        assert len(writer._api_call_buffer) == 0

    async def test_stop_flushes_remaining_signals(self) -> None:
        """stop() also drains any buffered signal records."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=50)
        await writer.start()

        await writer.add_signal(_make_signal_record(trace_id="sig-1"))

        assert len(writer._signal_buffer) == 1

        with patch("src.database.models.AgentStrategySignal") as MockModel:
            MockModel.side_effect = lambda **kw: MagicMock(**kw)
            await writer.stop()

        assert len(writer._signal_buffer) == 0

    async def test_stop_sets_running_false(self) -> None:
        """stop() sets _running to False so periodic flush loop exits."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory)
        await writer.start()
        assert writer._running is True

        with patch("src.database.models.AgentApiCall"):
            with patch("src.database.models.AgentStrategySignal"):
                await writer.stop()

        assert writer._running is False


# ---------------------------------------------------------------------------
# Flush failure — error is swallowed, no crash
# ---------------------------------------------------------------------------


class TestBatchWriterFlushFailure:
    """Tests for error resilience during flush."""

    async def test_flush_failure_is_logged_not_raised(self) -> None:
        """When the DB session raises during commit, the error is logged, not re-raised."""
        factory, _ = _make_session_factory(raise_on_commit=True)
        writer = LogBatchWriter(session_factory=factory, max_batch_size=50)

        await writer.add_api_call(_make_api_call_record())

        with patch("src.database.models.AgentApiCall") as MockModel:
            MockModel.side_effect = lambda **kw: MagicMock(**kw)
            # Must not raise even though commit fails
            await writer.flush()  # noqa: S608 (not SQL)

    async def test_flush_failure_drains_buffer_anyway(self) -> None:
        """A failed flush still pops records from the buffer — no infinite retry."""
        factory, _ = _make_session_factory(raise_on_commit=True)
        writer = LogBatchWriter(session_factory=factory, max_batch_size=50)

        await writer.add_api_call(_make_api_call_record())
        assert len(writer._api_call_buffer) == 1

        with patch("src.database.models.AgentApiCall") as MockModel:
            MockModel.side_effect = lambda **kw: MagicMock(**kw)
            await writer.flush()

        # Records are popped before the commit attempt; buffer is empty after failure
        assert len(writer._api_call_buffer) == 0

    async def test_signal_flush_failure_does_not_crash(self) -> None:
        """Signal flush failure is also swallowed without re-raising."""
        factory, _ = _make_session_factory(raise_on_commit=True)
        writer = LogBatchWriter(session_factory=factory, max_batch_size=50)

        await writer.add_signal(_make_signal_record())

        with patch("src.database.models.AgentStrategySignal") as MockModel:
            MockModel.side_effect = lambda **kw: MagicMock(**kw)
            await writer.flush()  # must not raise


# ---------------------------------------------------------------------------
# Signal buffer tests
# ---------------------------------------------------------------------------


class TestBatchWriterAddSignal:
    """Tests for add_signal() buffering behaviour."""

    async def test_add_single_signal_is_buffered(self) -> None:
        """A signal added below max_batch_size is buffered, not flushed immediately."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=10)

        await writer.add_signal(_make_signal_record())

        assert len(writer._signal_buffer) == 1
        factory.assert_not_called()

    async def test_add_multiple_signals_all_buffered(self) -> None:
        """Multiple signals accumulate in the signal buffer."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=10)

        for i in range(4):
            await writer.add_signal(_make_signal_record(trace_id=f"trace-{i}"))

        assert len(writer._signal_buffer) == 4

    async def test_api_call_buffer_stays_empty_when_only_signals_added(self) -> None:
        """Adding signal records does not populate the API call buffer."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=10)

        await writer.add_signal(_make_signal_record())

        assert len(writer._api_call_buffer) == 0

    async def test_signal_flush_triggers_at_max_batch_size(self) -> None:
        """Reaching max_batch_size for signals triggers an automatic flush."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=3)

        with patch("src.database.models.AgentStrategySignal") as MockModel:
            MockModel.side_effect = lambda **kw: MagicMock(**kw)
            for _ in range(3):
                await writer.add_signal(_make_signal_record())

        assert len(writer._signal_buffer) == 0
        factory.assert_called()

    async def test_independent_buffers_do_not_interfere(self) -> None:
        """API call and signal buffers are independent of each other."""
        factory, _ = _make_session_factory()
        writer = LogBatchWriter(session_factory=factory, max_batch_size=10)

        await writer.add_api_call(_make_api_call_record())
        await writer.add_signal(_make_signal_record())

        assert len(writer._api_call_buffer) == 1
        assert len(writer._signal_buffer) == 1
