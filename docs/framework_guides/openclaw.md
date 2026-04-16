# OpenClaw Integration Guide — AgentExchange

This guide shows you how to wire **AgentExchange** into an [OpenClaw](https://github.com/openclaw/openclaw) agent in under 10 minutes. AgentExchange exposes its full capability set as a `skill.md` file — the native format OpenClaw reads to give an LLM agent access to tools.

---

## What You Get

After following this guide your OpenClaw agent will be able to:

- Fetch live prices for any of 600+ Binance trading pairs
- Place, monitor, and cancel market / limit / stop-loss / take-profit orders
- Read account balances, open positions, and portfolio summary
- Pull performance analytics (Sharpe ratio, drawdown, win rate)
- Stream real-time prices and order notifications over WebSocket
- Reset its trading session to restart a strategy cleanly

All on simulated funds against real Binance market data.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| OpenClaw | latest (`pip install openclaw`) |
| AgentExchange server | running (see [quickstart](../quickstart.md)) |
| AgentExchange Python SDK | optional but recommended (`pip install agentexchange`) |

Start the platform with Docker Compose if you haven't already:

```bash
git clone https://github.com/tradeready/platform
cd agent-exchange
cp .env.example .env   # fill in JWT_SECRET and other required vars
docker compose up -d
```

Verify it's live:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

---

## Step 1 — Register an Account

Every agent needs an `api_key`. Register once and save the credentials:

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"display_name": "MyOpenClawBot", "starting_balance": "10000.00"}'
```

```json
{
  "account_id": "a1b2c3d4-...",
  "api_key": "ak_live_...",
  "api_secret": "sk_live_...",
  "starting_balance": "10000.00"
}
```

> **Save `api_secret` now — it is shown only once.**

---

## Step 2 — Point OpenClaw at the Skill File

`docs/skill.md` in this repository is the canonical LLM-readable instruction file for AgentExchange. It contains the full API reference, authentication instructions, WebSocket protocol, error codes, and trading workflows in a format that any LLM can parse and follow.

### Option A — Reference the file directly (local install)

In your OpenClaw agent config (`agent.yaml` or `openclaw.config.json`), add AgentExchange as a skill:

```yaml
# agent.yaml
name: trading-agent
model: claude-3-5-sonnet  # or any OpenClaw-supported model

skills:
  - path: /path/to/agent-exchange/docs/skill.md
    name: agentexchange
    description: >
      Simulated crypto exchange with real-time Binance prices.
      Trade 600+ pairs with virtual funds. Full REST + WebSocket API.

env:
  AGENTEXCHANGE_API_KEY: "ak_live_..."
  AGENTEXCHANGE_BASE_URL: "http://localhost:8000"
```

### Option B — Reference a hosted URL

If your AgentExchange instance is deployed, point directly at the hosted skill file:

```yaml
skills:
  - url: https://your-deployed-host/docs/skill.md
    name: agentexchange
    description: Simulated crypto exchange with live Binance data.
```

### Option C — Inline the skill in JSON config

```json
{
  "name": "trading-agent",
  "model": "claude-3-5-sonnet",
  "skills": [
    {
      "path": "./docs/skill.md",
      "name": "agentexchange",
      "description": "Simulated crypto exchange. 600+ pairs, virtual funds, live Binance prices."
    }
  ],
  "env": {
    "AGENTEXCHANGE_API_KEY": "ak_live_...",
    "AGENTEXCHANGE_BASE_URL": "http://localhost:8000"
  }
}
```

---

## Step 3 — Inject Credentials Into the Agent Context

The skill file tells the agent to include `X-API-Key: YOUR_API_KEY` on every request. You need to substitute the actual key at runtime. The cleanest approach is a system prompt injection:

```python
import openclaw

agent = openclaw.Agent.from_config("agent.yaml")

# Inject credentials into the system context so the agent always uses them
agent.add_context(
    "Your AgentExchange credentials:\n"
    f"  API Key: {os.environ['AGENTEXCHANGE_API_KEY']}\n"
    f"  Base URL: {os.environ['AGENTEXCHANGE_BASE_URL']}\n"
    "Always include `X-API-Key: <your key>` on every HTTP request.\n"
    "Never expose the api_secret in responses."
)

result = agent.run("Check the current BTC price and buy 0.01 BTC if it's below $65,000.")
print(result)
```

---

## Step 4 — Run the Agent

### Minimal example

```python
import os
import openclaw

agent = openclaw.Agent.from_config("agent.yaml")
agent.add_context(
    f"API Key: {os.environ['AGENTEXCHANGE_API_KEY']}\n"
    f"Base URL: {os.environ['AGENTEXCHANGE_BASE_URL']}"
)

# One-shot task
result = agent.run(
    "Check my balance, find the coin with the highest 24h change, "
    "and buy $200 worth at market price. Then set a 5% stop-loss."
)
print(result)
```

### Multi-turn conversation

```python
session = agent.start_session()

session.send("What's my current portfolio value?")
session.send("Which of my positions is performing best?")
session.send("Sell half of my best-performing position.")
```

### Autonomous loop with periodic review

```python
import time

session = agent.start_session()
session.send(
    "You are a momentum trading bot. Every 5 minutes:\n"
    "1. Scan all prices for coins up >3% in 24h.\n"
    "2. Buy the top candidate if you have enough balance and no current position.\n"
    "3. Set a stop-loss at -5% and take-profit at +10%.\n"
    "4. Report what you did."
)

while True:
    response = session.receive()
    print(response)
    time.sleep(300)
```

---

## Step 5 — Add SDK Tools (Optional, Recommended)

For tighter integration — typed responses, automatic retries, WebSocket streaming — wrap the Python SDK as OpenClaw tools. This is more robust than letting the LLM construct raw HTTP calls.

```python
import os
import openclaw
from decimal import Decimal
from agentexchange import AgentExchangeClient
from agentexchange.exceptions import AgentExchangeError, RateLimitError
import time

# Shared SDK client
_client = AgentExchangeClient(
    api_key=os.environ["AGENTEXCHANGE_API_KEY"],
    api_secret=os.environ["AGENTEXCHANGE_API_SECRET"],
    base_url=os.environ.get("AGENTEXCHANGE_BASE_URL", "http://localhost:8000"),
)

# --- Tool definitions ---

@openclaw.tool(description="Get the current price of a trading pair, e.g. BTCUSDT")
def get_price(symbol: str) -> dict:
    price = _client.get_price(symbol)
    return {"symbol": price.symbol, "price": str(price.price), "timestamp": price.timestamp.isoformat()}

@openclaw.tool(description="Get account balances for all assets")
def get_balance() -> dict:
    balance = _client.get_balance()
    return {
        "total_equity_usdt": str(balance.total_equity_usdt),
        "balances": [
            {"asset": b.asset, "available": str(b.available), "total": str(b.total)}
            for b in balance.balances
        ],
    }

@openclaw.tool(description="Place a market, limit, stop_loss, or take_profit order")
def place_order(symbol: str, side: str, order_type: str, quantity: str, price: str = None, trigger_price: str = None) -> dict:
    """
    Args:
        symbol: Trading pair e.g. 'BTCUSDT'
        side: 'buy' or 'sell'
        order_type: 'market', 'limit', 'stop_loss', or 'take_profit'
        quantity: Quantity as decimal string e.g. '0.01'
        price: Required for limit orders. Decimal string.
        trigger_price: Required for stop_loss / take_profit. Decimal string.
    """
    kwargs = {}
    if price:
        kwargs["price"] = Decimal(price)
    if trigger_price:
        kwargs["trigger_price"] = Decimal(trigger_price)
    order = _client.place_order(
        symbol=symbol, side=side, order_type=order_type, quantity=Decimal(quantity), **kwargs
    )
    return {
        "order_id": str(order.order_id),
        "status": order.status,
        "executed_price": str(order.executed_price) if order.executed_price else None,
        "slippage_pct": str(order.slippage_pct) if order.slippage_pct else None,
    }

@openclaw.tool(description="Get full portfolio summary including PnL and ROI")
def get_portfolio() -> dict:
    pf = _client.get_portfolio()
    return {
        "total_equity": str(pf.total_equity),
        "roi_pct": str(pf.roi_pct),
        "unrealized_pnl": str(pf.unrealized_pnl),
        "realized_pnl": str(pf.realized_pnl),
        "available_cash": str(pf.available_cash),
    }

@openclaw.tool(description="Get performance metrics: Sharpe ratio, win rate, drawdown. period: 1d/7d/30d/all")
def get_performance(period: str = "all") -> dict:
    perf = _client.get_performance(period=period)
    return {
        "sharpe_ratio": str(perf.sharpe_ratio),
        "win_rate": str(perf.win_rate),
        "max_drawdown_pct": str(perf.max_drawdown_pct),
        "total_trades": perf.total_trades,
        "profit_factor": str(perf.profit_factor),
    }

@openclaw.tool(description="Reset account to a fresh session with the given starting balance (USDT string)")
def reset_account(starting_balance: str = "10000.00") -> dict:
    session = _client.reset_account(starting_balance=Decimal(starting_balance))
    return {"session_id": str(session.session_id), "starting_balance": str(session.starting_balance)}

# --- Build agent with SDK tools ---

agent = openclaw.Agent(
    model="claude-3-5-sonnet",
    tools=[get_price, get_balance, place_order, get_portfolio, get_performance, reset_account],
    system=(
        "You are a crypto trading agent operating on the AgentExchange simulated exchange. "
        "All funds are virtual — real Binance prices, no real risk. "
        "Always check balance before placing orders. "
        "Always set a stop-loss after opening a position. "
        "Report your actions and reasoning after each trade."
    ),
)

result = agent.run("Run a momentum scan and buy the strongest coin today.")
print(result)
```

---

## Step 6 — Add WebSocket Streaming (Real-Time Prices)

For agents that need to react to live price movements rather than polling:

```python
import threading
from agentexchange import AgentExchangeWS

# Price state shared between WS thread and agent
latest_prices: dict[str, str] = {}

ws = AgentExchangeWS(
    api_key=os.environ["AGENTEXCHANGE_API_KEY"],
    base_url=os.environ.get("AGENTEXCHANGE_WS_URL", "ws://localhost:8000"),
)

@ws.on_ticker("BTCUSDT")
def on_btc_price(msg):
    latest_prices["BTCUSDT"] = msg["data"]["price"]

@ws.on_ticker("ETHUSDT")
def on_eth_price(msg):
    latest_prices["ETHUSDT"] = msg["data"]["price"]

@ws.on_order_update()
def on_order(msg):
    data = msg["data"]
    print(f"Order {data['order_id']} → {data['status']} @ {data.get('executed_price', 'N/A')}")

# Run WS in a background thread so the agent loop stays free
ws_thread = threading.Thread(target=ws.run_forever, daemon=True)
ws_thread.start()

# Now your agent can read from latest_prices without network calls
@openclaw.tool(description="Get the most recently streamed price from the live feed")
def get_streamed_price(symbol: str) -> dict:
    price = latest_prices.get(symbol.upper())
    if not price:
        return {"error": f"No streamed price yet for {symbol}. Subscribe first or use get_price instead."}
    return {"symbol": symbol.upper(), "price": price, "source": "websocket"}
```

---

## Configuration Reference

### `agent.yaml` full example

```yaml
name: agentexchange-trading-bot
model: claude-3-5-sonnet

skills:
  - path: ./docs/skill.md
    name: agentexchange
    description: >
      Simulated crypto exchange with real-time Binance prices.
      REST API at /api/v1. Auth via X-API-Key header.

env:
  AGENTEXCHANGE_API_KEY: "${AGENTEXCHANGE_API_KEY}"
  AGENTEXCHANGE_API_SECRET: "${AGENTEXCHANGE_API_SECRET}"
  AGENTEXCHANGE_BASE_URL: "http://localhost:8000"
  AGENTEXCHANGE_WS_URL: "ws://localhost:8000"

system_prompt: |
  You are a trading agent on the AgentExchange platform.
  Base URL: ${AGENTEXCHANGE_BASE_URL}
  API Key: ${AGENTEXCHANGE_API_KEY}
  Include header X-API-Key: ${AGENTEXCHANGE_API_KEY} on every request.
  All values of type quantity or price must be decimal strings (e.g. "0.01", not 0.01).
  Always call GET /account/balance before placing any order.
  Always place a stop-loss immediately after opening a new position.

memory:
  enabled: true
  backend: local   # or redis / postgres for persistent memory

max_iterations: 50
timeout_seconds: 120
```

---

## Error Handling in OpenClaw Agents

The skill file includes a full error code table. When the LLM encounters an API error it should follow these patterns:

| Error Code | Recommended Agent Behaviour |
|---|---|
| `INSUFFICIENT_BALANCE` | Call `GET /account/balance`, reduce order quantity, retry |
| `RATE_LIMIT_EXCEEDED` | Read `X-RateLimit-Reset`, wait until that Unix timestamp, retry |
| `DAILY_LOSS_LIMIT` | Stop placing orders, report status, wait until 00:00 UTC |
| `INVALID_SYMBOL` | Call `GET /market/pairs` to get the correct symbol, retry |
| `INVALID_QUANTITY` | Call `GET /market/pairs` to check `min_qty` and `step_size`, recalculate |
| `ORDER_REJECTED` | Check position limits and open order count before retrying |
| `PRICE_NOT_AVAILABLE` | Retry after 2–3 seconds; the ingestion service may be warming up |
| `INTERNAL_ERROR` | Retry with exponential back-off (1s, 2s, 4s, 8s, max 60s) |

If you are using the SDK tools wrapper from Step 5, these errors surface as typed Python exceptions (`RateLimitError`, `InsufficientBalanceError`, etc.) that you can handle in the tool implementation before they ever reach the LLM.

---

## Troubleshooting

**Agent says "I cannot access the API"**
- Verify the platform is running: `curl http://localhost:8000/health`
- Confirm the `api_key` in the agent context matches a registered account
- Check that `base_url` does not have a trailing slash

**`PRICE_NOT_AVAILABLE` on startup**
- The Binance WebSocket ingestion service needs ~30 seconds to stream initial prices for all pairs after a cold start. Wait and retry.

**Agent constructs malformed request bodies**
- Add an explicit reminder in the system prompt: *"All quantity and price fields must be decimal strings in quotes, e.g. `\"quantity\": \"0.01\"`, never bare numbers."*
- Alternatively, use the typed SDK tools wrapper (Step 5) — it handles serialization automatically.

**Rate limit hit during scans**
- `GET /market/prices` (a single call) returns all 600+ prices at once. Use it instead of looping over `/market/price/{symbol}`.

**WebSocket disconnects**
- The `AgentExchangeWS` client has a built-in reconnect loop with exponential back-off. If you bypass it with raw `websockets`, implement the same: 1s → 2s → 4s → … → 60s max, and respond to `{"type":"ping"}` with `{"type":"pong"}` within 10 seconds.

---

## Next Steps

- **LangChain integration** → see [`docs/framework_guides/langchain.md`](langchain.md)
- **Agent Zero integration** → see [`docs/framework_guides/agent_zero.md`](agent_zero.md)
- **CrewAI integration** → see [`docs/framework_guides/crewai.md`](crewai.md)
- **Full API reference** → [`docs/api_reference.md`](../api_reference.md)
- **5-minute quickstart** → [`docs/quickstart.md`](../quickstart.md)
- **LLM skill file** → [`docs/skill.md`](../skill.md)
