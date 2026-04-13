---
task_id: D-03
title: "Test dashboard components (5)"
type: task
agent: "frontend-developer"
track: D
depends_on: ["D-02"]
status: "completed"
priority: "high"
board: "[[april-2026-execution/README]]"
files: [
  "Frontend/src/components/dashboard/__tests__/EquityChart.test.tsx",
  "Frontend/src/components/dashboard/__tests__/PortfolioSummary.test.tsx",
  "Frontend/src/components/dashboard/__tests__/PositionsTable.test.tsx",
  "Frontend/src/components/dashboard/__tests__/RecentOrders.test.tsx",
  "Frontend/src/components/dashboard/__tests__/DashboardLayout.test.tsx"
]
tags:
  - task
  - frontend
  - testing
  - dashboard
---

# Task D-03: Test dashboard components (5)

## Assigned Agent: `frontend-developer`

## Objective
Write tests for the 5 critical dashboard components: EquityChart, PortfolioSummary, PositionsTable, RecentOrders, DashboardLayout.

## Context
Dashboard components display financial data (PnL, equity, positions). Rendering bugs here could mislead users about their portfolio status — these are the highest-priority frontend tests.

## Files to Reference
- `Frontend/src/components/dashboard/CLAUDE.md` — component inventory
- `Frontend/src/components/dashboard/` — source components

## Acceptance Criteria
- [ ] 5 test files created (one per component)
- [ ] Each test file covers: renders without crash, displays mock data correctly, handles empty state, handles loading state
- [ ] EquityChart: tests chart rendering with mock equity data
- [ ] PortfolioSummary: tests PnL display, balance formatting, percentage changes
- [ ] PositionsTable: tests position rows, sort behavior, empty state
- [ ] RecentOrders: tests order list rendering, status badges
- [ ] DashboardLayout: tests layout structure, section rendering
- [ ] All tests pass: `npm run test -- --filter dashboard`

## Dependencies
- **D-02**: Test utilities must be set up

## Agent Instructions
Read `Frontend/src/components/dashboard/CLAUDE.md` for component details. For each component:
1. Read the source to understand props and data flow
2. Create mock data matching the expected types
3. Write tests using the custom render from `test-utils.tsx`
4. Mock API hooks with `vi.mock()` for TanStack Query hooks
5. Test financial number formatting carefully (decimals, currency symbols, signs)

Place test files in `Frontend/src/components/dashboard/__tests__/` or co-located as `*.test.tsx`.

## Estimated Complexity
Medium — 5 components, financial data formatting is tricky.
