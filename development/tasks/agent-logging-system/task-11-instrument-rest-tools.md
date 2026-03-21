---
task_id: 11
title: "Instrument REST tools with API call logging"
type: task
agent: "backend-developer"
phase: 2
depends_on: [9]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/tools/rest_tools.py"]
tags:
  - task
  - agent
  - logging
---

# Task 11: Instrument REST Tools

## Assigned Agent: `backend-developer`

## Objective
Wrap all 11 `PlatformRESTClient` methods with `log_api_call("rest", ...)`.

## Files to Modify
- `agent/tools/rest_tools.py` — add logging to all REST methods

## The 11 Methods to Instrument

**Backtest lifecycle (6):**
1. `create_backtest(...)` — POST `/api/v1/backtest/create`
2. `start_backtest(id)` — POST `/api/v1/backtest/{id}/start`
3. `step_backtest_batch(id, steps)` — POST `/api/v1/backtest/{id}/step/batch`
4. `backtest_trade(id, ...)` — POST `/api/v1/backtest/{id}/trade/order`
5. `get_backtest_results(id)` — GET `/api/v1/backtest/{id}/results`
6. `get_backtest_candles(id, symbol)` — GET `/api/v1/backtest/{id}/market/candles/{symbol}`

**Strategy management (5):**
7. `create_strategy(...)` — POST `/api/v1/strategies`
8. `test_strategy(id, ...)` — POST `/api/v1/strategies/{id}/test`
9. `get_test_results(id, test_id)` — GET `/api/v1/strategies/{id}/tests/{test_id}`
10. `create_version(id, ...)` — POST `/api/v1/strategies/{id}/versions`
11. `compare_versions(id, v1, v2)` — GET `/api/v1/strategies/{id}/compare-versions`

## Acceptance Criteria
- [ ] All 11 methods wrapped with `log_api_call("rest", endpoint, method=...)`
- [ ] HTTP method and endpoint path logged for each
- [ ] Response status code captured in `ctx["response_status"]`
- [ ] `ruff check agent/tools/rest_tools.py` passes

## Estimated Complexity
Low — same pattern as Task 10, 11 instances
