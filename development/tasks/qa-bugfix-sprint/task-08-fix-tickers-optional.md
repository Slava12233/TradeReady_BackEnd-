---
task_id: 08
title: "Make tickers symbols param optional (BUG-012)"
type: task
agent: "backend-developer"
phase: 2
depends_on: []
status: "pending"
priority: "medium"
board: "[[qa-bugfix-sprint/README]]"
files: ["src/api/routes/market.py"]
tags:
  - task
  - market
  - api
  - P2
---

# Task 08: Make tickers `symbols` param optional (BUG-012)

## Assigned Agent: `backend-developer`

## Objective
Change `GET /api/v1/market/tickers` to accept an optional `symbols` query parameter. When omitted, return all available tickers instead of returning HTTP 422.

## Context
The tickers endpoint currently declares `symbols: str = Query(...)` (required). Calling without `symbols` returns `422 Unprocessable Entity`. The single-price endpoint `GET /market/prices` returns all prices when called without params — tickers should behave consistently.

## Files to Modify/Create
- `src/api/routes/market.py` — modify the tickers endpoint (lines ~342-351)

## Acceptance Criteria
- [ ] `GET /market/tickers` without params returns all tickers (HTTP 200)
- [ ] `GET /market/tickers?symbols=BTCUSDT,ETHUSDT` still works (filtered)
- [ ] Response format is identical whether filtered or unfiltered
- [ ] Performance: returning all tickers completes in <2s
- [ ] Regression test added

## Dependencies
None.

## Agent Instructions
1. Read `src/api/routes/market.py` — find the tickers endpoint handler
2. Change `symbols: str = Query(...)` to `symbols: str | None = Query(default=None)`
3. Add logic: if `symbols is None`, fetch all available ticker data from the price cache
4. Follow the pattern used by the prices endpoint (`GET /market/prices`) which already returns all prices
5. Keep the existing filtered behavior when `symbols` is provided

## Estimated Complexity
Low — single parameter change + small handler logic addition.
