---
task_id: C-03
title: "Run single observe cycle"
type: task
agent: "ml-engineer"
track: C
depends_on: ["C-02"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["agent/trading/loop.py"]
tags:
  - task
  - trading
  - integration
  - critical-path
---

# Task C-03: Run single observe cycle

## Assigned Agent: `ml-engineer`

## Objective
Execute one `TradingLoop.observe()` cycle and confirm price data, portfolio state, and regime detection all return valid data.

## Context
The TradingLoop follows: observe → decide → execute → monitor → journal → learn. We test each step incrementally to isolate bugs. This is the first step.

## Files to Reference
- `agent/trading/loop.py` — TradingLoop implementation
- `agent/strategies/regime/` — Regime detection

## Acceptance Criteria
- [ ] `TradingLoop.observe()` completes without errors
- [ ] Returns current price data for target pairs
- [ ] Returns portfolio state (positions, balance)
- [ ] Regime detection returns a valid market regime classification
- [ ] No database connection issues
- [ ] Observation data matches expected schema

## Dependencies
- **C-02**: SDK connectivity verified

## Agent Instructions
Read `agent/trading/CLAUDE.md` and `agent/trading/loop.py` to understand the observe cycle. Initialize a TradingLoop with the test agent's credentials and call `observe()`. Check that all data sources respond: price feed, portfolio tracker, regime classifier. If regime detection fails, it may need the trained model from Track B — check if it falls back to a default regime.

## Estimated Complexity
Medium — first integration test of the trading pipeline.
