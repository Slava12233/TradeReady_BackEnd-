---
task_id: 5
title: "Auto-compute DSR on test completion + SDK methods"
type: task
agent: "backend-developer"
phase: 1
depends_on: [4]
status: "done"
priority: "medium"
board: "[[platform-endgame-readiness/README]]"
files:
  - "src/strategies/test_aggregator.py"
  - "sdk/agentexchange/client.py"
  - "sdk/agentexchange/async_client.py"
tags:
  - task
  - metrics
  - strategies
  - sdk
  - phase-1
---

# Task 05: Auto-compute DSR on test completion + SDK methods

## Assigned Agent: `backend-developer`

## Objective
Wire the Deflated Sharpe computation into the strategy test completion flow (auto-computed and stored in results JSONB) and add SDK client methods.

## Context
Task 04 creates the core DSR service. This task integrates it: (1) auto-compute when strategy tests complete, (2) expose via SDK for programmatic access.

## Files to Modify/Create
- `src/strategies/test_aggregator.py` — After computing standard metrics, if `len(episode_sharpes) >= 2`, compute DSR and store in `results["deflated_sharpe"]`. Use number of strategy versions tested as `num_trials`.
- `sdk/agentexchange/client.py` — Add `compute_deflated_sharpe(returns, num_trials, annualization_factor)` method
- `sdk/agentexchange/async_client.py` — Add async `compute_deflated_sharpe()` method

## Acceptance Criteria
- [x] Strategy test completion auto-computes DSR when >= 2 episode Sharpes exist
- [x] DSR result stored in `StrategyTestRun.results["deflated_sharpe"]` JSONB field
- [x] `num_trials` defaults to count of strategy versions for this strategy
- [x] SDK `compute_deflated_sharpe()` calls the REST endpoint and returns typed result
- [x] No breaking changes to existing test completion flow
- [x] `ruff check` passes

## Dependencies
- **Task 04** must complete first (provides `compute_deflated_sharpe()` function)

## Agent Instructions
1. Read `src/strategies/CLAUDE.md` for strategy service patterns
2. Read `src/strategies/test_aggregator.py` to find the test completion hook
3. Import `compute_deflated_sharpe` from `src/metrics/deflated_sharpe`
4. Follow existing SDK method patterns for the client methods

## Estimated Complexity
Low — straightforward integration point + SDK method following existing patterns.
