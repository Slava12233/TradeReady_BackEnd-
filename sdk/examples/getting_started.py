"""Getting started companion script — validates Steps 4-6 from the getting-started guide.

Runs three sequential checks against a live platform:

  Step 4 — Price Watcher: fetch current BTC price and last 5 candles
  Step 5 — First Trade:   buy 0.001 BTC, inspect position, sell, check PnL
  Step 6 — Backtest:      run a 7-day BTCUSDT backtest, print performance metrics

Each step prints its result so you can verify the platform is responding correctly.
Stop-on-error: if any step fails, the script exits with a non-zero code.

Requirements:
    pip install -e sdk/
    export TRADEREADY_API_URL=http://localhost:8000
    export TRADEREADY_API_KEY=ak_live_YOUR_KEY
    export TRADEREADY_API_SECRET=sk_live_YOUR_SECRET

Run:
    python sdk/examples/getting_started.py
"""

from __future__ import annotations

import os
import sys
import time
from decimal import Decimal

from agentexchange import AgentExchangeClient
from agentexchange.exceptions import AgentExchangeError, InsufficientBalanceError

# ---------------------------------------------------------------------------
# Configuration from environment variables
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("TRADEREADY_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("TRADEREADY_API_KEY", "")
API_SECRET = os.environ.get("TRADEREADY_API_SECRET", "")

SYMBOL = "BTCUSDT"
ORDER_QTY = Decimal("0.001")        # small size to minimise balance impact
BACKTEST_START = "2025-01-01T00:00:00Z"
BACKTEST_END = "2025-01-07T23:59:00Z"   # 7 days — fast to run
BACKTEST_BALANCE = "10000"
BATCH_SIZE = 500                    # candles per batch step


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_env() -> None:
    """Exit with a clear message if required environment variables are missing."""
    missing = [
        v for v in ("TRADEREADY_API_KEY", "TRADEREADY_API_SECRET")
        if not os.environ.get(v)
    ]
    if missing:
        print(f"ERROR: Missing environment variable(s): {', '.join(missing)}")
        print("Set them with:")
        print("  export TRADEREADY_API_KEY=ak_live_...")
        print("  export TRADEREADY_API_SECRET=sk_live_...")
        sys.exit(1)


def _sep(title: str) -> None:
    """Print a section separator."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# Step 4 — Price Watcher
# ---------------------------------------------------------------------------

def step4_price_watcher(client: AgentExchangeClient) -> None:
    """Fetch current BTC price and the last 5 one-minute candles.

    Args:
        client: Authenticated SDK client.
    """
    _sep("Step 4 — Price Watcher")

    # Current price
    price = client.get_price(SYMBOL)
    print(f"Current {SYMBOL} price: ${price.price}")
    print(f"  Timestamp: {price.timestamp}")

    # Last 5 candles
    candles = client.get_candles(SYMBOL, interval="1m", limit=5)
    print(f"\nLast {len(candles)} one-minute candles:")
    for c in candles:
        print(
            f"  {str(c.open_time)[:19]}  O={c.open:>12}  H={c.high:>12}"
            f"  L={c.low:>12}  C={c.close:>12}  V={c.volume:>14}"
        )

    # Confirm at least one candle came back
    if not candles:
        print("ERROR: No candle data returned. Is the platform fully initialised?")
        sys.exit(1)

    print("\nStep 4 PASSED.")


# ---------------------------------------------------------------------------
# Step 5 — First Trade
# ---------------------------------------------------------------------------

def step5_first_trade(client: AgentExchangeClient) -> None:
    """Place a market buy, inspect position, then sell and check PnL.

    Args:
        client: Authenticated SDK client.
    """
    _sep("Step 5 — First Trade")

    # Check balance before trading
    balance = client.get_balance()
    usdt_balance = next(
        (b for b in balance.balances if b.asset == "USDT"), None
    )
    if usdt_balance:
        print(f"USDT available: {usdt_balance.available}")
    else:
        print("WARNING: No USDT balance found. Has the account been registered?")

    # Buy
    print(f"\nPlacing market buy: {ORDER_QTY} {SYMBOL}...")
    try:
        buy = client.place_market_order(SYMBOL, "buy", ORDER_QTY)
    except InsufficientBalanceError as e:
        print(f"ERROR: Insufficient balance — need {e.required} USDT, have {e.available} USDT.")
        print("Reset your account balance with: POST /api/v1/account/reset")
        sys.exit(1)
    except AgentExchangeError as e:
        print(f"ERROR: Order placement failed: {e}")
        sys.exit(1)

    print(f"  Filled {buy.executed_quantity} {SYMBOL} at ${buy.executed_price}")
    print(f"  Fee: ${buy.fee}   Slippage: {buy.slippage_pct}%")

    # Brief pause — give the position tracker a moment to update
    time.sleep(0.5)

    # Inspect open position
    positions = client.get_positions()
    btc_position = next(
        (p for p in positions if p.symbol == SYMBOL), None
    )
    if btc_position:
        print(f"\nOpen position: {btc_position.symbol}")
        print(f"  Quantity:     {btc_position.quantity}")
        print(f"  Avg entry:    ${btc_position.avg_entry_price}")
        print(f"  Unrealised PnL: ${btc_position.unrealized_pnl}")
    else:
        print("\nWARNING: Expected a BTC position but none found.")

    # Portfolio snapshot
    portfolio = client.get_portfolio()
    print(f"\nPortfolio equity: ${portfolio.total_equity}")

    # Sell (close the position)
    print(f"\nPlacing market sell: {ORDER_QTY} {SYMBOL}...")
    try:
        sell = client.place_market_order(SYMBOL, "sell", ORDER_QTY)
    except AgentExchangeError as e:
        print(f"ERROR: Sell order failed: {e}")
        sys.exit(1)

    print(f"  Sold {sell.executed_quantity} {SYMBOL} at ${sell.executed_price}")

    # Realised PnL
    pnl = client.get_pnl()
    print(f"\nRealised PnL:     ${pnl.realized_pnl}")
    print(f"Total PnL:        ${pnl.total_pnl}")

    print("\nStep 5 PASSED.")


# ---------------------------------------------------------------------------
# Step 6 — Backtest
# ---------------------------------------------------------------------------

def step6_backtest(client: AgentExchangeClient) -> None:
    """Run a 7-day BTCUSDT backtest and print the performance metrics.

    Uses the fast-batch path (500 candles per call) so the 7-day simulation
    finishes in a few seconds.

    Args:
        client: Authenticated SDK client.
    """
    _sep("Step 6 — Backtest")

    # Create the session
    print(f"Creating backtest session: {BACKTEST_START} -> {BACKTEST_END}")
    session = client._request(
        "POST",
        "/api/v1/backtest/create",
        json={
            "start_time": BACKTEST_START,
            "end_time": BACKTEST_END,
            "starting_balance": BACKTEST_BALANCE,
            "candle_interval": 60,
            "pairs": [SYMBOL],
            "strategy_label": "getting_started_example",
        },
    )
    session_id: str = session["session_id"]
    total_steps: int = session.get("total_steps", 0)
    print(f"Session: {session_id}  total_steps: {total_steps}")

    # Start the session
    client._request("POST", f"/api/v1/backtest/{session_id}/start")
    print("Session started.")

    # Place one buy at the beginning
    try:
        order = client._request(
            "POST",
            f"/api/v1/backtest/{session_id}/trade/order",
            json={
                "symbol": SYMBOL,
                "side": "buy",
                "type": "market",
                "quantity": "0.01",
            },
        )
        print(f"Initial buy placed: order_id={order.get('order_id')}  status={order.get('status')}")
    except AgentExchangeError as exc:
        print(f"WARNING: Could not place initial order: {exc}")

    # Step through the date range in fast batches
    print(f"\nRunning backtest in batches of {BATCH_SIZE} candles...")
    t0 = time.monotonic()

    while True:
        result = client.batch_step_fast(session_id, steps=BATCH_SIZE)
        progress = result.get("progress_pct", 0.0)
        step = result.get("step", 0)
        total = result.get("total_steps", total_steps)
        fills = len(result.get("orders_filled", []))
        print(f"  {step:>6}/{total}  ({progress:5.1f}%)  fills={fills}")

        if result.get("is_complete"):
            break

    elapsed = time.monotonic() - t0
    print(f"\nSimulation complete in {elapsed:.1f}s.")

    # Retrieve results
    try:
        results = client._request("GET", f"/api/v1/backtest/{session_id}/results")
    except AgentExchangeError as exc:
        print(f"ERROR: Could not retrieve results: {exc}")
        sys.exit(1)

    metrics = results.get("metrics") or {}
    print("\n--- Backtest Results ---")
    print(f"  Total Return : {metrics.get('total_return_pct', 'n/a')}%")
    print(f"  Sharpe Ratio : {metrics.get('sharpe_ratio', 'n/a')}")
    print(f"  Max Drawdown : {metrics.get('max_drawdown_pct', 'n/a')}%")
    print(f"  Win Rate     : {metrics.get('win_rate', 'n/a')}%")
    print(f"  Total Trades : {metrics.get('total_trades', 'n/a')}")
    print(f"  Final Equity : {results.get('final_equity', 'n/a')} USDT")

    print("\nStep 6 PASSED.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run Steps 4-6 from the getting-started guide end-to-end."""
    _require_env()

    print("AgentExchange — Getting Started Validation")
    print(f"  API URL : {BASE_URL}")
    print(f"  API Key : {API_KEY[:12]}...")

    with AgentExchangeClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        base_url=BASE_URL,
    ) as client:
        step4_price_watcher(client)
        step5_first_trade(client)
        step6_backtest(client)

    _sep("All steps passed")
    print("Your platform is working correctly.")
    print("\nNext steps:")
    print("  docs/getting-started-agents.md  — Steps 7-9 (RL, webhooks, DSR)")
    print("  sdk/README.md                   — Full SDK method reference")
    print("  docs/api_reference.md           — Complete REST API reference")
    print("  http://localhost:8000/docs      — Interactive Swagger UI")


if __name__ == "__main__":
    main()
