---
task_id: A-06
title: "Validate data completeness"
type: task
agent: "e2e-tester"
track: A
depends_on: ["A-05"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: []
tags:
  - task
  - data
  - validation
---

# Task A-06: Validate data completeness

## Assigned Agent: `e2e-tester`

## Objective
Query `candles_backfill` to confirm row counts, date ranges, and gap-free coverage for all loaded data.

## Context
Before declaring Track A complete, we need to verify the data is actually usable for training and backtesting — correct row counts, no gaps, proper OHLCV values.

## Acceptance Criteria
- [ ] 20 pairs have daily candle data
- [ ] 5 pairs have hourly candle data
- [ ] BTCUSDT daily data spans from 2017 to present
- [ ] BTCUSDT hourly data covers 12+ months
- [ ] No NULL values in open, high, low, close, volume columns
- [ ] No duplicate timestamps per symbol+interval
- [ ] Gap analysis: no missing trading days (weekends excluded for crypto = none expected)

## Dependencies
- **A-05**: All backfill operations must be complete

## Agent Instructions
Run these validation queries against TimescaleDB:

1. Row counts per symbol and interval:
```sql
SELECT symbol, interval, COUNT(*), MIN(timestamp), MAX(timestamp) 
FROM candles_backfill GROUP BY symbol, interval ORDER BY symbol, interval;
```

2. Check for NULLs:
```sql
SELECT COUNT(*) FROM candles_backfill 
WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL OR volume IS NULL;
```

3. Check for duplicates:
```sql
SELECT symbol, interval, timestamp, COUNT(*) 
FROM candles_backfill GROUP BY symbol, interval, timestamp HAVING COUNT(*) > 1;
```

4. Gap check for BTCUSDT daily:
```sql
WITH gaps AS (
  SELECT timestamp, LAG(timestamp) OVER (ORDER BY timestamp) as prev_ts
  FROM candles_backfill WHERE symbol = 'BTCUSDT' AND interval = '1d'
)
SELECT * FROM gaps WHERE timestamp - prev_ts > INTERVAL '2 days';
```

Report findings clearly — any issues block Track B and C.

## Estimated Complexity
Low — query-based validation.
