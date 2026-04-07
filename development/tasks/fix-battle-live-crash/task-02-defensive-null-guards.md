---
task_id: 2
title: "Defensive null guards in AgentPerformanceCard & BattleList"
type: task
agent: "frontend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[fix-battle-live-crash/README]]"
files:
  - "Frontend/src/components/battles/AgentPerformanceCard.tsx"
  - "Frontend/src/components/battles/BattleList.tsx"
tags:
  - task
  - battles
  - bugfix
  - frontend
---

# Task 02: Defensive null guards in AgentPerformanceCard & BattleList

## Assigned Agent: `frontend-developer`

## Objective
Add null/undefined safety to all `.toFixed()` and `parseFloat()` calls in battle components that receive data from the live endpoint. The backend currently returns fewer fields than the frontend expects, so many values are `undefined` at runtime.

## Context
The backend `get_live_snapshot()` returns only: `agent_id`, `display_name`, `equity`, `pnl`, `pnl_pct`, `status`. The frontend expects: `current_equity`, `roi_pct`, `total_pnl`, `total_trades`, `win_rate`, `sharpe_ratio`, `max_drawdown_pct`, `rank`, `avatar_url`, `color`. Field names also differ (`equity` vs `current_equity`, `pnl_pct` vs `roi_pct`).

## Files to Modify
- `Frontend/src/components/battles/AgentPerformanceCard.tsx` — Null-safe `total_trades` and equity display
- `Frontend/src/components/battles/BattleList.tsx` — Defensive `roi_pct` guard

## Specific Changes

### AgentPerformanceCard.tsx

**Line 92** — Already safe (`p.roi_pct ?? "0"`), no change needed.

**Line 99** (equity display) — Ensure `current_equity` falls back to `equity` field:
```tsx
// Add near line 92, after roi parsing:
const equityStr = p.current_equity ?? (p as any).equity ?? "0";
```

**Line 227** — `total_trades` null safety:
```tsx
// BEFORE
value={String(p.total_trades)}

// AFTER
value={p.total_trades != null ? String(p.total_trades) : "\u2014"}
```

### BattleList.tsx

**Line 104** — The existing guard `leader.roi_pct &&` is mostly safe, but add explicit null check:
```tsx
// BEFORE
{leader.roi_pct && (

// AFTER
{leader.roi_pct != null && leader.roi_pct !== "" && (
```

Also ensure `leader.roi_pct` falls back to `(leader as any).pnl_pct` if the backend field name mismatch persists:
```tsx
const roiPct = leader.roi_pct ?? (leader as any).pnl_pct;
```

## Acceptance Criteria
- [ ] `AgentPerformanceCard` displays "—" for `total_trades` when undefined
- [ ] `AgentPerformanceCard` equity display works even when field name is `equity` instead of `current_equity`
- [ ] `BattleList` doesn't show "NaN%" for leader ROI when field is missing
- [ ] No TypeScript errors introduced
- [ ] Existing battles (completed ones with full data) still render correctly

## Dependencies
None — can run in parallel with Task 01.

## Agent Instructions
Read `Frontend/src/components/battles/CLAUDE.md` first. The key insight is that the backend sends `equity`/`pnl`/`pnl_pct` but the frontend expects `current_equity`/`total_pnl`/`roi_pct`. Add fallbacks that check both field names. Use `(p as any).fieldName` for the fallback fields since the TypeScript type doesn't have them yet (that's Task 06).

## Estimated Complexity
Low — small defensive changes across 2 files
