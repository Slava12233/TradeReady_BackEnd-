---
task_id: 09
title: "Create API call logging middleware"
type: task
agent: "backend-developer"
phase: 2
depends_on: [1]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/logging_middleware.py"]
tags:
  - task
  - agent
  - logging
---

# Task 09: Create API Call Logging Middleware

## Assigned Agent: `backend-developer`

## Objective
Create `agent/logging_middleware.py` — an async context manager that wraps every outbound API call the agent makes, logging timing, status, and correlation context.

## Files to Create
- `agent/logging_middleware.py` — `log_api_call` async context manager

## Implementation Details

Create an `@asynccontextmanager` called `log_api_call` with parameters:
- `channel: str` — one of `"sdk"`, `"mcp"`, `"rest"`, `"db"`
- `endpoint: str` — the API endpoint or tool name
- `method: str = ""` — HTTP method (GET, POST, etc.)
- `**extra_context` — additional key-value pairs to include in log

Behavior:
1. Generate a `span_id` via `new_span_id()` from `agent.logging`
2. Record `start = time.monotonic()`
3. Yield a mutable `ctx` dict for the caller to enrich (e.g., `ctx["response_status"] = 200`)
4. On success: log `"agent.api.completed"` at INFO with channel, endpoint, method, span_id, latency_ms, status
5. On exception: log `"agent.api.failed"` at ERROR with error details, then re-raise
6. Latency calculation: `round((time.monotonic() - start) * 1000, 2)` for millisecond precision

## Acceptance Criteria
- [ ] `agent/logging_middleware.py` exists with `log_api_call` context manager
- [ ] Success path logs at INFO level with all required fields
- [ ] Error path logs at ERROR level with error type and message, then re-raises
- [ ] `span_id` is unique per call
- [ ] Latency is measured in milliseconds with 2 decimal precision
- [ ] Type annotations on all parameters
- [ ] `ruff check agent/logging_middleware.py` passes

## Agent Instructions
- Follow the code example in `development/agent-logging-plan.md` Task 2.1
- Import `new_span_id` from `agent.logging` (lazy import inside the function body to avoid circular imports)
- The context manager must be async (`@asynccontextmanager`)
- Filter out `None` values from extra_context before logging

## Estimated Complexity
Low — single function, well-defined interface
