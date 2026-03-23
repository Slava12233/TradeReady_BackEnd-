---
task_id: 20
title: "Add advanced order type tools (limit, stop-loss, take-profit, cancel)"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/tools/sdk_tools.py"]
tags:
  - task
  - tools
  - trading
---

# Task 20: Advanced order type tools

## Assigned Agent: `backend-developer`

## Objective
Expose 6 additional SDK methods as agent tools: `place_limit_order`, `place_stop_loss`, `place_take_profit`, `cancel_order`, `cancel_all_orders`, `get_open_orders`.

## Context
Currently the agent can only place market orders. For aggressive trading with 10% monthly target, the agent needs stop-losses (risk management), take-profits (capture gains), and limit orders (better entries).

## Files to Modify
- `agent/tools/sdk_tools.py` — add 6 new tool functions following existing pattern

## Pattern to Follow (from existing `place_market_order` tool):
```python
async def place_limit_order(symbol: str, side: str, quantity: str, price: str) -> str:
    async with log_api_call("sdk", "place_limit_order"):
        async with AsyncAgentExchangeClient(...) as client:
            result = await client.place_limit_order(symbol, side, quantity, price)
            return json.dumps(result, default=str)
```

## Acceptance Criteria
- [ ] 6 new tools registered in `get_sdk_tools(config)`
- [ ] Each tool wrapped in `log_api_call()` context manager
- [ ] Tools handle errors gracefully (return error string, don't raise)
- [ ] Tests for each new tool
- [ ] `PositionMonitor` can use stop-loss/take-profit tools

## Estimated Complexity
Low — following existing pattern for 6 similar functions.
