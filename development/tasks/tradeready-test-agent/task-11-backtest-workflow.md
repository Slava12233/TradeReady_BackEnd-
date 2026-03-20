---
task_id: 11
title: "Backtest workflow"
agent: "backend-developer"
phase: 5
depends_on: [6, 7, 8]
status: "completed"
priority: "high"
files:
  - "agent/workflows/backtest_workflow.py"
---

# Task 11: Backtest workflow

## Assigned Agent: `backend-developer`

## Objective
Implement the backtest workflow: create a backtest session → trade in the sandbox → analyze results → generate improvement plan.

## Files to Create
- `agent/workflows/backtest_workflow.py` — `async def run_backtest_workflow(config: AgentConfig) -> WorkflowResult`:

  **Steps:**
  1. REST: `GET /api/v1/market/data-range` — find available historical data window
  2. REST: `POST /api/v1/backtest/create` — create 7-day session for BTC+ETH
  3. REST: `POST /api/v1/backtest/{id}/start` — initialize sandbox
  4. Loop ~100 steps:
     a. REST: get candles at current virtual time
     b. Agent analyzes candle data and decides: buy/sell/hold
     c. If trading: REST: `POST /api/v1/backtest/{id}/trade/order`
     d. REST: `POST /api/v1/backtest/{id}/step/batch` — advance 5 candles
  5. REST: `GET /api/v1/backtest/{id}/results` — get final metrics
  6. Agent analyzes: Sharpe ratio, max drawdown, win rate via `output_type=BacktestAnalysis`
  7. Agent proposes improvement plan
  8. Return `WorkflowResult` with backtest metrics and improvement plan

## Acceptance Criteria
- [ ] Full backtest lifecycle from create to results
- [ ] Agent makes trading decisions during the backtest loop
- [ ] Uses `PlatformRESTClient` for all backtest API calls
- [ ] LLM generates structured `BacktestAnalysis` with improvement plan
- [ ] Handles edge cases: no data available, backtest already completed
- [ ] Step count and batch size are configurable
- [ ] Results include all metrics (Sharpe, drawdown, win rate, PnL)

## Dependencies
- Task 6 (REST tools for backtest endpoints)
- Task 7 (BacktestAnalysis model)
- Task 8 (system prompt)

## Agent Instructions
- Read `src/backtesting/CLAUDE.md` for backtest lifecycle details
- The backtest loop uses REST tools directly (not via LLM tool calls — too slow)
- Use the LLM only for trade decisions and final analysis
- Batch steps (advance 5 candles at a time) for efficiency
- The data-range endpoint tells you what time window has data — use it to set start/end

## Estimated Complexity
High — complex loop with REST calls, LLM decisions, and result analysis
