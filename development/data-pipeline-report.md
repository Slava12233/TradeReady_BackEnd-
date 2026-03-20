# TradeReady Data Pipeline: Complete A-Z Report
## How Data Flows from Binance to Every Consumer

---

## Table of Contents

1. [Executive Summary: The 30-Second Picture](#1-executive-summary)
2. [The Two Data Worlds](#2-the-two-data-worlds)
3. [All the Storage Systems (Where Data Lives)](#3-storage-systems)
4. [Data Source 1: Live Binance WebSocket](#4-live-binance-websocket)
5. [Data Source 2: CCXT Exchange Abstraction](#5-ccxt-exchange-abstraction)
6. [Data Source 3: Historical Backfill (Since 2013)](#6-historical-backfill)
7. [The Ingestion Service: Tick by Tick](#7-the-ingestion-service)
8. [Redis: The Real-Time Brain](#8-redis)
9. [TimescaleDB: The Historical Memory](#9-timescaledb)
10. [How Every Consumer Reads Data](#10-how-consumers-read-data)
11. [The Backtesting Data Path (Completely Separate)](#11-backtesting-data-path)
12. [WebSocket: Real-Time to the Frontend](#12-websocket-to-frontend)
13. [Complete Data Flow Diagrams](#13-data-flow-diagrams)
14. [When Does the System Use What?](#14-when-system-uses-what)
15. [The Complete Picture: Every Table, Key, and Channel](#15-complete-picture)
16. [Common Confusion Points Explained](#16-confusion-points)

---

## 1. Executive Summary: The 30-Second Picture

```
BINANCE (or any exchange)
    │
    │  WebSocket: real-time trade ticks (~1000/sec)
    ▼
┌──────────────────────────────┐
│  INGESTION SERVICE            │
│  (python -m src.price_ingestion.service)
│                               │
│  For EACH tick:               │
│    1. Write to Redis (instant)│  ← current prices, always fresh
│    2. Buffer in memory        │
│                               │
│  Every 1 second (or 5000 ticks):
│    3. Flush buffer to TimescaleDB (bulk COPY)
│    4. Broadcast to Redis pub/sub
└──────────────────────────────┘
         │                │
         ▼                ▼
    ┌─────────┐    ┌──────────────┐
    │  REDIS  │    │ TIMESCALEDB  │
    │ (fast)  │    │  (forever)   │
    └────┬────┘    └──────┬───────┘
         │                │
    Live consumers    Historical consumers
    (orders, risk,    (backtesting, candles,
     portfolio,        analytics, charts)
     WebSocket)
```

**That's it.** Everything else is details about HOW data gets into these two stores and HOW it gets read out.

---

## 2. The Two Data Worlds

The platform has **two completely separate data planes** that almost never cross:

### World 1: Live (Redis)

```
Purpose:    "What is the price RIGHT NOW?"
Latency:    < 1 millisecond
Data age:   < 1 second old
Storage:    Redis in-memory hash maps
Written by: Ingestion service (every tick)
Read by:    Order engine, risk manager, portfolio tracker,
            WebSocket clients, battle snapshots, market API
```

### World 2: Historical (TimescaleDB)

```
Purpose:    "What was the price at any point in history?"
Latency:    1-100 milliseconds (DB query)
Data age:   From 2013 to now
Storage:    TimescaleDB hypertables + continuous aggregates
Written by: Ingestion service (bulk flush) + backfill scripts
Read by:    Backtesting engine, candle endpoints, analytics,
            performance metrics, charts
```

### The Only Place They Meet

The `GET /api/v1/market/candles/{symbol}` endpoint queries TimescaleDB continuous aggregates first, then falls back to the Binance REST API if local data is thin. That's the only crossover point.

---

## 3. All the Storage Systems (Where Data Lives)

### Redis (In-Memory, Real-Time)

| What | Redis Key | Type | Updated By | Read By |
|------|-----------|------|-----------|---------|
| Current price per symbol | `prices` (Hash) | `HSET prices BTCUSDT "64521.30"` | Ingestion (every tick) | Order engine, risk, portfolio, market API |
| Price timestamp per symbol | `prices:meta` (Hash) | `HSET prices:meta BTCUSDT "2026-03-19T..."` | Ingestion (every tick) | Staleness detection, monitoring |
| 24h ticker stats | `ticker:{SYMBOL}` (Hash) | Fields: open,high,low,close,volume,change_pct | Ingestion (Lua script, every tick) | Slippage calculator, ticker API |
| Real-time tick broadcast | `price_updates` (Pub/Sub) | JSON per tick batch | Ingestion (every flush) | WebSocket bridge → frontend |
| Rate limit counters | `rate_limit:{key}:{endpoint}:{minute}` | Counter + TTL | Rate limit middleware | Rate limit middleware |
| Circuit breaker state | `circuit_breaker:{account_id}` | Hash: daily_pnl, tripped | Risk manager | Risk manager |

### TimescaleDB (Persistent, Historical)

| Table/View | Type | Data | Written By | Read By |
|------------|------|------|-----------|---------|
| `ticks` | Hypertable (1h chunks) | Every trade tick: time, symbol, price, qty, trade_id | Ingestion (asyncpg COPY) | Tick repo, candle aggregates, trade history |
| `candles_1m` | Continuous Aggregate | 1-minute OHLCV from ticks | Auto-materialized by TimescaleDB every 1 min | Market candles API, DataReplayer |
| `candles_5m` | Continuous Aggregate | 5-minute OHLCV from ticks | Auto-materialized every 5 min | Market candles API |
| `candles_1h` | Continuous Aggregate | 1-hour OHLCV from ticks | Auto-materialized every 1 hour | Market candles API, analytics |
| `candles_1d` | Continuous Aggregate | 1-day OHLCV from ticks | Auto-materialized every 1 day | Market candles API, analytics |
| `candles_backfill` | Hypertable (1mo chunks) | Historical Binance klines (pre-ingestion) | `scripts/backfill_history.py` | DataReplayer (backtesting) |
| `trading_pairs` | Regular table | 600+ pair metadata (min_qty, step_size, etc.) | `scripts/seed_pairs.py` | Order validation, market pairs API |
| `portfolio_snapshots` | Hypertable | Equity snapshots every 1min/1h/1d | Celery snapshot tasks | Performance metrics, equity charts |

---

## 4. Data Source 1: Live Binance WebSocket

### What It Is

A direct WebSocket connection to Binance's real-time trade stream. Every time anyone on Binance executes a trade (buy or sell), we receive a message within milliseconds.

### How It Connects

```
Our Server
    │
    │ WebSocket connection to:
    │ wss://stream.binance.com:9443/stream?streams=btcusdt@trade/ethusdt@trade/...
    │
    │ Up to 1024 streams per connection
    │ ~600 USDT pairs = 1 connection is enough
    │
    ▼
Binance Server
```

### What We Receive (Per Trade)

```json
{
  "stream": "btcusdt@trade",
  "data": {
    "e": "trade",
    "s": "BTCUSDT",
    "p": "64521.30",        // price
    "q": "0.012",           // quantity
    "T": 1708000000000,     // timestamp (ms)
    "m": false,             // is buyer the maker?
    "t": 123456789          // trade ID
  }
}
```

### Parsed Into

```python
Tick(
    symbol="BTCUSDT",
    price=Decimal("64521.30"),
    quantity=Decimal("0.012"),
    timestamp=datetime(2024, 2, 15, 12, 0, 0, tzinfo=UTC),
    is_buyer_maker=False,
    trade_id=123456789
)
```

### The Code

**File:** `src/price_ingestion/binance_ws.py` — `BinanceWebSocketClient`

1. `fetch_pairs()` — GET `https://api.binance.com/api/v3/exchangeInfo`, filters for `status="TRADING"` AND `quoteAsset="USDT"` → ~600+ symbols
2. `_build_stream_urls(symbols)` — builds `wss://stream.binance.com:9443/stream?streams=btcusdt@trade/ethusdt@trade/...`
3. `listen()` — creates an asyncio Queue (max 50,000), spawns one task per WebSocket URL running `_connection_loop`
4. `_connection_loop()` — connects with `websockets.connect(url, ping_interval=20)`, reads messages in a loop
5. `_parse_message()` — extracts the Tick from JSON

### Reconnection

```
On connection lost → wait 1s → reconnect
On second failure  → wait 2s → reconnect
On third failure   → wait 4s → reconnect
...doubles up to max 60s...
On successful connect → reset to 1s
```

This runs forever until the service is shut down with SIGINT/SIGTERM.

---

## 5. Data Source 2: CCXT Exchange Abstraction

### What It Is

CCXT is a universal library that supports **110+ cryptocurrency exchanges** with a single API. Instead of writing custom code for Binance, OKX, Bybit, etc., we use CCXT as a translation layer.

### Why We Have BOTH Binance Direct AND CCXT

```
BINANCE DIRECT (Legacy)              CCXT (New, Universal)
├─ Faster for Binance specifically   ├─ Works with ANY exchange
├─ No extra dependency               ├─ Requires ccxt + ccxt.pro packages
├─ Battle-tested                     ├─ Automatic symbol mapping
└─ Only works with Binance           └─ WebSocket + REST support

SELECTION LOGIC (in service.py):
  if EXCHANGE_ID == "binance":
      try CCXT first → fall back to Binance Direct on error
  else:
      CCXT only (no fallback)
```

### The Exchange Adapter Pattern

```
                         ┌──────────────────────┐
                         │  ExchangeAdapter      │ (Abstract Base)
                         │  ─────────────────    │
                         │  fetch_markets()       │
                         │  fetch_ticker()        │
                         │  fetch_ohlcv()         │
                         │  watch_trades()        │ ← WebSocket
                         │  create_order()        │
                         │  cancel_order()        │
                         └──────────┬─────────────┘
                                    │
                         ┌──────────▼─────────────┐
                         │  CCXTAdapter            │ (Concrete)
                         │  ─────────────────      │
                         │  _rest_exchange (lazy)   │ ← ccxt.async_support.binance()
                         │  _ws_exchange (lazy)     │ ← ccxt.pro.binance()
                         │  _mapper: SymbolMapper   │
                         └──────────────────────────┘
```

### Symbol Mapping

Binance uses `BTCUSDT`. CCXT uses `BTC/USDT`. The `SymbolMapper` translates:

```
Platform Format     CCXT Format
───────────────     ───────────
BTCUSDT         ↔   BTC/USDT
ETHUSDT         ↔   ETH/USDT
SOLUSDT         ↔   SOL/USDT
```

Built from `exchange.markets` at initialization. Heuristic fallback strips known quote assets (USDT, BUSD, USDC, etc.) for unlisted pairs.

### CCXT WebSocket Client

**File:** `src/price_ingestion/exchange_ws.py` — `ExchangeWebSocketClient`

```python
# How it works internally:
adapter = CCXTAdapter("binance")
await adapter.initialize()  # loads markets, builds symbol map
markets = await adapter.fetch_markets("USDT")  # ~600 pairs

# WebSocket streaming:
async for tick in adapter.watch_trades(symbols):
    yield _to_tick(tick)  # ExchangeTick → Tick conversion
```

If the exchange doesn't support CCXT Pro WebSocket (rare), it falls back to REST polling every 100ms per symbol (round-robin).

### The Key Files

| File | What It Does |
|------|-------------|
| `src/exchange/adapter.py` | Abstract base class defining the interface |
| `src/exchange/ccxt_adapter.py` | CCXT implementation — REST + WebSocket |
| `src/exchange/symbol_mapper.py` | `BTCUSDT` ↔ `BTC/USDT` translation |
| `src/exchange/types.py` | `ExchangeTick`, `ExchangeCandle`, `ExchangeMarket` dataclasses |
| `src/exchange/factory.py` | `create_adapter()` factory, reads settings |

---

## 6. Data Source 3: Historical Backfill (Since 2013)

### What It Is

Binance has historical kline (candlestick) data going back to when each pair was listed. BTC/USDT has data from ~2017. Some pairs go back further on other exchanges. The backfill script downloads this historical data and loads it into TimescaleDB.

### How It Works

**File:** `scripts/backfill_history.py`

```
1. Choose symbols (--all for all 600+ USDT pairs, or specify)
2. Choose intervals (1m, 5m, 1h, 1d)
3. Choose date range (--start "2020-01-01" --end "2024-12-31")

For each symbol × interval:
    Loop:
        GET https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=1000&startTime=...
        Parse response → list of candle dicts
        Batch INSERT INTO candles_backfill ... ON CONFLICT DO NOTHING
        Move startTime forward by 1000 candles
        (respects Binance rate limits with retry/backoff on HTTP 429)
```

### What Gets Stored

```sql
INSERT INTO candles_backfill (bucket, symbol, interval, open, high, low, close, volume, trade_count)
VALUES
  ('2024-01-01 00:00:00+00', 'BTCUSDT', '1h', 42150.00, 42300.00, 42050.00, 42200.00, 1234.56, 45678),
  ('2024-01-01 01:00:00+00', 'BTCUSDT', '1h', 42200.00, 42400.00, 42100.00, 42350.00, 987.65, 34567),
  ...
ON CONFLICT (symbol, interval, bucket) DO NOTHING
```

### For Non-Binance Exchanges

```python
# Uses CCXT instead of Binance REST
adapter = CCXTAdapter("okx")
await adapter.initialize()
candles = await adapter.fetch_ohlcv("BTCUSDT", timeframe="1h", since=start_ms, limit=500)
# Same INSERT INTO candles_backfill ...
```

### The `candles_backfill` Table

```
┌─────────────────────────────────────────────────────────────┐
│  candles_backfill (TimescaleDB Hypertable)                  │
│  Partitioned by: bucket (1-month chunks)                    │
│  Compressed after: 90 days                                  │
├─────────────────────────────────────────────────────────────┤
│  bucket      │ symbol   │ interval │ open    │ high    │    │
│  (timestamp) │ (text)   │ (text)   │ (num)   │ (num)   │ ...│
├──────────────┼──────────┼──────────┼─────────┼─────────┤    │
│  2020-01-01  │ BTCUSDT  │ 1d       │ 7200.00 │ 7500.00 │    │
│  2020-01-01  │ BTCUSDT  │ 1h       │ 7200.00 │ 7250.00 │    │
│  2020-01-01  │ BTCUSDT  │ 1m       │ 7200.00 │ 7205.00 │    │
│  2020-01-01  │ ETHUSDT  │ 1d       │  130.00 │  135.00 │    │
│  ...         │ ...      │ ...      │ ...     │ ...     │    │
└─────────────────────────────────────────────────────────────┘

Unique constraint: (symbol, interval, bucket)
This prevents duplicate candles on re-runs (ON CONFLICT DO NOTHING)
```

### Also: `scripts/seed_pairs.py`

Populates the `trading_pairs` table with pair metadata:

```
GET https://api.binance.com/api/v3/exchangeInfo
    → For each USDT trading pair:
        INSERT INTO trading_pairs (symbol, base_asset, quote_asset, min_qty, max_qty, step_size, min_notional)
        ON CONFLICT (symbol) DO UPDATE SET ...
```

This is needed so the order engine knows the minimum order size, step size, etc. for each pair.

---

## 7. The Ingestion Service: Tick by Tick

### What It Is

A standalone Python process that runs 24/7, streaming ticks from the exchange and feeding them into Redis + TimescaleDB.

```bash
# How to run it:
python -m src.price_ingestion.service

# Or via Docker:
docker compose up ingestion
```

### Startup Sequence

```
1. Load settings (.env)
2. Initialize TimescaleDB connection pool (asyncpg)
3. Initialize Redis connection pool
4. Create PriceCache (Redis wrapper)
5. Create PriceBroadcaster (Redis pub/sub publisher)
6. Create TickBuffer (in-memory buffer → DB writer)
7. Select tick source:
   ├─ EXCHANGE_ID=binance → try CCXT, fallback to direct Binance WS
   └─ EXCHANGE_ID=okx     → CCXT only
8. Fetch pair list from exchange
9. Connect WebSocket
10. Start periodic flush background task (every 1s)
11. Enter main loop: process ticks one by one
```

### The Main Loop (What Happens Per Tick)

```python
# Simplified from service.py:run()

async for tick in tick_source:  # Each tick from Binance WebSocket
    if _shutdown_requested:
        break

    # Step 1: Update Redis IMMEDIATELY (sub-millisecond)
    await price_cache.set_price(tick.symbol, tick.price, tick.timestamp)
    #   → HSET prices BTCUSDT "64521.30000000"
    #   → HSET prices:meta BTCUSDT "2026-03-19T12:00:00.123+00:00"

    # Step 2: Update 24h ticker stats (Lua script, atomic)
    await price_cache.update_ticker(tick)
    #   → EVALSHA ticker_update_script ticker:BTCUSDT ...
    #   → Updates: high = max(high, price), low = min(low, price),
    #              close = price, volume += quantity, change_pct recalculated

    # Step 3: Buffer the tick in memory
    await buffer.add(tick)
    #   → Appends to list. If list >= 5000: triggers immediate flush
```

### The Flush (Every 1 Second or 5000 Ticks)

```python
# TickBuffer._write_batch()

# Convert ticks to tuples
records = [(t.timestamp, t.symbol, t.price, t.quantity, t.is_buyer_maker, t.trade_id) for t in batch]

# Bulk write to TimescaleDB using asyncpg COPY (10-50x faster than INSERT)
async with pool.acquire() as conn:
    await conn.copy_records_to_table("ticks", records=records, columns=[...])

# Broadcast to Redis pub/sub for WebSocket clients
await broadcaster.broadcast_batch(batch)
#   → PUBLISH price_updates {"symbol":"BTCUSDT","price":"64521.30",...}
#   → One PUBLISH per tick, all in a single Redis pipeline (one TCP round-trip)
```

### Visual Timeline

```
Time ─────────────────────────────────────────────────────────────►

Tick 1 arrives (BTCUSDT trade)
  ├─ Redis: HSET prices BTCUSDT "64521.30"          ← INSTANT
  ├─ Redis: EVALSHA ticker_lua ticker:BTCUSDT        ← INSTANT
  └─ Memory: buffer.append(tick1)                    ← INSTANT

Tick 2 arrives (ETHUSDT trade) ... 50ms later
  ├─ Redis: HSET prices ETHUSDT "3200.15"
  ├─ Redis: EVALSHA ticker_lua ticker:ETHUSDT
  └─ Memory: buffer.append(tick2)

... hundreds more ticks arrive over the next second ...

1 SECOND TIMER FIRES (or buffer hits 5000 ticks)
  ├─ TimescaleDB: COPY 847 rows INTO ticks           ← BULK WRITE
  └─ Redis: PUBLISH price_updates × 847 messages     ← BROADCAST
       └─ WebSocket bridge picks these up
            └─ Fans out to all subscribed frontend clients

Next second: repeat
```

---

## 8. Redis: The Real-Time Brain

### What Redis Stores

Redis is the **speed layer**. It answers the question: "What is happening RIGHT NOW?"

```
┌──────────────────────────────────────────────────────────────┐
│                        REDIS                                  │
│                                                               │
│  HASH: prices                                                 │
│  ┌───────────┬──────────────────┐                            │
│  │ BTCUSDT   │ "64521.30000000" │  ← Updated every tick     │
│  │ ETHUSDT   │ "3200.15000000"  │     (~1000+ times/sec     │
│  │ SOLUSDT   │ "142.80000000"   │      across all pairs)    │
│  │ BNBUSDT   │ "580.20000000"   │                            │
│  │ ... (600+ fields)            │                            │
│  └───────────┴──────────────────┘                            │
│                                                               │
│  HASH: prices:meta                                            │
│  ┌───────────┬──────────────────────────────────┐            │
│  │ BTCUSDT   │ "2026-03-19T12:00:00.123+00:00" │            │
│  │ ETHUSDT   │ "2026-03-19T12:00:00.089+00:00" │            │
│  │ ...       │ (ISO-8601 timestamp of last tick) │            │
│  └───────────┴──────────────────────────────────┘            │
│                                                               │
│  HASH: ticker:BTCUSDT                                         │
│  ┌────────────┬──────────────────┐                           │
│  │ open       │ "63800.00000000" │  ← Set on first tick      │
│  │ high       │ "65100.50000000" │  ← max(high, new_price)  │
│  │ low        │ "63200.00000000" │  ← min(low, new_price)   │
│  │ close      │ "64521.30000000" │  ← Always latest price   │
│  │ volume     │ "12345.67800000" │  ← Cumulative volume     │
│  │ change_pct │ "1.13037618"     │  ← (close-open)/open*100│
│  │ last_update│ "2026-03-19..."  │                           │
│  └────────────┴──────────────────┘                           │
│  (One hash per symbol: ticker:ETHUSDT, ticker:SOLUSDT, ...)  │
│                                                               │
│  PUB/SUB: price_updates                                       │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ {"symbol":"BTCUSDT","price":"64521.30","quantity":   │     │
│  │  "0.012","timestamp":1708000000000,"trade_id":123}  │     │
│  └─────────────────────────────────────────────────────┘     │
│  (Published in batches every ~1 second by the broadcaster)    │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

### Who Reads What from Redis

| Consumer | Redis Operation | Latency |
|----------|----------------|---------|
| Order engine (market order fill) | `HGET prices BTCUSDT` | ~0.1ms |
| Slippage calculator | `HGETALL ticker:BTCUSDT` | ~0.2ms |
| Risk manager (equity check) | `HGET prices {SYMBOL}` per asset | ~0.1ms × N |
| Portfolio tracker | `HGET prices {SYMBOL}` per position | ~0.1ms × N |
| `GET /market/price/BTCUSDT` | `HGET prices BTCUSDT` + `HGET prices:meta BTCUSDT` | ~0.3ms |
| `GET /market/prices` | `HGETALL prices` | ~1ms (600+ fields) |
| `GET /market/ticker/BTCUSDT` | `HGETALL ticker:BTCUSDT` | ~0.2ms |
| Limit order matcher (Celery, every 1s) | Pipeline: `HGET prices {SYM}` × N unique symbols | ~0.5ms |
| Battle snapshot engine (every 5s) | `HGET prices {SYM}` per participant position | ~0.1ms × N |
| WebSocket bridge | SUBSCRIBE `price_updates` (pushed, not polled) | ~0ms (push) |

---

## 9. TimescaleDB: The Historical Memory

### What TimescaleDB Stores

TimescaleDB is the **persistence layer**. It answers: "What happened in the past?"

### The `ticks` Hypertable (Raw Trade Data)

```
┌─────────────────────────────────────────────────────────────────┐
│  ticks (TimescaleDB Hypertable)                                 │
│  Partitioned by: time (1-hour chunks)                           │
│  Written by: Ingestion service via asyncpg COPY                 │
├─────────────┬──────────┬────────────┬──────────┬───────────────┤
│ time        │ symbol   │ price      │ quantity │ trade_id      │
├─────────────┼──────────┼────────────┼──────────┼───────────────┤
│ 12:00:00.001│ BTCUSDT  │ 64521.30   │ 0.012    │ 123456789     │
│ 12:00:00.003│ ETHUSDT  │ 3200.15    │ 1.500    │ 987654321     │
│ 12:00:00.005│ BTCUSDT  │ 64521.50   │ 0.005    │ 123456790     │
│ 12:00:00.008│ SOLUSDT  │ 142.80     │ 10.000   │ 456789123     │
│ ...         │ ...      │ ...        │ ...      │ ...           │
│ (thousands of rows per second across all pairs)                 │
└─────────────────────────────────────────────────────────────────┘

Indexes:
  - (symbol, time DESC)  → Fast symbol-specific time queries
  - (symbol, trade_id)   → Deduplication on reconnect
```

### Continuous Aggregates (Auto-Generated Candles)

TimescaleDB automatically builds OHLCV candles from the raw ticks:

```
ticks (raw trades, sub-second)
    │
    │ TimescaleDB auto-materializes every 1 minute
    ▼
candles_1m (1-minute OHLCV)
    │
    │ Auto-materializes every 5 minutes
    ▼
candles_5m (5-minute OHLCV)
    │
    │ Auto-materializes every 1 hour
    ▼
candles_1h (1-hour OHLCV)
    │
    │ Auto-materializes every 1 day
    ▼
candles_1d (1-day OHLCV)
```

Each continuous aggregate is a materialized view:

```sql
-- Example: candles_1m definition (from migration 001)
CREATE MATERIALIZED VIEW candles_1m
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 minute', time) AS bucket,
    symbol,
    FIRST(price, time) AS open,      -- First price in the minute
    MAX(price) AS high,               -- Highest price
    MIN(price) AS low,                -- Lowest price
    LAST(price, time) AS close,       -- Last price in the minute
    SUM(quantity) AS volume,          -- Total volume
    COUNT(*) AS trade_count           -- Number of trades
FROM ticks
GROUP BY bucket, symbol;

-- Auto-refresh policy: materialize every 1 minute
SELECT add_continuous_aggregate_policy('candles_1m',
    start_offset => INTERVAL '10 minutes',
    end_offset => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute'
);
```

**Important:** These are computed FROM the `ticks` table automatically. You don't write to them — TimescaleDB builds them from raw tick data.

### The `candles_backfill` Table (Historical, Downloaded)

```
This is SEPARATE from the continuous aggregates.

candles_1m = auto-generated from ticks (only exists since ingestion started)
candles_backfill = downloaded from Binance API (goes back to 2013/2017+)

They are UNION-ed together when backtesting needs historical data.
```

### Safety Net: Celery Refresh Task

A Celery beat task runs every 60 seconds to refresh continuous aggregates as a backup:

```python
# src/tasks/candle_aggregation.py
# Runs: CALL refresh_continuous_aggregate('candles_1m', NOW()-10min, NOW()-1min)
# If TimescaleDB's auto-policy already ran, this is a no-op.
```

---

## 10. How Every Consumer Reads Data

### Consumer Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  ┌─────────────────────┐          ┌──────────────────────┐         │
│  │     REDIS            │          │    TIMESCALEDB        │         │
│  │  (real-time prices)  │          │  (historical data)    │         │
│  └──────────┬───────────┘          └──────────┬───────────┘         │
│             │                                  │                     │
│  ┌──────────▼───────────┐          ┌──────────▼───────────┐         │
│  │ PriceCache            │          │ Repositories          │         │
│  │ (src/cache/           │          │ (src/database/         │         │
│  │  price_cache.py)      │          │  repositories/)       │         │
│  └──────────┬───────────┘          └──────────┬───────────┘         │
│             │                                  │                     │
│  Who reads from Redis:              Who reads from TimescaleDB:      │
│  ├─ OrderEngine.place_order()       ├─ GET /market/candles/{sym}    │
│  ├─ SlippageCalculator.calculate()  ├─ DataReplayer (backtesting)   │
│  ├─ RiskManager.validate_order()    ├─ GET /market/trades/{sym}     │
│  ├─ PortfolioTracker.get_portfolio()├─ PerformanceMetrics           │
│  ├─ GET /market/price/{sym}         ├─ TickRepository.get_vwap()    │
│  ├─ GET /market/prices              ├─ Celery snapshot tasks         │
│  ├─ GET /market/ticker/{sym}        │  (reads portfolio_snapshots)  │
│  ├─ LimitOrderMatcher (Celery 1s)   └──────────────────────────     │
│  ├─ BattleSnapshotEngine (5s)                                       │
│  └─ WebSocket bridge (pub/sub)                                      │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### Detailed: Order Engine

```
POST /api/v1/trade/order  (agent places an order)
    │
    ├─ RiskManager.validate_order()
    │   ├─ Redis: HGET prices BTCUSDT           ← current price for size/equity checks
    │   ├─ DB: SUM(realized_pnl) from trades    ← daily loss check
    │   ├─ Redis: GET rate_limit:...            ← rate limit check
    │   └─ DB: COUNT(*) from orders             ← open order limit check
    │
    ├─ OrderEngine.place_order()
    │   ├─ Redis: HGET prices BTCUSDT           ← reference price
    │   │
    │   ├─ If MARKET order:
    │   │   ├─ SlippageCalculator.calculate()
    │   │   │   └─ Redis: HGETALL ticker:BTCUSDT ← volume for slippage calc
    │   │   ├─ Apply slippage + fees
    │   │   └─ DB: INSERT order (filled), UPDATE balances
    │   │
    │   └─ If LIMIT/STOP/TP order:
    │       └─ DB: INSERT order (pending), lock balance
    │
    └─ Response: order details
```

### Detailed: Limit Order Matching (Celery, Every 1 Second)

```
Every 1 second:
    │
    ├─ DB: SELECT * FROM orders WHERE status='pending' ORDER BY id
    │   → Returns all pending orders (limit, stop-loss, take-profit)
    │
    ├─ Collect unique symbols from pending orders
    │
    ├─ Redis PIPELINE:
    │   HGET prices BTCUSDT
    │   HGET prices ETHUSDT
    │   HGET prices SOLUSDT
    │   ... (all unique symbols in ONE TCP round-trip)
    │
    ├─ For each pending order:
    │   ├─ Limit buy:   triggers if current_price <= order.price
    │   ├─ Limit sell:  triggers if current_price >= order.price
    │   ├─ Stop-loss:   triggers if current_price <= order.trigger_price
    │   └─ Take-profit: triggers if current_price >= order.trigger_price
    │
    └─ For each triggered order:
        └─ DB: UPDATE order status='filled', INSERT trade, UPDATE balances
```

### Detailed: Portfolio Tracker

```
GET /api/v1/account/portfolio
    │
    ├─ DB: SELECT * FROM balances WHERE agent_id = :agent_id
    │   → All asset balances (USDT, BTC, ETH, etc.)
    │
    ├─ DB: SELECT * FROM positions WHERE agent_id = :agent_id AND quantity > 0
    │   → All open positions
    │
    ├─ For each open position:
    │   ├─ Redis: HGET prices {SYMBOL}   ← current market price
    │   ├─ market_value = quantity × current_price
    │   └─ unrealized_pnl = (current_price - avg_entry_price) × quantity
    │
    ├─ total_equity = usdt_balance + Σ(market_value for all positions)
    │
    └─ Response: { total_equity, available_cash, positions[], roi_pct }
```

---

## 11. The Backtesting Data Path (Completely Separate)

### Why It's Different

Backtesting does NOT use Redis at all. It replays historical data from TimescaleDB, loaded into memory at start time.

```
LIVE TRADING:                    BACKTESTING:
  Binance WS → Redis → Read       TimescaleDB → Memory → Read
  (real-time, < 1ms)              (historical, preloaded, O(log n))

  These paths NEVER cross.
```

### How Backtesting Gets Its Data

**File:** `src/backtesting/data_replayer.py` — `DataReplayer`

#### Step 1: Preload (Once, at backtest start)

```sql
-- ONE query loads ALL price data for the entire backtest range
SELECT bucket, symbol, close
FROM candles_1m
WHERE bucket >= '2024-01-01' AND bucket <= '2024-07-01'

UNION ALL

SELECT bucket, symbol, close
FROM candles_backfill
WHERE bucket >= '2024-01-01' AND bucket <= '2024-07-01'
  AND interval = '1m'

ORDER BY bucket, symbol
```

This loads potentially millions of rows into a Python dict:

```python
_price_cache = {
    datetime(2024,1,1,0,0): {"BTCUSDT": Decimal("42150.00"), "ETHUSDT": Decimal("2280.00"), ...},
    datetime(2024,1,1,0,1): {"BTCUSDT": Decimal("42155.00"), "ETHUSDT": Decimal("2281.50"), ...},
    datetime(2024,1,1,0,2): {"BTCUSDT": Decimal("42148.00"), "ETHUSDT": Decimal("2279.00"), ...},
    ...  # ~260,000 entries for 6 months of 1-minute candles
}
_sorted_times = [datetime(2024,1,1,0,0), datetime(2024,1,1,0,1), ...]  # sorted for bisect
```

#### Step 2: Per-Step Price Lookup (Zero DB Queries)

```python
def load_prices(self, timestamp):
    # O(log n) binary search — no database call!
    idx = bisect.bisect_right(self._sorted_times, timestamp) - 1
    if idx >= 0:
        return self._price_cache[self._sorted_times[idx]]
    return {}
```

#### Why UNION of `candles_1m` + `candles_backfill`?

```
Timeline:
─────────────────────────────────────────────────────────────────►

2017                    2024-06-15              2026-03-19
│                       │                       │
│   candles_backfill    │   candles_1m          │
│   (downloaded via     │   (auto-generated     │
│    backfill script)   │    from live ticks)   │
│                       │                       │
│◄──────────────────────┤◄──────────────────────┤
│ Historical klines     │ Continuous aggregates │
│ from Binance API      │ from ingestion service│

The UNION combines both sources seamlessly.
If a backtest spans June 2024, it gets data from BOTH tables.
The UNION ALL avoids dedup overhead — if both have the same
(bucket, symbol), the last one in the dict wins (benign).
```

#### The Anti-Look-Ahead Guarantee

```
Virtual clock: 2024-03-15 14:30:00

DataReplayer can only return prices where:
    bucket <= 2024-03-15 14:30:00

The bisect_right finds the LATEST bucket AT OR BEFORE the virtual clock.
Future prices are physically inaccessible — they're in the dict but
the bisect will never land on them until the virtual clock advances.
```

---

## 12. WebSocket: Real-Time to the Frontend

### The Full Chain

```
Binance Exchange
    │
    │ WebSocket: wss://stream.binance.com:9443/stream?streams=...
    ▼
Ingestion Service (binance_ws.py or exchange_ws.py)
    │
    │ Per tick: Redis HSET prices + EVALSHA ticker_lua
    │ Per flush (~1s): asyncpg COPY to ticks table
    │                  Redis PUBLISH price_updates {json} × N
    ▼
Redis Pub/Sub Channel: "price_updates"
    │
    │ RedisPubSubBridge._listen_loop() in websocket/handlers.py
    │ (subscribes to "price_updates", receives every published message)
    ▼
RedisPubSubBridge
    │
    ├─ For each tick message:
    │   ├─ broadcast_to_channel("ticker:BTCUSDT", formatted_msg)
    │   │   → Only clients subscribed to ticker:BTCUSDT receive this
    │   │
    │   └─ broadcast_to_channel("ticker:all", formatted_msg)
    │       → ALL clients subscribed to ticker:all receive this
    ▼
ConnectionManager
    │
    │ Looks up which WebSocket connections are subscribed to each channel
    │ Sends the message to each subscribed client via ws.send_json()
    ▼
Frontend Browser (WebSocket client)
    │
    │ ws://localhost:8000/ws/v1?api_key=ak_live_...
    │
    │ Receives: {"type":"ticker","data":{"symbol":"BTCUSDT","price":"64521.30",...}}
    ▼
React Component (re-renders with new price)
```

### WebSocket Channels

| Channel | Subscribe Message | What You Get | Update Frequency |
|---------|------------------|-------------|-----------------|
| `ticker:BTCUSDT` | `{"action":"subscribe","channel":"ticker","symbol":"BTCUSDT"}` | Every BTC trade tick | ~10-50/second for BTC |
| `ticker:all` | `{"action":"subscribe","channel":"ticker_all"}` | Every tick for every pair | ~1000+/second |
| `orders` | `{"action":"subscribe","channel":"orders"}` | Your order fills/cancels | On each event |
| `portfolio` | `{"action":"subscribe","channel":"portfolio"}` | Portfolio snapshots | Every ~60 seconds |
| `battle:{id}` | `{"action":"subscribe","channel":"battle","battle_id":"..."}` | Battle equity updates | Every 5 seconds |

### SDK WebSocket Client

```python
from sdk.agentexchange import AgentExchangeWS

ws = AgentExchangeWS(api_key="ak_live_...")

@ws.on_ticker("BTCUSDT")
async def handle_price(data):
    print(f"BTC: ${data['price']}")

@ws.on_order_update()
async def handle_order(data):
    print(f"Order {data['order_id']}: {data['status']}")

await ws.connect()  # Blocks with auto-reconnect
```

---

## 13. Complete Data Flow Diagrams

### Diagram 1: The Full System Overview

```
                           BINANCE EXCHANGE
                                 │
                    ┌────────────┤
                    │            │
              WebSocket       REST API
              (real-time      (historical
               trades)         klines)
                    │            │
                    ▼            ▼
         ┌──────────────┐  ┌──────────────┐
         │  Ingestion    │  │  Backfill    │
         │  Service      │  │  Script      │
         │  (24/7)       │  │  (one-time)  │
         └──┬────┬───┬───┘  └──────┬───────┘
            │    │   │              │
     ┌──────┘    │   └───────┐     │
     ▼           ▼           ▼     ▼
┌─────────┐ ┌────────────┐ ┌──────────────────────┐
│  REDIS  │ │ ticks      │ │ candles_backfill     │
│         │ │ (hypertable│ │ (hypertable)          │
│ prices  │ │  1h chunks)│ │                       │
│ tickers │ │            │ │ 2013/2017 → present   │
│ pub/sub │ │ ↓ auto     │ │                       │
│         │ │            │ │                       │
│         │ │ candles_1m │ │                       │
│         │ │ candles_5m │ │                       │
│         │ │ candles_1h │ │ Backtest DataReplayer │
│         │ │ candles_1d │ │ UNIONs candles_1m +   │
│         │ │            │ │ candles_backfill      │
└────┬────┘ └─────┬──────┘ └──────────┬───────────┘
     │            │                    │
     │    LIVE    │    HISTORICAL      │   BACKTESTING
     │    PATH    │    PATH            │   PATH
     ▼            ▼                    ▼
┌─────────┐ ┌──────────┐      ┌──────────────┐
│ Order   │ │ Candle   │      │ BacktestEngine│
│ Engine  │ │ API      │      │ (in-memory   │
│ Risk    │ │ endpoint │      │  sandbox)    │
│ Manager │ │          │      │              │
│ Portfolio│ │ Charts   │      │ Gym API      │
│ Tracker │ │ Frontend │      │ RL Training  │
│ WebSocket│ │         │      │              │
│ Battles │ │          │      │              │
└─────────┘ └──────────┘      └──────────────┘
```

### Diagram 2: Per-Tick Data Flow

```
Binance Trade Event
│
▼
┌─────────────────────────────────────────────────────┐
│              INGESTION SERVICE                       │
│                                                      │
│  1. Parse JSON → Tick(symbol, price, qty, time, id) │
│                                                      │
│  2. ──► Redis: HSET prices BTCUSDT "64521.30"       │ ◄─ INSTANT
│     ──► Redis: EVALSHA ticker_lua ticker:BTCUSDT     │ ◄─ INSTANT
│                                                      │
│  3. ──► Memory buffer: append(tick)                  │ ◄─ INSTANT
│         [tick1, tick2, tick3, ... tickN]              │
│                                                      │
│  4. Every 1 second OR buffer >= 5000:                │
│     ──► TimescaleDB: COPY N rows INTO ticks          │ ◄─ ~5-20ms
│     ──► Redis: PUBLISH price_updates × N             │ ◄─ ~1-5ms
│                                                      │
└─────────────────────────────────────────────────────┘
│                                           │
▼                                           ▼
Redis HSET prices                    Redis PUBLISH price_updates
│                                           │
├─► OrderEngine reads (on trade)            ├─► WebSocket Bridge
├─► RiskManager reads (on trade)            │     │
├─► PortfolioTracker reads (on request)     │     ├─► ticker:BTCUSDT channel
├─► GET /market/price reads                 │     │     → subscribed browsers
├─► LimitOrderMatcher reads (every 1s)      │     └─► ticker:all channel
└─► BattleSnapshot reads (every 5s)         │           → subscribed browsers
                                            │
                                TimescaleDB ticks table
                                            │
                                    auto-materializes
                                            │
                                    ├─► candles_1m
                                    ├─► candles_5m
                                    ├─► candles_1h
                                    └─► candles_1d
                                            │
                                    ├─► GET /market/candles reads
                                    ├─► DataReplayer reads (backtest)
                                    └─► PerformanceMetrics reads
```

### Diagram 3: Backtesting vs Live — Side by Side

```
┌────────────────────────────┐    ┌────────────────────────────┐
│        LIVE TRADING         │    │       BACKTESTING           │
├────────────────────────────┤    ├────────────────────────────┤
│                             │    │                             │
│ Price source:               │    │ Price source:               │
│   Redis HGET prices {SYM}  │    │   In-memory dict (preloaded)│
│   (< 1ms latency)          │    │   (O(log n) bisect lookup)  │
│                             │    │                             │
│ Data age:                   │    │ Data age:                   │
│   Real-time (< 1 second)   │    │   Historical (2013-present) │
│                             │    │                             │
│ Candle source:              │    │ Candle source:              │
│   TimescaleDB candles_1m    │    │   candles_1m UNION          │
│   (continuous aggregate)    │    │   candles_backfill          │
│                             │    │   (preloaded into memory)   │
│                             │    │                             │
│ Order execution:            │    │ Order execution:            │
│   OrderEngine → DB          │    │   BacktestSandbox (memory)  │
│   Celery matches limits     │    │   Checked every step()      │
│                             │    │                             │
│ Slippage source:            │    │ Slippage source:            │
│   Redis ticker:{SYM} volume │    │   Fixed factor (0.1 default)│
│                             │    │                             │
│ Risk checks:                │    │ Risk checks:                │
│   RiskManager (8 steps)     │    │   Sandbox._check_risk_limits│
│   CircuitBreaker (Redis)    │    │   (3 checks, in-memory)     │
│                             │    │                             │
│ Results:                    │    │ Results:                     │
│   DB: orders, trades,       │    │   DB: backtest_sessions,    │
│       positions, balances   │    │       backtest_trades,      │
│                             │    │       backtest_snapshots    │
│                             │    │                             │
│ Uses Redis: YES             │    │ Uses Redis: NO              │
│ Uses TimescaleDB: YES       │    │ Uses TimescaleDB: YES       │
│ Uses Binance WS: INDIRECTLY │    │ Uses Binance WS: NO         │
│                             │    │                             │
└────────────────────────────┘    └────────────────────────────┘
```

---

## 14. When Does the System Use What?

### Decision Table: "Where Does This Data Come From?"

| Question | Source | Why |
|----------|--------|-----|
| "What is BTC's price right now?" | Redis `HGET prices BTCUSDT` | Fastest possible (< 1ms) |
| "What was BTC's price 5 minutes ago?" | TimescaleDB `candles_1m` | Redis only has current price |
| "Show me BTC's 1-hour chart for today" | TimescaleDB `candles_1h` | Historical aggregated data |
| "Show me BTC's chart for 2023" | TimescaleDB `candles_backfill` | Pre-ingestion historical data |
| "Run a backtest on Jan-Jun 2024" | `candles_1m UNION candles_backfill` → memory | Preloaded, zero DB per step |
| "Fill this market order at current price" | Redis `HGET prices BTCUSDT` | Need real-time for execution |
| "Check if this limit order should trigger" | Redis pipeline `HGET prices {SYM}` × N | Celery task every 1 second |
| "What's my portfolio worth?" | Redis `HGET prices {SYM}` per position | Need current prices for valuation |
| "What's the 24h volume for BTC?" | Redis `HGETALL ticker:BTCUSDT` | Rolling ticker maintained per tick |
| "Calculate my Sharpe ratio" | TimescaleDB `portfolio_snapshots` | Needs historical equity series |
| "Stream live prices to my browser" | Redis pub/sub `price_updates` → WebSocket | Push-based, no polling |
| "What pairs are available?" | DB `trading_pairs` + Redis `HGETALL prices` | Metadata + live price flag |

### When Does Binance Direct vs CCXT Get Used?

| Scenario | What Runs | Why |
|----------|----------|-----|
| Default setup (`EXCHANGE_ID=binance`) | Try CCXT → fallback to Binance Direct WS | CCXT is preferred, Binance Direct is proven fallback |
| Forced legacy (`_FORCE_LEGACY_BINANCE=True`) | Binance Direct WS only | For debugging or if CCXT has issues |
| Non-Binance exchange (`EXCHANGE_ID=okx`) | CCXT only | Binance Direct doesn't work with OKX |
| Backfill historical data (`scripts/backfill_history.py`) | CCXT `fetch_ohlcv()` or Binance REST API | WebSocket doesn't serve historical data |
| Candle API fallback (`GET /market/candles`) | Binance/CCXT REST (if local DB is thin) | Supplement local data when available |

### When Does WebSocket vs REST Get Used?

| Use Case | Protocol | Why |
|----------|---------|-----|
| Ingesting live ticks from Binance | WebSocket (exchange → us) | Continuous stream, no polling overhead |
| Streaming prices to frontend | WebSocket (us → browser) | Real-time push, no polling |
| Agent places an order | REST (POST /trade/order) | Request-response pattern |
| Agent checks portfolio | REST (GET /account/portfolio) | On-demand query |
| Agent runs a backtest step | REST (POST /backtest/{id}/step) | Request-response per step |
| Downloading historical candles | REST (Binance API) | Paginated batch download |
| SDK agent gets price updates | WebSocket (us → agent) | Optional real-time feed |

---

## 15. The Complete Picture: Every Table, Key, and Channel

### All TimescaleDB Tables Related to Market Data

```
┌────────────────────────────────────────────────────────────────┐
│                     TIMESCALEDB                                 │
│                                                                 │
│  HYPERTABLES (time-partitioned):                               │
│  ┌──────────────────────────────────────────────────┐          │
│  │ ticks                                             │          │
│  │   Columns: time, symbol, price, quantity,         │          │
│  │            is_buyer_maker, trade_id               │          │
│  │   Partition: 1-hour chunks                        │          │
│  │   Written by: Ingestion service (COPY)            │          │
│  │   Rows: Millions per day                          │          │
│  └──────────────────────────────────────────────────┘          │
│                                                                 │
│  ┌──────────────────────────────────────────────────┐          │
│  │ candles_backfill                                  │          │
│  │   Columns: bucket, symbol, interval,              │          │
│  │            open, high, low, close, volume,        │          │
│  │            trade_count                            │          │
│  │   Partition: 1-month chunks                       │          │
│  │   Compressed after: 90 days                       │          │
│  │   Written by: backfill_history.py script          │          │
│  │   Rows: Millions (years of history)               │          │
│  └──────────────────────────────────────────────────┘          │
│                                                                 │
│  CONTINUOUS AGGREGATES (auto-generated from ticks):            │
│  ┌──────────────────────────────────────────────────┐          │
│  │ candles_1m  (refreshed every 1 minute)            │          │
│  │ candles_5m  (refreshed every 5 minutes)           │          │
│  │ candles_1h  (refreshed every 1 hour)              │          │
│  │ candles_1d  (refreshed every 1 day)               │          │
│  │                                                    │          │
│  │ All have columns:                                  │          │
│  │   bucket, symbol, open, high, low, close,         │          │
│  │   volume, trade_count                             │          │
│  │                                                    │          │
│  │ Source: SELECT ... FROM ticks GROUP BY             │          │
│  │         time_bucket(interval, time), symbol       │          │
│  └──────────────────────────────────────────────────┘          │
│                                                                 │
│  REGULAR TABLE:                                                │
│  ┌──────────────────────────────────────────────────┐          │
│  │ trading_pairs                                     │          │
│  │   Columns: symbol (PK), base_asset, quote_asset,  │          │
│  │            status, min_qty, max_qty, step_size,   │          │
│  │            min_notional, updated_at               │          │
│  │   Written by: seed_pairs.py script                │          │
│  │   Rows: ~600                                      │          │
│  └──────────────────────────────────────────────────┘          │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### All Redis Keys Related to Market Data

```
┌────────────────────────────────────────────────────────────────┐
│                        REDIS                                    │
│                                                                 │
│  HASH: prices                                                   │
│    600+ fields, one per USDT pair                               │
│    Updated: every tick (hundreds/sec)                            │
│    Read by: order engine, risk, portfolio, market API            │
│                                                                 │
│  HASH: prices:meta                                              │
│    600+ fields, ISO-8601 timestamps                             │
│    Updated: every tick                                           │
│    Read by: staleness detection, monitoring healthcheck          │
│                                                                 │
│  HASH: ticker:BTCUSDT  (one per symbol, 600+ hashes)           │
│    7 fields: open, high, low, close, volume, change_pct,       │
│              last_update                                        │
│    Updated: every tick via Lua script (atomic)                  │
│    Read by: slippage calculator, GET /market/ticker             │
│                                                                 │
│  PUBSUB: price_updates                                          │
│    JSON messages published in batches every ~1 second            │
│    Subscribers: WebSocket RedisPubSubBridge                     │
│    Not persisted (pub/sub is fire-and-forget)                   │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### All WebSocket Channels

```
┌────────────────────────────────────────────────────────────────┐
│                    WEBSOCKET SERVER                              │
│                 ws://host/ws/v1?api_key=...                     │
│                                                                 │
│  PUBLIC CHANNELS:                                               │
│  ┌──────────────────────────────────────────────┐              │
│  │ ticker:{SYMBOL}    (e.g. ticker:BTCUSDT)     │              │
│  │   Source: Redis pub/sub price_updates         │              │
│  │   Data: {symbol, price, quantity, timestamp}  │              │
│  │   Frequency: per-tick for that symbol         │              │
│  │                                               │              │
│  │ ticker:all                                    │              │
│  │   Source: Redis pub/sub price_updates         │              │
│  │   Data: same as above, for ALL symbols        │              │
│  │   Frequency: hundreds/sec (all pairs)         │              │
│  │                                               │              │
│  │ candles:{SYMBOL}:{interval}                   │              │
│  │   Source: (not yet actively broadcast)        │              │
│  │   Status: Channel class exists, no publisher  │              │
│  └──────────────────────────────────────────────┘              │
│                                                                 │
│  PRIVATE CHANNELS (per-account):                               │
│  ┌──────────────────────────────────────────────┐              │
│  │ orders                                        │              │
│  │   Source: broadcast_to_account() from routes  │              │
│  │   Data: order status changes (fill, cancel)   │              │
│  │   Frequency: on each event                    │              │
│  │                                               │              │
│  │ portfolio                                     │              │
│  │   Source: Celery snapshot task (60s)           │              │
│  │   Data: equity, positions, unrealized PnL     │              │
│  │   Frequency: ~every 60 seconds                │              │
│  └──────────────────────────────────────────────┘              │
│                                                                 │
│  BATTLE CHANNEL:                                               │
│  ┌──────────────────────────────────────────────┐              │
│  │ battle:{battle_id}                            │              │
│  │   Source: Celery battle snapshot task (5s)    │              │
│  │   Data: participant equities, trades, status  │              │
│  │   Frequency: every 5 seconds during battle    │              │
│  └──────────────────────────────────────────────┘              │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

---

## 16. Common Confusion Points Explained

### Q: "We have CCXT AND Binance direct — which one actually runs?"

**A:** It depends on the `EXCHANGE_ID` setting:

```
EXCHANGE_ID=binance (default):
    → Tries CCXT first
    → If CCXT fails (not installed, error): falls back to Binance Direct
    → Result: usually CCXT runs, but Binance Direct is the safety net

EXCHANGE_ID=okx (or any other):
    → CCXT only, no fallback
    → If CCXT fails: service crashes (intentional — no Binance code can talk to OKX)
```

You will never have BOTH running simultaneously. It's one or the other.

### Q: "We have WebSocket AND REST — when does each get used?"

**A:** Two completely different jobs:

```
INBOUND data (exchange → us):
    WebSocket = live tick stream (used by ingestion service 24/7)
    REST = historical candle download (used by backfill script, one-time)

OUTBOUND data (us → frontend/agents):
    WebSocket = real-time price push to browsers/SDK clients
    REST = on-demand queries (GET /market/price, POST /trade/order)
```

### Q: "We have `candles_1m` AND `candles_backfill` — what's the difference?"

**A:**

```
candles_1m:
    Source: Auto-generated by TimescaleDB from the ticks table
    Data: Only exists since you started running the ingestion service
    Example: If you started on 2024-06-15, candles_1m has data from 2024-06-15 onward
    Updated: Automatically every 1 minute

candles_backfill:
    Source: Downloaded from Binance API by running scripts/backfill_history.py
    Data: Goes back to whenever the pair was listed (2017+ for BTC)
    Example: 2017-08-17 to 2024-06-14 (before ingestion started)
    Updated: Only when you run the script again

For backtesting:
    DataReplayer UNIONs BOTH tables → seamless historical data
    Backtest from 2023-2025? Gets backfill for 2023 + live candles for 2024-2025
```

### Q: "Redis has prices AND TimescaleDB has ticks — why both?"

**A:**

```
Redis (prices hash):
    Stores: ONLY the latest price per symbol (one number)
    Purpose: "What is BTCUSDT right now?" → answer in 0.1ms
    History: NONE. Each tick overwrites the previous price.
    Use case: Order fills, risk checks, portfolio valuation

TimescaleDB (ticks table):
    Stores: EVERY single trade tick with full details
    Purpose: "What was BTCUSDT at 3:42:17.003 PM on March 15, 2024?"
    History: EVERYTHING since ingestion started
    Use case: Building candle charts, analytics, backtesting

They serve completely different needs.
Redis = speed (current state)
TimescaleDB = memory (full history)
```

### Q: "Where do candle charts come from?"

**A:**

```
GET /api/v1/market/candles/BTCUSDT?interval=1h&limit=24

1. Route determines view: interval=1h → query candles_1h
2. SQL: SELECT bucket, open, high, low, close, volume
        FROM candles_1h
        WHERE symbol='BTCUSDT' AND bucket <= NOW()
        ORDER BY bucket DESC LIMIT 24
3. If fewer than 24 rows returned:
   → Fallback to Binance REST API: GET /api/v3/klines?symbol=BTCUSDT&interval=1h&limit=24
   → Merge results
4. Return sorted OHLCV array to frontend
```

### Q: "How does the Gym API get its data?"

**A:**

```
The Gym API does NOT connect to Binance or Redis at all.
It calls the platform's REST API, which reads from:
    - Backtesting engine (which preloaded from TimescaleDB)

Flow:
    Gym env.reset()
        → POST /api/v1/backtest/create
        → POST /api/v1/backtest/{id}/start
           → DataReplayer loads candles_1m UNION candles_backfill into memory

    Gym env.step(action)
        → POST /api/v1/backtest/{id}/trade/order  (sandbox, in-memory)
        → POST /api/v1/backtest/{id}/step          (advances virtual clock)
        → GET /api/v1/backtest/{id}/market/candles  (reads from preloaded memory)

    Zero Redis. Zero Binance. Zero live data.
    Everything is historical, preloaded, deterministic.
```

### Q: "What happens if Redis goes down?"

**A:**

```
Ingestion service:
    - Catches RedisError, logs warning, continues
    - Ticks still buffer to memory and flush to TimescaleDB
    - Redis writes are non-fatal (DB is source of truth)

Live trading:
    - Order engine: PriceNotAvailableError (HTTP 503) for new orders
    - Risk manager: Cannot check rate limits → orders rejected
    - Portfolio tracker: Falls back to cost basis (stale valuation)
    - WebSocket clients: No price updates (bridge can't receive pub/sub)

Backtesting:
    - Completely unaffected (doesn't use Redis at all)
```

### Q: "What happens if TimescaleDB goes down?"

**A:**

```
Ingestion service:
    - TickBuffer catches PostgresError, prepends batch back to buffer
    - Retries on next flush (1 second later)
    - Warning: unbounded memory growth if DB stays down long
    - Redis writes continue normally (prices stay fresh)

Live trading:
    - Orders that need DB writes fail (balances, positions)
    - Redis prices still work (current price queries succeed)

Backtesting:
    - Cannot create new sessions (needs DB for session records)
    - Active sessions with preloaded data continue working (in-memory)
```

---

## Summary: The One-Page Mental Model

```
                    BINANCE (or any CCXT exchange)
                              │
                         WebSocket
                         (live ticks)
                              │
                    ┌─────────▼──────────┐
                    │  INGESTION SERVICE  │
                    │  (24/7 process)     │
                    └──┬──────┬──────┬───┘
                       │      │      │
              ┌────────┘      │      └────────┐
              ▼               ▼               ▼
         ┌─────────┐   ┌──────────┐   ┌──────────────┐
         │  REDIS  │   │  ticks   │   │ price_updates│
         │ prices  │   │ (table)  │   │  (pub/sub)   │
         │ tickers │   │          │   │              │
         └────┬────┘   └────┬─────┘   └──────┬───────┘
              │              │                │
         LIVE PATH      HISTORY PATH     PUSH PATH
              │              │                │
    ┌─────────┤         ┌────┤           ┌────┤
    │         │         │    │           │    │
    ▼         ▼         ▼    ▼           ▼    ▼
 Orders   Portfolio  candles  candles   WS     WS
 Engine   Tracker    _1m/5m/  backfill Bridge  Clients
 Risk               1h/1d             (push)  (browsers
 Manager            (auto-             ↓       agents)
                    aggregates)  Frontend
                         │       Charts
                         │
                    ┌────┤
                    │    │
                    ▼    ▼
              Backtesting  Market
              DataReplayer Candle
              (UNION →     API
               memory)    endpoint
```

**Three paths, three purposes:**
1. **REDIS** = real-time current state (sub-millisecond reads)
2. **TIMESCALEDB** = historical record (ticks → candles → charts/backtests)
3. **PUB/SUB → WEBSOCKET** = real-time push to connected clients
