---
task_id: R1-07
title: "Backfill historical candle data (12+ months)"
type: task
agent: "backend-developer"
phase: 1
depends_on: ["R1-05"]
status: "completed"
priority: "high"
board: "[[c-level-recommendations/README]]"
files: ["scripts/backfill_history.py"]
tags:
  - task
  - infrastructure
  - data
  - training
---

# Task R1-07: Backfill Historical Candle Data

## Assigned Agent: `backend-developer`

## Objective
Load 12+ months of 1h candle data for top 5 trading pairs from Binance into TimescaleDB.

## Context
ML strategy training (regime classifier, PPO RL, evolutionary GA) requires historical candle data. Walk-forward validation needs at least 12 months for 6 rolling windows. This is the critical-path bottleneck for Phase 3.

## Files to Modify/Create
- `scripts/backfill_history.py` (execute only)

## Acceptance Criteria
- [x] Backfill script completes for BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT
- [x] Data covers Jan 2024 to present (12+ months)
- [x] 1h interval candle data (8,760+ candles per symbol per year)
- [x] Coverage >= 95% validated via data prep script
- [x] `candles_backfill` table populated

## Completion Notes
- Completed: 2026-03-23
- Runtime: 29 seconds (Binance API rate limits were not hit; 3-way concurrency worked well)
- Total candles inserted: 97,520 (19,504 per symbol × 5 symbols)
- Coverage: 19,504 1h candles per symbol from 2024-01-01 to 2026-03-23 (27+ months, ~100%)
- All 5 symbols: 0 failures, ON CONFLICT DO NOTHING merged cleanly with pre-existing data from 2021
- Database: `candles_backfill` hypertable fully populated; data ready for ML training and walk-forward validation

## Dependencies
- R1-05 (TimescaleDB + API healthy)

## Agent Instructions
1. Run:
   ```bash
   python scripts/backfill_history.py \
     --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT \
     --interval 1h \
     --start 2024-01-01
   ```
2. Monitor progress — takes 10-30 minutes depending on Binance rate limits
3. Script supports `--resume` for interruption recovery
4. Validate coverage after completion

## Estimated Complexity
High — long-running process dependent on external API rate limits
