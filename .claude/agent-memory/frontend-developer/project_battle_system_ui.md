---
name: Battle System UI — Task 34
description: Battle system frontend built in Task 34 — file inventory, type additions, API client functions, hooks, components, and routes
type: project
---

# Battle System UI (Task 34)

**Fact:** Full battle system UI was implemented in Task 34 (2026-03-22).

**Why:** The `battles/` directory was empty. Backend API (20 endpoints) was complete. This task filled the last major frontend gap.

**How to apply:** When referencing or extending the battle system, look in these locations.

## Files Created

### Types (`Frontend/src/lib/types.ts`)
Added battle types: `BattleStatus`, `BattleMode`, `ParticipantStatus`, `BattleParticipant`, `Battle`, `BattleListResponse`, `BattleCreateRequest`, `BattlePreset`, `BattlePresetsResponse`, `BattleLiveParticipant`, `BattleLiveResponse`, `BattleResultsParticipant`, `BattleResultsResponse`, `BattleEquitySnapshot`, `BattleReplayResponse`

### API Client (`Frontend/src/lib/api-client.ts`)
Added battle API functions: `getBattles`, `getBattle`, `getBattlePresets`, `createBattle`, `updateBattle`, `deleteBattle`, `addBattleParticipant`, `removeBattleParticipant`, `startBattle`, `stopBattle`, `getBattleLive`, `getBattleResults`, `getBattleReplay`, `rematchBattle`

### Hooks
- `Frontend/src/hooks/use-battles.ts` — CRUD + lifecycle mutations, battleKeys factory
- `Frontend/src/hooks/use-battle-results.ts` — live polling (5s), results, replay snapshots

### Components (`Frontend/src/components/battles/`)
- `shared/battle-status-badge.tsx` — colored status pill with animated dot for "active"
- `shared/battle-mode-badge.tsx` — live vs historical badge
- `BattleList.tsx` — main list with status filter tabs + create CTA
- `BattleCreateDialog.tsx` — 2-step dialog (preset picker → name it)
- `AgentPerformanceCard.tsx` — single agent stat card with rank medal
- `EquityCurveChart.tsx` — overlaid Recharts LineChart (multi-agent equity)
- `BattleDetail.tsx` — tabbed detail view (overview/live/results/replay) with participant management
- `BattleReplay.tsx` — time-slider scrubber with play/pause/speed controls
- `BattleLeaderboard.tsx` — cross-battle aggregate rankings (wins, avg ROI, total PnL)

### Routes
- `Frontend/src/app/(dashboard)/battles/page.tsx` — main page (battles tab + leaderboard tab)
- `Frontend/src/app/(dashboard)/battles/[id]/page.tsx` — detail page
- `Frontend/src/app/(dashboard)/battles/[id]/loading.tsx` — skeleton loading
