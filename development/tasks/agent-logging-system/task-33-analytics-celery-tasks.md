---
task_id: 33
title: "Build analytics Celery tasks (attribution, memory effectiveness, platform health)"
type: task
agent: "backend-developer"
phase: 5
depends_on: [22, 25]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["src/tasks/agent_analytics.py"]
tags:
  - task
  - agent
  - logging
---

# Task 33: Build Analytics Celery Tasks

## Assigned Agent: `backend-developer`

## Objective
Create 3 new Celery tasks that analyze logging data to produce actionable insights.

## Files to Create
- `src/tasks/agent_analytics.py` — 3 Celery tasks

## Tasks to Implement

### `agent_strategy_attribution` (daily)
For each agent:
1. Query `agent_strategy_signals` for last 24h
2. Join with `agent_decisions` on `trace_id`
3. Join with `trades` on `order_id` (from decision)
4. Calculate per-strategy contribution: count, avg_confidence, total_pnl, win_rate
5. Store in `agent_performance` with `period="attribution"`

### `agent_memory_effectiveness` (weekly)
For each agent:
1. Query decisions that have associated memory context (from context builder logs)
2. Split into memory-assisted vs non-memory decisions
3. Compare win rates, avg PnL
4. Find most-reinforced memories and correlate with outcomes
5. Write findings to `agent_journal` as `entry_type="insight"`

### `agent_platform_health_report` (daily)
Aggregates `agent_api_calls`:
1. Calculate p50/p95/p99 latency per endpoint
2. Error rate per endpoint
3. Availability per endpoint
4. Compare to previous day (regression detection)
5. Auto-create `agent_feedback` for degraded endpoints (>2x p95 increase)

## Celery Beat Registration
Add all 3 tasks to the beat schedule in `src/tasks/celery_app.py`:
- `agent_strategy_attribution`: daily at 02:00 UTC
- `agent_memory_effectiveness`: weekly Sunday at 03:00 UTC
- `agent_platform_health_report`: daily at 06:00 UTC

## Acceptance Criteria
- [ ] All 3 tasks implemented with per-agent isolation (catch exceptions per agent)
- [ ] Attribution produces correct per-strategy PnL breakdown
- [ ] Memory effectiveness compares memory vs non-memory decisions
- [ ] Platform health auto-creates feedback for regressions
- [ ] Tasks registered in Celery beat schedule
- [ ] `ruff check src/tasks/agent_analytics.py` passes

## Agent Instructions
- Follow existing Celery task patterns in `src/tasks/` and `agent/tasks.py`
- Use `asyncio.run()` to bridge Celery sync → async
- Per-agent isolation: `for agent_id in agent_ids: try/except`
- Use structlog for task logging (not stdlib logging)
- The `agent_performance` table already has a flexible JSONB `stats` column

## Estimated Complexity
High — 3 complex analytical queries with multi-table joins
