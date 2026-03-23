---
task_id: 02
title: "Seed trading pairs and backfill 12 months historical data"
type: task
agent: "e2e-tester"
phase: 0
depends_on: [1]
status: "completed"
priority: "high"
board: "[[trading-agent-master-plan/README]]"
files: ["scripts/seed_pairs.py", "scripts/backfill_history.py"]
tags:
  - task
  - data
  - foundation
---

# Task 02: Seed trading pairs and backfill historical data

## Assigned Agent: `e2e-tester`

## Objective
Seed 600+ USDT trading pairs from Binance and backfill 12+ months of 1-minute OHLCV candle data into TimescaleDB. Then validate data coverage for the RL training pipeline.

## Context
All ML strategies require historical candle data to train. The PPO RL agent needs at minimum 10 months of training data, 2 months validation, and 1 month test. The evolutionary strategy needs 7+ days per battle. Without this data, no training can happen.

## Steps
1. Run `python scripts/seed_pairs.py` — seeds `trading_pairs` table from Binance
2. Run `python scripts/backfill_history.py` — downloads 1-minute candles into `candles_backfill` table
3. Validate: `python -m agent.strategies.rl.data_prep --base-url http://localhost:8000 --assets BTCUSDT ETHUSDT SOLUSDT`
4. Verify >95% coverage for all three splits (train/val/test)

## Acceptance Criteria
- [ ] `trading_pairs` table has 600+ USDT pairs
- [ ] `candles_backfill` table has 12+ months of 1-minute data for BTC, ETH, SOL
- [ ] Data prep validation reports >95% coverage for all splits
- [ ] `GET /api/v1/market/data-range` returns valid date range

## Estimated Complexity
Medium — data download takes time but scripts exist. May need to handle Binance rate limits.
