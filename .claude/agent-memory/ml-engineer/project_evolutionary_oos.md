---
name: evolutionary_oos_fitness_upgrade
description: Task 12 — OOS fitness upgrade for evolutionary GA: conventions, weight rationale, BattleRunner API extension, test patterns
type: project
---

Task 12 completed 2026-03-22. Upgraded the evolutionary fitness system from a simple `sharpe - 0.5 * drawdown` formula to a 5-factor composite with an out-of-sample Sharpe term.

**Key decisions:**

- Default `fitness_fn` changed from `sharpe_minus_drawdown` to `composite`. Legacy values still accepted.
- OOS split ratio default is 0.30 (30% held out). Validated to [0.10, 0.50] range.
- `EvolutionConfig` gained: `oos_split_ratio` field, `is_split` / `in_sample_window` / `oos_window` properties using `timedelta` arithmetic.
- `BattleRunner.get_detailed_metrics()` added — returns `dict[agent_id, dict[metric, float|None]]`. `get_fitness()` now delegates to it internally.
- `compute_composite_fitness()` is a pure function exported from `evolve.py`. Missing metrics fall back to neutral values (never raises).
- `profit_factor` clamped to [0, 5] to prevent single lucky-trade outliers from dominating.
- `ConvergenceDetector` extended with `best_oos_sharpe` tracking (diagnostic only, does not change convergence logic).
- OOS battle failure is non-fatal: `oos_sharpe` falls back to `None` → neutral 0.0 in formula.
- IS and OOS battles reuse the same provisioned agents; `reset_agents()` called between them; strategies not re-assigned.

**Weight rationale (in evolve.py docstring):**
- Sharpe 0.35: dominant risk-adjusted return signal
- Profit factor 0.25: penalises strategies that win rarely on large losses
- Drawdown -0.20: higher drawdown is worse; capped so it doesn't overwhelm Sharpe
- Win rate 0.10: secondary quality signal
- OOS Sharpe 0.10: anti-overfit penalty

**Test file:** `agent/tests/test_evolutionary_fitness.py` — 57 tests.
Classes: `TestCompositeFITNESS` (16), `TestComputeFitnessDispatch` (10), `TestConvergenceDetector` (10), `TestEvolutionConfigOOSSplit` (13), `TestGetDetailedMetrics` (8).

**Why:** Prevent overfitting — strategies tuned to a single IS period perform poorly live. OOS Sharpe term and validation split are standard ML anti-overfit practice applied to GA.

**How to apply:** When writing any evolutionary or GA fitness function in this codebase, always split the evaluation window and include an OOS term. The `EvolutionConfig.in_sample_window` / `oos_window` pattern is the standard way to express this.
