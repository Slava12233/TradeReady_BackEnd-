---
task_id: 1
title: "Implement step_batch_fast() engine method + API endpoint"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[platform-endgame-readiness/README]]"
files:
  - "src/backtesting/engine.py"
  - "src/api/routes/backtest.py"
  - "src/api/schemas/backtest.py"
  - "src/main.py"
tags:
  - task
  - backtesting
  - performance
  - phase-1
---

# Task 01: Implement step_batch_fast() engine method + API endpoint

## Assigned Agent: `backend-developer`

## Objective
Create an optimized batch stepping method for the backtest engine that eliminates per-step overhead (snapshots, DB writes, portfolio computation) and a corresponding API endpoint.

## Context
RL training makes 500K+ individual HTTP calls (one `POST /step` per candle). The existing `step_batch()` at `src/backtesting/engine.py:369-405` just loops `step()` internally with full per-step overhead. This task creates `step_batch_fast()` that defers all expensive operations to the end of the batch.

## Files to Modify/Create
- `src/backtesting/engine.py` — Add `BatchStepResult` frozen dataclass (slots=True) + `step_batch_fast()` async method
- `src/api/routes/backtest.py` — Add `POST /api/v1/backtest/{session_id}/step/batch/fast` endpoint
- `src/api/schemas/backtest.py` — Add `BacktestStepBatchFastRequest` + `BatchStepFastResponse` Pydantic v2 schemas

## Acceptance Criteria
- [ ] `BatchStepResult` dataclass exists with fields: virtual_time, step, total_steps, progress_pct, prices, orders_filled, portfolio, is_complete, remaining_steps, steps_executed
- [ ] `step_batch_fast()` defers snapshots to only fills + final step
- [ ] `step_batch_fast()` does single DB progress write at end of batch
- [ ] `step_batch_fast()` skips intermediate `get_portfolio()` — computes once at end
- [ ] `step_batch_fast()` accumulates order fills into a flat list
- [ ] `include_intermediate_trades` param controls whether fill details are returned
- [ ] API endpoint accepts `{ "steps": N, "include_intermediate_trades": bool }` body
- [ ] API endpoint returns `BatchStepFastResponse` with all fields
- [ ] `ruff check` passes on all modified files
- [ ] `mypy` passes on all modified files

## Dependencies
None — this is a Phase 1 task with no prerequisites.

## Agent Instructions
1. Read `src/backtesting/CLAUDE.md` for engine patterns and sandbox architecture
2. Read `src/api/routes/CLAUDE.md` for route patterns (auth, error handling, response shapes)
3. Read existing `step_batch()` at `engine.py:369-405` to understand current approach
4. Read existing `StepResult` and `PortfolioSummary` types to match conventions
5. Use `Decimal` for all financial values (never float)
6. Follow existing route decorator patterns (tags, response_model, status_code)
7. The key optimization: defer snapshot/DB/portfolio to batch end, accumulate fills in a plain list

## Estimated Complexity
High — requires understanding the backtest engine's inner loop, snapshot timing, and DB write patterns to correctly defer operations without losing data integrity.
