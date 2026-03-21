---
task_id: 29
title: "Expose agent /metrics endpoint and instrument code"
type: task
agent: "backend-developer"
phase: 4
depends_on: [28]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/server.py", "agent/logging_middleware.py", "agent/memory/postgres_store.py", "agent/memory/redis_cache.py", "agent/trading/loop.py", "agent/trading/journal.py", "agent/permissions/enforcement.py", "agent/permissions/budget.py"]
tags:
  - task
  - agent
  - logging
---

# Task 29: Expose Agent /metrics Endpoint and Instrument Code

## Assigned Agent: `backend-developer`

## Objective
1. Add a `/metrics` HTTP endpoint to `AgentServer` that serves Prometheus metrics
2. Add `.observe()` / `.inc()` / `.set()` calls to all Phase 2 instrumentation points

## Files to Modify

### `agent/server.py`
- Add HTTP handler for `/metrics` that returns `generate_latest(AGENT_REGISTRY)`
- The server already binds to port 8001

### `agent/logging_middleware.py`
- After logging API call, also emit:
  - `agent_api_call_duration.observe(latency_seconds)`
  - On error: `agent_api_errors_total.inc()`

### `agent/memory/postgres_store.py` + `redis_cache.py`
- On save/retrieve/reinforce: `agent_memory_ops_total.inc()`
- Cache hit: `agent_memory_cache_hits.inc()`
- Cache miss: `agent_memory_cache_misses.inc()`

### `agent/trading/loop.py`
- On decision: `agent_decisions_total.inc()`
- On health check: `agent_consecutive_errors.set()`, `agent_health_status.set()`

### `agent/trading/journal.py`
- On LLM call: `agent_llm_tokens_total.inc()`, `agent_llm_duration.observe()`, `agent_llm_cost_usd.inc()`

### `agent/permissions/enforcement.py`
- On denial: `agent_permission_denials.inc()`

### `agent/permissions/budget.py`
- On budget check: `agent_budget_usage.set(current/limit)`

## Acceptance Criteria
- [ ] `GET http://agent:8001/metrics` returns Prometheus-formatted metrics
- [ ] All 16 metrics emit data during normal agent operation
- [ ] Metrics labels match the registry definition
- [ ] No latency impact (metrics calls are synchronous but microsecond-fast)
- [ ] `ruff check` passes on all modified files

## Estimated Complexity
Medium — many files, but each change is 1-3 lines (metric call)
