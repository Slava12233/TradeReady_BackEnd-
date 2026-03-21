---
task_id: 34
title: "Add feedback lifecycle management and anomaly detection"
type: task
agent: "backend-developer"
phase: 5
depends_on: [21, 33]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "medium"
files: ["src/database/models.py", "src/api/routes/agents.py", "agent/trading/loop.py"]
tags:
  - task
  - agent
  - logging
---

# Task 34: Feedback Lifecycle and Anomaly Detection

## Assigned Agent: `backend-developer`

## Objective
1. Add lifecycle tracking to the `agent_feedback` table (status, resolution)
2. Add anomaly detection to the TradingLoop's learn phase

## Part 1: Feedback Lifecycle

### Database Changes
Add columns to `AgentFeedback`:
- `status VARCHAR(20) DEFAULT 'submitted'` — enum: submitted, acknowledged, in_progress, resolved, wont_fix
- `resolved_at TIMESTAMPTZ` — when resolved
- `resolution TEXT` — resolution description

### New Endpoint
```
PATCH /api/v1/agents/{agent_id}/feedback/{feedback_id}
    body: {"status": "resolved", "resolution": "Fixed in commit abc123"}
```

### Alembic Migration
Add the 3 new columns (nullable, with defaults).

## Part 2: Anomaly Detection

### Enhancement to `agent/trading/loop.py`
After the learn phase in each `tick()`, compare current metrics to rolling averages:

```python
async def _detect_anomalies(self, tick_metrics: dict):
    """Compare current tick metrics to rolling baselines."""
    anomalies = []

    # API latency spike (>2x rolling p95)
    if tick_metrics["avg_api_latency"] > self._rolling_p95_latency * 2:
        anomalies.append(("api_latency_spike", tick_metrics["avg_api_latency"]))

    # Confidence distribution shift
    if tick_metrics["avg_confidence"] < self._rolling_avg_confidence * 0.7:
        anomalies.append(("confidence_drop", tick_metrics["avg_confidence"]))

    # PnL outlier (>3 std devs)
    if abs(tick_metrics["pnl"]) > self._rolling_pnl_std * 3:
        anomalies.append(("pnl_outlier", tick_metrics["pnl"]))

    for anomaly_type, value in anomalies:
        logger.warning("agent.anomaly.detected", type=anomaly_type, value=value)
```

Rolling baselines maintained as exponential moving averages (lightweight, no DB required).

## Acceptance Criteria
- [ ] `AgentFeedback` has status, resolved_at, resolution columns
- [ ] PATCH endpoint updates feedback status
- [ ] Only account owners can update their agent's feedback
- [ ] Anomaly detection runs after each tick
- [ ] Anomalies logged at WARNING level with type and value
- [ ] Rolling baselines use EMA (no additional DB queries)
- [ ] Alembic migration for feedback columns
- [ ] `ruff check` passes on all modified files

## Agent Instructions
- For the feedback migration: use `migration-helper` patterns from `alembic/CLAUDE.md`
- The PATCH endpoint follows REST conventions — partial update, return updated resource
- For anomaly detection: keep it lightweight — EMA with alpha=0.1 is sufficient
- Store EMA state as instance variables on `TradingLoop` (ephemeral, reset on restart)

## Estimated Complexity
Medium — 2 independent features in one task, both well-scoped
