---
task_id: 4
title: "Schema validation: date range, intervals, balance cap"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "high"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "src/api/schemas/backtest.py"
  - "src/backtesting/engine.py"
tags:
  - task
  - backtesting
  - p1
---

# Task 04: Schema Validation — BT-03, BT-06, BT-12

## Assigned Agent: `backend-developer`

## Objective
Fix three input validation bugs in `BacktestCreateRequest`:

1. **BT-03:** End date before start date accepted → creates negative total_steps
2. **BT-06:** Non-standard candle intervals (e.g., 999) silently accepted
3. **BT-12:** No upper limit on starting_balance (accepts 1 billion)

## Files to Modify

### `src/api/schemas/backtest.py` — `BacktestCreateRequest` class:

**BT-03:** Add cross-field validator:
```python
from pydantic import model_validator
from typing import Self

@model_validator(mode="after")
def validate_date_range(self) -> Self:
    if self.end_time <= self.start_time:
        raise ValueError("end_time must be after start_time")
    return self
```

**BT-06:** Restrict candle_interval to valid values:
```python
VALID_INTERVALS = {60, 300, 3600, 86400}

@field_validator("candle_interval")
@classmethod
def validate_interval(cls, v: int) -> int:
    if v not in {60, 300, 3600, 86400}:
        raise ValueError(f"candle_interval must be one of [60, 300, 3600, 86400]")
    return v
```

**BT-12:** Add upper bound:
```python
starting_balance: Decimal = Field(ge=Decimal("1"), le=Decimal("10000000"))
```

### `src/backtesting/engine.py` — `create_session()`:
Add defense-in-depth check for date range (in case schema validation is bypassed).

## Acceptance Criteria
- [ ] `end_time < start_time` → 422 with clear message
- [ ] `candle_interval=999` → 422 listing valid values
- [ ] `starting_balance=1000000000` → 422 with max limit
- [ ] Valid requests still work (60s, 300s, 3600s, 86400s intervals)
- [ ] Existing tests pass

## Dependencies
None — schema-only changes.

## Agent Instructions
Read `src/api/schemas/CLAUDE.md` for Pydantic v2 patterns used in the project. Use `model_validator` for cross-field checks and `field_validator` for single-field checks. Check if the schema already has validators you need to integrate with.

## Estimated Complexity
Low — pure validation additions, no business logic changes.
