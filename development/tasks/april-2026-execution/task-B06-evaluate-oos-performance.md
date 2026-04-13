---
task_id: B-06
title: "Evaluate OOS performance"
type: task
agent: "ml-engineer"
track: B
depends_on: ["B-05"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["models/ppo_btc_v1.zip"]
tags:
  - task
  - ml
  - evaluation
  - critical-path
---

# Task B-06: Evaluate OOS performance

## Assigned Agent: `ml-engineer`

## Objective
Review the 10-episode out-of-sample evaluation output from the training script. Analyze average reward, Sharpe ratio, max drawdown, and win rate.

## Acceptance Criteria
- [ ] OOS evaluation results available (from B-05 training output)
- [ ] Average reward is documented
- [ ] Sharpe ratio calculated (target: > 0)
- [ ] Maximum drawdown recorded
- [ ] Win rate (% of profitable trades) documented
- [ ] Comparison with random baseline (is the model better than random?)

## Dependencies
- **B-05**: Full training must be complete with OOS eval

## Agent Instructions
The training script outputs OOS eval metrics at completion. If the script doesn't output Sharpe/drawdown directly, load the model and run evaluation manually:
```python
from stable_baselines3 import PPO
import gymnasium
model = PPO.load("models/ppo_btc_v1.zip")
env = gymnasium.make('TradeReady-BTC-Headless-v0')
# Run 10 episodes, collect returns
```
Record all metrics. The key success criterion is **OOS Sharpe > 0** — the model must show positive risk-adjusted returns on unseen data.

## Estimated Complexity
Medium — analysis and potential manual evaluation.
