# Agent Zero Integration Guide — AgentExchange

This guide shows you how to connect **AgentExchange** to an [Agent Zero](https://github.com/frdel/agent-zero) agent in under 10 minutes. Agent Zero reads skill files — plain-text Markdown instruction files — to extend an LLM agent's knowledge and capabilities. Drop `docs/skill.md` into Agent Zero's skill directory and your agent instantly knows how to trade on a simulated crypto exchange backed by real-time Binance prices.

---

## What You Get

After following this guide your Agent Zero agent will be able to:

- Fetch live prices for any of 600+ Binance trading pairs
- Place, monitor, and cancel market / limit / stop-loss / take-profit orders
- Read account balances, open positions, and portfolio summary
- Pull performance analytics (Sharpe ratio, drawdown, win rate)
- Stream real-time prices and order notifications over WebSocket
- Reset its trading session to restart a strategy cleanly

All on simulated funds backed by real Binance market data.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| Agent Zero | latest (`git clone https://github.com/frdel/agent-zero`) |
| AgentExchange server | running (see [quickstart](../quickstart.md)) |
| AgentExchange Python SDK | optional but recommended (`pip install agentexchange`) |

Start the AgentExchange platform with Docker Compose if you haven't already:

```bash
git clone https://github.com/tradeready/platform
cd agent-exchange
cp .env.example .env   # fill in JWT_SECRET and other required vars
docker compose up -d
```

Verify it is live:

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
  -d '{"display_name": "MyAgentZeroBot", "starting_balance": "10000.00"}'
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

Store both values in a `.env` file (never commit this):

```bash
AGENTEXCHANGE_API_KEY=ak_live_...
AGENTEXCHANGE_API_SECRET=sk_live_...
AGENTEXCHANGE_BASE_URL=http://localhost:8000
AGENTEXCHANGE_WS_URL=ws://localhost:8000
```

---

## Step 2 — Drop the Skill File Into Agent Zero

`docs/skill.md` in this repository is the canonical LLM-readable instruction file for AgentExchange. It contains the full API reference, authentication instructions, WebSocket protocol, error codes, and trading workflows in plain Markdown that any LLM can parse and follow.

Agent Zero discovers skills by scanning a configurable skills directory. Copy (or symlink) the skill file there:

### Option A — Copy the file

```bash
# From the agent-exchange repo root
cp docs/skill.md /path/to/agent-zero/skills/agentexchange.md
```

### Option B — Symlink (stays in sync with updates)

```bash
ln -s "$(pwd)/docs/skill.md" /path/to/agent-zero/skills/agentexchange.md
```

### Option C — Point Agent Zero at a hosted URL

If your AgentExchange instance is publicly deployed, you can configure Agent Zero to fetch the skill file directly from the server. In Agent Zero's `settings.json` or startup config, add the hosted URL as a remote skill source:

```json
{
  "skills": [
    {
      "name": "agentexchange",
      "url": "https://your-deployed-host/docs/skill.md"
    }
  ]
}
```

After placing the file, restart Agent Zero so it picks up the new skill on its next context-building pass.

---

## Step 3 — Inject Credentials Into the Agent Context

The skill file instructs the agent to include `X-API-Key: YOUR_API_KEY` on every request. You need to supply the actual key at runtime. The cleanest approach is to add a system-level instruction that Agent Zero loads at startup.

### Option A — System prompt / initial context string

In your Agent Zero startup script, set the initial context before the first run:

```python
import os
from python.helpers.dotenv import load_dotenv
import agent  # Agent Zero's main agent module

load_dotenv()

# Build the agent and inject credentials into its persistent context
a = agent.AgentContext.get(0)  # get or create the primary agent context
a.system_note(
    "AgentExchange credentials:\n"
    f"  API Key:  {os.environ['AGENTEXCHANGE_API_KEY']}\n"
    f"  Base URL: {os.environ['AGENTEXCHANGE_BASE_URL']}\n"
    "Always include `X-API-Key: <your key>` on every HTTP request to AgentExchange.\n"
    "Never expose the api_secret in responses or tool outputs."
)
```

### Option B — Agent Zero `.env` + system prompt template

Agent Zero supports variable substitution in its system prompt template (`prompts/default/agent.system.md`). Add the following block to that file:

```markdown
## AgentExchange Trading Platform

You have access to a simulated cryptocurrency exchange via the AgentExchange skill.

- Base URL: {{env.AGENTEXCHANGE_BASE_URL}}
- API Key: {{env.AGENTEXCHANGE_API_KEY}}
- Always include header: `X-API-Key: {{env.AGENTEXCHANGE_API_KEY}}` on every request.
- All quantity and price values must be decimal strings (e.g. `"0.01"`, not `0.01`).
- Check your balance before every order. Set a stop-loss after every new position.
```

Then ensure `.env` exports the required variables before starting Agent Zero.

---

## Step 4 — Run the Agent

Once the skill file is in place and credentials are injected, Agent Zero uses the skill context to answer trading-related prompts autonomously.

### Minimal one-shot example

Start Agent Zero normally and send a task:

```python
import os
from python.helpers.dotenv import load_dotenv

load_dotenv()

# Agent Zero's standard run entrypoint
from run_ui import app   # or run_cli for terminal mode
app.run(debug=False)
```

Then send a message in the Agent Zero UI or CLI:

```
Check the current BTC price and buy 0.01 BTC if it's below $65,000.
Then set a stop-loss at $62,000.
```

Agent Zero will read the skill file, construct the correct HTTP calls with your injected API key, and execute the strategy step by step.

### Multi-step strategy prompt

```
You are a momentum trading bot.
1. Scan all prices and find the coin with the highest 24-hour percentage gain.
2. Check my available USDT balance.
3. Buy $500 worth of that coin at market price.
4. Immediately set a stop-loss at -5% of the entry price.
5. Set a take-profit at +10% of the entry price.
6. Report every action taken and the final positions.
```

### Autonomous loop with portfolio review

```
Every 10 minutes:
1. Call GET /account/portfolio and report total equity and ROI.
2. If any position has unrealized PnL > 15%, sell half of it to lock in profit.
3. If total equity has dropped below 90% of starting balance, cancel all open orders and hold cash.
4. Log what you did each cycle.
```

---

## Step 5 — Add SDK Tools (Optional, Recommended)

For tighter integration — typed responses, automatic retries, rate-limit handling — you can register Python functions backed by the AgentExchange SDK as Agent Zero tools. This is more robust than letting the LLM construct raw HTTP calls from the skill file alone.

### Install the SDK

```bash
# From the agent-exchange repo root
pip install -e sdk/
```

### Create a tool file

Agent Zero discovers Python tools placed in its `python/tools/` directory. Create `python/tools/agentexchange_tools.py`:

```python
"""AgentExchange trading tools for Agent Zero."""

import os
import time
from decimal import Decimal
from typing import Any

from python.helpers.tool import Tool, Response
from agentexchange import AgentExchangeClient
from agentexchange.exceptions import (
    AgentExchangeError,
    InsufficientBalanceError,
    RateLimitError,
    InvalidSymbolError,
    DailyLossLimitError,
)

_client: AgentExchangeClient | None = None


def _get_client() -> AgentExchangeClient:
    """Return a shared SDK client, initialising on first call."""
    global _client
    if _client is None:
        _client = AgentExchangeClient(
            api_key=os.environ["AGENTEXCHANGE_API_KEY"],
            api_secret=os.environ["AGENTEXCHANGE_API_SECRET"],
            base_url=os.environ.get("AGENTEXCHANGE_BASE_URL", "http://localhost:8000"),
        )
    return _client


class GetPrice(Tool):
    """Get the current price of a trading pair, e.g. BTCUSDT."""

    async def execute(self, symbol: str = "", **kwargs: Any) -> Response:
        try:
            price = _get_client().get_price(symbol.upper())
            return Response(
                message=f"{price.symbol}: ${price.price} (as of {price.timestamp.isoformat()})",
                break_loop=False,
            )
        except InvalidSymbolError:
            return Response(
                message=f"Unknown symbol '{symbol}'. Call list_pairs to see valid symbols.",
                break_loop=False,
            )
        except AgentExchangeError as exc:
            return Response(message=f"AgentExchange error: {exc}", break_loop=False)


class GetBalance(Tool):
    """Get account balances for all assets."""

    async def execute(self, **kwargs: Any) -> Response:
        try:
            balance = _get_client().get_balance()
            lines = [f"Total equity: ${balance.total_equity_usdt}"]
            for b in balance.balances:
                lines.append(f"  {b.asset}: available={b.available}  locked={b.locked}  total={b.total}")
            return Response(message="\n".join(lines), break_loop=False)
        except AgentExchangeError as exc:
            return Response(message=f"AgentExchange error: {exc}", break_loop=False)


class PlaceOrder(Tool):
    """Place a market, limit, stop_loss, or take_profit order.

    Args:
        symbol: Trading pair, e.g. BTCUSDT
        side: buy or sell
        order_type: market | limit | stop_loss | take_profit
        quantity: Decimal string, e.g. "0.01"
        price: Required for limit orders (decimal string)
        trigger_price: Required for stop_loss / take_profit (decimal string)
    """

    async def execute(
        self,
        symbol: str = "",
        side: str = "",
        order_type: str = "market",
        quantity: str = "0",
        price: str = "",
        trigger_price: str = "",
        **kwargs: Any,
    ) -> Response:
        try:
            extra: dict[str, Any] = {}
            if price:
                extra["price"] = Decimal(price)
            if trigger_price:
                extra["trigger_price"] = Decimal(trigger_price)

            order = _get_client().place_order(
                symbol=symbol.upper(),
                side=side.lower(),
                order_type=order_type.lower(),
                quantity=Decimal(quantity),
                **extra,
            )
            msg = (
                f"Order {order.order_id} → {order.status}\n"
                f"  Executed price: {order.executed_price or 'pending'}\n"
                f"  Slippage: {order.slippage_pct or 'N/A'}%\n"
                f"  Fee: {order.fee or 'N/A'}"
            )
            return Response(message=msg, break_loop=False)

        except InsufficientBalanceError:
            return Response(
                message="Insufficient balance. Call get_balance to check available funds and reduce quantity.",
                break_loop=False,
            )
        except RateLimitError as exc:
            wait = getattr(exc, "retry_after", 60)
            return Response(
                message=f"Rate limit hit. Wait {wait} seconds before retrying.",
                break_loop=False,
            )
        except DailyLossLimitError:
            return Response(
                message="Daily loss limit reached. No new orders until 00:00 UTC. You can still read data.",
                break_loop=False,
            )
        except AgentExchangeError as exc:
            return Response(message=f"Order failed: {exc}", break_loop=False)


class GetPortfolio(Tool):
    """Get full portfolio summary including total equity, PnL, and ROI."""

    async def execute(self, **kwargs: Any) -> Response:
        try:
            pf = _get_client().get_portfolio()
            msg = (
                f"Portfolio summary:\n"
                f"  Total equity:    ${pf.total_equity}\n"
                f"  Available cash:  ${pf.available_cash}\n"
                f"  Position value:  ${pf.total_position_value}\n"
                f"  Unrealized PnL:  ${pf.unrealized_pnl}\n"
                f"  Realized PnL:    ${pf.realized_pnl}\n"
                f"  ROI:             {pf.roi_pct}%"
            )
            return Response(message=msg, break_loop=False)
        except AgentExchangeError as exc:
            return Response(message=f"AgentExchange error: {exc}", break_loop=False)


class GetPerformance(Tool):
    """Get performance metrics: Sharpe ratio, win rate, max drawdown.

    Args:
        period: 1d | 7d | 30d | all (default: all)
    """

    async def execute(self, period: str = "all", **kwargs: Any) -> Response:
        try:
            perf = _get_client().get_performance(period=period)
            msg = (
                f"Performance ({period}):\n"
                f"  Sharpe ratio:    {perf.sharpe_ratio}\n"
                f"  Win rate:        {perf.win_rate}%\n"
                f"  Max drawdown:    {perf.max_drawdown_pct}%\n"
                f"  Total trades:    {perf.total_trades}\n"
                f"  Profit factor:   {perf.profit_factor}"
            )
            return Response(message=msg, break_loop=False)
        except AgentExchangeError as exc:
            return Response(message=f"AgentExchange error: {exc}", break_loop=False)


class GetPositions(Tool):
    """Get all currently open positions."""

    async def execute(self, **kwargs: Any) -> Response:
        try:
            result = _get_client().get_positions()
            if not result.positions:
                return Response(message="No open positions.", break_loop=False)
            lines = ["Open positions:"]
            for pos in result.positions:
                lines.append(
                    f"  {pos.symbol}: qty={pos.quantity}  entry=${pos.avg_entry_price}"
                    f"  current=${pos.current_price}  unrealized_pnl=${pos.unrealized_pnl} ({pos.unrealized_pnl_pct}%)"
                )
            return Response(message="\n".join(lines), break_loop=False)
        except AgentExchangeError as exc:
            return Response(message=f"AgentExchange error: {exc}", break_loop=False)


class CancelOrder(Tool):
    """Cancel a pending order by order_id.

    Args:
        order_id: UUID of the order to cancel
    """

    async def execute(self, order_id: str = "", **kwargs: Any) -> Response:
        try:
            result = _get_client().cancel_order(order_id)
            return Response(
                message=f"Order {order_id} cancelled. Unlocked funds: ${result.unlocked_amount}",
                break_loop=False,
            )
        except AgentExchangeError as exc:
            return Response(message=f"Cancel failed: {exc}", break_loop=False)


class ResetAccount(Tool):
    """Reset account to a fresh session with a new starting balance.

    Args:
        starting_balance: USDT amount as decimal string (default "10000.00")
    """

    async def execute(self, starting_balance: str = "10000.00", **kwargs: Any) -> Response:
        try:
            session = _get_client().reset_account(starting_balance=Decimal(starting_balance))
            return Response(
                message=(
                    f"Account reset. New session: {session.session_id}\n"
                    f"Starting balance: ${session.starting_balance}\n"
                    f"Started at: {session.started_at.isoformat()}"
                ),
                break_loop=False,
            )
        except AgentExchangeError as exc:
            return Response(message=f"Reset failed: {exc}", break_loop=False)
```

### Register the tools in Agent Zero's config

In `initialize.py` (or wherever Agent Zero loads its tool list), add the new tools:

```python
from python.tools.agentexchange_tools import (
    GetPrice,
    GetBalance,
    PlaceOrder,
    GetPortfolio,
    GetPerformance,
    GetPositions,
    CancelOrder,
    ResetAccount,
)

# Add to the agent's tool list
tools = [
    # ... existing Agent Zero tools ...
    GetPrice(agent, name="get_price", args={"symbol": "str"}, message=""),
    GetBalance(agent, name="get_balance", args={}, message=""),
    PlaceOrder(
        agent,
        name="place_order",
        args={
            "symbol": "str",
            "side": "str",
            "order_type": "str",
            "quantity": "str",
            "price": "str",
            "trigger_price": "str",
        },
        message="",
    ),
    GetPortfolio(agent, name="get_portfolio", args={}, message=""),
    GetPerformance(agent, name="get_performance", args={"period": "str"}, message=""),
    GetPositions(agent, name="get_positions", args={}, message=""),
    CancelOrder(agent, name="cancel_order", args={"order_id": "str"}, message=""),
    ResetAccount(agent, name="reset_account", args={"starting_balance": "str"}, message=""),
]
```

---

## Step 6 — Add WebSocket Streaming (Real-Time Prices)

For agents that need to react to live price changes rather than polling, run the AgentExchange WebSocket client in a background thread and expose the latest prices as a fast in-memory lookup:

```python
"""Background WebSocket price feed for Agent Zero tools."""

import os
import threading
from agentexchange import AgentExchangeWS

# Shared price state — written by WS thread, read by tools
latest_prices: dict[str, str] = {}
latest_order_updates: list[dict] = []

ws = AgentExchangeWS(
    api_key=os.environ["AGENTEXCHANGE_API_KEY"],
    base_url=os.environ.get("AGENTEXCHANGE_WS_URL", "ws://localhost:8000"),
)


@ws.on_ticker("BTCUSDT")
def on_btc(msg: dict) -> None:
    latest_prices["BTCUSDT"] = msg["data"]["price"]


@ws.on_ticker("ETHUSDT")
def on_eth(msg: dict) -> None:
    latest_prices["ETHUSDT"] = msg["data"]["price"]


@ws.on_order_update()
def on_order(msg: dict) -> None:
    data = msg["data"]
    latest_order_updates.append(data)
    # Keep only the last 100 updates
    if len(latest_order_updates) > 100:
        latest_order_updates.pop(0)


def start_ws_feed() -> None:
    """Start the WebSocket feed in a daemon thread."""
    thread = threading.Thread(target=ws.run_forever, daemon=True)
    thread.start()
```

Add a `GetStreamedPrice` tool that reads from the shared cache:

```python
from python.tools.agentexchange_ws import latest_prices, start_ws_feed

# Call once at startup
start_ws_feed()

class GetStreamedPrice(Tool):
    """Get the most recently streamed price (faster than HTTP polling).

    Args:
        symbol: Trading pair, e.g. BTCUSDT
    """

    async def execute(self, symbol: str = "", **kwargs: Any) -> Response:
        sym = symbol.upper()
        price = latest_prices.get(sym)
        if not price:
            return Response(
                message=f"No streamed price yet for {sym}. Subscribe first or use get_price instead.",
                break_loop=False,
            )
        return Response(
            message=f"{sym}: ${price} (WebSocket, real-time)",
            break_loop=False,
        )
```

---

## Configuration Reference

### Recommended system prompt additions (`prompts/default/agent.system.md`)

```markdown
## AgentExchange Simulated Trading

You have access to AgentExchange — a simulated cryptocurrency exchange backed by real-time
Binance market data. All funds are virtual. Use the following credentials for every request:

- Base URL: http://localhost:8000/api/v1
- Auth header: X-API-Key: <injected at runtime>

### Rules before placing any order
1. Call `get_balance` to confirm you have enough available USDT.
2. Check `get_price` for the current price; do not rely on a price from more than 30 seconds ago.
3. After filling a market order, immediately set a stop-loss with `place_order` (type: stop_loss).
4. Never risk more than 10% of total equity on a single trade.
5. All quantity and price values must be decimal strings: `"0.01"`, not `0.01`.

### When things go wrong
- `INSUFFICIENT_BALANCE` → call `get_balance`, reduce quantity, retry.
- `RATE_LIMIT_EXCEEDED` → wait for the Unix timestamp in `X-RateLimit-Reset`, then retry.
- `DAILY_LOSS_LIMIT` → stop trading, report status, wait until 00:00 UTC.
- `INVALID_SYMBOL` → call `GET /market/pairs` to find the correct symbol.
- `PRICE_NOT_AVAILABLE` → wait 3 seconds and retry; the ingestion service may be warming up.
```

### Required environment variables

| Variable | Description |
|---|---|
| `AGENTEXCHANGE_API_KEY` | Your `ak_live_...` key from registration |
| `AGENTEXCHANGE_API_SECRET` | Your `sk_live_...` secret (needed only by the SDK) |
| `AGENTEXCHANGE_BASE_URL` | REST base URL, e.g. `http://localhost:8000` |
| `AGENTEXCHANGE_WS_URL` | WebSocket base URL, e.g. `ws://localhost:8000` |

---

## Error Handling

The skill file includes a complete error code table. When your Agent Zero agent encounters an API error, it should follow these patterns:

| Error Code | Recommended Agent Behaviour |
|---|---|
| `INSUFFICIENT_BALANCE` | Call `get_balance`, reduce order quantity, retry |
| `RATE_LIMIT_EXCEEDED` | Read `X-RateLimit-Reset`, wait until that Unix timestamp, retry |
| `DAILY_LOSS_LIMIT` | Stop placing orders, report status, wait until 00:00 UTC |
| `INVALID_SYMBOL` | Call `GET /market/pairs` to find the correct symbol, retry |
| `INVALID_QUANTITY` | Call `GET /market/pairs` to check `min_qty` and `step_size`, recalculate |
| `ORDER_REJECTED` | Check position limits and open order count before retrying |
| `PRICE_NOT_AVAILABLE` | Retry after 2–3 seconds; the ingestion service may be warming up |
| `INTERNAL_ERROR` | Retry with exponential back-off: 1s → 2s → 4s → 8s → max 60s |

If you are using the SDK tool wrappers from Step 5, these errors surface as typed Python exceptions (`RateLimitError`, `InsufficientBalanceError`, etc.) that are caught inside each tool function before they ever reach the LLM context.

---

## Troubleshooting

**Agent says "I cannot access the API" or constructs wrong URLs**
- Verify the platform is running: `curl http://localhost:8000/health`
- Confirm the `api_key` is present in the injected system context
- Check that `AGENTEXCHANGE_BASE_URL` does not have a trailing slash

**Skill file not being read by Agent Zero**
- Confirm the file extension is `.md`
- Restart Agent Zero after adding the file — it builds skill context at startup
- Check Agent Zero logs for skill loading errors

**`PRICE_NOT_AVAILABLE` on startup**
- The Binance WebSocket ingestion service needs ~30 seconds after a cold start to stream initial prices for all pairs. Wait and retry.

**Agent constructs malformed request bodies (bare numbers instead of decimal strings)**
- Add an explicit reminder in the system prompt: *"All quantity and price fields must be decimal strings in quotes, e.g. `\"quantity\": \"0.01\"`, never bare numbers."*
- Use the SDK tool wrappers from Step 5 — they handle serialisation automatically.

**Rate limit hit during price scans**
- `GET /market/prices` returns all 600+ prices in a single call. Use it instead of looping over `/market/price/{symbol}`.

**WebSocket disconnects**
- `AgentExchangeWS.run_forever()` has a built-in reconnect loop with exponential back-off. If you bypass it with raw `websockets`, implement the same: 1s → 2s → 4s → … → 60s max, and respond to `{"type":"ping"}` with `{"type":"pong"}` within 10 seconds.

---

## Next Steps

- **OpenClaw integration** → see [`docs/framework_guides/openclaw.md`](openclaw.md)
- **LangChain integration** → see [`docs/framework_guides/langchain.md`](langchain.md)
- **CrewAI integration** → see [`docs/framework_guides/crewai.md`](crewai.md)
- **Full API reference** → [`docs/api_reference.md`](../api_reference.md)
- **5-minute quickstart** → [`docs/quickstart.md`](../quickstart.md)
- **LLM skill file** → [`docs/skill.md`](../skill.md)
