---
task_id: 08
title: "Investigate battle historical mode bug"
agent: "codebase-researcher"
phase: 5
depends_on: [2]
status: "completed"
priority: "high"
files: ["src/battles/historical_engine.py", "src/api/routes/battles.py"]
---

# Task 08: Investigate battle historical mode bug

## Assigned Agent: `codebase-researcher`

## Objective
The development context notes a 500 INTERNAL_ERROR on battle create in historical mode (noted 2026-03-18). Investigate whether this bug still exists and what causes it. This blocks evolutionary training (Phase 8 in the plan).

## Steps
1. Read `src/battles/CLAUDE.md` for battle architecture
2. Read `src/battles/historical_engine.py` for historical mode implementation
3. Read `src/api/routes/battles.py` for the create endpoint
4. Check `git log --oneline src/battles/` for recent fixes
5. Test: try creating a historical battle via the API
6. Document findings: is the bug fixed, what caused it, what's needed

## Acceptance Criteria
- [ ] Root cause identified (or confirmed fixed)
- [ ] Historical battle creation tested via API
- [ ] If broken: specific error and fix documented
- [ ] If fixed: confirmation with successful test
- [ ] Findings written to `development/agent-development/battle-historical-investigation.md`

## Dependencies
- Task 02: platform running

## Agent Instructions
The battle create endpoint is `POST /api/v1/battles` with `{"mode": "historical"}`. It requires JWT auth (not API key). Check if the error is in validation, engine initialization, or data access. The BattleRunner in `agent/strategies/evolutionary/battle_runner.py` depends on this working.

## Estimated Complexity
Medium — debugging requires tracing through multiple layers.
