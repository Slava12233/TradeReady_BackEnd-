---
task_id: 27
title: "Performance check (training & inference)"
agent: "perf-checker"
phase: Post
depends_on: [6, 11, 16, 20, 25]
status: "completed"
priority: "medium"
files: ["agent/strategies/"]
---

# Task 27: Performance check (training & inference)

## Assigned Agent: `perf-checker`

## Objective
Check all strategy code for performance issues: blocking async calls, unbounded memory growth during training, N+1 API calls, and inference latency.

## Focus Areas
- Training loop: memory growth over 672 episodes (should be stable)
- Parallel envs: API call concurrency doesn't overwhelm the server
- Evolution loop: 30 generations × 12 agents doesn't leak memory
- Regime classifier inference: must be < 10ms per prediction
- Ensemble pipeline step: total latency should be < 500ms
- Model loading: should be lazy (load once, reuse)

## Acceptance Criteria
- [ ] No unbounded memory growth identified
- [ ] API call patterns are efficient (batch where possible)
- [ ] No blocking sync calls in async contexts
- [ ] Performance report saved to `development/code-reviews/`

## Dependencies
All implementation tasks complete.

## Estimated Complexity
Low — focused review.
