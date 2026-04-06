# TradeReady API — Tester Manual

**Base URL:** `https://api.tradeready.io/api/v1`
**Full reference:** `docs/skill.md`

> All paths below are relative to the base URL. For example, `/auth/register` means
> `https://api.tradeready.io/api/v1/auth/register`

---

## 1. Registration & Auth

### Register a new account
```bash
curl -X POST https://api.tradeready.io/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"display_name": "TestUser", "email": "test@test.com", "password": "Test1234!", "starting_balance": "10000.00"}'
```
**Response includes:** `api_key`, `api_secret`, `agent_id`, `agent_api_key`

> Use `agent_api_key` (not `api_key`) for all trading endpoints. The `agent_api_key` is scoped to the auto-created default agent which holds your balance.

### Login with email/password (get JWT)
```bash
curl -X POST https://api.tradeready.io/api/v1/auth/user-login \
  -H "Content-Type: application/json" \
  -d '{"email": "test@test.com", "password": "Test1234!"}'
```
**Response field:** `token` (not `access_token`)

### Login with API key/secret (get JWT)
```bash
curl -X POST https://api.tradeready.io/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"api_key": "ak_live_...", "api_secret": "sk_live_..."}'
```

### Auth headers
```
# For most endpoints — use API key:
X-API-Key: ak_live_...

# For agent/battle endpoints — use JWT:
Authorization: Bearer eyJ...
```

---

## 2. Market Data (Public — no auth needed)

| Endpoint | Path |
|----------|------|
| Single price | `GET /market/price/BTCUSDT` |
| All prices | `GET /market/prices` |
| Single ticker (24h stats) | `GET /market/ticker/BTCUSDT` |
| Multiple tickers | `GET /market/tickers?symbols=BTCUSDT,ETHUSDT` |
| All tickers (no param) | `GET /market/tickers` |
| Candles | `GET /market/candles/BTCUSDT?interval=1h&limit=10` |
| Order book | `GET /market/orderbook/BTCUSDT` |
| Recent trades | `GET /market/trades/BTCUSDT` |
| Trading pairs | `GET /market/pairs` |
| Data range (for backtesting) | `GET /market/data-range` |

> **Candles use path parameter** — `/market/candles/BTCUSDT`, NOT `/market/candles?symbol=BTCUSDT`

> Symbols are case-insensitive — `btcusdt` auto-converts to `BTCUSDT`

---

## 3. Trading

### Place order
```bash
curl -X POST https://api.tradeready.io/api/v1/trade/order \
  -H "X-API-Key: YOUR_AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.01"}'
```

### Order types
| Type | Required fields |
|------|----------------|
| Market | `symbol`, `side`, `type: "market"`, `quantity` |
| Limit | + `price` |
| Stop-loss | + `price` (or `stop_price`) |
| Take-profit | + `price` (or `stop_price`) |

> Both `price` and `stop_price` are accepted for stop-loss/take-profit orders.

### Other trading endpoints
| Action | Method | Path |
|--------|--------|------|
| List all orders | GET | `/trade/orders` |
| List open orders | GET | `/trade/orders/open` |
| Get single order | GET | `/trade/order/{order_id}` |
| Cancel order | DELETE | `/trade/order/{order_id}` |
| Cancel all open | DELETE | `/trade/orders/open` |
| Trade history | GET | `/trade/history` |

---

## 4. Account

| Action | Method | Path |
|--------|--------|------|
| Balance (per asset) | GET | `/account/balance` |
| Positions (open) | GET | `/account/positions` |
| Portfolio (summary) | GET | `/account/portfolio` |
| Account info | GET | `/account/info` |
| PnL breakdown | GET | `/account/pnl` |
| Reset account | POST | `/account/reset` with `{"confirm": true}` |

---

## 5. Analytics

| Action | Method | Path | Notes |
|--------|--------|------|-------|
| Performance metrics | GET | `/analytics/performance` | Sharpe, win rate, drawdown |
| **Portfolio history** | GET | **`/analytics/portfolio/history`** | Equity over time |
| Leaderboard | GET | `/analytics/leaderboard` | |

> **IMPORTANT:** Portfolio history path is `/analytics/portfolio/history` (with slash), NOT `/analytics/portfolio-history` (with hyphen).

---

## 6. Multi-Agent (JWT required)

| Action | Method | Path |
|--------|--------|------|
| Create agent | POST | `/agents` |
| List agents | GET | `/agents` |
| Get agent | GET | `/agents/{id}` |
| Update agent | PUT | `/agents/{id}` |
| Clone agent | POST | `/agents/{id}/clone` |
| Reset agent | POST | `/agents/{id}/reset` |
| Archive agent | POST | `/agents/{id}/archive` |
| Delete agent | DELETE | `/agents/{id}` |

---

## 7. Strategies

### Create strategy
```bash
curl -X POST https://api.tradeready.io/api/v1/strategies \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "MA Crossover",
    "description": "SMA cross strategy",
    "definition": {
      "pairs": ["BTCUSDT", "ETHUSDT"],
      "timeframe": "1h",
      "entry_conditions": {"sma_cross_above": {"short_period": 10, "long_period": 20}},
      "exit_conditions": {"sma_cross_below": {"short_period": 10, "long_period": 20}}
    }
  }'
```

> `definition.pairs` is **required**. Empty definition `{}` returns a validation error.

| Action | Method | Path |
|--------|--------|------|
| Create strategy | POST | `/strategies` |
| List strategies | GET | `/strategies` |
| Get strategy | GET | `/strategies/{id}` |
| Create version | POST | `/strategies/{id}/versions` |
| Test strategy | POST | `/strategies/{id}/test` |
| Deploy | POST | `/strategies/{id}/deploy` |

### Test a strategy
```bash
curl -X POST https://api.tradeready.io/api/v1/strategies/{strategy_id}/test \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/json" \
  -d '{"version": 1, "date_range": {"start": "2025-06-01", "end": "2025-06-05"}}'
```

---

## 8. Backtesting

### Create backtest
```bash
curl -X POST https://api.tradeready.io/api/v1/backtest/create \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "start_time": "2025-06-01T00:00:00Z",
    "end_time": "2025-06-07T00:00:00Z",
    "starting_balance": 10000,
    "candle_interval": 60,
    "agent_id": "YOUR_AGENT_UUID",
    "pairs": ["BTCUSDT", "ETHUSDT"]
  }'
```

> `candle_interval` is in **seconds** (60 = 1 minute) or string shorthand (`"1h"`, `"5m"`).
> `agent_id` is required.

### Backtest lifecycle
| Action | Method | Path |
|--------|--------|------|
| Create | POST | `/backtest/create` |
| Start | POST | `/backtest/{session_id}/start` |
| Step (1 candle) | POST | `/backtest/{session_id}/step` |
| Step batch | POST | `/backtest/{session_id}/step/batch` with `{"steps": 60}` |
| Cancel | POST | `/backtest/{session_id}/cancel` |
| Status | GET | `/backtest/{session_id}/status` |

### Trade inside a backtest
```
POST /backtest/{session_id}/trade/order
```
> NOT `/backtest/{session_id}/trade` or `/backtest/{session_id}/order`

### Backtest results
| Action | Method | Path |
|--------|--------|------|
| Full results | GET | `/backtest/{session_id}/results` |
| **Equity curve** | GET | **`/backtest/{session_id}/results/equity-curve`** |
| Trade log | GET | `/backtest/{session_id}/results/trades` |
| **List backtests** | GET | **`/backtest/list`** |
| Compare | GET | `/backtest/compare?sessions=id1,id2` |
| Best session | GET | `/backtest/best?metric=sharpe_ratio` |

### Backtest sandbox (same as live, scoped to session)
```
GET /backtest/{sid}/market/price/{symbol}
GET /backtest/{sid}/market/prices
GET /backtest/{sid}/account/balance
GET /backtest/{sid}/account/positions
GET /backtest/{sid}/account/portfolio
GET /backtest/{sid}/trade/orders
GET /backtest/{sid}/trade/orders/open
GET /backtest/{sid}/trade/history
```

---

## 9. Battles (JWT required)

### Create battle
```bash
curl -X POST https://api.tradeready.io/api/v1/battles \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Battle", "agent_ids": ["agent-uuid-1", "agent-uuid-2"], "duration_minutes": 5}'
```

| Action | Method | Path |
|--------|--------|------|
| Create | POST | `/battles` |
| List | GET | `/battles` |
| Get presets | GET | `/battles/presets` |
| Get battle | GET | `/battles/{id}` |
| Start | POST | `/battles/{id}/start` |
| Stop | POST | `/battles/{id}/stop` |
| Live metrics | GET | `/battles/{id}/live` |
| Results | GET | `/battles/{id}/results` |
| Replay data | GET | `/battles/{id}/replay` |
| Add agent | POST | `/battles/{id}/participants` |
| Remove agent | DELETE | `/battles/{id}/participants/{agent_id}` |

---

## Common Mistakes to Avoid

| Wrong | Correct | Bug |
|-------|---------|-----|
| `/backtest/{id}/trade` | `/backtest/{id}/trade/order` | #7 |
| `/backtest/{id}/equity` | `/backtest/{id}/results/equity-curve` | #8 |
| `/backtest/sessions` | `/backtest/list` | #9 |
| `/analytics/portfolio-history` | `/analytics/portfolio/history` | #10 |
| `"order_type": "market"` | `"type": "market"` | — |
| `"stop_price": "60000"` without `price` | `"price": "60000"` or `"stop_price": "60000"` | #15 |
| `"candle_interval": "1h"` | `"candle_interval": 60` (seconds) | — |
| Using `api_key` for trading | Use `agent_api_key` from registration | — |

---

## Error Response Format

All errors follow this format:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "details": { }
  }
}
```

Common codes: `INVALID_API_KEY`, `ORDER_REJECTED`, `INSUFFICIENT_BALANCE`, `VALIDATION_ERROR`, `BACKTEST_NO_DATA`

---

*Last updated: 2026-04-02*
