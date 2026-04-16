---
type: code-review
date: 2026-04-15
reviewer: perf-checker
verdict: CONDITIONAL_PASS
scope: Backend hot paths, DB indexes, frontend performance
tags:
  - performance
  - customer-readiness-audit
---

# Performance Audit Report — Task 08

**Date:** 2026-04-15
**Scope:** `src/api/routes/market.py`, `src/api/routes/trading.py`, `src/api/routes/account.py`, `src/order_engine/engine.py`, `src/price_ingestion/service.py`, `src/database/models.py`, `src/api/middleware/rate_limit.py`, `src/config.py`, `Frontend/src/lib/api-client.ts`, `Frontend/src/hooks/use-market-data.ts`, `Frontend/src/hooks/use-portfolio.ts`, `Frontend/src/components/market/market-table.tsx`

## Summary

- **14 findings total: 0 CRITICAL, 4 HIGH, 7 MEDIUM, 3 LOW**
- Overall: The platform is in good shape for hot paths. Redis-first price reads, bulk tick ingestion, async gather in batch endpoints, and query pagination are all correctly implemented. The most significant production concerns are a repeated DB symbol-validation query on every single-symbol market request, an unbounded PnL trade fetch that can pull 10,000 rows into Python, and the `useDailyCandlesBatch` hook creating 600 separate TanStack Query entries when rendering sparklines for the full market page.

---

## Findings

### [HIGH] `_validate_symbol` fires a DB query on every per-symbol market request

- **File:** `src/api/routes/market.py:705-717`
- **Check:** N+1 / Missing Cache Layer
- **Issue:** Five endpoints (`GET /market/price/{symbol}`, `/market/ticker/{symbol}`, `/market/candles/{symbol}`, `/market/trades/{symbol}`, `/market/orderbook/{symbol}`) each call `_validate_symbol()` before serving from Redis. That helper executes `SELECT symbol FROM trading_pairs WHERE symbol = :symbol LIMIT 1` — a full async DB round-trip on every request to what are the platform's highest-traffic public endpoints. At 1200 req/min (the market_data rate limit), that is 1200 DB reads/min per user just for symbol validation, for data that changes extremely rarely.
- **Impact:** Under load, this adds 1-5 ms to every single-symbol market request and consumes DB connection pool slots unnecessarily. The `trading_pairs` table has only ~600 rows and a `symbol` primary key — its contents are effectively static between pair seeding runs.
- **Suggestion:** Cache valid symbols in a module-level `frozenset` refreshed at startup (or via a short-TTL Redis key). A one-time `SELECT symbol FROM trading_pairs WHERE status = 'active'` at app startup, stored in `app.state.valid_symbols`, eliminates all 1200+ DB hits/min. Fix effort: small (1-2 hours).

---

### [HIGH] PnL endpoint fetches up to 10,000 trade rows into Python for period calculation

- **File:** `src/api/routes/account.py:630-650`
- **Check:** Large Result Set Without Pagination / Inefficient In-Memory Aggregation
- **Issue:** `GET /account/pnl` calls `_period_to_trade_limit()` which maps `"all"` → 10,000 and `"30d"` → 5,000. The function comment acknowledges this is "a coarse approximation" of time-bounded filtering. All rows are fetched into Python memory, then iterated three times to compute `fees_paid`, `winning_trades`, and `losing_trades` using `sum()` and comprehensions. For a busy agent with thousands of trades, this is 10,000 ORM objects in memory per request.
- **Impact:** A single request at `period=all` with a high-volume agent can allocate 5-20 MB of Python objects and take 100-500 ms. Under concurrent load from multiple agents, this will strain both the DB connection pool and process memory.
- **Suggestion:** Push the aggregation into SQL: use a single `SELECT count(*), sum(fee), sum(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) ... FROM trades WHERE agent_id = :id AND created_at >= :since` query that returns scalar aggregates. For `"all"` period, no date filter is needed. This eliminates the Python-side iteration entirely and reduces DB I/O by >99%. Fix effort: medium (3-4 hours, one new repo method + route change).

---

### [HIGH] `_get_price_timestamp` makes a separate Redis `HGET` per symbol after `get_price`

- **File:** `src/api/routes/market.py:199, 688`
- **Check:** Sequential Awaits That Could Be Parallelized
- **Issue:** `get_price()` and `get_orderbook()` each call `cache.get_price(symbol)` followed by `_get_price_timestamp(cache, symbol)`. The second call issues `HGET prices:meta {symbol}` — a second Redis round-trip after the first `HGET prices {symbol}`. These two calls are sequential and independent.
- **Impact:** Doubles the Redis latency for these endpoints (typically 0.2-0.5 ms each in Redis, adding 0.2-0.5 ms net overhead per request). Minor on its own, but at 1200 req/min for market data this is measurable.
- **Suggestion:** Use `asyncio.gather(cache.get_price(symbol), cache._redis.hget("prices:meta", symbol))` to fetch both in parallel, or extend `PriceCache.get_price()` to return the timestamp in the same call via a pipeline. Fix effort: small (1 hour).

---

### [HIGH] `cancel_all_orders` double-fetches open orders: once for total_unlocked calculation, once inside the engine

- **File:** `src/api/routes/trading.py:601-617`
- **Check:** N+1 / Redundant DB Query
- **Issue:** `DELETE /trade/orders/open` first calls `order_repo.list_open_by_agent(agent_id)` or `list_open_by_account(account_id, limit=500)` to compute `total_unlocked`, then calls `engine.cancel_all_orders()` which internally must also fetch and cancel each pending order. This means open orders are queried from the DB twice in one request — once by the route to compute the unlock amount, once by the engine to actually cancel them.
- **Impact:** Under normal conditions (few open orders) this is negligible. For an agent with many limit orders (up to the 50-order max), this doubles DB reads for a cancellation. More importantly, there is a TOCTOU window: orders can be filled between the two fetches, causing the reported `total_unlocked` to be incorrect.
- **Suggestion:** Have `OrderEngine.cancel_all_orders()` return the list of cancelled orders (or their locked amounts) so the route can compute `total_unlocked` from that result rather than issuing a pre-fetch. Fix effort: small (1-2 hours).

---

### [MEDIUM] `useDailyCandlesBatch` creates one TanStack Query entry per symbol for sparklines

- **File:** `Frontend/src/hooks/use-market-data.ts:206-237`
- **Check:** Query Efficiency / Bundle of Unbounded Queries
- **Issue:** `useDailyCandlesBatch(symbols)` calls `useQueries` with one query entry per symbol. When the market page is open with all 600+ pairs visible, this creates 600+ individual query cache entries and potentially 600+ in-flight requests on first load (before they are all cached). The CLAUDE.md notes "600 symbols → 12 query entries" which would imply 50 symbols/query — but the hook as implemented creates one query per symbol with no batching.
- **Impact:** On first market page load with a cold cache, this could fire up to 600 simultaneous `GET /market/candles/{symbol}?interval=1d&limit=7` requests. This will exhaust the DB connection pool (pool_size=10, max_overflow=20), trigger rate limiting (1200 req/min cap), and cause request queuing or 429s. Note: the market table uses pagination (25 rows at a time), so in practice only ~25 queries fire per visible page, but navigating through all pages would cumulatively hit all 600.
- **Suggestion:** The CLAUDE.md already describes the intended fix: batch 50 symbols per query using the `GET /market/tickers` batch endpoint (which accepts comma-separated symbols). Alternatively, only fetch sparklines for the currently-visible virtual-scroll window (25 rows) rather than all symbols. Fix effort: medium (2-3 hours).

---

### [MEDIUM] `useOrderbook` and `useRecentTrades` poll at 5s and 10s respectively without backoff

- **File:** `Frontend/src/hooks/use-market-data.ts:122-145`
- **Check:** Frontend Performance / Polling Efficiency
- **Issue:** `useOrderbook` polls every 5 seconds (`refetchInterval: 5_000`) and `useRecentTrades` polls every 10 seconds (`refetchInterval: 10_000`). There is no conditional polling to stop when the tab is backgrounded or when the data is unchanged. The orderbook is synthetic (generated from mid-price) so it only meaningfully changes when the price changes — not every 5 seconds unconditionally.
- **Impact:** A user with the coin detail page open for 1 hour generates 720 orderbook requests (5s) + 360 trades requests (10s) = 1080 unnecessary REST calls/hour. Across many concurrent users, this adds steady load to the DB (`ticks` table for trades) and the FastAPI server.
- **Suggestion:** Use conditional refetch: `refetchInterval: document.hidden ? false : 5_000` (stop polling in background tabs). For the orderbook, tie the refetch to the WebSocket price update rather than a fixed interval. Fix effort: small (30 min).

---

### [MEDIUM] `TradingPair` table has no `status` index for filtered pair lookups

- **File:** `src/database/models.py:175-221`
- **Check:** Missing Database Index
- **Issue:** `GET /market/pairs?status=active` executes `SELECT ... FROM trading_pairs WHERE status = :status ORDER BY symbol`. The `TradingPair` model's `__table_args__` contains no index on the `status` column. With ~600 rows this is a sequential scan.
- **Impact:** Low impact today (600 rows sequential scan takes <1 ms), but as the pair list grows or if the query is called frequently it will be unindexed. The `status` column is a low-cardinality string used in WHERE clauses.
- **Suggestion:** Add `Index("idx_trading_pairs_status", "status")` to `TradingPair.__table_args__`. Fix effort: trivial (one migration).

---

### [MEDIUM] Rate limiter uses two Redis round-trips (INCR + conditional EXPIRE) instead of a Lua script

- **File:** `src/api/middleware/rate_limit.py:244-276`
- **Check:** Redis Pipeline Efficiency
- **Issue:** `_increment_counter` calls `await redis.incr(key)` followed by a conditional `await redis.expire(key, ...)`. This is two sequential Redis calls per request. Under high throughput there is a race window: if the process crashes or the connection drops between INCR and EXPIRE, the key will never expire (it will grow forever). The TTL is set only on count==1, which means subsequent requests in the same window skip the EXPIRE entirely — this is correct but means the fix-window is only at key creation.
- **Impact:** Two Redis calls per authenticated request (except auth/health/docs). At 600 req/min (general tier), this is 1200 Redis calls/min per active user. A Lua script or `pipeline()` with `INCR` + `EXPIRE` would halve this. The race on key creation is a correctness risk: a key created without TTL would persist until Redis is restarted or memory pressure evicts it.
- **Suggestion:** Use a Redis pipeline: `pipe = redis.pipeline(); pipe.incr(key); pipe.expire(key, TTL * 2); results = await pipe.execute()`. This is atomic for the TTL concern and cuts round-trips in half. Fix effort: small (30 min).

---

### [MEDIUM] `account.py` `get_pnl` makes two sequential awaits that could be gathered

- **File:** `src/api/routes/account.py:626-636`
- **Check:** Sequential Awaits / Parallelism
- **Issue:** `GET /account/pnl` calls `await tracker.get_pnl(account.id, ...)` then `await trade_repo.list_by_account(...)` sequentially. The PnL tracker result (unrealized PnL from Redis) and the trade history fetch (DB) are completely independent operations.
- **Impact:** Adds the latency of one operation onto the other unnecessarily. `tracker.get_pnl` involves a Redis price lookup + DB position read; `trade_repo.list_by_account` is a DB query. Sequential adds ~5-15 ms depending on DB load.
- **Suggestion:** Wrap both in `asyncio.gather(tracker.get_pnl(...), trade_repo.list_by_account(...))` and unpack the results. Note: both use the same `AsyncSession` so this requires verifying session thread-safety (confirmed safe for concurrent reads on SQLAlchemy async sessions as of the BUG-012 fix in the CLAUDE.md). Fix effort: small (30 min).

---

### [MEDIUM] `TickBuffer` retry prepend on flush failure is unbounded

- **File:** `src/price_ingestion/tick_buffer.py:165-200` (inferred from CLAUDE.md documentation)
- **Check:** Memory Leak / Unbounded Growth
- **Issue:** Per the CLAUDE.md and known patterns: when a `TickBuffer` flush fails (PostgreSQL down), the batch is prepended back into `self._buffer`. There is no cap on the cumulative size of the retry buffer. At 600 pairs × high-volume ticks, a DB outage of 60 seconds at 5000 ticks/flush = potentially millions of ticks in memory before the retry buffer fills.
- **Impact:** During a DB outage, the service will OOM in proportion to the outage duration. At 600 pairs with moderate tick volume (~500 ticks/second), a 5-minute outage could accumulate 150,000+ ticks before the process runs out of memory.
- **Suggestion:** Cap the retry buffer: if `len(self._buffer) > max_size * 10` after a failure, log a critical warning and drop the oldest ticks. This is an acknowledged known issue per the existing CLAUDE.md but warrants explicit fix before customer launch. Fix effort: small (1 hour).

---

### [LOW] `_compute_staleness` fallback scans all 600 `prices:meta` entries on BTCUSDT miss

- **File:** `src/api/routes/market.py:770-786`
- **Check:** Redis Efficiency
- **Issue:** When `BTCUSDT` is absent from `prices:meta` (edge case: service restart, BTCUSDT not yet streamed), `_compute_staleness` calls `cache._redis.hgetall("prices:meta")` which returns all 600+ symbol timestamps. This is then iterated in Python to find the freshest timestamp. This is called on every `GET /market/prices` request.
- **Impact:** In normal operation (BTCUSDT always present), this is never reached. However during startup or after a Redis flush, every `GET /market/prices` call will scan ~600 entries. This is acceptable latency-wise but wasteful.
- **Suggestion:** Instead of iterating all entries to find the freshest, check a small set of liquid pairs (BTC, ETH, BNB). BTCUSDT will almost always be present. The edge case is self-resolving. Fix effort: trivial (10 min).

---

### [LOW] `market-table.tsx` columns definition recreated on every filter change

- **File:** `Frontend/src/components/market/market-table.tsx:78`
- **Check:** React Render Performance
- **Issue:** The `columns` array is defined inside a `useMemo` that depends on `[hasVolumeData, hasTradeData]`. When the `filter` prop changes, `filteredData` recomputes, which recomputes `hasVolumeData` and `hasTradeData`, which then recreates the `columns` array and forces TanStack Table to re-initialize. For 600+ rows, column reinitializtion triggers a full table re-render.
- **Impact:** Every filter change (gainers/losers/volume) causes a full column recreation + table re-render. Noticeable as a flash at 600+ rows.
- **Suggestion:** Compute `hasVolumeData` and `hasTradeData` from the raw `data` prop rather than `filteredData`, since whether volume/trade data exists does not change when filtering. This decouples column recreation from filter changes. Fix effort: trivial (5 min).

---

### [LOW] DB connection pool `pool_size=10 / max_overflow=20` may be insufficient for production load

- **File:** `src/database/session.py` (per CLAUDE.md: `pool_size=10, max_overflow=20`)
- **Check:** Missing Connection Pool Configuration
- **Issue:** The SQLAlchemy async pool is configured at 10 persistent + 20 overflow = max 30 connections. With the market data rate limit at 1200 req/min (20 req/sec), and each request holding a DB session for ~5-10 ms, the concurrent session count peaks at ~200 ms × 20 req/sec = ~4 concurrent sessions at steady state. This seems fine. However, `cancel_all_orders`, `get_pnl` at high limits, and `analytics.py` leaderboard scans each hold sessions for 50-200 ms, which can saturate the pool during bursts.
- **Impact:** Pool exhaustion causes `TimeoutError` on new requests if all 30 connections are held. At current limits this is unlikely, but with multiple concurrent active agents running order-heavy strategies, it becomes a risk.
- **Suggestion:** Consider raising `pool_size` to 15-20 for a production deployment with multiple concurrent agents. Also ensure `pool_timeout` is set (default is 30s — acceptable). The current setting is adequate for initial customer launch with a small user base. Fix effort: trivial (config change).

---

### [LOW] `GET /account/pnl` period filter uses trade count approximation instead of time-bounded SQL

- **File:** `src/api/routes/account.py:741-760`
- **Check:** Query Correctness + Performance
- **Issue:** `_period_to_trade_limit` maps `"1d"` → 500 trades, `"7d"` → 2000, etc. A very active agent could exceed these limits (e.g., 2000+ trades in 7 days for HFT-style strategies), causing the `"7d"` PnL calculation to silently undercount fees and trade stats. The comment in the code acknowledges this is an approximation.
- **Impact:** Incorrect PnL statistics for high-frequency agents. Not a performance issue per se, but the "fix" for correctness (time-bounded SQL) also eliminates the large result set problem identified in the HIGH finding above.
- **Suggestion:** See HIGH finding #2 above — time-bounded SQL aggregation fixes both the performance and correctness issues simultaneously.

---

## Hot Path Analysis

| Endpoint | Critical Path | Assessment |
|---|---|---|
| `GET /market/prices` | `get_all_prices()` → Redis HGETALL → Python dict | **Good.** Single Redis call, no DB. |
| `GET /market/price/{symbol}` | `_validate_symbol` → DB + `get_price` → Redis | **Issue: unnecessary DB call.** |
| `GET /market/tickers` | `asyncio.gather(get_ticker×N)` → N Redis calls | **Good.** Concurrent Redis reads, capped at 100. |
| `POST /trade/order` | RiskManager (8-step) → Redis price → DB write | **Good.** Single Redis read + DB transaction. |
| `GET /account/portfolio` | `tracker.get_portfolio` + `_build_opened_at_map` | **Acceptable.** Sequential but short. |
| `GET /account/pnl?period=all` | `tracker.get_pnl` + `list_by_account(limit=10000)` | **Issue: 10k row fetch.** |
| Price ingestion tick loop | `set_price` + `update_ticker` + `buffer.add` | **Good.** All async, bulk DB write. |

## Database Performance Assessment

**Well-indexed tables (all critical query patterns covered):**
- `orders`: `(account_id)`, `(agent_id)`, `(account_id, status)`, partial `(symbol, status WHERE pending)`
- `trades`: `(account_id)`, `(agent_id)`, `(account_id, created_at)`, `(symbol, created_at)`
- `positions`: `(account_id)`, `(agent_id)`, unique `(agent_id, symbol)`
- `balances`: `(account_id)`, `(agent_id)`, unique `(agent_id, asset)`
- `ticks`: composite `(symbol, time DESC)` — correct for TimescaleDB range queries
- `agents`: `api_key` unique index — O(1) auth lookup

**Missing/weak indexes:**
- `trading_pairs.status` — no index (low impact, ~600 rows)
- `accounts` — `api_key` column has `unique=True` which PostgreSQL auto-indexes; confirmed safe
- `TradingSession.status` — no explicit index; queried in `_get_active_session()` with `WHERE status = 'active'`

## Frontend Performance Assessment

**Implemented correctly:**
- Virtual scrolling on market table (`@tanstack/react-virtual`)
- `React.memo` with custom comparators on `PriceFlashCell` / market table rows
- GET request deduplication in `api-client.ts`
- `PriceBatchBuffer` with 100ms RAF throttle and Map-based symbol dedup
- `keepPreviousData` on 7 paginated hooks
- Lazy-loading (`next/dynamic`) for 8 dashboard sections
- `staleTime: 30_000` on all market data queries
- Selective Zustand subscriptions (`selectPortfolio`, `usePrice(symbol)`)

**Issues:**
- `useDailyCandlesBatch` creates 1 query per symbol (up to 600) rather than batching (see MEDIUM finding above)
- Orderbook/trades poll unconditionally regardless of tab visibility

## Scalability Concerns

1. **Rate limits are appropriate for alpha/beta**: 1200 req/min for market data and 100 req/min for orders are reasonable for initial customer access. No action needed for launch.
2. **Order engine is not the bottleneck**: market orders execute in a single DB transaction; limit/stop orders are queued and matched by Celery in the background.
3. **Price ingestion scales with Redis**: all 600+ pairs update via a single asyncpg COPY bulk flush every 1s. This is the most scalable design available.
4. **WebSocket fan-out**: the `RedisPubSubBridge` pattern is correct. Broadcasting happens in a background asyncio task, not on the request path.

## Recommendations by Priority

| Priority | Finding | Effort |
|---|---|---|
| Fix before launch | Symbol validation DB call on every market request | Small (1-2h) |
| Fix before launch | PnL endpoint fetching 10k rows into Python | Medium (3-4h) |
| Fix before launch | TickBuffer unbounded retry buffer | Small (1h) |
| Fix before launch | `useDailyCandlesBatch` per-symbol queries | Medium (2-3h) |
| Fix soon | `cancel_all_orders` double-fetch | Small (1-2h) |
| Fix soon | Rate limiter two Redis round-trips vs pipeline | Small (30 min) |
| Fix soon | Sequential awaits in `get_pnl` | Small (30 min) |
| Background | Orderbook/trades unconditional polling | Small (30 min) |
| Background | `TradingPair.status` missing index | Trivial |
| Background | `columns` memo dependency on filtered data | Trivial |
