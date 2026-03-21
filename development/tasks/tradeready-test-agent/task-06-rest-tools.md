---
task_id: 6
title: "REST tools module (backtest, strategy, battle)"
type: task
agent: "backend-developer"
phase: 2
depends_on: [2, 3]
status: "completed"
board: "[[tradeready-test-agent/README]]"
priority: "high"
files:
  - "agent/tools/rest_tools.py"
tags:
  - task
  - testing-agent
---

# Task 6: REST tools module

## Assigned Agent: `backend-developer`

## Objective
Implement `agent/tools/rest_tools.py` — `PlatformRESTClient` class for endpoints not covered by the SDK (backtesting, strategies, battles).

## Context
The SDK covers trading and market data but not backtesting, strategy management, or battle workflows. These require direct REST calls via httpx.

## Files to Create
- `agent/tools/rest_tools.py` — `PlatformRESTClient` class with async methods:

  **Backtest methods:**
  - `create_backtest(start_time, end_time, symbols, interval)` → POST `/api/v1/backtest/create`
  - `start_backtest(session_id)` → POST `/api/v1/backtest/{id}/start`
  - `step_backtest_batch(session_id, steps)` → POST `/api/v1/backtest/{id}/step/batch`
  - `backtest_trade(session_id, symbol, side, quantity)` → POST `/api/v1/backtest/{id}/trade/order`
  - `get_backtest_results(session_id)` → GET `/api/v1/backtest/{id}/results`
  - `get_backtest_candles(session_id, symbol)` → GET `/api/v1/backtest/{id}/market/candles/{symbol}`

  **Strategy methods:**
  - `create_strategy(name, description, definition)` → POST `/api/v1/strategies`
  - `test_strategy(strategy_id)` → POST `/api/v1/strategies/{id}/test`
  - `get_test_results(strategy_id, test_id)` → GET `/api/v1/strategies/{id}/tests/{test_id}`
  - `create_version(strategy_id, definition)` → POST `/api/v1/strategies/{id}/versions`
  - `compare_versions(strategy_id)` → GET `/api/v1/strategies/{id}/compare-versions`

  Also: `get_rest_tools(config) -> list` function returning Pydantic AI tool functions wrapping the client.

## Acceptance Criteria
- [ ] `PlatformRESTClient` class with all listed methods
- [ ] Uses `httpx.AsyncClient` with 30s timeout
- [ ] Auth via `X-API-Key` header on all requests
- [ ] Error handling: `raise_for_status()` wrapped with descriptive error messages
- [ ] `get_rest_tools()` returns tool functions compatible with Pydantic AI
- [ ] Type hints and docstrings on all methods

## Dependencies
- Task 2 (config) — needs `AgentConfig` for base URL and API key
- Task 3 (research) — needs exact endpoint paths and request/response shapes

## Agent Instructions
- Read `src/api/routes/backtest_routes.py` for exact endpoint definitions
- Read `src/api/routes/strategy_routes.py` for strategy endpoints
- Read the research output at `development/tasks/tradeready-test-agent/research-integration-surfaces.md`
- Use `httpx.AsyncClient` (not `aiohttp`)
- The client should be created once and reused (store as instance var)
- Add an `async def close()` method for cleanup

## Estimated Complexity
Medium — multiple endpoints with request/response handling
