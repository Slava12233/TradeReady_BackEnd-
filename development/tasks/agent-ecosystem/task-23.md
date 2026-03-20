---
task_id: 23
title: "Permission system — enforcement middleware and audit log"
agent: "backend-developer"
phase: 2
depends_on: [21, 22]
status: "pending"
priority: "high"
files: ["agent/permissions/enforcement.py"]
---

# Task 23: Permission system — enforcement middleware and audit log

## Assigned Agent: `backend-developer`

## Objective
Create the permission enforcement layer that wraps all agent actions, checking capabilities and budgets before execution. Every check is logged for audit.

## Files to Create
- `agent/permissions/enforcement.py` — `PermissionEnforcer` class

## Key Design
```python
class PermissionEnforcer:
    """Central enforcement point for all agent permissions."""

    def __init__(self, capability_mgr: CapabilityManager, budget_mgr: BudgetManager): ...

    async def check_action(self, agent_id: str, action: str, context: dict | None = None) -> EnforcementResult:
        """
        Full permission check:
        1. Is the capability allowed? (role + explicit grants)
        2. Is the budget sufficient? (if action involves trading)
        3. Log the check (pass or fail)
        4. Return result with reason
        """

    async def require_action(self, agent_id: str, action: str, context: dict | None = None) -> None:
        """Like check_action but raises PermissionDenied on failure."""

    async def get_audit_log(self, agent_id: str, limit: int = 100) -> list[AuditEntry]:
        """Retrieve recent permission checks for an agent."""

    # Decorator for tool functions
    def require(self, capability: Capability):
        """Decorator that enforces a capability before tool execution."""
        def decorator(func): ...
```

## Acceptance Criteria
- [ ] Every action checked against capability + budget
- [ ] Audit log records: agent_id, action, result (allow/deny), reason, timestamp
- [ ] Audit log persisted to DB (batch write for performance)
- [ ] `@require(Capability.CAN_TRADE)` decorator works on tool functions
- [ ] `PermissionDenied` exception raised on failure with clear message
- [ ] Permission escalation: agent can REQUEST higher permissions (logged, not auto-granted)

## Dependencies
- Task 21 (capabilities), Task 22 (budget)

## Agent Instructions
1. The `@require` decorator should wrap async functions and check permission before execution
2. Audit log: buffer entries in memory, flush to DB every 100 entries or 30 seconds
3. Use `src/utils/exceptions.py` pattern for `PermissionDenied` exception
4. Permission escalation: save request to `agent_feedback` with category `feature_request`

## Estimated Complexity
Medium — enforcement decorator, audit logging, and escalation flow.
