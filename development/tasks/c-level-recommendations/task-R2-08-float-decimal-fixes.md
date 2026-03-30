---
task_id: R2-08
title: "Fix remaining float(Decimal) casts in agent handlers"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "medium"
board: "[[c-level-recommendations/README]]"
files: ["agent/server_handlers.py", "agent/trading/ab_testing.py", "agent/trading/journal.py", "agent/strategies/ensemble/attribution.py", "agent/strategies/rl/deploy.py", "agent/strategies/risk/middleware.py"]
tags:
  - task
  - code-quality
  - financial-precision
---

# Task R2-08: Fix Remaining `float(Decimal)` Casts in Agent

## Assigned Agent: `backend-developer`

## Objective
Replace all `float(Decimal(...))` casts on monetary/financial values with proper `Decimal` arithmetic. Document exceptions for numpy/RL interop.

## Context
Project convention: `Decimal` required for ALL money/price/balance values — never `float`. The code-reviewer agent has flagged multiple violations across the agent package.

## Files to Modify/Create
- `agent/server_handlers.py:210` — `float(c.close)` for SMA calculation
- `agent/trading/ab_testing.py:921` — `float(r.outcome_pnl)`
- `agent/trading/journal.py:844` — `float(r.outcome_pnl)`
- `agent/strategies/ensemble/attribution.py:309` — `float(row.pnl_sum)`
- `agent/strategies/rl/deploy.py:235,397,617,625,856` — `float(prices.get(...))`
- `agent/strategies/risk/middleware.py:745` — `float(max(Decimal(...)))`

## Acceptance Criteria
- [x] No `float()` calls on financial values except documented RL/numpy exceptions
- [x] RL/numpy exceptions have inline comment: `# float() required for numpy/SB3 interop`
- [x] `Decimal` arithmetic produces identical results
- [x] All existing tests pass after changes

## Dependencies
None — pure code fix

## Agent Instructions
1. For each file, replace `float(x)` with `Decimal(str(x))` for financial values
2. For RL deploy.py: `float()` is required for numpy arrays — add documenting comment
3. Run affected tests after each file change
4. Use `Decimal` division: `sum(closes) / Decimal(str(len(closes)))`

## Estimated Complexity
Medium — 6 files, mechanical but must verify each context
