---
task_id: 14
title: "Add partial error boundaries to dashboard sections"
type: task
agent: "frontend-developer"
phase: 3
depends_on: [8]
status: "completed"
board: "[[frontend-performance-fixes/README]]"
priority: "medium"
files:
  - "Frontend/src/app/(dashboard)/dashboard/page.tsx"
  - "Frontend/src/components/shared/section-error-boundary.tsx"
tags:
  - task
  - frontend
  - performance
---

# Task 14: Add Partial Error Boundaries to Dashboard Sections

## Assigned Agent: `frontend-developer`

## Objective

Create a reusable `SectionErrorBoundary` component and wrap each independent dashboard section so a single failing query doesn't break the entire page.

## Context

If `usePerformance()` times out, the entire QuickStatsRow doesn't render. Each independent data source should be isolated.

From the performance review (M8): "No partial error boundaries — single failing endpoint blocks entire page section."

## Files to Create/Modify

- Create `Frontend/src/components/shared/section-error-boundary.tsx` — Reusable error boundary with retry button and section title
- `Frontend/src/app/(dashboard)/dashboard/page.tsx` — Wrap each major section in `<SectionErrorBoundary>`

## Acceptance Criteria

- [ ] `SectionErrorBoundary` shows a compact error state with retry button
- [ ] Each dashboard section (charts, tables, stats) is independently wrapped
- [ ] A failing section shows error UI while other sections work normally
- [ ] Retry button re-mounts the section and re-fires its queries
- [ ] Matches the project's UI styling (shadcn/ui patterns)
- [ ] `pnpm build` passes

## Agent Instructions

1. Read existing error handling patterns in the project
2. Create the error boundary as a class component (React error boundaries require class components)
3. Use shadcn/ui `Alert` or `Card` for the error display
4. Wrap each dashboard grid section independently

## Estimated Complexity

Medium — new component + dashboard integration
