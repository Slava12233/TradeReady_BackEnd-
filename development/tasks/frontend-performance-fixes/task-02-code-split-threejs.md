---
task_id: 2
title: "Code-split Three.js DottedSurface with next/dynamic"
agent: "frontend-developer"
phase: 1
depends_on: []
status: "completed"
priority: "high"
files:
  - "Frontend/src/components/ui/dotted-surface.tsx"
---

# Task 2: Code-Split Three.js DottedSurface with next/dynamic

## Assigned Agent: `frontend-developer`

## Objective

Lazy-load the `DottedSurface` component using `next/dynamic` with `{ ssr: false }` to remove Three.js (~440KB) from the main bundle.

## Context

Three.js is imported for a single component (`DottedSurface`) that creates a WebGL scene. This adds ~440KB to the bundle unnecessarily for pages that don't use it.

From the performance review (C3): "Three.js (~440KB raw) is used for ONE component."

## Files to Modify

- Find all files that import `DottedSurface` and replace with dynamic import:
  ```tsx
  const DottedSurface = dynamic(() => import("@/components/ui/dotted-surface"), { ssr: false })
  ```

## Acceptance Criteria

- [ ] `DottedSurface` is imported via `next/dynamic` with `{ ssr: false }` everywhere it's used
- [ ] Three.js is no longer in the main bundle (verify with build output)
- [ ] Component still renders correctly where used
- [ ] No hydration errors
- [ ] `pnpm build` passes

## Agent Instructions

1. Search for all imports of `dotted-surface` across the codebase: `grep -r "dotted-surface" Frontend/src/`
2. Replace static imports with `next/dynamic` at each usage site
3. The component file itself (`dotted-surface.tsx`) stays unchanged — only the import sites change
4. Ensure `{ ssr: false }` since WebGL requires browser APIs

## Estimated Complexity

Low — import change only, no logic changes
