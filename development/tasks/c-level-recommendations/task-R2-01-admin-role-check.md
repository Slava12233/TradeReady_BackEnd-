---
task_id: R2-01
title: "Add ADMIN role check to grant_capability and set_role"
type: task
agent: "security-reviewer"
phase: 2
depends_on: ["R1-03"]
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["agent/permissions/capabilities.py"]
tags:
  - task
  - security
  - permissions
---

# Task R2-01: Add ADMIN Role Check to `grant_capability` and `set_role`

## Assigned Agent: `security-reviewer`

## Objective
Prevent privilege escalation by requiring the grantor to have ADMIN role before granting capabilities or changing roles.

## Context
HIGH-1 from security review (2026-03-20): `grant_capability()` and `set_role()` accept any UUID as `granted_by` with no privilege check. Any caller with access to `CapabilityManager` can escalate any agent to ADMIN.

## Files to Modify/Create
- `agent/permissions/capabilities.py` — modify `grant_capability()` (~line 450), `set_role()`, and `revoke_capability()`

## Acceptance Criteria
- [x] `grant_capability()` raises `PermissionDenied` when grantor is not ADMIN
- [x] `set_role()` raises `PermissionDenied` when grantor is not ADMIN
- [x] `revoke_capability()` raises `PermissionDenied` when grantor is not ADMIN
- [x] Existing ADMIN flows continue to work
- [x] Audit log records the denial (via `logger.warning` before raise)

## Completion Notes (2026-03-23)
- All three methods in `agent/permissions/capabilities.py` now check `ROLE_HIERARCHY[grantor_role] >= ROLE_HIERARCHY[AgentRole.ADMIN]` before mutating.
- `PermissionDenied` is imported lazily (inside method) from `agent.permissions.enforcement` to avoid circular imports.
- Fail-closed: `get_role()` returns the default `"viewer"` role on any DB/lookup failure, so unknown grantors (e.g. account UUIDs not in agents table) are always denied.
- `revoke_capability()` now takes `granted_by: str | None = None`; `None` is explicitly denied (fail-closed for callers that omit the parameter).
- Existing test `test_revoke_sets_capability_false_in_db` will fail because it calls without `granted_by` — it tests old insecure behavior and must be updated to mock ADMIN role + pass `granted_by`.

## Dependencies
- R1-03 (DB must be running to test permission lookups)

## Agent Instructions
1. Read `agent/permissions/CLAUDE.md` for the roles hierarchy: `READ_ONLY < STANDARD < ADVANCED < AUTONOMOUS < ADMIN`
2. In `grant_capability()`, after UUID validation, add:
   ```python
   grantor_role = await self.get_role(granted_by)
   if ROLE_HIERARCHY.get(grantor_role, 0) < ROLE_HIERARCHY[AgentRole.ADMIN]:
       raise PermissionDenied(agent_id=granted_by, action="grant_capability",
           reason=f"Grantor {granted_by} is {grantor_role.value}, not ADMIN")
   ```
3. Apply same pattern to `set_role()` and `revoke_capability()`
4. Handle edge case: `granted_by` might be an account UUID, not an agent UUID

## Estimated Complexity
Medium — logic is straightforward but must handle edge cases (account vs agent UUID)
