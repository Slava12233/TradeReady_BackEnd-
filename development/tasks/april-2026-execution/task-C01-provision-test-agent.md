---
task_id: C-01
title: "Provision test agent"
type: task
agent: "e2e-tester"
track: C
depends_on: ["A-06"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["scripts/e2e_provision_agents.py"]
tags:
  - task
  - e2e
  - agent
  - trading
---

# Task C-01: Provision test agent

## Assigned Agent: `e2e-tester`

## Objective
Create a test trading agent with a conservative risk profile for end-to-end trade loop testing.

## Context
Track C validates the entire trading pipeline. We need a real agent in the database with proper account, balance, and risk configuration.

## Files to Use
- `scripts/e2e_provision_agents.py` — provisions 5 agents with distinct risk profiles

## Acceptance Criteria
- [ ] At least 1 agent created in the database
- [ ] Agent has an associated account with starting balance
- [ ] Agent has a conservative risk profile (low position size, tight stop-loss)
- [ ] Agent API key is generated and accessible
- [ ] Agent appears in the API: `GET /api/v1/agents`

## Dependencies
- **A-06**: Historical data validated (needed for the agent's trading environment)

## Agent Instructions
Run `python scripts/e2e_provision_agents.py` or create a single agent via the API:
```bash
curl -X POST http://localhost:8000/api/v1/agents \
  -H "Content-Type: application/json" \
  -d '{"name": "e2e-test-agent", "description": "Conservative test agent for e2e validation"}'
```
Record the agent ID and API key for subsequent tasks. Use conservative settings — this agent will execute real (simulated) trades.

## Estimated Complexity
Low — running existing provisioning script.
