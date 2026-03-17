"""Seed a test user with 3 agents, each having distinct trades and balances.

Creates:
- 1 account (slavatest2 / slava@test.com)
- 3 agents: "Alpha Scalper", "Beta Swing", "Gamma HODL"
- Separate USDT + base-asset balances per agent
- Different trades per agent (different symbols, quantities, PnL)
- Different positions per agent

Usage:
    python -m scripts.seed_test_user

The script is idempotent — it skips creation if the email already exists and
prints the API keys for each agent so you can log in immediately.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import sys
from uuid import uuid4

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from src.accounts.auth import generate_api_credentials, hash_password  # noqa: E402
from src.database.models import Account, Agent, Balance, Order, Position, Trade  # noqa: E402
from src.database.session import close_db, get_session_factory, init_db  # noqa: E402

# ---------------------------------------------------------------------------
# Agent definitions — each has a different trading personality
# ---------------------------------------------------------------------------

AGENT_CONFIGS = [
    {
        "display_name": "Alpha Scalper",
        "color": "#FF5733",
        "llm_model": "gpt-4o",
        "framework": "langchain",
        "strategy_tags": ["scalping", "high-frequency"],
        "starting_balance": Decimal("10000"),
        "trades": [
            # Aggressive BTC scalping — many small trades
            {"symbol": "BTCUSDT", "side": "buy", "qty": "0.05", "price": "67200", "pnl": "12.50"},
            {"symbol": "BTCUSDT", "side": "sell", "qty": "0.05", "price": "67350", "pnl": "7.50"},
            {"symbol": "BTCUSDT", "side": "buy", "qty": "0.03", "price": "67100", "pnl": "-4.20"},
            {"symbol": "ETHUSDT", "side": "buy", "qty": "0.5", "price": "3420", "pnl": "15.00"},
            {"symbol": "ETHUSDT", "side": "sell", "qty": "0.5", "price": "3440", "pnl": "10.00"},
            {"symbol": "SOLUSDT", "side": "buy", "qty": "10", "price": "145.50", "pnl": "22.00"},
            {"symbol": "BTCUSDT", "side": "buy", "qty": "0.02", "price": "67500", "pnl": "8.30"},
            {"symbol": "BTCUSDT", "side": "sell", "qty": "0.02", "price": "67600", "pnl": "2.00"},
        ],
        "balances": {"USDT": "8450.60", "BTC": "0.03000000", "ETH": "0.00000000", "SOL": "10.00000000"},
        "positions": [
            {"symbol": "BTCUSDT", "qty": "0.03", "avg_entry": "67300", "pnl": "18.10"},
            {"symbol": "SOLUSDT", "qty": "10", "avg_entry": "145.50", "pnl": "22.00"},
        ],
    },
    {
        "display_name": "Beta Swing",
        "color": "#33A1FF",
        "llm_model": "claude-opus-4-20250514",
        "framework": "custom",
        "strategy_tags": ["swing", "trend-following"],
        "starting_balance": Decimal("25000"),
        "trades": [
            # Bigger positions, fewer trades, ETH-focused
            {"symbol": "ETHUSDT", "side": "buy", "qty": "3.0", "price": "3380", "pnl": None},
            {"symbol": "ETHUSDT", "side": "sell", "qty": "1.5", "price": "3520", "pnl": "210.00"},
            {"symbol": "BNBUSDT", "side": "buy", "qty": "5.0", "price": "620", "pnl": None},
            {"symbol": "AVAXUSDT", "side": "buy", "qty": "50", "price": "38.50", "pnl": None},
            {"symbol": "AVAXUSDT", "side": "sell", "qty": "50", "price": "41.20", "pnl": "135.00"},
        ],
        "balances": {"USDT": "14520.30", "ETH": "1.50000000", "BNB": "5.00000000"},
        "positions": [
            {"symbol": "ETHUSDT", "qty": "1.5", "avg_entry": "3380", "pnl": "210.00"},
            {"symbol": "BNBUSDT", "qty": "5.0", "avg_entry": "620", "pnl": "0.00"},
        ],
    },
    {
        "display_name": "Gamma HODL",
        "color": "#33FF57",
        "llm_model": "gpt-4o-mini",
        "framework": "crewai",
        "strategy_tags": ["hodl", "dca", "long-term"],
        "starting_balance": Decimal("50000"),
        "trades": [
            # Big BTC buys, rarely sells — accumulation strategy
            {"symbol": "BTCUSDT", "side": "buy", "qty": "0.3", "price": "64000", "pnl": None},
            {"symbol": "BTCUSDT", "side": "buy", "qty": "0.2", "price": "62500", "pnl": None},
            {"symbol": "BTCUSDT", "side": "buy", "qty": "0.1", "price": "66800", "pnl": None},
        ],
        "balances": {"USDT": "11220.00", "BTC": "0.60000000"},
        "positions": [
            {"symbol": "BTCUSDT", "qty": "0.6", "avg_entry": "63933.33", "pnl": "0.00"},
        ],
    },
]


async def seed() -> None:
    """Create the test user, agents, and their trading data."""
    await init_db()
    session_factory = get_session_factory()

    async with session_factory() as session:
        # ----- Check if account already exists -----
        result = await session.execute(
            select(Account).where(Account.email == "slava@test.com")
        )
        existing_account = result.scalars().first()

        if existing_account:
            print(f"Account 'slava@test.com' already exists (id={existing_account.id})")
            # Check if agents exist
            result = await session.execute(
                select(Agent).where(Agent.account_id == existing_account.id)
            )
            existing_agents = result.scalars().all()
            if existing_agents:
                print(f"  {len(existing_agents)} agent(s) already exist — printing keys:")
                for ag in existing_agents:
                    print(f"  - {ag.display_name}: api_key={ag.api_key}")
                print("\nTo re-seed, delete the account first or use a different email.")
                await close_db()
                return
            account = existing_account
        else:
            # ----- Create account -----
            acct_creds = generate_api_credentials()
            account = Account(
                api_key=acct_creds.api_key,
                api_key_hash=acct_creds.api_key_hash,
                api_secret_hash=acct_creds.api_secret_hash,
                password_hash=hash_password("TestPass123!"),
                display_name="slavatest2",
                email="slava@test.com",
                starting_balance=Decimal("10000"),
                status="active",
            )
            session.add(account)
            await session.flush()
            print(f"Created account: {account.display_name} (id={account.id})")
            print(f"  Account API key: {acct_creds.api_key}")

        # ----- Create agents + data -----
        print("\n--- Creating agents ---\n")

        for i, cfg in enumerate(AGENT_CONFIGS):
            agent_creds = generate_api_credentials()
            agent = Agent(
                account_id=account.id,
                display_name=cfg["display_name"],
                api_key=agent_creds.api_key,
                api_key_hash=agent_creds.api_key_hash,
                starting_balance=cfg["starting_balance"],
                llm_model=cfg["llm_model"],
                framework=cfg["framework"],
                strategy_tags=cfg["strategy_tags"],
                risk_profile={},
                color=cfg["color"],
                status="active",
            )
            session.add(agent)
            await session.flush()

            print(f"Agent {i + 1}: {cfg['display_name']}")
            print(f"  ID:      {agent.id}")
            print(f"  API Key: {agent_creds.api_key}")
            print(f"  Balance: {cfg['starting_balance']} USDT")
            print(f"  Color:   {cfg['color']}")

            # ----- Balances -----
            for asset, amount in cfg["balances"].items():
                bal = Balance(
                    account_id=account.id,
                    agent_id=agent.id,
                    asset=asset,
                    available=Decimal(amount),
                    locked=Decimal("0"),
                )
                session.add(bal)

            # ----- Orders + Trades -----
            now = datetime.now(tz=UTC)
            for j, t in enumerate(cfg["trades"]):
                order_id = uuid4()
                trade_time = now - timedelta(hours=len(cfg["trades"]) - j, minutes=j * 7)

                order = Order(
                    id=order_id,
                    account_id=account.id,
                    agent_id=agent.id,
                    symbol=t["symbol"],
                    side=t["side"],
                    type="market",
                    quantity=Decimal(t["qty"]),
                    status="filled",
                    executed_price=Decimal(t["price"]),
                    executed_qty=Decimal(t["qty"]),
                    slippage_pct=Decimal("0.01"),
                    fee=Decimal(t["qty"]) * Decimal(t["price"]) * Decimal("0.001"),
                    filled_at=trade_time,
                    created_at=trade_time,
                )
                session.add(order)

                trade = Trade(
                    account_id=account.id,
                    agent_id=agent.id,
                    order_id=order_id,
                    symbol=t["symbol"],
                    side=t["side"],
                    quantity=Decimal(t["qty"]),
                    price=Decimal(t["price"]),
                    quote_amount=Decimal(t["qty"]) * Decimal(t["price"]),
                    fee=Decimal(t["qty"]) * Decimal(t["price"]) * Decimal("0.001"),
                    realized_pnl=Decimal(t["pnl"]) if t["pnl"] is not None else None,
                    created_at=trade_time,
                )
                session.add(trade)

            # ----- Positions -----
            for p in cfg["positions"]:
                qty = Decimal(p["qty"])
                avg = Decimal(p["avg_entry"])
                pos = Position(
                    account_id=account.id,
                    agent_id=agent.id,
                    symbol=p["symbol"],
                    side="long",
                    quantity=qty,
                    avg_entry_price=avg,
                    total_cost=qty * avg,
                    realized_pnl=Decimal(p["pnl"]),
                )
                session.add(pos)

            print(f"  Trades:    {len(cfg['trades'])}")
            print(f"  Positions: {len(cfg['positions'])}")
            print()

        await session.commit()
        print("All data committed successfully!")

        # ----- Summary -----
        print("\n" + "=" * 60)
        print("SEED COMPLETE — Login with:")
        print("  Email:    slava@test.com")
        print("  Password: TestPass123!")
        print("=" * 60)

    await close_db()


if __name__ == "__main__":
    asyncio.run(seed())
