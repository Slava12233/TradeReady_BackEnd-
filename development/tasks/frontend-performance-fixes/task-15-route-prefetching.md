---
task_id: 15
title: "Add route data prefetching on link hover"
agent: "frontend-developer"
phase: 3
depends_on: [9]
status: "completed"
priority: "medium"
files:
  - "Frontend/src/components/layout/sidebar.tsx"
  - "Frontend/src/lib/prefetch.ts"
---

# Task 15: Add Route Data Prefetching on Link Hover

## Assigned Agent: `frontend-developer`

## Objective

Prefetch TanStack Query data for key routes when the user hovers over sidebar navigation links, so data is already cached when they navigate.

## Context

Currently, navigating to `/coin/BTCUSDT` or `/dashboard` fetches all data from scratch. Prefetching on hover would make navigation feel instant.

From the performance review (M5): "No route prefetching — should prefetch on link hover."

## Files to Create/Modify

- Create `Frontend/src/lib/prefetch.ts` — Utility with prefetch functions per route:
  - `prefetchDashboard()` — prefetch portfolio summary, positions, orders
  - `prefetchCoin(symbol)` — prefetch candles, orderbook, recent trades
  - `prefetchMarket()` — prefetch prices, pairs
- `Frontend/src/components/layout/sidebar.tsx` — Add `onMouseEnter` handlers to nav links that call prefetch functions

## Acceptance Criteria

- [ ] Hovering over a sidebar link prefetches key data for that route
- [ ] Prefetched data is stored in TanStack Query cache
- [ ] Navigation to prefetched routes shows data immediately (no loading state)
- [ ] Prefetch only fires once per hover (debounced or guarded)
- [ ] No impact on routes that aren't hovered
- [ ] `pnpm build` passes

## Agent Instructions

1. Read `Frontend/src/hooks/` to understand the query keys and fetch functions for each route
2. Use `queryClient.prefetchQuery()` from TanStack Query
3. Access the query client via `useQueryClient()` in the sidebar or create standalone prefetch functions
4. Add `onMouseEnter` to sidebar `Link` components
5. Use a simple `Set<string>` to track already-prefetched routes and avoid duplicate prefetches

## Estimated Complexity

Medium — new utility + sidebar integration
