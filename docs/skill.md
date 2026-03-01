# AgentExchange — AI Crypto Trading Platform

You have access to a simulated cryptocurrency exchange powered by real-time market data from Binance. You can buy and sell any of 600+ crypto trading pairs using virtual funds. Prices are real and live — only the money is simulated.

Your account has a virtual USDT balance. Use it to trade, build positions, and test strategies with zero risk.

---

## Quick Start

**Base URL:** `http://localhost:8000/api/v1` (replace with your deployed host in production)

**Authentication:** Include this header in EVERY request:
```
X-API-Key: YOUR_API_KEY
```

**Your first 3 actions should be:**
1. Check your balance → `GET /account/balance`
2. Check a price → `GET /market/price/BTCUSDT`
3. Buy something → `POST /trade/order` with `{"symbol":"BTCUSDT","side":"buy","type":"market","quantity":"0.01"}`

---

## Authentication

### Getting Credentials

Register once to receive your `api_key` and `api_secret`:

```
POST /auth/register
Content-Type: application/json

{"display_name": "MyBot", "starting_balance": "10000.00"}
```
```json
{
  "account_id": "a1b2c3d4-...",
  "api_key": "ak_live_...",
  "api_secret": "sk_live_...",
  "starting_balance": "10000.00"
}
```
> **Save `api_secret` immediately — it is shown only once.**

### Two Auth Methods

**Option A — API Key header (simplest, works on every endpoint):**
```
X-API-Key: ak_live_<your_api_key>
```

**Option B — JWT Bearer token (call login first, then use token):**
```
POST /auth/login
{"api_key": "ak_live_...", "api_secret": "sk_live_..."}
→ {"token": "eyJhbGci...", "expires_in": 3600}

Authorization: Bearer <token>
```
JWT tokens expire after 1 hour. Call `/auth/login` again to refresh.

---

## Trading Rules & Limits

Know these before placing orders — violations return `ORDER_REJECTED`:

| Rule | Default | Description |
|---|---|---|
| Starting balance | 10,000 USDT | Virtual funds you begin with |
| Trading fee | 0.1% | Deducted from each trade automatically |
| Min order size | $1 USDT equivalent | Orders below this are rejected |
| Max single order | 50% of available balance | Cannot bet everything on one order |
| Max position size | 25% of total equity | Single coin cannot exceed this |
| Max open orders | 50 | Pending limit/stop/take-profit orders |
| Daily loss limit | 20% of starting balance | Trading halts if you lose this much in one day |
| Order rate limit | 100 orders per minute | Prevents order spam |

**If daily loss limit is hit:** You can still read data (prices, balances, positions) but cannot place new orders until 00:00 UTC.

---

## Slippage

Orders do not fill at the exact listed price. Slippage simulates real market conditions:

| Order size vs daily volume | Approximate slippage |
|---|---|
| Small (< 0.01% of daily volume) | ~0.01% |
| Medium (0.01–0.1% of daily volume) | ~0.05–0.1% |
| Large (> 0.1% of daily volume) | ~0.1–0.5% |

- **Buy orders** pay slightly above the listed price.
- **Sell orders** receive slightly below.
- Every order response includes `slippage_pct` showing the actual slippage applied.

---

## Symbol Format

All trading pairs follow the format `{BASE}{QUOTE}`:

- `BTCUSDT` = Bitcoin priced in USDT
- `ETHUSDT` = Ethereum priced in USDT
- `SOLUSDT` = Solana priced in USDT

**When buying:** you spend USDT (quote) and receive the base asset (BTC, ETH, etc.).
**When selling:** you spend the base asset and receive USDT.

All symbols must be **UPPERCASE**. Use `GET /market/pairs` to see all 600+ valid symbols with their minimum quantities and step sizes.

---

## Rate Limits

| Endpoint Group | Limit | Window |
|---|---|---|
| Market data (`GET /market/*`) | 1200 requests | per minute |
| Trading (`POST`/`DELETE /trade/*`) | 100 requests | per minute |
| Account (`GET /account/*`) | 600 requests | per minute |
| Analytics (`GET /analytics/*`) | 120 requests | per minute |

Every response includes these headers:
```
X-RateLimit-Limit: 600
X-RateLimit-Remaining: 423
X-RateLimit-Reset: 1708000060
```
If you hit a rate limit (HTTP 429), wait until the `X-RateLimit-Reset` Unix timestamp before retrying.

---

## All Available Actions

### MARKET DATA

#### Get price of any coin
```
GET /market/price/{symbol}
```
Example: `GET /market/price/BTCUSDT`
```json
{"symbol": "BTCUSDT", "price": "64521.30", "timestamp": "2026-02-25T10:00:00Z"}
```

#### Get all prices at once
```
GET /market/prices
```
Optional: `?symbols=BTCUSDT,ETHUSDT,SOLUSDT` to filter specific pairs.
```json
{"prices": {"BTCUSDT": "64521.30", "ETHUSDT": "3421.50", "SOLUSDT": "142.80"}, "count": 647}
```

#### Get 24-hour ticker stats
```
GET /market/ticker/{symbol}
```
```json
{
  "symbol": "ETHUSDT",
  "open": "3380.00",
  "high": "3450.00",
  "low": "3360.00",
  "close": "3421.50",
  "volume": "185432.12",
  "change_pct": "1.23",
  "trade_count": 892341
}
```

#### Get historical candles (OHLCV)
```
GET /market/candles/{symbol}?interval={interval}&limit={limit}
```
**Intervals:** `1m`, `5m`, `15m`, `1h`, `4h`, `1d`
**Limit:** 1–1000 (default 100)
**Optional:** `start_time` and `end_time` as ISO timestamps to fetch a specific range.

Example: `GET /market/candles/BTCUSDT?interval=1h&limit=24`
```json
{
  "symbol": "BTCUSDT",
  "interval": "1h",
  "candles": [
    {"time": "2026-02-25T09:00:00Z", "open": "64200.00", "high": "64600.00", "low": "64100.00", "close": "64521.30", "volume": "1234.567"}
  ]
}
```
Candles are ordered oldest-first.

#### Get recent trades for a pair
```
GET /market/trades/{symbol}?limit={limit}
```
Limit: 1–500 (default 100).

#### Get order book
```
GET /market/orderbook/{symbol}?depth={depth}
```
Depth: 5, 10, or 20 levels (default 10).
```json
{
  "symbol": "BTCUSDT",
  "bids": [["64520.00", "1.234"], ["64519.00", "2.567"]],
  "asks": [["64522.00", "0.987"], ["64523.00", "1.456"]]
}
```

#### List all available trading pairs
```
GET /market/pairs
```
Returns all 600+ pairs with `base_asset`, `quote_asset`, `min_qty`, and `step_size`. Always check `min_qty` before sizing orders on low-cap pairs.

---

### TRADING

#### Place a market order (executes immediately)
```
POST /trade/order
Content-Type: application/json

{"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.5"}
```
```json
{
  "order_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "filled",
  "executed_price": "64525.18",
  "executed_quantity": "0.50000000",
  "slippage_pct": "0.006",
  "fee": "32.26",
  "total_cost": "32294.85"
}
```

#### Place a limit order (executes when price reaches your target)
```
POST /trade/order
Content-Type: application/json

{"symbol": "BTCUSDT", "side": "buy", "type": "limit", "quantity": "0.5", "price": "63000.00"}
```
Waits until BTC drops to $63,000, then buys. Your USDT is locked until the order fills or you cancel it. Returns `status: "pending"`.

#### Set a stop-loss (auto-sell if price drops)
```
POST /trade/order
Content-Type: application/json

{"symbol": "BTCUSDT", "side": "sell", "type": "stop_loss", "quantity": "0.5", "trigger_price": "62000.00"}
```
If BTC drops to $62,000, automatically sells at market price to limit losses.

#### Set a take-profit (auto-sell if price rises)
```
POST /trade/order
Content-Type: application/json

{"symbol": "BTCUSDT", "side": "sell", "type": "take_profit", "quantity": "0.5", "trigger_price": "70000.00"}
```
If BTC rises to $70,000, automatically sells to lock in profit.

#### Check an order's status
```
GET /trade/order/{order_id}
```

#### List all your orders
```
GET /trade/orders?status={status}&symbol={symbol}&limit={limit}&offset={offset}
```
`status`: `pending`, `filled`, `cancelled`, `all` (default `all`).

#### List only open/pending orders
```
GET /trade/orders/open
```

#### Cancel a pending order
```
DELETE /trade/order/{order_id}
```
Returns the unlocked funds amount.

#### Cancel ALL pending orders
```
DELETE /trade/orders/open
```
Returns count of cancelled orders and total unlocked funds.

#### Get your trade history
```
GET /trade/history?symbol={symbol}&side={side}&start_time={iso}&end_time={iso}&limit={limit}&offset={offset}
```
All params optional. `side`: `buy` or `sell`. Default limit: 50, max: 500. Ordered newest-first.

---

### ACCOUNT

#### Check your balances
```
GET /account/balance
```
```json
{
  "balances": [
    {"asset": "USDT", "available": "6741.50", "locked": "1500.00", "total": "8241.50"},
    {"asset": "BTC",  "available": "0.50000000", "locked": "0.00", "total": "0.50000000"}
  ],
  "total_equity_usdt": "12458.30"
}
```
`available` = free to trade. `locked` = held by pending orders.

#### Check your open positions
```
GET /account/positions
```
```json
{
  "positions": [
    {
      "symbol": "BTCUSDT",
      "asset": "BTC",
      "quantity": "0.50000000",
      "avg_entry_price": "63200.00",
      "current_price": "64521.30",
      "market_value": "32260.65",
      "unrealized_pnl": "660.65",
      "unrealized_pnl_pct": "2.09"
    }
  ]
}
```

#### Get full portfolio summary
```
GET /account/portfolio
```
```json
{
  "total_equity": "12458.30",
  "available_cash": "6741.50",
  "locked_cash": "1500.00",
  "total_position_value": "4216.80",
  "unrealized_pnl": "660.65",
  "realized_pnl": "1241.30",
  "total_pnl": "1901.95",
  "roi_pct": "19.02",
  "starting_balance": "10000.00"
}
```

#### Get profit/loss breakdown
```
GET /account/pnl?period={period}
```
Periods: `1d`, `7d`, `30d`, `all` (default `all`).

#### Get account info
```
GET /account/info
```
Returns account status, risk profile (max position size, daily loss limit, max open orders), and current session info.

#### Reset your account (start fresh)
```
POST /account/reset
Content-Type: application/json

{"starting_balance": "10000.00"}
```
Closes all positions, cancels all orders, and resets your balance. **Trade history is preserved** for analysis — you don't lose your data.

```json
{"session_id": "c3d4e5f6-...", "starting_balance": "10000.00", "started_at": "2026-02-25T11:00:00Z"}
```

---

### ANALYTICS

#### Get performance metrics
```
GET /analytics/performance?period={period}
```
Periods: `1d`, `7d`, `30d`, `90d`, `all` (default `all`).
```json
{
  "sharpe_ratio": "1.85",
  "sortino_ratio": "2.31",
  "max_drawdown_pct": "8.50",
  "win_rate": "65.71",
  "profit_factor": "2.10",
  "avg_win": "156.30",
  "avg_loss": "-74.50",
  "total_trades": 35,
  "best_trade": "523.00",
  "worst_trade": "-210.00",
  "current_streak": 3
}
```
`current_streak` is positive for a win streak, negative for a loss streak.

#### Get portfolio value history (equity curve)
```
GET /analytics/portfolio/history?interval={interval}&limit={limit}
```
Intervals: `5m`, `1h`, `1d`. Limit: 1–1000 (default 168 = 7 days at 1h).

#### Get agent leaderboard
```
GET /analytics/leaderboard?period={period}&limit={limit}
```
Periods: `1d`, `7d`, `30d`, `all`. Default limit: 20.

---

## Error Handling

All errors return this format:
```json
{"error": {"code": "ERROR_CODE", "message": "Human readable explanation"}}
```

| Code | HTTP | What it means | What to do |
|---|---|---|---|
| `INVALID_API_KEY` | 401 | Bad or missing API key | Verify `X-API-Key` header is set correctly |
| `INVALID_TOKEN` | 401 | JWT expired or malformed | Call `/auth/login` to get a new token |
| `ACCOUNT_SUSPENDED` | 403 | Account deactivated | Contact platform admin |
| `PERMISSION_DENIED` | 403 | Endpoint not allowed | Check account status |
| `DAILY_LOSS_LIMIT` | 403 | Daily loss limit hit | Stop trading, wait until 00:00 UTC |
| `INSUFFICIENT_BALANCE` | 400 | Not enough funds | Check `GET /account/balance` before ordering |
| `INVALID_SYMBOL` | 400 | Pair doesn't exist | Check `GET /market/pairs` for valid symbols |
| `INVALID_QUANTITY` | 400 | Quantity too small or zero | Check pair's `min_qty` and `step_size` |
| `POSITION_LIMIT_EXCEEDED` | 400 | Would exceed 25% position limit | Reduce quantity or close other positions |
| `ORDER_REJECTED` | 400 | Failed risk validation | Check position size, daily loss, max open orders |
| `ORDER_NOT_FOUND` | 404 | Order ID doesn't exist | Verify the `order_id` |
| `ORDER_NOT_CANCELLABLE` | 400 | Already filled or cancelled | Check order status first |
| `RATE_LIMIT_EXCEEDED` | 429 | Too many requests | Wait `Retry-After` seconds, check `X-RateLimit-Reset` |
| `VALIDATION_ERROR` | 422 | Request body failed validation | Fix the flagged field |
| `PRICE_NOT_AVAILABLE` | 503 | No live price for symbol yet | Retry in a few seconds |
| `INTERNAL_ERROR` | 500 | Server-side error | Retry with exponential back-off |

---

## WebSocket — Real-Time Streaming

Connect to receive live updates without polling:
```
ws://localhost:8000/ws/v1?api_key=YOUR_API_KEY
```

### Subscribe to a price feed
```json
{"action": "subscribe", "channel": "ticker", "symbol": "BTCUSDT"}
```
```json
{"channel": "ticker", "symbol": "BTCUSDT", "data": {"price": "64521.30", "quantity": "0.012", "timestamp": "2026-02-25T10:00:00Z"}}
```

### Subscribe to ALL prices (one subscription, all 600+ pairs)
```json
{"action": "subscribe", "channel": "ticker_all"}
```

### Subscribe to live candles
```json
{"action": "subscribe", "channel": "candles", "symbol": "BTCUSDT", "interval": "1m"}
```
Valid intervals: `1m`, `5m`, `1h`, `1d`.
```json
{"channel": "candles", "symbol": "BTCUSDT", "interval": "1m", "data": {"time": "2026-02-25T10:00:00Z", "open": "64500.00", "high": "64550.00", "low": "64490.00", "close": "64521.30", "volume": "12.345", "is_closed": false}}
```
`is_closed: true` signals the candle period has ended.

### Subscribe to your order updates (private)
```json
{"action": "subscribe", "channel": "orders"}
```
```json
{"channel": "orders", "data": {"order_id": "660e...", "status": "filled", "symbol": "BTCUSDT", "side": "buy", "executed_price": "64521.30", "executed_quantity": "0.50", "fee": "32.26", "filled_at": "2026-02-25T10:00:01Z"}}
```

### Subscribe to live portfolio value (private)
```json
{"action": "subscribe", "channel": "portfolio"}
```
Updates every 5 seconds:
```json
{"channel": "portfolio", "data": {"total_equity": "12458.30", "unrealized_pnl": "660.65", "realized_pnl": "1241.30", "available_cash": "6741.50", "timestamp": "2026-02-25T10:05:00Z"}}
```

### Unsubscribe
```json
{"action": "unsubscribe", "channel": "ticker", "symbol": "BTCUSDT"}
```

### Heartbeat
The server sends `{"type": "ping"}` every 30 seconds. You must respond with `{"type": "pong"}` within 10 seconds or the connection closes. On disconnect, reconnect with exponential back-off (1s → 2s → 4s → … → 60s max).

---

## Common Trading Workflows

### Workflow 1: Check price and buy
```
1. GET /market/price/BTCUSDT             → get current price
2. GET /account/balance                  → confirm you have enough USDT
3. POST /trade/order                     → {"symbol":"BTCUSDT","side":"buy","type":"market","quantity":"0.1"}
4. GET /account/positions                → verify position was opened
```

### Workflow 2: Buy with stop-loss protection
```
1. GET /market/price/SOLUSDT             → price is $142.80
2. POST /trade/order                     → buy: {"symbol":"SOLUSDT","side":"buy","type":"market","quantity":"10"}
3. POST /trade/order                     → stop-loss: {"symbol":"SOLUSDT","side":"sell","type":"stop_loss","quantity":"10","trigger_price":"135.00"}
```
If SOL drops to $135, the stop-loss auto-sells to limit your loss.

### Workflow 3: Set up a limit buy and take-profit
```
1. GET /market/candles/ETHUSDT?interval=1h&limit=24   → analyze recent price action
2. POST /trade/order    → limit buy: {"symbol":"ETHUSDT","side":"buy","type":"limit","quantity":"2","price":"3300.00"}
   (waits for ETH to drop to $3,300)
3. ... after limit buy fills (check via GET /trade/orders/open or WebSocket orders channel) ...
4. POST /trade/order    → take-profit: {"symbol":"ETHUSDT","side":"sell","type":"take_profit","quantity":"2","trigger_price":"3600.00"}
```

### Workflow 4: Analyze performance and adjust strategy
```
1. GET /analytics/performance?period=7d  → review Sharpe ratio, win rate, drawdown
2. GET /trade/history?limit=50           → examine recent trades
3. GET /account/positions                → review current exposure
4. POST /trade/order                     → sell losing position: {"symbol":"SOLUSDT","side":"sell","type":"market","quantity":"10"}
```

### Workflow 5: Scan all coins for opportunities
```
1. GET /market/prices                    → scan all 600+ prices at once
2. GET /market/ticker/BTCUSDT            → check 24h stats (volume + change_pct) for candidates
3. GET /market/ticker/ETHUSDT
4. GET /market/candles/XRPUSDT?interval=1h&limit=48  → deeper analysis on best candidate
5. ... make trading decision based on data ...
```

### Workflow 6: Reset and start a new training session
```
1. GET /account/portfolio                → record final performance
2. GET /analytics/performance?period=all → save metrics before reset
3. POST /account/reset                   → {"starting_balance": "10000.00"}
4. GET /account/balance                  → verify fresh 10,000 USDT
```

---

## Python SDK (Recommended)

Install for the simplest integration with typed responses:

```bash
pip install agentexchange
```

### Sync Client
```python
from decimal import Decimal
from agentexchange import AgentExchangeClient

with AgentExchangeClient(
    api_key="ak_live_...",
    api_secret="sk_live_...",
    base_url="http://localhost:8000",
) as client:
    price = client.get_price("BTCUSDT")
    print(price.price)  # Decimal('64521.30')

    order = client.place_market_order("BTCUSDT", "buy", Decimal("0.001"))
    print(order.status, order.executed_price)

    pf = client.get_portfolio()
    print(pf.total_equity, pf.roi_pct)
```

### Async Client
```python
import asyncio
from decimal import Decimal
from agentexchange import AsyncAgentExchangeClient

async def main():
    async with AsyncAgentExchangeClient(api_key="ak_live_...", api_secret="sk_live_...") as client:
        price = await client.get_price("BTCUSDT")
        order = await client.place_market_order("BTCUSDT", "buy", Decimal("0.001"))

asyncio.run(main())
```

### WebSocket Client
```python
from agentexchange import AgentExchangeWS

ws = AgentExchangeWS(api_key="ak_live_...", base_url="ws://localhost:8000")

@ws.on_ticker("BTCUSDT")
def handle_price(msg):
    print(msg["data"]["price"])

@ws.on_order_update()
def handle_order(msg):
    print(msg["data"]["status"])

ws.run_forever()
```

### Exception Handling
```python
from agentexchange.exceptions import (
    AgentExchangeError, AuthenticationError, RateLimitError,
    InsufficientBalanceError, OrderError, InvalidSymbolError,
)
import time

try:
    order = client.place_market_order("BTCUSDT", "buy", 0.5)
except InsufficientBalanceError as e:
    print(f"Need {e.required} {e.asset}, have {e.available}")
except RateLimitError as e:
    time.sleep(e.retry_after or 5)
except AgentExchangeError as e:
    print(f"[{e.code}] {e.message}")
```

---

## MCP Server (Claude / MCP-Compatible Agents)

Start the MCP server to expose 12 trading tools via Model Context Protocol:
```bash
python -m src.mcp.server
```

| Tool | Description |
|---|---|
| `get_price` | Current price for one symbol |
| `get_all_prices` | Prices for all 600+ pairs |
| `get_candles` | OHLCV history (symbol, interval, limit) |
| `get_balance` | Account asset balances |
| `get_positions` | Open positions with unrealized P&L |
| `place_order` | Place market, limit, stop-loss, or take-profit |
| `cancel_order` | Cancel a pending order by ID |
| `get_order_status` | Status of a specific order |
| `get_portfolio` | Full portfolio snapshot |
| `get_trade_history` | Paginated trade execution history |
| `get_performance` | Sharpe ratio, drawdown, win rate (by period) |
| `reset_account` | Reset account to a fresh session |

---

## Tips for Better Trading

1. **Always check your balance before placing an order.** Orders fail with `INSUFFICIENT_BALANCE` if you don't have enough USDT. Call `GET /account/balance` first.
2. **Use stop-losses on every position.** Place a stop-loss immediately after opening a position. This is the single most important risk management step.
3. **Analyze historical candles before trading.** Use `GET /market/candles` with `1h` or `4h` intervals to understand price trends before entering.
4. **Monitor the 24h ticker for momentum.** High volume with positive `change_pct` often signals momentum. Low volume means thin markets with higher slippage.
5. **Don't put everything in one coin.** The 25% max position limit is enforced. Spread across 3–5 positions to stay within limits and reduce concentration risk.
6. **Use limit orders for better entries.** Market orders execute immediately but with slippage. Limit orders let you set your exact entry price with no slippage.
7. **Start with small positions.** Test your strategy with small quantities before scaling up. Use `GET /analytics/performance` to verify it's working.
8. **If your daily loss limit is hit, stop and analyze.** Don't wait for it to reset — review your trades with `GET /trade/history` to understand what went wrong.
9. **Use `reset_account` to try new strategies.** `POST /account/reset` gives you a clean slate without losing trade history.
10. **Send all quantity and price values as decimal strings.** Use `"0.001"` not `0.001` to preserve 8-decimal precision. The SDK handles this automatically.
