---
task_id: 10
title: "Backfill historical candle data (BUG-006)"
type: task
agent: "backend-developer"
phase: 3
depends_on: []
status: "pending"
priority: "high"
board: "[[qa-bugfix-sprint/README]]"
files: ["scripts/backfill_history.py"]
tags:
  - task
  - backtesting
  - data
  - P1
---

# Task 10: Backfill historical candle data (BUG-006)

## Assigned Agent: `backend-developer`

## Objective
Run the existing `backfill_history.py` script to populate historical candle data in TimescaleDB, enabling backtesting against historical periods (not just today's data).

## Context
The backtesting engine only has data from today because the backfill script has never been run. The `candles_backfill` table is empty. When creating a backtest with `start_time: 2025-01-15`, the API returns `BACKTEST_NO_DATA: Start time is before earliest data`. This makes the entire backtesting value proposition non-functional.

## Files to Modify/Create
- `scripts/backfill_history.py` — verify it works, run it
- Documentation — update data availability claims after backfill

## Acceptance Criteria
- [ ] `scripts/backfill_history.py` runs successfully against production DB
- [ ] At minimum, 8 key symbols backfilled: BTC, ETH, SOL, BNB, XRP, DOGE, ADA, AVAX (all USDT pairs)
- [ ] At minimum, 6 intervals backfilled: 1m, 5m, 15m, 1h, 4h, 1d
- [ ] At minimum, 6 months of history (2025-10-01 to 2026-04-01)
- [ ] Backtests can be created with `start_time` in the historical range
- [ ] Documentation updated with actual data availability

## Dependencies
None — operational task.

## Agent Instructions
1. Read `scripts/CLAUDE.md` for script conventions
2. Read `scripts/backfill_history.py` — understand its CLI args, data source (Binance API), and target table
3. Verify the script works locally first with a small test:
   ```bash
   python scripts/backfill_history.py --symbols BTCUSDT --start 2026-03-01 --end 2026-03-02 --intervals 1h
   ```
4. If successful, run the full backfill (consider batching to avoid Binance rate limits):
   - Batch by symbol + month to stay within rate limits
   - Add retry logic if not present
5. After backfill, verify via API:
   ```bash
   curl "/api/v1/backtest/create" -d '{"symbol":"BTCUSDT","start_time":"2025-12-01T00:00:00Z","end_time":"2025-12-07T00:00:00Z","interval":"1h","starting_balance":"10000"}'
   ```
6. Update docs with the actual data range

## Estimated Complexity
Medium — the script exists, but running it at scale requires rate limit management and verification.
