---
task_id: 12
title: "Performance benchmarks (batch stepping + webhook load)"
type: task
agent: "e2e-tester"
phase: 3
depends_on: [7]
status: "pending"
priority: "low"
board: "[[v003-next-steps/README]]"
files: []
tags:
  - task
  - performance
  - benchmarks
  - e2e
---

# Task 12: Performance Benchmarks

## Assigned Agent: `e2e-tester`

## Objective
Measure actual batch stepping speedup and verify webhook delivery at scale.

## Context
The batch stepping improvement claims 100-500x throughput. The webhook system needs load testing to verify Celery handles concurrent deliveries.

## Acceptance Criteria
- [ ] Benchmark: 10K steps via single `/step` vs 10K via `/step/batch/fast` (batches of 500)
- [ ] Report: actual throughput ratio (expected 100-500x)
- [ ] Webhook load: 50 subscriptions for same event, fire one completion, all 50 delivered within 60s
- [ ] Results documented in a report file

## Dependencies
- **Task 7** (full test suite passes) — confirms system is stable before benchmarking

## Agent Instructions
1. Run benchmarks against running platform (Docker services up)
2. Create a test account, session, and webhook subscriptions
3. Time both approaches and report the ratio
4. For webhooks: use a simple echo server to receive deliveries

## Estimated Complexity
Medium — requires running platform and timing infrastructure.
