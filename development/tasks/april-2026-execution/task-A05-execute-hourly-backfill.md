---
task_id: A-05
title: "Execute hourly backfill (top 5)"
type: task
agent: "backend-developer"
track: A
depends_on: ["A-04"]
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

# Task A-05: Execute hourly backfill (top 5)

## Assigned Agent: `backend-developer`

## Objective
Run the hourly candle backfill for the top 5 USDT pairs. PPO training specifically needs 1h candle data for its observation space.

## Context
Critical path task. The headless gym environment uses hourly candles for training. Estimated runtime: 3-5 hours (much more data than daily).

## Command
```bash
python scripts/backfill_history.py --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT --interval 1h --resume
```

## Acceptance Criteria
- [ ] Backfill completes for all 5 pairs
- [ ] `candles_backfill` contains 1h candles for BTCUSDT with 12+ months of coverage
- [ ] Data is gap-free (no missing hours in continuous trading periods)
- [ ] `--resume` works correctly if script is restarted

## Dependencies
- **A-04**: Daily backfill should complete first (to avoid concurrent DB load)

## Agent Instructions
Run the hourly backfill command. This will take 3-5 hours. Monitor for rate limiting and connection errors. After completion, verify data completeness with:
```sql
SELECT symbol, COUNT(*), MIN(timestamp), MAX(timestamp) 
FROM candles_backfill WHERE interval = '1h' 
GROUP BY symbol ORDER BY symbol;
```

## Estimated Complexity
Medium — long-running, more data volume than daily. Risk: Binance rate limits on 1h data.
