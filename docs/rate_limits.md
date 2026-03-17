# Rate Limits & Resource Constraints — Complete Reference

> **Audience:** Developers, SDK consumers, and ops engineers working with the AiTradingAgent platform.

---

## Table of Contents

1. [HTTP API Rate Limiting](#1-http-api-rate-limiting)
2. [Order-Level Rate Limiting (Risk Manager)](#2-order-level-rate-limiting-risk-manager)
3. [Risk Manager — 8-Step Validation Chain](#3-risk-manager--8-step-validation-chain)
4. [Circuit Breaker (Daily Loss Limit)](#4-circuit-breaker-daily-loss-limit)
5. [WebSocket Limits](#5-websocket-limits)
6. [Backtesting Engine Limits](#6-backtesting-engine-limits)
7. [Price Ingestion Limits](#7-price-ingestion-limits)
8. [Celery Task Limits](#8-celery-task-limits)
9. [Database Connection Pooling](#9-database-connection-pooling)
10. [API Pagination & Batch Limits](#10-api-pagination--batch-limits)
11. [Frontend Client Behavior](#11-frontend-client-behavior)
12. [Redis Key Reference](#12-redis-key-reference)
13. [Master Summary Table](#13-master-summary-table)
14. [Gotchas & Edge Cases](#14-gotchas--edge-cases)

---

## 1. HTTP API Rate Limiting

**Source:** `src/api/middleware/rate_limit.py`

### Algorithm

Sliding-window counter using Redis `INCR` with a **60-second window** (`_WINDOW_SECONDS = 60`). Each API key gets an independent counter per tier per minute bucket. The key auto-expires after **120 seconds** (2× window to handle boundary overlap).

### Three Rate-Limit Tiers

Tier is resolved by **first prefix match** against the request path:

| Path Prefix | Tier Name | Limit (req/min) | Use Case |
|-------------|-----------|-----------------|----------|
| `/api/v1/trade/` | `orders` | **100** | Order placement, cancellation, trade history |
| `/api/v1/market/` | `market_data` | **1,200** | Prices, candles, tickers, orderbook |
| `/api/v1/*` (catch-all) | `general` | **600** | Account, agents, analytics, backtests, battles |

All limits are **hardcoded constants** — not configurable via environment variables or settings. Changing them requires a code change.

### Public Paths (Bypass Rate Limiting)

These paths skip rate limiting entirely:

```
/api/v1/auth/*    (register, login)
/health
/docs
/redoc
/openapi.json
/metrics
```

### Response Headers

Every authenticated response includes:

| Header | Description | Example |
|--------|-------------|---------|
| `X-RateLimit-Limit` | Max requests per window | `600` |
| `X-RateLimit-Remaining` | Remaining requests in current window | `589` |
| `X-RateLimit-Reset` | Unix timestamp when window resets | `1710500160` |

These headers are exposed via CORS (`expose_headers` in `src/main.py`), so browser clients can read them.

### 429 Response

When the limit is exceeded:

```http
HTTP/1.1 429 Too Many Requests
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1710500160
Retry-After: 47
Content-Type: application/json

{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Too many requests.",
    "details": {
      "limit": 100,
      "window_seconds": 60,
      "retry_after_seconds": 47
    }
  }
}
```

### Fail-Open Policy

If Redis is unavailable or errors occur, the counter returns `0` and the request is **allowed through**. This is logged as `rate_limit.redis_error` but never blocks the request. A Redis outage effectively disables rate limiting.

### Middleware Execution Order

```
Request → LoggingMiddleware → AuthMiddleware → RateLimitMiddleware → Route Handler
```

Auth runs before rate limiter so `request.state.account` is populated. Unauthenticated requests are rejected by auth middleware before reaching rate limiting.

---

## 2. Order-Level Rate Limiting (Risk Manager)

**Source:** `src/risk/manager.py` (Step 3 of validation chain)

This is a **separate** rate limit from the HTTP middleware — it specifically counts successful order submissions (not HTTP requests).

| Setting | Default | Override Via |
|---------|---------|-------------|
| `order_rate_limit` | **100 orders/min** | Account `risk_profile` JSONB or Agent `risk_profile` JSONB |

### Key Differences from HTTP Rate Limit

| Aspect | HTTP Middleware | Order Rate Limit |
|--------|---------------|-----------------|
| Scope | Per API key, per tier | Per account/agent, orders only |
| Counts | All HTTP requests | Only orders that pass all validation |
| Redis key | `rate_limit:{api_key}:{group}:{bucket}` | `rate_limit:{scope_id}:orders:{minute}` |
| Rejected requests | Counted | **Not counted** |
| Configurable | No (hardcoded) | Yes (via `risk_profile` JSONB) |

### How It Works

```
1. Minute bucket = UTC time formatted as %Y%m%d%H%M
2. Scope = agent_id (if present) or account_id
3. Redis key = rate_limit:{scope_id}:orders:{minute_bucket}
4. If current_count >= limit → reject with "rate_limit_exceeded"
5. Token consumed ONLY after all 8 validation steps pass
```

---

## 3. Risk Manager — 8-Step Validation Chain

**Source:** `src/risk/manager.py`

Every order goes through these checks in sequence (short-circuits on first failure):

| Step | Check | Default Limit | Rejection Code |
|------|-------|--------------|----------------|
| 1 | Account is active | — | `account_not_active` |
| 2 | Daily loss limit (circuit breaker) | 20% of starting balance | `daily_loss_limit` |
| 3 | Order rate limit | 100 orders/min | `rate_limit_exceeded` |
| 4 | Minimum order size | $1.00 USD | `order_too_small` |
| 5 | Maximum order size | 50% of equity | `order_too_large` |
| 6 | Position size limit | 25% of equity | `position_limit_exceeded` |
| 7 | Max open orders | 50 concurrent | `max_open_orders_exceeded` |
| 8 | Sufficient balance | Account balance | `insufficient_balance` |

### Default Risk Constants

```python
_DEFAULT_MAX_POSITION_SIZE_PCT = Decimal("25")    # 25% of equity
_DEFAULT_MAX_OPEN_ORDERS       = 50               # concurrent pending orders
_DEFAULT_DAILY_LOSS_LIMIT_PCT  = Decimal("20")    # 20% of starting balance
_DEFAULT_MIN_ORDER_SIZE_USD    = Decimal("1.0")   # $1.00 minimum
_DEFAULT_MAX_ORDER_SIZE_PCT    = Decimal("50")    # 50% of equity
_DEFAULT_ORDER_RATE_LIMIT      = 100              # orders per minute
```

All defaults can be overridden per-account or per-agent via the `risk_profile` JSONB column.

---

## 4. Circuit Breaker (Daily Loss Limit)

**Source:** `src/risk/circuit_breaker.py`

Halts all trading for an account/agent when cumulative daily PnL exceeds the loss threshold.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `daily_loss_limit_pct` | 20% | Max daily loss as % of starting balance |

### Redis Schema

| Key | Fields | TTL |
|-----|--------|-----|
| `circuit_breaker:{account_id}` | `daily_pnl`, `tripped`, `tripped_at` | Auto-expires at midnight UTC |

### Reset Mechanism

- **Primary:** Redis TTL auto-expires keys at midnight UTC
- **Belt-and-suspenders:** Celery beat task at **00:01 UTC** scans and resets all circuit breaker keys (batch size: 1,000 keys per SCAN page)

---

## 5. WebSocket Limits

**Source:** `src/api/websocket/manager.py`

| Limit | Value | Description |
|-------|-------|-------------|
| Max subscriptions per connection | **10** | Error `SUBSCRIPTION_LIMIT` on 11th |
| Ping interval | **30 seconds** | Server sends ping every 30s |
| Pong timeout | **10 seconds** | Client must respond within 10s or disconnected |
| Auth failure close code | **4401** | WebSocket close on invalid API key |

### Heartbeat Protocol

1. Server sends `{"type": "ping"}` every 30 seconds
2. Client must respond with `{"action": "pong"}` within 10 seconds
3. Timeout → automatic disconnect with cleanup of all subscriptions and tasks

> **Note:** This is an application-level heartbeat (JSON messages), not WebSocket protocol-level ping/pong frames.

### Authentication

- Query param: `ws://localhost:8000/ws/v1?api_key=ak_live_...`
- Validated on connection open; close code 4401 on failure

---

## 6. Backtesting Engine Limits

**Source:** `src/backtesting/sandbox.py`, `src/backtesting/engine.py`

### Slippage Clamping

```python
_MIN_SLIPPAGE = Decimal("0.0001")  # 0.01%
_MAX_SLIPPAGE = Decimal("0.10")    # 10%
```

### Fee Model

```python
_FEE_FRACTION = Decimal("0.001")   # 0.1% per trade
```

### Resource Usage Controls

| Parameter | Value | Description |
|-----------|-------|-------------|
| Snapshot frequency | Every **60 steps** | Portfolio snapshots saved to DB |
| DB progress writes | Every **500 steps** | Backtest progress updated in DB |
| Data preload | Full dataset at `start()` | Single SQL UNION query; zero per-step DB queries |
| Price lookup | O(log n) via `bisect_right` | In-memory binary search |

### Risk Limits in Sandbox

The backtest sandbox reimplements risk checks independently:
- `max_order_size_pct` (configurable per backtest)
- `max_position_size_pct` (configurable per backtest)
- `daily_loss_limit_pct` (configurable per backtest)

> **Warning:** Changes to live risk logic do NOT auto-propagate to the backtest sandbox — they are separate implementations.

---

## 7. Price Ingestion Limits

**Source:** `src/price_ingestion/`

### Tick Buffer

| Setting | Default | Env Var | Description |
|---------|---------|---------|-------------|
| Flush interval | 1.0s | `TICK_FLUSH_INTERVAL` | Time-based flush trigger |
| Buffer max size | 5,000 | `TICK_BUFFER_MAX_SIZE` | Size-based flush trigger |

Flushing occurs on **whichever comes first**: interval elapsed or buffer full.

### Binance WebSocket

| Limit | Value | Description |
|-------|-------|-------------|
| Max streams per connection | **1,024** | Symbols partitioned into chunks for separate connections |
| Reconnect backoff | 1s → 60s max | Exponential backoff on disconnect |
| Tick queue capacity | **50,000** | `asyncio.Queue(maxsize=50_000)` — backpressure limit |

### HTTP Timeouts (Data Fetching)

| Operation | Timeout |
|-----------|---------|
| Exchange info fetch | 30 seconds |
| Klines fetch | 15 seconds |
| Max candles per request | 1,000 (Binance API limit) |

### Bulk Insert

- Uses asyncpg `COPY` for batch inserts (not row-by-row)
- On failure: batch is retained and prepended for retry on next flush
- **Risk:** Persistent DB outage causes unbounded memory growth (failed batches accumulate)

---

## 8. Celery Task Limits

**Source:** `src/tasks/celery_app.py`

### Global Defaults

```python
task_soft_time_limit = 55   # SIGTERM after 55s
task_time_limit      = 60   # SIGKILL after 60s
visibility_timeout   = 300  # Must exceed task_time_limit
max_retries          = 0    # No retries; next beat invocation is implicit retry
```

### Per-Task Schedule & Limits

| Task | Interval | Soft Limit | Hard Limit | Queue |
|------|----------|-----------|-----------|-------|
| `limit-order-monitor` | Every 1s | 2s | 5s | `high_priority` |
| `aggregate-candles` | Every 1 min | 55s | 60s | `default` |
| `capture-battle-snapshots` | Every 5s | 10s | 15s | `default` |
| `capture-portfolio-snapshots` | Every 1 hour | 55s | 60s | `default` |
| `capture-hourly-battle-snapshots` | Every 1 hour | 30s | 45s | `default` |
| `capture-daily-snapshots` | Daily @ 00:00 UTC | 110s | 120s | `default` |
| `cleanup-expired-orders` | Daily @ 06:00 UTC | 110s | 120s | `default` |
| `reset-circuit-breakers` | Daily @ 00:01 UTC | 55s | 60s | `default` |

### Batch Processing

| Context | Batch Size |
|---------|-----------|
| Limit order matcher pagination | 500 orders per page |
| Account batch processing | 100 accounts per batch |
| Circuit breaker SCAN | 1,000 keys per cursor page |

---

## 9. Database Connection Pooling

**Source:** `src/database/session.py`

### SQLAlchemy AsyncEngine

| Parameter | Value | Description |
|-----------|-------|-------------|
| `pool_size` | 10 | Minimum concurrent connections |
| `max_overflow` | 20 | Additional connections beyond pool |
| `pool_pre_ping` | True | Verify connection before reuse |
| `pool_recycle` | 3,600s (1 hour) | Recycle connections after this duration |

**Effective max connections:** 10 + 20 = **30 concurrent connections**

### Raw asyncpg Pool (Bulk Inserts)

| Parameter | Value |
|-----------|-------|
| `min_size` | 2 |
| `max_size` | 10 |
| `command_timeout` | 60 seconds |

---

## 10. API Pagination & Batch Limits

### Pagination Limits per Endpoint

| Endpoint | Min | Default | Max |
|----------|-----|---------|-----|
| `GET /trade/orders` | 1 | 100 | **500** |
| `GET /trade/positions` | 1 | 100 | **200** |
| `GET /trade/history` | 1 | 50 | **500** |
| `GET /agents` | 1 | 100 | **500** |
| `GET /backtest/{id}/candles` | 1 | 100 | **1,000** |
| `GET /backtest/trades` | 1 | 1,000 | **10,000** |
| `GET /backtest/snapshots` | 1 | 50 | **200** |
| `GET /battles` | 1 | 50 | **200** |
| `GET /battles/{id}/snapshots` | 1 | 10,000 | **100,000** |

### Batch Endpoints

| Endpoint | Max Items |
|----------|-----------|
| `GET /market/tickers/batch` | **100 symbols** (`_MAX_BATCH_SYMBOLS`) |
| `POST /backtest/{id}/step/batch` | No hard cap |
| `POST /battles/{id}/step/batch` | No hard cap |

### Other Computed Limits

| Context | Limit |
|---------|-------|
| Leaderboard max accounts | 200 (`_LEADERBOARD_MAX_ACCOUNTS`) |

---

## 11. Frontend Client Behavior

### HTTP Client (`Frontend/src/lib/api-client.ts`)

| Setting | Value |
|---------|-------|
| Request timeout | **4 seconds** (`REQUEST_TIMEOUT_MS`) |
| Max retries | **1** (on 5xx only) |
| Retry delay | 1 second (flat, not exponential) |
| 429 handling | Throws `ApiClientError` with server error code |

### WebSocket Client (`Frontend/src/lib/websocket-client.ts`)

| Setting | Value |
|---------|-------|
| Reconnect backoff | 1s base → 60s max (exponential) |
| Auto-resubscribe | Yes (all channels on reconnect) |
| Heartbeat | Responds to server `{"type":"ping"}` with `{"type":"pong"}` |

### TanStack Query Stale Times

| Data Type | Stale Time | Refetch Interval |
|-----------|-----------|-----------------|
| Market data | 30s | — |
| Candles | 5–10 min | — |
| Recent trades | — | 10s |
| Orderbook | — | 5s |
| Trading pairs | 5 min | — |
| Trade history | 30s | — |

---

## 12. Redis Key Reference

| Pattern | Purpose | TTL |
|---------|---------|-----|
| `rate_limit:{api_key}:{group}:{bucket}` | HTTP middleware rate limit counter | 120s |
| `rate_limit:{scope_id}:orders:{minute}` | Order submission rate limit | 120s |
| `circuit_breaker:{account_id}` | Daily PnL tracker + trip state | Until midnight UTC |
| `prices` (HSET) | Current prices: `{SYMBOL} → {price}` | None (always fresh) |

---

## 13. Master Summary Table

| Component | Limit Type | Value | Configurable? | Location |
|-----------|-----------|-------|--------------|----------|
| **HTTP — Orders tier** | Requests/min | 100 | No (hardcoded) | `middleware/rate_limit.py` |
| **HTTP — Market tier** | Requests/min | 1,200 | No (hardcoded) | `middleware/rate_limit.py` |
| **HTTP — General tier** | Requests/min | 600 | No (hardcoded) | `middleware/rate_limit.py` |
| **Risk — Order rate** | Orders/min | 100 | Yes (`risk_profile`) | `risk/manager.py` |
| **Risk — Max open orders** | Count | 50 | Yes (`risk_profile`) | `risk/manager.py` |
| **Risk — Max position size** | % of equity | 25% | Yes (`risk_profile`) | `risk/manager.py` |
| **Risk — Max order size** | % of equity | 50% | Yes (`risk_profile`) | `risk/manager.py` |
| **Risk — Min order value** | USD | $1.00 | Yes (`risk_profile`) | `risk/manager.py` |
| **Risk — Daily loss limit** | % of balance | 20% | Yes (`risk_profile`) | `risk/circuit_breaker.py` |
| **WebSocket — Subscriptions** | Per connection | 10 | No (hardcoded) | `websocket/manager.py` |
| **WebSocket — Pong timeout** | Seconds | 10 | No (hardcoded) | `websocket/manager.py` |
| **WebSocket — Ping interval** | Seconds | 30 | No (hardcoded) | `websocket/manager.py` |
| **Ingestion — Buffer size** | Ticks | 5,000 | Yes (`TICK_BUFFER_MAX_SIZE`) | `config.py` |
| **Ingestion — Flush interval** | Seconds | 1.0 | Yes (`TICK_FLUSH_INTERVAL`) | `config.py` |
| **Ingestion — Queue capacity** | Ticks | 50,000 | No (hardcoded) | `price_ingestion/` |
| **Ingestion — Streams/conn** | Count | 1,024 | No (hardcoded) | `price_ingestion/` |
| **Celery — Soft time limit** | Seconds | 55 | No (hardcoded) | `tasks/celery_app.py` |
| **Celery — Hard time limit** | Seconds | 60 | No (hardcoded) | `tasks/celery_app.py` |
| **DB — Pool size** | Connections | 10 | No (hardcoded) | `database/session.py` |
| **DB — Max overflow** | Connections | 20 | No (hardcoded) | `database/session.py` |
| **DB — asyncpg pool** | Connections | 2–10 | No (hardcoded) | `database/session.py` |
| **Pagination — Orders** | Max per page | 500 | No (schema) | Route schemas |
| **Pagination — Trades** | Max per page | 10,000 | No (schema) | Route schemas |
| **Batch — Tickers** | Symbols | 100 | No (hardcoded) | `routes/market.py` |
| **Frontend — Timeout** | Seconds | 4 | No (hardcoded) | `api-client.ts` |
| **Frontend — Retries** | Count | 1 | No (hardcoded) | `api-client.ts` |
| **Slippage — Min** | Fraction | 0.01% | No (hardcoded) | `order_engine/slippage.py` |
| **Slippage — Max** | Fraction | 10% | No (hardcoded) | `order_engine/slippage.py` |
| **Trading Fee** | Fraction | 0.1% | No (hardcoded) | `order_engine/slippage.py` |

---

## 14. Gotchas & Edge Cases

1. **Two separate rate limit systems.** The HTTP middleware (`rate_limit.py`) and the Risk Manager (`manager.py`) both enforce order rate limits independently. A request can pass one but fail the other.

2. **Rejected orders don't consume tokens.** In the Risk Manager, the rate limit counter is incremented only after all 8 validation steps pass. Failed orders are "free."

3. **Redis failure = no rate limiting.** The HTTP middleware fails open — if Redis is down, all requests are allowed through. Monitor `rate_limit.redis_error` logs.

4. **Backtest sandbox has separate risk logic.** `BacktestSandbox._check_risk_limits()` is an independent reimplementation. Changes to `RiskManager` don't auto-propagate.

5. **Slippage clamped twice.** Both `SlippageCalculator` (live) and `BacktestSandbox` independently clamp between 0.01% and 10%.

6. **Price ingestion can OOM.** If the database is persistently down, failed tick batches are retained in memory and prepended for retry, causing unbounded growth.

7. **Circuit breaker double-reset.** TTL expiry at midnight UTC and Celery task at 00:01 UTC both reset — this is intentional belt-and-suspenders.

8. **WebSocket heartbeat is app-level.** Clients must send `{"action": "pong"}` JSON, not WebSocket protocol PONG frames.

9. **All HTTP rate limits are hardcoded.** No env vars or settings — changing limits requires a code deployment.

10. **Per-agent risk overrides.** When an agent has a `risk_profile`, it fully overrides the account-level defaults. Multi-agent accounts can have wildly different limits per agent.

---

<!-- last-updated: 2026-03-17 -->
