---
task_id: 3
title: "Update BattleLiveResponse Pydantic schema"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "pending"
priority: "high"
board: "[[fix-battle-live-crash/README]]"
files:
  - "src/api/schemas/battles.py"
tags:
  - task
  - battles
  - backend
  - schema
---

# Task 03: Update BattleLiveResponse Pydantic schema

## Assigned Agent: `backend-developer`

## Objective
Replace the untyped `list[dict[str, object]]` in `BattleLiveResponse` with a properly typed `BattleLiveParticipantSchema` that includes all fields the frontend needs.

## Context
The current schema at `src/api/schemas/battles.py:120-127` uses `list[dict[str, object]]` for participants, providing no type safety or validation. The frontend expects specific fields with specific names. This task creates the typed schema that Tasks 04 and 05 will populate.

## Files to Modify
- `src/api/schemas/battles.py` — Add `BattleLiveParticipantSchema`, update `BattleLiveResponse`

## Specific Changes

Add a new schema class before `BattleLiveResponse`:

```python
class BattleLiveParticipantSchema(_BaseSchema):
    """One participant's live metrics in an active battle."""

    agent_id: UUID
    display_name: str
    avatar_url: str | None = None
    color: str | None = None
    current_equity: str
    roi_pct: str
    total_pnl: str
    total_trades: int = 0
    win_rate: str | None = None
    sharpe_ratio: str | None = None
    max_drawdown_pct: str | None = None
    rank: int | None = None
    status: str
```

Update `BattleLiveResponse`:

```python
class BattleLiveResponse(_BaseSchema):
    """Response for GET /api/v1/battles/{battle_id}/live."""

    battle_id: UUID
    status: str
    elapsed_minutes: float | None = None
    remaining_minutes: float | None = None
    participants: list[BattleLiveParticipantSchema]
    updated_at: datetime
```

## Acceptance Criteria
- [ ] `BattleLiveParticipantSchema` class exists with all 13 fields
- [ ] `BattleLiveResponse` has `elapsed_minutes`, `remaining_minutes`, `updated_at` fields
- [ ] `BattleLiveResponse.participants` is typed as `list[BattleLiveParticipantSchema]`
- [ ] `ruff check src/api/schemas/battles.py` passes
- [ ] `mypy src/api/schemas/battles.py` passes

## Dependencies
None — schema can be created independently.

## Agent Instructions
Read `src/api/schemas/CLAUDE.md` first. Follow the existing schema patterns — all schemas inherit from `_BaseSchema`. Use `str` for decimal values (equity, PnL) per project convention. Keep the `timestamp` field renamed to `updated_at` for frontend consistency. Import `UUID` from the same place as other schemas in the file.

## Estimated Complexity
Low — adding a new Pydantic model class
