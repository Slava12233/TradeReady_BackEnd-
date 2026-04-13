---
task_id: B-02
title: "Smoke-test headless env"
type: task
agent: "ml-engineer"
track: B
depends_on: ["B-01"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["tradeready-gym/"]
tags:
  - task
  - ml
  - gym
  - critical-path
---

# Task B-02: Smoke-test headless env

## Assigned Agent: `ml-engineer`

## Objective
Create `TradeReady-BTC-Headless-v0`, run 100 steps, and confirm no connection pool errors occur.

## Context
The headless env was recently fixed for connection pool exhaustion (commits 881e27f, 89f2a81, f3dbd97, 020e859). This smoke test validates those fixes work end-to-end with real data.

## Acceptance Criteria
- [ ] Environment creates successfully
- [ ] 100 steps complete without errors
- [ ] No "connection pool exhausted" errors in logs
- [ ] No "event loop is closed" errors
- [ ] Observation space matches expected shape
- [ ] Rewards are non-zero (data is being read correctly)

## Dependencies
- **B-01**: Gym must be installed with all dependencies

## Agent Instructions
```python
import gymnasium
env = gymnasium.make('TradeReady-BTC-Headless-v0')
obs, info = env.reset()
print(f"Obs shape: {obs.shape}, Info: {info}")
for i in range(100):
    action = env.action_space.sample()
    obs, reward, terminated, truncated, info = env.step(action)
    if i % 20 == 0:
        print(f"Step {i}: reward={reward:.4f}, terminated={terminated}")
    if terminated or truncated:
        obs, info = env.reset()
env.close()
print("Smoke test passed!")
```

If connection pool errors occur, check if the single-episode session fix from 881e27f is properly applied. Read `tradeready-gym/CLAUDE.md` for environment details.

## Estimated Complexity
Low — running existing environment, but first real validation with live data.
