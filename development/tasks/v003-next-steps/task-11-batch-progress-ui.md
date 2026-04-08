---
task_id: 11
title: "Batch backtest progress UI"
type: task
agent: "frontend-developer"
phase: 3
depends_on: [6]
status: "pending"
priority: "low"
board: "[[v003-next-steps/README]]"
files:
  - "Frontend/src/components/backtest/batch-progress-bar.tsx"
tags:
  - task
  - frontend
  - backtesting
  - progress
---

# Task 11: Batch Backtest Progress UI

## Assigned Agent: `frontend-developer`

## Objective
Show a progress bar during batch-stepped backtests displaying steps_executed/total_steps.

## Context
The `BatchStepFastResponse` includes `steps_executed`, `total_steps`, `progress_pct`, and `is_complete`. The UI should visualize this during active backtests.

## Files to Modify/Create
- `Frontend/src/components/backtest/batch-progress-bar.tsx` — Progress bar with step count, percentage, ETA estimation

## Acceptance Criteria
- [ ] Progress bar showing `progress_pct` value
- [ ] Text showing `steps_executed / total_steps`
- [ ] Completion state (green bar + checkmark when `is_complete`)
- [ ] Integrates into existing backtest detail view

## Dependencies
- **Task 6** — backend security fixes complete

## Agent Instructions
1. Read `Frontend/src/components/backtest/CLAUDE.md` for backtest UI patterns
2. Use shadcn/ui Progress component
3. Keep it simple — just a progress bar with text

## Estimated Complexity
Low — simple progress bar component.
