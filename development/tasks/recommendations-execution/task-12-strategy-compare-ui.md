---
task_id: 12
title: "Strategy comparison view"
type: task
agent: "frontend-developer"
phase: 2
depends_on: [9]
status: "pending"
priority: "medium"
board: "[[recommendations-execution/README]]"
files:
  - "Frontend/src/components/strategies/strategy-comparison.tsx"
  - "Frontend/src/hooks/use-strategy-compare.ts"
tags:
  - task
  - frontend
  - strategies
  - comparison
---

# Task 12: Strategy Comparison View

## Assigned Agent: `frontend-developer`

## Objective
Multi-select 2-10 strategies, compare side-by-side with metrics + DSR, show winner recommendation.

## Context
R3 Component 3. Backend has `POST /api/v1/strategies/compare`.

## Files to Modify/Create
- `Frontend/src/hooks/use-strategy-compare.ts` — TanStack Query mutation
- `Frontend/src/components/strategies/strategy-comparison.tsx` — Multi-select, comparison table, winner banner
- Wire into strategies page

## Acceptance Criteria
- [ ] Multi-select checkboxes on strategy list (2-10)
- [ ] "Compare" button triggers comparison
- [ ] Side-by-side table: sharpe, drawdown, win_rate, roi, DSR p-value
- [ ] Winner row highlighted with badge
- [ ] DSR significance: pass (green) / fail (red)
- [ ] Recommendation text displayed
- [ ] Metric dropdown to change ranking metric

## Agent Instructions
1. Read `Frontend/src/components/strategies/CLAUDE.md`
2. Response shape: `strategies[]` (ranked), `winner` (UUID), `recommendation` (string)

## Estimated Complexity
Medium — interactive table with selection and dynamic ranking.
