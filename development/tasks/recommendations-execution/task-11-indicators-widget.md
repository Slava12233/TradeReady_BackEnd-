---
task_id: 11
title: "Indicators dashboard widget on coin detail page"
type: task
agent: "frontend-developer"
phase: 2
depends_on: [9]
status: "done"
priority: "medium"
board: "[[recommendations-execution/README]]"
files:
  - "Frontend/src/components/coin/indicators-widget.tsx"
  - "Frontend/src/hooks/use-indicators.ts"
tags:
  - task
  - frontend
  - indicators
  - coin-detail
---

# Task 11: Indicators Dashboard Widget

## Assigned Agent: `frontend-developer`

## Objective
Display live technical indicators for the selected symbol on the coin detail page, auto-refreshing every 30 seconds.

## Context
R3 Component 2. Backend exposes `GET /api/v1/market/indicators/{symbol}` with 15 indicators.

## Files to Modify/Create
- `Frontend/src/hooks/use-indicators.ts` — TanStack Query hook with 30s refetchInterval
- `Frontend/src/components/coin/indicators-widget.tsx` — Grid of indicator values with color coding
- Wire into coin detail page

## Acceptance Criteria
- [x] Shows all 15 indicators grouped: Trend (SMA, EMA), Momentum (RSI, MACD), Volatility (BB, ATR, ADX), Volume
- [x] RSI color-coded: green < 30, red > 70
- [x] MACD histogram positive/negative coloring
- [x] Auto-refresh every 30 seconds
- [x] Loading skeleton
- [x] Responsive for mobile

## Agent Instructions
1. Read `Frontend/src/components/coin/CLAUDE.md`
2. Read `Frontend/src/hooks/CLAUDE.md` for polling patterns
3. Use `staleTime: 30_000` and `refetchInterval: 30_000`

## Estimated Complexity
Medium — data display with polling and color logic.
