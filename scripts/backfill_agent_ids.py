"""Backfill agent_id on trading tables from account_id → agent lookup.

For each row in balances, orders, trades, positions, trading_sessions,
and portfolio_snapshots where agent_id IS NULL, sets agent_id by looking
up the agent created from that account_id.

Verifies zero NULLs remain after backfill.

Usage:
    python -m scripts.backfill_agent_ids

IMPORTANT: Run AFTER scripts/migrate_accounts_to_agents.py and
           BEFORE alembic migration 009 (enforce_agent_id_not_null).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text, update  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from src.config import get_settings  # noqa: E402
from src.database.models import Agent  # noqa: E402
from src.database.session import init_db, get_session_factory, close_db  # noqa: E402

_TABLES = ["balances", "orders", "trades", "positions", "trading_sessions", "portfolio_snapshots"]


async def backfill() -> None:
    """Backfill agent_id on all trading tables."""
    await init_db()
    session_factory = get_session_factory()

    async with session_factory() as session:
        # Build account_id → agent_id mapping
        result = await session.execute(select(Agent.account_id, Agent.id))
        rows = result.all()
        account_to_agent: dict = {}
        for account_id, agent_id in rows:
            # Use the first agent for each account (there should be exactly one from migration)
            if account_id not in account_to_agent:
                account_to_agent[account_id] = agent_id

        if not account_to_agent:
            print("ERROR: No agents found. Run migrate_accounts_to_agents.py first.")
            return

        print(f"Found {len(account_to_agent)} account→agent mappings.\n")

        total_updated = 0
        for table in _TABLES:
            # Update all rows where agent_id IS NULL using a subquery
            stmt = text(f"""
                UPDATE {table}
                SET agent_id = agents.id
                FROM agents
                WHERE {table}.account_id = agents.account_id
                  AND {table}.agent_id IS NULL
            """)
            result = await session.execute(stmt)
            updated = result.rowcount
            total_updated += updated
            print(f"  {table}: {updated} rows updated")

        await session.commit()

        # Verify zero NULLs remain
        print(f"\nVerifying zero NULLs remain...")
        all_clean = True
        for table in _TABLES:
            result = await session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE agent_id IS NULL")
            )
            null_count = result.scalar()
            if null_count > 0:
                print(f"  WARNING: {table} still has {null_count} NULL agent_id rows!")
                all_clean = False
            else:
                print(f"  {table}: OK (0 NULLs)")

    await close_db()

    print(f"\n{'='*60}")
    print("Backfill Report")
    print(f"{'='*60}")
    print(f"  Total rows updated: {total_updated}")
    print(f"  All clean: {'YES' if all_clean else 'NO — FIX BEFORE RUNNING MIGRATION 009'}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(backfill())
