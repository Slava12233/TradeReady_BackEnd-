# Price Ingestion

<!-- last-updated: 2026-03-17 -->

> Streams real-time trade ticks from Binance WebSocket, caches prices in Redis, and bulk-flushes tick history to TimescaleDB.

## What This Module Does

The price ingestion service is a standalone long-running process (`python -m src.price_ingestion.service`) that:

1. Fetches all active USDT trading pairs from the Binance REST API (~600+ pairs).
2. Opens one or more combined WebSocket connections to Binance (max 1024 streams per connection) and receives every trade tick in real time.
3. For each incoming tick:
   - Writes the latest price to the Redis `prices` hash (overwrite) via `PriceCache.set_price()`.
   - Updates rolling 24-hour ticker stats in Redis via `PriceCache.update_ticker()`.
   - Appends the tick to an in-memory `TickBuffer`.
4. The `TickBuffer` flushes accumulated ticks to the TimescaleDB `ticks` hypertable using asyncpg `COPY` (10-50x faster than row-by-row INSERT). Flushes are triggered by either a time interval (default 1 second) or a size threshold (default 5000 ticks), whichever comes first.
5. On each successful DB flush, the same batch is broadcast to the Redis `price_updates` pub/sub channel in a single pipeline round-trip for downstream WebSocket consumers.
6. Handles SIGINT/SIGTERM gracefully: stops accepting ticks, performs a final buffer flush, then tears down Redis and DB connections.

Additionally, `binance_klines.py` provides a REST client for fetching historical OHLCV candles from Binance when local TimescaleDB data is insufficient.

## Key Files

| File | Purpose |
|------|---------|
| `service.py` | Main entry point and orchestrator. Wires up all dependencies, runs the tick loop, handles signals. |
| `binance_ws.py` | `BinanceWebSocketClient` -- fetches USDT pairs, builds combined-stream URLs, manages WS connections with exponential-backoff reconnect, yields `Tick` objects. |
| `tick_buffer.py` | `TickBuffer` -- asyncio-safe in-memory buffer with time-based and size-based flush triggers. Uses asyncpg `COPY` for bulk inserts. Retains ticks on flush failure. |
| `broadcaster.py` | `PriceBroadcaster` -- publishes ticks to the Redis `price_updates` pub/sub channel. Supports single and batched (pipeline) publishing. |
| `binance_klines.py` | `fetch_binance_klines()` -- async function to fetch historical OHLCV candles from the Binance `/api/v3/klines` REST endpoint. Used as a fallback for time ranges not covered by local data. |
| `__init__.py` | Empty package marker. |

## Architecture & Patterns

### Data Flow

```
Binance WS  ──tick──>  service.run()
                          ├── PriceCache.set_price()        [Redis HSET prices {SYMBOL}]
                          ├── PriceCache.update_ticker()     [Redis ticker:{symbol}]
                          └── TickBuffer.add()               [in-memory list]
                                │
                          (every 1s OR every 5000 ticks)
                                │
                                ├── asyncpg COPY → TimescaleDB `ticks` table
                                └── PriceBroadcaster.broadcast_batch() → Redis pub/sub `price_updates`
```

### Multi-Connection Multiplexing

Binance caps combined streams at 1024 per WebSocket connection. `BinanceWebSocketClient` partitions symbols into chunks and spawns one `_connection_loop` task per URL. All tasks write to a shared `asyncio.Queue` (max 50,000 items), producing a single unified tick stream for the consumer.

### Flush Cycle

Two independent triggers cause a flush:

1. **Size trigger** -- when `TickBuffer.add()` detects the buffer has reached `max_size` ticks, it snapshots and clears the buffer under the lock, then writes outside the lock so `add()` is not blocked during the DB round-trip.
2. **Time trigger** -- `start_periodic_flush()` runs as a background `asyncio.Task`, calling `flush()` every `flush_interval` seconds.

On flush failure (PostgreSQL error or unexpected exception), the batch is prepended back into the buffer so the next flush retries those ticks. No data is silently dropped.

### Reconnection Strategy

Each WebSocket connection runs an independent reconnect loop with exponential backoff: starts at 1 second, doubles on each failure, caps at 60 seconds. Backoff resets to 1 second on successful connection. `CancelledError` is caught separately to allow clean shutdown.

### Graceful Shutdown

`service.py` registers a POSIX signal handler (`SIGINT`, `SIGTERM`) that sets a module-level `_shutdown_requested` flag. The main tick loop checks this flag on every iteration. On exit, the `finally` block cancels the periodic flush task, calls `buffer.shutdown()` (final flush), disconnects Redis, and closes the DB pool.

## Public API / Interfaces

### `BinanceWebSocketClient`

```python
client = BinanceWebSocketClient(exchange_info_url=..., ws_base_url=..., max_streams=1024)
await client.fetch_pairs()            # -> list[str] of USDT symbols
client.get_all_pairs()                # -> list[str] (cached)
async for tick in client.listen():    # -> AsyncGenerator[Tick, None]
    ...
```

### `TickBuffer`

```python
buffer = TickBuffer(db_pool, flush_interval=1.0, max_size=5000, broadcaster=None)
await buffer.add(tick)                # append; auto-flushes if full
await buffer.flush()                  # manual flush -> int (count written)
task = asyncio.create_task(buffer.start_periodic_flush())  # background loop
await buffer.shutdown()               # final flush before exit
```

### `PriceBroadcaster`

```python
broadcaster = PriceBroadcaster(redis)
await broadcaster.broadcast(tick)           # single tick -> PUBLISH
await broadcaster.broadcast_batch(ticks)    # batched via Redis pipeline
```

### `fetch_binance_klines()`

```python
candles = await fetch_binance_klines(
    symbol="BTCUSDT", interval="1h", limit=500,
    start_time=datetime(...), end_time=datetime(...)
)
# Returns list[dict] with keys: time, open, high, low, close, volume, trade_count
```

### Shared Type: `Tick`

Defined in `src/cache/types.py` (not in this module). A namedtuple with fields: `symbol`, `price` (Decimal), `quantity` (Decimal), `timestamp` (datetime, UTC), `is_buyer_maker` (bool), `trade_id` (int).

## Dependencies

| Dependency | Used By | Purpose |
|------------|---------|---------|
| `websockets` | `binance_ws.py` | Binance WebSocket connections |
| `httpx` | `binance_ws.py`, `binance_klines.py` | HTTP client for Binance REST API |
| `asyncpg` | `tick_buffer.py` | Bulk `COPY` inserts to TimescaleDB |
| `redis.asyncio` | `broadcaster.py` | Pub/sub publishing |
| `structlog` | all files | Structured logging |
| `src.cache.types.Tick` | all files | Shared tick data type |
| `src.cache.price_cache.PriceCache` | `service.py` | Redis price/ticker cache |
| `src.cache.redis_client.RedisClient` | `service.py` | Redis connection management |
| `src.database.session` | `service.py` | `init_db`, `close_db`, `get_asyncpg_pool` |
| `src.config.get_settings` | `service.py` | `flush_interval`, `buffer_max_size`, `binance_ws_url`, `redis_url` |

## Common Tasks

**Run the service locally:**
```bash
python -m src.price_ingestion.service
```

**Tune flush behavior** via environment variables (see `src/config.py`):
- `TICK_FLUSH_INTERVAL` -- seconds between periodic flushes (default `1.0`)
- `TICK_BUFFER_MAX_SIZE` -- max ticks before size-triggered flush (default `5000`)
- `BINANCE_WS_URL` -- override the Binance WS base URL

**Backfill historical candles** (separate script, not part of this module):
```bash
python scripts/backfill_history.py
```

## Gotchas & Pitfalls

- **`structlog.configure()` is called inside `main()`, not at module level.** This prevents test imports from mutating the global structlog singleton. If you move it to module level, log-assertion tests will break.
- **The `_shutdown_requested` flag is a module-level global**, not an asyncio Event. It works because the tick loop and signal handler run in the same thread. Do not use this pattern in multi-threaded contexts.
- **`TickBuffer` retains batches on flush failure** by prepending them back into the buffer. This means a persistent DB outage will cause unbounded memory growth. There is no cap on retry buffer size.
- **The asyncio.Queue in `listen()` has a maxsize of 50,000.** If the consumer falls behind (e.g., slow Redis writes), `queue.put()` will block, applying backpressure to the WebSocket reader tasks. This is intentional but can cause missed heartbeats if sustained.
- **`binance_klines.py` uses `logging` (stdlib)** while every other file uses `structlog`. This is an inconsistency but does not cause runtime issues.
- **SIGTERM handling is guarded** for Windows compatibility -- `signal.signal(signal.SIGTERM, ...)` is wrapped in a try/except because SIGTERM is not available on all Windows configurations.
- **Binance combined-stream URL format**: streams are joined with `/` (e.g., `?streams=btcusdt@trade/ethusdt@trade`). The `@trade` suffix selects trade events specifically; other stream types (e.g., `@kline_1m`) would need different parsing logic.
- **`_parse_message` returns `None` for non-trade events** (e.g., connection ack messages). These are silently dropped, which is correct behavior.
- **Decimal precision**: prices and quantities are parsed as `Decimal(str)` to avoid float rounding. Never convert to float in this pipeline.

## Recent Changes

- `2026-03-17` -- Initial CLAUDE.md created
