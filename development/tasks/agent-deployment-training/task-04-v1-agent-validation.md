---
task_id: 04
title: "Run V1 agent full validation (4 workflows)"
type: task
agent: "e2e-tester"
phase: 4
depends_on: [3]
status: "completed"
board: "[[agent-deployment-training/README]]"
priority: "high"
files: []
tags:
  - task
  - deployment
  - training
---

# Task 04: Run V1 agent full validation (4 workflows)

## Assigned Agent: `e2e-tester`

## Objective
Run all 4 V1 agent workflows against the live platform to confirm end-to-end functionality before starting training.

## Steps
1. Smoke test: `python -m agent.main smoke` — 10/10 steps
2. Trading workflow: `python -m agent.main trade` — LLM trade lifecycle
3. Backtest workflow: `python -m agent.main backtest` — MA-crossover backtest
4. Strategy workflow: `python -m agent.main strategy` — create/test/improve cycle
5. Full validation: `python -m agent.main all` — produces `platform-validation-*.json`

## Acceptance Criteria
- [ ] Smoke test: 10/10 steps pass
- [ ] Trading workflow: status "pass" or "partial" (HOLD is acceptable)
- [ ] Backtest workflow: status "pass", backtest session completes
- [ ] Strategy workflow: status "pass", V1→V2 comparison works
- [ ] Full validation report saved to `agent/reports/`

## Dependencies
- Task 03: historical data loaded

## Agent Instructions
Run workflows sequentially. The smoke test needs no LLM (fast). Trading/backtest/strategy need `OPENROUTER_API_KEY` set in `agent/.env`. If a workflow fails, check the error in the JSON report before proceeding.

## Estimated Complexity
Low — running existing CLI commands.
