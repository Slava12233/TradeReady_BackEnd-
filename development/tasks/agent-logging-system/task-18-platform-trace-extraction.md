---
task_id: 18
title: "Platform-side trace ID extraction in LoggingMiddleware"
type: task
agent: "backend-developer"
phase: 3
depends_on: [16]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["src/api/middleware/logging.py"]
tags:
  - task
  - agent
  - logging
---

# Task 18: Platform-Side Trace ID Extraction

## Assigned Agent: `backend-developer`

## Objective
Modify the platform's `LoggingMiddleware` to read `X-Trace-Id` from incoming requests and include it in log output, enabling cross-system log correlation.

## Files to Modify
- `src/api/middleware/logging.py` — extract and log `X-Trace-Id` header

## Implementation Details
1. In the middleware's request processing, read: `trace_id = request.headers.get("X-Trace-Id", "")`
2. If present, include `trace_id` in the log event dict
3. Also store it in `request.state.trace_id` so downstream handlers can access it
4. The `request_id` (existing UUID4) should remain — `trace_id` is an ADDITIONAL correlation field

## Acceptance Criteria
- [ ] `trace_id` field appears in HTTP request logs when `X-Trace-Id` header is present
- [ ] `trace_id` stored in `request.state.trace_id` for downstream use
- [ ] Existing `request_id` behavior unchanged
- [ ] No `trace_id` field in logs when header is absent (clean output)
- [ ] `ruff check src/api/middleware/logging.py` passes

## Agent Instructions
- Read `src/api/middleware/logging.py` and `src/api/middleware/CLAUDE.md` first
- The middleware uses structlog — add `trace_id` as a keyword arg to the log call
- This is a platform-side change, not agent-side

## Estimated Complexity
Low — add 3-4 lines to existing middleware
