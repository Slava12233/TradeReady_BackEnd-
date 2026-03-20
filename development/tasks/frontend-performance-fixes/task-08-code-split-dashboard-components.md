---
task_id: 8
title: "Code-split dashboard page with next/dynamic for below-fold components"
agent: "frontend-developer"
phase: 2
depends_on: [6]
status: "completed"
priority: "high"
files:
  - "Frontend/src/app/(dashboard)/dashboard/page.tsx"
---

# Task 8: Code-Split Dashboard Page with next/dynamic

## Assigned Agent: `frontend-developer`

## Objective

Use `next/dynamic` to lazy-load below-fold dashboard components (charts, tables, secondary cards), reducing initial bundle by ~200KB and deferring non-critical queries.

## Context

Dashboard imports 12 heavy components synchronously. Each fires its own REST query on mount, creating a waterfall of 15+ requests. The landing page already uses this pattern correctly in `landing-below-fold.tsx`.

From the performance review (H1, H5): "Dashboard 10+ waterfall queries on mount" and "Dashboard components not code-split."

## Files to Modify

- `Frontend/src/app/(dashboard)/dashboard/page.tsx` (lines 1-12):
  - Keep above-fold: `PnlSummaryCards`, `PortfolioValueCard`, `QuickStatsRow`
  - Lazy-load below-fold:
    - `EquityChart` (Recharts — heavy)
    - `AllocationPieChart` (Recharts — heavy)
    - `OpenPositionsTable`
    - `ActiveOrdersTable`
    - `RecentTradesFeed` (Framer Motion)
    - `RiskStatusCard`
    - `StrategyStatusCard`
    - `TrainingStatusCard`

## Acceptance Criteria

- [ ] Above-fold components load immediately (PnlSummaryCards, PortfolioValueCard, QuickStatsRow)
- [ ] Below-fold components load via `next/dynamic` with loading skeletons
- [ ] Initial page load is visually faster (above-fold renders before charts)
- [ ] All components still render correctly after lazy loading
- [ ] No layout shift when lazy components load in
- [ ] No TypeScript errors
- [ ] `pnpm build` passes

## Agent Instructions

1. Read `Frontend/src/app/(dashboard)/dashboard/page.tsx` for current structure
2. Read `Frontend/src/components/landing/landing-below-fold.tsx` for the correct `next/dynamic` pattern
3. Use the same `.then((m) => ({ default: m.ComponentName }))` pattern for named exports
4. Add loading fallback skeletons that match the component dimensions to prevent layout shift
5. Keep the page's grid/layout structure unchanged — only change how components are imported

## Estimated Complexity

Medium — import changes + loading skeletons needed
