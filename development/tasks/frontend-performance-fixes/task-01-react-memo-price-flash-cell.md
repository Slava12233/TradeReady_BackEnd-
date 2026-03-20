---
task_id: 1
title: "Add React.memo to PriceFlashCell and market table row components"
agent: "frontend-developer"
phase: 1
depends_on: []
status: "completed"
priority: "high"
files:
  - "Frontend/src/components/market/market-table-row.tsx"
  - "Frontend/src/components/market/market-table.tsx"
---

# Task 1: Add React.memo to PriceFlashCell and Market Table Row Components

## Assigned Agent: `frontend-developer`

## Objective

Wrap `PriceFlashCell` (and the parent row component if applicable) in `React.memo` with a custom comparator to prevent 600+ rows from re-rendering on every price tick.

## Context

The market table renders 600+ trading pairs. Currently, `PriceFlashCell` is an unwrapped function component — when the parent table re-renders (e.g., from a WS price update to ANY symbol), ALL 600 cells re-render even though only 1-2 prices changed.

From the performance review (C2): "Every price update from WS triggers a re-render of the parent table, which re-renders ALL PriceFlashCell instances."

## Files to Modify

- `Frontend/src/components/market/market-table-row.tsx` — Wrap `PriceFlashCell` in `React.memo` with `(prev, next) => prev.price === next.price && prev.className === next.className`
- `Frontend/src/components/market/market-table.tsx` — If the table row itself is a separate component, also wrap it in `React.memo`

## Acceptance Criteria

- [ ] `PriceFlashCell` is exported as `React.memo(PriceFlashCellInner, comparator)`
- [ ] Custom comparator compares `price` and `className` props (and `children` if used)
- [ ] Table rows only re-render when their specific data changes, not when unrelated rows update
- [ ] Flash animation still works correctly (up/down color on price change)
- [ ] No TypeScript errors
- [ ] `pnpm build` passes

## Agent Instructions

1. Read `Frontend/src/components/market/market-table-row.tsx` and `market-table.tsx`
2. Read `Frontend/CLAUDE.md` for component conventions
3. Wrap `PriceFlashCell` in `React.memo` — use a named inner component so React DevTools shows a useful name
4. If the row component is separate, wrap that too
5. Test that flash animation still triggers on price changes

## Estimated Complexity

Low — straightforward `React.memo` wrapper addition
