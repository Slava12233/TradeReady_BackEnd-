---
task_id: 22
title: "Create repositories for agent_api_calls and agent_strategy_signals"
type: task
agent: "backend-developer"
phase: 3
depends_on: [19, 20]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["src/database/repositories/agent_api_call_repo.py", "src/database/repositories/agent_strategy_signal_repo.py", "src/dependencies.py"]
tags:
  - task
  - agent
  - logging
---

# Task 22: Create Repositories for New Tables

## Assigned Agent: `backend-developer`

## Objective
Create repository classes for the 2 new logging tables and register them in the dependency injection system.

## Files to Create
- `src/database/repositories/agent_api_call_repo.py` — `AgentApiCallRepository`
- `src/database/repositories/agent_strategy_signal_repo.py` — `AgentStrategySignalRepository`

## Files to Modify
- `src/dependencies.py` — add dependency aliases

## Repository Methods

### `AgentApiCallRepository`
- `create(api_call: AgentApiCall) -> AgentApiCall` — insert single record
- `bulk_create(api_calls: list[AgentApiCall]) -> int` — bulk insert (for batch writer)
- `get_by_trace(agent_id: UUID, trace_id: str) -> list[AgentApiCall]` — all calls in a trace
- `get_recent(agent_id: UUID, limit: int = 100) -> list[AgentApiCall]` — recent calls
- `get_stats(agent_id: UUID, start: datetime, end: datetime) -> dict` — aggregated stats (count, avg latency, error rate by endpoint)
- `prune_old(agent_id: UUID, older_than: datetime) -> int` — cleanup

### `AgentStrategySignalRepository`
- `create(signal: AgentStrategySignal) -> AgentStrategySignal` — insert single
- `bulk_create(signals: list[AgentStrategySignal]) -> int` — bulk insert
- `get_by_trace(trace_id: str) -> list[AgentStrategySignal]` — all signals in a trace
- `get_by_strategy(agent_id: UUID, strategy_name: str, limit: int = 100) -> list` — recent signals by strategy
- `get_attribution(agent_id: UUID, start: datetime, end: datetime) -> list[dict]` — grouped by strategy with avg confidence

## Dependency Injection
Add to `src/dependencies.py`:
```python
AgentApiCallRepoDep = Annotated[AgentApiCallRepository, Depends(get_agent_api_call_repo)]
AgentStrategySignalRepoDep = Annotated[AgentStrategySignalRepository, Depends(get_agent_strategy_signal_repo)]
```

## Acceptance Criteria
- [ ] Both repositories follow existing repo patterns (see `src/database/repositories/agent_learning_repo.py`)
- [ ] `bulk_create` uses `session.add_all()` for efficiency
- [ ] `get_stats` returns dict with `total_calls`, `avg_latency_ms`, `error_rate`, `by_endpoint`
- [ ] Dependencies registered with typed aliases
- [ ] `ruff check` passes on all new/modified files

## Agent Instructions
- Read `src/database/repositories/CLAUDE.md` and an existing agent repo for patterns
- Use lazy imports in `src/dependencies.py` (follow existing `# noqa: PLC0415` pattern)
- The `bulk_create` method is critical for the batch writer (Task 24) — optimize for throughput

## Estimated Complexity
Medium — 2 new files with multiple query methods each
