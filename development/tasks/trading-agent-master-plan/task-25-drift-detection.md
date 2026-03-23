---
task_id: 25
title: "Implement concept drift detection"
type: task
agent: "backend-developer"
phase: 3
depends_on: [14]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/drift.py", "agent/trading/loop.py"]
tags:
  - task
  - ml
  - drift
  - intelligence
---

# Task 25: Concept drift detection

## Assigned Agent: `backend-developer`

## Objective
Create `DriftDetector` class that monitors strategy performance and detects statistically significant degradation using Page-Hinkley test.

## Implementation
1. Track rolling window of per-strategy Sharpe, win rate, avg PnL
2. Page-Hinkley test: accumulate `sum += (x - mean - delta)`, detect when `sum - min_sum > threshold`
3. When drift detected:
   - Emit `REGIME_DRIFT_DETECTED` structlog event
   - Set `drift_active = True` flag
   - Auto-reduce position sizes by 50%
   - Increase REGIME strategy weight

## Files to Create/Modify
- `agent/strategies/drift.py` — new `DriftDetector` class
- `agent/trading/loop.py` — wire drift detector into observe-learn cycle

## Acceptance Criteria
- [ ] `DriftDetector` implements Page-Hinkley test
- [ ] Drift detection triggers logging + size reduction
- [ ] Recovery from drift when performance normalizes
- [ ] Configurable sensitivity parameters (delta, threshold)
- [ ] Tests with synthetic performance degradation

## Estimated Complexity
Medium — statistical test implementation + integration.
