---
task_id: 16
title: "Add trace ID propagation to SDK client"
type: task
agent: "backend-developer"
phase: 3
depends_on: [1]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["sdk/agentexchange/async_client.py"]
tags:
  - task
  - agent
  - logging
---

# Task 16: Add Trace ID Propagation to SDK Client

## Assigned Agent: `backend-developer`

## Objective
Inject `X-Trace-Id` header into every HTTP request made by `AsyncAgentExchangeClient` so the platform can correlate agent requests with its own logs.

## Files to Modify
- `sdk/agentexchange/async_client.py` — add `X-Trace-Id` header to request method

## Implementation Details
1. The SDK client has a central `_request()` or `_make_request()` method that all API calls go through
2. Add `X-Trace-Id` header to the headers dict in that method
3. The trace ID should be read from `contextvars` (import `get_trace_id` from `agent.logging`) OR passed as an optional `trace_id` parameter
4. Since the SDK is a separate package, prefer a `trace_id_provider: Callable[[], str] | None = None` constructor parameter to avoid hard-coupling to `agent.logging`
5. If no provider is set, the header is omitted (backwards compatible)

## Acceptance Criteria
- [ ] `X-Trace-Id` header included in all SDK HTTP requests when a trace_id_provider is set
- [ ] Header omitted when no provider is configured (backwards compatible)
- [ ] Existing SDK tests still pass
- [ ] `ruff check sdk/` passes

## Agent Instructions
- Read `sdk/agentexchange/async_client.py` and `sdk/CLAUDE.md` first
- The SDK is a standalone package — do NOT import from `agent/` directly
- Use a callback pattern: `trace_id_provider: Callable[[], str] | None = None` in `__init__`
- In `agent/tools/sdk_tools.py`, when creating the client, pass `trace_id_provider=get_trace_id`

## Estimated Complexity
Medium — need to modify SDK without breaking its standalone nature
