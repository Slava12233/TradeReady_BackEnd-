---
task_id: 13
title: "Add Suspense boundaries in dashboard layout for streaming"
type: task
agent: "frontend-developer"
phase: 2
depends_on: [7]
status: "completed"
board: "[[frontend-performance-fixes/README]]"
priority: "medium"
files:
  - "Frontend/src/app/(dashboard)/layout.tsx"
tags:
  - task
  - frontend
  - performance
---

# Task 13: Add Suspense Boundaries in Dashboard Layout

## Assigned Agent: `frontend-developer`

## Objective

Add separate `<Suspense>` boundaries around Header, Sidebar, and main content area so they can stream independently and a slow component doesn't block the entire layout.

## Context

Currently there are no Suspense boundaries in the dashboard layout. If any component suspends (e.g., a slow data fetch), the entire page is blocked.

From the performance review (M3): "Missing Suspense boundaries in dashboard layout for streaming."

## Files to Modify

- `Frontend/src/app/(dashboard)/layout.tsx` — Wrap Header, Sidebar, and `{children}` in separate `<Suspense>` with appropriate fallback skeletons

## Acceptance Criteria

- [ ] Header, Sidebar, and content area have independent Suspense boundaries
- [ ] Each Suspense boundary has an appropriate skeleton fallback
- [ ] Slow-loading content in one area doesn't block others
- [ ] No visual regressions in normal loading scenarios
- [ ] `pnpm build` passes

## Agent Instructions

1. This task depends on Task 7 (layout restructure) — apply after that's done
2. Create lightweight skeleton fallbacks that match the dimensions of Header and Sidebar
3. Use existing skeleton/loading patterns from the project

## Estimated Complexity

Low-Medium — Suspense wrappers + skeleton fallbacks
