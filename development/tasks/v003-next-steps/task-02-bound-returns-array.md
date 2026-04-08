---
task_id: 2
title: "Bound returns array on Deflated Sharpe endpoint"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[v003-next-steps/README]]"
files:
  - "src/api/schemas/metrics.py"
  - "src/api/middleware/auth.py"
tags:
  - task
  - security
  - metrics
  - dos-prevention
---

# Task 02: Bound returns array on Deflated Sharpe endpoint

## Assigned Agent: `backend-developer`

## Objective
Add upper bounds to the `DeflatedSharpeRequest` fields to prevent unauthenticated DoS, and require auth on the endpoint.

## Context
Security audit finding [HIGH]: `returns` has no `max_length`, `num_trials` has no upper bound. The endpoint is unauthenticated and not rate-limited for anonymous callers. A single POST with millions of floats can consume significant CPU.

## Files to Modify/Create
- `src/api/schemas/metrics.py` — Add `max_length=10_000` to `returns`, `le=100_000` to `num_trials`, `le=525_600` to `annualization_factor`
- `src/api/middleware/auth.py` — Remove `/api/v1/metrics/` from `_PUBLIC_PREFIXES` (require auth)

## Acceptance Criteria
- [ ] `returns` field has `max_length=10_000`
- [ ] `num_trials` field has `le=100_000`
- [ ] `annualization_factor` field has `le=525_600`
- [ ] Endpoint requires authentication (removed from public prefixes)
- [ ] Existing DSR tests updated if they relied on unauthenticated access
- [ ] `ruff check` passes

## Dependencies
None — can run in parallel with Task 1.

## Agent Instructions
1. Read `src/api/schemas/metrics.py` — add the bounds to existing Field() definitions
2. Read `src/api/middleware/auth.py` — remove `/api/v1/metrics/` from `_PUBLIC_PREFIXES`
3. Check `tests/integration/test_metrics_api.py` for any tests that rely on unauthenticated access — update them to include auth headers

## Estimated Complexity
Low — simple field constraint additions + auth prefix change.
