---
task_id: 01
title: "Fix zero balance at registration (BUG-001)"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[qa-bugfix-sprint/README]]"
files: ["src/accounts/service.py", "src/agents/service.py"]
tags:
  - task
  - accounts
  - registration
  - P0
---

# Task 01: Fix zero balance at registration (BUG-001)

## Assigned Agent: `backend-developer`

## Objective
After `POST /auth/register`, the new account must have a usable USDT balance immediately — not $0. Currently, balances are only created when an agent is created via `AgentService.create_agent()`, leaving brand-new accounts unable to trade.

## Context
This is the #1 P0 bug from the QA report. Every new user sees $0 balance and all trade orders fail with `ORDER_REJECTED: insufficient_balance`. The platform's balance model is agent-scoped (each `Balance` row has a NOT NULL `agent_id`), so the fix must work within that constraint.

## Files to Modify/Create
- `src/accounts/service.py` — modify `register()` (lines ~183-226) to auto-create a default agent after account creation
- Possibly `src/api/routes/auth.py` — if the register endpoint response needs to include agent info

## Acceptance Criteria
- [ ] New account registration automatically creates a default agent with the requested `starting_balance`
- [ ] `GET /account/portfolio` immediately after registration shows correct `available_cash` and `total_equity`
- [ ] `GET /account/balance` shows USDT balance equal to `starting_balance`
- [ ] Trading (market buy) works immediately after registration without manually creating an agent
- [ ] Existing agent creation flow still works independently
- [ ] Registration response includes the default agent's info (or at minimum, the API key still works for trading)
- [ ] Regression test added covering the full register → check-balance → trade flow

## Dependencies
None — this is the first task and has no blockers.

## Agent Instructions
1. Read `src/accounts/CLAUDE.md` and `src/agents/CLAUDE.md` first
2. Read `src/accounts/service.py` — focus on the `register()` method
3. Read `src/agents/service.py` — focus on `create_agent()` to understand how balances are created
4. In `register()`, after the account is persisted and flushed, call the agent creation logic to create a default agent. Be careful about:
   - Circular imports — `AgentService` may need to be imported lazily
   - The agent needs the `account_id` from the just-created account
   - The agent's `starting_balance` should match the registration request's `starting_balance`
   - Use a sensible default name like `"{display_name}'s Agent"` or `"Default Agent"`
5. Ensure the API key returned by registration still works for all endpoints
6. Write a unit test in `tests/unit/` that mocks the DB and verifies `register()` creates both an account AND an agent with balance

## Estimated Complexity
Medium — the fix is conceptually simple (add one service call) but needs careful handling of imports, transaction boundaries, and the response shape.
