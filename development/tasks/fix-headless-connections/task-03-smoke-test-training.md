---
task_id: 3
title: "Smoke test PPO training inside Docker"
type: task
agent: "ml-engineer"
phase: 2
depends_on: [1, 2]
status: "pending"
priority: "high"
board: "[[fix-headless-connections/README]]"
files: []
tags:
  - task
  - ml
  - rl-training
  - e2e
---

# Task 03: Smoke Test PPO Training Inside Docker

## Assigned Agent: `ml-engineer`

## Objective
Run the training script inside Docker with the fixed headless env and verify it completes without connection errors.

## Context
Tasks 1-2 fix the headless env and update tests. This task validates the fix works end-to-end with real DB queries and SB3 PPO.

## Steps
1. Copy fixed `headless_env.py` into the API container
2. Reinstall tradeready-gym in the container
3. Run: `python scripts/train_ppo_btc.py --timesteps 2048 --eval-episodes 1 --skip-dsr`
4. Verify output shows training progress, model saved, no errors

## Acceptance Criteria
- [ ] Training starts and prints "Training PPO for 2,048 timesteps..."
- [ ] PPO completes 1 rollout (2048 steps) without errors
- [ ] No `QueuePool limit reached` in output
- [ ] No `Event loop is closed` in output
- [ ] Model saved message appears
- [ ] OOS evaluation completes (1 episode)
- [ ] Exit code 0

## Agent Instructions
1. Copy files into container: `docker cp tradeready-gym aitradingagent-api-1:/app/tradeready-gym`
2. Install: `docker compose exec api pip install /app/tradeready-gym/ --force-reinstall --no-deps`
3. Copy script: `docker cp scripts/train_ppo_btc.py aitradingagent-api-1:/app/scripts/`
4. Run with env vars: `DATABASE_URL=postgresql+asyncpg://agentexchange:<password>@timescaledb:5432/agentexchange PYTHONPATH=/app`
5. Check password in `.env` file (`POSTGRES_PASSWORD` field)

## Estimated Complexity
Low — running existing script against fixed code.
