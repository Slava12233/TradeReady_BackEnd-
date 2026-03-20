---
task_id: 6
title: "Install and configure @next/bundle-analyzer"
agent: "frontend-developer"
phase: 1
depends_on: []
status: "completed"
priority: "high"
files:
  - "Frontend/package.json"
  - "Frontend/next.config.ts"
---

# Task 6: Install and Configure @next/bundle-analyzer

## Assigned Agent: `frontend-developer`

## Objective

Add `@next/bundle-analyzer` as a dev dependency and wire it into `next.config.ts` so the team can measure actual bundle sizes and identify dead code.

## Context

Without a bundle analyzer, we cannot verify the actual impact of Three.js, Remotion, Recharts, and other heavy dependencies. This blocks informed optimization decisions.

From the performance review (H8): "Missing bundle analyzer."

## Files to Modify

- `Frontend/package.json` — Add `@next/bundle-analyzer` to devDependencies
- `Frontend/next.config.ts` — Wrap config with bundle analyzer (enabled via `ANALYZE=true` env var)

## Acceptance Criteria

- [ ] `@next/bundle-analyzer` installed as dev dependency
- [ ] `next.config.ts` conditionally wraps config when `ANALYZE=true`
- [ ] Running `ANALYZE=true pnpm build` opens bundle visualization
- [ ] Normal `pnpm build` is unaffected (no analyzer overhead)
- [ ] No TypeScript errors

## Agent Instructions

1. Read `Frontend/next.config.ts` to understand current config structure (uses `createMDX()` wrapper)
2. Install: `cd Frontend && pnpm add -D @next/bundle-analyzer`
3. Update `next.config.ts` to compose bundle analyzer with existing MDX wrapper
4. Test that `pnpm build` still works without `ANALYZE=true`

## Estimated Complexity

Low — standard Next.js plugin setup
