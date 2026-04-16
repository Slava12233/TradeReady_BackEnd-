---
task_id: 14
title: "Fix price staleness fail-open on Redis error"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["src/price_ingestion/service.py", "src/cache/price_cache.py"]
tags:
  - task
  - backend
  - data-integrity
  - redis
  - P1
---

# Task 14: Fix price staleness fail-open on Redis error

## Assigned Agent: `backend-developer`

## Objective
When Redis errors occur during price staleness checks, the system fails open — treating stale prices as fresh. This means users could trade on outdated prices without any warning.

## Context
Code standards review (SR-04) flagged this as HIGH. Fail-open on price data is dangerous for a trading platform, even a simulated one. Stale prices should be flagged, not silently served.

## Files to Modify
- `src/cache/price_cache.py` or `src/price_ingestion/service.py` — Find the staleness check that catches Redis errors
- Change from fail-open to fail-closed: on Redis error, mark price as stale/unknown

## Acceptance Criteria
- [ ] Redis connection errors during staleness check mark prices as stale (not fresh)
- [ ] Stale prices include a `stale: true` flag or similar indicator in the API response
- [ ] Log a warning when Redis errors cause staleness checks to degrade
- [ ] Normal operation (Redis healthy) is unchanged
- [ ] Test: simulate Redis error → verify price is marked stale

## Agent Instructions
1. Read `src/cache/CLAUDE.md` for cache patterns
2. Find the try/except around the Redis staleness check
3. Change the except block from returning "fresh" to returning "stale/unknown"
4. Add a structlog warning for observability

## Estimated Complexity
Low — change one except handler + add test
