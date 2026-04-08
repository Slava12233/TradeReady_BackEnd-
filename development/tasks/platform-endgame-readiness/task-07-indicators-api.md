---
task_id: 7
title: "Create Market Data Indicators API endpoints"
type: task
agent: "backend-developer"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[platform-endgame-readiness/README]]"
files:
  - "src/api/routes/indicators.py"
  - "src/api/schemas/indicators.py"
  - "src/main.py"
tags:
  - task
  - market-data
  - indicators
  - phase-1
---

# Task 07: Create Market Data Indicators API endpoints

## Assigned Agent: `backend-developer`

## Objective
Expose the existing `IndicatorEngine` (from `src/strategies/indicators.py`) via REST API with Redis caching.

## Context
The platform already has a working `IndicatorEngine` with 7 indicators computing 15 values per symbol (RSI, MACD, SMA, EMA, Bollinger, ADX, ATR, volume MA). It's only used internally by `StrategyExecutor`. This task exposes it via REST so external agents can access computed indicators without reimplementing them.

## Files to Modify/Create
- `src/api/routes/indicators.py` — Create: `GET /api/v1/market/indicators/{symbol}` and `GET /api/v1/market/indicators/available`
- `src/api/schemas/indicators.py` — Create: `IndicatorResponse`, `AvailableIndicatorsResponse` schemas
- `src/main.py` — Register indicators router

## Acceptance Criteria
- [ ] `GET /api/v1/market/indicators/{symbol}` returns computed indicator values
- [ ] Query params: `indicators` (comma-separated filter), `lookback` (default 200, range 14-500)
- [ ] Response includes: symbol, timestamp, candles_used, indicators dict
- [ ] `GET /api/v1/market/indicators/available` returns static list of supported indicators
- [ ] Redis caching with 30-second TTL (key: `indicators:{symbol}:{sorted_indicator_hash}`)
- [ ] Symbol validation: `^[A-Z]{2,10}USDT$`
- [ ] Falls under `/api/v1/market/*` public prefix — no auth changes needed
- [ ] Router registered in `src/main.py`
- [ ] `ruff check` and `mypy` pass

## Dependencies
None — this is a Phase 1 task with no prerequisites.

## Agent Instructions
1. Read `src/strategies/CLAUDE.md` and look at `src/strategies/indicators.py` for `IndicatorEngine` interface
2. Read `src/cache/CLAUDE.md` for Redis cache patterns
3. Read `src/api/routes/CLAUDE.md` for route patterns
4. Implementation flow: validate symbol → check Redis → on miss: query last N 1-min candles from TimescaleDB → feed through fresh `IndicatorEngine` → filter to requested indicators → cache → return
5. The available indicators are: rsi_14, macd_line, macd_signal, macd_hist, sma_20, sma_50, ema_12, ema_26, bb_upper, bb_mid, bb_lower, adx_14, atr_14, volume_ma_20, price

## Estimated Complexity
Medium — main work is wiring the IndicatorEngine to a route with proper caching and candle fetching.
