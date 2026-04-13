---
task_id: C-02
title: "Verify agent SDK connectivity"
type: task
agent: "e2e-tester"
track: C
depends_on: ["C-01"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["sdk/"]
tags:
  - task
  - e2e
  - sdk
  - trading
---

# Task C-02: Verify agent SDK connectivity

## Assigned Agent: `e2e-tester`

## Objective
Use the Python SDK client to authenticate as the test agent, fetch balance, and list available trading pairs.

## Context
The SDK is the bridge between the trading agent and the platform API. Before testing the trading loop, we verify the SDK works correctly.

## Acceptance Criteria
- [ ] SDK client authenticates with the agent's API key
- [ ] `client.get_balance()` returns the agent's current balance
- [ ] `client.get_pairs()` returns available trading pairs (should include BTCUSDT)
- [ ] `client.get_agent()` returns the agent's profile
- [ ] No authentication errors or timeout issues

## Dependencies
- **C-01**: Test agent must be provisioned with a valid API key

## Agent Instructions
Read `sdk/CLAUDE.md` for SDK usage patterns. Test both sync and async clients:
```python
from sdk import TradeReadyClient
client = TradeReadyClient(api_key="<agent_api_key>", base_url="http://localhost:8000")
print(client.get_balance())
print(client.get_pairs())
print(client.get_agent())
```
Record any errors or unexpected responses.

## Estimated Complexity
Low — SDK verification.
