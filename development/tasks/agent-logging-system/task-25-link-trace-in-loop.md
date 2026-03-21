---
task_id: 25
title: "Link trace_id in TradingLoop decisions and strategy signals"
type: task
agent: "backend-developer"
phase: 3
depends_on: [21, 24]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/trading/loop.py", "agent/strategies/ensemble/run.py"]
tags:
  - task
  - agent
  - logging
---

# Task 25: Link trace_id in TradingLoop and Strategy Signals

## Assigned Agent: `backend-developer`

## Objective
Wire up trace ID generation in the TradingLoop's `tick()` method and log per-strategy signals to the `agent_strategy_signals` table via the batch writer.

## Files to Modify

### `agent/trading/loop.py`
1. At the start of each `tick()`, call `set_trace_id()` to generate a new trace ID for this decision cycle
2. Pass the `trace_id` to `AgentDecision` records (the new `trace_id` column from Task 19)
3. Pass the `LogBatchWriter` instance to log API calls made during the tick

### `agent/strategies/ensemble/run.py`
1. After each strategy produces a signal, record it via `batch_writer.add_signal(...)` with:
   - `trace_id` from context
   - `strategy_name` (rl_ppo, evolutionary, regime)
   - `symbol`, `action`, `confidence`, `weight`
   - `signal_data` as JSONB (strategy-specific details)

## Integration Points
- `TradingLoop.__init__()` should accept an optional `LogBatchWriter` instance
- `TradingLoop.tick()` should call `set_trace_id()` at the start
- `EnsembleRunner.run()` should accept an optional `LogBatchWriter`

## Acceptance Criteria
- [ ] Each `tick()` generates a unique `trace_id`
- [ ] `AgentDecision` records include `trace_id`
- [ ] Per-strategy signals logged to batch writer
- [ ] Batch writer is optional (no crash if None — backwards compatible)
- [ ] `ruff check` passes on all modified files

## Agent Instructions
- Read `agent/trading/loop.py` and `agent/strategies/ensemble/run.py` first
- The `set_trace_id()` call at the start of `tick()` ensures all subsequent log calls in that tick share the same trace
- Use `get_trace_id()` when creating records — don't pass trace_id as a parameter through every function

## Estimated Complexity
Medium — integration across multiple files with optional dependency
