"""Provision 5 trading agent accounts for the AiTradingAgent platform.

Creates:
- 1 account: trader@tradeready.ai
- 5 agents: Momentum, Balanced, Evolved, Regime-Adaptive, Conservative
- Sets distinct risk profiles per agent
- Saves Agent 1 (Momentum) API key to agent/.env as PLATFORM_API_KEY

Usage:
    python scripts/e2e_provision_agents.py

Prerequisites:
    - API running at http://localhost:8000
    - Docker services up (docker compose up -d)
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"

EMAIL = "trader@tradeready.ai"
PASSWORD = "Tr@d3r_S3cur3_2026!"  # noqa: S105
DISPLAY_NAME = "TradeReady_Main"

# Agent definitions — (display_name, starting_balance, color, llm_model, framework, tags)
AGENTS = [
    {
        "display_name": "Momentum",
        "starting_balance": "10000",
        "color": "#FF5733",
        "llm_model": "claude-opus-4",
        "framework": "custom",
        "strategy_tags": ["momentum", "breakout", "trend-following"],
        "risk": {"max_position_size_pct": 10, "daily_loss_limit_pct": 30, "max_open_orders": 50},
    },
    {
        "display_name": "Balanced",
        "starting_balance": "10000",
        "color": "#33A1FF",
        "llm_model": "gpt-4o",
        "framework": "langchain",
        "strategy_tags": ["mean-reversion", "balanced", "multi-coin"],
        "risk": {"max_position_size_pct": 5, "daily_loss_limit_pct": 15, "max_open_orders": 30},
    },
    {
        "display_name": "Evolved",
        "starting_balance": "10000",
        "color": "#A633FF",
        "llm_model": "claude-sonnet-4",
        "framework": "custom",
        "strategy_tags": ["evolutionary", "genetic", "adaptive"],
        "risk": {"max_position_size_pct": 10, "daily_loss_limit_pct": 25, "max_open_orders": 40},
    },
    {
        "display_name": "Regime-Adaptive",
        "starting_balance": "10000",
        "color": "#33FF99",
        "llm_model": "gemini-flash",
        "framework": "pydantic-ai",
        "strategy_tags": ["regime-detection", "adaptive", "macro"],
        "risk": {"max_position_size_pct": 8, "daily_loss_limit_pct": 20, "max_open_orders": 35},
    },
    {
        "display_name": "Conservative",
        "starting_balance": "10000",
        "color": "#FFD700",
        "llm_model": "claude-haiku-3",
        "framework": "custom",
        "strategy_tags": ["conservative", "low-risk", "capital-preservation"],
        "risk": {"max_position_size_pct": 3, "daily_loss_limit_pct": 10, "max_open_orders": 15},
    },
]

passed = 0
failed = 0


async def req(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    json: dict | None = None,
    headers: dict | None = None,
    expected: tuple[int, ...] = (200,),
    label: str = "",
) -> dict[str, Any] | None:
    global passed, failed
    url = f"{API}{path}"
    resp = await client.request(method, url, json=json, headers=headers, timeout=30)
    if resp.status_code in expected:
        passed += 1
        print(f"  [PASS] {label} -> {resp.status_code}")
        try:
            return resp.json()
        except Exception:
            return {}
    else:
        failed += 1
        print(f"  [FAIL] {label} -> {resp.status_code}: {resp.text[:300]}")
        return None


async def health_check(client: httpx.AsyncClient) -> bool:
    resp = await client.get(f"{BASE_URL}/health", timeout=10)
    data = resp.json()
    db_ok = data.get("db_connected", False)
    redis_ok = data.get("redis_connected", False)
    print(f"  Health: status={data.get('status')} db={db_ok} redis={redis_ok}")
    return db_ok and redis_ok


async def main() -> None:
    start = time.perf_counter()

    print()
    print("=" * 70)
    print("  PROVISION: 5 Trading Agent Accounts")
    print("=" * 70)

    async with httpx.AsyncClient() as client:

        # ----------------------------------------------------------------
        # Phase 0: Prerequisites
        # ----------------------------------------------------------------
        print()
        print("=" * 70)
        print("  PHASE 0: Prerequisites Check")
        print("=" * 70)
        if not await health_check(client):
            print("  [FAIL] API health check failed — DB or Redis not connected")
            sys.exit(1)
        print("  [PASS] API is healthy")

        # ----------------------------------------------------------------
        # Phase 1: Account Registration
        # ----------------------------------------------------------------
        print()
        print("=" * 70)
        print("  PHASE 1: Account Registration")
        print("=" * 70)

        reg = await req(
            client,
            "POST",
            "/auth/register",
            json={
                "display_name": DISPLAY_NAME,
                "email": EMAIL,
                "password": PASSWORD,
                "starting_balance": "10000",
            },
            expected=(200, 201, 409),
            label="Register account",
        )

        if reg is None:
            print("  [FAIL] Registration returned unexpected status — aborting")
            sys.exit(1)

        account_id: str | None = None
        api_key: str | None = None
        api_secret: str | None = None

        if reg.get("account_id"):
            account_id = reg["account_id"]
            api_key = reg.get("api_key")
            api_secret = reg.get("api_secret") or reg.get("secret")
            print(f"       > New account ID: {account_id}")
            print(f"       > API Key: {api_key}")
        else:
            # 409 — account already exists, api key/secret not returned
            print("       > Account already exists, proceeding to login")

        # ----------------------------------------------------------------
        # Phase 2: Login (get JWT for agent management)
        # ----------------------------------------------------------------
        print()
        print("=" * 70)
        print("  PHASE 2: JWT Login")
        print("=" * 70)

        # Try user-login (email/password → JWT)
        login = await req(
            client,
            "POST",
            "/auth/user-login",
            json={"email": EMAIL, "password": PASSWORD},
            expected=(200, 201),
            label="User login (email/password)",
        )
        if login is None:
            print("  [FAIL] Login failed — aborting")
            sys.exit(1)

        jwt_token = login.get("token") or login.get("access_token")
        if not jwt_token:
            print(f"  [FAIL] No token in login response: {login}")
            sys.exit(1)
        print(f"       > JWT: {jwt_token[:40]}...")

        jwt_headers = {"Authorization": f"Bearer {jwt_token}"}

        # ----------------------------------------------------------------
        # Phase 3: Create 5 Agents
        # ----------------------------------------------------------------
        print()
        print("=" * 70)
        print("  PHASE 3: Create 5 Agents")
        print("=" * 70)

        created_agents: list[dict[str, Any]] = []

        for idx, agent_def in enumerate(AGENTS, start=1):
            print(f"\n  --- Agent {idx}: {agent_def['display_name']} ---")

            create_resp = await req(
                client,
                "POST",
                "/agents",
                json={
                    "display_name": agent_def["display_name"],
                    "starting_balance": agent_def["starting_balance"],
                    "color": agent_def["color"],
                    "llm_model": agent_def["llm_model"],
                    "framework": agent_def["framework"],
                    "strategy_tags": agent_def["strategy_tags"],
                    "risk_profile": agent_def["risk"],
                },
                headers=jwt_headers,
                expected=(200, 201),
                label=f"Create agent {agent_def['display_name']}",
            )

            if create_resp is None:
                print(f"  [FAIL] Could not create agent {agent_def['display_name']}")
                continue

            agent_id = str(create_resp.get("agent_id", ""))
            agent_api_key = create_resp.get("api_key", "")
            balance = create_resp.get("starting_balance", "?")
            print(f"       > Agent ID:  {agent_id}")
            print(f"       > API Key:   {agent_api_key}")
            print(f"       > Balance:   {balance} USDT")

            created_agents.append({
                "display_name": agent_def["display_name"],
                "agent_id": agent_id,
                "api_key": agent_api_key,
                "risk": agent_def["risk"],
            })

            # Set risk profile explicitly via PUT (even though we passed it in creation,
            # this ensures the values are applied and confirmed)
            risk_resp = await req(
                client,
                "PUT",
                f"/agents/{agent_id}/risk-profile",
                json={
                    "max_position_size_pct": agent_def["risk"]["max_position_size_pct"],
                    "daily_loss_limit_pct": agent_def["risk"]["daily_loss_limit_pct"],
                    "max_open_orders": agent_def["risk"]["max_open_orders"],
                },
                headers=jwt_headers,
                expected=(200, 201),
                label=f"Set risk profile for {agent_def['display_name']}",
            )
            if risk_resp:
                print(f"       > Risk: max_pos={risk_resp.get('max_position_size_pct')}%  "
                      f"daily_loss={risk_resp.get('daily_loss_limit_pct')}%  "
                      f"max_orders={risk_resp.get('max_open_orders')}")

        # ----------------------------------------------------------------
        # Phase 4: Verify all agents exist
        # ----------------------------------------------------------------
        print()
        print("=" * 70)
        print("  PHASE 4: Verify Agents")
        print("=" * 70)

        agents_resp = await req(
            client,
            "GET",
            "/agents",
            headers=jwt_headers,
            expected=(200,),
            label="List all agents",
        )

        if agents_resp:
            # Response may be a list or {agents: [...]}
            agents_list = agents_resp if isinstance(agents_resp, list) else agents_resp.get("agents", [])
            print(f"       > Total agents found: {len(agents_list)}")
            for a in agents_list:
                name = a.get("display_name", "?")
                aid = a.get("id", a.get("agent_id", "?"))
                preview = a.get("api_key_preview", "?")
                status = a.get("status", "?")
                print(f"         - {name:20s} id={aid} key_preview={preview} status={status}")

        # ----------------------------------------------------------------
        # Phase 5: Update agent/.env with Momentum API key
        # ----------------------------------------------------------------
        print()
        print("=" * 70)
        print("  PHASE 5: Update agent/.env")
        print("=" * 70)

        momentum_agent = next((a for a in created_agents if a["display_name"] == "Momentum"), None)

        if momentum_agent and momentum_agent["api_key"]:
            env_path = Path(__file__).parent.parent / "agent" / ".env"
            if env_path.exists():
                content = env_path.read_text(encoding="utf-8")
                # Replace existing PLATFORM_API_KEY line
                lines = content.splitlines()
                new_lines = []
                key_updated = False
                for line in lines:
                    if line.startswith("PLATFORM_API_KEY="):
                        new_lines.append(f"PLATFORM_API_KEY={momentum_agent['api_key']}")
                        key_updated = True
                    else:
                        new_lines.append(line)
                if not key_updated:
                    new_lines.append(f"PLATFORM_API_KEY={momentum_agent['api_key']}")
                env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                print(f"  [PASS] Updated agent/.env PLATFORM_API_KEY")
                print(f"       > Momentum API Key: {momentum_agent['api_key']}")
                print(f"       > File: {env_path}")
            else:
                print(f"  [WARN] agent/.env not found at {env_path} — skipping update")
        else:
            print("  [WARN] Momentum agent key not available — skipping .env update")

        # ----------------------------------------------------------------
        # Summary
        # ----------------------------------------------------------------
        elapsed = time.perf_counter() - start

        print()
        print("=" * 70)
        print("  RESULTS SUMMARY")
        print("=" * 70)
        print(f"  Passed: {passed}")
        print(f"  Failed: {failed}")
        print(f"  Time:   {elapsed:.1f}s")
        print()
        print("  ============================================================")
        print("    LOGIN CREDENTIALS")
        print("  ============================================================")
        print(f"    Email:    {EMAIL}")
        print(f"    Password: {PASSWORD}")
        print(f"    Frontend: http://localhost:3000")
        print("  ============================================================")
        print()
        print("  Agents Created:")
        print(f"  {'#':<3} {'Name':<20} {'Agent ID':<38} API Key")
        print(f"  {'-'*3} {'-'*20} {'-'*38} {'-'*30}")
        for idx, a in enumerate(created_agents, start=1):
            key_display = a["api_key"][:30] + "..." if len(a["api_key"]) > 30 else a["api_key"]
            print(f"  {idx:<3} {a['display_name']:<20} {a['agent_id']:<38} {key_display}")
        print()
        print("  Risk Profiles Applied:")
        print(f"  {'Name':<20} {'max_position_pct':>17} {'daily_loss_pct':>15}")
        print(f"  {'-'*20} {'-'*17} {'-'*15}")
        for agent_def in AGENTS:
            r = agent_def["risk"]
            print(f"  {agent_def['display_name']:<20} {r['max_position_size_pct']:>16}%"
                  f" {r['daily_loss_limit_pct']:>14}%")
        print()
        print("  What to verify in the UI:")
        print("    1. Open http://localhost:3000")
        print("    2. Login with the credentials above")
        print("    3. Agent Switcher: should show all 5 agents")
        print("    4. Each agent has 10,000 USDT starting balance")
        print("    5. Settings > Risk Profile: verify limits per agent")
        print()

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
