---
task_id: 13
title: "Batch backtest progress bar"
type: task
agent: "frontend-developer"
phase: 2
depends_on: [9]
status: "pending"
priority: "low"
board: "[[recommendations-execution/README]]"
files:
  - "Frontend/src/components/backtest/monitor/batch-progress.tsx"
tags:
  - task
  - frontend
  - backtesting
  - progress
---

# Task 13: Batch Backtest Progress Bar

## Assigned Agent: `frontend-developer`

## Objective
Show progress bar during batch-stepped backtests with steps_executed/total_steps.

## Context
R3 Component 4. `BatchStepFastResponse` includes progress data.

## Files to Modify/Create
- `Frontend/src/components/backtest/monitor/batch-progress.tsx`

## Acceptance Criteria
- [ ] Progress bar showing `progress_pct`
- [ ] Text: `steps_executed / total_steps`
- [ ] Green bar + checkmark on completion
- [ ] Integrates into backtest detail view

## Agent Instructions
1. Read `Frontend/src/components/backtest/CLAUDE.md`
2. Use shadcn/ui Progress component
3. Keep simple — just progress bar + text

## Estimated Complexity
Low — simple progress component.
