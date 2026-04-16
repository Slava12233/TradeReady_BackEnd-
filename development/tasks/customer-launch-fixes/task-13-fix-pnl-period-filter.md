---
task_id: 13
title: "Fix PnL endpoint period filter"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "completed"
priority: "P1"
board: "[[customer-launch-fixes/README]]"
files: ["src/portfolio/service.py", "src/api/routes/portfolio.py"]
tags:
  - task
  - backend
  - pnl
  - data-accuracy
  - P1
---

# Task 13: Fix PnL endpoint period filter

## Assigned Agent: `backend-developer`

## Objective
The PnL endpoint uses a count-based period filter instead of time-based. Requesting "last 7 days of PnL" returns the last N records regardless of time, leading to wrong PnL numbers.

## Context
Code standards review (SR-04) flagged this as HIGH — PnL numbers are the most important metric for traders. Wrong numbers destroy trust.

## Files to Modify
- `src/portfolio/service.py` — Change period filter from count-based to time-based
- `src/api/routes/portfolio.py` — Update query parameters if needed

## Acceptance Criteria
- [ ] PnL endpoint filters by actual time period (e.g., last 7 days = trades from 7 days ago to now)
- [ ] Time-based filter uses proper datetime comparison with timezone awareness
- [ ] API query parameter clearly communicates it's a time period (e.g., `period=7d`, `period=30d`)
- [ ] Backward-compatible: existing API consumers don't break
- [ ] Test: requesting 7d PnL only includes trades from the last 7 calendar days

## Agent Instructions
1. Read `src/portfolio/CLAUDE.md` for portfolio service patterns
2. Find the current count-based filter and replace with `WHERE created_at >= NOW() - INTERVAL '7 days'` equivalent
3. Support standard period formats: 1d, 7d, 30d, 90d, all
4. Write a unit test that creates trades across different dates and verifies the filter

## Estimated Complexity
Medium — query logic change + test
