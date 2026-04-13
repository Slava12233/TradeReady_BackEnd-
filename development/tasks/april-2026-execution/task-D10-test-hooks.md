---
task_id: D-10
title: "Test hooks (5)"
type: task
agent: "frontend-developer"
track: D
depends_on: ["D-02"]
status: "completed"
priority: "high"
board: "[[april-2026-execution/README]]"
files: [
  "Frontend/src/hooks/__tests__/useAgent.test.ts",
  "Frontend/src/hooks/__tests__/usePortfolio.test.ts",
  "Frontend/src/hooks/__tests__/useTrades.test.ts",
  "Frontend/src/hooks/__tests__/useBattles.test.ts",
  "Frontend/src/hooks/__tests__/useWebSocket.test.ts"
]
tags:
  - task
  - frontend
  - testing
  - hooks
---

# Task D-10: Test hooks (5)

## Assigned Agent: `frontend-developer`

## Objective
Write tests for the 5 most critical hooks: useAgent, usePortfolio, useTrades, useBattles, useWebSocket.

## Files to Reference
- `Frontend/src/hooks/CLAUDE.md`

## Acceptance Criteria
- [ ] 5 test files created
- [ ] useAgent: tests data fetching, loading state, error state, agent switching
- [ ] usePortfolio: tests portfolio data, balance updates, position tracking
- [ ] useTrades: tests trade history fetching, pagination, filtering
- [ ] useBattles: tests battle list, battle detail, live updates
- [ ] useWebSocket: tests connection lifecycle, message handling, reconnection
- [ ] All tests use `renderHook` from testing-library
- [ ] TanStack Query cache behavior tested (stale time, refetch)
- [ ] All tests pass

## Dependencies
- **D-02**: Test utilities (QueryClient wrapper)

## Agent Instructions
Use `@testing-library/react`'s `renderHook` with the custom QueryClient wrapper. Mock the API client (`Frontend/src/lib/api-client.ts`) to return test data. For useWebSocket, mock the WebSocket constructor. Test the `keepPreviousData` behavior that was added in the performance optimization sprint.

## Estimated Complexity
Medium — hooks require careful async testing and mock setup.
