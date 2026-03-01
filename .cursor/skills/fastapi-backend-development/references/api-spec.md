# AiTradingAgent REST API Specification

**Base URL:** `/api/v1`

---

## Auth

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Register new account |
| POST | `/auth/login` | Login with API credentials |

### POST /auth/register

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| display_name | string | Yes | Display name |
| email | string | No | Email address |
| starting_balance | number | No | Initial balance (default: 10000) |

**Response:** `201 Created`

| Field | Type | Description |
|-------|------|-------------|
| account_id | UUID | Account ID |
| api_key | string | API key (store securely) |
| api_secret | string | API secret (store securely) |
| display_name | string | Display name |
| starting_balance | number | Starting balance |
| message | string | Success message |

### POST /auth/login

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| api_key | string | Yes | API key |
| api_secret | string | Yes | API secret |

**Response:** `200 OK`

| Field | Type | Description |
|-------|------|-------------|
| token | string | JWT token |
| expires_at | string (ISO8601) | Token expiration |
| token_type | string | `Bearer` |

---

## Market Data

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/market/pairs` | List trading pairs |
| GET | `/market/price/{symbol}` | Single symbol price |
| GET | `/market/prices` | Bulk prices |
| GET | `/market/ticker/{symbol}` | Ticker for symbol |
| GET | `/market/candles/{symbol}` | OHLCV candles |
| GET | `/market/trades/{symbol}` | Recent trades |
| GET | `/market/orderbook/{symbol}` | Order book |

### GET /market/pairs

**Response:** `200 OK`

| Field | Type | Description |
|-------|------|-------------|
| pairs | array | List of pair objects |
| total | number | Total count |

**Pair object:**

| Field | Type |
|-------|------|
| symbol | string |
| base_asset | string |
| quote_asset | string |
| status | string |
| min_qty | number |
| step_size | number |
| min_notional | number |

### GET /market/price/{symbol}

**Response:** `200 OK`

| Field | Type |
|-------|------|
| symbol | string |
| price | number |
| timestamp | string (ISO8601) |

### GET /market/prices

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| symbols | string | Comma-separated symbols |

**Response:** `200 OK`

| Field | Type |
|-------|------|
| prices | object (symbol → price) |
| timestamp | string (ISO8601) |
| count | number |

### GET /market/ticker/{symbol}

**Response:** `200 OK`

| Field | Type |
|-------|------|
| symbol | string |
| open | number |
| high | number |
| low | number |
| close | number |
| volume | number |
| quote_volume | number |
| change | number |
| change_pct | number |
| trade_count | number |
| timestamp | string (ISO8601) |

### GET /market/candles/{symbol}

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| interval | string | 1m, 5m, 1h, 1d |
| limit | number | Max candles |
| start_time | string (ISO8601) | Start time |
| end_time | string (ISO8601) | End time |

**Response:** `200 OK`

| Field | Type |
|-------|------|
| symbol | string |
| interval | string |
| candles | array of candle objects |
| count | number |

**Candle object:**

| Field | Type |
|-------|------|
| time | string (ISO8601) |
| open | number |
| high | number |
| low | number |
| close | number |
| volume | number |
| trade_count | number |

### GET /market/trades/{symbol}

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| limit | number | Max trades |

**Response:** `200 OK`

| Field | Type |
|-------|------|
| symbol | string |
| trades | array of trade objects |

**Trade object:**

| Field | Type |
|-------|------|
| trade_id | number |
| price | number |
| quantity | number |
| time | string (ISO8601) |
| is_buyer_maker | boolean |

### GET /market/orderbook/{symbol}

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| depth | number | Order book depth |

**Response:** `200 OK`

| Field | Type |
|-------|------|
| symbol | string |
| bids | array of [price, qty] |
| asks | array of [price, qty] |
| timestamp | string (ISO8601) |

---

## Trading

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/trade/order` | Place order |
| GET | `/trade/order/{order_id}` | Get order details |
| GET | `/trade/orders` | List orders |
| GET | `/trade/orders/open` | Pending orders |
| DELETE | `/trade/order/{order_id}` | Cancel order |
| DELETE | `/trade/orders/open` | Cancel all open orders |
| GET | `/trade/history` | Trade history |

### POST /trade/order

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| symbol | string | Yes | Trading pair |
| side | string | Yes | `buy` or `sell` |
| type | string | Yes | `market`, `limit`, `stop_loss`, `take_profit` |
| quantity | number | Yes | Order quantity |
| price | number | No | Limit price (required for limit orders) |

**Response:** `201 Created` — filled or pending order response

### GET /trade/order/{order_id}

**Response:** `200 OK` — order details

### GET /trade/orders

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| status | string | Filter by status |
| symbol | string | Filter by symbol |
| side | string | Filter by side |
| limit | number | Max results |
| offset | number | Pagination offset |

**Response:** `200 OK` — orders list

### GET /trade/orders/open

**Response:** `200 OK` — pending orders

### DELETE /trade/order/{order_id}

**Response:** `200 OK`

| Field | Type |
|-------|------|
| order_id | UUID |
| status | string |
| unlocked_amount | number |
| cancelled_at | string (ISO8601) |

### DELETE /trade/orders/open

**Response:** `200 OK`

| Field | Type |
|-------|------|
| cancelled_count | number |
| total_unlocked | number |

### GET /trade/history

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| symbol | string | Filter by symbol |
| side | string | Filter by side |
| start_time | string (ISO8601) | Start time |
| end_time | string (ISO8601) | End time |
| limit | number | Max results |
| offset | number | Pagination offset |

**Response:** `200 OK` — trade history

---

## Account

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/account/info` | Account details |
| GET | `/account/balance` | Balances |
| GET | `/account/positions` | Open positions |
| GET | `/account/portfolio` | Full portfolio summary |
| GET | `/account/pnl` | PnL breakdown |
| POST | `/account/reset` | Reset account |

### GET /account/info

**Response:** `200 OK` — account details with session and risk profile

### GET /account/balance

**Response:** `200 OK`

| Field | Type |
|-------|------|
| balances | array of balance objects |
| total_equity_usdt | number |

**Balance object:**

| Field | Type |
|-------|------|
| asset | string |
| available | number |
| locked | number |
| total | number |

### GET /account/positions

**Response:** `200 OK`

| Field | Type |
|-------|------|
| positions | array of position objects |
| total_unrealized_pnl | number |

**Position object:**

| Field | Type |
|-------|------|
| symbol | string |
| asset | string |
| quantity | number |
| avg_entry_price | number |
| current_price | number |
| market_value | number |
| unrealized_pnl | number |
| unrealized_pnl_pct | number |
| opened_at | string (ISO8601) |

### GET /account/portfolio

**Response:** `200 OK` — full portfolio summary

### GET /account/pnl

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| period | string | Time period |

**Response:** `200 OK` — PnL breakdown

### POST /account/reset

**Request body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| confirm | boolean | Yes | Confirmation flag |
| new_starting_balance | number | No | New starting balance |

**Response:** `200 OK` — reset result

---

## Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/analytics/performance` | Performance metrics |
| GET | `/analytics/portfolio/history` | Portfolio snapshots |
| GET | `/analytics/leaderboard` | Rankings |

### GET /analytics/performance

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| period | string | Time period |

**Response:** `200 OK` — metrics (sharpe, sortino, drawdown, etc.)

### GET /analytics/portfolio/history

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| interval | string | Snapshot interval |
| start_time | string (ISO8601) | Start time |
| end_time | string (ISO8601) | End time |
| limit | number | Max snapshots |

**Response:** `200 OK` — snapshots

### GET /analytics/leaderboard

**Query params:**

| Param | Type | Description |
|-------|------|-------------|
| period | string | Time period |

**Response:** `200 OK` — rankings
