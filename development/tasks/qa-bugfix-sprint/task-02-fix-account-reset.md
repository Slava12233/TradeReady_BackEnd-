---
task_id: 02
title: "Fix account reset DATABASE_ERROR (BUG-002)"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1]
status: "pending"
priority: "high"
board: "[[qa-bugfix-sprint/README]]"
files: ["src/accounts/service.py", "src/api/routes/account.py"]
tags:
  - task
  - accounts
  - reset
  - P1
---

# Task 02: Fix account reset DATABASE_ERROR (BUG-002)

## Assigned Agent: `backend-developer`

## Objective
Fix `POST /account/reset` which currently returns `DATABASE_ERROR` due to NOT NULL constraint violations when creating `Balance` and `TradingSession` rows without `agent_id`.

## Context
`reset_account()` in `src/accounts/service.py:380-484` creates new `Balance` and `TradingSession` rows but omits the required `agent_id` column. Both columns are NOT NULL in the schema. This causes an `IntegrityError` → caught as `SQLAlchemyError` → re-raised as generic `DatabaseError`.

Note: Task 01 establishes that all accounts have at least one default agent. The reset should work per-agent or iterate all agents.

## Files to Modify/Create
- `src/accounts/service.py` — fix `reset_account()` to be agent-aware (lines ~380-484)
- `src/api/routes/account.py` — if the reset endpoint needs to accept/resolve `agent_id`

## Acceptance Criteria
- [ ] `POST /account/reset` with `{"confirm": true}` succeeds (HTTP 200)
- [ ] After reset, account balance returns to starting amount
- [ ] All existing orders, trades, positions are cleared
- [ ] A new `TradingSession` is created with valid `agent_id`
- [ ] If account has multiple agents, all agents are reset (or the endpoint accepts agent-specific reset)
- [ ] Regression test added

## Dependencies
- Task 01 must be completed first (establishes the default agent pattern)

## Agent Instructions
1. Read `src/accounts/service.py` — focus on `reset_account()` method (lines ~380-484)
2. The core issue is at lines ~448-463 where `Balance()` and `TradingSession()` are created without `agent_id`
3. **Recommended approach:** Make `reset_account()` iterate all agents for the account and reset each one. For each agent:
   - Delete old balances, orders, trades, positions scoped to that `agent_id`
   - Create new `Balance(agent_id=agent.id, ...)` and `TradingSession(agent_id=agent.id, ...)`
4. Alternatively, delegate to `AgentService.reset_agent()` which already works (QA test 7.4 passed)
5. Watch for: transaction boundaries, FK constraints during deletion, proper `await session.flush()` ordering

## Estimated Complexity
Medium — needs understanding of the multi-agent balance model and careful transaction handling.
