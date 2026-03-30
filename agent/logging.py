"""Centralised structlog configuration and correlation context for the agent ecosystem.

This module provides:

- Three ``contextvars.ContextVar`` variables that carry trace/span/agent IDs across
  ``asyncio`` task boundaries without explicit argument threading.
- Accessor functions that read and write those variables in a safe, idempotent way.
- A structlog processor (``add_correlation_context``) that injects the current IDs
  into every log line automatically.
- ``configure_agent_logging`` — a single function that every entry point should call
  once at startup instead of inline ``structlog.configure()`` calls.

Usage::

    from agent.logging import configure_agent_logging, set_trace_id, set_agent_id

    configure_agent_logging(log_level="INFO")
    set_trace_id()          # auto-generates a 16-char hex trace ID
    set_agent_id("abc123")  # tags all subsequent log lines with agent_id=abc123

No ``structlog.configure()`` call is made at import time — calling this module
as a side effect is safe and will not mutate global structlog state.
"""

from __future__ import annotations

import logging as _stdlib_logging
import uuid
from contextvars import ContextVar
from typing import Any

import structlog

# ---------------------------------------------------------------------------
# Module-level context variables
# ---------------------------------------------------------------------------

#: Spans an entire agent decision cycle (created at the start of a run).
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")

#: Identifies an individual operation within the current trace.
_span_id: ContextVar[str] = ContextVar("span_id", default="")

#: The UUID of the agent that owns the current operation.
_agent_id: ContextVar[str] = ContextVar("agent_id", default="")


# ---------------------------------------------------------------------------
# Context accessor functions
# ---------------------------------------------------------------------------


def get_trace_id() -> str:
    """Return the current trace ID, or an empty string if none is set.

    Returns:
        The trace ID stored in the current ``asyncio`` context, or ``""`` if
        :func:`set_trace_id` has not been called yet.
    """
    return _trace_id.get()


def set_trace_id(trace_id: str | None = None) -> str:
    """Set the trace ID for the current ``asyncio`` context.

    If *trace_id* is ``None`` (the default), a fresh 16-character hex string
    derived from a random UUID is generated and stored.

    Args:
        trace_id: An explicit trace ID to use.  Pass ``None`` to
            auto-generate one.

    Returns:
        The trace ID that was stored (either the supplied value or the
        auto-generated one).
    """
    if trace_id is None:
        trace_id = uuid.uuid4().hex[:16]
    _trace_id.set(trace_id)
    return trace_id


def new_span_id() -> str:
    """Generate a fresh span ID and store it in the current context.

    Each call produces a unique 12-character hex string derived from a
    random UUID.  The new value overwrites any span ID that was previously
    set for this context.

    Returns:
        The newly generated span ID (12-character hex string).
    """
    span_id = uuid.uuid4().hex[:12]
    _span_id.set(span_id)
    return span_id


def set_agent_id(agent_id: str) -> None:
    """Store *agent_id* in the current ``asyncio`` context.

    All subsequent log lines emitted on this context will automatically
    include the ``agent_id`` field via :func:`add_correlation_context`.

    Args:
        agent_id: The UUID (or any string identifier) of the owning agent.
    """
    _agent_id.set(agent_id)


def get_agent_id() -> str:
    """Return the current agent ID, or an empty string if none is set.

    Returns:
        The agent ID stored in the current ``asyncio`` context, or ``""`` if
        :func:`set_agent_id` has not been called yet.
    """
    return _agent_id.get()


# ---------------------------------------------------------------------------
# Structlog processor
# ---------------------------------------------------------------------------


def add_correlation_context(
    logger: Any,  # noqa: ANN401 — structlog processor signature requires Any
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Inject trace/span/agent IDs into the structlog event dictionary.

    This processor is designed to be placed in the structlog processor chain
    configured by :func:`configure_agent_logging`.  It reads the current
    values of the three context variables and adds them to *event_dict* only
    when they are non-empty — log lines produced outside of an agent context
    will not carry spurious empty-string fields.

    Args:
        logger: The wrapped logger instance (passed by structlog; not used
            directly).
        method_name: The name of the logging method that was called (e.g.
            ``"info"``, ``"error"``; passed by structlog; not used directly).
        event_dict: The mutable event dictionary that structlog is assembling.

    Returns:
        The updated *event_dict* with any non-empty correlation fields added.
    """
    trace = _trace_id.get()
    span = _span_id.get()
    agent = _agent_id.get()

    if trace:
        event_dict["trace_id"] = trace
    if span:
        event_dict["span_id"] = span
    if agent:
        event_dict["agent_id"] = agent

    return event_dict


# ---------------------------------------------------------------------------
# Configuration function
# ---------------------------------------------------------------------------


def configure_agent_logging(log_level: str = "INFO") -> None:
    """Configure structlog for the agent ecosystem.

    Call this function **once** at process start — before any workflow or
    service code runs.  It is safe to call multiple times (subsequent calls
    overwrite the previous configuration), but in normal usage a single call
    from the entry point is sufficient.

    The processor chain applied in order:

    1. ``structlog.contextvars.merge_contextvars`` — merges any values that
       were bound via ``structlog.contextvars.bind_contextvars()``.
    2. ``structlog.stdlib.add_log_level`` — adds the ``level`` field.
    3. ``structlog.stdlib.add_logger_name`` — adds the ``logger`` field.
    4. ``structlog.processors.TimeStamper(fmt="iso", utc=True)`` — adds an
       ISO-8601 ``timestamp`` field in UTC.
    5. :func:`add_correlation_context` — injects ``trace_id``, ``span_id``,
       and ``agent_id`` from the current ``asyncio`` context when set.
    6. ``structlog.processors.StackInfoRenderer()`` — renders ``stack_info``
       frames when present.
    7. ``structlog.processors.format_exc_info`` — renders exception info into
       the ``exception`` field.
    8. ``structlog.processors.JSONRenderer()`` — serialises the final dict to
       a JSON string (one object per line; Docker-stdout compatible).

    The logger factory is ``PrintLoggerFactory`` (writes to stdout), which
    is the correct choice for containerised workloads where log aggregators
    read from stdout/stderr.

    Args:
        log_level: Minimum log level to emit.  Case-insensitive string, e.g.
            ``"DEBUG"``, ``"INFO"``, ``"WARNING"``.  Defaults to ``"INFO"``.
    """
    numeric_level: int = _stdlib_logging.getLevelName(log_level.upper())
    if not isinstance(numeric_level, int):
        # getLevelName returns a string like "Level 99" for unknown names;
        # fall back to INFO rather than propagating a confusing error.
        numeric_level = _stdlib_logging.INFO

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            # add_logger_name requires a stdlib logger with a .name attribute;
            # PrintLoggerFactory produces PrintLogger which lacks .name, so we
            # skip this processor to avoid AttributeError on structlog >= 25.x.
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            add_correlation_context,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
