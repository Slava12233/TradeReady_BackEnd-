---
task_id: D-09
title: "Test shared components (5)"
type: task
agent: "frontend-developer"
track: D
depends_on: ["D-02"]
status: "completed"
priority: "medium"
board: "[[april-2026-execution/README]]"
files: [
  "Frontend/src/components/shared/__tests__/PriceFlashCell.test.tsx",
  "Frontend/src/components/shared/__tests__/SectionErrorBoundary.test.tsx",
  "Frontend/src/components/shared/__tests__/LoadingSkeleton.test.tsx",
  "Frontend/src/components/shared/__tests__/StatusBadge.test.tsx",
  "Frontend/src/components/shared/__tests__/TimeAgo.test.tsx"
]
tags:
  - task
  - frontend
  - testing
  - shared
---

# Task D-09: Test shared components (5)

## Assigned Agent: `frontend-developer`

## Objective
Write tests for the 5 most-used shared components: PriceFlashCell, SectionErrorBoundary, LoadingSkeleton, StatusBadge, TimeAgo.

## Files to Reference
- `Frontend/src/components/shared/CLAUDE.md`

## Acceptance Criteria
- [ ] 5 test files created
- [ ] PriceFlashCell: tests price display, green/red flash on increase/decrease, memo behavior
- [ ] SectionErrorBoundary: tests error catching, fallback UI, reset behavior
- [ ] LoadingSkeleton: tests skeleton rendering, various size props
- [ ] StatusBadge: tests all status variants (active, inactive, pending, error, etc.)
- [ ] TimeAgo: tests relative time formatting (seconds, minutes, hours, days ago)
- [ ] All tests pass

## Dependencies
- **D-02**: Test utilities

## Agent Instructions
These are reusable building blocks used across many components. PriceFlashCell was recently optimized with React.memo — test that it only re-renders when price changes. SectionErrorBoundary needs a component that throws to test error catching. TimeAgo needs mock dates.

## Estimated Complexity
Low — small, focused components with clear behavior.
