---
task_id: 4
title: "Add useShallow to portfolio Zustand selector"
type: task
agent: "frontend-developer"
phase: 1
depends_on: []
status: "completed"
board: "[[frontend-performance-fixes/README]]"
priority: "high"
files:
  - "Frontend/src/hooks/use-portfolio.ts"
tags:
  - task
  - frontend
  - performance
---

# Task 4: Add useShallow to Portfolio Zustand Selector

## Assigned Agent: `frontend-developer`

## Objective

Add `useShallow` wrapper to the portfolio selector in `use-portfolio.ts` to prevent unnecessary re-renders when unrelated WebSocket store data changes.

## Context

`use-all-prices.ts` correctly uses `useShallow(selectAllPrices)`, but `use-portfolio.ts` uses the selector directly without shallow comparison. The portfolio object reference changes on every store update, triggering re-renders even when portfolio data hasn't changed.

From the performance review (H7): "Portfolio selector without useShallow."

## Files to Modify

- `Frontend/src/hooks/use-portfolio.ts` (line 22) — Wrap selector with `useShallow`

## Acceptance Criteria

- [ ] `useShallow` imported from `zustand/react/shallow`
- [ ] Portfolio selector wrapped: `useWebSocketStore(useShallow(selectPortfolio))`
- [ ] Components using this hook no longer re-render on unrelated WS store changes
- [ ] Portfolio data still updates correctly when actual portfolio changes arrive
- [ ] No TypeScript errors

## Agent Instructions

1. Read `Frontend/src/hooks/use-portfolio.ts`
2. Read `Frontend/src/hooks/use-all-prices.ts` for the correct `useShallow` pattern
3. Apply the same pattern to the portfolio selector
4. Check if there are other hooks using WebSocket store selectors without `useShallow` — fix those too

## Estimated Complexity

Low — one-line change plus import
