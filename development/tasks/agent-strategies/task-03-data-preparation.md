---
task_id: 03
title: "Data preparation & validation script"
type: task
agent: "ml-engineer"
phase: A
depends_on: [1]
status: "completed"
board: "[[agent-strategies/README]]"
priority: "high"
files: ["agent/strategies/rl/data_prep.py"]
tags:
  - task
  - ml
  - strategies
---

# Task 03: Data preparation & validation script

## Assigned Agent: `ml-engineer`

## Objective
Create a script that validates historical data availability for RL training: checks candle coverage for all 5 assets across the train/val/test date ranges, identifies gaps, and reports readiness.

## Context
RL training requires continuous OHLCV data. If there are gaps (missing candles), episodes will fail mid-training. We need to validate data before starting the expensive training run.

## Files to Create
- `agent/strategies/rl/data_prep.py`:
  - Query `GET /api/v1/market/data-range` to find available data window
  - For each asset in universe, check candle count vs expected count
  - Flag gaps (missing candles > threshold)
  - Compute train/val/test splits based on available range (8/2/2 ratio)
  - Output: DataReadiness report (Pydantic model) with per-asset coverage %
  - CLI: `python -m agent.strategies.rl.data_prep --base-url http://localhost:8000 --api-key ak_live_...`

## Acceptance Criteria
- [ ] Script queries data range from platform API
- [ ] Reports coverage % per asset per split (train/val/test)
- [ ] Exits with error code if any asset has < 95% coverage
- [ ] Prints recommended date ranges for train/val/test splits
- [ ] Output is JSON-serializable (Pydantic model with `.model_dump_json()`)
- [ ] Works with both 1m and 1h candle intervals

## Dependencies
- Task 01 output: understanding of data sources (candles_backfill vs candles_1m)
- Platform running with historical data loaded (`scripts/backfill_history.py`)

## Agent Instructions
Use `httpx.AsyncClient` for API calls (same pattern as `agent/tools/rest_tools.py`). The data range endpoint returns `{earliest, latest}` per pair — use this to compute expected candle count.

## Estimated Complexity
Low — mostly API queries and arithmetic.
