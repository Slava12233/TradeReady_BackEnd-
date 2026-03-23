---
task_id: 24
title: "Add enhanced signal generation tools (ticker, PnL)"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "medium"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/tools/sdk_tools.py", "agent/trading/signal_generator.py"]
tags:
  - task
  - tools
  - signals
---

# Task 24: Enhanced signal generation tools

## Assigned Agent: `backend-developer`

## Objective
Add `get_ticker()` and `get_pnl()` SDK tools. Add volume-weighted signal confirmation to `SignalGenerator`.

## Changes
1. Add `get_ticker(symbol)` tool — returns 24h volume, high, low, change%
2. Add `get_pnl(period)` tool — returns realized PnL breakdown
3. In `SignalGenerator`: after generating a signal, confirm with volume (reject if volume < 50% of 20-period average)
4. Adjust confidence threshold to 0.55 (from 0.5)

## Acceptance Criteria
- [ ] 2 new SDK tools registered and working
- [ ] Volume confirmation filter in SignalGenerator
- [ ] Confidence threshold configurable (default 0.55)
- [ ] Tests for volume filter logic

## Estimated Complexity
Low — adding tools + simple volume check.
