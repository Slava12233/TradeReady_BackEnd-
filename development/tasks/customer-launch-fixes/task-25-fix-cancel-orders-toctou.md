---
task_id: 25
title: "Fix cancel-all-orders TOCTOU race"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: ["src/order_engine/service.py"]
tags:
  - task
  - backend
  - concurrency
  - P2
---

# Task 25: Fix cancel-all-orders TOCTOU race

## Assigned Agent: `backend-developer`

## Objective
Cancel-all-orders double-fetches open orders (Time of Check/Time of Use race condition). Between the fetch and the cancel, new orders could be placed or existing orders could fill.

## Context
Performance audit (SR-08) flagged this. The race is unlikely to cause visible bugs in normal usage but could lead to inconsistent state under concurrent load.

## Files to Modify
- `src/order_engine/service.py` — Combine fetch and cancel into a single atomic operation

## Acceptance Criteria
- [ ] Cancel-all-orders uses a single query (UPDATE ... WHERE status = 'open' RETURNING)
- [ ] No double-fetch pattern
- [ ] Orders placed between check and cancel are not affected
- [ ] Test: verify atomic cancellation

## Agent Instructions
1. Read `src/order_engine/CLAUDE.md` for order engine patterns
2. Replace the two-step (fetch open orders → cancel each) with single UPDATE query
3. Use `RETURNING *` to get the cancelled orders for the response

## Estimated Complexity
Low — query consolidation
