---
task_id: D-07
title: "Test market components (3)"
type: task
agent: "frontend-developer"
track: D
depends_on: ["D-02"]
status: "completed"
priority: "medium"
board: "[[april-2026-execution/README]]"
files: [
  "Frontend/src/components/market/__tests__/MarketTable.test.tsx",
  "Frontend/src/components/coin/__tests__/CoinDetail.test.tsx",
  "Frontend/src/components/coin/__tests__/OrderBook.test.tsx"
]
tags:
  - task
  - frontend
  - testing
  - market
---

# Task D-07: Test market components (3)

## Assigned Agent: `frontend-developer`

## Objective
Write tests for MarketTable (with virtual scrolling), CoinDetail, and OrderBook.

## Files to Reference
- `Frontend/src/components/market/CLAUDE.md`
- `Frontend/src/components/coin/CLAUDE.md`

## Acceptance Criteria
- [ ] 3 test files created
- [ ] MarketTable: renders pair rows, search filtering, sort columns, handles 600+ pairs
- [ ] CoinDetail: renders TradingView chart area, price stats, pair info
- [ ] OrderBook: renders bid/ask sides, price levels, quantity bars
- [ ] Virtual scroll behavior tested (or mocked appropriately)
- [ ] All tests pass

## Dependencies
- **D-02**: Test utilities

## Agent Instructions
MarketTable uses virtual scrolling (likely `@tanstack/react-virtual`) — you may need to mock the virtualization or test with a subset of data. CoinDetail may embed TradingView — mock the chart widget. OrderBook has real-time updates — mock the WebSocket connection.

## Estimated Complexity
Medium — virtual scrolling and chart widgets need careful mocking.
