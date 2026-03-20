---
task_id: 10
title: "Trading workflow"
agent: "backend-developer"
phase: 5
depends_on: [4, 7, 8]
status: "completed"
priority: "high"
files:
  - "agent/workflows/trading_workflow.py"
---

# Task 10: Trading workflow

## Assigned Agent: `backend-developer`

## Objective
Implement the full trading lifecycle workflow: analyze market data → generate trade signal → execute trade → monitor position → close → evaluate.

## Files to Create
- `agent/workflows/trading_workflow.py` — `async def run_trading_workflow(config: AgentConfig) -> WorkflowResult`:

  **Steps:**
  1. Fetch 1h candles for BTC, ETH, SOL (last 100 candles each)
  2. Agent analyzes trends (moving averages, momentum, support/resistance)
  3. Agent generates `TradeSignal` with reasoning via `output_type=TradeSignal`
  4. Validate signal (check confidence threshold, position size limits)
  5. Execute the trade via SDK
  6. Monitor position — check price 3 times with 10s delay
  7. Close position
  8. Check PnL and performance metrics
  9. Agent evaluates: did the analysis help? Generate `MarketAnalysis`
  10. Return `WorkflowResult` with trade details and evaluation

## Acceptance Criteria
- [ ] Full trade lifecycle from analysis to close
- [ ] LLM generates structured `TradeSignal` output
- [ ] Position size respects `max_trade_pct` config limit
- [ ] Monitoring loop with configurable interval
- [ ] Performance comparison (before trade vs after)
- [ ] Structured evaluation of whether analysis was helpful
- [ ] Error recovery: if trade fails, report but don't crash

## Dependencies
- Task 4 (SDK tools for trading and market data)
- Task 7 (TradeSignal, MarketAnalysis models)
- Task 8 (system prompt)

## Agent Instructions
- Create a Pydantic AI Agent with `output_type=TradeSignal` for the decision step
- Use a separate agent call with `output_type=MarketAnalysis` for evaluation
- The monitoring loop should use `asyncio.sleep(10)` between checks
- Max trade quantity = balance × max_trade_pct / current_price
- Log all decisions and trades with structlog

## Estimated Complexity
High — multi-step workflow with LLM decision-making and trade lifecycle
