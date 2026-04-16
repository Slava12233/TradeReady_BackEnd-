---
task_id: 26
title: "Pipeline rate limiter Redis calls"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: ["src/api/middleware/rate_limit.py"]
tags:
  - task
  - performance
  - redis
  - P2
---

# Task 26: Pipeline rate limiter Redis calls

## Assigned Agent: `backend-developer`

## Objective
Rate limiter uses 2 sequential Redis calls (GET + INCR/EXPIRE) when a single pipeline call would halve the latency.

## Context
Performance audit (SR-08) flagged this. Every API request goes through the rate limiter, so this affects overall latency.

## Files to Modify
- `src/api/middleware/rate_limit.py` — Use Redis pipeline for GET + INCR/EXPIRE

## Acceptance Criteria
- [ ] Rate limiter uses a single Redis pipeline instead of 2 sequential calls
- [ ] Latency per rate-limit check is reduced
- [ ] Rate limiting behavior is identical (same limits, same responses)
- [ ] Test: verify rate limiting still works correctly with pipeline

## Agent Instructions
1. Read `src/api/middleware/CLAUDE.md` for rate limiter implementation
2. Use `redis.pipeline()` to batch the GET and INCR/EXPIRE commands
3. Consider using a Lua script for atomic rate limiting (INCR + EXPIRE in one call)

## Estimated Complexity
Low — Redis pipeline refactor
