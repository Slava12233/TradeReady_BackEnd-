---
task_id: 36
title: "Fix Prometheus scraping and verify Grafana dashboards"
type: task
agent: "deploy-checker"
phase: 6
depends_on: []
status: "completed"
priority: "medium"
board: "[[trading-agent-master-plan/README]]"
files: ["docker-compose.yml", "monitoring/"]
tags:
  - task
  - monitoring
  - infrastructure
---

# Task 36: Prometheus + Grafana fixes

## Assigned Agent: `deploy-checker`

## Objective
Verify Prometheus scrapes both `:8000/metrics` (platform) and `:8001/metrics` (agent). Import all 6 Grafana dashboards. Verify alert rules fire correctly.

## Acceptance Criteria
- [ ] Prometheus config includes scrape job for `:8001`
- [ ] All 6 Grafana dashboards imported and showing data
- [ ] 11 alert rules configured and testable
- [ ] Agent health dashboard shows real metrics
- [ ] Docker compose volumes mount dashboard JSON files

## Estimated Complexity
Low — configuration and verification.
