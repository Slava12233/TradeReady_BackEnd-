---
task_id: C-04
title: "Run single decide cycle"
type: task
agent: "ml-engineer"
track: C
depends_on: ["C-03"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["agent/trading/loop.py", "agent/strategies/risk/"]
tags:
  - task
  - trading
  - integration
  - critical-path
---

# Task C-04: Run single decide cycle

## Assigned Agent: `ml-engineer`

## Objective
Execute `TradingLoop.decide()` with the risk overlay and confirm signal generation and veto pipeline work correctly.

## Context
The decide step takes observations from C-03 and generates trading signals. The risk overlay (VetoPipeline, DynamicSizer) can modify or reject signals based on risk parameters.

## Files to Reference
- `agent/trading/loop.py` — decide cycle
- `agent/strategies/risk/` — VetoPipeline, DynamicSizer, RiskMiddleware

## Acceptance Criteria
- [ ] `TradingLoop.decide()` completes without errors
- [ ] Returns a trading signal (buy/sell/hold) with confidence
- [ ] Risk overlay processes the signal (may veto or resize)
- [ ] Position sizing is within the agent's risk limits
- [ ] Signal includes target pair, direction, and size
- [ ] VetoPipeline logs its decision (approve/veto with reason)

## Dependencies
- **C-03**: Observe cycle must return valid data

## Agent Instructions
Read `agent/strategies/risk/CLAUDE.md` for the risk overlay architecture. Call `decide()` after `observe()`. The risk overlay should run automatically. If the signal is vetoed, that's a valid outcome — document why (e.g., position too large, drawdown limit hit). Try different market conditions if needed.

## Estimated Complexity
Medium — integration of signal generation + risk management.
