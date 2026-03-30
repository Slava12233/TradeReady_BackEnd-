---
task_id: R1-08
title: "Provision 5 agent accounts"
type: task
agent: "e2e-tester"
phase: 1
depends_on: ["R1-04"]
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["scripts/e2e_provision_agents.py", "agent/.env"]
tags:
  - task
  - infrastructure
  - agents
---

# Task R1-08: Provision Agent Accounts

## Assigned Agent: `e2e-tester`

## Objective
Create 5 trading agents with individual wallets, API keys, and risk profiles. Configure `agent/.env` with credentials.

## Context
The agent trading system requires provisioned agents in the database before any trading can occur. The provisioning script creates accounts and agents, returning API keys for the `agent/.env` configuration.

## Files to Modify/Create
- `scripts/e2e_provision_agents.py` (execute only)
- `agent/.env` (new, from `agent/.env.example`) — populate with returned API keys

## Acceptance Criteria
- [x] 5 agents exist in the `agents` database table
- [x] Each agent has unique API key (`ak_live_...`)
- [x] Each agent has starting balance of 10,000 USDT
- [x] `agent/.env` populated with valid `PLATFORM_API_KEY` and `PLATFORM_API_SECRET`
- [x] `agent/.env` has `OPENROUTER_API_KEY` configured

## Dependencies
- R1-04 (exchange pairs must be seeded)

## Agent Instructions
1. Copy `agent/.env.example` to `agent/.env`
2. Run `python scripts/e2e_provision_agents.py`
3. Update `agent/.env` with the returned credentials
4. Verify agents via API: `curl http://localhost:8000/api/v1/agents`

## Estimated Complexity
Medium — script execution + credential wiring

## Completion Notes (2026-03-23)

Agents were already provisioned in a prior run (Task 03 on 2026-03-22). All 5 agents verified active:

| Agent | ID | Status |
|-------|----|--------|
| Momentum | 68aeab2c-419b-4101-9325-ed2d411d841a | active |
| Balanced | 2950f684-0ed9-4db9-95ca-04441ec3cc8a | active |
| Evolved | 507e6b1f-0c6c-4440-a76b-a84f2ac7fef3 | active |
| Regime-Adaptive | 828adc57-a7d6-44ec-a181-3f74050e7e08 | active |
| Conservative | dae70ce7-3a30-4d8d-8402-eb17b2f15070 | active |

`agent/.env` confirmed populated with Momentum API key (`ak_live_q_aN...`), secret, base URL, and OpenRouter key.
