---
type: code-review
date: 2026-03-23
reviewer: code-reviewer
verdict: PASS WITH WARNINGS
scope: float-decimal-audit
tags:
  - review
  - agent
  - code-quality
  - decimal
  - audit
---

# Code Review Report

- **Date:** 2026-03-23 17:36
- **Reviewer:** code-reviewer agent
- **Verdict:** PASS WITH WARNINGS
- **Task:** R4-02 — Audit all `float(Decimal)` casts across `agent/` package

## Files Reviewed

Entire `agent/` package searched with:
- `grep -rn "float(.*Decimal" agent/ --include="*.py"`
- `grep -rn "float(" agent/ --include="*.py"` (filtered for financial attribute names)

Key files individually inspected:
- `agent/permissions/budget.py`
- `agent/strategies/rl/deploy.py`
- `agent/tools/agent_tools.py`
- `agent/trading/journal.py`
- `agent/trading/ab_testing.py`
- `agent/trading/loop.py`
- `agent/server_handlers.py`
- `agent/strategies/retrain.py`
- `agent/strategies/risk/sizing.py`
- `agent/strategies/risk/risk_agent.py`
- `agent/strategies/risk/veto.py`
- `agent/strategies/ensemble/attribution.py`
- `agent/strategies/regime/labeler.py`
- `agent/strategies/evolutionary/analyze.py`, `battle_runner.py`, `evolve.py`
- `agent/strategies/rl/evaluate.py`, `runner.py`

## CLAUDE.md Files Consulted

- `CLAUDE.md` (root)
- `agent/CLAUDE.md`
- `agent/strategies/CLAUDE.md`
- `agent/strategies/rl/CLAUDE.md`
- `agent/permissions/CLAUDE.md`
- `agent/tools/CLAUDE.md`
- `agent/trading/CLAUDE.md`
- `.claude/agent-memory/code-reviewer/MEMORY.md`

## Critical Issues

None.

No `float()` cast was found on a value that flows into:
- Redis `INCRBYFLOAT` budget counters (those correctly use `str(Decimal(...))`)
- DB monetary column writes
- Order engine quantity or price calculations
- Budget enforcement decision logic

The previously identified CRITICAL-1 security finding (float precision drift in INCRBYFLOAT) has been correctly remediated. The `pipe.incrbyfloat()` calls in `budget.py` lines 887 and 974 pass pre-converted strings.

## Warnings (should fix)

### W-1: 12 undocumented RL/numpy interop float casts in `deploy.py`

The convention established in `agent/strategies/rl/deploy.py` is to annotate every `float()` cast that converts a `Decimal` for numpy/SB3 use with the comment `# float() required for numpy/SB3 interop`. Three lines correctly carry this comment (lines 235, 397, 858). However, twelve additional lines in the same file and same context are missing the comment:

- **File:** `agent/strategies/rl/deploy.py`
- **Lines:** 219, 222, 300, 304, 307, 314, 341, 342, 379, 605, 606, 618, 626, 627, 823, 825

These casts are functionally correct (they feed numpy observation arrays and weight-to-order arithmetic, not enforcement paths), but without the comment a future reviewer cannot distinguish them from an accidental monetary-float violation.

**Fix:** Add `# float() required for numpy/SB3 interop` to each of these lines. Example:

```python
# Before (line 219):
equity_f = float(equity) if equity > 0 else 1.0

# After:
equity_f = float(equity) if equity > 0 else 1.0  # float() required for numpy/SB3 interop
```

## Suggestions (consider)

### S-1: Consolidate RL float conversion into a helper

With 15+ float cast sites in `deploy.py`, a small helper function would reduce annotation noise and make the intent explicit:

```python
def _to_f(d: Decimal) -> float:
    """Convert Decimal to float for numpy/SB3 observation array construction."""
    return float(d)
```

This is optional — the inline comments are sufficient.

### S-2: `journal.py` line 1182 round-trip is redundant

```python
mem_confidence = Decimal(str(round(float(confidence), 4))) if confidence else Decimal("0.8000")
```

`confidence` is already a float (it comes from `TradingSignal.confidence: float`). The `float()` call is a no-op. The round-trip can be simplified to:

```python
mem_confidence = Decimal(str(round(confidence, 4))) if confidence else Decimal("0.8000")
```

Not a violation, but slightly cleaner.

## Passed Checks

- **CRITICAL-1 remediation verified:** `pipe.incrbyfloat()` in `budget.py` uses `str(Decimal(...))` strings — no float precision drift into Redis budget counters.
- **Prometheus gauge casts:** `budget.py` lines 750, 754 cast ratio to float for `prometheus_client` gauge `.set()` — legitimate, display-only, not stored.
- **Statistical library interop:** All `float()` casts feeding `scipy`, `numpy`, and `statistics` functions (Sharpe, t-test, drawdown, std) are appropriate — these are unitless mathematical computations, not monetary values.
- **Sizing return types:** `sizing.py` returns position size as `float` fraction (a dimensionless ratio in [0.0, 1.0]) — correct type for a size percentage.
- **f-string display casts:** All `float()` calls in f-string log messages and console display (server_handlers, veto, middleware, risk_agent) are display-only with no storage side effects.
- **Evolutionary fitness casts:** Fitness scores (ROI%, Sharpe, drawdown) are inherently unitless and correctly handled in float domain.
- **Regime labeler numpy arrays:** Candle OHLCV data coming from REST API responses (already untyped dicts) is correctly cast to float64 for numpy array construction.
- **AB testing statistical test:** `ab_testing.py` converts `Decimal` PnL list to float list for Welch t-test — the test operates on relative performance, not monetary storage.
- **RL evaluate/runner:** Equity curve and SB3 reward values are all in the float domain for ML metric computation — correct.
- **Dependency direction:** No upward imports detected in audited files.
- **No bare `float(Decimal(...))` in security-sensitive paths:** All budget enforcement, order sizing decisions, and balance reads use `Decimal` or `str` throughout.

## Scope of Remaining Risk

After this audit the remaining risk from float casts is limited to the 12 undocumented lines in `deploy.py` (W-1), which are documentation gaps rather than functional precision risks. No undocumented float casts were found on values flowing into any of the four precision-critical paths: Redis budget counters, DB monetary writes, order engine inputs, or risk enforcement thresholds.
