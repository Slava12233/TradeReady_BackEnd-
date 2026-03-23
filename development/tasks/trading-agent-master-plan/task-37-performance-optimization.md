---
task_id: 37
title: "Performance optimization pass"
type: task
agent: "perf-checker"
phase: 6
depends_on: [27]
status: "completed"
priority: "medium"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/conversation/context.py", "agent/trading/loop.py"]
tags:
  - task
  - performance
  - optimization
---

# Task 37: Performance optimization

## Assigned Agent: `perf-checker`

## Objective
Audit and optimize the agent's hot paths:
1. `ContextBuilder.build()` — add 30-second cache for portfolio state
2. Batch API calls (fetch all prices at once, not per-symbol)
3. Verify WebSocket integration (Task 27) reduces API call count
4. Check for N+1 queries in decision settlement loop

## Acceptance Criteria
- [ ] `ContextBuilder` caches portfolio state (30s TTL)
- [ ] Price fetches batched where possible
- [ ] API call count per trading cycle reduced by >50%
- [ ] No N+1 queries in settlement or journal paths
- [ ] Performance report generated

## Estimated Complexity
Medium — profiling and optimizing multiple hot paths.
