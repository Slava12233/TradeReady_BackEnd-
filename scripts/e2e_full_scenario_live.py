"""Full E2E scenario against a LIVE backend -- everything visible in the UI.

Mirrors the 8 phases from test_real_user_scenario_e2e.py but hits the real API,
so all data persists in the database and shows up in the frontend.

Creates:
- 1 account with email/password (for UI login)
- 3 agents (AlphaBot, BetaBot, GammaBot)
- 25 trades across all agents (market buy/sell across multiple symbols)
- Backtests per agent (if historical data available)
- 1 historical battle with all 3 agents (if historical data available)
- Verifies analytics, portfolio, positions, PnL

Usage:
    python scripts/e2e_full_scenario_live.py

    # Use fixed credentials (reusable across runs):
    python scripts/e2e_full_scenario_live.py --email e2e_trader@agentexchange.io

    # Skip backtests/battles (just account + agents + trades):
    python scripts/e2e_full_scenario_live.py --skip-backtest --skip-battle

Prerequisites:
    - API running at http://localhost:8000 (docker compose up)
    - Live prices flowing (Binance WS connected)
    - For backtests/battles: historical candle data in DB
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime, timedelta
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"

DEFAULT_EMAIL = "e2e_trader@agentexchange.io"
DEFAULT_PASSWORD = "Tr@d1ng_S3cur3_2026!"  # noqa: S105
DEFAULT_DISPLAY_NAME = "E2E_RealUser_Trader"

AGENTS = [
    {
        "display_name": "AlphaBot",
        "starting_balance": "10000",
        "color": "#FF5733",
        "llm_model": "claude-opus-4",
        "framework": "custom",
        "strategy_tags": ["momentum", "breakout"],
        "risk_profile": {"max_position_size_pct": 25, "daily_loss_limit_pct": 20, "max_open_orders": 50},
    },
    {
        "display_name": "BetaBot",
        "starting_balance": "10000",
        "color": "#33A1FF",
        "llm_model": "gpt-4o",
        "framework": "langchain",
        "strategy_tags": ["mean-reversion", "eth-focused"],
        "risk_profile": {"max_position_size_pct": 30, "daily_loss_limit_pct": 25, "max_open_orders": 40},
    },
    {
        "display_name": "GammaBot",
        "starting_balance": "10000",
        "color": "#33FF57",
        "llm_model": "claude-sonnet-4",
        "framework": "custom",
        "strategy_tags": ["scalping", "multi-coin"],
        "risk_profile": {"max_position_size_pct": 20, "daily_loss_limit_pct": 15, "max_open_orders": 30},
    },
]

# Trades per agent (symbol, side, quantity)
ALPHA_TRADES = [
    ("BTCUSDT", "buy", "0.01"), ("ETHUSDT", "buy", "0.5"), ("SOLUSDT", "buy", "5"),
    ("BTCUSDT", "buy", "0.005"), ("XRPUSDT", "buy", "500"), ("DOGEUSDT", "buy", "5000"),
    ("ETHUSDT", "sell", "0.2"), ("BTCUSDT", "sell", "0.005"), ("SOLUSDT", "buy", "3"),
    ("XRPUSDT", "sell", "200"),
]
BETA_TRADES = [
    ("ETHUSDT", "buy", "1.0"), ("BTCUSDT", "buy", "0.02"), ("DOGEUSDT", "buy", "10000"),
    ("SOLUSDT", "buy", "10"), ("ETHUSDT", "sell", "0.3"), ("BTCUSDT", "sell", "0.01"),
    ("XRPUSDT", "buy", "1000"), ("DOGEUSDT", "sell", "5000"),
]
GAMMA_TRADES = [
    ("BTCUSDT", "buy", "0.02"), ("SOLUSDT", "buy", "20"), ("ETHUSDT", "buy", "1.0"),
    ("XRPUSDT", "buy", "2000"), ("BTCUSDT", "sell", "0.01"), ("SOLUSDT", "sell", "10"),
    ("ETHUSDT", "sell", "0.5"),
]

ALL_AGENT_TRADES = [ALPHA_TRADES, BETA_TRADES, GAMMA_TRADES]

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

passed = 0
failed = 0
skipped = 0


def header(msg: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {msg}")
    print(f"{'=' * 70}\n")


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  [PASS] {msg}")


def fail(msg: str) -> None:
    global failed
    failed += 1
    print(f"  [FAIL] {msg}")


def skip(msg: str) -> None:
    global skipped
    skipped += 1
    print(f"  [SKIP] {msg}")


def info(msg: str) -> None:
    print(f"       > {msg}")


# ---------------------------------------------------------------------------
# API helper
# ---------------------------------------------------------------------------


async def api(
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
    url = f"{API}{path}" if not path.startswith("http") else path
    if isinstance(expected, int):
        expected = (expected,)
    try:
        resp = await client.request(method, url, json=json, headers=headers, params=params)
        if resp.status_code in expected:
            ok(f"{label or path} -> {resp.status_code}")
            try:
                return resp.json()
            except Exception:
                return {}
        else:
            fail(f"{label or path} -> {resp.status_code}: {resp.text[:300]}")
            return None
    except Exception as e:
        fail(f"{label or path} -> {e}")
        return None


# ---------------------------------------------------------------------------
# Main scenario
# ---------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> None:
    email = args.email or DEFAULT_EMAIL
    password = args.password or DEFAULT_PASSWORD
    display_name = args.display_name or DEFAULT_DISPLAY_NAME

    async with httpx.AsyncClient(timeout=30.0) as client:

        # ==================================================================
        # PHASE 0: Wait for API
        # ==================================================================
        header("PHASE 0: Connecting to API")
        for attempt in range(10):
            try:
                r = await client.get(f"{BASE_URL}/health")
                if r.status_code < 500:
                    ok(f"API reachable (attempt {attempt + 1})")
                    break
            except httpx.ConnectError:
                pass
            info(f"Waiting... (attempt {attempt + 1}/10)")
            await asyncio.sleep(2)
        else:
            fail("API not reachable at " + BASE_URL)
            print("\nMake sure 'docker compose up' is running.")
            sys.exit(1)

        # ==================================================================
        # PHASE 1: Register & Login
        # ==================================================================
        header("PHASE 1: Account Registration & Authentication")

        reg = await api(
            client, "POST", "/auth/register",
            json={"display_name": display_name, "email": email, "password": password, "starting_balance": "10000"},
            expected=(200, 201),
            label="Register account",
        )
        if not reg:
            # Maybe account already exists -- try logging in directly
            info("Registration failed (account may already exist). Trying login...")

        login = await api(
            client, "POST", "/auth/user-login",
            json={"email": email, "password": password},
            label="Login with email/password",
        )
        if not login:
            fail("Cannot login. Aborting.")
            sys.exit(1)

        jwt = login["token"]
        jwt_h = {"Authorization": f"Bearer {jwt}"}
        info(f"JWT: {jwt[:50]}...")

        # Also test API key login if we just registered
        if reg:
            api_key = reg["api_key"]
            api_secret = reg["api_secret"]
            info(f"Account ID: {reg['account_id']}")
            info(f"API Key: {api_key}")
            info(f"API Secret: {api_secret[:20]}... (SAVE THIS)")

            key_login = await api(
                client, "POST", "/auth/login",
                json={"api_key": api_key, "api_secret": api_secret},
                label="Login with API key/secret",
            )

        # Account info
        await api(client, "GET", "/account/info", headers=jwt_h, label="Get account info")

        # Initial balance
        bal = await api(client, "GET", "/account/balance", headers=jwt_h, label="Get initial balance")
        if bal:
            for b in bal.get("balances", []):
                if float(b.get("total", 0)) > 0:
                    info(f"{b['asset']}: {b['available']} available, {b['locked']} locked")

        # ==================================================================
        # PHASE 2: Create 3 Agents
        # ==================================================================
        header("PHASE 2: Create 3 Agents")

        created_agents: list[dict[str, Any]] = []

        # Check if agents already exist
        existing = await api(client, "GET", "/agents", headers=jwt_h, label="Check existing agents")
        existing_names = set()
        if existing:
            for a in existing.get("agents", []):
                existing_names.add(a["display_name"])
                info(f"Already exists: {a['display_name']} (id={a['id']})")

        for agent_cfg in AGENTS:
            name = agent_cfg["display_name"]
            if name in existing_names:
                # Find the existing agent
                for a in existing.get("agents", []):
                    if a["display_name"] == name:
                        created_agents.append({
                            "name": name,
                            "id": a["id"],
                            "api_key": None,  # We don't have it anymore
                            "color": agent_cfg["color"],
                        })
                        skip(f"{name} already exists (id={a['id']})")
                        break
                continue

            result = await api(
                client, "POST", "/agents",
                json=agent_cfg,
                headers=jwt_h,
                expected=(200, 201),
                label=f"Create {name}",
            )
            if result:
                created_agents.append({
                    "name": name,
                    "id": result["agent_id"],
                    "api_key": result.get("api_key"),
                    "color": agent_cfg["color"],
                })
                info(f"  ID: {result['agent_id']}")
                info(f"  API Key: {result.get('api_key', 'N/A')}")
            await asyncio.sleep(0.3)

        if len(created_agents) < 3:
            info(f"WARNING: Only {len(created_agents)}/3 agents available.")

        # List and overview
        await api(client, "GET", "/agents", headers=jwt_h, label="List all agents")
        overview = await api(client, "GET", "/agents/overview", headers=jwt_h, label="Agent overview")
        if overview:
            for a in overview.get("agents", []):
                info(f"  {a.get('display_name')}: equity={a.get('current_equity', '?')}, roi={a.get('roi_pct', '?')}%")

        # Get detail for first agent
        if created_agents:
            await api(client, "GET", f"/agents/{created_agents[0]['id']}", headers=jwt_h,
                      label=f"Get {created_agents[0]['name']} detail")

        # ==================================================================
        # PHASE 3: Trading (25 trades across all agents)
        # ==================================================================
        header("PHASE 3: Trading")

        for agent, trades in zip(created_agents, ALL_AGENT_TRADES):
            agent_name = agent["name"]
            agent_key = agent.get("api_key")

            if not agent_key:
                skip(f"{agent_name}: No API key (agent existed before this run)")
                continue

            trade_headers = {"X-API-Key": agent_key}
            print(f"\n  --- {agent_name}: {len(trades)} trades ---")

            for i, (symbol, side, qty) in enumerate(trades):
                result = await api(
                    client, "POST", "/trade/order",
                    json={"symbol": symbol, "side": side, "type": "market", "quantity": qty},
                    headers=trade_headers,
                    expected=(200, 201),
                    label=f"{agent_name} #{i+1}: {side} {qty} {symbol}",
                )
                if result:
                    info(f"  Status: {result.get('status')}, Price: {result.get('executed_price', 'N/A')}")
                await asyncio.sleep(0.3)

        # Limit order test (BetaBot)
        if len(created_agents) >= 2 and created_agents[1].get("api_key"):
            beta_key = created_agents[1]["api_key"]
            beta_h = {"X-API-Key": beta_key}
            print(f"\n  --- Limit order test (BetaBot) ---")

            limit = await api(
                client, "POST", "/trade/order",
                json={"symbol": "BTCUSDT", "side": "buy", "type": "limit", "quantity": "0.001", "price": "10000.00"},
                headers=beta_h,
                expected=(200, 201),
                label="BetaBot: Limit buy BTC @$10,000 (won't fill)",
            )

            if limit and limit.get("order_id"):
                await api(client, "GET", "/trade/orders/open", headers=beta_h, label="BetaBot: Open orders")
                await api(client, "DELETE", f"/trade/order/{limit['order_id']}", headers=beta_h,
                          label="BetaBot: Cancel limit order")

        # Trade history
        for agent in created_agents:
            if agent.get("api_key"):
                h = await api(client, "GET", "/trade/history", headers={"X-API-Key": agent["api_key"]},
                              label=f"{agent['name']}: Trade history")
                if h:
                    info(f"  Total trades: {h.get('total', len(h.get('trades', [])))}")

        # ==================================================================
        # PHASE 4: Portfolio & Positions
        # ==================================================================
        header("PHASE 4: Portfolio, Positions, PnL")

        for agent in created_agents:
            if not agent.get("api_key"):
                continue

            agent_h = {"X-API-Key": agent["api_key"]}
            print(f"\n  --- {agent['name']} ---")

            bal = await api(client, "GET", "/account/balance", headers=agent_h,
                            label=f"{agent['name']}: Balance")
            if bal:
                info(f"  Equity: {bal.get('total_equity_usdt', '?')}")
                for b in bal.get("balances", []):
                    if float(b.get("total", 0)) > 0:
                        info(f"  {b['asset']}: avail={b['available']}, locked={b['locked']}")

            pos = await api(client, "GET", "/account/positions", headers=agent_h,
                            label=f"{agent['name']}: Positions")
            if pos:
                for p in pos.get("positions", []):
                    info(f"  {p['symbol']}: qty={p['quantity']}, value={p.get('market_value', '?')}, "
                         f"pnl={p.get('unrealized_pnl', '?')}")

            await api(client, "GET", "/account/portfolio", headers=agent_h,
                      label=f"{agent['name']}: Portfolio")

            pnl = await api(client, "GET", "/account/pnl", headers=agent_h, params={"period": "all"},
                            label=f"{agent['name']}: PnL")
            if pnl:
                info(f"  Realized: {pnl.get('realized_pnl')}, Unrealized: {pnl.get('unrealized_pnl')}, "
                     f"Win rate: {pnl.get('win_rate')}%")

        # ==================================================================
        # PHASE 5: Backtesting
        # ==================================================================
        if args.skip_backtest:
            header("PHASE 5: Backtesting (SKIPPED)")
            skip("Backtesting skipped via --skip-backtest flag")
        else:
            header("PHASE 5: Backtesting")

            # Check data availability
            data_range = await api(client, "GET", "/market/data-range", headers=jwt_h,
                                   label="Check historical data range")

            has_data = False
            bt_start = bt_end = None
            if data_range and data_range.get("earliest") and data_range.get("latest"):
                total_pairs = data_range.get("total_pairs", 0)
                info(f"Data: {data_range['earliest']} to {data_range['latest']} ({total_pairs} pairs)")
                if total_pairs > 0:
                    has_data = True
                    latest_dt = datetime.fromisoformat(data_range["latest"].replace("Z", "+00:00"))
                    bt_end = latest_dt - timedelta(hours=1)
                    bt_start = bt_end - timedelta(days=1)

            if not has_data:
                skip("No historical data available -- skipping backtests")
                info("Run 'python scripts/backfill_history.py --daily --resume' to populate data")
            else:
                backtest_configs = [
                    ("AlphaBot", "alpha_momentum", created_agents[0]["id"], ["BTCUSDT", "ETHUSDT"]),
                    ("AlphaBot", "alpha_trend", created_agents[0]["id"], ["BTCUSDT", "SOLUSDT"]),
                    ("BetaBot", "beta_mean_rev", created_agents[1]["id"], ["ETHUSDT", "XRPUSDT"]),
                    ("BetaBot", "beta_arb", created_agents[1]["id"], ["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
                    ("GammaBot", "gamma_scalp", created_agents[2]["id"], ["BTCUSDT", "SOLUSDT"]),
                    ("GammaBot", "gamma_momentum", created_agents[2]["id"], ["BTCUSDT", "ETHUSDT"]),
                ]

                for agent_name, strategy, agent_id, pairs in backtest_configs:
                    print(f"\n  --- {agent_name}: {strategy} ---")

                    bt = await api(
                        client, "POST", "/backtest/create",
                        json={
                            "start_time": bt_start.isoformat(),
                            "end_time": bt_end.isoformat(),
                            "starting_balance": "10000",
                            "candle_interval": 300,
                            "pairs": pairs,
                            "strategy_label": strategy,
                            "agent_id": str(agent_id),
                        },
                        headers=jwt_h,
                        label=f"Create backtest: {strategy}",
                    )
                    if not bt or not bt.get("session_id"):
                        continue

                    sid = bt["session_id"]
                    info(f"Session: {sid}, Steps: {bt.get('total_steps')}")

                    # Start
                    started = await api(client, "POST", f"/backtest/{sid}/start", headers=jwt_h,
                                        label=f"Start {strategy}")
                    if not started:
                        continue

                    # Step forward, place a trade, step more
                    step = await api(client, "POST", f"/backtest/{sid}/step", headers=jwt_h,
                                     label=f"Step 1: {strategy}")

                    # Place a buy in the sandbox
                    await api(client, "POST", f"/backtest/{sid}/trade/order",
                              json={"symbol": pairs[0], "side": "buy", "type": "market", "quantity": "0.01"},
                              headers=jwt_h, label=f"BT Buy {pairs[0]}")

                    # Batch step to complete
                    total_steps = bt.get("total_steps", 1000)
                    batch = await api(client, "POST", f"/backtest/{sid}/step/batch",
                                      json={"steps": min(total_steps, 5000)},
                                      headers=jwt_h, label=f"Batch step: {strategy}")

                    if batch and not batch.get("is_complete"):
                        # Cancel to finalize
                        await api(client, "POST", f"/backtest/{sid}/cancel", headers=jwt_h,
                                  label=f"Cancel (finalize): {strategy}")

                    await asyncio.sleep(0.3)

                    # Results
                    results = await api(client, "GET", f"/backtest/{sid}/results", headers=jwt_h,
                                        label=f"Results: {strategy}")
                    if results:
                        m = results.get("metrics", results.get("summary", {}))
                        info(f"  Equity: {m.get('final_equity')}, ROI: {m.get('roi_pct')}%, "
                             f"Sharpe: {m.get('sharpe_ratio')}")

                # List all backtests
                await api(client, "GET", "/backtest/list", headers=jwt_h, label="List all backtests")

        # ==================================================================
        # PHASE 6: Battles
        # ==================================================================
        if args.skip_battle:
            header("PHASE 6: Battles (SKIPPED)")
            skip("Battles skipped via --skip-battle flag")
        elif len(created_agents) < 2:
            header("PHASE 6: Battles (SKIPPED)")
            skip("Need at least 2 agents for a battle")
        else:
            header("PHASE 6: Battles")

            # Presets
            presets = await api(client, "GET", "/battles/presets", headers=jwt_h, label="Get battle presets")

            # Determine battle mode
            battle_mode = "live"
            battle_body: dict[str, Any] = {
                "name": "E2E Agent Championship",
                "ranking_metric": "roi_pct",
                "battle_mode": battle_mode,
                "config": {"duration_minutes": 5, "starting_balance": "10000"},
            }

            # If we have historical data, use historical mode
            if has_data and bt_start and bt_end:
                battle_mode = "historical"
                battle_body["battle_mode"] = "historical"
                battle_body["backtest_config"] = {
                    "start_time": bt_start.isoformat(),
                    "end_time": bt_end.isoformat(),
                    "candle_interval": 300,
                    "pairs": ["BTCUSDT", "ETHUSDT"],
                }

            info(f"Battle mode: {battle_mode}")

            # Create battle
            battle = await api(
                client, "POST", "/battles",
                json=battle_body,
                headers=jwt_h,
                expected=(200, 201),
                label="Create battle",
            )
            if not battle:
                fail("Cannot create battle")
            else:
                bid = battle["id"]
                info(f"Battle ID: {bid}")

                # Add participants
                for agent in created_agents:
                    p = await api(
                        client, "POST", f"/battles/{bid}/participants",
                        json={"agent_id": str(agent["id"])},
                        headers=jwt_h,
                        expected=(200, 201),
                        label=f"Add {agent['name']} to battle",
                    )

                # Start battle
                started = await api(client, "POST", f"/battles/{bid}/start", headers=jwt_h,
                                    label="Start battle")

                if started and battle_mode == "historical":
                    # Step through historical battle
                    step = await api(client, "POST", f"/battles/{bid}/step", headers=jwt_h,
                                     label="Battle step 1")

                    # Place an order in the battle
                    await api(
                        client, "POST", f"/battles/{bid}/trade/order",
                        json={
                            "agent_id": str(created_agents[0]["id"]),
                            "symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.01",
                        },
                        headers=jwt_h,
                        label="Battle order: AlphaBot buys BTC",
                    )

                    # Batch step
                    batch = await api(
                        client, "POST", f"/battles/{bid}/step/batch",
                        json={"steps": 500},
                        headers=jwt_h,
                        label="Battle batch step (500)",
                    )

                    # Get market prices in battle
                    await api(client, "GET", f"/battles/{bid}/market/prices", headers=jwt_h,
                              label="Battle market prices")

                # Live metrics
                live = await api(client, "GET", f"/battles/{bid}/live", headers=jwt_h,
                                 label="Battle live metrics")
                if live:
                    for p in live.get("participants", []):
                        info(f"  {p.get('display_name')}: equity={p.get('current_equity')}, "
                             f"pnl={p.get('pnl')}, trades={p.get('total_trades')}")

                # Stop battle
                await api(client, "POST", f"/battles/{bid}/stop", headers=jwt_h, label="Stop battle")

                # Results
                results = await api(client, "GET", f"/battles/{bid}/results", headers=jwt_h,
                                    label="Battle results")
                if results:
                    for i, p in enumerate(results.get("participants", [])):
                        info(f"  #{i+1}: {p.get('display_name')} -- equity={p.get('final_equity')}, "
                             f"roi={p.get('roi_pct')}%")

                # Replay
                await api(client, "GET", f"/battles/{bid}/replay", headers=jwt_h, label="Battle replay data")

                # List battles
                await api(client, "GET", "/battles", headers=jwt_h, label="List all battles")

        # ==================================================================
        # PHASE 7: Analytics & Market Data
        # ==================================================================
        header("PHASE 7: Analytics & Market Data")

        # Performance analytics (per agent)
        for agent in created_agents:
            if not agent.get("api_key"):
                continue
            perf = await api(client, "GET", "/analytics/performance",
                             headers={"X-API-Key": agent["api_key"]},
                             params={"period": "all"},
                             label=f"{agent['name']}: Performance analytics")
            if perf:
                info(f"  Sharpe: {perf.get('sharpe_ratio')}, Win rate: {perf.get('win_rate')}%, "
                     f"Trades: {perf.get('total_trades')}")

        # Market data (public)
        prices = await api(client, "GET", "/market/prices", label="Market prices (all)")
        if prices:
            info(f"  {prices.get('count', '?')} pairs, stale={prices.get('stale')}")

        btc = await api(client, "GET", "/market/price/BTCUSDT", label="BTC price")
        if btc:
            info(f"  BTCUSDT: ${btc.get('price')}")

        eth = await api(client, "GET", "/market/price/ETHUSDT", label="ETH price")
        if eth:
            info(f"  ETHUSDT: ${eth.get('price')}")

        # ==================================================================
        # PHASE 8: Account Management
        # ==================================================================
        header("PHASE 8: Account Management")

        # Update risk profile
        await api(client, "PUT", "/account/risk-profile",
                  json={"max_position_size_pct": 30, "daily_loss_limit_pct": 15, "max_open_orders": 100},
                  headers=jwt_h, label="Update account risk profile")

        # Agent management
        if len(created_agents) >= 2 and created_agents[1].get("api_key"):
            await api(client, "POST", f"/agents/{created_agents[1]['id']}/regenerate-key",
                      headers=jwt_h, label="Regenerate BetaBot API key")

        if created_agents and created_agents[0].get("api_key"):
            clone = await api(
                client, "POST", f"/agents/{created_agents[0]['id']}/clone",
                json={"display_name": "AlphaBot Clone"},
                headers=jwt_h,
                expected=(200, 201),
                label="Clone AlphaBot",
            )
            if clone:
                info(f"  Clone ID: {clone.get('agent_id')}")

        # ==================================================================
        # SUMMARY
        # ==================================================================
        header("RESULTS SUMMARY")

        print(f"  Passed: {passed}")
        print(f"  Failed: {failed}")
        print(f"  Skipped: {skipped}")
        print(f"  Total:  {passed + failed + skipped}")
        print()
        print("  Login Credentials (use in the UI):")
        print(f"    Email:    {email}")
        print(f"    Password: {password}")
        print()
        print("  Agents Created:")
        for agent in created_agents:
            print(f"    {agent['name']} ({agent['color']})")
            print(f"      ID:      {agent['id']}")
            if agent.get("api_key"):
                print(f"      API Key: {agent['api_key']}")
            print()

        print("  What to check in the UI:")
        print("    1. Open http://localhost:3000")
        print(f"    2. Login with {email} / {password}")
        print("    3. Dashboard: see all 3 agents with different balances & PnL")
        print("    4. Switch agents: each has its own trades, positions, portfolio")
        print("    5. Trade History: 10 trades (Alpha), 8 (Beta), 7 (Gamma)")
        print("    6. Backtests page: see backtest results per agent")
        print("    7. Battles page: see the championship battle results")
        print("    8. Analytics: performance metrics per agent")
        print()

        if failed > 0:
            print(f"  WARNING: {failed} step(s) failed. Check output above.")
            sys.exit(1)
        else:
            print("  All steps passed!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Full E2E scenario against live backend")
    parser.add_argument("--email", default=None, help=f"Account email (default: {DEFAULT_EMAIL})")
    parser.add_argument("--password", default=None, help="Account password")
    parser.add_argument("--display-name", default=None, help="Display name")
    parser.add_argument("--skip-backtest", action="store_true", help="Skip backtest phase")
    parser.add_argument("--skip-battle", action="store_true", help="Skip battle phase")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    args = parser.parse_args()

    # Update module-level URLs if custom base provided
    _update_urls(args.base_url)

    asyncio.run(run(args))


def _update_urls(base_url: str) -> None:
    global BASE_URL, API
    BASE_URL = base_url
    API = f"{BASE_URL}/api/v1"


if __name__ == "__main__":
    main()
