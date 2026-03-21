---
task_id: 18
title: "Add keepPreviousData to remaining paginated hooks"
type: task
agent: "frontend-developer"
phase: 3
depends_on: []
status: "completed"
board: "[[frontend-performance-fixes/README]]"
priority: "low"
files:
  - "Frontend/src/hooks/use-market-data.ts"
  - "Frontend/src/hooks/use-backtests.ts"
tags:
  - task
  - frontend
  - performance
---

# Task 18: Add keepPreviousData to Remaining Paginated Hooks

## Assigned Agent: `frontend-developer`

## Objective

Add `placeholderData: keepPreviousData` to paginated hooks that are missing it, preventing loading flashes when users change pages or filters.

## Context

`useTrades()` correctly uses `keepPreviousData`, but other paginated/filterable hooks don't, causing tables to flash empty during pagination.

From the performance review (L2): "Missing keepPreviousData on some paginated hooks."

## Files to Modify

- `Frontend/src/hooks/use-market-data.ts` — Add to `useAllTickers()`, `useDailyCandlesBatch()`
- `Frontend/src/hooks/use-backtests.ts` — Add to backtest list hook if paginated
- Any other paginated hooks found during investigation

## Acceptance Criteria

- [ ] All paginated/filterable hooks use `placeholderData: keepPreviousData`
- [ ] Tables show stale data (dimmed) instead of loading skeleton during page changes
- [ ] No TypeScript errors
- [ ] `pnpm build` passes

## Agent Instructions

1. Search hooks directory for `useQuery` calls that support pagination or filtering
2. Check if they already have `placeholderData`
3. Add `import { keepPreviousData } from "@tanstack/react-query"` and apply

## Estimated Complexity

Low — add one config option per hook
