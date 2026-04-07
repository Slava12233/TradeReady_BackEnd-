---
task_id: 6
title: "Sync frontend types & hook field mapping"
type: task
agent: "frontend-developer"
phase: 3
depends_on: [3, 4, 5]
status: "pending"
priority: "medium"
board: "[[fix-battle-live-crash/README]]"
files:
  - "Frontend/src/lib/types.ts"
  - "Frontend/src/hooks/use-battle-results.ts"
tags:
  - task
  - battles
  - frontend
  - types
---

# Task 06: Sync frontend types & hook field mapping

## Assigned Agent: `frontend-developer`

## Objective
Update the TypeScript `BattleLiveResponse` and `BattleLiveParticipant` interfaces to match the enriched backend response. Remove any `(as any)` fallbacks added in Task 02 now that the backend sends correct field names.

## Context
After Tasks 03-05, the backend now sends all expected fields with correct names. The frontend types at `Frontend/src/lib/types.ts:864-887` should already mostly match. This task ensures exact alignment and cleans up any temporary workarounds from Task 02.

## Files to Modify
- `Frontend/src/lib/types.ts` — Verify/update `BattleLiveParticipant` and `BattleLiveResponse` interfaces
- `Frontend/src/hooks/use-battle-results.ts` — Remove any field mapping transforms if present; verify the hook works with new response shape
- `Frontend/src/components/battles/AgentPerformanceCard.tsx` — Remove any `(as any)` fallbacks from Task 02
- `Frontend/src/components/battles/BattleList.tsx` — Remove any `(as any)` fallbacks from Task 02

## Specific Changes

### types.ts

Verify `BattleLiveResponse` (line 880) has:
```typescript
export interface BattleLiveResponse {
  battle_id: string;
  status: BattleStatus;
  elapsed_minutes: number | null;
  remaining_minutes: number | null;
  participants: BattleLiveParticipant[];
  updated_at: string;
}
```

Verify `BattleLiveParticipant` (line 864) has all 13 fields with correct types. Ensure `total_trades` defaults appropriately (it's `number` not `number | null` since backend sends `0` as default).

### use-battle-results.ts

Check the `useBattleLive` hook — ensure it doesn't need a `select` transform now that field names match. If there was a mapping layer, it can be removed.

### Component cleanup

Remove any `(as any)` casts or field name fallbacks added in Task 02, since the backend now sends correct field names.

## Acceptance Criteria
- [ ] `BattleLiveParticipant` TypeScript interface exactly matches backend `BattleLiveParticipantSchema`
- [ ] `BattleLiveResponse` TypeScript interface matches backend schema (with `updated_at`, `elapsed_minutes`, `remaining_minutes`)
- [ ] No `(as any)` casts remain in battle components for field name workarounds
- [ ] `pnpm build` passes with zero TypeScript errors
- [ ] Live battle view renders correctly with enriched data

## Dependencies
Tasks 03, 04, 05 must all be complete — the backend must be sending the correct fields before types are synced.

## Agent Instructions
Read `Frontend/src/lib/CLAUDE.md` first. The types file is at `Frontend/src/lib/types.ts`. The hook is at `Frontend/src/hooks/use-battle-results.ts`. After making changes, run `cd Frontend && pnpm build` to verify no type errors.

## Estimated Complexity
Low — mostly verification and cleanup
