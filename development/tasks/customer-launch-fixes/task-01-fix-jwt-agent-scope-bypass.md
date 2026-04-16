---
task_id: 01
title: "Fix JWT agent scope bypass"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "completed"
priority: "P0"
board: "[[customer-launch-fixes/README]]"
files: ["src/api/middleware/auth.py", "src/api/routes/agents.py"]
tags:
  - task
  - security
  - jwt
  - P0
---

# Task 01: Fix JWT agent scope bypass

## Assigned Agent: `backend-developer`

## Objective
The `X-Agent-Id` header is not ownership-checked in the JWT authentication path. An attacker with a valid JWT can read another account's agent data by spoofing the `X-Agent-Id` header. Add an ownership check: `agent.account_id == authenticated_account.id`.

## Context
Security audit (SR-06) found this HIGH severity vulnerability. The API key auth path correctly scopes to the agent's owner, but the JWT path trusts the header blindly. This is the #1 launch blocker.

## Files to Modify
- `src/api/middleware/auth.py` — Add agent ownership validation in the JWT auth flow where `X-Agent-Id` is read
- `src/api/routes/agents.py` — Verify any direct agent lookups also check account ownership

## Acceptance Criteria
- [ ] JWT-authenticated requests with `X-Agent-Id` header verify that the agent belongs to the authenticated account
- [ ] Returns 403 Forbidden if agent doesn't belong to the account
- [ ] API key auth path remains unchanged (already correct)
- [ ] Existing tests pass
- [ ] New test: JWT user A cannot access agent belonging to user B

## Agent Instructions
1. Read `src/api/middleware/CLAUDE.md` for middleware patterns
2. Read the current auth middleware to understand the JWT vs API key paths
3. In the JWT path, after extracting the agent_id from `X-Agent-Id`, query the agent and verify `agent.account_id == account.id`
4. If mismatch, raise `HTTPException(403, "Agent does not belong to this account")`
5. Write a regression test in `tests/unit/` that proves cross-account agent access is blocked

## Estimated Complexity
Low — targeted 1-line ownership check + test
