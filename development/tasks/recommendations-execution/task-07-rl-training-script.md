---
task_id: 7
title: "Create PPO BTC training script"
type: task
agent: "ml-engineer"
phase: 2
depends_on: [6]
status: "pending"
priority: "high"
board: "[[recommendations-execution/README]]"
files:
  - "scripts/train_ppo_btc.py"
tags:
  - task
  - ml
  - rl-training
  - ppo
---

# Task 07: Create PPO BTC Training Script

## Assigned Agent: `ml-engineer`

## Objective
Create `scripts/train_ppo_btc.py` — a complete PPO training script using the headless gym env with batch stepping, composite reward, and OOS evaluation with DSR validation.

## Context
R2 from the C-level report. The plan at `development/recommendations-execution-plan.md` Section R2 has the full config and requirements.

## Files to Modify/Create
- `scripts/train_ppo_btc.py` — Full training script

## Acceptance Criteria
- [ ] Uses `TradeReady-BTC-Headless-v0` with `db_url` from env var
- [ ] Applies `BatchStepWrapper(n_steps=5)` + `NormalizationWrapper`
- [ ] Uses `CompositeReward` (0.4 sortino + 0.3 pnl + 0.2 activity + 0.1 drawdown)
- [ ] PPO with MlpPolicy, 500K timesteps, CPU-friendly hyperparameters
- [ ] TensorBoard logging to `logs/ppo_btc_v1`
- [ ] Saves model to `models/ppo_btc_v1.zip`
- [ ] OOS evaluation (2025-01-01 to 2025-03-01) for 10 episodes
- [ ] Prints summary: avg reward, Sharpe, max drawdown, win rate
- [ ] Validates with Deflated Sharpe Ratio (calls platform API)
- [ ] `if __name__ == "__main__"` block
- [ ] `ruff check` passes

## Dependencies
- **Task 6** (data verified, env tested)

## Agent Instructions
1. Read `development/recommendations-execution-plan.md` Section R2 for the full config
2. Read `sdk/examples/rl_training.py` for a reference pattern
3. Read `tradeready-gym/CLAUDE.md` for env and wrapper patterns
4. Use `os.environ["DATABASE_URL"]` for DB connection
5. Training config from the plan: 500K steps, lr=3e-4, n_steps=2048, batch_size=64, episode_length=720

## Estimated Complexity
High — complete training pipeline with evaluation and validation.
