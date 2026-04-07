---
task_id: 1
title: "Hotfix: BattleDetail remaining_minutes crash"
type: task
agent: "frontend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[fix-battle-live-crash/README]]"
files: ["Frontend/src/components/battles/BattleDetail.tsx"]
tags:
  - task
  - battles
  - bugfix
  - frontend
  - hotfix
---

# Task 01: Hotfix — BattleDetail remaining_minutes crash

## Assigned Agent: `frontend-developer`

## Objective
Fix the crash "Cannot read properties of undefined (reading 'toFixed')" on `BattleDetail.tsx` line 312. This is the PRIMARY crash that blocks live battle observation.

## Context
The backend `GET /api/v1/battles/{id}/live` does NOT return `remaining_minutes` in its response. The frontend type declares it as `number | null`, but the actual value at runtime is `undefined`. The guard on line 308 uses strict equality (`!== null`) which passes for `undefined`, causing `.toFixed(0)` to be called on `undefined`.

## Files to Modify
- `Frontend/src/components/battles/BattleDetail.tsx` — Fix the null guard on line 308

## Specific Changes

**Line 308** — Change strict null check to loose equality:
```tsx
// BEFORE (line 308)
{live.remaining_minutes !== null && (

// AFTER — catches both null and undefined
{live.remaining_minutes != null && (
```

Also apply the same pattern to `elapsed_minutes` if it's referenced anywhere in the file.

## Acceptance Criteria
- [ ] `BattleDetail.tsx` line 308 uses `!= null` (loose equality) instead of `!== null`
- [ ] Opening `/battles/{id}` for a live battle no longer crashes
- [ ] When `remaining_minutes` is undefined/null, the time remaining section is hidden (not shown as "NaN")
- [ ] No TypeScript errors introduced

## Dependencies
None — this is the first task and can run immediately.

## Agent Instructions
Read `Frontend/src/components/battles/CLAUDE.md` and `Frontend/CLAUDE.md` first. This is a one-line fix. Do NOT add any other changes — keep the diff minimal for this hotfix.

## Estimated Complexity
Low — single character change (`!==` to `!=`)
