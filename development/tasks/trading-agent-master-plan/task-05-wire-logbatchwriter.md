---
task_id: 05
title: "Wire LogBatchWriter into AgentServer decision loop"
type: task
agent: "backend-developer"
phase: 0
depends_on: []
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/server.py", "agent/logging_writer.py", "agent/logging_middleware.py", "agent/trading/loop.py"]
tags:
  - task
  - integration
  - foundation
---

# Task 05: Wire LogBatchWriter into AgentServer

## Assigned Agent: `backend-developer`

## Objective
Connect the existing `LogBatchWriter` (in `agent/logging_writer.py`) to the agent's decision loop so that API calls and strategy signals are actually persisted to the `agent_api_calls` and `agent_strategy_signals` DB tables.

## Context
The `LogBatchWriter` class exists and is fully implemented with dual deque buffers, flush triggers, and DB persistence. However, it is not instantiated anywhere in the `AgentServer` or `TradingLoop`. The `log_api_call()` context manager in `agent/logging_middleware.py` emits structlog events and Prometheus metrics but does NOT call `writer.add_api_call()`.

## Steps
1. Instantiate `LogBatchWriter` as a singleton in `AgentServer.__init__()`
2. Pass it to `TradingLoop`, `SignalGenerator`, and `TradeExecutor`
3. In `log_api_call()`, add an optional `writer` parameter — when provided, call `writer.add_api_call()` with the call metadata
4. In `EnsembleRunner`, call `writer.add_signal()` after each strategy produces a signal
5. On `AgentServer.shutdown()`, call `await writer.flush()` before closing

## Acceptance Criteria
- [ ] `LogBatchWriter` instantiated in `AgentServer`
- [ ] API calls are written to `agent_api_calls` table during trading
- [ ] Strategy signals are written to `agent_strategy_signals` table
- [ ] `writer.flush()` called on graceful shutdown
- [ ] Tests verify buffer → DB persistence

## Estimated Complexity
Medium — wiring existing components together, no new logic needed.
