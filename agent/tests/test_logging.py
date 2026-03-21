"""Tests for agent/logging.py — correlation context, structlog configuration."""

from __future__ import annotations

import asyncio
from contextvars import copy_context

import structlog

from agent.logging import (
    add_correlation_context,
    configure_agent_logging,
    get_agent_id,
    get_trace_id,
    new_span_id,
    set_agent_id,
    set_trace_id,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_context() -> None:
    """Reset all three ContextVar values to their defaults (empty strings).

    This runs the reset inside a copy_context so that it does not affect the
    caller's context — but we still need to set the vars in the *test* context,
    which we do by calling the setters directly with empty strings.
    """
    set_trace_id("")
    set_agent_id("")
    # _span_id has no public setter that accepts a value; new_span_id() always
    # generates a new ID, so we directly call new_span_id to clear it and then
    # overwrite via the module-level ContextVar.  We import the private var only
    # here to keep the helper self-contained.
    from agent.logging import _span_id

    _span_id.set("")


# ---------------------------------------------------------------------------
# Trace ID
# ---------------------------------------------------------------------------


class TestSetGetTraceId:
    """Tests for set_trace_id() and get_trace_id()."""

    def setup_method(self) -> None:
        _reset_context()

    def test_set_explicit_trace_id(self) -> None:
        """set_trace_id('abc123') stores the value; get_trace_id() returns it."""
        set_trace_id("abc123")
        assert get_trace_id() == "abc123"

    def test_set_trace_id_returns_the_stored_value(self) -> None:
        """set_trace_id() returns the trace ID that was stored."""
        returned = set_trace_id("xyz789")
        assert returned == "xyz789"
        assert get_trace_id() == "xyz789"

    def test_default_before_set_is_empty_string(self) -> None:
        """get_trace_id() returns '' when set_trace_id has not been called."""
        assert get_trace_id() == ""


class TestAutoGenerateTraceId:
    """Tests for auto-generation when set_trace_id(None) is called."""

    def setup_method(self) -> None:
        _reset_context()

    def test_auto_generate_returns_16_char_hex(self) -> None:
        """set_trace_id(None) generates and returns a 16-character hex string."""
        generated = set_trace_id(None)
        assert len(generated) == 16
        # Must be valid hexadecimal
        int(generated, 16)

    def test_auto_generate_stores_the_id(self) -> None:
        """The auto-generated ID is stored and retrievable via get_trace_id()."""
        generated = set_trace_id(None)
        assert get_trace_id() == generated

    def test_two_auto_generates_are_different(self) -> None:
        """Two successive auto-generated trace IDs are (very likely) unique."""
        first = set_trace_id(None)
        second = set_trace_id(None)
        # Statistically near-impossible to collide; test guards against a
        # broken implementation that always returns the same value.
        assert first != second


# ---------------------------------------------------------------------------
# Agent ID
# ---------------------------------------------------------------------------


class TestSetGetAgentId:
    """Tests for set_agent_id() and get_agent_id()."""

    def setup_method(self) -> None:
        _reset_context()

    def test_set_and_get_agent_id(self) -> None:
        """set_agent_id stores the value; get_agent_id returns it."""
        set_agent_id("agent-uuid-001")
        assert get_agent_id() == "agent-uuid-001"

    def test_default_agent_id_is_empty_string(self) -> None:
        """get_agent_id() returns '' before set_agent_id is called."""
        assert get_agent_id() == ""

    def test_overwrite_agent_id(self) -> None:
        """Calling set_agent_id twice updates the stored value."""
        set_agent_id("first-agent")
        set_agent_id("second-agent")
        assert get_agent_id() == "second-agent"


# ---------------------------------------------------------------------------
# Span ID
# ---------------------------------------------------------------------------


class TestNewSpanId:
    """Tests for new_span_id()."""

    def test_span_id_is_12_char_hex(self) -> None:
        """new_span_id() returns a 12-character hex string."""
        span = new_span_id()
        assert len(span) == 12
        int(span, 16)  # raises ValueError if not valid hex

    def test_two_span_ids_are_different(self) -> None:
        """Two successive calls produce different span IDs."""
        first = new_span_id()
        second = new_span_id()
        assert first != second

    def test_span_id_is_stored(self) -> None:
        """new_span_id() stores the generated ID in the ContextVar."""
        from agent.logging import _span_id

        span = new_span_id()
        assert _span_id.get() == span


# ---------------------------------------------------------------------------
# Processor: add_correlation_context
# ---------------------------------------------------------------------------


class TestCorrelationContextProcessorPopulated:
    """Tests for add_correlation_context when IDs are set."""

    def setup_method(self) -> None:
        _reset_context()

    def test_all_three_keys_injected(self) -> None:
        """When all three IDs are set, all three keys appear in the event dict."""
        set_trace_id("trace-aaa")
        new_span_id()  # sets _span_id
        set_agent_id("agent-bbb")

        event: dict = {}
        result = add_correlation_context(None, None, event)

        assert "trace_id" in result
        assert "span_id" in result
        assert "agent_id" in result

    def test_values_match_set_values(self) -> None:
        """The injected values match exactly what was set."""
        set_trace_id("trace-exact")
        span = new_span_id()
        set_agent_id("agent-exact")

        result = add_correlation_context(None, None, {})

        assert result["trace_id"] == "trace-exact"
        assert result["span_id"] == span
        assert result["agent_id"] == "agent-exact"

    def test_existing_event_dict_keys_preserved(self) -> None:
        """Pre-existing keys in event_dict are not removed by the processor."""
        set_trace_id("t1")
        event = {"event": "something happened", "level": "info"}
        result = add_correlation_context(None, None, event)
        assert result["event"] == "something happened"
        assert result["level"] == "info"


class TestCorrelationContextProcessorEmpty:
    """Tests for add_correlation_context when no IDs are set."""

    def test_no_keys_injected_when_context_empty(self) -> None:
        """When context vars hold empty strings, no keys are added to event_dict."""
        # Run inside a fresh copy_context so that any IDs set elsewhere in the
        # test session do not leak in.
        def _run() -> dict:
            # Reset all context vars within this isolated context
            set_trace_id("")
            set_agent_id("")
            from agent.logging import _span_id
            _span_id.set("")
            return add_correlation_context(None, None, {})

        result = copy_context().run(_run)

        assert "trace_id" not in result
        assert "span_id" not in result
        assert "agent_id" not in result

    def test_only_set_ids_appear(self) -> None:
        """Only the IDs that are non-empty are injected."""
        def _run() -> dict:
            set_trace_id("")
            set_agent_id("")
            from agent.logging import _span_id
            _span_id.set("")
            # Only set trace_id
            set_trace_id("only-trace")
            return add_correlation_context(None, None, {})

        result = copy_context().run(_run)

        assert "trace_id" in result
        assert "span_id" not in result
        assert "agent_id" not in result


# ---------------------------------------------------------------------------
# configure_agent_logging
# ---------------------------------------------------------------------------


class TestConfigureAgentLogging:
    """Tests for configure_agent_logging()."""

    def test_structlog_is_configured_after_call(self) -> None:
        """After configure_agent_logging(), structlog.is_configured() returns True."""
        configure_agent_logging("INFO")
        assert structlog.is_configured()

    def test_debug_level_accepted(self) -> None:
        """configure_agent_logging('DEBUG') does not raise."""
        configure_agent_logging("DEBUG")
        assert structlog.is_configured()

    def test_warning_level_accepted(self) -> None:
        """configure_agent_logging('WARNING') does not raise."""
        configure_agent_logging("WARNING")
        assert structlog.is_configured()

    def test_invalid_level_falls_back_gracefully(self) -> None:
        """An unrecognised log level does not raise; structlog is still configured."""
        configure_agent_logging("NOTAREALEVEL")
        assert structlog.is_configured()

    def test_can_get_logger_after_configure(self) -> None:
        """After configure_agent_logging(), structlog.get_logger() works."""
        configure_agent_logging("INFO")
        logger = structlog.get_logger("test")
        assert logger is not None


# ---------------------------------------------------------------------------
# Async context isolation
# ---------------------------------------------------------------------------


class TestAsyncContextIsolation:
    """Test that asyncio tasks have independent ContextVar state."""

    async def test_two_tasks_do_not_share_trace_id(self) -> None:
        """Two concurrent asyncio tasks can set independent trace IDs."""

        trace_a: str = ""
        trace_b: str = ""

        async def task_a() -> None:
            nonlocal trace_a
            set_trace_id("trace-task-a")
            await asyncio.sleep(0)  # yield to allow task_b to run
            trace_a = get_trace_id()

        async def task_b() -> None:
            nonlocal trace_b
            set_trace_id("trace-task-b")
            await asyncio.sleep(0)
            trace_b = get_trace_id()

        await asyncio.gather(task_a(), task_b())

        assert trace_a == "trace-task-a"
        assert trace_b == "trace-task-b"

    async def test_parent_context_not_mutated_by_child_task(self) -> None:
        """A child asyncio.Task does not mutate the parent task's ContextVar."""
        set_trace_id("parent-trace")

        async def child() -> None:
            set_trace_id("child-trace")

        # asyncio.create_task copies the context — mutations inside do not
        # propagate back to the parent.
        task = asyncio.create_task(child())
        await task

        # Parent trace ID must still be the one set in this task.
        assert get_trace_id() == "parent-trace"

    async def test_agent_id_isolation_across_gathered_tasks(self) -> None:
        """Each gathered task maintains its own agent_id independently."""
        results: list[str] = ["", ""]

        async def worker(index: int, agent_name: str) -> None:
            set_agent_id(agent_name)
            await asyncio.sleep(0)
            results[index] = get_agent_id()

        await asyncio.gather(
            worker(0, "agent-alpha"),
            worker(1, "agent-beta"),
        )

        assert results[0] == "agent-alpha"
        assert results[1] == "agent-beta"
