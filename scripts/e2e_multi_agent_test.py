"""End-to-end multi-agent test script.

Exercises the full API stack: auth, agent creation, risk profiles,
live trading (buy/sell), backtesting, and agent isolation verification.

Creates:
- 1 account with email/password (for UI login)
- 3 agents with distinct personalities, balances, and risk profiles
- Live trades per agent (market buys/sells)
- 1 backtest session (if historical data is available)

Usage:
    python scripts/e2e_multi_agent_test.py

Prerequisites:
    - API running at http://localhost:8000 (docker compose up)
    - Live prices flowing (Binance WS connected)
    - pip install httpx (already in project deps)
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import sys
import time
from typing import Any

import httpx

BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"

# Unique email per run
TS = int(time.time())
EMAIL = f"e2etest_{TS}@test.com"
PASSWORD = "E2eTestPass123!"  # noqa: S105
DISPLAY_NAME = f"E2E Tester {TS}"

# Agent definitions
AGENTS = [
    {
        "display_name": "Agent Alpha",
        "starting_balance": "10000",
        "color": "#FF5733",
        "llm_model": "gpt-4o",
        "framework": "langchain",
        "strategy_tags": ["scalping", "btc-focused"],
        "risk_profile": {
            "max_position_size_pct": 15,
            "daily_loss_limit_pct": 10,
            "max_open_orders": 20,
        },
    },
    {
        "display_name": "Agent Beta",
        "starting_balance": "25000",
        "color": "#33A1FF",
        "llm_model": "claude-opus-4-20250514",
        "framework": "custom",
        "strategy_tags": ["swing", "eth-bnb"],
        "risk_profile": {
            "max_position_size_pct": 25,
            "daily_loss_limit_pct": 20,
            "max_open_orders": 50,
        },
    },
    {
        "display_name": "Agent Gamma",
        "starting_balance": "50000",
        "color": "#33FF57",
        "llm_model": "gpt-4o-mini",
        "framework": "crewai",
        "strategy_tags": ["hodl", "multi-coin", "dca"],
        "risk_profile": {
            "max_position_size_pct": 40,
            "daily_loss_limit_pct": 30,
            "max_open_orders": 100,
        },
    },
]


def header(msg: str) -> None:
    """Print a section header."""
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}\n")


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def info(msg: str) -> None:
    print(f"  > {msg}")


async def api_call(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    expected: int | tuple[int, ...] = 200,
    label: str = "",
) -> dict[str, Any] | None:
    """Make an API call with error handling."""
    url = f"{API}{path}" if not path.startswith("http") else path
    if isinstance(expected, int):
        expected = (expected,)
    try:
        resp = await client.request(method, url, json=json, headers=headers, params=params)
        if resp.status_code in expected:
            ok(f"{label or path} -> {resp.status_code}")
            if resp.status_code == 204:
                return {}
            try:
                return resp.json()
            except Exception:
                return {}
        else:
            fail(f"{label or path} -> {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        fail(f"{label or path} -> Exception: {e}")
        return None


async def wait_for_api(client: httpx.AsyncClient, max_retries: int = 15) -> None:
    """Wait for the API to be ready."""
    for i in range(max_retries):
        try:
            resp = await client.get(f"{API}/health")
            # API responds (even with 401 = auth required), it's up
            if resp.status_code < 500:
                ok(f"API ready (attempt {i + 1})")
                return
        except httpx.ConnectError:
            pass
        info(f"Waiting for API... (attempt {i + 1}/{max_retries})")
        await asyncio.sleep(2)
    print("FATAL: API not reachable after retries.")
    sys.exit(1)


async def run() -> None:
    """Run the full E2E test."""
    async with httpx.AsyncClient(timeout=30.0) as client:

        # ── Step 0: Wait for API ─────────────────────────────────────
        header("Step 0: Wait for API")
        await wait_for_api(client)

        # ── Step 1: Register & Login ─────────────────────────────────
        header("Step 1: Register Account & Login")

        reg = await api_call(
            client, "POST", "/auth/register",
            json={
                "display_name": DISPLAY_NAME,
                "email": EMAIL,
                "password": PASSWORD,
                "starting_balance": "10000",
            },
            expected=(200, 201),
            label="Register account",
        )
        if not reg:
            print("FATAL: Cannot register. Is the API running at localhost:8000?")
            sys.exit(1)

        info(f"Account ID: {reg.get('account_id')}")
        info(f"Account API Key: {reg.get('api_key')}")

        login = await api_call(
            client, "POST", "/auth/user-login",
            json={"email": EMAIL, "password": PASSWORD},
            expected=(200,),
            label="User login (JWT)",
        )
        if not login:
            print("FATAL: Cannot login.")
            sys.exit(1)

        jwt_token = login["token"]
        jwt_headers = {"Authorization": f"Bearer {jwt_token}"}
        info(f"JWT token: {jwt_token[:40]}...")

        # ── Step 2: Create 3 Agents ──────────────────────────────────
        header("Step 2: Create 3 Agents")

        created_agents: list[dict[str, Any]] = []

        for agent_cfg in AGENTS:
            result = await api_call(
                client, "POST", "/agents",
                json={
                    "display_name": agent_cfg["display_name"],
                    "starting_balance": agent_cfg["starting_balance"],
                    "color": agent_cfg["color"],
                    "llm_model": agent_cfg["llm_model"],
                    "framework": agent_cfg["framework"],
                    "strategy_tags": agent_cfg["strategy_tags"],
                    "risk_profile": agent_cfg["risk_profile"],
                },
                headers=jwt_headers,
                expected=(200, 201),
                label=f"Create {agent_cfg['display_name']}",
            )
            if result:
                created_agents.append({
                    "name": agent_cfg["display_name"],
                    "id": result.get("agent_id"),
                    "api_key": result.get("api_key"),
                    "risk_profile": agent_cfg["risk_profile"],
                    "starting_balance": agent_cfg["starting_balance"],
                    "color": agent_cfg["color"],
                })
                info(f"  ID: {result.get('agent_id')}")
                info(f"  API Key: {result.get('api_key')}")
            await asyncio.sleep(0.3)

        if len(created_agents) < 3:
            print(f"WARNING: Only {len(created_agents)}/3 agents created. Continuing with what we have.")

        if not created_agents:
            print("FATAL: No agents created.")
            sys.exit(1)

        # ── Step 3: Set Risk Profiles ────────────────────────────────
        header("Step 3: Set & Verify Risk Profiles")

        for agent in created_agents:
            risk = AGENTS[[a["display_name"] for a in AGENTS].index(agent["name"])]["risk_profile"]

            # Set risk profile
            await api_call(
                client, "PUT", f"/agents/{agent['id']}/risk-profile",
                json=risk,
                headers=jwt_headers,
                label=f"Set risk profile: {agent['name']}",
            )
            await asyncio.sleep(0.2)

            # Verify risk profile
            got = await api_call(
                client, "GET", f"/agents/{agent['id']}/risk-profile",
                headers=jwt_headers,
                label=f"Verify risk profile: {agent['name']}",
            )
            if got:
                info(f"  max_position={got.get('max_position_size_pct')}%, "
                     f"daily_loss={got.get('daily_loss_limit_pct')}%, "
                     f"max_orders={got.get('max_open_orders')}")

        # ── Step 4: Trade with Each Agent ────────────────────────────
        header("Step 4: Trade with Each Agent")

        async def trade(api_key: str, symbol: str, side: str, quantity: str, label: str) -> dict | None:
            """Place a market order."""
            return await api_call(
                client, "POST", "/trade/order",
                json={"symbol": symbol, "side": side, "type": "market", "quantity": quantity},
                headers={"X-API-Key": api_key},
                expected=(200, 201),
                label=label,
            )

        # --- Agent Alpha: BTC scalper ---
        if len(created_agents) >= 1:
            alpha = created_agents[0]
            alpha_key = alpha["api_key"]
            print(f"\n  --- {alpha['name']} (BTC Scalper) ---")

            await trade(alpha_key, "BTCUSDT", "buy", "0.01", "Alpha: Buy 0.01 BTC")
            await asyncio.sleep(0.5)
            await trade(alpha_key, "BTCUSDT", "buy", "0.005", "Alpha: Buy 0.005 BTC")
            await asyncio.sleep(0.5)
            await trade(alpha_key, "BTCUSDT", "sell", "0.005", "Alpha: Sell 0.005 BTC (take profit)")
            await asyncio.sleep(0.5)

            # Check balances & positions
            bal = await api_call(
                client, "GET", "/account/balance",
                headers={"X-API-Key": alpha_key},
                label="Alpha: Check balance",
            )
            if bal:
                for b in bal.get("balances", []):
                    if b.get("total") and float(b["total"]) > 0:
                        info(f"  {b['asset']}: available={b['available']}, locked={b['locked']}")

            pos = await api_call(
                client, "GET", "/account/positions",
                headers={"X-API-Key": alpha_key},
                label="Alpha: Check positions",
            )
            if pos:
                info(f"  Positions: {len(pos.get('positions', []))}")

            hist = await api_call(
                client, "GET", "/trade/history",
                headers={"X-API-Key": alpha_key},
                label="Alpha: Trade history",
            )
            if hist:
                info(f"  Trades: {hist.get('total', len(hist.get('trades', [])))}")

        # --- Agent Beta: ETH/BNB swing ---
        if len(created_agents) >= 2:
            beta = created_agents[1]
            beta_key = beta["api_key"]
            print(f"\n  --- {beta['name']} (ETH/BNB Swing) ---")

            await trade(beta_key, "ETHUSDT", "buy", "0.5", "Beta: Buy 0.5 ETH")
            await asyncio.sleep(0.5)
            await trade(beta_key, "BNBUSDT", "buy", "1.0", "Beta: Buy 1.0 BNB")
            await asyncio.sleep(0.5)
            await trade(beta_key, "ETHUSDT", "sell", "0.25", "Beta: Sell 0.25 ETH (partial)")
            await asyncio.sleep(0.5)

            # Place a limit order (below market) then cancel it
            # Place limit buy at a low price that won't fill
            limit_result = await api_call(
                client, "POST", "/trade/order",
                json={
                    "symbol": "ETHUSDT",
                    "side": "buy",
                    "type": "limit",
                    "quantity": "0.5",
                    "price": "100.00",  # Very low price, won't fill
                },
                headers={"X-API-Key": beta_key},
                expected=(200, 201),
                label="Beta: Limit buy 0.5 ETH @$100",
            )

            if limit_result and limit_result.get("order_id"):
                await asyncio.sleep(0.3)
                # Check open orders
                open_orders = await api_call(
                    client, "GET", "/trade/orders/open",
                    headers={"X-API-Key": beta_key},
                    label="Beta: Check open orders",
                )
                if open_orders:
                    info(f"  Open orders: {open_orders.get('total', len(open_orders.get('orders', [])))}")

                # Cancel it
                await api_call(
                    client, "DELETE", f"/trade/order/{limit_result['order_id']}",
                    headers={"X-API-Key": beta_key},
                    label="Beta: Cancel limit order",
                )

            bal = await api_call(
                client, "GET", "/account/balance",
                headers={"X-API-Key": beta_key},
                label="Beta: Check balance",
            )
            if bal:
                for b in bal.get("balances", []):
                    if b.get("total") and float(b["total"]) > 0:
                        info(f"  {b['asset']}: available={b['available']}")

            portfolio = await api_call(
                client, "GET", "/account/portfolio",
                headers={"X-API-Key": beta_key},
                label="Beta: Portfolio",
            )
            if portfolio:
                info(f"  Equity: {portfolio.get('total_equity')}, PnL: {portfolio.get('total_pnl')}")

        # --- Agent Gamma: Multi-coin HODL ---
        if len(created_agents) >= 3:
            gamma = created_agents[2]
            gamma_key = gamma["api_key"]
            print(f"\n  --- {gamma['name']} (Multi-Coin HODL) ---")

            await trade(gamma_key, "BTCUSDT", "buy", "0.1", "Gamma: Buy 0.1 BTC")
            await asyncio.sleep(0.5)
            await trade(gamma_key, "ETHUSDT", "buy", "1.0", "Gamma: Buy 1.0 ETH")
            await asyncio.sleep(0.5)
            await trade(gamma_key, "SOLUSDT", "buy", "5.0", "Gamma: Buy 5.0 SOL")
            await asyncio.sleep(0.5)
            await trade(gamma_key, "ADAUSDT", "buy", "50", "Gamma: Buy 50 ADA")
            await asyncio.sleep(0.5)

            pos = await api_call(
                client, "GET", "/account/positions",
                headers={"X-API-Key": gamma_key},
                label="Gamma: Check positions",
            )
            if pos:
                info(f"  Positions: {len(pos.get('positions', []))}")
                for p in pos.get("positions", []):
                    info(f"    {p['symbol']}: qty={p['quantity']}, value={p.get('market_value', '?')}")

            portfolio = await api_call(
                client, "GET", "/account/portfolio",
                headers={"X-API-Key": gamma_key},
                label="Gamma: Portfolio",
            )
            if portfolio:
                info(f"  Equity: {portfolio.get('total_equity')}, Positions: {len(portfolio.get('positions', []))}")

        # ── Step 5: Verify Agent Isolation ────────────────────────────
        header("Step 5: Verify Agent Isolation")

        # Collect per-agent metrics for comparison
        isolation_data: list[dict[str, Any]] = []

        for agent in created_agents:
            key = agent["api_key"]
            print(f"\n  --- {agent['name']} ---")
            agent_metrics: dict[str, Any] = {"name": agent["name"]}

            acct_info = await api_call(
                client, "GET", "/account/info",
                headers={"X-API-Key": key},
                label=f"{agent['name']}: Account info",
            )
            if acct_info:
                rp = acct_info.get("risk_profile", {})
                agent_metrics["risk_profile"] = rp
                info(f"  Risk: pos={rp.get('max_position_size_pct')}%, "
                     f"loss={rp.get('daily_loss_limit_pct')}%, "
                     f"orders={rp.get('max_open_orders')}")

            bal = await api_call(
                client, "GET", "/account/balance",
                headers={"X-API-Key": key},
                label=f"{agent['name']}: Balance",
            )
            if bal:
                equity = bal.get("total_equity_usdt", "?")
                agent_metrics["equity"] = equity
                info(f"  Total equity: {equity}")
                for b in bal.get("balances", []):
                    if b.get("total") and float(b["total"]) > 0:
                        info(f"    {b['asset']}: {b['available']}")

            pos = await api_call(
                client, "GET", "/account/positions",
                headers={"X-API-Key": key},
                label=f"{agent['name']}: Positions",
            )
            if pos:
                positions = pos.get("positions", [])
                agent_metrics["position_count"] = len(positions)
                info(f"  Position count: {len(positions)}")
                for p in positions:
                    info(f"    {p['symbol']}: qty={p['quantity']}")

            hist = await api_call(
                client, "GET", "/trade/history",
                headers={"X-API-Key": key},
                label=f"{agent['name']}: Trade history",
            )
            if hist:
                trade_count = hist.get("total", len(hist.get("trades", [])))
                agent_metrics["trade_count"] = trade_count
                info(f"  Trade count: {trade_count}")

            isolation_data.append(agent_metrics)

        # ── Isolation Check ───────────────────────────────────────────
        print("\n  --- Isolation Verification ---")
        trade_counts = [d.get("trade_count", 0) for d in isolation_data]
        position_counts = [d.get("position_count", 0) for d in isolation_data]
        equities = [d.get("equity", "?") for d in isolation_data]

        info(f"Trade counts:    {[f'{d['name']}={d.get('trade_count', '?')}' for d in isolation_data]}")
        info(f"Position counts: {[f'{d['name']}={d.get('position_count', '?')}' for d in isolation_data]}")
        info(f"Equities:        {[f'{d['name']}={d.get('equity', '?')}' for d in isolation_data]}")

        if len(set(trade_counts)) > 1:
            ok("Trade counts differ across agents (isolation working)")
        else:
            fail(f"All agents have same trade count: {trade_counts[0]} (isolation may be broken)")

        if len(set(position_counts)) > 1:
            ok("Position counts differ across agents (isolation working)")
        else:
            fail(f"All agents have same position count: {position_counts[0]} (isolation may be broken)")

        if len(set(str(e) for e in equities)) > 1:
            ok("Equity values differ across agents (isolation working)")
        else:
            fail(f"All agents have same equity: {equities[0]} (isolation may be broken)")

        # ── Step 6: Run Backtest (Agent Alpha) ────────────────────────
        header("Step 6: Run Backtest")

        # Check data range
        data_range = await api_call(
            client, "GET", "/market/data-range",
            headers=jwt_headers,
            label="Check data range",
        )

        backtest_ok = False
        if data_range and data_range.get("earliest") and data_range.get("latest"):
            earliest = data_range["earliest"]
            latest = data_range["latest"]
            total_pairs = data_range.get("total_pairs", 0)
            info(f"Data range: {earliest} to {latest} ({total_pairs} pairs)")

            # Use a 1-day window ending 1 hour before latest
            try:
                latest_dt = datetime.fromisoformat(latest.replace("Z", "+00:00"))
                end_time = latest_dt - timedelta(hours=1)
                start_time = end_time - timedelta(days=1)

                # Create backtest
                bt_create = await api_call(
                    client, "POST", "/backtest/create",
                    json={
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                        "starting_balance": "10000",
                        "candle_interval": 300,  # 5-minute candles
                        "pairs": ["BTCUSDT", "ETHUSDT"],
                        "strategy_label": "e2e_alpha_test",
                    },
                    headers=jwt_headers,
                    label="Create backtest",
                )

                if bt_create and bt_create.get("session_id"):
                    session_id = bt_create["session_id"]
                    info(f"Session: {session_id}")
                    info(f"Total steps: {bt_create.get('total_steps')}")

                    # Start backtest
                    started = await api_call(
                        client, "POST", f"/backtest/{session_id}/start",
                        headers=jwt_headers,
                        label="Start backtest",
                    )

                    if started:
                        # Trading loop: step → buy → step → sell (3 rounds)
                        for round_num in range(1, 4):
                            info(f"  Round {round_num}/3...")

                            # Step forward 50 candles
                            step_result = await api_call(
                                client, "POST", f"/backtest/{session_id}/step/batch",
                                json={"steps": 50},
                                headers=jwt_headers,
                                label=f"  Step 50 (round {round_num}a)",
                            )

                            if not step_result:
                                info("  Stepping failed, stopping backtest loop.")
                                break

                            if step_result.get("is_complete"):
                                info("  Backtest completed early.")
                                break

                            # Buy BTC
                            await api_call(
                                client, "POST", f"/backtest/{session_id}/trade/order",
                                json={"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.01"},
                                headers=jwt_headers,
                                label=f"  BT Buy 0.01 BTC (round {round_num})",
                            )

                            # Step forward 50 more candles
                            step_result = await api_call(
                                client, "POST", f"/backtest/{session_id}/step/batch",
                                json={"steps": 50},
                                headers=jwt_headers,
                                label=f"  Step 50 (round {round_num}b)",
                            )

                            if not step_result:
                                break

                            if step_result.get("is_complete"):
                                info("  Backtest completed early.")
                                break

                            # Sell BTC
                            await api_call(
                                client, "POST", f"/backtest/{session_id}/trade/order",
                                json={"symbol": "BTCUSDT", "side": "sell", "type": "market", "quantity": "0.01"},
                                headers=jwt_headers,
                                label=f"  BT Sell 0.01 BTC (round {round_num})",
                            )

                        # Get results
                        await asyncio.sleep(0.5)

                        # Check status first
                        status = await api_call(
                            client, "GET", f"/backtest/{session_id}/status",
                            headers=jwt_headers,
                            label="Backtest status",
                        )
                        if status:
                            info(f"  Status: {status.get('status')}, Progress: {status.get('progress_pct')}%")

                        # If still running, cancel it to get results
                        if status and status.get("status") == "running":
                            await api_call(
                                client, "POST", f"/backtest/{session_id}/cancel",
                                headers=jwt_headers,
                                label="Cancel backtest (to finalize)",
                            )
                            await asyncio.sleep(0.5)

                        results = await api_call(
                            client, "GET", f"/backtest/{session_id}/results",
                            headers=jwt_headers,
                            label="Get backtest results",
                        )
                        if results:
                            metrics = results.get("metrics", {})
                            info(f"  Final equity: {metrics.get('final_equity')}")
                            info(f"  ROI: {metrics.get('roi_pct')}%")
                            info(f"  Sharpe: {metrics.get('sharpe_ratio')}")
                            info(f"  Max drawdown: {metrics.get('max_drawdown_pct')}%")
                            backtest_ok = True

                        # Equity curve
                        curve = await api_call(
                            client, "GET", f"/backtest/{session_id}/results/equity-curve",
                            headers=jwt_headers,
                            label="Get equity curve",
                        )
                        if curve:
                            points = curve.get("data_points", curve.get("snapshots", []))
                            info(f"  Equity curve: {len(points)} data points")

                        # Trade log
                        bt_trades = await api_call(
                            client, "GET", f"/backtest/{session_id}/results/trades",
                            headers=jwt_headers,
                            label="Get backtest trades",
                        )
                        if bt_trades:
                            trades_list = bt_trades.get("trades", [])
                            info(f"  Backtest trades: {len(trades_list)}")

            except Exception as e:
                fail(f"Backtest error: {e}")
        else:
            info("No historical data available — skipping backtest.")

        # ── Step 7: Print Summary ─────────────────────────────────────
        header("SUMMARY")

        print("  Login Credentials:")
        print(f"    Email:    {EMAIL}")
        print(f"    Password: {PASSWORD}")
        print()

        print("  Agents:")
        for agent in created_agents:
            print(f"    {agent['name']} ({agent['color']})")
            print(f"      ID:       {agent['id']}")
            print(f"      API Key:  {agent['api_key']}")
            print(f"      Balance:  ${agent['starting_balance']} USDT")
            rp = agent["risk_profile"]
            print(f"      Risk:     pos={rp['max_position_size_pct']}%, "
                  f"loss={rp['daily_loss_limit_pct']}%, "
                  f"orders={rp['max_open_orders']}")
            print()

        if backtest_ok:
            print(f"  Backtest: Session {session_id}")
        else:
            print("  Backtest: Skipped or failed (no historical data)")

        print()
        print("  Next Steps:")
        print("    1. Open http://localhost:3000 in your browser")
        print(f"    2. Login with {EMAIL} / {PASSWORD}")
        print("    3. Switch between agents in the sidebar")
        print("    4. Check each agent's different balances, trades, positions")
        print("    5. Check Settings -> each agent has its own risk profile")
        if backtest_ok:
            print("    6. Check Backtest page -> see completed backtest results")
        print()
        print("  Done!")


if __name__ == "__main__":
    asyncio.run(run())
