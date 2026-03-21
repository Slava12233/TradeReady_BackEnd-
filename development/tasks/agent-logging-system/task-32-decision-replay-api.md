---
task_id: 32
title: "Build decision replay and analysis API endpoints"
type: task
agent: "backend-developer"
phase: 5
depends_on: [21, 22, 25]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "high"
files: ["src/api/routes/agents.py", "src/api/schemas/agents.py"]
tags:
  - task
  - agent
  - logging
---

# Task 32: Decision Replay and Analysis API Endpoints

## Assigned Agent: `backend-developer`

## Objective
Add 2 new API endpoints for querying and analyzing agent decisions with full trace correlation.

## Endpoints to Create

### `GET /api/v1/agents/{agent_id}/decisions/trace/{trace_id}`
Returns the full decision chain for a trace:
- Strategy signals (`agent_strategy_signals` WHERE trace_id)
- Decision record (`agent_decisions` WHERE trace_id)
- API calls made (`agent_api_calls` WHERE trace_id)
- Order result (join `orders` via `agent_decisions.order_id`)
- Trade outcome (join `trades` via order)

Response shape:
```json
{
    "trace_id": "abc123...",
    "signals": [...],
    "decision": {...},
    "api_calls": [...],
    "order": {...},
    "trade": {...},
    "pnl": "12.50"
}
```

### `GET /api/v1/agents/{agent_id}/decisions/analyze`
Query params: `start`, `end`, `min_confidence`, `direction`, `pnl_outcome` (positive/negative/all)

Returns filtered decisions with aggregated stats:
```json
{
    "total": 150,
    "wins": 90,
    "losses": 60,
    "win_rate": 0.60,
    "avg_pnl": "5.23",
    "avg_confidence": 0.72,
    "by_direction": {"buy": {...}, "sell": {...}},
    "decisions": [...]
}
```

## Files to Modify
- `src/api/routes/agents.py` — add 2 route handlers
- `src/api/schemas/agents.py` — add response schemas

## Acceptance Criteria
- [ ] Both endpoints return correct data
- [ ] Trace endpoint joins all 4 tables correctly
- [ ] Analysis endpoint supports all query filters
- [ ] Response schemas validated by Pydantic v2
- [ ] Endpoints require authentication (agent owner only)
- [ ] `ruff check` passes

## Agent Instructions
- Read `src/api/routes/CLAUDE.md` for route patterns
- Read `src/api/schemas/CLAUDE.md` for schema patterns
- Use the existing `AgentDecisionRepository` for decision queries
- Add new query methods to repos if needed (e.g., multi-table join)
- Ensure agent ownership check (agent must belong to authenticated account)

## Estimated Complexity
High — multi-table joins, complex query filters, new schemas
