---
task_id: 15
title: "Cache symbol validation to avoid per-request DB query"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["src/exchange/symbol_mapper.py", "src/cache/price_cache.py"]
tags:
  - task
  - performance
  - backend
  - database
  - P1
---

# Task 15: Cache symbol validation

## Assigned Agent: `backend-developer`

## Objective
Symbol validation fires a DB query on every market data request (~1200/min in production). Cache the valid symbols list in Redis with a reasonable TTL.

## Context
Performance audit (SR-08) flagged this as HIGH — unnecessary DB load on every request. The list of valid symbols changes rarely (only when new pairs are added).

## Files to Modify
- `src/exchange/symbol_mapper.py` — Add Redis-backed symbol cache
- `src/cache/price_cache.py` — Add symbol cache functions if needed

## Acceptance Criteria
- [ ] Valid symbols are cached in Redis with TTL (e.g., 5 minutes)
- [ ] Cache miss falls back to DB query and populates cache
- [ ] Cache invalidation when symbols are added/removed
- [ ] DB queries for symbol validation drop to near-zero in steady state
- [ ] Test: verify cache hit avoids DB call

## Agent Instructions
1. Read `src/exchange/CLAUDE.md` for symbol mapper patterns
2. Read `src/cache/CLAUDE.md` for Redis cache patterns
3. Use a Redis SET or sorted set for the symbol list
4. TTL of 300s (5 minutes) is reasonable — symbols don't change frequently
5. Keep the DB fallback for cache misses

## Estimated Complexity
Medium — caching layer addition
