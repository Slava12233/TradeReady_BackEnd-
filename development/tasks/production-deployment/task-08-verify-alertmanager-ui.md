---
task_id: 08
title: "Verify Alertmanager UI reachable"
type: task
agent: "deploy-checker"
phase: 2
depends_on: [7]
status: "pending"
priority: "high"
board: "[[production-deployment/README]]"
files: []
tags:
  - task
  - alerting
  - smoke-test
---

# Task 08: Verify Alertmanager UI reachable

## Objective
Confirm the Alertmanager web UI is reachable and the loaded config is valid.

## Acceptance Criteria
- [ ] `curl http://localhost:9093/-/ready` returns 200 OK
- [ ] `http://localhost:9093` web UI loads in browser (via SSH tunnel if needed)
- [ ] Status page shows the loaded config (should match `monitoring/alertmanager.yml`)
- [ ] No config parse errors in `docker compose logs alertmanager`
- [ ] Test alert from Task 06 appears in the Alerts tab

## Dependencies
Task 07 — Alertmanager container must be running.

## Agent Instructions
1. Verify readiness: `curl -f http://localhost:9093/-/ready` (exit code 0)
2. Check Alertmanager logs: `docker compose logs alertmanager | tail -20` — should be free of `error` entries
3. Open UI (via SSH port-forward: `ssh -L 9093:localhost:9093 <server>`)
4. Navigate Status → Config — verify loaded config matches `monitoring/alertmanager.yml`
5. Check Alerts tab — should show the test alert fired in Task 06 (until it resolves)

## Estimated Complexity
Low — smoke test
