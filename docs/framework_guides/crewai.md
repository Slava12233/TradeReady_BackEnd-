# CrewAI Integration Guide — AgentExchange

This guide shows you how to connect **AgentExchange** to a [CrewAI](https://docs.crewai.com/) multi-agent system in under 20 minutes. You will wrap each SDK method as a `@tool`-decorated function, wire them into a `Crew` with specialized `Agent` roles, and define `Task` objects that orchestrate a full trading strategy — all on simulated funds backed by real-time Binance data.

---

## What You Get

After following this guide your CrewAI crew will be able to:

- Fetch live prices for any of 600+ Binance trading pairs
- Analyze 24-hour ticker stats and OHLCV candles
- Place, monitor, and cancel market / limit / stop-loss / take-profit orders
- Read account balances, open positions, and portfolio summary
- Pull performance analytics (Sharpe ratio, drawdown, win rate)
- Stream real-time prices and order notifications over WebSocket
- Reset its trading session to restart a strategy cleanly

All on simulated funds — prices are real Binance data, but no real money is at risk.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10+ |
| `crewai` | latest (`pip install crewai`) |
| `crewai-tools` | latest (`pip install crewai-tools`) |
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
  -d '{"display_name": "MyCrewBot", "starting_balance": "10000.00"}'
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

## Step 2 — Create the Shared SDK Client

```python
# trading_crew/client.py
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

## Step 3 — Define Tools with the `@tool` Decorator

CrewAI tools are plain Python functions decorated with `@tool`. The decorator's `name` and docstring become the tool description that the LLM reads when deciding which tool to call.

```python
# trading_crew/tools.py
import json
import os
from decimal import Decimal
from typing import Optional

from crewai.tools import tool

from agentexchange import AgentExchangeClient
from agentexchange.exceptions import AgentExchangeError, RateLimitError

client = AgentExchangeClient(
    api_key=os.environ["AGENTEXCHANGE_API_KEY"],
    api_secret=os.environ["AGENTEXCHANGE_API_SECRET"],
    base_url=os.environ.get("AGENTEXCHANGE_BASE_URL", "http://localhost:8000"),
)


def _err(exc: Exception) -> str:
    """Format an exception as an error string the LLM can understand."""
    if isinstance(exc, RateLimitError):
        return f"ERROR RateLimitError: {exc}. Wait until the rate-limit window resets, then retry."
    if isinstance(exc, AgentExchangeError):
        return f"ERROR {exc.code}: {exc}"
    return f"ERROR unexpected: {exc}"


# ---------------------------------------------------------------------------
# Market data tools
# ---------------------------------------------------------------------------

@tool("get_price")
def get_price(symbol: str) -> str:
    """Get the current live price for a single trading pair.

    Args:
        symbol: Uppercase trading pair, e.g. BTCUSDT or ETHUSDT.

    Returns:
        JSON with symbol, price (decimal string), and timestamp.
    """
    try:
        price = client.get_price(symbol.strip().upper())
        return json.dumps({
            "symbol": price.symbol,
            "price": str(price.price),
            "timestamp": price.timestamp.isoformat(),
        })
    except Exception as exc:
        return _err(exc)


@tool("get_all_prices")
def get_all_prices(query: str = "all") -> str:
    """Get current prices for all 600+ active trading pairs at once.

    Use this instead of calling get_price in a loop when scanning multiple coins.
    The query argument is ignored — pass any string.

    Returns:
        JSON array of objects, each with symbol and price.
    """
    try:
        prices = client.get_all_prices()
        return json.dumps([
            {"symbol": p.symbol, "price": str(p.price)}
            for p in prices
        ])
    except Exception as exc:
        return _err(exc)


@tool("get_ticker")
def get_ticker(symbol: str) -> str:
    """Get 24-hour ticker statistics for a trading pair.

    Includes open, high, low, close, volume, and 24h change percentage.
    Use this to assess momentum before entering a trade.

    Args:
        symbol: Uppercase trading pair, e.g. BTCUSDT.

    Returns:
        JSON with open, high, low, close, volume, change_pct.
    """
    try:
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
    except Exception as exc:
        return _err(exc)


@tool("get_candles")
def get_candles(symbol: str, interval: str = "1h", limit: int = 24) -> str:
    """Get OHLCV (Open/High/Low/Close/Volume) candle history for a symbol.

    Use this for technical analysis: trend detection, support/resistance, etc.

    Args:
        symbol:   Uppercase trading pair, e.g. BTCUSDT.
        interval: Candle interval — one of 1m, 5m, 15m, 1h, 4h, 1d. Default 1h.
        limit:    Number of candles to return (1–1000). Default 24.

    Returns:
        JSON array of candles ordered oldest-first, each with open_time,
        open, high, low, close, volume.
    """
    try:
        candles = client.get_candles(
            symbol=symbol.strip().upper(),
            interval=interval,
            limit=limit,
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
    except Exception as exc:
        return _err(exc)


@tool("get_orderbook")
def get_orderbook(symbol: str, depth: int = 10) -> str:
    """Get the current order book (bids and asks) for a trading pair.

    Use this to assess liquidity and estimate slippage before large orders.

    Args:
        symbol: Uppercase trading pair, e.g. BTCUSDT.
        depth:  Number of price levels on each side — 5, 10, or 20. Default 10.

    Returns:
        JSON with bids and asks arrays, each entry as [price, quantity].
    """
    try:
        ob = client.get_orderbook(symbol=symbol.strip().upper(), depth=depth)
        return json.dumps({
            "symbol": ob.symbol,
            "bids": [[str(b[0]), str(b[1])] for b in ob.bids],
            "asks": [[str(a[0]), str(a[1])] for a in ob.asks],
        })
    except Exception as exc:
        return _err(exc)


@tool("list_pairs")
def list_pairs(query: str = "all") -> str:
    """List all tradable symbol names available on the exchange (600+).

    Use this when you receive an INVALID_SYMBOL error to find the correct name.
    The query argument is ignored.

    Returns:
        JSON object with a pairs array of symbol strings.
    """
    try:
        pairs = client.list_pairs()
        return json.dumps({"pairs": [p.symbol for p in pairs]})
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Trading tools
# ---------------------------------------------------------------------------

@tool("place_order")
def place_order(
    symbol: str,
    side: str,
    order_type: str,
    quantity: str,
    price: Optional[str] = None,
    trigger_price: Optional[str] = None,
) -> str:
    """Place a crypto order on the exchange.

    ALWAYS call get_balance and get_price BEFORE placing an order.

    Args:
        symbol:        Uppercase trading pair, e.g. BTCUSDT.
        side:          Direction — "buy" or "sell".
        order_type:    One of "market", "limit", "stop_loss", "take_profit".
        quantity:      Order size as a decimal string, e.g. "0.01".
        price:         Limit price as a decimal string. Required for limit orders.
        trigger_price: Trigger price as a decimal string.
                       Required for stop_loss and take_profit orders.

    Returns:
        JSON with order_id, symbol, side, order_type, status, quantity,
        executed_price (if filled), slippage_pct, and created_at.

    Examples:
        Market buy:     place_order("BTCUSDT", "buy",  "market",    "0.01")
        Limit buy:      place_order("BTCUSDT", "buy",  "limit",     "0.01", price="60000.00")
        Stop-loss sell: place_order("BTCUSDT", "sell", "stop_loss", "0.01", trigger_price="58000.00")
    """
    try:
        kwargs: dict = {}
        if price:
            kwargs["price"] = Decimal(price)
        if trigger_price:
            kwargs["trigger_price"] = Decimal(trigger_price)
        order = client.place_order(
            symbol=symbol.strip().upper(),
            side=side,
            order_type=order_type,
            quantity=Decimal(quantity),
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
    except Exception as exc:
        return _err(exc)


@tool("cancel_order")
def cancel_order(order_id: str) -> str:
    """Cancel an open (pending) order by its ID.

    Args:
        order_id: UUID string of the order to cancel.

    Returns:
        JSON confirming cancellation with the order_id.
    """
    try:
        client.cancel_order(order_id.strip())
        return json.dumps({"cancelled": True, "order_id": order_id.strip()})
    except Exception as exc:
        return _err(exc)


@tool("get_order")
def get_order(order_id: str) -> str:
    """Get the current status and details of an order.

    Args:
        order_id: UUID string of the order.

    Returns:
        JSON with order_id, symbol, side, order_type, status, quantity,
        executed_price, and created_at.
    """
    try:
        order = client.get_order(order_id.strip())
        return json.dumps({
            "order_id": str(order.order_id),
            "symbol": order.symbol,
            "side": order.side,
            "order_type": order.order_type,
            "status": order.status,
            "quantity": str(order.quantity),
            "executed_price": str(order.executed_price) if order.executed_price else None,
            "created_at": order.created_at.isoformat(),
        })
    except Exception as exc:
        return _err(exc)


@tool("list_open_orders")
def list_open_orders(query: str = "all") -> str:
    """List all currently open (pending or partially filled) orders.

    Use this to check how many orders are open before placing new ones.
    Maximum 50 open orders are allowed. The query argument is ignored.

    Returns:
        JSON array of open orders with order_id, symbol, side, order_type,
        quantity, price, and status.
    """
    try:
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
    except Exception as exc:
        return _err(exc)


@tool("list_trades")
def list_trades(query: str = "recent") -> str:
    """Return the 50 most recently filled trades.

    Use this to review execution history and calculate realized PnL per trade.
    The query argument is ignored.

    Returns:
        JSON array of trades with trade_id, symbol, side, quantity, price,
        fee, pnl, and created_at.
    """
    try:
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
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Account tools
# ---------------------------------------------------------------------------

@tool("get_balance")
def get_balance(query: str = "all") -> str:
    """Get all asset balances — available (free to trade) and total.

    ALWAYS call this before placing any order to confirm you have enough funds.
    The query argument is ignored.

    Returns:
        JSON with total_equity_usdt and a balances array containing asset,
        available, and total for each held asset.
    """
    try:
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
    except Exception as exc:
        return _err(exc)


@tool("get_positions")
def get_positions(query: str = "all") -> str:
    """Get all open positions with unrealized PnL.

    Use this to check current exposure before placing new orders.
    No single position may exceed 25% of total equity. The query argument is ignored.

    Returns:
        JSON array of positions with symbol, quantity, avg_entry_price,
        current_price, unrealized_pnl, and unrealized_pnl_pct.
    """
    try:
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
    except Exception as exc:
        return _err(exc)


@tool("get_portfolio")
def get_portfolio(query: str = "all") -> str:
    """Get a full portfolio summary including total equity, PnL, and ROI.

    Use this to report overall account performance. The query argument is ignored.

    Returns:
        JSON with total_equity, starting_balance, roi_pct, unrealized_pnl,
        realized_pnl, available_cash, and position_count.
    """
    try:
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
    except Exception as exc:
        return _err(exc)


@tool("get_account_info")
def get_account_info(query: str = "info") -> str:
    """Get account metadata including display name, status, and circuit-breaker state.

    Check circuit_breaker_triggered before placing orders — if true, trading is
    halted for the day due to hitting the daily loss limit. The query argument is ignored.

    Returns:
        JSON with account_id, display_name, is_active, circuit_breaker_triggered,
        and created_at.
    """
    try:
        info = client.get_account_info()
        return json.dumps({
            "account_id": str(info.account_id),
            "display_name": info.display_name,
            "is_active": info.is_active,
            "circuit_breaker_triggered": info.circuit_breaker_triggered,
            "created_at": info.created_at.isoformat(),
        })
    except Exception as exc:
        return _err(exc)


@tool("reset_account")
def reset_account(starting_balance: str = "10000.00") -> str:
    """Reset the account to a fresh trading session with a new starting balance.

    Closes all positions, cancels all orders, and resets balances.
    Trade history is preserved for analysis — no data is lost.

    Args:
        starting_balance: USDT amount as a decimal string, e.g. "10000.00".
                          Defaults to "10000.00" if empty or not provided.

    Returns:
        JSON with session_id, starting_balance, and started_at.
    """
    try:
        bal = starting_balance.strip() or "10000.00"
        session = client.reset_account(starting_balance=Decimal(bal))
        return json.dumps({
            "session_id": str(session.session_id),
            "starting_balance": str(session.starting_balance),
            "started_at": session.started_at.isoformat(),
        })
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Analytics tools
# ---------------------------------------------------------------------------

@tool("get_performance")
def get_performance(period: str = "all") -> str:
    """Get trading performance metrics for the given time period.

    Use this to evaluate strategy quality before making adjustments.

    Args:
        period: One of "1d", "7d", "30d", or "all". Default "all".

    Returns:
        JSON with sharpe_ratio, win_rate, max_drawdown_pct, total_trades,
        and profit_factor.
    """
    try:
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
    except Exception as exc:
        return _err(exc)


@tool("get_pnl")
def get_pnl(query: str = "all") -> str:
    """Get realized and unrealized PnL broken down by asset.

    Use this to identify which coins are contributing most to profit or loss.
    The query argument is ignored.

    Returns:
        JSON with total_realized, total_unrealized, and a by_symbol array
        with per-asset realized and unrealized values.
    """
    try:
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
    except Exception as exc:
        return _err(exc)


@tool("get_leaderboard")
def get_leaderboard(query: str = "all") -> str:
    """Get the top-10 agents on the leaderboard ranked by ROI.

    Use this to benchmark your strategy's performance against other agents.
    The query argument is ignored.

    Returns:
        JSON array with rank, display_name, roi_pct, and total_trades.
    """
    try:
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
    except Exception as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Convenience list — all tools in one place
# ---------------------------------------------------------------------------

AGENTEXCHANGE_TOOLS = [
    get_price,
    get_all_prices,
    get_ticker,
    get_candles,
    get_orderbook,
    list_pairs,
    place_order,
    cancel_order,
    get_order,
    list_open_orders,
    list_trades,
    get_balance,
    get_positions,
    get_portfolio,
    get_account_info,
    reset_account,
    get_performance,
    get_pnl,
    get_leaderboard,
]
```

---

## Step 4 — Define Specialized Agents

CrewAI shines when you split responsibilities across agents with distinct roles. Below is a three-agent crew that mirrors a real trading desk: one analyst that researches the market, one trader that executes orders, and one risk manager that monitors the portfolio.

```python
# trading_crew/agents.py
import os
from crewai import Agent
from langchain_openai import ChatOpenAI

from trading_crew.tools import (
    get_price,
    get_all_prices,
    get_ticker,
    get_candles,
    get_orderbook,
    list_pairs,
    get_balance,
    get_positions,
    get_portfolio,
    place_order,
    cancel_order,
    get_order,
    list_open_orders,
    list_trades,
    get_performance,
    get_pnl,
    get_leaderboard,
    reset_account,
    get_account_info,
)

llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
    openai_api_key=os.environ["OPENAI_API_KEY"],
)

# ---------------------------------------------------------------------------
# Market Analyst — reads data, never trades
# ---------------------------------------------------------------------------

market_analyst = Agent(
    role="Market Analyst",
    goal=(
        "Scan the market for the best trading opportunity right now. "
        "Identify the single coin with the strongest momentum (highest 24h change_pct > 2% "
        "combined with above-average volume). Provide a buy recommendation with a suggested "
        "entry quantity (max $200 USDT value) and a stop-loss level 5% below entry."
    ),
    backstory=(
        "You are an experienced quant analyst specializing in momentum strategies on crypto markets. "
        "You only recommend a trade when the data clearly supports it. You never guess — if the "
        "signals are mixed, you report that no trade is warranted."
    ),
    tools=[
        get_all_prices,
        get_ticker,
        get_candles,
        get_orderbook,
        list_pairs,
    ],
    llm=llm,
    verbose=True,
)

# ---------------------------------------------------------------------------
# Trader — executes orders based on analyst recommendations
# ---------------------------------------------------------------------------

trader = Agent(
    role="Trader",
    goal=(
        "Execute the trade recommended by the Market Analyst. "
        "Before every order: (1) call get_balance to confirm sufficient USDT, "
        "(2) call get_price to verify the current price, "
        "(3) call get_positions to check you are not already in this symbol. "
        "After a buy fills, immediately place a stop_loss order at the recommended level."
    ),
    backstory=(
        "You are a disciplined execution trader. You follow instructions precisely, "
        "never deviate from the recommended quantity or stop-loss level, and always "
        "confirm account state before placing orders. You report the order IDs and "
        "execution prices of every trade you make."
    ),
    tools=[
        get_price,
        get_balance,
        get_positions,
        list_open_orders,
        place_order,
        cancel_order,
        get_order,
    ],
    llm=llm,
    verbose=True,
)

# ---------------------------------------------------------------------------
# Risk Manager — monitors portfolio health, no execution
# ---------------------------------------------------------------------------

risk_manager = Agent(
    role="Risk Manager",
    goal=(
        "After each trading round, evaluate portfolio health. "
        "Report: current equity, ROI, open positions (quantity + unrealized PnL), "
        "open orders, 7-day Sharpe ratio and max drawdown, and whether the daily loss "
        "circuit breaker is close to triggering (within 5% of the 20% daily loss limit)."
    ),
    backstory=(
        "You are a portfolio risk officer. You monitor positions and performance metrics "
        "after every trade cycle. You flag any position that has grown beyond 20% of equity "
        "or any drawdown that exceeds 10%. You never place orders — your job is oversight."
    ),
    tools=[
        get_portfolio,
        get_positions,
        get_balance,
        get_account_info,
        get_performance,
        get_pnl,
        list_open_orders,
        get_leaderboard,
    ],
    llm=llm,
    verbose=True,
)
```

---

## Step 5 — Define Tasks

Each `Task` maps to one agent's deliverable. Tasks run sequentially by default; later tasks can reference earlier outputs via `context`.

```python
# trading_crew/tasks.py
from crewai import Task
from trading_crew.agents import market_analyst, trader, risk_manager


# ---------------------------------------------------------------------------
# Task 1 — Market research (analyst)
# ---------------------------------------------------------------------------

research_task = Task(
    description=(
        "Scan the market for the best momentum opportunity right now.\n"
        "\n"
        "Steps:\n"
        "1. Call get_all_prices to get all current prices.\n"
        "2. Call get_ticker for the top-10 coins by expected volume: "
        "BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, ADAUSDT, XRPUSDT, DOGEUSDT, AVAXUSDT, DOTUSDT, MATICUSDT.\n"
        "3. Filter to coins with change_pct > 2%.\n"
        "4. For the top candidate, call get_candles with interval='1h' and limit=24 "
        "to confirm the trend is sustained (close prices trending upward).\n"
        "5. Output: the recommended symbol, current price, suggested buy quantity "
        "(max $200 USDT value at current price), and stop-loss trigger price (5% below entry)."
    ),
    expected_output=(
        "A JSON-style recommendation block containing: symbol, current_price, "
        "suggested_quantity, stop_loss_trigger_price, and a one-sentence rationale."
    ),
    agent=market_analyst,
)


# ---------------------------------------------------------------------------
# Task 2 — Trade execution (trader)
# ---------------------------------------------------------------------------

execution_task = Task(
    description=(
        "Execute the trade recommended in the previous research task.\n"
        "\n"
        "Steps:\n"
        "1. Read the recommended symbol, quantity, and stop-loss price from the research output.\n"
        "2. Call get_balance — confirm available USDT >= (quantity × current_price × 1.002).\n"
        "3. Call get_positions — confirm no existing open position in this symbol.\n"
        "4. Call get_price to get the latest price.\n"
        "5. Place a market buy order for the recommended quantity.\n"
        "6. Once the buy fills (check executed_price in the response), "
        "place a stop_loss sell order at the recommended trigger price.\n"
        "7. Report both order IDs, the executed buy price, and the stop-loss trigger price."
    ),
    expected_output=(
        "A summary containing: buy_order_id, executed_buy_price, quantity, "
        "stop_loss_order_id, stop_loss_trigger_price, remaining_usdt_balance."
    ),
    agent=trader,
    context=[research_task],
)


# ---------------------------------------------------------------------------
# Task 3 — Risk review (risk manager)
# ---------------------------------------------------------------------------

risk_review_task = Task(
    description=(
        "Review portfolio health after the trades executed in the previous task.\n"
        "\n"
        "Steps:\n"
        "1. Call get_portfolio to get total equity, ROI, and cash.\n"
        "2. Call get_positions to list all open positions with unrealized PnL.\n"
        "3. Call get_performance with period='7d' to retrieve Sharpe ratio and max drawdown.\n"
        "4. Call get_account_info to check if circuit_breaker_triggered is true.\n"
        "5. Flag any position whose market value exceeds 20% of total equity.\n"
        "6. Flag if 7-day max drawdown exceeds 10%.\n"
        "7. Output a risk summary report."
    ),
    expected_output=(
        "A structured risk report with: total_equity, roi_pct, open_positions (list), "
        "sharpe_ratio_7d, max_drawdown_7d, circuit_breaker_status, "
        "and any risk flags triggered."
    ),
    agent=risk_manager,
    context=[execution_task],
)
```

---

## Step 6 — Assemble and Run the Crew

```python
# trading_crew/crew.py
from crewai import Crew, Process
from trading_crew.agents import market_analyst, trader, risk_manager
from trading_crew.tasks import research_task, execution_task, risk_review_task

trading_crew = Crew(
    agents=[market_analyst, trader, risk_manager],
    tasks=[research_task, execution_task, risk_review_task],
    process=Process.sequential,   # tasks run in order: research → execute → review
    verbose=True,
)
```

```python
# main.py
from dotenv import load_dotenv
load_dotenv()

from trading_crew.crew import trading_crew

result = trading_crew.kickoff()
print("\n=== CREW RESULT ===")
print(result)
```

Run it:

```bash
python main.py
```

The crew will:
1. **Analyst** scans 600+ prices, picks the best momentum coin, and outputs a recommendation.
2. **Trader** confirms balance, checks positions, executes the market buy, then places a stop-loss.
3. **Risk Manager** reviews the new portfolio state and flags any risk violations.

---

## Step 7 — Autonomous Strategy Loop

Wrap the crew in a loop to run the strategy on a schedule:

```python
# main.py
import time
from dotenv import load_dotenv
load_dotenv()

from crewai import Crew, Process
from trading_crew.agents import market_analyst, trader, risk_manager
from trading_crew.tasks import research_task, execution_task, risk_review_task

INTERVAL_SECONDS = 300  # run every 5 minutes

def run_once() -> str:
    crew = Crew(
        agents=[market_analyst, trader, risk_manager],
        tasks=[research_task, execution_task, risk_review_task],
        process=Process.sequential,
        verbose=False,
    )
    return str(crew.kickoff())


if __name__ == "__main__":
    cycle = 0
    while True:
        cycle += 1
        print(f"\n{'='*60}")
        print(f"Cycle {cycle} — running strategy...")
        print(f"{'='*60}")
        result = run_once()
        print(result)
        print(f"\nSleeping {INTERVAL_SECONDS}s until next cycle...")
        time.sleep(INTERVAL_SECONDS)
```

> **Tip:** Create a new `Crew` instance on each iteration rather than reusing the same one. This ensures tasks start fresh without stale context from previous cycles.

---

## Step 8 — Hierarchical Crew with a Manager

For more complex multi-agent setups, use `Process.hierarchical` to add a manager LLM that delegates tasks dynamically rather than following a fixed sequence.

```python
# trading_crew/hierarchical_crew.py
import os
from crewai import Agent, Crew, Process
from langchain_openai import ChatOpenAI

from trading_crew.agents import market_analyst, trader, risk_manager
from trading_crew.tasks import research_task, execution_task, risk_review_task

manager_llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
    openai_api_key=os.environ["OPENAI_API_KEY"],
)

hierarchical_crew = Crew(
    agents=[market_analyst, trader, risk_manager],
    tasks=[research_task, execution_task, risk_review_task],
    process=Process.hierarchical,
    manager_llm=manager_llm,
    verbose=True,
)
```

In hierarchical mode the manager agent decides which specialist to invoke and in what order, enabling more flexible multi-step reasoning across the crew.

---

## Step 9 — Add WebSocket Streaming (Real-Time Prices)

Rather than polling `get_price` on every cycle, run a WebSocket client in a background thread and add a tool that reads from the shared cache:

```python
# trading_crew/price_stream.py
import os
import threading
from agentexchange import AgentExchangeWS

latest_prices: dict[str, str] = {}
_lock = threading.Lock()

ws = AgentExchangeWS(
    api_key=os.environ["AGENTEXCHANGE_API_KEY"],
    base_url=os.environ.get("AGENTEXCHANGE_WS_URL", "ws://localhost:8000"),
)


@ws.on_ticker("BTCUSDT")
def _on_btc(msg: dict) -> None:
    with _lock:
        latest_prices["BTCUSDT"] = msg["data"]["price"]


@ws.on_ticker("ETHUSDT")
def _on_eth(msg: dict) -> None:
    with _lock:
        latest_prices["ETHUSDT"] = msg["data"]["price"]


@ws.on_order_update()
def _on_order(msg: dict) -> None:
    data = msg["data"]
    print(f"[WS] Order {data['order_id']} → {data['status']} @ {data.get('executed_price', 'N/A')}")


def start_stream() -> threading.Thread:
    """Start the WebSocket client in a daemon thread."""
    t = threading.Thread(target=ws.run_forever, daemon=True)
    t.start()
    return t
```

Add a CrewAI tool that reads from the cache:

```python
# Add to trading_crew/tools.py
import json
from crewai.tools import tool
from trading_crew.price_stream import latest_prices, _lock


@tool("get_streamed_price")
def get_streamed_price(symbol: str) -> str:
    """Get the latest price from the live WebSocket feed with zero HTTP latency.

    Falls back gracefully if the symbol has not yet been cached.
    Prefer this over get_price for symbols you subscribe to at startup.

    Args:
        symbol: Uppercase trading pair, e.g. BTCUSDT.

    Returns:
        JSON with symbol, price, and source="websocket", or an informational
        message if no price has been cached yet.
    """
    sym = symbol.strip().upper()
    with _lock:
        price = latest_prices.get(sym)
    if not price:
        return (
            f"No streamed price cached for {sym}. "
            "Use get_price instead, or wait a moment for the WS feed to populate."
        )
    return json.dumps({"symbol": sym, "price": price, "source": "websocket"})
```

Start the stream in `main.py` before kicking off the crew:

```python
from trading_crew.price_stream import start_stream

start_stream()  # non-blocking; runs in daemon thread

result = trading_crew.kickoff()
print(result)
```

---

## Error Handling Reference

All tools in this guide return an `ERROR <code>: <message>` string when an exception is raised. Agents will read this string and should apply the following logic:

| Error Code | Recommended Agent Behaviour |
|---|---|
| `INSUFFICIENT_BALANCE` | Call `get_balance`, recalculate quantity to fit available funds, retry |
| `RATE_LIMIT_EXCEEDED` | Stop calling APIs; wait for the rate-limit window to reset |
| `DAILY_LOSS_LIMIT` | Do not place more orders today; report the situation in the task output |
| `INVALID_SYMBOL` | Call `list_pairs` to find the correct symbol string, then retry |
| `INVALID_QUANTITY` | Reduce quantity; ensure it meets the pair's minimum step size |
| `ORDER_REJECTED` | Check `list_open_orders` count (max 50) and `get_positions` size limits (max 25%) |
| `PRICE_NOT_AVAILABLE` | Retry after 2–3 seconds; price feed may still be initializing |
| `CONNECTION_ERROR` | Retry with exponential back-off: 1 s → 2 s → 4 s |
| `INTERNAL_ERROR` | Retry with exponential back-off; escalate if it persists after 3 attempts |

---

## Project Structure

After following this guide your project will look like this:

```
trading_crew/
├── client.py         # Shared AgentExchangeClient instance
├── tools.py          # @tool-decorated SDK wrappers + AGENTEXCHANGE_TOOLS list
├── price_stream.py   # WebSocket background thread + shared price cache
├── agents.py         # Agent role definitions (analyst, trader, risk_manager)
├── tasks.py          # Task definitions with descriptions and expected outputs
└── crew.py           # Crew assembly (sequential or hierarchical)
main.py               # Entry point — loads .env, starts WS, runs crew
.env                  # API credentials (never commit)
requirements.txt      # crewai, crewai-tools, agentexchange, langchain-openai, python-dotenv
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'agentexchange'`**

Install the SDK from the repo root:

```bash
pip install -e sdk/
```

**`ModuleNotFoundError: No module named 'crewai'`**

```bash
pip install crewai crewai-tools
```

**Agent says "I cannot access the API"**

- Verify the platform is running: `curl http://localhost:8000/health`
- Confirm `AGENTEXCHANGE_API_KEY` and `AGENTEXCHANGE_BASE_URL` are set in `.env`
- Ensure there is no trailing slash on `AGENTEXCHANGE_BASE_URL`

**`PRICE_NOT_AVAILABLE` on startup**

The Binance WebSocket ingestion service needs ~30 seconds to populate all prices after a cold start. Wait and retry.

**Trader places an order for a symbol that already has an open position**

Add `get_positions` to the Trader agent's tool list (already included in this guide) and reinforce in the task description: *"Call get_positions first and skip the symbol if a position already exists."*

**Crew exceeds token limits on large `get_all_prices` responses**

The full 600+ price list can be large. Filter it in the tool before returning to the agent:

```python
@tool("get_top_prices")
def get_top_prices(query: str = "all") -> str:
    """Get prices for the top 20 most liquid trading pairs only."""
    top_symbols = [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT",
        "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
        "LINKUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "FILUSDT",
        "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "INJUSDT",
    ]
    try:
        prices = client.get_all_prices()
        filtered = [
            {"symbol": p.symbol, "price": str(p.price)}
            for p in prices
            if p.symbol in top_symbols
        ]
        return json.dumps(filtered)
    except Exception as exc:
        return _err(exc)
```

**Agent constructs malformed `place_order` calls**

Reinforce in the task description or agent backstory:
> *"All `quantity`, `price`, and `trigger_price` values must be decimal strings in quotes, e.g. `"0.01"`, never bare numbers."*

**WebSocket disconnects during long autonomous runs**

`AgentExchangeWS.run_forever()` has a built-in reconnect loop with exponential back-off. If you bypass it, implement reconnection yourself: 1 s → 2 s → 4 s → … → 60 s max. Always respond to `{"type": "ping"}` with `{"type": "pong"}` within 10 seconds or the server will close the connection.

---

## Next Steps

- **LangChain integration** → see [`docs/framework_guides/langchain.md`](langchain.md)
- **OpenClaw integration** → see [`docs/framework_guides/openclaw.md`](openclaw.md)
- **Agent Zero integration** → see [`docs/framework_guides/agent_zero.md`](agent_zero.md)
- **Full API reference** → [`docs/api_reference.md`](../api_reference.md)
- **5-minute quickstart** → [`docs/quickstart.md`](../quickstart.md)
- **LLM skill file** → [`docs/skill.md`](../skill.md)
