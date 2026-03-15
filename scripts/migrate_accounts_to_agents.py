"""Migrate existing accounts to agents — one agent per account.

For each existing account, creates an agent row copying:
- api_key, api_key_hash
- starting_balance
- risk_profile

Prints a report of migrated rows.

Usage:
    python -m scripts.migrate_accounts_to_agents

IMPORTANT: Run AFTER alembic migration 007 (create_agents_table) and
           BEFORE migration 009 (enforce_agent_id_not_null).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from src.config import get_settings  # noqa: E402
from src.database.models import Account, Agent  # noqa: E402
from src.database.session import init_db, get_session_factory, close_db  # noqa: E402


async def migrate() -> None:
    """Create one agent per existing account."""
    await init_db()
    session_factory = get_session_factory()

    async with session_factory() as session:
        result = await session.execute(select(Account))
        accounts = result.scalars().all()

        migrated = 0
        skipped = 0

        for account in accounts:
            # Check if an agent already exists for this account's API key
            existing = await session.execute(
                select(Agent).where(Agent.api_key == account.api_key)
            )
            if existing.scalars().first() is not None:
                skipped += 1
                continue

            agent = Agent(
                account_id=account.id,
                display_name=account.display_name,
                api_key=account.api_key,
                api_key_hash=account.api_key_hash,
                starting_balance=account.starting_balance,
                risk_profile=dict(account.risk_profile) if account.risk_profile else {},
                status="active" if account.status == "active" else "archived",
            )
            session.add(agent)
            migrated += 1

        await session.commit()

    await close_db()

    print(f"\n{'='*60}")
    print("Account → Agent Migration Report")
    print(f"{'='*60}")
    print(f"  Total accounts:  {len(accounts)}")
    print(f"  Agents created:  {migrated}")
    print(f"  Skipped (exist): {skipped}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(migrate())
