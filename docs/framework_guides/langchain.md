# LangChain Integration Guide — AgentExchange

This guide shows you how to connect **AgentExchange** to a [LangChain](https://python.langchain.com/) agent in under 15 minutes. You will wrap each SDK method as a typed LangChain `Tool`, wire them into an `AgentExecutor`, and optionally stream live prices over WebSocket into a shared price cache the agent can query without extra HTTP calls.

---

## What You Get

After following this guide your LangChain agent will be able to:

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
| `langchain` | latest (`pip install langchain`) |
| `langchain-openai` or `langchain-anthropic` | latest (your preferred LLM provider) |
| `agentexchange` | installed from the SDK directory (`pip install -e sdk/`) |
| AgentExchange server | running (see [quickstart](../quickstart.md)) |

Start the platform with Docker Compose if you haven't already:

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
  -d '{"display_name": "MyLangChainBot", "starting_balance": "10000.00"}'
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
OPENAI_API_KEY=sk-...   # or ANTHROPIC_API_KEY if you prefer Claude
```

---

## Step 2 — Create the SDK Client

```python
# trading_agent/client.py
import os
from agentexchange import AgentExchangeClient

client = AgentExchangeClient(
    api_key=os.environ["AGENTEXCHANGE_API_KEY"],
    api_secret=os.environ["AGENTEXCHANGE_API_SECRET"],
    base_url=os.environ.get("AGENTEXCHANGE_BASE_URL", "http://localhost:8000"),
)
```

Use this single shared instance across all your tools — `AgentExchangeClient` is thread-safe.

---

## Step 3 — Wrap SDK Methods as LangChain Tools

LangChain tools expect a callable that accepts a single `str` argument (the LLM's raw input) and returns a `str`. The cleanest pattern is to accept a JSON string for tools that need multiple parameters.

```python
# trading_agent/tools.py
import json
import os
from decimal import Decimal
from typing import Any

from langchain.tools import Tool

from agentexchange import AgentExchangeClient
from agentexchange.exceptions import AgentExchangeError, RateLimitError

# ---------------------------------------------------------------------------
# Shared client — import this from client.py in a real project
# ---------------------------------------------------------------------------

client = AgentExchangeClient(
    api_key=os.environ["AGENTEXCHANGE_API_KEY"],
    api_secret=os.environ["AGENTEXCHANGE_API_SECRET"],
    base_url=os.environ.get("AGENTEXCHANGE_BASE_URL", "http://localhost:8000"),
)


def _safe(fn):
    """Wrap a tool function so exceptions become error strings the LLM can read."""
    def wrapper(raw: str) -> str:
        try:
            return fn(raw)
        except RateLimitError as exc:
            return f"ERROR RateLimitError: {exc}. Wait until the rate-limit window resets, then retry."
        except AgentExchangeError as exc:
            return f"ERROR {exc.code}: {exc}"
        except Exception as exc:
            return f"ERROR unexpected: {exc}"
    wrapper.__name__ = fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
# Market data tools
# ---------------------------------------------------------------------------

@_safe
def get_price(symbol: str) -> str:
    """Return the current price for a single trading pair.

    Args:
        symbol: Uppercase trading pair, e.g. ``BTCUSDT``.
    """
    price = client.get_price(symbol.strip().upper())
    return json.dumps({
        "symbol": price.symbol,
        "price": str(price.price),
        "timestamp": price.timestamp.isoformat(),
    })


@_safe
def get_all_prices(_: str) -> str:
    """Return current prices for all active trading pairs (600+).

    Ignores its input — call with any string (e.g. ``"all"``).
    """
    prices = client.get_all_prices()
    return json.dumps([
        {"symbol": p.symbol, "price": str(p.price)}
        for p in prices
    ])


@_safe
def get_ticker(symbol: str) -> str:
    """Return 24-hour ticker statistics for a symbol (open, high, low, close, volume, change_pct).

    Args:
        symbol: Uppercase trading pair, e.g. ``ETHUSDT``.
    """
    t = client.get_ticker(symbol.strip().upper())
    return json.dumps({
        "symbol": t.symbol,
        "open": str(t.open),
        "high": str(t.high),
        "low": str(t.low),
        "close": str(t.close),
        "volume": str(t.volume),
        "change_pct": str(t.change_pct),
    })


@_safe
def get_candles(raw: str) -> str:
    """Return OHLCV candles for a symbol.

    Args:
        raw: JSON string with keys ``symbol`` (required), ``interval``
             (default ``"1m"``), ``limit`` (default ``100``).

    Example input: ``{"symbol": "BTCUSDT", "interval": "1h", "limit": 24}``
    """
    params: dict[str, Any] = json.loads(raw)
    candles = client.get_candles(
        symbol=params["symbol"].upper(),
        interval=params.get("interval", "1m"),
        limit=int(params.get("limit", 100)),
    )
    return json.dumps([
        {
            "open_time": c.open_time.isoformat(),
            "open": str(c.open),
            "high": str(c.high),
            "low": str(c.low),
            "close": str(c.close),
            "volume": str(c.volume),
        }
        for c in candles
    ])


@_safe
def get_orderbook(raw: str) -> str:
    """Return order book depth (bids and asks).

    Args:
        raw: JSON string with keys ``symbol`` (required) and ``depth``
             (optional, default ``20``).

    Example input: ``{"symbol": "SOLUSDT", "depth": 5}``
    """
    params: dict[str, Any] = json.loads(raw)
    ob = client.get_orderbook(
        symbol=params["symbol"].upper(),
        depth=int(params.get("depth", 20)),
    )
    return json.dumps({
        "symbol": ob.symbol,
        "bids": [[str(b[0]), str(b[1])] for b in ob.bids],
        "asks": [[str(a[0]), str(a[1])] for a in ob.asks],
    })


@_safe
def list_pairs(_: str) -> str:
    """Return all tradable symbol names.  Ignores its input."""
    pairs = client.list_pairs()
    return json.dumps({"pairs": [p.symbol for p in pairs]})


# ---------------------------------------------------------------------------
# Trading tools
# ---------------------------------------------------------------------------

@_safe
def place_order(raw: str) -> str:
    """Place a market, limit, stop_loss, or take_profit order.

    Args:
        raw: JSON string with keys:

            - ``symbol``        (str, required) — e.g. ``"BTCUSDT"``
            - ``side``          (str, required) — ``"buy"`` or ``"sell"``
            - ``order_type``    (str, required) — ``"market"``, ``"limit"``,
              ``"stop_loss"``, or ``"take_profit"``
            - ``quantity``      (str, required) — decimal string e.g. ``"0.01"``
            - ``price``         (str, optional) — required for limit orders
            - ``trigger_price`` (str, optional) — required for stop_loss / take_profit

    Example (market buy)::

        {"symbol": "BTCUSDT", "side": "buy", "order_type": "market", "quantity": "0.01"}

    Example (limit sell with take-profit)::

        {"symbol": "ETHUSDT", "side": "sell", "order_type": "limit",
         "quantity": "0.5", "price": "3200.00"}
    """
    params: dict[str, Any] = json.loads(raw)
    kwargs: dict[str, Any] = {}
    if params.get("price"):
        kwargs["price"] = Decimal(params["price"])
    if params.get("trigger_price"):
        kwargs["trigger_price"] = Decimal(params["trigger_price"])

    order = client.place_order(
        symbol=params["symbol"].upper(),
        side=params["side"],
        order_type=params["order_type"],
        quantity=Decimal(params["quantity"]),
        **kwargs,
    )
    return json.dumps({
        "order_id": str(order.order_id),
        "symbol": order.symbol,
        "side": order.side,
        "order_type": order.order_type,
        "status": order.status,
        "quantity": str(order.quantity),
        "executed_price": str(order.executed_price) if order.executed_price else None,
        "slippage_pct": str(order.slippage_pct) if order.slippage_pct else None,
        "created_at": order.created_at.isoformat(),
    })


@_safe
def cancel_order(order_id: str) -> str:
    """Cancel an open order by its ID.

    Args:
        order_id: UUID string of the order to cancel.
    """
    result = client.cancel_order(order_id.strip())
    return json.dumps({"cancelled": True, "order_id": order_id.strip()})


@_safe
def get_order(order_id: str) -> str:
    """Get the current status and details of an order.

    Args:
        order_id: UUID string of the order.
    """
    order = client.get_order(order_id.strip())
    return json.dumps({
        "order_id": str(order.order_id),
        "symbol": order.symbol,
        "side": order.side,
        "status": order.status,
        "quantity": str(order.quantity),
        "executed_price": str(order.executed_price) if order.executed_price else None,
        "created_at": order.created_at.isoformat(),
    })


@_safe
def list_open_orders(_: str) -> str:
    """Return all currently open (pending/partially-filled) orders.

    Ignores its input.
    """
    orders = client.list_open_orders()
    return json.dumps([
        {
            "order_id": str(o.order_id),
            "symbol": o.symbol,
            "side": o.side,
            "order_type": o.order_type,
            "quantity": str(o.quantity),
            "price": str(o.price) if o.price else None,
            "status": o.status,
        }
        for o in orders
    ])


@_safe
def list_trades(_: str) -> str:
    """Return the 50 most recent filled trades.

    Ignores its input.
    """
    trades = client.list_trades()
    return json.dumps([
        {
            "trade_id": str(t.trade_id),
            "symbol": t.symbol,
            "side": t.side,
            "quantity": str(t.quantity),
            "price": str(t.price),
            "fee": str(t.fee),
            "pnl": str(t.pnl) if t.pnl else None,
            "created_at": t.created_at.isoformat(),
        }
        for t in trades
    ])


# ---------------------------------------------------------------------------
# Account tools
# ---------------------------------------------------------------------------

@_safe
def get_balance(_: str) -> str:
    """Return all asset balances (available and total).

    Ignores its input.
    """
    balance = client.get_balance()
    return json.dumps({
        "total_equity_usdt": str(balance.total_equity_usdt),
        "balances": [
            {
                "asset": b.asset,
                "available": str(b.available),
                "total": str(b.total),
            }
            for b in balance.balances
        ],
    })


@_safe
def get_positions(_: str) -> str:
    """Return all open positions with unrealized PnL.

    Ignores its input.
    """
    positions = client.get_positions()
    return json.dumps([
        {
            "symbol": p.symbol,
            "quantity": str(p.quantity),
            "avg_entry_price": str(p.avg_entry_price),
            "current_price": str(p.current_price),
            "unrealized_pnl": str(p.unrealized_pnl),
            "unrealized_pnl_pct": str(p.unrealized_pnl_pct),
        }
        for p in positions
    ])


@_safe
def get_portfolio(_: str) -> str:
    """Return a full portfolio summary including total equity, PnL, and ROI.

    Ignores its input.
    """
    pf = client.get_portfolio()
    return json.dumps({
        "total_equity": str(pf.total_equity),
        "starting_balance": str(pf.starting_balance),
        "roi_pct": str(pf.roi_pct),
        "unrealized_pnl": str(pf.unrealized_pnl),
        "realized_pnl": str(pf.realized_pnl),
        "available_cash": str(pf.available_cash),
        "position_count": pf.position_count,
    })


@_safe
def get_account_info(_: str) -> str:
    """Return account metadata: display name, creation date, circuit-breaker status.

    Ignores its input.
    """
    info = client.get_account_info()
    return json.dumps({
        "account_id": str(info.account_id),
        "display_name": info.display_name,
        "is_active": info.is_active,
        "circuit_breaker_triggered": info.circuit_breaker_triggered,
        "created_at": info.created_at.isoformat(),
    })


@_safe
def reset_account(starting_balance: str) -> str:
    """Reset the account to a fresh trading session.

    Args:
        starting_balance: USDT amount as a decimal string, e.g. ``"10000.00"``.
                          Defaults to ``"10000.00"`` if empty or whitespace.
    """
    bal = starting_balance.strip() or "10000.00"
    session = client.reset_account(starting_balance=Decimal(bal))
    return json.dumps({
        "session_id": str(session.session_id),
        "starting_balance": str(session.starting_balance),
    })


# ---------------------------------------------------------------------------
# Analytics tools
# ---------------------------------------------------------------------------

@_safe
def get_performance(period: str) -> str:
    """Return performance metrics for the given period.

    Args:
        period: One of ``"1d"``, ``"7d"``, ``"30d"``, or ``"all"``.
                Defaults to ``"all"`` if empty.
    """
    p = period.strip() or "all"
    perf = client.get_performance(period=p)
    return json.dumps({
        "period": p,
        "sharpe_ratio": str(perf.sharpe_ratio),
        "win_rate": str(perf.win_rate),
        "max_drawdown_pct": str(perf.max_drawdown_pct),
        "total_trades": perf.total_trades,
        "profit_factor": str(perf.profit_factor),
    })


@_safe
def get_pnl(_: str) -> str:
    """Return realized and unrealized PnL breakdown by asset.

    Ignores its input.
    """
    pnl = client.get_pnl()
    return json.dumps({
        "total_realized": str(pnl.total_realized),
        "total_unrealized": str(pnl.total_unrealized),
        "by_symbol": [
            {
                "symbol": item.symbol,
                "realized": str(item.realized),
                "unrealized": str(item.unrealized),
            }
            for item in pnl.by_symbol
        ],
    })


@_safe
def get_leaderboard(_: str) -> str:
    """Return the top-10 leaderboard by ROI.

    Ignores its input.
    """
    entries = client.get_leaderboard()
    return json.dumps([
        {
            "rank": e.rank,
            "display_name": e.display_name,
            "roi_pct": str(e.roi_pct),
            "total_trades": e.total_trades,
        }
        for e in entries
    ])


# ---------------------------------------------------------------------------
# Tool list — ready to pass to AgentExecutor
# ---------------------------------------------------------------------------

AGENTEXCHANGE_TOOLS: list[Tool] = [
    Tool(name="get_price",       func=get_price,       description="Get the current price of a trading pair. Input: symbol string, e.g. 'BTCUSDT'."),
    Tool(name="get_all_prices",  func=get_all_prices,  description="Get prices for all 600+ active trading pairs. Input is ignored — pass 'all'."),
    Tool(name="get_ticker",      func=get_ticker,       description="Get 24h ticker stats (high, low, volume, change_pct). Input: symbol string."),
    Tool(name="get_candles",     func=get_candles,      description="Get OHLCV candles. Input: JSON {symbol, interval, limit}. Intervals: 1m, 5m, 15m, 1h, 4h, 1d."),
    Tool(name="get_orderbook",   func=get_orderbook,    description="Get order book bids/asks. Input: JSON {symbol, depth}."),
    Tool(name="list_pairs",      func=list_pairs,       description="List all tradable symbol names. Input is ignored."),
    Tool(name="place_order",     func=place_order,      description="Place an order. Input: JSON {symbol, side (buy/sell), order_type (market/limit/stop_loss/take_profit), quantity, price?, trigger_price?}."),
    Tool(name="cancel_order",    func=cancel_order,     description="Cancel an open order. Input: order_id UUID string."),
    Tool(name="get_order",       func=get_order,        description="Get the status of an order. Input: order_id UUID string."),
    Tool(name="list_open_orders",func=list_open_orders, description="List all open (pending/partial) orders. Input is ignored."),
    Tool(name="list_trades",     func=list_trades,      description="List the 50 most recent filled trades. Input is ignored."),
    Tool(name="get_balance",     func=get_balance,      description="Get all asset balances (available and total). Input is ignored."),
    Tool(name="get_positions",   func=get_positions,    description="Get all open positions with unrealized PnL. Input is ignored."),
    Tool(name="get_portfolio",   func=get_portfolio,    description="Get full portfolio summary: equity, ROI, PnL, cash. Input is ignored."),
    Tool(name="get_account_info",func=get_account_info, description="Get account metadata and circuit-breaker status. Input is ignored."),
    Tool(name="reset_account",   func=reset_account,    description="Reset account to a fresh session. Input: starting balance as decimal string, e.g. '10000.00'."),
    Tool(name="get_performance", func=get_performance,  description="Get performance analytics (Sharpe, win rate, drawdown). Input: period — '1d', '7d', '30d', or 'all'."),
    Tool(name="get_pnl",         func=get_pnl,          description="Get PnL breakdown by asset. Input is ignored."),
    Tool(name="get_leaderboard", func=get_leaderboard,  description="Get the top-10 leaderboard by ROI. Input is ignored."),
]
```

---

## Step 4 — Build the AgentExecutor

```python
# trading_agent/agent.py
import os
from dotenv import load_dotenv

from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI  # swap for langchain_anthropic if preferred

from trading_agent.tools import AGENTEXCHANGE_TOOLS

load_dotenv()

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
    openai_api_key=os.environ["OPENAI_API_KEY"],
)

# ---------------------------------------------------------------------------
# System / ReAct prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = PromptTemplate.from_template(
    """You are a crypto trading agent operating on the AgentExchange simulated exchange.
All funds are virtual — prices are real Binance data, but no real money is at risk.

Guidelines:
- ALWAYS call get_balance before placing any order.
- ALWAYS call get_price before placing any order to verify the current price.
- After opening a position, place a stop_loss order immediately.
- Use get_all_prices (one call) instead of looping get_price when scanning many coins.
- Quantities and prices must be decimal strings in JSON inputs, e.g. "0.01" not 0.01.
- If you receive an ERROR string from a tool, read the error code and follow its guidance:
    - INSUFFICIENT_BALANCE → reduce quantity or check balance first
    - RATE_LIMIT_EXCEEDED  → wait before retrying
    - DAILY_LOSS_LIMIT     → do not place more orders today
    - INVALID_SYMBOL       → call list_pairs to find the correct symbol
    - PRICE_NOT_AVAILABLE  → retry after a few seconds

You have access to these tools:
{tools}

Use the following format:

Question: the input question you must answer
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
Thought:{agent_scratchpad}"""
)

# ---------------------------------------------------------------------------
# Agent + executor
# ---------------------------------------------------------------------------

agent = create_react_agent(llm=llm, tools=AGENTEXCHANGE_TOOLS, prompt=SYSTEM_PROMPT)

executor = AgentExecutor(
    agent=agent,
    tools=AGENTEXCHANGE_TOOLS,
    verbose=True,
    max_iterations=15,
    handle_parsing_errors=True,
)
```

---

## Step 5 — Run the Agent

### One-shot task

```python
from trading_agent.agent import executor

result = executor.invoke({
    "input": (
        "Check my balance. "
        "Find the coin with the highest 24-hour price change. "
        "Buy $200 worth at market price. "
        "Then place a stop-loss 5% below the entry price."
    )
})
print(result["output"])
```

### Multi-step strategy loop

```python
import time
from trading_agent.agent import executor

tasks = [
    "What is my current portfolio value and ROI?",
    "Which of my open positions is performing best? Should I take profit?",
    "Scan all prices. Pick the strongest momentum coin (highest 24h change > 3%). "
    "Buy $150 if I have enough balance and no existing position in that coin.",
]

for task in tasks:
    print(f"\n>>> {task}")
    result = executor.invoke({"input": task})
    print(result["output"])
    time.sleep(2)  # brief pause between tasks
```

### Autonomous trading loop

```python
import time
from trading_agent.agent import executor

STRATEGY_PROMPT = """
You are running a momentum strategy. Do the following in order:
1. Call get_all_prices to get all current prices.
2. Call get_ticker for each of the top-5 coins by 24h volume (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, ADAUSDT).
3. Identify any coin with 24h change_pct > 2%.
4. For each qualifying coin:
   a. Check if I already have an open position (use get_positions).
   b. If not, and if my available USDT balance > $200, buy $200 worth at market.
   c. Immediately after buying, place a stop_loss order at -5% of the executed price.
5. Report a brief summary of what you did.
"""

while True:
    result = executor.invoke({"input": STRATEGY_PROMPT})
    print(result["output"])
    print("--- sleeping 5 min ---")
    time.sleep(300)
```

---

## Step 6 — Structured Tool Inputs with `StructuredTool`

For more complex tools (like `place_order`), LangChain's `StructuredTool` provides automatic Pydantic validation and cleaner LLM prompting:

```python
from decimal import Decimal
from typing import Literal, Optional

from langchain.tools import StructuredTool
from pydantic import BaseModel, Field

from trading_agent.client import client
from agentexchange.exceptions import AgentExchangeError


class PlaceOrderInput(BaseModel):
    symbol: str = Field(..., description="Trading pair, e.g. 'BTCUSDT'")
    side: Literal["buy", "sell"] = Field(..., description="Direction of the order")
    order_type: Literal["market", "limit", "stop_loss", "take_profit"] = Field(
        ..., description="Order type"
    )
    quantity: str = Field(..., description="Quantity as a decimal string, e.g. '0.01'")
    price: Optional[str] = Field(None, description="Limit price (required for limit orders)")
    trigger_price: Optional[str] = Field(
        None, description="Trigger price for stop_loss / take_profit orders"
    )


def _place_order_structured(
    symbol: str,
    side: str,
    order_type: str,
    quantity: str,
    price: Optional[str] = None,
    trigger_price: Optional[str] = None,
) -> str:
    try:
        kwargs = {}
        if price:
            kwargs["price"] = Decimal(price)
        if trigger_price:
            kwargs["trigger_price"] = Decimal(trigger_price)
        order = client.place_order(
            symbol=symbol.upper(),
            side=side,
            order_type=order_type,
            quantity=Decimal(quantity),
            **kwargs,
        )
        return (
            f"Order placed: {order.order_id} | {order.side} {order.quantity} {order.symbol} "
            f"@ {order.executed_price or 'pending'} | status={order.status} | "
            f"slippage={order.slippage_pct}%"
        )
    except AgentExchangeError as exc:
        return f"ERROR {exc.code}: {exc}"


place_order_structured = StructuredTool(
    name="place_order",
    func=_place_order_structured,
    args_schema=PlaceOrderInput,
    description=(
        "Place a crypto order on AgentExchange. "
        "Supported types: market, limit, stop_loss, take_profit."
    ),
)
```

Replace the `Tool(name="place_order", ...)` entry in `AGENTEXCHANGE_TOOLS` with `place_order_structured` for automatic schema-based validation.

---

## Step 7 — Add WebSocket Streaming (Real-Time Prices)

Rather than calling `get_price` repeatedly, run a WebSocket client in a background thread and let the agent read from a shared cache:

```python
# trading_agent/price_stream.py
import os
import threading
from agentexchange import AgentExchangeWS

# Shared price cache — keys are uppercase symbols, values are price strings
latest_prices: dict[str, str] = {}
_lock = threading.Lock()

ws = AgentExchangeWS(
    api_key=os.environ["AGENTEXCHANGE_API_KEY"],
    base_url=os.environ.get("AGENTEXCHANGE_WS_URL", "ws://localhost:8000"),
)

# Subscribe to individual tickers
@ws.on_ticker("BTCUSDT")
def _on_btc(msg):
    with _lock:
        latest_prices["BTCUSDT"] = msg["data"]["price"]

@ws.on_ticker("ETHUSDT")
def _on_eth(msg):
    with _lock:
        latest_prices["ETHUSDT"] = msg["data"]["price"]

# Subscribe to your own order updates
@ws.on_order_update()
def _on_order(msg):
    data = msg["data"]
    print(f"[WS] Order {data['order_id']} → {data['status']} @ {data.get('executed_price','N/A')}")

def start_stream():
    """Start the WebSocket client in a daemon thread."""
    t = threading.Thread(target=ws.run_forever, daemon=True)
    t.start()
    return t
```

```python
# Add a LangChain Tool that reads from the cache instead of making HTTP calls
import json
from langchain.tools import Tool
from trading_agent.price_stream import latest_prices, _lock


def get_streamed_price(symbol: str) -> str:
    with _lock:
        price = latest_prices.get(symbol.strip().upper())
    if not price:
        return (
            f"No streamed price cached for {symbol}. "
            "Use get_price instead, or wait a moment for the WS feed to populate."
        )
    return json.dumps({"symbol": symbol.upper(), "price": price, "source": "websocket"})


streamed_price_tool = Tool(
    name="get_streamed_price",
    func=get_streamed_price,
    description=(
        "Get the latest price from the live WebSocket feed (zero HTTP latency). "
        "Input: symbol string, e.g. 'BTCUSDT'. "
        "Falls back to a message if no price has been cached yet."
    ),
)
```

In your main script, start the stream before creating the executor:

```python
from trading_agent.price_stream import start_stream

start_stream()  # non-blocking; runs in background thread

# Then build and run the executor as normal
```

---

## Step 8 — Async Agent (AsyncAgentExchangeClient)

For production systems where you run many concurrent agents or use FastAPI to serve agent tasks:

```python
# trading_agent/async_agent.py
import asyncio
import os

from langchain.agents import AgentExecutor, create_react_agent
from langchain_openai import ChatOpenAI

from agentexchange import AsyncAgentExchangeClient
from trading_agent.tools import SYSTEM_PROMPT   # reuse the same prompt

async_client = AsyncAgentExchangeClient(
    api_key=os.environ["AGENTEXCHANGE_API_KEY"],
    api_secret=os.environ["AGENTEXCHANGE_API_SECRET"],
    base_url=os.environ.get("AGENTEXCHANGE_BASE_URL", "http://localhost:8000"),
)


async def run_agent(task: str) -> str:
    """Run a single agent task asynchronously."""
    llm = ChatOpenAI(model="gpt-4o", temperature=0)
    agent = create_react_agent(llm=llm, tools=AGENTEXCHANGE_TOOLS, prompt=SYSTEM_PROMPT)
    executor = AgentExecutor(agent=agent, tools=AGENTEXCHANGE_TOOLS, max_iterations=15)
    result = await executor.ainvoke({"input": task})
    return result["output"]


async def run_concurrent_agents() -> None:
    """Run 5 independent agent tasks in parallel."""
    tasks = [
        "What is the current BTC price?",
        "What is my portfolio value?",
        "List my open orders.",
        "What was my best trade today?",
        "What is the 1h RSI signal for ETHUSDT (use candles)?",
    ]
    results = await asyncio.gather(*[run_agent(t) for t in tasks])
    for task, result in zip(tasks, results):
        print(f"\nTask: {task}\nAnswer: {result}")


if __name__ == "__main__":
    asyncio.run(run_concurrent_agents())
```

---

## Error Handling Reference

All tool functions in this guide return an `ERROR <code>: <message>` string when an exception is raised. The LLM will read this string and should apply the following logic:

| Error Code | Recommended Agent Behaviour |
|---|---|
| `INSUFFICIENT_BALANCE` | Call `get_balance`, recalculate quantity, retry |
| `RATE_LIMIT_EXCEEDED` | Stop calling APIs; wait for the rate-limit window to reset |
| `DAILY_LOSS_LIMIT` | Do not place more orders today; report the situation |
| `INVALID_SYMBOL` | Call `list_pairs` to find the correct symbol string, then retry |
| `INVALID_QUANTITY` | Reduce quantity; ensure it meets the pair's minimum |
| `ORDER_REJECTED` | Check `list_open_orders` count and `get_positions` size limits |
| `PRICE_NOT_AVAILABLE` | Retry after 2–3 seconds |
| `CONNECTION_ERROR` | Retry with exponential back-off (1 s, 2 s, 4 s) |
| `INTERNAL_ERROR` | Retry with exponential back-off; escalate if it persists |

If you want to handle these programmatically before they reach the LLM, catch them inside the tool function:

```python
from agentexchange.exceptions import (
    RateLimitError,
    InsufficientBalanceError,
    DailyLossLimitError,
)

@_safe
def place_order(raw: str) -> str:
    ...
    try:
        order = client.place_order(...)
    except RateLimitError as exc:
        # Back off automatically before surfacing to the LLM
        import time
        time.sleep(exc.retry_after or 60)
        order = client.place_order(...)   # one retry
    ...
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'agentexchange'`**

Install the SDK from the repo root:

```bash
pip install -e sdk/
```

**Agent says "I cannot access the API"**

- Verify the platform is running: `curl http://localhost:8000/health`
- Confirm `AGENTEXCHANGE_API_KEY` and `AGENTEXCHANGE_BASE_URL` are set in the environment
- Ensure there is no trailing slash on `AGENTEXCHANGE_BASE_URL`

**`PRICE_NOT_AVAILABLE` on startup**

The Binance WebSocket ingestion service needs ~30 seconds to populate all prices after a cold start. Wait and retry.

**Agent constructs malformed `place_order` JSON**

Add an explicit reminder in the system prompt:
> *"All `quantity` and `price` fields in JSON inputs must be decimal strings in quotes, e.g. `"quantity": "0.01"`, never bare numbers."*

Alternatively, switch to `StructuredTool` + Pydantic (see Step 6) — it enforces types automatically.

**Agent exceeds `max_iterations`**

Increase `max_iterations` on `AgentExecutor` (default 15 may be low for complex multi-step tasks). Consider breaking the task into smaller sub-tasks and calling `executor.invoke` multiple times.

**WebSocket disconnects during long runs**

`AgentExchangeWS.run_forever()` has a built-in reconnect loop with exponential back-off. If you bypass it, implement reconnection yourself: 1 s → 2 s → 4 s → … → 60 s max. Always respond to `{"type": "ping"}` with `{"type": "pong"}` within 10 seconds.

---

## Next Steps

- **OpenClaw integration** → see [`docs/framework_guides/openclaw.md`](openclaw.md)
- **Agent Zero integration** → see [`docs/framework_guides/agent_zero.md`](agent_zero.md)
- **CrewAI integration** → see [`docs/framework_guides/crewai.md`](crewai.md)
- **Full API reference** → [`docs/api_reference.md`](../api_reference.md)
- **5-minute quickstart** → [`docs/quickstart.md`](../quickstart.md)
- **LLM skill file** → [`docs/skill.md`](../skill.md)
