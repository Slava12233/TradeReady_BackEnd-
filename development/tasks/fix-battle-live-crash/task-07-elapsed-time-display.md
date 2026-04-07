---
task_id: 7
title: "Add elapsed time display in BattleDetail"
type: task
agent: "frontend-developer"
phase: 3
depends_on: [6]
status: "pending"
priority: "low"
board: "[[fix-battle-live-crash/README]]"
files:
  - "Frontend/src/components/battles/BattleDetail.tsx"
tags:
  - task
  - battles
  - frontend
  - enhancement
---

# Task 07: Add elapsed time display in BattleDetail

## Assigned Agent: `frontend-developer`

## Objective
Display the elapsed time alongside the remaining time in the live battle view, using the new `elapsed_minutes` field from the backend.

## Context
After Tasks 04 and 06, the backend sends `elapsed_minutes` and the frontend type includes it. This task adds a visual display so users can see how long the battle has been running.

## Files to Modify
- `Frontend/src/components/battles/BattleDetail.tsx` — Add elapsed time badge near the remaining time badge

## Specific Changes

Near the existing remaining time badge (around line 306-315), add an elapsed time display:

```tsx
{/* Time info */}
<div className="flex items-center gap-3">
  {live.elapsed_minutes != null && (
    <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-muted/50 border border-border w-fit">
      <Timer className="h-4 w-4 text-muted-foreground" />
      <span className="text-sm font-mono tabular-nums text-muted-foreground">
        {Math.floor(live.elapsed_minutes)}m elapsed
      </span>
    </div>
  )}
  {live.remaining_minutes != null && (
    <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-accent/5 border border-accent/20 w-fit">
      <Clock className="h-4 w-4 text-accent" />
      <span className="text-sm font-mono tabular-nums text-accent font-medium">
        {live.remaining_minutes.toFixed(0)}m remaining
      </span>
    </div>
  )}
</div>
```

Import `Timer` from lucide-react if not already imported.

## Acceptance Criteria
- [ ] Elapsed time shows as "Xm elapsed" with muted styling
- [ ] Remaining time still shows as "Xm remaining" with accent styling
- [ ] Both badges appear side by side when both values are available
- [ ] Only elapsed shows if there's no duration limit (remaining is null)
- [ ] Neither shows if the battle hasn't started yet
- [ ] Uses `font-mono tabular-nums` for numbers per project conventions
- [ ] No TypeScript errors

## Dependencies
Task 06 must complete — frontend types must include `elapsed_minutes`.

## Agent Instructions
Read `Frontend/src/components/battles/CLAUDE.md`. Follow existing styling patterns in BattleDetail.tsx. Use the same badge pattern as the existing remaining time display. Import `Timer` from `lucide-react` for the elapsed icon. Keep the existing `Clock` icon for remaining time.

## Estimated Complexity
Low — adding a styled badge component
