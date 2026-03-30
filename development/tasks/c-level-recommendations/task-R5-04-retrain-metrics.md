---
task_id: R5-04
title: "Add Prometheus metrics for retrain events"
type: task
agent: "backend-developer"
phase: 4
depends_on: ["R5-01"]
status: "completed"
priority: "medium"
board: "[[c-level-recommendations/README]]"
files: ["agent/metrics.py"]
tags:
  - task
  - retraining
  - monitoring
  - prometheus
---

# Task R5-04: Add Prometheus Metrics for Retrain Events

## Assigned Agent: `backend-developer`

## Objective
Add Prometheus metrics to track retraining runs, durations, and deployment outcomes.

## Files to Modify/Create
- `agent/metrics.py` — add 3 new metrics to `AGENT_REGISTRY`

## Acceptance Criteria
- [ ] `agent_retrain_runs_total` Counter (labels: strategy, trigger)
- [ ] `agent_retrain_duration_seconds` Histogram (labels: strategy)
- [ ] `agent_retrain_deployed_total` Counter (labels: strategy)
- [ ] Metrics appear at `/metrics` endpoint after a retrain cycle
- [ ] Trigger labels: `scheduled`, `drift`, `manual`

## Dependencies
- R5-01 (retrain tasks must exist to instrument)

## Estimated Complexity
Low — 3 metric definitions + instrumentation points
