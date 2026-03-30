---
task_id: R3-06
title: "Record baseline performance metrics"
type: task
agent: "ml-engineer"
phase: 3
depends_on: ["R3-04", "R3-05"]
status: "partial"
priority: "medium"
board: "[[c-level-recommendations/README]]"
files: ["agent/reports/regime-baseline.json"]
completed_date: "2026-03-23"
tags:
  - task
  - training
  - ml
  - metrics
---

# Task R3-06: Record Baseline Performance Metrics

## Assigned Agent: `ml-engineer`

## Objective
Document baseline performance metrics from walk-forward validation and backtest comparison as the reference point for measuring future improvement.

## Files to Modify/Create
- `agent/reports/regime-baseline.json` (created 2026-03-23)

## Acceptance Criteria
- [x] JSON report created with timestamp for historical tracking
- [x] Regime detection accuracy captured (99.92%)
- [x] Per-regime F1 scores captured (all > 0.99)
- [x] Feature importances captured
- [x] Training/test split sizes documented
- [ ] Sharpe ratio, max drawdown, win rate, profit factor included (pending R3-04/R3-05)
- [ ] WFE score included (pending R3-04)
- [ ] Metrics compared against targets: Sharpe >= 1.0, max drawdown <= 8%, win rate >= 55%

## Current Report Summary (`agent/reports/regime-baseline.json`)

| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| Overall accuracy | 99.92% | >= 70% | PASS |
| trending F1 | 0.9995 | recall >= 40% | PASS |
| high_volatility F1 | 0.9990 | recall >= 40% | PASS |
| low_volatility F1 | 0.9988 | recall >= 40% | PASS |
| mean_reverting F1 | 0.9985 | recall >= 40% | PASS |
| Sharpe ratio | pending | >= 1.0 | — |
| Max drawdown | pending | <= 8% | — |
| Win rate | pending | >= 55% | — |
| WFE score | pending | >= 0.5 | — |

## Top Feature Importances
| Feature | Importance |
|---------|-----------|
| adx | 69.04% |
| atr_ratio | 21.46% |
| bb_width | 4.85% |
| macd_hist | 2.20% |
| rsi | 1.88% |
| volume_ratio | 0.55% |

## Pending Work
This task is marked **partial**. Full completion requires:
1. **R3-04** — Walk-forward validation to produce WFE score and IS/OOS metric comparison
2. **R3-05** — Backtest comparison: regime-adaptive vs static MACD vs buy-and-hold
3. Update `agent/reports/regime-baseline.json` with trading performance metrics once available

## Dependencies
- R3-04 (walk-forward results) + R3-05 (backtest comparison results)

## Estimated Complexity
Low — documentation/aggregation task
