---
task_id: 8
title: "Add get_indicators() to SDK clients"
type: task
agent: "backend-developer"
phase: 1
depends_on: [7]
status: "done"
priority: "medium"
board: "[[platform-endgame-readiness/README]]"
files:
  - "sdk/agentexchange/client.py"
  - "sdk/agentexchange/async_client.py"
tags:
  - task
  - sdk
  - indicators
  - phase-1
---

# Task 08: Add get_indicators() to SDK clients

## Assigned Agent: `backend-developer`

## Objective
Add `get_indicators()` methods to both SDK clients for the new indicators API.

## Context
Task 07 creates the indicators API endpoints. This task adds SDK convenience methods.

## Files to Modify/Create
- `sdk/agentexchange/client.py` — Add `get_indicators(symbol, indicators=None, lookback=200)` method
- `sdk/agentexchange/async_client.py` — Add async `get_indicators()` method

## Acceptance Criteria
- [x] `client.get_indicators("BTCUSDT")` returns all indicators
- [x] `client.get_indicators("BTCUSDT", indicators=["rsi_14", "macd_hist"])` returns filtered
- [x] `lookback` param passed as query parameter
- [x] Async client has matching method
- [x] `ruff check` passes

## Dependencies
- **Task 07** must complete first

## Agent Instructions
1. Read `sdk/CLAUDE.md` for client patterns
2. Follow existing GET method patterns in the SDK (query params, response parsing)

## Estimated Complexity
Low — straightforward SDK method following existing patterns.
