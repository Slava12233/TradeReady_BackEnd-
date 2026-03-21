---
task_id: 12
title: "Instrument agent tools (direct DB) with logging"
type: task
agent: "backend-developer"
phase: 2
depends_on: [9]
status: "pending"
board: "[[agent-logging-system/README]]"
priority: "medium"
files: ["agent/tools/agent_tools.py"]
tags:
  - task
  - agent
  - logging
---

# Task 12: Instrument Agent Tools (Direct DB)

## Assigned Agent: `backend-developer`

## Objective
Wrap all 5 direct-DB agent tools with `log_api_call("db", ...)`.

## Files to Modify
- `agent/tools/agent_tools.py` — add logging to all 5 tools

## The 5 Tools
1. `reflect_on_trade(trade_id)` — reads trades + observations, writes journal + learnings
2. `review_portfolio()` — reads balances + positions + budget, writes journal
3. `scan_opportunities(criteria)` — reads prices from Redis, returns only
4. `journal_entry(content, entry_type)` — reads prices + portfolio, writes journal
5. `request_platform_feature(description, category)` — reads/writes agent_feedback

## Acceptance Criteria
- [ ] All 5 tools wrapped with `log_api_call("db", tool_name)`
- [ ] DB read vs write operations distinguished in extra context
- [ ] `ruff check agent/tools/agent_tools.py` passes

## Estimated Complexity
Low — 5 instances, same pattern
