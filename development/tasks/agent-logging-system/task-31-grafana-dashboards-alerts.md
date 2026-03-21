---
task_id: 31
title: "Create Grafana dashboard definitions and alert rules"
type: task
agent: "backend-developer"
phase: 4
depends_on: [28, 29]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "medium"
files: ["monitoring/dashboards/agent-overview.json", "monitoring/dashboards/agent-api-calls.json", "monitoring/dashboards/agent-llm-usage.json", "monitoring/dashboards/agent-memory.json", "monitoring/dashboards/agent-strategy.json", "monitoring/dashboards/ecosystem-health.json", "monitoring/alerts/agent-alerts.yml"]
tags:
  - task
  - agent
  - logging
---

# Task 31: Create Grafana Dashboards and Alert Rules

## Assigned Agent: `backend-developer`

## Objective
Create 6 Grafana dashboard JSON definitions and 1 Prometheus alert rules file.

## Dashboards to Create

| Dashboard | Key Panels |
|-----------|-----------|
| `agent-overview.json` | Decision rate (rate), PnL histogram, win rate gauge, active agents, health status |
| `agent-api-calls.json` | Latency heatmap, error rate, calls by endpoint, top 10 slowest |
| `agent-llm-usage.json` | Token consumption over time, cost per day, latency by model, calls by purpose |
| `agent-memory.json` | Cache hit ratio, memory count by type, retrieval score distribution |
| `agent-strategy.json` | Per-strategy confidence distribution, ensemble weight trends, veto rate |
| `ecosystem-health.json` | Agent + platform health combined, error correlation, price lag |

## Alert Rules (`monitoring/alerts/agent-alerts.yml`)

```yaml
groups:
  - name: agent-alerts
    rules:
      - alert: AgentUnhealthy
        expr: agent_health_status == 0
        for: 5m
        labels: { severity: critical }
      - alert: AgentHighErrorRate
        expr: rate(agent_api_errors_total[5m]) > 0.1
        for: 5m
        labels: { severity: warning }
      - alert: AgentHighLLMCost
        expr: increase(agent_llm_cost_usd_total[1h]) > 5.0
        labels: { severity: warning }
      - alert: AgentBudgetExhausted
        expr: agent_budget_usage_ratio > 0.95
        labels: { severity: warning }
      - alert: AgentDecisionDrop
        expr: rate(agent_decisions_total[15m]) == 0
        for: 30m
        labels: { severity: warning }
      - alert: AgentMemoryCacheLow
        expr: agent_memory_cache_hits_total / (agent_memory_cache_hits_total + agent_memory_cache_misses_total) < 0.5
        for: 1h
        labels: { severity: info }
```

## Acceptance Criteria
- [ ] 6 dashboard JSON files valid and importable into Grafana
- [ ] Each dashboard uses correct metric names from `agent/metrics.py`
- [ ] Alert rules file valid YAML with correct PromQL expressions
- [ ] Dashboards have variables for `agent_id` filtering
- [ ] `monitoring/dashboards/` and `monitoring/alerts/` directories created

## Agent Instructions
- Create `monitoring/dashboards/` and `monitoring/alerts/` directories
- Use Grafana JSON model format (can be minimal — focus on correct queries)
- Each dashboard should have a datasource variable pointing to Prometheus
- Add an `agent_id` template variable for filtering

## Estimated Complexity
Medium — JSON dashboard definitions are verbose but formulaic
