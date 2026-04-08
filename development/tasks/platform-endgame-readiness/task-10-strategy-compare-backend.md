---
task_id: 10
title: "Implement Strategy Comparison API (endpoint + service)"
type: task
agent: "backend-developer"
phase: 2
depends_on: [4]
status: "done"
priority: "medium"
board: "[[platform-endgame-readiness/README]]"
files:
  - "src/api/routes/strategies.py"
  - "src/api/schemas/strategies.py"
  - "src/strategies/service.py"
  - "sdk/agentexchange/client.py"
  - "sdk/agentexchange/async_client.py"
tags:
  - task
  - strategies
  - comparison
  - phase-2
---

# Task 10: Implement Strategy Comparison API (endpoint + service)

## Assigned Agent: `backend-developer`

## Objective
Create a new endpoint that accepts a list of strategy IDs, fetches their latest test results, normalizes metrics, ranks them (including DSR), and returns a winner with recommendation.

## Context
The current `compare_versions` endpoint only compares 2 versions of the same strategy. Agents running autoresearch need to compare N different strategies and rank them. This uses the Deflated Sharpe from Improvement 2.

## Files to Modify/Create
- `src/strategies/service.py` — Add `compare_strategies(strategy_ids, ranking_metric)` method
- `src/api/routes/strategies.py` — Add `POST /api/v1/strategies/compare` endpoint
- `src/api/schemas/strategies.py` — Add `StrategyComparisonRequest` + `StrategyComparisonResponse` schemas
- `sdk/agentexchange/client.py` — Add `compare_strategies()` method
- `sdk/agentexchange/async_client.py` — Add async `compare_strategies()` method

## Acceptance Criteria
- [x] `POST /api/v1/strategies/compare` accepts `{ strategy_ids: [...], ranking_metric: "sharpe_ratio" }`
- [x] Validates 2-10 strategy IDs
- [x] Fetches latest test results for each strategy
- [x] Includes DSR data if available in test results
- [x] Ranks strategies by `ranking_metric` (default: sharpe_ratio)
- [x] Response includes: ranked strategies array, winner ID, recommendation text
- [x] Each strategy in response has: strategy_id, name, version, rank, metrics, deflated_sharpe (if available)
- [x] SDK methods in both clients
- [x] `ruff check` passes (pre-existing SDK errors excluded)

## Dependencies
- **Task 04** (Deflated Sharpe core) — uses DSR data from test results

## Agent Instructions
1. Read `src/strategies/CLAUDE.md` for service patterns
2. Read existing `compare_versions` in `src/api/routes/strategies.py` for patterns
3. The recommendation text should be a simple one-liner: "{name} ranks first by {metric} ({value}) and {passes/fails} the Deflated Sharpe test (p={p_value}). Consider deploying."
4. If no DSR data exists for a strategy, omit the `deflated_sharpe` field (make it Optional)

## Estimated Complexity
Medium — fetching and ranking is straightforward; the recommendation generation adds minor complexity.
