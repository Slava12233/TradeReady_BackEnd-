# Market Data Gap-Fill: Continuous Backfill Task

## Problem

Our market data pipeline has a single point of failure:

```
Binance WebSocket → ticks → continuous aggregates (candles_1m/5m/1h/1d)
```

If the ingestion service goes down for **any reason** (deploy, crash, server restart, network issue), we lose raw ticks during that window. TimescaleDB continuous aggregates can only build candles from ticks that exist — **missing ticks = missing or incomplete candles**.

We have no mechanism to detect or recover from these gaps automatically.

### Impact

- **Backtesting accuracy**: Gaps in candle data produce unreliable backtest results. An agent might see a price jump from $60k to $62k when in reality there were 30 minutes of gradual movement in between.
- **Live trading signals**: Any strategy relying on candle history (moving averages, RSI, MACD) will compute incorrect values over gap periods.
- **Data integrity**: Over time, accumulated gaps degrade confidence in the entire dataset.

## Current State

| Component | Status |
|-----------|--------|
| Live ingestion (WebSocket → ticks → candles) | Running, but no gap recovery |
| Historical backfill script (`backfill_history.py`) | Manual, one-time use only |
| Gap detection | None |
| Automated gap recovery | None |

## Proposed Solution

Add a **Celery periodic task** that runs on a schedule (e.g., every 5-15 minutes) and:

1. **Detects gaps** — For each active trading pair, compare the latest candle timestamp in the DB against the current time. If the gap exceeds the expected interval + tolerance, flag it.
2. **Fetches missing klines** — Pull the missing candles from Binance REST API (`GET /api/v3/klines`), which is free, requires no API key, and returns up to 1000 candles per request.
3. **Inserts into `candles_backfill`** — Uses the existing table with its `ON CONFLICT DO NOTHING` upsert (unique constraint on `symbol, interval, bucket` prevents duplicates).

### Architecture

```
┌──────────────────────────────────────────────────┐
│                  Normal Flow                      │
│  Binance WS → ticks → continuous aggregates       │
│  (candles_1m, candles_5m, candles_1h, candles_1d) │
└──────────────────────────────────────────────────┘
                        │
                   gaps happen
                        │
┌──────────────────────────────────────────────────┐
│               Gap-Fill Task (NEW)                 │
│  Celery Beat (every 15 min)                       │
│    → detect gaps in candles_1m / candles_1h       │
│    → fetch missing klines from Binance REST       │
│    → insert into candles_backfill                 │
│                                                   │
│  DataReplayer already UNIONs candles_1m +          │
│  candles_backfill, so gaps are filled seamlessly   │
└──────────────────────────────────────────────────┘
```

### Why `candles_backfill`?

We don't need to touch `candles_1m` or the continuous aggregates. The `DataReplayer` already UNIONs `candles_*` with `candles_backfill` in every query. By inserting gap data into `candles_backfill`, it becomes immediately available to both backtesting and live trading queries — zero schema changes, zero migration needed.

## Scope of Work

| Task | Effort |
|------|--------|
| Gap detection query (find missing intervals per symbol) | Small |
| Celery periodic task wired to Celery Beat schedule | Small |
| Reuse existing Binance REST fetch logic from `backfill_history.py` | Small |
| Batch upsert into `candles_backfill` | Already exists |
| Monitoring: log/metric for gaps detected and filled | Small |
| Tests: unit + integration | Medium |

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `GAP_FILL_INTERVAL_MINUTES` | 15 | How often the task runs |
| `GAP_FILL_LOOKBACK_HOURS` | 24 | How far back to check for gaps |
| `GAP_FILL_PAIRS` | top 100 by volume | Which pairs to monitor |
| `GAP_FILL_CANDLE_INTERVAL` | `1h` | Which candle interval to gap-fill |

## Risks & Considerations

- **Binance rate limits**: REST API allows 1200 requests/minute. Gap-filling 100 pairs at 1h interval requires at most 100 requests per run — well within limits.
- **Duplicate data**: The unique constraint on `candles_backfill` (`symbol, interval, bucket`) prevents duplicates. Upserts are safe to run repeatedly.
- **Not a replacement for live ingestion**: This is a safety net, not a primary data source. Live ingestion remains the primary path for real-time data.
- **Celery dependency**: Requires Celery worker + Beat to be running. Already a dependency for order matching and backtest cleanup.

## Decision Needed

1. **Which candle intervals to gap-fill?**
   - Option A: `1h` only (simplest, covers most strategy needs)
   - Option B: `1m` + `1h` (more complete, but 60x more Binance API calls)
   - Option C: `1m` + `5m` + `1h` + `1d` (full coverage, highest API usage)

2. **Which pairs to monitor?**
   - Option A: Top 100 by 24h volume (practical)
   - Option B: All 600+ pairs (thorough, but higher API load)

3. **Priority**: Is this a blocker for anything currently in progress, or can it be scheduled into the next sprint?
