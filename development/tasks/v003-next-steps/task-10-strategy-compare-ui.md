---
task_id: 10
title: "Strategy comparison view"
type: task
agent: "frontend-developer"
phase: 3
depends_on: [6]
status: "pending"
priority: "medium"
board: "[[v003-next-steps/README]]"
files:
  - "Frontend/src/components/strategies/strategy-comparison.tsx"
  - "Frontend/src/hooks/use-strategy-compare.ts"
  - "Frontend/src/lib/api-client.ts"
tags:
  - task
  - frontend
  - strategies
  - comparison
---

# Task 10: Strategy Comparison View

## Assigned Agent: `frontend-developer`

## Objective
Build a multi-select strategy comparison view: select 2-10 strategies, compare side-by-side with metrics + DSR, show winner recommendation.

## Context
Backend has `POST /api/v1/strategies/compare` that ranks strategies by metric and returns DSR data + recommendation text.

## Files to Modify/Create
- `Frontend/src/components/strategies/strategy-comparison.tsx` — Comparison table, winner highlight, DSR badge, recommendation card
- `Frontend/src/hooks/use-strategy-compare.ts` — TanStack Query mutation for comparison
- `Frontend/src/lib/api-client.ts` — Add `compareStrategies(strategyIds, rankingMetric)` function

## Acceptance Criteria
- [ ] Multi-select checkboxes on strategy list (2-10 strategies)
- [ ] "Compare" button triggers comparison
- [ ] Side-by-side table: sharpe, max_drawdown, win_rate, roi, DSR p-value
- [ ] Winner row highlighted with badge
- [ ] DSR significance shown as pass/fail badge (green/red)
- [ ] Recommendation text displayed
- [ ] Metric dropdown to change ranking metric
- [ ] Loading state during comparison

## Dependencies
- **Task 6** — backend security fixes complete

## Agent Instructions
1. Read `Frontend/src/components/strategies/CLAUDE.md` for strategy UI patterns
2. The response shape includes `strategies[]` (ranked), `winner` (UUID), `recommendation` (string)
3. Each strategy has `metrics` object and optional `deflated_sharpe` object

## Estimated Complexity
Medium — table with dynamic columns and interactive selection.
