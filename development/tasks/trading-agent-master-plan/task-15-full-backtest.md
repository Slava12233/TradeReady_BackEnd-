---
task_id: 15
title: "Full pipeline backtest validation"
type: task
agent: "ml-engineer"
phase: 1
depends_on: [14]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/ensemble/run.py"]
tags:
  - task
  - ml
  - validation
---

# Task 15: Full pipeline backtest

## Assigned Agent: `ml-engineer`

## Objective
Run the complete ensemble pipeline in backtest mode to validate the integrated system achieves acceptable performance before live trading.

## Steps
1. `python -m agent.strategies.ensemble.run --mode backtest --base-url http://localhost:8000`
2. Verify metrics: target monthly return projection, Sharpe, win rate
3. If metrics fail: identify weak strategy, adjust weights or retrain
4. Generate final validation report

## Acceptance Criteria
- [ ] Full ensemble backtest completes without errors
- [ ] Sharpe ratio ≥ 0.5 (lower bar for aggressive strategy)
- [ ] Win rate ≥ 50%
- [ ] Positive ROI over backtest period
- [ ] All 3 signal sources (RL, evolved, regime) contributing signals
- [ ] Validation report saved

## Estimated Complexity
Medium — orchestrating existing components, analyzing results.
