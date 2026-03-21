---
task_id: 01
title: "Create centralized agent logging module"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/logging.py"]
tags:
  - task
  - agent
  - logging
---

# Task 01: Create Centralized Agent Logging Module

## Assigned Agent: `backend-developer`

## Objective
Create `agent/logging.py` — a single module that centralizes all structlog configuration and correlation context management for the agent ecosystem.

## Context
Currently `agent/main.py`, `agent/server.py`, and 3 strategy CLIs each have their own duplicate `structlog.configure()` calls. This module unifies them and adds correlation context (trace_id, span_id, agent_id) via `contextvars` that will be used by all subsequent logging phases.

## Files to Create
- `agent/logging.py` — centralized logging configuration + correlation context utilities

## Implementation Details

The module must provide:

1. **Context variables** (via `contextvars.ContextVar`):
   - `_trace_id` — spans an entire agent decision cycle
   - `_span_id` — individual operation within a trace
   - `_agent_id` — the owning agent UUID

2. **Context accessor functions**:
   - `get_trace_id() -> str`
   - `set_trace_id(trace_id: str | None = None) -> str` — generates hex[:16] if None
   - `new_span_id() -> str` — generates hex[:12]
   - `set_agent_id(agent_id: str) -> None`
   - `get_agent_id() -> str`

3. **Structlog processor**: `add_correlation_context(logger, method_name, event_dict)` — injects trace/span/agent IDs into every log line

4. **Configuration function**: `configure_agent_logging(log_level: str = "INFO") -> None` with these processors in order:
   - `structlog.contextvars.merge_contextvars`
   - `structlog.stdlib.add_log_level`
   - `structlog.stdlib.add_logger_name`
   - `structlog.processors.TimeStamper(fmt="iso", utc=True)`
   - `add_correlation_context`
   - `structlog.processors.StackInfoRenderer()`
   - `structlog.processors.format_exc_info`
   - `structlog.processors.JSONRenderer()`

   Use `PrintLoggerFactory()` (not `LoggerFactory()`) for Docker stdout compatibility.
   Use `make_filtering_bound_logger()` with the provided log level.
   Set `cache_logger_on_first_use=True`.

## Acceptance Criteria
- [ ] `agent/logging.py` exists with all functions described above
- [ ] `configure_agent_logging()` produces JSON log lines to stdout
- [ ] Correlation context vars propagate correctly in async contexts
- [ ] Module is importable without side effects (no `structlog.configure()` at import time)
- [ ] Docstrings on all public functions (Google style)
- [ ] Type annotations on all functions
- [ ] `ruff check agent/logging.py` passes

## Agent Instructions
- Read `agent/CLAUDE.md` for agent package conventions
- Read `agent/main.py` lines 63-77 to see the existing structlog config you're replacing
- The module name `logging` shadows stdlib's `logging` — use `import logging as stdlib_logging` internally if needed
- Follow the code example in the plan file `development/agent-logging-plan.md` Task 1.1

## Estimated Complexity
Low — single file, well-defined interface, no external dependencies beyond structlog
