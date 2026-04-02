---
task_id: 06
title: "Fix strategy creation ValidationError (BUG-005)"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "pending"
priority: "high"
board: "[[qa-bugfix-sprint/README]]"
files: ["src/strategies/service.py", "src/strategies/models.py", "src/api/routes/strategies.py"]
tags:
  - task
  - strategies
  - P0
---

# Task 06: Fix strategy creation INTERNAL_ERROR (BUG-005)

## Assigned Agent: `backend-developer`

## Objective
Fix `POST /strategies` which returns `INTERNAL_ERROR` because an unhandled Pydantic `ValidationError` from `StrategyDefinition(**definition)` propagates as HTTP 500.

## Context
`StrategyService.create_strategy()` at line ~63 calls `StrategyDefinition(**definition)` to validate the incoming definition dict. If the dict is missing required fields (like `pairs`) or contains invalid data, Pydantic raises `ValidationError` which is never caught — it bubbles to the global handler as HTTP 500. This makes the entire strategy system unusable, which also blocks RL training.

## Files to Modify/Create
- `src/strategies/service.py` — wrap `StrategyDefinition(**definition)` in try/except (line ~63)
- `src/strategies/models.py` — read to understand `StrategyDefinition` required fields
- `src/api/routes/strategies.py` — verify the route handler passes data correctly

## Acceptance Criteria
- [ ] Valid strategy definition returns `strategy_id` (HTTP 201)
- [ ] Invalid definition returns HTTP 400 with specific validation errors (not HTTP 500)
- [ ] Empty definition `{}` returns HTTP 400 listing which fields are required
- [ ] The `StrategyDefinition` schema is documented in the API response/docs
- [ ] Regression tests: valid creation + 3 invalid payloads

## Dependencies
None — independent fix.

## Agent Instructions
1. Read `src/strategies/CLAUDE.md` for context
2. Read `src/strategies/models.py` — understand `StrategyDefinition` fields and which are required
3. Read `src/strategies/service.py` — find `create_strategy()`, locate the `StrategyDefinition(**definition)` call
4. Wrap in try/except:
   ```python
   from pydantic import ValidationError
   from src.utils.exceptions import InputValidationError

   try:
       validated_def = StrategyDefinition(**definition)
   except ValidationError as e:
       raise InputValidationError(
           message=f"Invalid strategy definition: {e.error_count()} validation errors",
           details={"errors": e.errors()},
       ) from e
   ```
5. Verify `InputValidationError` exists in `src/utils/exceptions.py` — if not, create it or use the closest existing validation exception
6. Check if the route handler in `strategies.py` also needs error handling
7. Write tests that cover both valid and invalid strategy payloads

## Estimated Complexity
Low — clear root cause, simple try/except fix. Most work is writing the regression tests.
