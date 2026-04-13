---
task_id: A-02
title: "Refresh trading pairs"
type: task
agent: "backend-developer"
track: A
depends_on: ["A-01"]
status: "pending"
priority: "high"
board: "[[april-2026-execution/README]]"
files: ["scripts/seed_pairs.py"]
tags:
  - task
  - data
  - exchange
---

# Task A-02: Refresh trading pairs

## Assigned Agent: `backend-developer`

## Objective
Run `seed_pairs.py` to refresh the trading pairs table with current Binance USDT listings.

## Context
The backfill scripts need up-to-date trading pair entries in the database. `seed_pairs.py` fetches all USDT pairs from Binance and upserts them.

## Files to Use
- `scripts/seed_pairs.py` — pair seeding script

## Acceptance Criteria
- [ ] `seed_pairs.py` runs without errors
- [ ] Trading pairs table contains BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT and the other 15 target pairs
- [ ] No duplicate entries created

## Dependencies
- **A-01**: Docker services must be running (TimescaleDB accessible)

## Agent Instructions
Run `python scripts/seed_pairs.py`. Verify output shows pairs were inserted/updated. Query the `trading_pairs` table to confirm the 20 target pairs exist: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, ADAUSDT, AVAXUSDT, DOTUSDT, LINKUSDT, MATICUSDT, SHIBUSDT, LTCUSDT, UNIUSDT, ATOMUSDT, NEARUSDT, AAVEUSDT, ARBUSDT, OPUSDT, APTUSDT.

## Estimated Complexity
Low — running an existing script.
