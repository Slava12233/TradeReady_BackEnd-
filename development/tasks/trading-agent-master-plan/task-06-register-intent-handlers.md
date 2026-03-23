---
task_id: 06
title: "Register IntentRouter handlers in AgentServer"
type: task
agent: "backend-developer"
phase: 0
depends_on: []
status: "completed"
priority: "medium"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/server.py", "agent/conversation/router.py"]
tags:
  - task
  - integration
  - foundation
---

# Task 06: Register IntentRouter handlers

## Assigned Agent: `backend-developer`

## Objective
Wire real handler functions into the `IntentRouter` so that slash commands and intent-classified messages route to actual functionality instead of returning stubs.

## Context
`IntentRouter` classifies user messages into 8 intent types (TRADE, ANALYZE, PORTFOLIO, JOURNAL, LEARN, PERMISSIONS, STATUS, GENERAL) but all handlers return placeholder strings like `"[TRADE handler not registered]"`. The `AgentServer.process_message()` calls `_reasoning_loop()` directly, bypassing routing.

## Steps
1. Create handler functions for each intent type that call appropriate SDK/agent tools
2. Register handlers in `AgentServer.__init__()` via `router.register(IntentType.X, handler)`
3. Update `process_message()` to route through `IntentRouter` first, fall back to `_reasoning_loop()` for GENERAL intent

## Acceptance Criteria
- [ ] `/trade`, `/portfolio`, `/status`, `/analyze` commands produce real output
- [ ] TRADE intent routes to `TradingLoop` or `SignalGenerator`
- [ ] PORTFOLIO intent calls `sdk_client.get_balance()` + `get_positions()`
- [ ] STATUS intent returns agent health + position summary
- [ ] GENERAL intent falls through to LLM reasoning loop
- [ ] Tests for each handler

## Estimated Complexity
Medium — implement 8 handler functions with SDK integration.
