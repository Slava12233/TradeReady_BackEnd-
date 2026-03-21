---
task_id: 12
title: "Validate individual strategies (regime + PPO)"
type: task
agent: "e2e-tester"
phase: 7
depends_on: [5, 7]
status: "pending"
board: "[[agent-deployment-training/README]]"
priority: "medium"
files: ["agent/reports/"]
tags:
  - task
  - deployment
  - training
---

# Task 12: Validate individual strategies (regime + PPO)

## Assigned Agent: `e2e-tester`

## Objective
Run validation backtests for the regime-adaptive strategy and PPO deploy bridge independently.

## Steps
1. Regime validation (12 months):
   ```bash
   python -m agent.strategies.regime.validate \
     --base-url http://localhost:8000 \
     --api-key ak_live_KEY \
     --months 12
   ```
2. PPO deploy test (backtest mode):
   ```bash
   python -m agent.strategies.rl.deploy \
     --model agent/strategies/rl/models/ppo_seed42.zip \
     --mode backtest
   ```

## Acceptance Criteria
- [ ] Regime validation report generated with 12 monthly results
- [ ] Regime-adaptive outperforms static in 8+/12 months
- [ ] PPO deploy bridge generates valid orders
- [ ] Reports saved to `agent/reports/`

## Dependencies
- Task 05: trained regime classifier
- Task 07: evaluated PPO models

## Estimated Complexity
Medium — running validation scripts, analyzing results.
