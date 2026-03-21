---
task_id: 30
title: "Register platform-side Prometheus application metrics"
type: task
agent: "backend-developer"
phase: 4
depends_on: []
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "medium"
files: ["src/main.py", "src/order_engine/engine.py", "src/api/middleware/logging.py", "src/price_ingestion/service.py"]
tags:
  - task
  - agent
  - logging
---

# Task 30: Register Platform-Side Prometheus Metrics

## Assigned Agent: `backend-developer`

## Objective
Register application-level Prometheus metrics for the platform. Currently only default process collectors exist at `/metrics`.

## Metrics to Add

### In `src/main.py` or new `src/monitoring/metrics.py`
- `platform_orders_total` (Counter) — labels: `agent_id`, `side`, `order_type`
- `platform_order_latency_seconds` (Histogram) — labels: `order_type`
- `platform_api_errors_total` (Counter) — labels: `endpoint`, `status_code`
- `platform_price_ingestion_lag_seconds` (Gauge) — single value

### Instrumentation Points
- `src/order_engine/engine.py` — increment `platform_orders_total` on order placement, observe `platform_order_latency_seconds`
- `src/api/middleware/logging.py` — increment `platform_api_errors_total` on 4xx/5xx responses
- `src/price_ingestion/service.py` — set `platform_price_ingestion_lag_seconds` based on staleness

## Acceptance Criteria
- [ ] 4 platform metrics registered and emitting data
- [ ] Visible at `http://localhost:8000/metrics` alongside process metrics
- [ ] No performance regression (metric calls are fast)
- [ ] `ruff check` passes on all modified files

## Agent Instructions
- Use the DEFAULT `CollectorRegistry` (not a custom one) — the platform's `/metrics` endpoint already serves from it
- Keep metric definitions in a single location (either `src/main.py` or a new `src/monitoring/metrics.py`)
- Read `src/monitoring/CLAUDE.md` for existing monitoring patterns

## Estimated Complexity
Medium — 4 metrics across 4 files
