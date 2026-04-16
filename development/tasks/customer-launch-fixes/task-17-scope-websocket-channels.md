---
task_id: 17
title: "Scope WebSocket channels to agents"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["src/api/websocket/manager.py", "src/api/websocket/channels.py"]
tags:
  - task
  - security
  - websocket
  - P1
---

# Task 17: Scope WebSocket channels to agents

## Assigned Agent: `backend-developer`

## Objective
WebSocket channels are not agent-scoped — within the same account, agents can see each other's data. This compromises battle fairness (one agent could spy on another's trades).

## Context
Security audit (SR-06) flagged this as MEDIUM. In battle mode, agents from the same account compete against each other. If WS channels leak cross-agent data, battles are unfair.

## Files to Modify
- `src/api/websocket/manager.py` — Add agent_id scoping to channel subscriptions
- `src/api/websocket/channels.py` — Filter messages by agent_id

## Acceptance Criteria
- [ ] WebSocket connections are scoped to a specific agent_id
- [ ] Agent A's trade updates don't leak to Agent B's WebSocket
- [ ] API key connections automatically scope to the key's agent
- [ ] JWT connections require explicit agent_id in subscription
- [ ] Test: two agents on same account receive only their own data

## Agent Instructions
1. Read `src/api/websocket/CLAUDE.md` for WebSocket patterns
2. Add `agent_id` to the connection/subscription metadata
3. Filter outgoing messages to only include the subscribed agent's data
4. Ensure backward compatibility — old clients that don't send agent_id should still work (default to first agent)

## Estimated Complexity
Medium — WebSocket channel filtering logic
