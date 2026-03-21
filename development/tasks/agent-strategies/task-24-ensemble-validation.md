---
task_id: 24
title: "Ensemble validation & final battle"
type: task
agent: "e2e-tester"
phase: E
depends_on: [23]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "low"
files: []
tags:
  - task
  - ml
  - strategies
---

# Task 24: Ensemble validation & final battle

## Assigned Agent: `e2e-tester`

## Objective
Run the final validation: ensemble vs each individual strategy in a historical battle. Verify ensemble Sharpe > max(individual Sharpe). Test on 3 held-out months.

## Steps
1. Create 4 agents: Ensemble, PPO-only, Evolved-only, Regime-only
2. Run historical battle (3 months held-out data)
3. Each agent trades independently using its strategy
4. Compare results: Sharpe, ROI, max drawdown, win rate, profit factor
5. Repeat on 2 more held-out periods for robustness
6. Generate final report: `agent/reports/ensemble-final-validation-{timestamp}.json`

## Acceptance Criteria
- [ ] Ensemble Sharpe > max(individual Sharpe) in at least 2/3 periods
- [ ] Ensemble max drawdown < worst individual max drawdown
- [ ] All 4 agents complete all 3 battle periods without errors
- [ ] Final report includes: per-strategy per-period metrics + summary
- [ ] 10% improvement target verified against baseline (buy-and-hold)

## Dependencies
- Task 23: ensemble pipeline complete

## Agent Instructions
This is the culminating test. Use `historical_month` battle preset for thorough evaluation. Log everything — this report goes to the CTO.

## Estimated Complexity
Medium — battle orchestration with careful result collection.
