---
task_id: 18
title: "Veto logic & position sizing"
type: task
agent: "ml-engineer"
phase: D
depends_on: [17]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "medium"
files: ["agent/strategies/risk/veto.py", "agent/strategies/risk/sizing.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 18: Veto logic & position sizing

## Assigned Agent: `ml-engineer`

## Objective
Build the veto pipeline and dynamic position sizing that adjusts trade sizes based on volatility and portfolio state.

## Files to Create
- `agent/strategies/risk/veto.py`:
  - `VetoPipeline` class:
    - `evaluate(signal: TradeSignal, risk_assessment: RiskAssessment)` → `VetoDecision`:
      - `action`: "APPROVED" | "RESIZED" | "VETOED"
      - `original_size_pct`: float
      - `adjusted_size_pct`: float (if resized)
      - `reason`: str
    - Pipeline checks (in order):
      1. If risk verdict == "HALT" → VETOED
      2. If signal.confidence < 0.5 → VETOED (low conviction)
      3. If adding position exceeds max_portfolio_exposure → RESIZED (cap at remaining capacity)
      4. If position in same sector as 2+ existing → VETOED (correlation)
      5. If recent drawdown > 3% → RESIZED (halve position size)
      6. Otherwise → APPROVED

- `agent/strategies/risk/sizing.py`:
  - `DynamicSizer` class:
    - `calculate_size(base_size_pct, atr, avg_atr, drawdown_pct)` → adjusted_size_pct:
      - Volatility adjustment: `size *= avg_atr / atr` (smaller in high vol, larger in low vol)
      - Drawdown adjustment: `size *= (1 - drawdown_pct * 2)` (reduce as drawdown grows)
      - Clamp to [0.01, max_single_position]

## Acceptance Criteria
- [ ] Veto pipeline runs all 6 checks in order, short-circuits on first VETOED
- [ ] RESIZED gives correct remaining capacity (not negative)
- [ ] Dynamic sizing reduces in high volatility and drawdown periods
- [ ] All sizes clamped within bounds (no zero or negative sizes)
- [ ] VetoDecision includes clear reason string for debugging

## Dependencies
- Task 17: RiskAgent and RiskAssessment models

## Agent Instructions
The veto pipeline is a chain-of-responsibility pattern. Each check either passes or terminates with VETOED/RESIZED. The dynamic sizer is used when a trade is APPROVED to fine-tune the final size.

## Estimated Complexity
Low-Medium — straightforward business logic.
