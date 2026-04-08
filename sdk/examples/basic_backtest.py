"""Basic backtest example using the AgentExchange SDK.

Demonstrates the core backtesting workflow:
  1. Create a backtest session for a 30-day date range on BTCUSDT
  2. Advance the simulation in fast-batch steps of 500 candles at a time
  3. Place a simple buy order when the session first starts
  4. Retrieve and print the final performance metrics

Requirements:
    pip install -e sdk/
    export TRADEREADY_API_URL=http://localhost:8000
    export TRADEREADY_API_KEY=ak_live_YOUR_KEY
    export TRADEREADY_API_SECRET=sk_live_YOUR_SECRET

Run:
    python sdk/examples/basic_backtest.py
"""

from __future__ import annotations

import os
import sys
import time
from decimal import Decimal

from agentexchange import AgentExchangeClient
from agentexchange.exceptions import AgentExchangeError, NotFoundError

# ---------------------------------------------------------------------------
# Configuration from environment variables
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("TRADEREADY_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("TRADEREADY_API_KEY", "")
API_SECRET = os.environ.get("TRADEREADY_API_SECRET", "")

BACKTEST_START = "2025-01-01T00:00:00Z"
BACKTEST_END = "2025-01-31T23:59:00Z"
STARTING_BALANCE = Decimal("10000")
SYMBOL = "BTCUSDT"
BATCH_SIZE = 500  # candles per batch step


def _require_env() -> None:
    """Verify required environment variables are set before proceeding."""
    missing = [v for v in ("TRADEREADY_API_KEY", "TRADEREADY_API_SECRET") if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Missing environment variable(s): {', '.join(missing)}")
        sys.exit(1)


def create_session(client: AgentExchangeClient) -> str:
    """Create a new backtest session and return its session ID.

    Args:
        client: Authenticated SDK client.

    Returns:
        Session ID string for the new backtest.
    """
    print(f"Creating backtest session: {BACKTEST_START} -> {BACKTEST_END}")
    response = client._request(
        "POST",
        "/api/v1/backtest/create",
        json={
            "start_time": BACKTEST_START,
            "end_time": BACKTEST_END,
            "starting_balance": str(STARTING_BALANCE),
            "candle_interval": 60,  # 1-minute candles
            "pairs": [SYMBOL],
            "strategy_label": "sdk_example_basic",
        },
    )
    session_id: str = response["session_id"]
    print(f"Session created: {session_id}")
    return session_id


def start_session(client: AgentExchangeClient, session_id: str) -> None:
    """Start the backtest session so it is ready to step.

    Args:
        client:     Authenticated SDK client.
        session_id: Session ID returned by create_session().
    """
    client._request("POST", f"/api/v1/backtest/{session_id}/start")
    print("Session started.")


def place_initial_order(client: AgentExchangeClient, session_id: str) -> None:
    """Place a small buy order at the beginning of the backtest.

    Args:
        client:     Authenticated SDK client.
        session_id: Active backtest session ID.
    """
    print(f"Placing initial buy order on {SYMBOL}...")
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
        print(f"  Order placed: id={order.get('order_id')}, status={order.get('status')}")
    except AgentExchangeError as exc:
        # Insufficient balance or bad symbol — log and continue
        print(f"  Warning: could not place order: {exc}")


def run_backtest_loop(client: AgentExchangeClient, session_id: str) -> dict:
    """Advance the backtest using fast-batch steps until completion.

    Prints progress after each batch and returns the final step response.

    Args:
        client:     Authenticated SDK client.
        session_id: Active backtest session ID.

    Returns:
        The last batch step response dict.
    """
    print(f"\nRunning backtest in batches of {BATCH_SIZE} steps...")
    result: dict = {}
    t0 = time.monotonic()

    while True:
        result = client.batch_step_fast(session_id, steps=BATCH_SIZE)

        progress = result.get("progress_pct", 0.0)
        step = result.get("step", 0)
        total = result.get("total_steps", 0)
        virtual_time = result.get("virtual_time", "")
        fills = len(result.get("orders_filled", []))

        print(
            f"  Step {step:>6}/{total}  ({progress:5.1f}%)  "
            f"virtual_time={virtual_time[:19]}  fills={fills}"
        )

        if result.get("is_complete"):
            break

    elapsed = time.monotonic() - t0
    print(f"\nBacktest complete in {elapsed:.1f}s.")
    return result


def print_results(client: AgentExchangeClient, session_id: str) -> None:
    """Fetch and display the final backtest results.

    Args:
        client:     Authenticated SDK client.
        session_id: Completed backtest session ID.
    """
    try:
        results = client._request("GET", f"/api/v1/backtest/{session_id}/results")
    except NotFoundError:
        print("Results not yet available (session may still be finalising).")
        return

    metrics = results.get("metrics") or {}
    print("\n--- Backtest Results ---")
    print(f"  Total Return    : {metrics.get('total_return_pct', 'n/a')}%")
    print(f"  Sharpe Ratio    : {metrics.get('sharpe_ratio', 'n/a')}")
    print(f"  Max Drawdown    : {metrics.get('max_drawdown_pct', 'n/a')}%")
    print(f"  Win Rate        : {metrics.get('win_rate', 'n/a')}%")
    print(f"  Total Trades    : {metrics.get('total_trades', 'n/a')}")
    print(f"  Final Equity    : {results.get('final_equity', 'n/a')} USDT")


def main() -> None:
    """Run the basic backtest workflow end-to-end."""
    _require_env()

    with AgentExchangeClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        base_url=BASE_URL,
    ) as client:
        # Step 1 — Create a backtest session
        session_id = create_session(client)

        # Step 2 — Start the session so it is ready to accept steps
        start_session(client, session_id)

        # Step 3 — Place an initial buy to give the backtest something to do
        place_initial_order(client, session_id)

        # Step 4 — Advance through the entire date range in fast batches
        run_backtest_loop(client, session_id)

        # Step 5 — Print the final performance metrics
        print_results(client, session_id)


if __name__ == "__main__":
    main()
