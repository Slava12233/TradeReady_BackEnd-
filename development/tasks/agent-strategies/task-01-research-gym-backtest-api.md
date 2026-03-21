---
task_id: 01
title: "Research gym environments & backtest API surface"
type: task
agent: "codebase-researcher"
phase: A
depends_on: []
status: "completed"
board: "[[agent-strategies/README]]"
priority: "high"
files: ["tradeready-gym/", "src/backtesting/", "src/strategies/indicators.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 01: Research gym environments & backtest API surface

## Assigned Agent: `codebase-researcher`

## Objective
Map the exact interface between the Gymnasium environments and the backtest API. Document: which API calls each env makes per step, what observation features are available, how reward functions work, and what the `TrainingTracker` reports.

## Context
Before building the PPO training pipeline (Task 02), we need to understand exactly what `tradeready-gym` provides and what gaps exist. The CTO brief estimates ~8 API calls per step — verify this.

## Files to Read
- `tradeready-gym/tradeready_gym/envs/base_trading_env.py` — base env logic, `reset()` and `step()` implementations
- `tradeready-gym/tradeready_gym/envs/multi_asset_env.py` — portfolio env (action = weight targets)
- `tradeready-gym/tradeready_gym/rewards/` — all 4 reward functions
- `tradeready-gym/tradeready_gym/wrappers/` — all 3 wrappers
- `tradeready-gym/tradeready_gym/utils/training_tracker.py` — what it reports
- `tradeready-gym/tradeready_gym/utils/observation_builder.py` — feature construction
- `src/backtesting/engine.py` — how backtest sessions are created/stepped
- `src/strategies/indicators.py` — available indicators (RSI, MACD, SMA, EMA, BB, ADX, ATR)

## Acceptance Criteria
- [ ] Document: exact API calls per `env.reset()` (count and endpoints)
- [ ] Document: exact API calls per `env.step()` for HOLD vs BUY/SELL actions
- [ ] Document: observation space dimensions for 5-asset portfolio with all features
- [ ] Document: how each reward function computes its value (formula)
- [ ] Document: what wrappers add to observation space
- [ ] Document: TrainingTracker payload (what fields, when sent)
- [ ] Identify any gaps: missing features, broken integrations, version mismatches
- [ ] Write findings to `development/agent-development/gym-api-research.md`

## Dependencies
None — this is the starting task.

## Agent Instructions
Focus on concrete numbers: how many API calls, how many features, how many bytes. The ml-engineer will use your findings to configure the training pipeline. Don't speculate — read the actual code.

## Estimated Complexity
Medium — extensive reading but no code changes.
