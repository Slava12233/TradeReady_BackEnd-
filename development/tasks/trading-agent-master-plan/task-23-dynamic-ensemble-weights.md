---
task_id: 23
title: "Implement dynamic ensemble weights with regime-conditional modifiers"
type: task
agent: "backend-developer"
phase: 3
depends_on: [14, 16]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/ensemble/meta_learner.py", "agent/strategies/ensemble/run.py"]
tags:
  - task
  - ensemble
  - intelligence
---

# Task 23: Dynamic ensemble weights

## Assigned Agent: `backend-developer`

## Objective
Replace static ensemble weights with dynamic weights that adjust based on recent per-source performance and current market regime.

## Implementation
1. Track rolling Sharpe per signal source (RL, EVOLVED, REGIME) over last 50 trades
2. `weight[source] = base_weight * (1 + source_sharpe) / norm_factor`
3. Regime-conditional modifiers:
   - TRENDING: RL +30%, EVOLVED -10%
   - MEAN_REVERTING: EVOLVED +30%, RL -10%
   - HIGH_VOLATILITY: all sizes -50%, REGIME +20%
   - LOW_VOLATILITY: RL +20%

## Files to Modify
- `agent/strategies/ensemble/meta_learner.py` — add `update_weights()`, regime modifiers
- `agent/strategies/ensemble/run.py` — call `update_weights()` after each step

## Acceptance Criteria
- [ ] `MetaLearner.update_weights(recent_outcomes)` method implemented
- [ ] Per-source rolling Sharpe tracked in `deque(maxlen=50)`
- [ ] Regime-conditional modifiers applied when `RegimeType` is known
- [ ] Weights always normalized to sum to 1.0
- [ ] Tests: verify weights shift toward winning strategy

## Estimated Complexity
Medium — extend existing MetaLearner with performance tracking.
