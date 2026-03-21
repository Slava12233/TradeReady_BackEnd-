---
task_id: 28
title: "Create Prometheus metrics registry module"
type: task
agent: "backend-developer"
phase: 4
depends_on: [9]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["agent/metrics.py"]
tags:
  - task
  - agent
  - logging
---

# Task 28: Create Prometheus Metrics Registry

## Assigned Agent: `backend-developer`

## Objective
Create `agent/metrics.py` — a centralized Prometheus metrics registry with all counters, histograms, and gauges for the agent ecosystem.

## Files to Create
- `agent/metrics.py` — full metrics registry

## Metrics to Register

### Decision Metrics
- `agent_decisions_total` (Counter) — labels: `agent_id`, `decision_type`, `direction`
- `agent_trade_pnl_usd` (Histogram) — labels: `agent_id`, `symbol`; buckets: [-1000, -500, -100, -50, -10, 0, 10, 50, 100, 500, 1000]

### API Call Metrics
- `agent_api_call_duration_seconds` (Histogram) — labels: `agent_id`, `channel`, `endpoint`; buckets: [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
- `agent_api_errors_total` (Counter) — labels: `agent_id`, `channel`, `endpoint`, `error_type`

### Memory Metrics
- `agent_memory_operations_total` (Counter) — labels: `agent_id`, `operation`
- `agent_memory_cache_hits_total` (Counter) — labels: `agent_id`
- `agent_memory_cache_misses_total` (Counter) — labels: `agent_id`

### LLM Metrics
- `agent_llm_tokens_total` (Counter) — labels: `agent_id`, `model`, `direction`
- `agent_llm_call_duration_seconds` (Histogram) — labels: `agent_id`, `model`, `purpose`
- `agent_llm_cost_usd_total` (Counter) — labels: `agent_id`, `model`

### Permission/Budget Metrics
- `agent_permission_denials_total` (Counter) — labels: `agent_id`, `capability`
- `agent_budget_usage_ratio` (Gauge) — labels: `agent_id`, `limit_type`

### Strategy Metrics
- `agent_strategy_signal_confidence` (Histogram) — labels: `agent_id`, `strategy_name`

### Health Metrics
- `agent_consecutive_errors` (Gauge) — labels: `agent_id`
- `agent_health_status` (Gauge) — labels: `agent_id`

## Implementation Details
- Use a custom `CollectorRegistry` (`AGENT_REGISTRY`) to avoid conflicts with the platform's default registry
- All metrics use the custom registry: `registry=AGENT_REGISTRY`
- Export the registry for use in the `/metrics` endpoint

## Acceptance Criteria
- [ ] 16 metrics defined with correct types, labels, and buckets
- [ ] Custom `AGENT_REGISTRY` used (not default registry)
- [ ] All metrics importable individually
- [ ] `ruff check agent/metrics.py` passes
- [ ] No import-time side effects beyond metric registration

## Estimated Complexity
Low — declarative metric definitions, no logic
