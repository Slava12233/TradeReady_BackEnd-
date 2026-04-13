---
task_id: D-01
title: "Fix vitest setup"
type: task
agent: "frontend-developer"
track: D
depends_on: []
status: "completed"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["Frontend/vitest.config.ts", "Frontend/package.json"]
tags:
  - task
  - frontend
  - testing
  - setup
---

# Task D-01: Fix vitest setup

## Assigned Agent: `frontend-developer`

## Objective
Ensure `npm run test` works in the Frontend directory — install missing deps, fix config issues, get a 0-test green baseline.

## Context
The frontend has 250+ .tsx components but 0 running tests. vitest is configured but may have broken dependencies or config issues.

## Files to Check/Modify
- `Frontend/vitest.config.ts` — vitest configuration
- `Frontend/package.json` — scripts and dependencies
- `Frontend/tsconfig.json` — TypeScript paths (vitest needs to resolve them)

## Acceptance Criteria
- [ ] `cd Frontend && npm run test` exits with code 0
- [ ] vitest runs and reports "0 tests" (no errors)
- [ ] `@testing-library/react` and `@testing-library/jest-dom` are installed
- [ ] `jsdom` or `happy-dom` environment configured in vitest
- [ ] TypeScript path aliases resolve correctly in test files
- [ ] Test script exists in `package.json`: `"test": "vitest run"`

## Dependencies
None — can start immediately.

## Agent Instructions
Read `Frontend/CLAUDE.md` first. Then:
1. Check `Frontend/package.json` for test script and testing dependencies
2. Run `cd Frontend && npm run test` to see current state
3. Install missing deps: `npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom`
4. Fix `vitest.config.ts` if needed (environment, path aliases, setup files)
5. Verify with `npm run test` — should exit 0 with no test files found

## Estimated Complexity
Medium — dependency resolution and config debugging.
