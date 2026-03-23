---
task_id: 17
title: "Implement configurable drawdown profiles per agent"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/risk/risk_agent.py", "agent/strategies/risk/veto.py"]
tags:
  - task
  - risk
---

# Task 17: Configurable drawdown profiles

## Assigned Agent: `backend-developer`

## Objective
Replace the binary drawdown response with per-agent configurable `DrawdownProfile` that maps drawdown ranges to position size multipliers.

## Profiles
- **Aggressive** (Momentum, Evolved): 0-15% full → 15-25% 0.75x → 25-40% 0.5x → >40% 0.25x
- **Moderate** (Balanced, Regime): 0-10% full → 10-20% 0.75x → 20-30% 0.5x → >30% 0.25x
- **Conservative**: 0-5% full → 5-10% 0.5x → >10% 0.25x

## Files to Modify
- `agent/strategies/risk/risk_agent.py` — add `DrawdownProfile` dataclass, modify `assess()` to return `scale_factor`
- `agent/strategies/risk/veto.py` — accept and propagate `scale_factor`

## Acceptance Criteria
- [ ] `DrawdownProfile` dataclass with configurable thresholds and multipliers
- [ ] `RiskAssessment` includes `scale_factor: float` field
- [ ] 3 preset profiles: AGGRESSIVE, MODERATE, CONSERVATIVE
- [ ] Each agent can be assigned a different profile
- [ ] Tests for each profile at boundary conditions

## Estimated Complexity
Medium — extend existing risk assessment with new data model.
