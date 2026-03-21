---
task_id: 23
title: "Activate AuditLog writer middleware"
type: task
agent: "backend-developer"
phase: 3
depends_on: [18]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "medium"
files: ["src/api/middleware/audit.py"]
tags:
  - task
  - agent
  - logging
---

# Task 23: Activate AuditLog Writer Middleware

## Assigned Agent: `backend-developer`

## Objective
Create an async audit log writer that populates the existing `AuditLog` table for key platform operations. The table schema exists (defined in `src/database/models.py` line 1072) but has zero active writers.

## Files to Create
- `src/api/middleware/audit.py` — async audit log writer

## Files to Modify
- `src/main.py` — register the audit middleware

## Implementation Details

Create an ASGI middleware or post-response hook that:
1. Checks if the request matches an auditable action
2. If yes, fires an `asyncio.create_task()` to write the `AuditLog` row (non-blocking)
3. Never fails the request even if audit logging fails

```python
AUDITABLE_ACTIONS = {
    ("POST", "/api/v1/trade/order"): "place_order",
    ("POST", "/api/v1/auth/register"): "register",
    ("POST", "/api/v1/auth/login"): "login",
    ("DELETE", "/api/v1/agents/"): "delete_agent",
    ("POST", "/api/v1/backtest/create"): "create_backtest",
    ("POST", "/api/v1/strategies"): "create_strategy",
}
```

For each auditable request, write:
- `account_id` from `request.state.account` (if available)
- `action` from the mapping
- `details` as JSONB with `request_id`, `trace_id`, `path`, response `status_code`
- `ip_address` from request headers

## Acceptance Criteria
- [ ] `AuditLog` rows written for all mapped actions
- [ ] Audit writes are fire-and-forget (no latency impact on responses)
- [ ] Failures in audit writing are logged but don't crash requests
- [ ] Middleware registered AFTER auth middleware (so `account_id` is available)
- [ ] `ruff check src/api/middleware/audit.py` passes

## Agent Instructions
- Read the existing `AuditLog` model in `src/database/models.py` (line 1072)
- Read `src/api/middleware/CLAUDE.md` for middleware patterns and execution order
- Use `asyncio.create_task()` for non-blocking writes
- The cleanup task in `src/tasks/cleanup.py` already handles 30-day retention

## Estimated Complexity
Medium — new middleware with async fire-and-forget pattern
