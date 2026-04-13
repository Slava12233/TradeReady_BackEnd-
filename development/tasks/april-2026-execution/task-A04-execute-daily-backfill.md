---
task_id: A-04
title: "Execute daily backfill (top 20)"
type: task
agent: "backend-developer"
track: A
depends_on: ["A-03"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["scripts/backfill_history.py"]
tags:
  - task
  - data
  - backfill
  - critical-path
---

# Task A-04: Execute daily backfill (top 20)

## Assigned Agent: `backend-developer`

## Objective
Run the daily candle backfill for the top 20 USDT pairs. This loads 12+ months of daily OHLCV data into the `candles_backfill` hypertable.

## Context
This is on the **critical path**. PPO training (Track B), regime classifier, evolutionary fitness, and backtesting all require this historical data. Estimated runtime: 2-3 hours.

## Files to Use
- `scripts/backfill_history.py` — main backfill script

## Command
```bash
python scripts/backfill_history.py --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,DOTUSDT,LINKUSDT,MATICUSDT,SHIBUSDT,LTCUSDT,UNIUSDT,ATOMUSDT,NEARUSDT,AAVEUSDT,ARBUSDT,OPUSDT,APTUSDT --interval 1d --resume
```

## Acceptance Criteria
- [ ] Backfill completes for all 20 pairs
- [ ] `candles_backfill` contains daily candles from 2017+ for BTC/ETH (or earliest available per pair)
- [ ] `--resume` flag ensures no duplicate data if restarted
- [ ] No connection errors or timeouts during execution

## Dependencies
- **A-03**: Dry-run must have passed successfully

## Agent Instructions
Run the backfill command. This is a long-running operation (2-3 hours). Use `--resume` so it can be safely restarted if interrupted. Monitor output for errors. If rate-limited by Binance, the script should handle retries automatically. After completion, do a quick row count: `SELECT symbol, COUNT(*), MIN(timestamp), MAX(timestamp) FROM candles_backfill WHERE interval = '1d' GROUP BY symbol ORDER BY symbol;`

## Estimated Complexity
Medium — long-running but using an existing script. Risk: rate limiting, connection issues.
