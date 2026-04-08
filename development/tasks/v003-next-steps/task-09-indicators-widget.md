---
task_id: 9
title: "Indicators dashboard widget on coin detail page"
type: task
agent: "frontend-developer"
phase: 3
depends_on: [6]
status: "pending"
priority: "medium"
board: "[[v003-next-steps/README]]"
files:
  - "Frontend/src/components/coin/indicator-panel.tsx"
  - "Frontend/src/hooks/use-indicators.ts"
  - "Frontend/src/lib/api-client.ts"
tags:
  - task
  - frontend
  - indicators
  - coin-detail
---

# Task 09: Indicators Dashboard Widget

## Assigned Agent: `frontend-developer`

## Objective
Display live technical indicators for the selected symbol on the coin detail page, auto-refreshing every 30 seconds.

## Context
The backend exposes `GET /api/v1/market/indicators/{symbol}` with 15 indicators (RSI, MACD, Bollinger, SMA, EMA, ADX, ATR, volume MA). No frontend currently displays these.

## Files to Modify/Create
- `Frontend/src/components/coin/indicator-panel.tsx` — New component: indicator grid/table with values, color coding (RSI overbought/oversold), sparklines optional
- `Frontend/src/hooks/use-indicators.ts` — TanStack Query hook with 30s refetch interval
- `Frontend/src/lib/api-client.ts` — Add `getIndicators(symbol)` and `getAvailableIndicators()` functions

## Acceptance Criteria
- [ ] Panel shows all 15 indicators with current values
- [ ] RSI color-coded: green < 30, red > 70, neutral otherwise
- [ ] MACD histogram positive/negative color coding
- [ ] Auto-refreshes every 30 seconds
- [ ] Loading skeleton while fetching
- [ ] Integrates into coin detail page layout
- [ ] Responsive for mobile

## Dependencies
- **Task 6** — backend security fixes complete

## Agent Instructions
1. Read `Frontend/src/components/coin/CLAUDE.md` for coin page patterns
2. Read `Frontend/src/hooks/CLAUDE.md` for polling/refetch patterns
3. Group indicators logically: Trend (SMA, EMA), Momentum (RSI, MACD), Volatility (Bollinger, ATR, ADX), Volume

## Estimated Complexity
Medium — data display component with polling and color logic.
