---
task_id: 17
title: "Review Grafana infrastructure dashboard"
type: task
agent: "deploy-checker"
phase: 3
depends_on: [7]
status: "pending"
priority: "medium"
board: "[[production-deployment/README]]"
files: ["monitoring/dashboards/platform-infrastructure.json"]
tags:
  - task
  - monitoring
  - observability
  - post-deploy
---

# Task 17: Review Grafana infrastructure dashboard

## Objective
Open the new Grafana platform infrastructure dashboard (from Task 37 of customer launch fixes) and verify all 14 panels render with data.

## Acceptance Criteria
- [ ] Grafana loads at `http://localhost:3000` (or public URL)
- [ ] "Platform Infrastructure" dashboard is auto-provisioned (appears in dashboard list)
- [ ] Service Health Overview (6 stat panels): API Up, Agent Up, Ingestion Lag, API Error Rate, Order Latency P95, Unhealthy Agents — all render with data
- [ ] Container CPU & Memory timeseries show data
- [ ] API Response Time Percentiles (P50/P95/P99) show data
- [ ] API Error Rate charts show data (may be empty if no errors — that's OK)
- [ ] Price Ingestion Lag shows data
- [ ] No "No Data" panels unless genuinely expected

## Dependencies
Task 07 — Grafana must be running with Prometheus datasource.

## Agent Instructions
1. Open Grafana UI
2. Navigate to Dashboards → Browse → find "Platform Infrastructure"
3. Click through all 5 sections — verify panels populate
4. If a panel shows "No Data":
   - Check Prometheus is scraping the expected target (Status → Targets)
   - Check the metric exists: `curl http://localhost:9090/api/v1/label/__name__/values | jq | grep <metric>`
   - Panel query may need adjustment
5. Take a screenshot of the dashboard for the deployment log
6. Bookmark the dashboard URL for ops team

## Estimated Complexity
Low — visual verification
