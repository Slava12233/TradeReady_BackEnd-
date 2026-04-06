---
task_id: 7
title: "Schema validation: pairs symbol format"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "completed"
priority: "medium"
board: "[[backtest-bugfix-sprint/README]]"
files:
  - "src/api/schemas/backtest.py"
tags:
  - task
  - backtesting
  - p2
---

# Task 07: Fix BT-07 — Invalid Symbol in Pairs Silently Accepted

## Assigned Agent: `backend-developer`

## Objective
`pairs: ["FAKECOINUSDT"]` is accepted without validation. Add format validation for trading pair symbols.

## Files to Modify

### `src/api/schemas/backtest.py`:
Add a field validator for `pairs`:
```python
@field_validator("pairs")
@classmethod
def validate_pairs(cls, v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    import re
    pattern = re.compile(r"^[A-Z]{2,10}USDT$")
    invalid = [p for p in v if not pattern.match(p)]
    if invalid:
        raise ValueError(f"Invalid trading pairs: {invalid}. Must match pattern [A-Z]{{2,10}}USDT")
    return v
```

## Acceptance Criteria
- [ ] `FAKECOINUSDT` with invalid format → 422
- [ ] `BTCUSDT`, `ETHUSDT` → accepted
- [ ] `btcusdt` (lowercase) → 422
- [ ] Empty list `[]` → accepted (or rejected, be consistent with existing behavior)
- [ ] `None` / omitted → accepted (uses default pairs)

## Dependencies
None.

## Agent Instructions
This validates format only, not existence in the database. A symbol like `ABCUSDT` passes format validation but may have no data — the engine handles that at runtime. Keep the validator simple.

## Estimated Complexity
Low — single field validator.
