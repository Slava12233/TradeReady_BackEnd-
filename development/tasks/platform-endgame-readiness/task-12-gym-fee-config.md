---
task_id: 12
title: "Add configurable fee_rate to backtest sandbox + gym envs"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "done"
priority: "medium"
board: "[[platform-endgame-readiness/README]]"
files:
  - "src/backtesting/sandbox.py"
  - "src/backtesting/engine.py"
  - "src/api/schemas/backtest.py"
  - "src/api/routes/backtest.py"
  - "tradeready-gym/tradeready_gym/envs/base_trading_env.py"
  - "tradeready-gym/tradeready_gym/__init__.py"
  - "tradeready-gym/tradeready_gym/envs/multi_asset_env.py"
tags:
  - task
  - backtesting
  - gymnasium
  - phase-2
---

# Task 12: Add configurable fee_rate to backtest sandbox + gym envs

## Assigned Agent: `backend-developer`

## Objective
Make the backtest fee rate configurable (currently hardcoded at 0.1%) and register a custom portfolio gym environment with configurable symbols.

## Context
Improvement 5a+5b: The `BacktestSandbox` hardcodes `_FEE_FRACTION = Decimal("0.001")`. External agents need to test strategies with different fee models. Also, the portfolio env is hardcoded to BTC/ETH/SOL — agents need configurable symbols.

## Files to Modify/Create
- `src/backtesting/sandbox.py` — Add `fee_rate: Decimal` param to `__init__()`, replace hardcoded `_FEE_FRACTION`
- `src/backtesting/engine.py` — Add `fee_rate` to `BacktestConfig`, pass to sandbox
- `src/api/schemas/backtest.py` — Add optional `fee_rate` field to `BacktestCreateRequest` (default 0.001)
- `src/api/routes/backtest.py` — Pass `fee_rate` from request to config
- `tradeready-gym/tradeready_gym/envs/base_trading_env.py` — Add `fee_rate` constructor param
- `tradeready-gym/tradeready_gym/__init__.py` — Register `TradeReady-Portfolio-Custom-v0`
- `tradeready-gym/tradeready_gym/envs/multi_asset_env.py` — Accept `symbols` kwarg in registration

## Acceptance Criteria
- [x] `BacktestSandbox(fee_rate=Decimal("0.0005"))` uses the provided fee rate
- [x] Default remains `Decimal("0.001")` — no breaking change
- [x] `BacktestCreateRequest` accepts optional `fee_rate` field
- [x] API passes fee_rate through to engine config
- [x] Gym base env accepts `fee_rate` param, passes to API on session creation
- [x] `TradeReady-Portfolio-Custom-v0` registered with configurable `symbols` kwarg
- [x] `ruff check` and `mypy` pass

## Dependencies
None — can run in parallel with other Phase 2 tasks.

## Agent Instructions
1. Read `src/backtesting/CLAUDE.md` for sandbox and engine patterns
2. Read `tradeready-gym/CLAUDE.md` for gym registration patterns
3. The `_FEE_FRACTION` constant in sandbox.py should become an instance variable set from the constructor
4. Keep backward compatibility: all defaults match current behavior

## Estimated Complexity
Medium — threading a parameter through multiple layers (sandbox → engine → API → gym).
