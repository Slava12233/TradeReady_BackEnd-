# AgentExchange — REST API Reference

**Base URL:** `http://localhost:8000/api/v1`  
**OpenAPI docs:** `http://localhost:8000/docs` (Swagger UI) · `http://localhost:8000/redoc`

---

## Contents

1. [Authentication](#authentication)
2. [Common Headers & Response Format](#common-headers--response-format)
3. [Rate Limits](#rate-limits)
4. [Auth Endpoints](#auth-endpoints)
5. [Market Data Endpoints](#market-data-endpoints)
6. [Trading Endpoints](#trading-endpoints)
7. [Account Endpoints](#account-endpoints)
8. [Analytics Endpoints](#analytics-endpoints)
9. [Error Codes](#error-codes)
10. [WebSocket Reference](#websocket-reference)

---

## Authentication

Every endpoint except `POST /auth/register` and `POST /auth/login` requires authentication. Two methods are supported:

### Option A — API Key (recommended)

Include the `X-API-Key` header in every request:

```
X-API-Key: ak_live_<your_api_key>
```

### Option B — JWT Bearer Token

Exchange your API key + secret for a short-lived JWT, then include it as a Bearer token:

```
Authorization: Bearer <token>
```

Tokens expire after 1 hour (configurable via `JWT_EXPIRY_HOURS`). Call `POST /auth/login` again to refresh.

---

## Common Headers & Response Format

### Request Headers

| Header | Required | Description |
|---|---|---|
| `Content-Type` | Yes (POST/PUT) | Must be `application/json` |
| `X-API-Key` | Yes (or Bearer) | API key credential |
| `Authorization` | Yes (or X-API-Key) | `Bearer <jwt_token>` |

### Response Headers

Every response includes rate-limit headers:

```
X-RateLimit-Limit: 600
X-RateLimit-Remaining: 423
X-RateLimit-Reset: 1708000060
```

### Success Response

HTTP 200 or 201 with a JSON body specific to each endpoint.

### Error Response

All errors use this consistent structure:

```json
{
  "error": {
    "code": "INVALID_SYMBOL",
    "message": "Symbol 'XXXUSDT' is not a valid trading pair."
  }
}
```

### Decimal Precision

All monetary and quantity values are returned as **decimal strings** (e.g. `"64521.30000000"`) to preserve 8-decimal precision. Send request values as strings or numbers — both are accepted.

---

## Rate Limits

| Endpoint Group | Limit | Window |
|---|---|---|
| Market data (`GET /market/*`) | 1200 requests | per minute |
| Trading (`POST`/`DELETE /trade/*`) | 100 requests | per minute |
| Account (`GET /account/*`) | 600 requests | per minute |
| Analytics (`GET /analytics/*`) | 120 requests | per minute |

When a limit is exceeded, the server returns HTTP 429 with `RATE_LIMIT_EXCEEDED`. Wait until the `X-RateLimit-Reset` Unix timestamp before retrying. The `Retry-After` header (seconds) is also included.

---

## Auth Endpoints

### POST /auth/register

Create a new virtual-trading agent account. Returns credentials **once only** — the `api_secret` is never shown again.

**Auth required:** No

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `display_name` | string | Yes | Human-readable name for the account (1–64 chars) |
| `email` | string (email) | No | Optional contact email |
| `starting_balance` | decimal string | No | Initial USDT balance (default: `"10000.00"`) |

**Response: HTTP 201**

| Field | Type | Description |
|---|---|---|
| `account_id` | UUID string | Permanent account identifier |
| `api_key` | string | API key with `ak_live_` prefix — use in `X-API-Key` header |
| `api_secret` | string | API secret with `sk_live_` prefix — **shown once, save immediately** |
| `display_name` | string | The name you registered with |
| `starting_balance` | decimal string | USDT balance the account was seeded with |
| `message` | string | Reminder to save the secret |

**Errors:**

| Code | HTTP | Condition |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Missing `display_name` or invalid field format |
| `DUPLICATE_ACCOUNT` | 409 | Email already registered |
| `INTERNAL_ERROR` | 500 | Database failure |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"display_name": "AlphaBot", "email": "alpha@example.com", "starting_balance": "10000.00"}'
```

**Response example:**

```json
{
  "account_id": "550e8400-e29b-41d4-a716-446655440000",
  "api_key": "ak_live_Hx3kP9...",
  "api_secret": "sk_live_Qz7mR2...",
  "display_name": "AlphaBot",
  "starting_balance": "10000.00",
  "message": "Save your API secret now. It will not be shown again."
}
```

---

### POST /auth/login

Exchange an API key + secret for a signed JWT bearer token.

**Auth required:** No

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `api_key` | string | Yes | Your `ak_live_` prefixed API key |
| `api_secret` | string | Yes | Your `sk_live_` prefixed API secret |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `token` | string | Signed HS256 JWT |
| `expires_at` | ISO-8601 datetime | Token expiry time (UTC) |
| `token_type` | string | Always `"Bearer"` |

**Errors:**

| Code | HTTP | Condition |
|---|---|---|
| `INVALID_API_KEY` | 401 | API key not found |
| `INVALID_TOKEN` | 401 | API secret does not match |
| `ACCOUNT_SUSPENDED` | 403 | Account is suspended or archived |
| `ACCOUNT_NOT_FOUND` | 404 | No account owns the provided API key |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"api_key": "ak_live_Hx3kP9...", "api_secret": "sk_live_Qz7mR2..."}'
```

**Response example:**

```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_at": "2026-02-26T13:00:00Z",
  "token_type": "Bearer"
}
```

---

## Market Data Endpoints

All market endpoints are **public** (no authentication required). They read from the Redis price cache for sub-millisecond lookups, falling back to TimescaleDB for historical data.

---

### GET /market/pairs

List all trading pairs with exchange filter rules.

**Auth required:** No

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `status` | string | No | Filter by pair status: `"active"` or `"inactive"` |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `pairs` | array | List of trading pair objects |
| `total` | integer | Total number of pairs returned |

**Pair object:**

| Field | Type | Description |
|---|---|---|
| `symbol` | string | Trading pair symbol (e.g. `"BTCUSDT"`) |
| `base_asset` | string | Base currency (e.g. `"BTC"`) |
| `quote_asset` | string | Quote currency (e.g. `"USDT"`) |
| `status` | string | `"active"` or `"inactive"` |
| `min_qty` | decimal string | Minimum order quantity |
| `step_size` | decimal string | Quantity increment (lot size) |
| `min_notional` | decimal string | Minimum order value in USDT |

**Errors:**

| Code | HTTP | Condition |
|---|---|---|
| `INTERNAL_ERROR` | 500 | Database failure |

**curl example:**

```bash
curl http://localhost:8000/api/v1/market/pairs?status=active
```

**Response example:**

```json
{
  "pairs": [
    {
      "symbol": "BTCUSDT",
      "base_asset": "BTC",
      "quote_asset": "USDT",
      "status": "active",
      "min_qty": "0.00001000",
      "step_size": "0.00001000",
      "min_notional": "1.00000000"
    }
  ],
  "total": 647
}
```

---

### GET /market/price/{symbol}

Get the current live price for a single trading pair from the Redis cache.

**Auth required:** No

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `symbol` | string | Trading pair symbol (case-insensitive, e.g. `BTCUSDT`) |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `symbol` | string | Uppercase trading pair symbol |
| `price` | decimal string | Current mid-price (8 decimal places) |
| `timestamp` | ISO-8601 datetime | Time of the last price update (UTC) |

**Errors:**

| Code | HTTP | Condition |
|---|---|---|
| `INVALID_SYMBOL` | 400 | Symbol not found in trading pairs |
| `PRICE_NOT_AVAILABLE` | 503 | No live price in cache yet; retry in a few seconds |

**curl example:**

```bash
curl http://localhost:8000/api/v1/market/price/BTCUSDT
```

**Response example:**

```json
{
  "symbol": "BTCUSDT",
  "price": "64521.30000000",
  "timestamp": "2026-02-26T10:00:00.123456Z"
}
```

---

### GET /market/prices

Get current prices for all pairs (or a filtered subset) in one call.

**Auth required:** No

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `symbols` | string | No | Comma-separated list of symbols to include, e.g. `BTCUSDT,ETHUSDT`. Omit to return all. |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `prices` | object | Map of `symbol → price string` |
| `timestamp` | ISO-8601 datetime | Server time of the response (UTC) |
| `count` | integer | Number of symbols included |

**curl example:**

```bash
# All prices
curl http://localhost:8000/api/v1/market/prices

# Filtered
curl "http://localhost:8000/api/v1/market/prices?symbols=BTCUSDT,ETHUSDT,SOLUSDT"
```

**Response example:**

```json
{
  "prices": {
    "BTCUSDT": "64521.30000000",
    "ETHUSDT": "3421.50000000",
    "SOLUSDT": "142.80000000"
  },
  "timestamp": "2026-02-26T10:00:00Z",
  "count": 3
}
```

---

### GET /market/ticker/{symbol}

Get 24-hour rolling OHLCV statistics for a symbol.

**Auth required:** No

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `symbol` | string | Trading pair symbol (e.g. `ETHUSDT`) |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `symbol` | string | Trading pair symbol |
| `open` | decimal string | Opening price 24 hours ago |
| `high` | decimal string | Highest price in last 24 hours |
| `low` | decimal string | Lowest price in last 24 hours |
| `close` | decimal string | Most recent price |
| `volume` | decimal string | Base asset volume traded in last 24 hours |
| `quote_volume` | decimal string | Quote asset (USDT) volume |
| `change` | decimal string | Absolute price change (`close - open`) |
| `change_pct` | decimal string | Percentage price change |
| `trade_count` | integer | Number of trades in last 24 hours |
| `timestamp` | ISO-8601 datetime | Timestamp of last update |

**Errors:**

| Code | HTTP | Condition |
|---|---|---|
| `INVALID_SYMBOL` | 400 | Symbol not found |
| `PRICE_NOT_AVAILABLE` | 503 | No ticker data in cache yet |

**curl example:**

```bash
curl http://localhost:8000/api/v1/market/ticker/ETHUSDT
```

**Response example:**

```json
{
  "symbol": "ETHUSDT",
  "open": "3380.00000000",
  "high": "3450.00000000",
  "low": "3360.00000000",
  "close": "3421.50000000",
  "volume": "185432.12000000",
  "quote_volume": "634226157.18000000",
  "change": "41.50000000",
  "change_pct": "1.23000000",
  "trade_count": 892341,
  "timestamp": "2026-02-26T10:00:00Z"
}
```

---

### GET /market/candles/{symbol}

Get historical OHLCV candle data from TimescaleDB continuous aggregates.

**Auth required:** No

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `symbol` | string | Trading pair symbol (e.g. `BTCUSDT`) |

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `interval` | string | No | `"1h"` | Candle interval: `"1m"`, `"5m"`, `"1h"`, `"1d"` |
| `limit` | integer | No | `100` | Number of candles to return (1–1000) |
| `start_time` | ISO-8601 datetime | No | — | Start of time range (UTC, inclusive) |
| `end_time` | ISO-8601 datetime | No | — | End of time range (UTC, inclusive) |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `symbol` | string | Trading pair symbol |
| `interval` | string | Requested candle interval |
| `candles` | array | List of candle objects (oldest-first) |
| `count` | integer | Number of candles returned |

**Candle object:**

| Field | Type | Description |
|---|---|---|
| `time` | ISO-8601 datetime | Candle open time (UTC) |
| `open` | decimal string | Opening price |
| `high` | decimal string | Highest price in the interval |
| `low` | decimal string | Lowest price in the interval |
| `close` | decimal string | Closing price |
| `volume` | decimal string | Base asset volume |
| `trade_count` | integer | Number of trades in the candle |

**Errors:**

| Code | HTTP | Condition |
|---|---|---|
| `INVALID_SYMBOL` | 400 | Symbol not found or unsupported interval |

**curl example:**

```bash
# Last 24 hourly candles
curl "http://localhost:8000/api/v1/market/candles/BTCUSDT?interval=1h&limit=24"

# Daily candles for a specific range
curl "http://localhost:8000/api/v1/market/candles/BTCUSDT?interval=1d&start_time=2026-02-01T00:00:00Z&end_time=2026-02-26T00:00:00Z"
```

**Response example:**

```json
{
  "symbol": "BTCUSDT",
  "interval": "1h",
  "candles": [
    {
      "time": "2026-02-25T09:00:00Z",
      "open": "64200.00000000",
      "high": "64600.00000000",
      "low": "64100.00000000",
      "close": "64521.30000000",
      "volume": "1234.56700000",
      "trade_count": 18432
    }
  ],
  "count": 24
}
```

---

### GET /market/trades/{symbol}

Get recent public trade ticks from the tick history.

**Auth required:** No

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `symbol` | string | Trading pair symbol (e.g. `BTCUSDT`) |

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `limit` | integer | No | `100` | Number of recent trades to return (1–500) |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `symbol` | string | Trading pair symbol |
| `trades` | array | List of trade objects (newest-first) |

**Trade object:**

| Field | Type | Description |
|---|---|---|
| `trade_id` | integer | Binance trade ID |
| `price` | decimal string | Trade execution price |
| `quantity` | decimal string | Trade quantity (base asset) |
| `time` | ISO-8601 datetime | Trade execution time (UTC) |
| `is_buyer_maker` | boolean | `true` if the buyer was the market maker |

**Errors:**

| Code | HTTP | Condition |
|---|---|---|
| `INVALID_SYMBOL` | 400 | Symbol not found |

**curl example:**

```bash
curl "http://localhost:8000/api/v1/market/trades/BTCUSDT?limit=50"
```

**Response example:**

```json
{
  "symbol": "BTCUSDT",
  "trades": [
    {
      "trade_id": 3123456789,
      "price": "64521.30000000",
      "quantity": "0.01200000",
      "time": "2026-02-26T10:00:00.543Z",
      "is_buyer_maker": false
    }
  ]
}
```

---

### GET /market/orderbook/{symbol}

Get a simulated order book snapshot generated from the current mid-price.

> **Note:** This is a simulation. Depth does not reflect real Binance liquidity. Quantities are synthetic and seeded deterministically from the current price.

**Auth required:** No

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `symbol` | string | Trading pair symbol (e.g. `BTCUSDT`) |

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `depth` | integer | No | `10` | Number of levels per side: `5`, `10`, or `20` |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `symbol` | string | Trading pair symbol |
| `bids` | array | Bid levels — `[price_str, qty_str]` pairs, highest-price first |
| `asks` | array | Ask levels — `[price_str, qty_str]` pairs, lowest-price first |
| `timestamp` | ISO-8601 datetime | Snapshot time (UTC) |

**Errors:**

| Code | HTTP | Condition |
|---|---|---|
| `INVALID_SYMBOL` | 400 | Symbol not found or invalid `depth` value |
| `PRICE_NOT_AVAILABLE` | 503 | No live price in cache yet |

**curl example:**

```bash
curl "http://localhost:8000/api/v1/market/orderbook/BTCUSDT?depth=5"
```

**Response example:**

```json
{
  "symbol": "BTCUSDT",
  "bids": [
    ["64514.87", "1.234"],
    ["64508.44", "2.891"]
  ],
  "asks": [
    ["64527.73", "0.987"],
    ["64534.16", "3.456"]
  ],
  "timestamp": "2026-02-26T10:00:00Z"
}
```

---

## Trading Endpoints

All trading endpoints require authentication (`X-API-Key` or `Authorization: Bearer`).

---

### POST /trade/order

Place a market, limit, stop-loss, or take-profit order.

The request passes through an 8-step risk validation chain before execution. Market orders fill immediately; all other types are queued as `pending`.

**Auth required:** Yes

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `symbol` | string | Yes | Trading pair symbol (e.g. `"BTCUSDT"`) — case-insensitive |
| `side` | string | Yes | `"buy"` or `"sell"` |
| `type` | string | Yes | `"market"`, `"limit"`, `"stop_loss"`, or `"take_profit"` |
| `quantity` | decimal string | Yes | Order quantity in base asset |
| `price` | decimal string | For `limit` | Limit price (required for `limit` type) |
| `trigger_price` | decimal string | For `stop_loss`/`take_profit` | Trigger price for conditional orders |

**Response: HTTP 201**

**For market orders (status = `"filled"`):**

| Field | Type | Description |
|---|---|---|
| `order_id` | UUID string | Unique order identifier |
| `status` | string | `"filled"` |
| `symbol` | string | Trading pair symbol |
| `side` | string | `"buy"` or `"sell"` |
| `type` | string | `"market"` |
| `requested_quantity` | decimal string | Quantity requested |
| `executed_quantity` | decimal string | Quantity actually filled |
| `executed_price` | decimal string | Actual fill price (includes slippage) |
| `slippage_pct` | decimal string | Slippage applied as a percentage |
| `fee` | decimal string | Trading fee in USDT |
| `total_cost` | decimal string | Total USDT debited (buy) or received (sell) |
| `filled_at` | ISO-8601 datetime | Fill timestamp (UTC) |

**For pending orders (status = `"pending"`):**

| Field | Type | Description |
|---|---|---|
| `order_id` | UUID string | Unique order identifier |
| `status` | string | `"pending"` |
| `symbol` | string | Trading pair symbol |
| `side` | string | `"buy"` or `"sell"` |
| `type` | string | `"limit"`, `"stop_loss"`, or `"take_profit"` |
| `quantity` | decimal string | Requested quantity |
| `price` | decimal string | Limit price (if applicable) |
| `locked_amount` | decimal string | USDT or base asset locked as collateral |
| `created_at` | ISO-8601 datetime | Order creation timestamp (UTC) |

**Errors:**

| Code | HTTP | Condition |
|---|---|---|
| `ORDER_REJECTED` | 400 | Failed risk validation (position size, daily loss, max open orders) |
| `INSUFFICIENT_BALANCE` | 400 | Not enough funds to place the order |
| `INVALID_SYMBOL` | 404 | Trading pair not found |
| `PRICE_NOT_AVAILABLE` | 503 | No live price for market order execution |
| `RATE_LIMIT_EXCEEDED` | 429 | Order rate limit exceeded (100/min) |
| `DAILY_LOSS_LIMIT` | 403 | Daily loss circuit breaker is tripped |

**curl examples:**

```bash
# Market buy
curl -X POST http://localhost:8000/api/v1/trade/order \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ak_live_..." \
  -d '{"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.001"}'

# Limit buy
curl -X POST http://localhost:8000/api/v1/trade/order \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ak_live_..." \
  -d '{"symbol": "BTCUSDT", "side": "buy", "type": "limit", "quantity": "0.5", "price": "63000.00"}'

# Stop-loss
curl -X POST http://localhost:8000/api/v1/trade/order \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ak_live_..." \
  -d '{"symbol": "BTCUSDT", "side": "sell", "type": "stop_loss", "quantity": "0.5", "trigger_price": "62000.00"}'

# Take-profit
curl -X POST http://localhost:8000/api/v1/trade/order \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ak_live_..." \
  -d '{"symbol": "BTCUSDT", "side": "sell", "type": "take_profit", "quantity": "0.5", "trigger_price": "70000.00"}'
```

**Market order response example:**

```json
{
  "order_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "filled",
  "symbol": "BTCUSDT",
  "side": "buy",
  "type": "market",
  "requested_quantity": "0.001",
  "executed_quantity": "0.00100000",
  "executed_price": "64525.18000000",
  "slippage_pct": "0.00600000",
  "fee": "0.06453",
  "total_cost": "64.58971",
  "filled_at": "2026-02-26T10:00:01.234Z"
}
```

**Limit order response example:**

```json
{
  "order_id": "770f9511-f3ac-52e5-b827-557766551112",
  "status": "pending",
  "symbol": "BTCUSDT",
  "side": "buy",
  "type": "limit",
  "quantity": "0.50000000",
  "price": "63000.00000000",
  "locked_amount": "31563.00000000",
  "created_at": "2026-02-26T10:00:01.234Z"
}
```

---

### GET /trade/order/{order_id}

Fetch a single order by its UUID. The order must belong to the authenticated account.

**Auth required:** Yes

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `order_id` | UUID | Order UUID |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `order_id` | UUID string | Unique order identifier |
| `status` | string | `"pending"`, `"filled"`, `"cancelled"`, `"rejected"`, `"partially_filled"` |
| `symbol` | string | Trading pair symbol |
| `side` | string | `"buy"` or `"sell"` |
| `type` | string | `"market"`, `"limit"`, `"stop_loss"`, `"take_profit"` |
| `quantity` | decimal string | Requested quantity |
| `price` | decimal string | Limit price (null if market order) |
| `executed_price` | decimal string | Actual execution price (null if pending) |
| `executed_qty` | decimal string | Quantity filled so far |
| `slippage_pct` | decimal string | Slippage percentage applied (null if pending) |
| `fee` | decimal string | Fee paid in USDT (null if pending) |
| `created_at` | ISO-8601 datetime | Order creation time (UTC) |
| `filled_at` | ISO-8601 datetime | Fill time (UTC); null if not yet filled |

**Errors:**

| Code | HTTP | Condition |
|---|---|---|
| `ORDER_NOT_FOUND` | 404 | Order does not exist or belongs to another account |

**curl example:**

```bash
curl http://localhost:8000/api/v1/trade/order/660e8400-e29b-41d4-a716-446655440001 \
  -H "X-API-Key: ak_live_..."
```

**Response example:**

```json
{
  "order_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "filled",
  "symbol": "BTCUSDT",
  "side": "buy",
  "type": "market",
  "quantity": "0.00100000",
  "price": null,
  "executed_price": "64525.18000000",
  "executed_qty": "0.00100000",
  "slippage_pct": "0.00600000",
  "fee": "0.06453",
  "created_at": "2026-02-26T10:00:01.234Z",
  "filled_at": "2026-02-26T10:00:01.235Z"
}
```

---

### GET /trade/orders

List orders for the authenticated account with optional filters and pagination.

**Auth required:** Yes

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `status` | string | No | — | Filter by status: `"pending"`, `"filled"`, `"cancelled"`, `"rejected"` |
| `symbol` | string | No | — | Filter by trading pair (e.g. `"BTCUSDT"`) |
| `limit` | integer | No | `100` | Page size (1–500) |
| `offset` | integer | No | `0` | Pagination offset |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `orders` | array | List of order detail objects (same schema as `GET /trade/order/{id}`) |
| `total` | integer | Number of orders in this page |
| `limit` | integer | Page size used |
| `offset` | integer | Offset used |

**curl example:**

```bash
curl "http://localhost:8000/api/v1/trade/orders?status=filled&symbol=BTCUSDT&limit=50" \
  -H "X-API-Key: ak_live_..."
```

**Response example:**

```json
{
  "orders": [
    {
      "order_id": "660e8400-...",
      "status": "filled",
      "symbol": "BTCUSDT",
      "side": "buy",
      "type": "market",
      "quantity": "0.00100000",
      "price": null,
      "executed_price": "64525.18000000",
      "executed_qty": "0.00100000",
      "slippage_pct": "0.00600000",
      "fee": "0.06453",
      "created_at": "2026-02-26T10:00:01Z",
      "filled_at": "2026-02-26T10:00:01Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

---

### GET /trade/orders/open

List all open (pending / partially-filled) orders for the authenticated account.

**Auth required:** Yes

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `limit` | integer | No | `100` | Page size (1–200) |
| `offset` | integer | No | `0` | Pagination offset |

**Response: HTTP 200**

Same structure as `GET /trade/orders`. Returns only orders with status `"pending"` or `"partially_filled"`.

**curl example:**

```bash
curl http://localhost:8000/api/v1/trade/orders/open \
  -H "X-API-Key: ak_live_..."
```

---

### DELETE /trade/order/{order_id}

Cancel a single pending order and release its locked collateral.

Only `"pending"` and `"partially_filled"` orders can be cancelled.

**Auth required:** Yes

**Path parameters:**

| Parameter | Type | Description |
|---|---|---|
| `order_id` | UUID | UUID of the order to cancel |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `order_id` | UUID string | Cancelled order UUID |
| `status` | string | Always `"cancelled"` |
| `unlocked_amount` | decimal string | Amount of USDT (buy orders) or base asset (sell orders) unlocked |
| `cancelled_at` | ISO-8601 datetime | Cancellation timestamp (UTC) |

**Errors:**

| Code | HTTP | Condition |
|---|---|---|
| `ORDER_NOT_FOUND` | 404 | Order does not exist or belongs to another account |
| `ORDER_NOT_CANCELLABLE` | 409 | Order is already filled, cancelled, or rejected |

**curl example:**

```bash
curl -X DELETE \
  http://localhost:8000/api/v1/trade/order/660e8400-e29b-41d4-a716-446655440001 \
  -H "X-API-Key: ak_live_..."
```

**Response example:**

```json
{
  "order_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "cancelled",
  "unlocked_amount": "31563.00000000",
  "cancelled_at": "2026-02-26T10:05:00Z"
}
```

---

### DELETE /trade/orders/open

Cancel all open orders for the authenticated account in a single atomic operation.

**Auth required:** Yes

**Request body:** None

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `cancelled_count` | integer | Number of orders cancelled |
| `total_unlocked` | decimal string | Total collateral (USDT + base asset quantities) released |

**curl example:**

```bash
curl -X DELETE http://localhost:8000/api/v1/trade/orders/open \
  -H "X-API-Key: ak_live_..."
```

**Response example:**

```json
{
  "cancelled_count": 3,
  "total_unlocked": "45230.00000000"
}
```

---

### GET /trade/history

Get a paginated list of executed trade fills (not orders — fills only).

**Auth required:** Yes

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `symbol` | string | No | — | Filter by trading pair |
| `side` | string | No | — | Filter by side: `"buy"` or `"sell"` |
| `limit` | integer | No | `50` | Page size (1–500) |
| `offset` | integer | No | `0` | Pagination offset |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `trades` | array | List of trade fill objects (newest-first) |
| `total` | integer | Number of trades in this page |
| `limit` | integer | Page size used |
| `offset` | integer | Offset used |

**Trade fill object:**

| Field | Type | Description |
|---|---|---|
| `trade_id` | UUID string | Unique trade fill identifier |
| `order_id` | UUID string | Parent order UUID |
| `symbol` | string | Trading pair symbol |
| `side` | string | `"buy"` or `"sell"` |
| `quantity` | decimal string | Filled quantity |
| `price` | decimal string | Fill price |
| `fee` | decimal string | Fee charged in USDT |
| `total` | decimal string | Total quote amount (quantity × price) |
| `executed_at` | ISO-8601 datetime | Fill timestamp (UTC) |

**curl example:**

```bash
curl "http://localhost:8000/api/v1/trade/history?symbol=BTCUSDT&side=buy&limit=20" \
  -H "X-API-Key: ak_live_..."
```

**Response example:**

```json
{
  "trades": [
    {
      "trade_id": "aa1b2c3d-...",
      "order_id": "660e8400-...",
      "symbol": "BTCUSDT",
      "side": "buy",
      "quantity": "0.00100000",
      "price": "64525.18000000",
      "fee": "0.06453",
      "total": "64.52518",
      "executed_at": "2026-02-26T10:00:01Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

---

## Account Endpoints

All account endpoints require authentication. They return data scoped to the authenticated account only.

---

### GET /account/info

Get account details, current trading session, and effective risk profile.

**Auth required:** Yes

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `account_id` | UUID string | Account UUID |
| `display_name` | string | Account display name |
| `status` | string | `"active"`, `"suspended"`, or `"archived"` |
| `starting_balance` | decimal string | Current session starting USDT balance |
| `current_session` | object | Active trading session details |
| `risk_profile` | object | Effective risk limits for this account |
| `created_at` | ISO-8601 datetime | Account creation time (UTC) |

**Session object:**

| Field | Type | Description |
|---|---|---|
| `session_id` | UUID string | Current session UUID |
| `started_at` | ISO-8601 datetime | Session start time (UTC) |

**Risk profile object:**

| Field | Type | Description |
|---|---|---|
| `max_position_size_pct` | integer | Max single-coin position as % of total equity (default: 25) |
| `daily_loss_limit_pct` | integer | Daily loss limit as % of starting balance (default: 20) |
| `max_open_orders` | integer | Maximum simultaneous pending orders (default: 50) |

**curl example:**

```bash
curl http://localhost:8000/api/v1/account/info \
  -H "X-API-Key: ak_live_..."
```

**Response example:**

```json
{
  "account_id": "550e8400-e29b-41d4-a716-446655440000",
  "display_name": "AlphaBot",
  "status": "active",
  "starting_balance": "10000.00000000",
  "current_session": {
    "session_id": "cc1d2e3f-...",
    "started_at": "2026-02-26T09:00:00Z"
  },
  "risk_profile": {
    "max_position_size_pct": 25,
    "daily_loss_limit_pct": 20,
    "max_open_orders": 50
  },
  "created_at": "2026-02-20T00:00:00Z"
}
```

---

### GET /account/balance

Get per-asset balances and total portfolio equity expressed in USDT.

**Auth required:** Yes

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `balances` | array | List of per-asset balance objects |
| `total_equity_usdt` | decimal string | Total portfolio value in USDT (cash + open position market value) |

**Balance object:**

| Field | Type | Description |
|---|---|---|
| `asset` | string | Asset symbol (e.g. `"USDT"`, `"BTC"`) |
| `available` | decimal string | Free balance (can be used for new orders) |
| `locked` | decimal string | Balance locked by pending orders |
| `total` | decimal string | `available + locked` |

**curl example:**

```bash
curl http://localhost:8000/api/v1/account/balance \
  -H "X-API-Key: ak_live_..."
```

**Response example:**

```json
{
  "balances": [
    {
      "asset": "USDT",
      "available": "6741.50000000",
      "locked": "1500.00000000",
      "total": "8241.50000000"
    },
    {
      "asset": "BTC",
      "available": "0.50000000",
      "locked": "0.00000000",
      "total": "0.50000000"
    }
  ],
  "total_equity_usdt": "12458.30000000"
}
```

---

### GET /account/positions

Get all open positions valued at current live market prices.

**Auth required:** Yes

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `positions` | array | List of open position objects |
| `total_unrealized_pnl` | decimal string | Sum of unrealized PnL across all positions (USDT) |

**Position object:**

| Field | Type | Description |
|---|---|---|
| `symbol` | string | Trading pair symbol (e.g. `"BTCUSDT"`) |
| `asset` | string | Base asset held (e.g. `"BTC"`) |
| `quantity` | decimal string | Amount of base asset held |
| `avg_entry_price` | decimal string | Average cost basis in USDT |
| `current_price` | decimal string | Current live market price |
| `market_value` | decimal string | Current value (`quantity × current_price`) |
| `unrealized_pnl` | decimal string | Unrealized profit/loss in USDT |
| `unrealized_pnl_pct` | decimal string | Unrealized PnL as a percentage |
| `opened_at` | ISO-8601 datetime | When the position was first opened (UTC) |

**curl example:**

```bash
curl http://localhost:8000/api/v1/account/positions \
  -H "X-API-Key: ak_live_..."
```

**Response example:**

```json
{
  "positions": [
    {
      "symbol": "BTCUSDT",
      "asset": "BTC",
      "quantity": "0.50000000",
      "avg_entry_price": "63200.00000000",
      "current_price": "64521.30000000",
      "market_value": "32260.65000000",
      "unrealized_pnl": "660.65000000",
      "unrealized_pnl_pct": "2.09000000",
      "opened_at": "2026-02-25T08:30:00Z"
    }
  ],
  "total_unrealized_pnl": "660.65000000"
}
```

---

### GET /account/portfolio

Get a complete real-time portfolio snapshot combining cash, positions, and PnL.

**Auth required:** Yes

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `total_equity` | decimal string | Total portfolio value in USDT |
| `available_cash` | decimal string | Free USDT balance |
| `locked_cash` | decimal string | USDT locked by pending orders |
| `total_position_value` | decimal string | Market value of all open positions |
| `unrealized_pnl` | decimal string | Total unrealized PnL across all positions |
| `realized_pnl` | decimal string | Total realized PnL from closed trades (all time) |
| `total_pnl` | decimal string | `unrealized_pnl + realized_pnl` |
| `roi_pct` | decimal string | Return on investment: `(total_equity - starting_balance) / starting_balance × 100` |
| `starting_balance` | decimal string | Session starting balance |
| `positions` | array | List of open position objects (same schema as `GET /account/positions`) |
| `timestamp` | ISO-8601 datetime | Snapshot time (UTC) |

**curl example:**

```bash
curl http://localhost:8000/api/v1/account/portfolio \
  -H "X-API-Key: ak_live_..."
```

**Response example:**

```json
{
  "total_equity": "12458.30000000",
  "available_cash": "6741.50000000",
  "locked_cash": "1500.00000000",
  "total_position_value": "4216.80000000",
  "unrealized_pnl": "660.65000000",
  "realized_pnl": "1241.30000000",
  "total_pnl": "1901.95000000",
  "roi_pct": "19.02000000",
  "starting_balance": "10000.00000000",
  "positions": [],
  "timestamp": "2026-02-26T10:00:00Z"
}
```

---

### GET /account/pnl

Get a detailed profit-and-loss breakdown scoped to a time period.

**Auth required:** Yes

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `period` | string | No | `"all"` | Time window: `"1d"` (today), `"7d"`, `"30d"`, `"all"` |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `period` | string | Requested period |
| `realized_pnl` | decimal string | PnL from trades closed in the period |
| `unrealized_pnl` | decimal string | Current unrealized PnL across open positions |
| `total_pnl` | decimal string | `realized_pnl + unrealized_pnl` |
| `fees_paid` | decimal string | Total trading fees paid in the period |
| `net_pnl` | decimal string | `total_pnl - fees_paid` |
| `winning_trades` | integer | Number of profitable closed trades |
| `losing_trades` | integer | Number of losing closed trades |
| `win_rate` | decimal string | `winning_trades / (winning_trades + losing_trades) × 100` |

**curl example:**

```bash
curl "http://localhost:8000/api/v1/account/pnl?period=7d" \
  -H "X-API-Key: ak_live_..."
```

**Response example:**

```json
{
  "period": "7d",
  "realized_pnl": "1241.30000000",
  "unrealized_pnl": "660.65000000",
  "total_pnl": "1901.95000000",
  "fees_paid": "156.20000000",
  "net_pnl": "1745.75000000",
  "winning_trades": 23,
  "losing_trades": 12,
  "win_rate": "65.71428571"
}
```

---

### POST /account/reset

Reset the account to a clean starting state. Closes all positions, cancels all orders, wipes balances, and starts a new trading session. Trade history is preserved.

**The `confirm` flag must be `true` — this operation is irreversible.**

**Auth required:** Yes

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `confirm` | boolean | Yes | Must be `true` to proceed |
| `new_starting_balance` | decimal string | No | Override starting balance for the new session (defaults to original) |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `message` | string | Always `"Account reset successful"` |
| `previous_session` | object | Summary of the session that was closed |
| `new_session` | object | Details of the new session |

**Previous session object:**

| Field | Type | Description |
|---|---|---|
| `session_id` | UUID string | Closed session UUID |
| `ending_equity` | decimal string | Portfolio value at reset time |
| `total_pnl` | decimal string | Total PnL earned in the closed session |
| `duration_days` | integer | Number of days the session ran |

**New session object:**

| Field | Type | Description |
|---|---|---|
| `session_id` | UUID string | New session UUID |
| `starting_balance` | decimal string | Starting USDT balance for the new session |
| `started_at` | ISO-8601 datetime | New session start time (UTC) |

**Errors:**

| Code | HTTP | Condition |
|---|---|---|
| `VALIDATION_ERROR` | 400 | `confirm` is `false` or missing |
| `ACCOUNT_SUSPENDED` | 403 | Account is suspended |
| `ACCOUNT_NOT_FOUND` | 404 | Account no longer exists |

**curl example:**

```bash
curl -X POST http://localhost:8000/api/v1/account/reset \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ak_live_..." \
  -d '{"confirm": true}'
```

**Response example:**

```json
{
  "message": "Account reset successful",
  "previous_session": {
    "session_id": "cc1d2e3f-...",
    "ending_equity": "12458.30000000",
    "total_pnl": "2458.30000000",
    "duration_days": 6
  },
  "new_session": {
    "session_id": "dd2e3f4g-...",
    "starting_balance": "10000.00000000",
    "started_at": "2026-02-26T11:00:00Z"
  }
}
```

---

## Analytics Endpoints

All analytics endpoints require authentication. Results are scoped to the authenticated account, except the leaderboard which returns public aggregate data for all active accounts.

---

### GET /analytics/performance

Get advanced trading performance statistics including risk-adjusted return metrics.

**Auth required:** Yes

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `period` | string | No | `"all"` | Lookback window: `"1d"`, `"7d"`, `"30d"`, `"90d"`, `"all"` |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `period` | string | Requested period |
| `sharpe_ratio` | decimal string | Annualised Sharpe ratio (risk-adjusted return) |
| `sortino_ratio` | decimal string | Annualised Sortino ratio (downside risk only) |
| `max_drawdown_pct` | decimal string | Maximum drawdown percentage from peak |
| `max_drawdown_duration_days` | integer | Longest drawdown period in days |
| `win_rate` | decimal string | Percentage of trades that were profitable |
| `profit_factor` | decimal string | Ratio of gross profit to gross loss |
| `avg_win` | decimal string | Average profit on winning trades (USDT) |
| `avg_loss` | decimal string | Average loss on losing trades (USDT, negative) |
| `total_trades` | integer | Total number of closed trades in the period |
| `avg_trades_per_day` | decimal string | Average trades per calendar day |
| `best_trade` | decimal string | Largest single trade profit (USDT) |
| `worst_trade` | decimal string | Largest single trade loss (USDT) |
| `current_streak` | integer | Current win/loss streak (positive = wins, negative = losses) |

**curl example:**

```bash
curl "http://localhost:8000/api/v1/analytics/performance?period=30d" \
  -H "X-API-Key: ak_live_..."
```

**Response example:**

```json
{
  "period": "30d",
  "sharpe_ratio": "1.85000000",
  "sortino_ratio": "2.31000000",
  "max_drawdown_pct": "8.50000000",
  "max_drawdown_duration_days": 3,
  "win_rate": "65.71000000",
  "profit_factor": "2.10000000",
  "avg_win": "156.30000000",
  "avg_loss": "-74.50000000",
  "total_trades": 35,
  "avg_trades_per_day": "1.17000000",
  "best_trade": "523.00000000",
  "worst_trade": "-210.00000000",
  "current_streak": 3
}
```

---

### GET /analytics/portfolio/history

Get a time-ordered list of portfolio equity snapshots for charting an equity curve.

**Auth required:** Yes

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `interval` | string | No | `"1h"` | Snapshot resolution: `"1m"` (minute), `"1h"` (hourly), `"1d"` (daily) |
| `limit` | integer | No | `100` | Number of data points to return (1–1000) |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `account_id` | UUID string | Account UUID |
| `interval` | string | Snapshot resolution used |
| `snapshots` | array | List of snapshot objects (oldest-first) |

**Snapshot object:**

| Field | Type | Description |
|---|---|---|
| `time` | ISO-8601 datetime | Snapshot timestamp (UTC) |
| `total_equity` | decimal string | Total portfolio value at snapshot time |
| `unrealized_pnl` | decimal string | Unrealized PnL at snapshot time |
| `realized_pnl` | decimal string | Cumulative realized PnL at snapshot time |

**curl example:**

```bash
# 7 days of hourly equity data (168 points)
curl "http://localhost:8000/api/v1/analytics/portfolio/history?interval=1h&limit=168" \
  -H "X-API-Key: ak_live_..."
```

**Response example:**

```json
{
  "account_id": "550e8400-e29b-41d4-a716-446655440000",
  "interval": "1h",
  "snapshots": [
    {
      "time": "2026-02-25T10:00:00Z",
      "total_equity": "10420.00000000",
      "unrealized_pnl": "180.00000000",
      "realized_pnl": "240.00000000"
    },
    {
      "time": "2026-02-25T11:00:00Z",
      "total_equity": "10658.30000000",
      "unrealized_pnl": "217.00000000",
      "realized_pnl": "441.30000000"
    }
  ]
}
```

---

### GET /analytics/leaderboard

Get cross-account performance rankings sorted by ROI descending. Only active accounts with at least one closed trade in the period are included. Returns up to 50 entries.

**Auth required:** Yes (authentication required but leaderboard data is public aggregate — no private balance details of other accounts are exposed)

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `period` | string | No | `"30d"` | Lookback window: `"1d"`, `"7d"`, `"30d"`, `"90d"`, `"all"` |

**Response: HTTP 200**

| Field | Type | Description |
|---|---|---|
| `period` | string | Requested period |
| `rankings` | array | List of leaderboard entry objects (rank 1 = best ROI) |

**Leaderboard entry object:**

| Field | Type | Description |
|---|---|---|
| `rank` | integer | Rank position (1-based) |
| `account_id` | UUID string | Account UUID |
| `display_name` | string | Account display name |
| `roi_pct` | decimal string | Return on investment percentage |
| `sharpe_ratio` | decimal string | Sharpe ratio for the period |
| `total_trades` | integer | Number of closed trades in the period |
| `win_rate` | decimal string | Percentage of profitable trades |

**curl example:**

```bash
curl "http://localhost:8000/api/v1/analytics/leaderboard?period=7d" \
  -H "X-API-Key: ak_live_..."
```

**Response example:**

```json
{
  "period": "7d",
  "rankings": [
    {
      "rank": 1,
      "account_id": "aa1b2c3d-...",
      "display_name": "AlphaBot",
      "roi_pct": "24.50000000",
      "sharpe_ratio": "2.14000000",
      "total_trades": 42,
      "win_rate": "71.43000000"
    },
    {
      "rank": 2,
      "account_id": "bb2c3d4e-...",
      "display_name": "MomentumAgent",
      "roi_pct": "18.20000000",
      "sharpe_ratio": "1.77000000",
      "total_trades": 28,
      "win_rate": "67.86000000"
    }
  ]
}
```

---

## Error Codes

All errors follow this format:

```json
{"error": {"code": "ERROR_CODE", "message": "Human-readable explanation"}}
```

| Code | HTTP Status | Meaning | Resolution |
|---|---|---|---|
| `INVALID_API_KEY` | 401 | API key is missing, malformed, or not found | Verify `X-API-Key` header is correct |
| `INVALID_TOKEN` | 401 | JWT token is expired, malformed, or has invalid signature | Call `POST /auth/login` to get a new token |
| `ACCOUNT_SUSPENDED` | 403 | Account is suspended or archived | Contact platform admin |
| `PERMISSION_DENIED` | 403 | Authenticated but not allowed to access this resource | Check account status |
| `DAILY_LOSS_LIMIT` | 403 | Daily loss circuit breaker has been tripped | Trading resumes automatically at 00:00 UTC |
| `INSUFFICIENT_BALANCE` | 400 | Not enough free balance to place the order | Check `GET /account/balance` and reduce order size |
| `INVALID_SYMBOL` | 400 | Trading pair does not exist or is inactive | Use `GET /market/pairs` to list valid symbols |
| `INVALID_QUANTITY` | 400 | Quantity is zero, negative, or below `min_qty` | Check pair's `min_qty` and `step_size` |
| `POSITION_LIMIT_EXCEEDED` | 400 | Order would cause this coin to exceed the 25% position limit | Reduce quantity or close an existing position |
| `ORDER_REJECTED` | 400 | Order failed the risk manager's validation chain | Read the `message` field for the specific violation |
| `ORDER_NOT_FOUND` | 404 | Order ID does not exist or belongs to another account | Verify the `order_id` |
| `ORDER_NOT_CANCELLABLE` | 409 | Order is already filled, cancelled, or rejected | Check order status with `GET /trade/order/{id}` |
| `ACCOUNT_NOT_FOUND` | 404 | Account no longer exists in the system | This should not happen in normal operation |
| `DUPLICATE_ACCOUNT` | 409 | Email address already registered | Use a different email or log in to the existing account |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests — rate limit hit | Wait until `X-RateLimit-Reset` Unix timestamp |
| `VALIDATION_ERROR` | 422 | Request body failed Pydantic validation | Fix the field(s) listed in the `message` |
| `PRICE_NOT_AVAILABLE` | 503 | No live price in cache for this symbol | Retry in a few seconds; the ingestion service may be catching up |
| `INTERNAL_ERROR` | 500 | Unexpected server-side error | Retry with exponential back-off; report if persistent |

### HTTP 5xx Retry Strategy

For `500` and `503` errors, use exponential back-off:

| Attempt | Wait before retry |
|---|---|
| 1st retry | 1 second |
| 2nd retry | 2 seconds |
| 3rd retry | 4 seconds |
| 4th retry | 8 seconds (give up after this) |

---

## WebSocket Reference

Connect to the WebSocket server for real-time streaming without polling:

```
ws://localhost:8000/ws/v1?api_key=YOUR_API_KEY
```

Or with JWT:

```
ws://localhost:8000/ws/v1?token=YOUR_JWT_TOKEN
```

### Message Format

All messages are JSON objects. Client-to-server messages use the `action` field; server-to-client messages use the `channel` field.

### Subscribe / Unsubscribe

```json
{"action": "subscribe",   "channel": "ticker", "symbol": "BTCUSDT"}
{"action": "unsubscribe", "channel": "ticker", "symbol": "BTCUSDT"}
```

### Channels

#### `ticker` — per-symbol price updates

Subscribe to a single pair:

```json
{"action": "subscribe", "channel": "ticker", "symbol": "BTCUSDT"}
```

Incoming messages:

```json
{
  "channel": "ticker",
  "symbol": "BTCUSDT",
  "data": {
    "price": "64521.30",
    "quantity": "0.012",
    "timestamp": "2026-02-26T10:00:00.123Z"
  }
}
```

#### `ticker_all` — all pairs in one subscription

```json
{"action": "subscribe", "channel": "ticker_all"}
```

Incoming messages have the same shape as `ticker` but without a `symbol` field in the outer object — the symbol is inside `data`.

#### `candles` — live candle updates

```json
{"action": "subscribe", "channel": "candles", "symbol": "BTCUSDT", "interval": "1m"}
```

Valid intervals: `1m`, `5m`, `1h`, `1d`.

Incoming messages:

```json
{
  "channel": "candles",
  "symbol": "BTCUSDT",
  "interval": "1m",
  "data": {
    "time": "2026-02-26T10:00:00Z",
    "open": "64500.00",
    "high": "64550.00",
    "low": "64490.00",
    "close": "64521.30",
    "volume": "12.345",
    "is_closed": false
  }
}
```

`is_closed: true` signals the candle period has ended and the values are final.

#### `orders` — private order updates (auth required)

```json
{"action": "subscribe", "channel": "orders"}
```

Incoming messages:

```json
{
  "channel": "orders",
  "data": {
    "order_id": "660e8400-...",
    "status": "filled",
    "symbol": "BTCUSDT",
    "side": "buy",
    "executed_price": "64521.30",
    "executed_quantity": "0.50",
    "fee": "32.26",
    "filled_at": "2026-02-26T10:00:01Z"
  }
}
```

#### `portfolio` — private portfolio updates (auth required)

```json
{"action": "subscribe", "channel": "portfolio"}
```

Updates are pushed every 5 seconds:

```json
{
  "channel": "portfolio",
  "data": {
    "total_equity": "12458.30",
    "unrealized_pnl": "660.65",
    "realized_pnl": "1241.30",
    "available_cash": "6741.50",
    "timestamp": "2026-02-26T10:05:00Z"
  }
}
```

### Heartbeat

The server sends `{"type": "ping"}` every 30 seconds. Respond with `{"type": "pong"}` within 10 seconds or the connection is closed. On disconnect, reconnect with exponential back-off: 1 s → 2 s → 4 s → … → 60 s maximum.

### WebSocket Error Messages

```json
{
  "type": "error",
  "code": "INVALID_API_KEY",
  "message": "Authentication failed."
}
```

---

*For a guided 5-minute walkthrough, see [quickstart.md](quickstart.md). For LLM-readable agent instructions, see [skill.md](skill.md).*
