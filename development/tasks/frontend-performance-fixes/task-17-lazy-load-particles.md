---
task_id: 17
title: "Lazy-load tsparticles Sparkles component"
type: task
agent: "frontend-developer"
phase: 3
depends_on: []
status: "completed"
board: "[[frontend-performance-fixes/README]]"
priority: "medium"
files:
  - "Frontend/src/components/ui/sparkles.tsx"
  - "Frontend/src/components/landing/frameworks-section.tsx"
tags:
  - task
  - frontend
  - performance
---

# Task 17: Lazy-Load tsparticles Sparkles Component

## Assigned Agent: `frontend-developer`

## Objective

Ensure the `Sparkles` component (which imports `@tsparticles/slim` + `@tsparticles/react`) is lazy-loaded via `next/dynamic` wherever it's used, so the particle engine doesn't bloat the main bundle.

## Context

`@tsparticles/slim` + `@tsparticles/react` are medium-weight dependencies used only for the Sparkles visual effect on the landing page.

From the performance review (M10): "Remotion/tsparticles lazy loading — verify and fix."

## Files to Modify

- Find all imports of `Sparkles` and ensure they use `next/dynamic({ ssr: false })`
- `Frontend/src/components/landing/frameworks-section.tsx` already uses dynamic import for Sparkles — verify this pattern
- Check if any other file imports Sparkles directly

## Acceptance Criteria

- [ ] Sparkles is always imported via `next/dynamic` with `{ ssr: false }`
- [ ] No direct static import of Sparkles anywhere
- [ ] tsparticles is not in the main bundle (verify with build output)
- [ ] Sparkles still renders correctly on the landing page
- [ ] `pnpm build` passes

## Agent Instructions

1. Search for all imports of `sparkles` across the codebase
2. Verify each import uses `next/dynamic`
3. Fix any static imports found

## Estimated Complexity

Low — verify and fix imports
