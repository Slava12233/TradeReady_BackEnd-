---
task_id: 15
title: "Monitor Alertmanager 24h baseline"
type: task
agent: "deploy-checker"
phase: 3
depends_on: [8]
status: "pending"
priority: "medium"
board: "[[production-deployment/README]]"
files: ["monitoring/alertmanager.yml"]
tags:
  - task
  - monitoring
  - alerting
  - post-deploy
---

# Task 15: Monitor Alertmanager 24h baseline

## Objective
Observe Alertmanager behavior for 24 hours post-deploy. Tune routing if alerts are too noisy or silent.

## Acceptance Criteria
- [ ] After 24 hours: no critical alerts that were actual false positives
- [ ] No alert storms (> 10 alerts of same type in 5 minutes)
- [ ] Expected baseline alerts are delivered (e.g., `PriceIngestionDegraded` if any pairs are stale)
- [ ] On-call recipient confirms email delivery is working
- [ ] If false positives detected: add inhibition rules or adjust thresholds

## Dependencies
Task 08 — Alertmanager must be verified reachable.

## Agent Instructions
1. Over first 24 hours, check Alertmanager UI periodically: `http://localhost:9093`
2. Review delivered alerts in the on-call email inbox
3. Cross-reference with Prometheus metrics to confirm alerts are genuine
4. If alert is noisy (false positive or too frequent):
   - Adjust threshold in the alert rule (`monitoring/prometheus_rules.yml` or equivalent)
   - Or add an inhibition rule in `monitoring/alertmanager.yml`
5. If an alert that SHOULD fire is silent: check Prometheus `/rules` page and Alertmanager Status → Config
6. Document baseline expectations in `monitoring/CLAUDE.md`

## Estimated Complexity
Medium — 24-hour observation window
