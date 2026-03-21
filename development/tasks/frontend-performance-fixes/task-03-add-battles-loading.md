---
task_id: 3
title: "Add missing loading.tsx for /battles route"
type: task
agent: "frontend-developer"
phase: 1
depends_on: []
status: "completed"
board: "[[frontend-performance-fixes/README]]"
priority: "medium"
files:
  - "Frontend/src/app/(dashboard)/battles/loading.tsx"
tags:
  - task
  - frontend
  - performance
---

# Task 3: Add Missing loading.tsx for /battles Route

## Assigned Agent: `frontend-developer`

## Objective

Create a `loading.tsx` file for the `/battles` route, matching the pattern used by all other dashboard routes.

## Context

Every dashboard route has a `loading.tsx` except `/battles`. Users see a blank screen during route transitions to this page.

From the performance review (M4): "Missing `/battles/loading.tsx`."

## Files to Create

- `Frontend/src/app/(dashboard)/battles/loading.tsx` — Follow the same pattern as `Frontend/src/app/(dashboard)/agents/loading.tsx` or another existing loading file

## Acceptance Criteria

- [ ] `loading.tsx` exists in the battles route directory
- [ ] Shows a skeleton/spinner consistent with other dashboard loading states
- [ ] No TypeScript errors
- [ ] `pnpm build` passes

## Agent Instructions

1. Read an existing loading.tsx (e.g., `Frontend/src/app/(dashboard)/agents/loading.tsx`) for the pattern
2. Create the battles loading file with the same structure
3. Adapt the skeleton to match what the battles page content looks like

## Estimated Complexity

Low — copy existing pattern
