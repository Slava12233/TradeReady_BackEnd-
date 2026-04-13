---
task_id: D-02
title: "Create test utilities"
type: task
agent: "frontend-developer"
track: D
depends_on: ["D-01"]
status: "completed"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["Frontend/src/test-utils.tsx", "Frontend/src/setupTests.ts"]
tags:
  - task
  - frontend
  - testing
  - utilities
---

# Task D-02: Create test utilities

## Assigned Agent: `frontend-developer`

## Objective
Set up `test-utils.tsx` with a custom render function that wraps components in all necessary providers (QueryClient, theme, router mocks).

## Context
All component tests will import from this file instead of `@testing-library/react` directly. This ensures consistent test setup across all test files.

## Files to Create
- `Frontend/src/test-utils.tsx` — custom render with providers
- `Frontend/src/setupTests.ts` — global test setup (jest-dom matchers, mock globals)

## Acceptance Criteria
- [ ] `test-utils.tsx` exports a custom `render` function wrapping all providers
- [ ] Providers include: QueryClientProvider (fresh client per test), theme, router mock
- [ ] Re-exports all `@testing-library/react` utilities
- [ ] `setupTests.ts` imports `@testing-library/jest-dom`
- [ ] `setupTests.ts` mocks `window.matchMedia`, `ResizeObserver`, `IntersectionObserver` if needed
- [ ] vitest config references `setupTests.ts` as a setup file
- [ ] A simple smoke test file works with the custom render

## Dependencies
- **D-01**: vitest must be working

## Agent Instructions
Read `Frontend/CLAUDE.md` for component patterns. Check which providers the app uses:
- `Frontend/src/app/layout.tsx` — root providers
- `Frontend/src/lib/` — QueryClient setup
- `Frontend/src/stores/` — Zustand stores

Create providers that match the real app setup. The QueryClient should be created fresh per test to prevent state leakage. Add a simple test to verify the setup works:
```tsx
// Frontend/src/test-utils.test.tsx
import { render, screen } from './test-utils';
test('custom render works', () => {
  render(<div>hello</div>);
  expect(screen.getByText('hello')).toBeInTheDocument();
});
```

## Estimated Complexity
Medium — requires understanding the app's provider stack.
