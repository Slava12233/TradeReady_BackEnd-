---
task_id: 25
title: "Tests for permission system"
agent: "test-runner"
phase: 2
depends_on: [21, 22, 23]
status: "pending"
priority: "high"
files: ["tests/unit/test_agent_permissions.py", "tests/unit/test_agent_budget.py", "tests/unit/test_permission_enforcement.py"]
---

# Task 25: Tests for permission system

## Assigned Agent: `test-runner`

## Objective
Comprehensive tests for the entire permission system: roles, capabilities, budgets, and enforcement.

## Files to Create
- `tests/unit/test_agent_permissions.py` — role hierarchy, capability grants/revokes, cache
- `tests/unit/test_agent_budget.py` — budget checks, atomic increments, daily reset, denial reasons
- `tests/unit/test_permission_enforcement.py` — enforcement decorator, audit logging, escalation

## Acceptance Criteria
- [ ] At least 8 tests for roles/capabilities
- [ ] At least 8 tests for budget enforcement
- [ ] At least 6 tests for enforcement middleware
- [ ] 22+ tests total
- [ ] Test privilege escalation is prevented
- [ ] Test budget denial with clear reasons
- [ ] Test `@require` decorator on async functions
- [ ] Test audit log records all checks
- [ ] Test Redis cache failure fallback to DB

## Dependencies
- Tasks 21, 22, 23 (all permission components)

## Agent Instructions
1. Test the negative cases heavily — permission denied, budget exceeded, unauthorized escalation
2. Mock Redis to simulate cache failures
3. Test concurrent budget increments if possible (asyncio.gather)
4. Verify the `@require` decorator properly blocks unauthorized calls

## Estimated Complexity
Medium — security-critical tests require thorough negative case coverage.
