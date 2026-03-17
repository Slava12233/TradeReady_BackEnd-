# Cache Layer

<!-- last-updated: 2026-03-17 -->

> Redis-backed price store, ticker aggregation, and async connection management for sub-millisecond price lookups.

## What This Module Does

Provides the entire Redis interface for the platform: connection pooling, current-price storage, 24-hour rolling ticker statistics, and staleness detection. Every other module that touches Redis obtains its handle through this package -- never by creating ad-hoc `redis.asyncio.Redis` instances directly.

The price ingestion pipeline writes prices here; the order engine, risk manager, portfolio tracker, and snapshot engine read from here. Pub/sub broadcasting lives in `src/price_ingestion/broadcaster.py` but uses the same Redis connection pool.

## Key Files

| File | Purpose |
|------|---------|
| `redis_client.py` | `RedisClient` class (pool wrapper) + module-level singleton (`get_redis_client` / `close_redis_client`) |
| `price_cache.py` | `PriceCache` -- read/write current prices, atomic ticker updates via Lua script, stale-pair detection |
| `types.py` | `Tick` (NamedTuple) and `TickerData` (dataclass) -- canonical data carriers shared across ingestion, buffer, broadcaster, and cache |
| `__init__.py` | Re-exports all public symbols: `RedisClient`, `get_redis_client`, `close_redis_client`, `PriceCache`, `Tick`, `TickerData` |

## Architecture & Patterns

### Connection Management

- **`RedisClient`** wraps `redis.asyncio` with a capped connection pool (default 50 connections). Supports `async with` context manager. Used by the price ingestion service which manages its own lifecycle.
- **`get_redis_client()`** is a module-level singleton with double-checked locking (`asyncio.Lock`) for safe concurrent first-call initialization. Used by FastAPI dependencies and health checks.
- **`close_redis_client()`** tears down the singleton on app shutdown (called from lifespan handler).
- All connections use `decode_responses=True` so values come back as `str`, not `bytes`.

### Redis Key Patterns

| Key | Type | Purpose |
|-----|------|---------|
| `prices` | Hash | Field per pair -> current price string. `HSET prices BTCUSDT 64521.30` |
| `prices:meta` | Hash | Field per pair -> ISO-8601 last-update timestamp. Used for staleness detection. |
| `ticker:{symbol}` | Hash | Fields: `open`, `high`, `low`, `close`, `volume`, `change_pct`, `last_update`. Rolling 24h stats. |
| `rate_limit:{api_key}:{group}:{minute}` | String (counter) | API rate limiting (managed by `src/api/middleware/rate_limit.py`) |
| `circuit_breaker:{account_id}` | Hash | Daily PnL circuit breaker state (managed by `src/risk/circuit_breaker.py`) |

### Pub/Sub

The cache module itself does not publish or subscribe. Pub/sub is handled by adjacent modules using the same Redis connection:

- **Channel `price_updates`** -- `src/price_ingestion/broadcaster.py` publishes JSON-encoded tick data after each flush. WebSocket channels (`src/api/websocket/channels.py`) subscribe and fan out to connected clients.
- Message format: `{"symbol": "BTCUSDT", "price": "64521.30", "quantity": "0.012", "timestamp": 1708000000000, "is_buyer_maker": false, "trade_id": 123456789}`

### Atomic Ticker Updates (Lua Script)

`PriceCache.update_ticker()` uses a server-side Lua script (`_UPDATE_TICKER_LUA`) to atomically read-modify-write the `ticker:{symbol}` hash. This eliminates the TOCTOU race where two concurrent coroutines could overwrite each other's high/low/volume. On first tick for a symbol, all fields are initialized; subsequent ticks update high/low/close/volume and recompute `change_pct` relative to the stored open. The script is registered once via `register_script()` and uses `EVALSHA` on subsequent calls.

### Pipeline Usage

`set_price()` batches the `prices` and `prices:meta` HSET commands in a single non-transactional pipeline (one TCP round-trip). This means a reader may briefly see a new price before the corresponding timestamp lands in `prices:meta`.

## Public API / Interfaces

### `RedisClient`
- `RedisClient(url, max_connections=50)` -- constructor
- `await client.connect()` -- create pool, verify with PING (cleans up on failure)
- `await client.disconnect()` -- close all pooled connections
- `client.get_client() -> aioredis.Redis` -- returns underlying client (raises `RuntimeError` if not connected)
- `await client.ping() -> bool` -- safe health check

### `get_redis_client() -> aioredis.Redis`
Module-level singleton accessor. Reads `REDIS_URL` from settings on first call.

### `close_redis_client()`
Tears down the singleton. Call from app lifespan shutdown.

### `PriceCache(redis)`
- `await cache.set_price(symbol, price, timestamp)` -- store current price + meta timestamp
- `await cache.get_price(symbol) -> Decimal | None` -- fetch single price
- `await cache.get_all_prices() -> dict[str, Decimal]` -- snapshot of all prices
- `await cache.update_ticker(tick)` -- atomic Lua-based ticker update
- `await cache.get_ticker(symbol) -> TickerData | None` -- fetch 24h ticker
- `await cache.get_stale_pairs(threshold_seconds=60) -> list[str]` -- symbols with no update in N seconds

### `Tick` (NamedTuple)
Fields: `symbol`, `price` (Decimal), `quantity` (Decimal), `timestamp` (datetime), `is_buyer_maker` (bool), `trade_id` (int).

### `TickerData` (dataclass, slots=True)
Fields: `symbol`, `open`, `high`, `low`, `close`, `volume`, `change_pct`, `last_update`.

## Dependencies

- **`redis.asyncio`** (`redis-py` async driver) -- connection pool, pipeline, Lua scripting
- **`structlog`** -- structured logging for all error/warning paths
- **`src.config.get_settings`** -- lazy-imported inside `get_redis_client()` to avoid circular imports

### Downstream consumers (depend on this module)
- `src/dependencies.py` -- `get_price_cache()` creates `PriceCache` per request
- `src/price_ingestion/service.py` -- uses `RedisClient` for its own connection lifecycle
- `src/portfolio/tracker.py` -- reads prices via `PriceCache`
- `src/risk/manager.py` -- reads prices via `PriceCache`
- `src/battles/snapshot_engine.py` -- reads prices for unrealized PnL calculation
- `src/order_engine/` -- fetches current price for market order fills

## Common Tasks

**Get current price for a symbol:**
```python
price = await price_cache.get_price("BTCUSDT")  # Decimal or None
```

**Update price from ingestion tick:**
```python
await price_cache.set_price(tick.symbol, tick.price, tick.timestamp)
await price_cache.update_ticker(tick)
```

**Check for stale pairs (monitoring):**
```python
stale = await price_cache.get_stale_pairs(threshold_seconds=60)
```

**Use in FastAPI route (via dependency injection):**
```python
async def handler(cache: PriceCacheDep):
    prices = await cache.get_all_prices()
```

## Gotchas & Pitfalls

- **Singleton caching**: `get_redis_client()` is a module-level singleton. In tests, you must patch it before the cached instance is created, or use dependency injection overrides.
- **Non-transactional pipeline**: `set_price()` uses `transaction=False` on the pipeline. A reader may see a new price in `prices` before `prices:meta` is updated. This is a deliberate trade-off for throughput.
- **Ticker open price is sticky**: The Lua script only sets `open` on the first tick for a symbol. There is no daily reset logic in this module -- session resets must be handled externally.
- **All values are strings**: Redis stores everything as strings. `PriceCache` handles `Decimal` conversion on read, but direct Redis access returns raw strings.
- **Partial ticker hash**: If a `ticker:{symbol}` hash is partially written or evicted, `get_ticker()` returns `None` and logs a warning rather than raising.
- **`RedisError` is caught everywhere**: All public methods catch `RedisError` and return safe defaults (`None`, empty dict/list). Callers should handle `None` returns gracefully.
- **Never create ad-hoc Redis clients**: All Redis access must go through `RedisClient` or `get_redis_client()` to share the connection pool.

## Recent Changes

- `2026-03-17` -- Initial CLAUDE.md created
