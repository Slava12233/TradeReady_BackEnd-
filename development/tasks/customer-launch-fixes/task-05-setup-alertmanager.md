---
task_id: 05
title: "Set up Alertmanager pipeline"
type: task
agent: "deploy-checker"
phase: 1
depends_on: []
status: "completed"
priority: "P0"
board: "[[customer-launch-fixes/README]]"
files: ["monitoring/alertmanager.yml", "monitoring/prometheus.yml", "docker-compose.yml"]
tags:
  - task
  - infrastructure
  - alerting
  - monitoring
  - P0
---

# Task 05: Set up Alertmanager pipeline

## Assigned Agent: `deploy-checker`

## Objective
11 Prometheus alert rules exist but there's no Alertmanager configured — alerts fire into the void. Set up Alertmanager with at minimum email notifications so incidents are detected.

## Context
Infrastructure audit (SR-07) flagged this as a P0 — production incidents currently go completely undetected. The alert rules are in `monitoring/` but Alertmanager is not configured.

## Files to Create/Modify
- `monitoring/alertmanager.yml` — Create Alertmanager configuration with email receiver
- `monitoring/prometheus.yml` — Ensure alerting section points to Alertmanager
- `docker-compose.yml` — Add Alertmanager service container

## Acceptance Criteria
- [ ] Alertmanager container added to docker-compose.yml
- [ ] Alertmanager configured with at least one receiver (email or webhook)
- [ ] Prometheus alerting config points to Alertmanager endpoint
- [ ] Existing 11 alert rules will route to the receiver
- [ ] Test: can verify Alertmanager is reachable at its web UI port

## Agent Instructions
1. Read `monitoring/CLAUDE.md` for existing monitoring setup
2. Read the existing Prometheus config to understand current alert rules
3. Add Alertmanager as a Docker service (use `prom/alertmanager:latest`)
4. Configure a simple email receiver — use environment variables for SMTP credentials
5. Wire Prometheus's `alerting.alertmanagers` to point at the Alertmanager service

## Estimated Complexity
Medium — Docker + config changes, no code
