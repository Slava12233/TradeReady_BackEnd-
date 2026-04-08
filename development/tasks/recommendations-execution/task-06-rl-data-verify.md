---
task_id: 6
title: "Verify training data and set up RL environment"
type: task
agent: "ml-engineer"
phase: 2
depends_on: [3]
status: "pending"
priority: "high"
board: "[[recommendations-execution/README]]"
files: []
tags:
  - task
  - ml
  - rl-training
  - data
---

# Task 06: Verify Training Data and Set Up RL Environment

## Assigned Agent: `ml-engineer`

## Objective
Verify BTCUSDT candle data exists in the database (6+ months hourly), install SB3, and test the headless gym environment works.

## Context
R2 from the C-level report. Before training, must confirm data availability and env setup.

## Acceptance Criteria
- [ ] `candles_backfill` has >= 6 months of BTCUSDT hourly data (2024-07-01 to 2025-01-01)
- [ ] If insufficient data, `scripts/backfill_history.py --symbols BTCUSDT --hourly --resume` run
- [ ] `stable-baselines3>=2.0` and `tensorboard` installed
- [ ] `gym.make("TradeReady-BTC-Headless-v0", db_url=...)` creates successfully
- [ ] `env.reset()` returns valid observation
- [ ] `env.step(action)` works for 10 steps

## Dependencies
- **Task 3** (deploy complete, DB with migration 023 applied)

## Agent Instructions
1. Check candle data via Docker exec psql query
2. Run backfill if needed
3. Test headless env creation and basic step loop
4. Report data counts and env observation shape

## Estimated Complexity
Medium — data verification + potential backfill.
