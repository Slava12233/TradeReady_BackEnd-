---
task_id: B-01
title: "Verify gym installation"
type: task
agent: "ml-engineer"
track: B
depends_on: ["A-05"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["tradeready-gym/", "scripts/train_ppo_btc.py"]
tags:
  - task
  - ml
  - gym
  - setup
---

# Task B-01: Verify gym installation

## Assigned Agent: `ml-engineer`

## Objective
Install `tradeready-gym` in editable mode and verify all dependencies (stable-baselines3, tensorboard) are available.

## Context
Track B requires the Gymnasium environments and SB3 for PPO training. The gym package was recently fixed for connection pool exhaustion (commit 881e27f).

## Commands
```bash
pip install -e tradeready-gym/
pip install "stable-baselines3>=2.0" tensorboard
```

## Acceptance Criteria
- [ ] `pip install -e tradeready-gym/` succeeds
- [ ] `python -c "import tradeready_gym; print(tradeready_gym.__version__)"` works
- [ ] `python -c "import stable_baselines3; print(stable_baselines3.__version__)"` shows >= 2.0
- [ ] `python -c "import tensorboard"` succeeds
- [ ] `python -c "import gymnasium; env = gymnasium.make('TradeReady-BTC-Headless-v0'); print(env)"` creates the environment

## Dependencies
- **A-05**: Hourly data must be loaded (the headless env reads from `candles_backfill`)

## Agent Instructions
Read `tradeready-gym/CLAUDE.md` first for package structure. Install in editable mode. If import fails, check for missing dependencies in `tradeready-gym/pyproject.toml`. The headless env requires a database connection — ensure Docker services are running.

## Estimated Complexity
Low — package installation and verification.
