---
task_id: 4
title: "SDK tools module"
agent: "backend-developer"
phase: 2
depends_on: [2, 3]
status: "completed"
priority: "high"
files:
  - "agent/tools/sdk_tools.py"
---

# Task 4: SDK tools module

## Assigned Agent: `backend-developer`

## Objective
Implement `agent/tools/sdk_tools.py` — SDK-based tools that wrap `AsyncAgentExchangeClient` methods as Pydantic AI tool functions.

## Context
The SDK is the primary integration for trading, market data, and account operations. Each tool function must follow Pydantic AI's `@agent.tool` pattern with `RunContext` as first arg.

## Files to Create
- `agent/tools/sdk_tools.py` — `get_sdk_tools(config: AgentConfig) -> list` function that returns tool functions:
  - `get_price(ctx, symbol)` — current price
  - `get_balance(ctx)` — account balance
  - `place_market_order(ctx, symbol, side, quantity)` — market order
  - `get_candles(ctx, symbol, interval, limit)` — OHLCV data
  - `get_performance(ctx)` — performance metrics
  - `get_positions(ctx)` — open positions
  - `get_trade_history(ctx, limit)` — recent trades

## Acceptance Criteria
- [ ] All 7 SDK tools implemented
- [ ] Each tool returns serializable dict/list (not Pydantic models — LLM needs plain data)
- [ ] Error handling wraps SDK exceptions with descriptive messages
- [ ] `AsyncAgentExchangeClient` instantiated once and shared across tools
- [ ] Type hints on all functions
- [ ] Google-style docstrings on each tool (the docstring becomes the tool description for the LLM)

## Dependencies
- Task 2 (config) — needs `AgentConfig` for credentials
- Task 3 (research) — needs exact SDK method signatures from `research-integration-surfaces.md`

## Agent Instructions
- Read `sdk/agentexchange/async_client.py` for the exact `AsyncAgentExchangeClient` API
- Read the research output at `development/tasks/tradeready-test-agent/research-integration-surfaces.md`
- Tools must return `dict` or `list[dict]`, not raw Pydantic models — LLMs need serializable data
- Use `Decimal` for quantities, convert to `str` in return values
- Wrap all SDK calls in try/except, returning `{"error": str(e)}` on failure

## Estimated Complexity
Medium — 7 tool functions with error handling
