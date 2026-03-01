# AgentExchange — 5-Minute Quickstart

Get your AI agent trading against live Binance prices in 5 minutes.

**What you'll do:**

1. Start the platform with Docker
2. Register an account and get your API key
3. Fetch a live price
4. Place a market order
5. Check your portfolio

---

## Prerequisites

- Docker and Docker Compose installed
- Python 3.12+ (for SDK samples)
- `curl` available in your terminal

---

## Step 1 — Start the Platform

Clone the repository (if you haven't already) and bring up all services:

```bash
git clone https://github.com/your-org/agentexchange.git
cd agentexchange
cp .env.example .env
docker compose up -d
```

Wait ~15 seconds for all services to be healthy, then verify:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{
  "status": "ok",
  "services": {
    "redis": "ok",
    "timescaledb": "ok",
    "ingestion": "ok"
  }
}
```

> If `ingestion` shows `degraded`, wait another 10–20 seconds for the Binance WebSocket connection to fully initialise and seed live prices.

### Services started by Docker Compose

| Service | URL | Purpose |
|---|---|---|
| API | `http://localhost:8000` | REST + WebSocket |
| API docs | `http://localhost:8000/docs` | Interactive Swagger UI |
| Grafana | `http://localhost:3000` | Monitoring dashboards |
| Prometheus | `http://localhost:9090` | Raw metrics |

---

## Step 2 — Register an Account

You need an account to get an API key. Register once and save the credentials immediately — the `api_secret` is shown only at registration time.

### curl

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"display_name": "MyTradingBot", "starting_balance": "10000.00"}'
```

Response:

```json
{
  "account_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "api_key": "ak_live_abc123...",
  "api_secret": "sk_live_xyz789...",
  "starting_balance": "10000.00",
  "created_at": "2026-02-26T10:00:00Z"
}
```

> **Save `api_key` and `api_secret` now.** You cannot retrieve `api_secret` again.

### Python SDK

Install the SDK first:

```bash
pip install agentexchange
```

```python
from agentexchange import AgentExchangeClient

# Register a new account
with AgentExchangeClient(base_url="http://localhost:8000") as client:
    account = client.register(display_name="MyTradingBot", starting_balance="10000.00")
    print(account.api_key)     # ak_live_abc123...
    print(account.api_secret)  # sk_live_xyz789...  ← save this!
```

---

## Step 3 — Get a Live Price

Prices are sourced tick-by-tick from Binance WebSocket streams and served from Redis in sub-millisecond time.

### curl

```bash
export API_KEY="ak_live_abc123..."  # replace with your key

curl -s http://localhost:8000/api/v1/market/price/BTCUSDT \
  -H "X-API-Key: $API_KEY"
```

Response:

```json
{
  "symbol": "BTCUSDT",
  "price": "64521.30",
  "timestamp": "2026-02-26T10:00:01Z"
}
```

To fetch multiple prices at once:

```bash
curl -s "http://localhost:8000/api/v1/market/prices?symbols=BTCUSDT,ETHUSDT,SOLUSDT" \
  -H "X-API-Key: $API_KEY"
```

```json
{
  "prices": {
    "BTCUSDT": "64521.30",
    "ETHUSDT": "3421.50",
    "SOLUSDT": "142.80"
  },
  "count": 3
}
```

### Python SDK

```python
from agentexchange import AgentExchangeClient

with AgentExchangeClient(
    api_key="ak_live_abc123...",
    api_secret="sk_live_xyz789...",
    base_url="http://localhost:8000",
) as client:
    price = client.get_price("BTCUSDT")
    print(price.symbol)     # BTCUSDT
    print(price.price)      # Decimal('64521.30')
    print(price.timestamp)  # datetime(2026, 2, 26, 10, 0, 1)
```

---

## Step 4 — Place a Market Order

Market orders execute immediately at the current live price (with small slippage to simulate real market conditions). Your account starts with 10,000 USDT.

### curl

```bash
curl -s -X POST http://localhost:8000/api/v1/trade/order \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.01"}'
```

Response:

```json
{
  "order_id": "660e8400-e29b-41d4-a716-446655440001",
  "symbol": "BTCUSDT",
  "side": "buy",
  "type": "market",
  "status": "filled",
  "executed_price": "64525.18",
  "executed_quantity": "0.01000000",
  "slippage_pct": "0.006",
  "fee": "0.65",
  "total_cost": "645.90",
  "filled_at": "2026-02-26T10:00:02Z"
}
```

To sell it back immediately:

```bash
curl -s -X POST http://localhost:8000/api/v1/trade/order \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "BTCUSDT", "side": "sell", "type": "market", "quantity": "0.01"}'
```

### Python SDK

```python
from decimal import Decimal
from agentexchange import AgentExchangeClient
from agentexchange.exceptions import InsufficientBalanceError, RateLimitError
import time

with AgentExchangeClient(
    api_key="ak_live_abc123...",
    api_secret="sk_live_xyz789...",
    base_url="http://localhost:8000",
) as client:
    # Check price first
    price = client.get_price("BTCUSDT")
    print(f"BTC is trading at ${price.price}")

    try:
        # Place a market buy order
        order = client.place_market_order(
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("0.01"),
        )
        print(f"Order {order.status}: bought {order.executed_quantity} BTC")
        print(f"  Price: ${order.executed_price}  Fee: ${order.fee}")
        print(f"  Slippage: {order.slippage_pct}%")

    except InsufficientBalanceError as e:
        print(f"Not enough funds: need {e.required} USDT, have {e.available}")
    except RateLimitError as e:
        time.sleep(e.retry_after or 5)
```

---

## Step 5 — Check Your Portfolio

View your current balances, open positions, and performance metrics.

### curl

```bash
# Full portfolio summary
curl -s http://localhost:8000/api/v1/account/portfolio \
  -H "X-API-Key: $API_KEY"
```

```json
{
  "total_equity": "10012.45",
  "available_cash": "9367.10",
  "locked_cash": "0.00",
  "total_position_value": "645.35",
  "unrealized_pnl": "-0.55",
  "realized_pnl": "0.00",
  "total_pnl": "-0.55",
  "roi_pct": "-0.01",
  "starting_balance": "10000.00"
}
```

```bash
# Individual asset balances
curl -s http://localhost:8000/api/v1/account/balance \
  -H "X-API-Key: $API_KEY"
```

```json
{
  "balances": [
    {"asset": "USDT", "available": "9367.10", "locked": "0.00", "total": "9367.10"},
    {"asset": "BTC",  "available": "0.01000000", "locked": "0.00", "total": "0.01000000"}
  ],
  "total_equity_usdt": "10012.45"
}
```

```bash
# Open positions with unrealized P&L
curl -s http://localhost:8000/api/v1/account/positions \
  -H "X-API-Key: $API_KEY"
```

### Python SDK

```python
from agentexchange import AgentExchangeClient

with AgentExchangeClient(
    api_key="ak_live_abc123...",
    api_secret="sk_live_xyz789...",
    base_url="http://localhost:8000",
) as client:
    portfolio = client.get_portfolio()
    print(f"Total equity:    ${portfolio.total_equity}")
    print(f"Unrealized P&L:  ${portfolio.unrealized_pnl}")
    print(f"ROI:             {portfolio.roi_pct}%")

    positions = client.get_positions()
    for pos in positions:
        print(f"{pos.symbol}: {pos.quantity} @ avg ${pos.avg_entry_price}")
        print(f"  Current: ${pos.current_price}  Unrealized P&L: ${pos.unrealized_pnl}")
```

---

## What's Next

You're now up and running. Here are common next steps:

### Place a limit order with stop-loss protection

```bash
# Limit buy at $63,000
curl -s -X POST http://localhost:8000/api/v1/trade/order \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "BTCUSDT", "side": "buy", "type": "limit", "quantity": "0.01", "price": "63000.00"}'

# Stop-loss at $61,000 to limit downside
curl -s -X POST http://localhost:8000/api/v1/trade/order \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "BTCUSDT", "side": "sell", "type": "stop_loss", "quantity": "0.01", "trigger_price": "61000.00"}'
```

### Stream live prices via WebSocket

```bash
# Connect with wscat (npm install -g wscat)
wscat -c "ws://localhost:8000/ws/v1?api_key=$API_KEY"

# Then send:
> {"action": "subscribe", "channel": "ticker", "symbol": "BTCUSDT"}
```

```python
from agentexchange import AgentExchangeWS

ws = AgentExchangeWS(api_key="ak_live_abc123...", base_url="ws://localhost:8000")

@ws.on_ticker("BTCUSDT")
def handle_price(msg):
    price = msg["data"]["price"]
    print(f"BTC: ${price}")

@ws.on_order_update()
def handle_order(msg):
    order = msg["data"]
    print(f"Order {order['order_id']}: {order['status']}")

ws.run_forever()
```

### Use the MCP server (Claude agents)

```bash
# Start the MCP server
python -m src.mcp.server
```

The MCP server exposes 12 tools (`get_price`, `place_order`, `get_portfolio`, etc.) compatible with Claude and any MCP-aware agent framework.

### Reset and start a new session

```bash
curl -s -X POST http://localhost:8000/api/v1/account/reset \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"starting_balance": "10000.00"}'
```

This closes all positions, cancels pending orders, and restores 10,000 USDT — while preserving your trade history for analysis.

---

## Further Reading

| Document | Description |
|---|---|
| [`docs/api_reference.md`](api_reference.md) | Complete REST API reference — every endpoint, parameter, and error code |
| [`docs/skill.md`](skill.md) | Drop-in LLM instruction file — paste into any agent's system prompt |
| [`docs/framework_guides/langchain.md`](framework_guides/langchain.md) | Wiring the SDK as LangChain Tools |
| [`docs/framework_guides/crewai.md`](framework_guides/crewai.md) | Using the SDK with CrewAI Agents |
| [`docs/framework_guides/agent_zero.md`](framework_guides/agent_zero.md) | Registering `skill.md` in Agent Zero |
| [`docs/framework_guides/openclaw.md`](framework_guides/openclaw.md) | OpenClaw configuration |
| `http://localhost:8000/docs` | Interactive Swagger UI — try every endpoint in the browser |
