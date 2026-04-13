---
task_id: C-05
title: "Execute first live trade"
type: task
agent: "ml-engineer"
track: C
depends_on: ["C-04"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["agent/trading/executor.py", "agent/trading/loop.py"]
tags:
  - task
  - trading
  - integration
  - critical-path
  - milestone
---

# Task C-05: Execute first live trade

## Assigned Agent: `ml-engineer`

## Objective
Execute a single market buy order (minimum size) through `TradingLoop.execute()`. This is the platform's **first ever trade**.

## Context
This is a milestone moment — the platform has 5,130+ tests and 127 API endpoints but zero executed trades. This task bridges the gap.

## Files to Reference
- `agent/trading/executor.py` — TradeExecutor (SDK-backed order placement)
- `agent/trading/loop.py` — execute cycle

## Acceptance Criteria
- [ ] Market buy order submitted through the TradeExecutor
- [ ] Order uses minimum allowed size
- [ ] Order confirmation received from the platform
- [ ] Trade ID returned
- [ ] No errors in the execution pipeline
- [ ] Agent balance decremented by trade cost

## Dependencies
- **C-04**: Decide cycle must produce an actionable signal (not vetoed)

## Agent Instructions
If C-04's signal was vetoed by the risk overlay, you may need to:
1. Use a more permissive risk profile temporarily
2. Or manually call `execute()` with a small buy signal

Use the minimum position size to minimize risk. Target BTCUSDT as it has the most data. After execution, immediately check the agent's balance to confirm it was deducted.

## Estimated Complexity
High — first real trade execution. Integration bugs are the primary risk.
