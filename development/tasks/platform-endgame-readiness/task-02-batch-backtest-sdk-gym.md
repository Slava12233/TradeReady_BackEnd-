---
task_id: 2
title: "Add batch_step_fast() to SDK clients + gym batch_size param"
type: task
agent: "backend-developer"
phase: 1
depends_on: [1]
status: "pending"
priority: "high"
board: "[[platform-endgame-readiness/README]]"
files:
  - "sdk/agentexchange/client.py"
  - "sdk/agentexchange/async_client.py"
  - "tradeready-gym/tradeready_gym/envs/base_trading_env.py"
tags:
  - task
  - sdk
  - gymnasium
  - phase-1
---

# Task 02: Add batch_step_fast() to SDK clients + gym batch_size param

## Assigned Agent: `backend-developer`

## Objective
Add `batch_step_fast()` methods to both SDK clients (sync + async) and add a `batch_size` constructor param to the base Gymnasium environment so it uses the fast batch endpoint when `batch_size > 1`.

## Context
Task 01 creates the engine method and API endpoint. This task wires it into the SDK and Gymnasium environment so external agents and RL training can use batch stepping.

## Files to Modify/Create
- `sdk/agentexchange/client.py` — Add `batch_step_fast(session_id, steps, include_intermediate_trades)` method
- `sdk/agentexchange/async_client.py` — Add async `batch_step_fast()` method
- `tradeready-gym/tradeready_gym/envs/base_trading_env.py` — Add `batch_size: int = 1` constructor param; when `batch_size > 1`, `step()` calls `/step/batch/fast`

## Acceptance Criteria
- [ ] `client.batch_step_fast(session_id, steps=500)` works and returns typed result
- [ ] `async_client.batch_step_fast(session_id, steps=500)` works
- [ ] Both SDK methods accept `include_intermediate_trades` param (default False)
- [ ] `base_trading_env.py` accepts `batch_size` in constructor
- [ ] When `batch_size > 1`, env `step()` calls the fast batch endpoint
- [ ] When `batch_size == 1` (default), behavior is unchanged (no breaking change)
- [ ] `ruff check` passes

## Dependencies
- **Task 01** must complete first (provides the API endpoint)

## Agent Instructions
1. Read `sdk/CLAUDE.md` for SDK client patterns
2. Read `tradeready-gym/CLAUDE.md` for gym env patterns
3. Follow existing SDK method patterns (error handling, response parsing, type hints)
4. The gym env change should be backwards-compatible — default `batch_size=1` preserves existing behavior

## Estimated Complexity
Medium — follows existing SDK patterns closely; gym change is a conditional branch in `step()`.
