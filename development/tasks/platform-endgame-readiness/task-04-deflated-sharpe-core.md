---
task_id: 4
title: "Implement Deflated Sharpe Ratio service + API endpoint"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[platform-endgame-readiness/README]]"
files:
  - "src/metrics/deflated_sharpe.py"
  - "src/api/routes/metrics.py"
  - "src/api/schemas/metrics.py"
  - "src/main.py"
tags:
  - task
  - metrics
  - statistics
  - phase-1
---

# Task 04: Implement Deflated Sharpe Ratio service + API endpoint

## Assigned Agent: `backend-developer`

## Objective
Implement the Bailey & Lopez de Prado (2014) Deflated Sharpe Ratio as a standalone service module and REST endpoint.

## Context
When agents test thousands of strategy variants, they'll find strategies that look profitable by chance. The DSR corrects for multiple testing bias. Must be pure Python (no scipy dependency) using Abramowitz & Stegun rational approximation for normal CDF.

## Files to Modify/Create
- `src/metrics/deflated_sharpe.py` — Create: `DeflatedSharpeResult` dataclass, `compute_deflated_sharpe()` function, pure-Python `_normal_cdf()` helper
- `src/api/routes/metrics.py` — Create: `POST /api/v1/metrics/deflated-sharpe` endpoint
- `src/api/schemas/metrics.py` — Create: `DeflatedSharpeRequest` + `DeflatedSharpeResponse` Pydantic v2 schemas
- `src/main.py` — Register metrics router

## Acceptance Criteria
- [ ] `compute_deflated_sharpe(returns, num_trials, annualization_factor)` returns `DeflatedSharpeResult`
- [ ] Result includes: observed_sharpe, expected_max_sharpe, deflated_sharpe, p_value, is_significant, num_trials, num_returns, skewness, kurtosis
- [ ] Pure-Python normal CDF (no scipy) — Abramowitz & Stegun, accurate to 7.5e-8
- [ ] `is_significant` is True when `p_value > 0.95` (95% confidence)
- [ ] API endpoint accepts `{ returns, num_trials, annualization_factor }` body
- [ ] API endpoint validates: `len(returns) >= 10`, `num_trials >= 1`
- [ ] Router registered in `src/main.py`
- [ ] `ruff check` and `mypy` pass

## Dependencies
None — this is a Phase 1 task with no prerequisites.

## Agent Instructions
1. Read `src/metrics/CLAUDE.md` for metrics calculator patterns
2. Read `src/api/routes/CLAUDE.md` for route conventions
3. The math (Bailey & Lopez de Prado 2014):
   - E[max(SR)] ≈ √(2·ln(N)) · (1 - γ_euler/(2·ln(N))) + γ_euler/√(2·ln(N))
   - Var(SR_hat) = (1/T) · (1 - γ·SR + ((κ-1)/4)·SR²)
   - DSR = (SR_observed - E[max(SR)]) / √(Var(SR_hat))
   - p_value = Φ(DSR) via standard normal CDF
4. Use `Decimal` for financial computations where appropriate, but `float` is acceptable for statistical math (returns, sharpe ratios)
5. γ_euler ≈ 0.5772156649 (Euler-Mascheroni constant)
6. Default `annualization_factor=252` (daily returns)

## Estimated Complexity
Medium — the math is well-defined; main complexity is implementing a precise normal CDF without scipy.
