---
type: plan
tags:
  - backtesting
  - bugfix
  - sprint
date: 2026-04-06
status: pending
source: "[[reports/tester-report-backtesting]]"
---

# Backtest Bugfix Plan A-Z

**Date:** 2026-04-06
**Source:** `development/reports/tester-report-backtesting.md` (45 tests, 17 bugs)
**Goal:** Fix all 17 bugs across 3 sprints, ordered by severity and dependency.

---

## File Impact Map

| File | Bugs Touched |
|------|-------------|
| `src/api/schemas/backtest.py` | BT-03, BT-06, BT-07, BT-12 |
| `src/api/routes/backtest.py` | BT-04, BT-05, BT-08, BT-09, BT-10, BT-11, BT-13, BT-14, BT-15, BT-16, BT-17 |
| `src/backtesting/engine.py` | BT-01, BT-05, BT-15 |
| `src/backtesting/sandbox.py` | BT-02, BT-17 |
| `src/backtesting/results.py` | BT-04 |
| `src/database/repositories/backtest_repo.py` | BT-10, BT-11 |

---

## Sprint 1 — P0 Critical (Blocks core functionality)

### Fix 1A: BUG-BT-01 — Backtest system breaks after initial use

**Root Cause:** `_persist_results()` in `engine.py` calls `await db.commit()` directly, violating the "repositories flush, routes commit" pattern. This poisons the SQLAlchemy session state. After the first backtest completes via auto-complete inside `step()`, the `db.commit()` inside the engine corrupts session state for subsequent operations. Additionally, orphan detection in `backtest.py` routes also calls `await db.commit()` mid-request.

**Files to change:**
- `src/backtesting/engine.py` — `_persist_results()` (~line 634): Replace `await db.commit()` with `await db.flush()`
- `src/backtesting/engine.py` — `complete()` method: Ensure it uses `flush()` not `commit()`
- `src/api/routes/backtest.py` — Orphan detection blocks (~lines 523-534, 711-721): Move `await db.commit()` to after the route handler logic, or use `flush()` + let the session middleware handle commit
- `src/api/routes/backtest.py` — Add explicit `await db.commit()` at the END of route handlers that mutate state (create, step, cancel, complete) to follow the correct pattern

**Verification:** Create 3+ backtests sequentially — all must reach "completed" status.

---

### Fix 1B: BUG-BT-02 + BT-17 — Stop-loss orders never trigger; stop_price not persisted

**Root Cause (two parts):**

1. **stop_price field missing:** `SandboxOrder` dataclass has only `price` — no `stop_price`. When `_execute_market_order()` creates the filled order copy, it sets `price=None` (line 644), wiping the original trigger price.

2. **Trigger logic may fail:** The trigger check in `check_pending_orders()` uses `order.price` which IS set while the order is pending. But if balance locking/unlocking for sell-side stop-losses encounters issues (e.g., `_lock_balance` allows negative available), the execution can silently fail.

**Files to change:**
- `src/backtesting/sandbox.py`:
  - `SandboxOrder` dataclass (~line 54): Add `stop_price: Decimal | None = None` field
  - `place_order()` (~line 244): For `stop_loss` and `take_profit` types, set `stop_price=price` and keep `price` as the trigger price for matching
  - `check_pending_orders()` (~line 312): Use `order.stop_price or order.price` for trigger comparison
  - `_execute_market_order()` (~line 644): Preserve `stop_price` from original order on the filled copy; set `price` to actual execution price (`ref_price`)
- `src/api/routes/backtest.py` — Order list serialization (~lines 257-272): Add `"stop_price": str(o.stop_price) if o.stop_price else None` to the order dict

**Verification:** Place stop-loss sell 0.02 BTC @ $85,000 → step through Feb 2025 (BTC hit $84,349) → stop-loss must trigger. Order list must show `stop_price` field.

---

## Sprint 2 — P1 High (Correctness & validation)

### Fix 2A: BUG-BT-03 — End date before start date accepted

**Root Cause:** No cross-field validation in `BacktestCreateRequest` schema.

**File:** `src/api/schemas/backtest.py` — `BacktestCreateRequest` class (~line 27)

**Change:** Add Pydantic v2 model validator:
```python
@model_validator(mode="after")
def validate_date_range(self) -> Self:
    if self.end_time <= self.start_time:
        raise ValueError("end_time must be after start_time")
    return self
```

**Defense in depth:** Also add guard in `engine.create_session()` (~line 169).

---

### Fix 2B: BUG-BT-04 — `by_pair` always returns empty array

**Root Cause:** Per-pair stats are computed in `_persist_results()` but never stored. The results route hardcodes `by_pair=[]`.

**Files to change:**
- `src/backtesting/results.py` — `BacktestMetrics.to_dict()` (~line 41): Include `"by_pair"` key with serialized per-pair stats
- `src/backtesting/engine.py` — `_persist_results()` (~line 636): Compute per-pair stats and include in `metrics.to_dict()` before persisting to the `metrics` JSONB column
- `src/api/routes/backtest.py` — `get_backtest_results()` (~line 621): Read `raw_metrics.get("by_pair", [])` instead of hardcoded `[]`

---

### Fix 2C: BUG-BT-05 — Fake agent_id returns INTERNAL_ERROR

**Root Cause:** Invalid `agent_id` UUID causes a PostgreSQL FK violation (`IntegrityError`) on `db.flush()`, caught only by the global exception handler as a generic 500.

**Files to change:**
- `src/backtesting/engine.py` — `create_session()` (~line 149): Before inserting the session row, query the `Agent` table to verify the agent exists. If not found, raise a domain-specific error:
  ```python
  if config.agent_id:
      agent = await db.get(Agent, config.agent_id)
      if not agent:
          raise BacktestNoDataError(f"Agent {config.agent_id} not found")
  ```
- Alternatively, `src/api/routes/backtest.py` — `create_backtest()` (~line 136): Validate agent ownership before calling the engine.

---

### Fix 2D: BUG-BT-06 — Non-standard candle intervals accepted

**Root Cause:** Schema only enforces `ge=60`, no whitelist.

**File:** `src/api/schemas/backtest.py` (~line 33)

**Change:**
```python
candle_interval: Literal[60, 300, 3600, 86400] = 60
```

Or add a validator:
```python
VALID_INTERVALS = {60, 300, 3600, 86400}

@field_validator("candle_interval")
@classmethod
def validate_interval(cls, v: int) -> int:
    if v not in VALID_INTERVALS:
        raise ValueError(f"candle_interval must be one of {sorted(VALID_INTERVALS)}")
    return v
```

---

## Sprint 3 — P2 Medium (Validation gaps & edge cases)

### Fix 3A: BUG-BT-07 — Invalid symbol in pairs silently accepted

**Root Cause:** No per-element validation on `pairs: list[str]`.

**File:** `src/api/schemas/backtest.py` (~line 34)

**Change:** Add a field validator:
```python
@field_validator("pairs")
@classmethod
def validate_pairs(cls, v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    pattern = re.compile(r"^[A-Z]{2,10}USDT$")
    invalid = [p for p in v if not pattern.match(p)]
    if invalid:
        raise ValueError(f"Invalid trading pairs: {invalid}. Must match [A-Z]{{2,10}}USDT")
    return v
```

**Note:** This validates format only. Runtime validation against available pairs happens in the engine via `DataReplayer.get_available_pairs()` — the engine should also warn/error if zero pairs match.

---

### Fix 3B: BUG-BT-08 — Compare silently ignores non-existent session IDs

**Root Cause:** `get_sessions_for_compare()` uses `WHERE id IN (...)` which drops missing IDs silently.

**File:** `src/api/routes/backtest.py` — `compare_backtests()` (~line 771)

**Change:** After fetching sessions, check for missing IDs:
```python
found_ids = {s.id for s in bt_sessions}
missing = [str(sid) for sid in session_ids if sid not in found_ids]
if missing:
    raise BacktestNotFoundError(f"Sessions not found: {', '.join(missing)}")
```

---

### Fix 3C: BUG-BT-09 — Compare accepts single session

**Root Cause:** No minimum length check on parsed session IDs.

**File:** `src/api/routes/backtest.py` — `compare_backtests()` (~line 770)

**Change:**
```python
if len(session_ids) < 2:
    raise InputValidationError(
        field="sessions",
        details={"message": "At least 2 session IDs required for comparison"}
    )
```

---

### Fix 3D: BUG-BT-10 + BT-11 — Best endpoint: invalid metrics + sharpe returns "N/A"

**Root Cause (BT-10):** `getattr(BacktestSession, metric, BacktestSession.roi_pct)` silently falls back for unknown metrics.

**Root Cause (BT-11):** `sharpe_ratio`, `sortino_ratio`, `max_drawdown_pct`, `win_rate`, `profit_factor` are stored inside the `metrics` JSONB column, not as direct ORM columns. `getattr(session, "sharpe_ratio")` returns the default `"N/A"`.

**Files to change:**
- `src/api/routes/backtest.py` — `get_best_backtest()` (~line 819):
  ```python
  VALID_METRICS = {"roi_pct", "sharpe_ratio", "sortino_ratio", "max_drawdown_pct",
                   "win_rate", "profit_factor", "total_trades", "total_pnl"}
  JSONB_METRICS = {"sharpe_ratio", "sortino_ratio", "max_drawdown_pct", "win_rate", "profit_factor"}
  
  if metric not in VALID_METRICS:
      raise InputValidationError(field="metric", details={"valid": sorted(VALID_METRICS)})
  ```
- `src/api/routes/backtest.py` — Value extraction (~line 825):
  ```python
  if metric in JSONB_METRICS:
      value = str(session.metrics.get(metric, "N/A")) if session.metrics else "N/A"
  else:
      value = str(getattr(session, metric, "N/A"))
  ```
- `src/database/repositories/backtest_repo.py` — `get_best_session()` (~line 190): For JSONB metrics, use SQL cast:
  ```python
  from sqlalchemy import func, cast, Numeric
  if metric in JSONB_METRICS:
      sort_expr = cast(BacktestSession.metrics[metric].astext, Numeric)
  else:
      sort_expr = getattr(BacktestSession, metric, BacktestSession.roi_pct)
  ```

---

### Fix 3E: BUG-BT-12 — No upper limit on starting_balance

**Root Cause:** Only `ge=1` enforced.

**File:** `src/api/schemas/backtest.py` (~line 32)

**Change:**
```python
starting_balance: Decimal = Field(ge=Decimal("1"), le=Decimal("10000000"))
```

Cap at $10M — prevents precision issues and unrealistic simulations.

---

## Sprint 4 — P3 Low (Polish & UX)

### Fix 4A: BUG-BT-13 — Cancelled sessions show max_drawdown: 100%, sharpe: 0

**Root Cause:** Compare route defaults to `Decimal("100")` for drawdown and `Decimal("0")` for sharpe when `session.metrics` is None (cancelled sessions).

**File:** `src/api/routes/backtest.py` — `compare_backtests()` (~lines 780-781)

**Change:** Use `None` instead of misleading defaults, and skip cancelled/failed sessions from ranking:
```python
sharpe = Decimal(s.metrics.get("sharpe_ratio", "0")) if s.metrics and s.status == "completed" else None
dd = Decimal(s.metrics.get("max_drawdown_pct", "0")) if s.metrics and s.status == "completed" else None
```

Alternatively, compute partial metrics in `engine.cancel()` before persisting.

---

### Fix 4B: BUG-BT-14 — Failed session shows final_equity: 0

**Root Cause:** Orphan detection sets `status="failed"` but doesn't set `final_equity`. Results route defaults to `"0"`.

**File:** `src/api/routes/backtest.py` — Orphan detection UPDATE statements (~lines 529, 718)

**Change:** Set `final_equity` to the session's `starting_balance`:
```python
.values(status="failed", completed_at=now, final_equity=BacktestSessionModel.starting_balance)
```

Or in the results serialization, fallback to `starting_balance`:
```python
"final_equity": str(session.final_equity or session.starting_balance)
```

---

### Fix 4C: BUG-BT-15 — Misleading error for stepping completed backtest

**Root Cause:** Auto-complete pops session from `engine._active` dict. Subsequent step raises `BacktestNotFoundError("is not active")` instead of `BacktestInvalidStateError("already completed")`.

**File:** `src/api/routes/backtest.py` — `step_backtest()` (~line 176)

**Change:** Catch `BacktestNotFoundError`, re-query the DB for actual status, and raise a specific error:
```python
try:
    result = await engine.step(session_id, steps, db)
except BacktestNotFoundError:
    session = await repo.get_session(session_id)
    if session and session.status == "completed":
        raise BacktestInvalidStateError("Backtest session has already completed", current_status="completed")
    elif session and session.status == "failed":
        raise BacktestInvalidStateError("Backtest session has failed", current_status="failed")
    elif session and session.status == "cancelled":
        raise BacktestInvalidStateError("Backtest session was cancelled", current_status="cancelled")
    raise  # genuinely not found
```

---

### Fix 4D: BUG-BT-16 — Missing agent_id silently defaults

**Root Cause:** Route falls back to `_get_agent_id(request)` when `body.agent_id` is None.

**Decision needed:** Is this by design? If yes → document it in the API docs. If no → make `agent_id` required in the schema.

**File:** `src/api/schemas/backtest.py` — `BacktestCreateRequest.agent_id`

**Change (if making required):**
```python
agent_id: str  # Remove Optional/None default
```

**Change (if keeping fallback):** Add a note in the response indicating which agent was used:
```python
"agent_id": str(agent_id),  # Already done, but add docs
```

---

## Execution Order & Dependencies

```
Sprint 1 (P0 — do first, blocks everything):
  Fix 1A (BT-01) ← Must fix first; other tests can't run without this
  Fix 1B (BT-02 + BT-17) ← Unblocks risk management testing

Sprint 2 (P1 — correctness):
  Fix 2A (BT-03) ← Schema validation, no deps
  Fix 2B (BT-04) ← Requires understanding metrics persistence
  Fix 2C (BT-05) ← Route-level validation
  Fix 2D (BT-06) ← Schema validation, no deps
  
  2A, 2C, 2D can be done in parallel (all independent schema/route changes)
  2B depends on understanding the metrics JSONB structure

Sprint 3 (P2 — validation):
  Fix 3A (BT-07) ← Schema validation
  Fix 3B (BT-08) ← Route logic
  Fix 3C (BT-09) ← Route logic
  Fix 3D (BT-10 + BT-11) ← Route + repo changes, related
  Fix 3E (BT-12) ← Schema validation
  
  3A, 3B, 3C, 3E can be done in parallel
  3D is more complex (JSONB sorting in SQL)

Sprint 4 (P3 — polish):
  Fix 4A (BT-13) ← Depends on understanding compare route
  Fix 4B (BT-14) ← Simple default change
  Fix 4C (BT-15) ← Route-level error improvement
  Fix 4D (BT-16) ← Design decision needed
  
  All Sprint 4 fixes are independent
```

---

## Test Plan

Each fix needs:
1. **Regression test** — reproduce the exact bug scenario from the tester report
2. **Positive test** — verify the happy path still works
3. **Edge case test** — boundary values for validation fixes

**Key test scenarios to add:**
| Bug | Test |
|-----|------|
| BT-01 | `test_create_multiple_sequential_backtests` — create 3 backtests back-to-back, all must complete |
| BT-02 | `test_stop_loss_triggers_on_price_drop` — place stop-loss, step through price below trigger, verify fill |
| BT-03 | `test_reject_end_before_start` — expect 422 with clear error |
| BT-04 | `test_results_by_pair_populated` — run backtest with 2 pairs, verify per-pair stats |
| BT-05 | `test_create_with_fake_agent_id` — expect 404 AGENT_NOT_FOUND |
| BT-06 | `test_reject_invalid_candle_interval` — 999 → 422 |
| BT-07 | `test_reject_invalid_symbol` — FAKECOIN → 422 |
| BT-08 | `test_compare_missing_session_id` — expect error listing missing IDs |
| BT-09 | `test_compare_requires_two_sessions` — single ID → 422 |
| BT-10 | `test_best_rejects_invalid_metric` — banana → 422 |
| BT-11 | `test_best_by_sharpe_returns_value` — verify actual sharpe ratio returned |
| BT-12 | `test_reject_excessive_balance` — 10B → 422 |
| BT-13 | `test_cancelled_session_metrics_null` — metrics should be null, not 100%/0 |
| BT-14 | `test_failed_session_equity_equals_starting` — final_equity = starting_balance |
| BT-15 | `test_step_completed_backtest_message` — error says "already completed" |

---

## Estimated Scope

| Sprint | Bugs | Files Changed | New Tests |
|--------|------|---------------|-----------|
| 1 | 3 (BT-01, BT-02, BT-17) | 3 | ~6 |
| 2 | 4 (BT-03, BT-04, BT-05, BT-06) | 5 | ~8 |
| 3 | 5 (BT-07, BT-08, BT-09, BT-10/11, BT-12) | 3 | ~10 |
| 4 | 4 (BT-13, BT-14, BT-15, BT-16) | 1-2 | ~6 |
| **Total** | **17** | **6 files** | **~30 tests** |

---

*Generated: 2026-04-06*
