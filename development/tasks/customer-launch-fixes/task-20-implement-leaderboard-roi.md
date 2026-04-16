---
task_id: 20
title: "Implement leaderboard ROI calculation"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["src/api/routes/leaderboard.py", "src/portfolio/service.py", "Frontend/src/components/leaderboard/leaderboard-table.tsx"]
tags:
  - task
  - backend
  - frontend
  - leaderboard
  - P1
---

# Task 20: Implement leaderboard ROI calculation

## Assigned Agent: `backend-developer` (API) + `frontend-developer` (display)

## Objective
Leaderboard ROI shows 0% for all agents — it's a placeholder. Implement real ROI calculation based on agent PnL history.

## Context
Feature completeness audit (SR-09) flagged this — the leaderboard feature appears broken to users even though it's just not implemented yet. ROI is the primary ranking metric.

## Files to Modify
- `src/api/routes/leaderboard.py` — Compute real ROI from agent trading history
- `src/portfolio/service.py` — Add ROI calculation method if not already present
- `Frontend/src/components/leaderboard/leaderboard-table.tsx` — Verify it displays the calculated ROI

## Acceptance Criteria
- [ ] Leaderboard API returns real ROI percentages (not 0%)
- [ ] ROI formula: (current_value - initial_value) / initial_value * 100
- [ ] Agents with no trades show 0% (legitimate zero)
- [ ] Leaderboard is sorted by ROI descending
- [ ] Frontend table displays the real percentages

## Agent Instructions
1. Read `src/portfolio/CLAUDE.md` for PnL calculation patterns
2. ROI should be calculated from the agent's total PnL relative to initial balance (10,000 USDT)
3. Cache the leaderboard results in Redis (TTL 60s) to avoid computing on every request
4. Frontend should already display whatever the API returns — verify it handles real numbers

## Estimated Complexity
Medium — calculation logic + caching
