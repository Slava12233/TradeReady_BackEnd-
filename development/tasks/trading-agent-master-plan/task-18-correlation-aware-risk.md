---
task_id: 18
title: "Implement correlation-aware portfolio construction"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["agent/strategies/risk/middleware.py"]
tags:
  - task
  - risk
  - portfolio
---

# Task 18: Correlation-aware portfolio construction

## Assigned Agent: `backend-developer`

## Objective
Add a correlation check gate to `RiskMiddleware` that reduces position sizes when the proposed trade is highly correlated with existing positions.

## Implementation
1. Before executing a new trade, fetch candle data for the proposed asset and each existing position
2. Compute rolling 20-period Pearson correlation
3. If correlation > 0.7 with any existing position: `size *= (1 - correlation)`
4. Cap total correlated exposure at 2x single position risk budget

## Files to Modify
- `agent/strategies/risk/middleware.py` — add `_check_correlation()` method, insert as gate in pipeline

## Acceptance Criteria
- [ ] `_check_correlation()` computes rolling correlation using candle returns
- [ ] Position size reduced proportionally to correlation
- [ ] Total correlated exposure capped
- [ ] BTC+ETH (typically r>0.8) triggers size reduction
- [ ] Tests with synthetic correlated price series

## Estimated Complexity
Medium — correlation calculation + integration into existing pipeline.
