---
task_id: 37
title: "Add platform infrastructure Grafana dashboard"
type: task
agent: "deploy-checker"
phase: 3
depends_on: []
status: "completed"
priority: "P2"
board: "[[customer-launch-fixes/README]]"
files: ["monitoring/dashboards/platform-infrastructure.json"]
tags:
  - task
  - monitoring
  - grafana
  - infrastructure
  - P2
---

# Task 37: Add platform infrastructure Grafana dashboard

## Assigned Agent: `deploy-checker`

## Objective
No Grafana dashboard shows platform infrastructure metrics (CPU, memory, disk, container health). Existing dashboards focus on application metrics. Add an infrastructure overview dashboard.

## Context
Infrastructure audit (SR-07) flagged this. Operators need visibility into infrastructure health, not just application metrics.

## Files to Create
- `monitoring/dashboards/platform-infrastructure.json` — New Grafana dashboard

## Acceptance Criteria
- [ ] Dashboard shows: container CPU/memory usage, disk usage, network I/O
- [ ] Panels for each service: api, celery worker, Redis, TimescaleDB, price ingestion
- [ ] Health status panel showing which containers are up/down
- [ ] Response time percentiles (p50, p95, p99) for the API
- [ ] Dashboard auto-provisions via Grafana provisioning config

## Agent Instructions
1. Read `monitoring/CLAUDE.md` for existing dashboard patterns
2. Use `cadvisor` or `node_exporter` metrics if available, or Docker metrics
3. Follow the existing dashboard JSON format for consistency
4. Include the dashboard in Grafana's provisioning directory

## Estimated Complexity
Medium — Grafana dashboard JSON creation
