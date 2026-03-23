---
task_id: 03
title: "Provision 5 trading agent accounts with different risk profiles"
type: task
agent: "e2e-tester"
phase: 0
depends_on: [1]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/.env"]
tags:
  - task
  - agents
  - foundation
---

# Task 03: Provision 5 trading agent accounts

## Assigned Agent: `e2e-tester`

## Objective
Create one account and 5 trading agents with different risk profiles for the multi-agent battle system. Configure `agent/.env` with the primary agent's credentials.

## Agent Profiles

| Agent | Name | Risk Profile |
|-------|------|-------------|
| 1 | Momentum | `max_position_pct=0.10`, `daily_loss_limit_pct=0.30` |
| 2 | Balanced | `max_position_pct=0.05`, `daily_loss_limit_pct=0.15` |
| 3 | Evolved | `max_position_pct=0.10`, `daily_loss_limit_pct=0.25` |
| 4 | Regime-Adaptive | `max_position_pct=0.08`, `daily_loss_limit_pct=0.20` |
| 5 | Conservative | `max_position_pct=0.03`, `daily_loss_limit_pct=0.10` |

## Steps
1. `POST /api/v1/auth/register` — create main account
2. `POST /api/v1/auth/login` — get JWT
3. `POST /api/v1/agents` ×5 — create each agent with name and starting_balance=10000
4. `PUT /api/v1/agents/{id}/risk-profile` ×5 — set risk profiles
5. Save Agent 1 (Momentum) credentials to `agent/.env`
6. Run `python -m agent.main smoke` to verify connectivity

## Acceptance Criteria
- [ ] 5 agents created with unique API keys
- [ ] Each agent has correct risk profile
- [ ] `agent/.env` configured with primary agent credentials
- [ ] Smoke test passes all 10 steps
- [ ] All agent credentials documented (stored securely, not committed)

## Estimated Complexity
Medium — involves multiple API calls with JWT auth flow.
