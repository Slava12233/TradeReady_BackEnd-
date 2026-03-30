---
task_id: R1-06
title: "Import Grafana dashboards and verify Prometheus scraping"
type: task
agent: "deploy-checker"
phase: 1
depends_on: ["R1-05"]
status: "completed"
priority: "medium"
board: "[[c-level-recommendations/README]]"
files: ["monitoring/dashboards/", "monitoring/provisioning/"]
tags:
  - task
  - infrastructure
  - monitoring
---

# Task R1-06: Import Grafana Dashboards and Verify Prometheus

## Assigned Agent: `deploy-checker`

## Objective
Verify Grafana auto-provisioning loaded all 6 dashboards and Prometheus is scraping both platform and agent metrics.

## Context
6 Grafana dashboards exist in `monitoring/dashboards/` and should be auto-provisioned via volume mounts. 11 Prometheus alert rules are defined in `monitoring/alerts/agent-alerts.yml`.

## Acceptance Criteria
- [ ] Grafana accessible at `http://localhost:3000`
- [ ] 6 dashboards visible: agent-overview, agent-api-calls, agent-llm-usage, agent-memory, agent-strategy, ecosystem-health
- [ ] Prometheus accessible at `http://localhost:9090`
- [ ] Prometheus targets show 2+ scrape targets with status "up"
- [ ] Alert rules loaded (11 rules in agent-alerts.yml)

## Dependencies
- R1-05 (all services healthy)

## Agent Instructions
1. Check Grafana dashboard list: `curl http://localhost:3000/api/dashboards`
2. Check Prometheus targets: `curl http://localhost:9090/api/v1/targets`
3. If dashboards missing, check provisioning config in `monitoring/provisioning/dashboards/dashboards.yml`

## Estimated Complexity
Low — verification + minor troubleshooting
