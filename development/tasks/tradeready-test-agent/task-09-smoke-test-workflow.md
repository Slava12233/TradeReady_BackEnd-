---
task_id: 9
title: "Smoke test workflow"
type: task
agent: "backend-developer"
phase: 5
depends_on: [4, 5, 6, 7, 8]
status: "completed"
board: "[[tradeready-test-agent/README]]"
priority: "high"
files:
  - "agent/workflows/smoke_test.py"
tags:
  - task
  - testing-agent
---

# Task 9: Smoke test workflow

## Assigned Agent: `backend-developer`

## Objective
Implement the smoke test workflow — a 10-step connectivity validation that exercises all three integration methods (SDK, MCP, REST).

## Files to Create
- `agent/workflows/smoke_test.py` — `async def run_smoke_test(config: AgentConfig) -> WorkflowResult`:

  **Steps:**
  1. SDK: `get_price("BTCUSDT")` — verify non-zero price
  2. SDK: `get_balance()` — verify starting balance exists
  3. SDK: `get_candles("BTCUSDT", "1h", 10)` — verify historical data available
  4. SDK: `place_market_order("BTCUSDT", "buy", "0.0001")` — tiny test trade
  5. SDK: `get_positions()` — verify position opened
  6. SDK: `get_trade_history()` — verify trade recorded
  7. SDK: `get_performance()` — verify metrics calculate
  8. REST: `GET /api/v1/health` — verify platform health
  9. REST: `GET /api/v1/market/prices` — verify market data accessible
  10. Report: return structured `WorkflowResult`

  The workflow creates a Pydantic AI agent with SDK tools, sends it the task prompt, and collects structured output.

## Acceptance Criteria
- [ ] All 10 steps implemented
- [ ] Each step validates the response (not just calls — checks return values)
- [ ] Failures are caught and recorded (workflow doesn't crash on single step failure)
- [ ] Returns `WorkflowResult` with pass/fail status, findings, and bugs
- [ ] Logs each step with structlog
- [ ] Tiny trade amount (0.0001 BTC) to minimize impact

## Dependencies
- Tasks 4, 5, 6 (tool modules)
- Task 7 (output models for WorkflowResult)
- Task 8 (system prompt)

## Agent Instructions
- The workflow function creates its own Pydantic AI Agent instance with SDK tools
- Use `agent.run()` with a structured prompt for each step
- Alternatively, implement steps as direct SDK/REST calls (no LLM needed for basic connectivity)
- Consider a hybrid: direct calls for validation, LLM for analysis of results
- Use `structlog` for logging each step

## Estimated Complexity
Medium — 10 steps with validation and error handling
