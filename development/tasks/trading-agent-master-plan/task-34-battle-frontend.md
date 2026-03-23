---
task_id: 34
title: "Build battle system frontend"
type: task
agent: "frontend-developer"
phase: 5
depends_on: []
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["Frontend/src/components/battles/"]
tags:
  - task
  - frontend
  - battles
---

# Task 34: Battle system frontend

## Assigned Agent: `frontend-developer`

## Objective
Build the battle system UI — the last major incomplete frontend area. Components needed:

## Components to Create
```
Frontend/src/components/battles/
├── BattleList.tsx           — list all battles with status filters
├── BattleDetail.tsx         — single battle: participants, metrics, status
├── BattleLeaderboard.tsx    — agent rankings across all battles
├── AgentPerformanceCard.tsx — individual agent stats card
├── EquityCurveChart.tsx     — overlaid equity curves (Recharts)
├── BattleCreateDialog.tsx   — create new battle (preset selection)
└── BattleReplay.tsx         — time-slider replay of historical battles
```

## Also Needed
- Hooks: `useBattles`, `useBattle`, `useBattleResults`
- API client functions for all 20 battle endpoints
- Route: `/battles` and `/battles/[id]`

## Acceptance Criteria
- [ ] All 7 components implemented following `Frontend/CLAUDE.md` conventions
- [ ] 3 custom hooks with TanStack Query
- [ ] Battle list with status filters (draft, active, completed)
- [ ] Real-time live battle view (polling or WebSocket)
- [ ] Equity curve chart with agent comparison
- [ ] Create dialog with preset selection
- [ ] Mobile responsive layout
- [ ] TypeScript: zero errors

## Estimated Complexity
High — 7 new components, 3 hooks, 2 routes.
