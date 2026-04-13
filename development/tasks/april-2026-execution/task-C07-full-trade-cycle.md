---
task_id: C-07
title: "Run full trade cycle"
type: task
agent: "ml-engineer"
track: C
depends_on: ["C-06"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["agent/trading/loop.py"]
tags:
  - task
  - trading
  - integration
  - critical-path
  - milestone
---

# Task C-07: Run full trade cycle

## Assigned Agent: `ml-engineer`

## Objective
Execute the complete TradingLoop for 10 iterations: observe → decide → execute → monitor → journal → learn.

## Context
This validates the entire trading pipeline end-to-end with multiple cycles. The full loop includes journaling decisions and the learning feedback step.

## Files to Reference
- `agent/trading/loop.py` — full cycle implementation
- `agent/trading/journal.py` — TradingJournal
- `agent/strategies/` — all strategy components

## Acceptance Criteria
- [ ] 10 complete loop iterations execute without crash
- [ ] Each iteration logs: observation, decision, execution result, monitoring status
- [ ] Journal entries recorded for each decision (with reasoning)
- [ ] Learning step executes (even if no model update — just verify the pipeline)
- [ ] No connection pool exhaustion or session leaks
- [ ] No memory growth across 10 iterations
- [ ] Multiple trades executed (not all held/vetoed)

## Dependencies
- **C-06**: Single trade verified in DB (confirms execution works)

## Agent Instructions
Initialize the TradingLoop with the test agent and run 10 iterations. Monitor logs for:
1. Connection pool warnings
2. Session leak errors
3. Memory growth (check process memory before/after)
4. Increasing latency per iteration

If iterations are too fast (< 1 second each), add a small delay to simulate realistic trading intervals. Document any errors, unexpected behaviors, or configuration adjustments needed.

## Estimated Complexity
High — full integration test. Most likely to surface bugs.
