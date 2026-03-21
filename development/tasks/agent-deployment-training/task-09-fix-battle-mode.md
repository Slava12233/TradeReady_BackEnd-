---
task_id: 09
title: "Fix battle historical mode (if broken)"
type: task
agent: "backend-developer"
phase: 5
depends_on: [8]
status: "skipped"
board: "[[agent-deployment-training/README]]"
priority: "high"
files: ["src/battles/"]
tags:
  - task
  - deployment
  - training
---

# Task 09: Fix battle historical mode (if broken)

## Assigned Agent: `backend-developer`

## Objective
If Task 08 finds the battle historical mode bug is still present, fix it. If already fixed, mark this task as "skipped".

## Context
The evolutionary training strategy uses `BattleRunner.run_battle()` which creates historical battles, adds participants, starts them, and steps through them. If battle creation fails with a 500 error, the entire evolutionary pipeline is blocked.

## Acceptance Criteria
- [ ] `POST /api/v1/battles` with `{"mode": "historical"}` returns 201
- [ ] Historical battle can be started and stepped
- [ ] `BattleRunner` smoke test passes (3 gen, 4 agents)
- [ ] Existing battle tests still pass

## Dependencies
- Task 08: investigation findings

## Agent Instructions
Read Task 08's findings first. Follow the fix recommended there. After fixing, run `pytest tests/unit/test_battle*.py tests/integration/test_battle*.py -v` to verify no regressions.

## Estimated Complexity
Medium — depends on root cause complexity from Task 08.
