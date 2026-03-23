---
task_id: 27
title: "Integrate WebSocket for real-time price and order updates"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "medium"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/server.py", "agent/trading/loop.py"]
tags:
  - task
  - websocket
  - performance
---

# Task 27: WebSocket integration

## Assigned Agent: `backend-developer`

## Objective
Replace REST polling for prices and order status with WebSocket streaming using the existing `AgentExchangeWS` SDK client.

## Implementation
1. In `AgentServer.start()`: connect `AgentExchangeWS` alongside REST client
2. Subscribe to `ticker:{symbol}` for active trading pairs
3. Subscribe to `orders` channel for fill notifications
4. Buffer incoming ticks in a local dict; `TradingLoop` reads from buffer instead of polling
5. On order fill event, trigger immediate position check

## Files to Modify
- `agent/server.py` — add WebSocket lifecycle management
- `agent/trading/loop.py` — read prices from WS buffer instead of REST

## Acceptance Criteria
- [ ] WebSocket connection established on agent startup
- [ ] Price data streamed in real-time to local buffer
- [ ] Order fill events trigger immediate processing
- [ ] Graceful fallback to REST polling if WebSocket disconnects
- [ ] Reconnection logic with exponential backoff

## Estimated Complexity
Medium — integrating existing WS client into agent lifecycle.
