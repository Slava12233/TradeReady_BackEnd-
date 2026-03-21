---
task_id: 17
title: "Add trace ID propagation to REST client"
type: task
agent: "backend-developer"
phase: 3
depends_on: [1]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/tools/rest_tools.py"]
tags:
  - task
  - agent
  - logging
---

# Task 17: Add Trace ID Propagation to REST Client

## Assigned Agent: `backend-developer`

## Objective
Inject `X-Trace-Id` header into all `PlatformRESTClient` HTTP requests.

## Files to Modify
- `agent/tools/rest_tools.py` — add `X-Trace-Id` to request headers

## Implementation Details
1. `PlatformRESTClient` uses `httpx.AsyncClient` with a base URL
2. In the `__init__` or request method, add `X-Trace-Id` header using `get_trace_id()` from `agent.logging`
3. Since this client lives inside `agent/`, it CAN import directly from `agent.logging`
4. Add the header in the shared request method (or `httpx.AsyncClient` default headers)

## Acceptance Criteria
- [ ] `X-Trace-Id` header included in all REST client requests
- [ ] Header value matches the current `trace_id` from context vars
- [ ] `ruff check agent/tools/rest_tools.py` passes

## Agent Instructions
- Read `agent/tools/rest_tools.py` to find where headers are set
- If there's a shared `_request()` method, add the header there
- If headers are set per-method, consider refactoring to a shared method first

## Estimated Complexity
Low — single file, header injection in request method
