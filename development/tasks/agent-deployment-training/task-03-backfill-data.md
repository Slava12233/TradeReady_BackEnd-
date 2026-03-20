---
task_id: 03
title: "Backfill historical data & validate coverage"
agent: "e2e-tester"
phase: 3
depends_on: [2]
status: "completed"
priority: "high"
files: []
---

# Task 03: Backfill historical data & validate coverage

## Assigned Agent: `e2e-tester`

## Objective
Load 12+ months of 1h candle data for training assets and validate coverage meets 95% threshold.

## Steps
1. Run backfill script:
   ```bash
   python scripts/backfill_history.py \
     --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT \
     --interval 1h \
     --start 2024-01-01
   ```
2. Validate data coverage:
   ```bash
   python -m agent.strategies.rl.data_prep \
     --base-url http://localhost:8000 \
     --api-key ak_live_YOUR_KEY \
     --assets BTCUSDT,ETHUSDT,SOLUSDT \
     --interval 1h \
     --min-coverage 95
   ```
3. Verify exit code 0 (sufficient coverage)

## Acceptance Criteria
- [ ] Backfill completes without errors for all 5 symbols
- [ ] Data validation shows 95%+ coverage for train/val/test splits
- [ ] Date range covers 2024-01-01 through latest available
- [ ] `data_prep.py` exits with code 0

## Dependencies
- Task 02: platform running with healthy API

## Agent Instructions
Backfill takes 10-30 minutes depending on Binance API rate limits. If rate-limited, the script handles retries. Check `scripts/CLAUDE.md` for script details. The data_prep validation uses the API key from `agent/.env`.

## Estimated Complexity
Low — running existing scripts and verifying output.
