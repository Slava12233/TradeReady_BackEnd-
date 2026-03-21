---
type: plan
title: "Implementation Plan: Periodic Market Data Gap-Fill Task"
status: archived
phase: data-pipeline
tags:
  - plan
  - data-pipeline
---

# Implementation Plan: Periodic Market Data Gap-Fill Task

## Context

The live price ingestion service streams ticks from Binance WebSocket into TimescaleDB, which auto-aggregates them into candle views (`candles_1m/5m/1h/1d`). If the ingestion service has any downtime (deploy, crash, restart), those ticks are lost permanently — resulting in missing or incomplete candles. There is currently **no mechanism** to detect or recover from these gaps.

This task adds an automatic safety net: a Celery periodic task that runs every 4 hours, detects gaps in 1h candle data, and fills them from Binance REST API into the existing `candles_backfill` table. Since the `DataReplayer` already UNIONs both tables in every query, filled gaps become immediately available to backtesting and live trading — **zero schema changes, zero migrations needed**.

---

## Implementation Steps

### Step 1: Create `src/tasks/binance_helpers.py`

Extract shared Binance API helpers from `scripts/backfill_history.py` into a reusable module:

| Function | Source | Purpose |
|----------|--------|---------|
| `fetch_klines_page()` | `backfill_history.py:67-105` | Fetch one page (up to 1000 candles) from Binance REST with retry/backoff |
| `fetch_top_volume_symbols()` | `backfill_history.py:108-116` | Get top N USDT pairs by 24h volume |
| `kline_to_row()` | New helper | Convert raw Binance kline array to dict for DB insert |
| `UPSERT_SQL` | `backfill_history.py:55-59` | `INSERT INTO candles_backfill ... ON CONFLICT DO NOTHING` |

Constants: `BINANCE_KLINES_URL`, `MAX_CANDLES_PER_REQUEST=1000`, `MAX_RETRIES=3`, `INITIAL_BACKOFF=1.0`

### Step 2: Create `src/tasks/gap_fill.py`

New Celery task following the exact pattern from `src/tasks/backtest_cleanup.py`.

**Task signature:**
```python
@app.task(name="src.tasks.gap_fill.fill_candle_gaps",
          bind=True, max_retries=0, soft_time_limit=580, time_limit=600)
def fill_candle_gaps(self) -> dict:
    return asyncio.run(_run_gap_fill())
```

**Async workflow (`_run_gap_fill`):**

1. **Get target symbols** — Intersect our `trading_pairs` table with Binance top N by volume (configurable via `GAP_FILL_TOP_PAIRS`, default 50)

2. **Detect gaps** — Single efficient query:
   ```sql
   SELECT symbol, MAX(bucket) AS latest
   FROM candles_backfill
   WHERE interval = '1h' AND symbol = ANY(:symbols)
   GROUP BY symbol
   ```
   Any symbol whose latest bucket is >2 hours old has a gap.

3. **Fill gaps** — For each gapped symbol:
   - Paginate through Binance `GET /api/v3/klines` (1h interval)
   - Batch-insert into `candles_backfill` using `ON CONFLICT DO NOTHING`
   - Rate limit: 150ms between API pages

4. **Return summary:**
   ```json
   {
     "symbols_checked": 50,
     "symbols_with_gaps": 3,
     "symbols_filled": 3,
     "symbols_failed": 0,
     "candles_inserted": 72,
     "duration_ms": 4500
   }
   ```

**Safety caps:**
- Max gap per run: **7 days** (168 hours). Larger gaps → use manual `scripts/backfill_history.py`
- Sequential symbol processing (no parallel fetches) — simple and within Binance rate limits
- 10-minute hard timeout on the Celery task

### Step 3: Add config to `src/config.py`

```python
# After grafana_admin_password (line 84)
gap_fill_top_pairs: int = Field(
    default=50, ge=5, le=200,
    description="Number of top-volume USDT pairs to check for data gaps.",
)
```

### Step 4: Register in `src/tasks/celery_app.py`

Add to `include` list:
```python
"src.tasks.gap_fill",
```

Add to `beat_schedule`:
```python
"fill-candle-gaps": {
    "task": "src.tasks.gap_fill.fill_candle_gaps",
    "schedule": crontab(minute=30, hour="*/4"),  # 00:30, 04:30, 08:30, ...
},
```

### Step 5: Update `.env.example`

```
GAP_FILL_TOP_PAIRS=50
```

### Step 6: Create unit tests `tests/unit/test_gap_fill.py`

| Test | What it verifies |
|------|------------------|
| `test_detect_gaps_finds_stale_symbols` | Symbols with old MAX(bucket) are flagged |
| `test_detect_gaps_skips_current_symbols` | Recent symbols are not flagged |
| `test_detect_gaps_caps_max_gap` | Gap start capped to 7 days |
| `test_get_target_symbols_intersects_with_db` | Only symbols in both Binance top list and our DB |
| `test_get_target_symbols_fallback_on_error` | Falls back to major pairs if Binance API fails |
| `test_fill_symbol_gap_inserts_klines` | Fetched klines are batch-inserted |
| `test_fill_symbol_gap_handles_empty_response` | Returns 0 on empty Binance response |
| `test_kline_to_row_converts_correctly` | Raw kline → dict with Decimals |
| `test_fill_candle_gaps_returns_summary` | Full task returns expected dict shape |

### Step 7: Lint & type check

```bash
ruff check src/tasks/gap_fill.py src/tasks/binance_helpers.py tests/unit/test_gap_fill.py
mypy src/tasks/gap_fill.py src/tasks/binance_helpers.py
pytest tests/unit/test_gap_fill.py -v
```

---

## Files Summary

### New Files
| File | Purpose |
|------|---------|
| `src/tasks/binance_helpers.py` | Shared Binance REST API helpers (fetch klines, top symbols, upsert SQL) |
| `src/tasks/gap_fill.py` | Celery periodic task: detect and fill candle gaps |
| `tests/unit/test_gap_fill.py` | Unit tests with mocked DB/HTTP |

### Modified Files
| File | Change |
|------|--------|
| `src/tasks/celery_app.py` | Add to `include` list + beat schedule entry |
| `src/config.py` | Add `gap_fill_top_pairs` setting |
| `.env.example` | Add `GAP_FILL_TOP_PAIRS` |

### No Changes Needed
| File | Why |
|------|-----|
| Database migrations | `candles_backfill` table already exists with correct schema/constraints |
| `src/backtesting/data_replayer.py` | Already UNIONs `candles_backfill` — gap data is auto-available |
| `scripts/backfill_history.py` | Stays as-is (manual script). Helpers extracted, not moved. |

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│               Normal Flow (always running)           │
│  Binance WS → ticks → TimescaleDB continuous aggs   │
│  (candles_1m, candles_5m, candles_1h, candles_1d)    │
└─────────────────────────────────────────────────────┘
                         │
                    gaps happen
                    (downtime)
                         │
┌─────────────────────────────────────────────────────┐
│            Gap-Fill Task (NEW, every 4h)             │
│                                                      │
│  1. Query MAX(bucket) per symbol in candles_backfill │
│  2. Find symbols with stale data (>2h old)           │
│  3. Fetch missing 1h klines from Binance REST API    │
│  4. INSERT INTO candles_backfill ON CONFLICT DO NOTHING│
│                                                      │
│  DataReplayer UNIONs candles_1m + candles_backfill   │
│  → gaps filled seamlessly, zero code changes needed  │
└─────────────────────────────────────────────────────┘
```

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Binance rate limits | 150ms between pages, top 50 pairs only, sequential processing. Uses ~7 req/s vs 1200/min limit. |
| Large gaps after extended downtime | Capped at 7 days. Longer gaps → manual `backfill_history.py` |
| Task timeout | 10-min hard limit. Worst case: 50 symbols × 7-day gap × 7 pages = ~350 API calls at 150ms = ~52s total |
| Duplicate inserts | `ON CONFLICT DO NOTHING` on unique constraint `(symbol, interval, bucket)` — idempotent |
| Celery worker/beat not running | Same risk as all existing periodic tasks. No new dependency. |

---

## Deployment

1. Merge code
2. Restart Celery worker (`celery -A src.tasks.celery_app worker`)
3. Restart Celery beat (`celery -A src.tasks.celery_app beat`)
4. Task auto-runs on next 4-hour window (e.g., 00:30, 04:30, 08:30 UTC)
5. Monitor logs for `gap_fill.finished` entries
6. No database migration needed
