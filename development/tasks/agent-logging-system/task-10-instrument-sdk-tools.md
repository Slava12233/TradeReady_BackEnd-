---
task_id: 10
title: "Instrument SDK tools with API call logging"
type: task
agent: "backend-developer"
phase: 2
depends_on: [9]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/tools/sdk_tools.py"]
tags:
  - task
  - agent
  - logging
---

# Task 10: Instrument SDK Tools

## Assigned Agent: `backend-developer`

## Objective
Wrap all 7 SDK tool functions in `agent/tools/sdk_tools.py` with the `log_api_call("sdk", ...)` context manager.

## Files to Modify
- `agent/tools/sdk_tools.py` — add `log_api_call` wrapper to each tool

## The 7 Tools to Instrument
1. `get_price(symbol)` — endpoint: `"get_price"`
2. `get_candles(symbol, interval, limit)` — endpoint: `"get_candles"`
3. `get_balance()` — endpoint: `"get_balance"`
4. `get_positions()` — endpoint: `"get_positions"`
5. `get_performance(period)` — endpoint: `"get_performance"`
6. `get_trade_history(limit)` — endpoint: `"get_trade_history"`
7. `place_market_order(symbol, side, quantity)` — endpoint: `"place_market_order"`

## Implementation Pattern
```python
async def get_price(symbol: str) -> dict:
    async with log_api_call("sdk", "get_price", symbol=symbol) as ctx:
        result = await client.get_price(symbol)
        ctx["response_status"] = 200
        return result
```

## Acceptance Criteria
- [ ] All 7 tool functions wrapped with `log_api_call`
- [ ] Each call includes relevant context kwargs (symbol, side, etc.)
- [ ] Error handling preserved (tools return `{"error": "..."}` on failure)
- [ ] Existing tool behavior unchanged
- [ ] `ruff check agent/tools/sdk_tools.py` passes

## Agent Instructions
- Read `agent/tools/sdk_tools.py` fully first
- Tools currently catch exceptions and return `{"error": "..."}` dicts — the `log_api_call` wrapper should be INSIDE the existing try/except, not outside
- Import `log_api_call` from `agent.logging_middleware`

## Estimated Complexity
Low — repetitive wrapping pattern, 7 instances
