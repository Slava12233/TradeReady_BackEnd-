"""Backfill agent_id on existing backtest_sessions rows.

For each backtest_session where agent_id IS NULL, assigns the first agent
(by created_at) belonging to the session's account_id.

Usage:
    python -m scripts.backfill_backtest_agent_ids

Run this AFTER migration 013 and BEFORE migration 014.
"""

from __future__ import annotations

import asyncio

import structlog

logger = structlog.get_logger(__name__)


async def backfill() -> None:
    """Backfill agent_id on backtest_sessions."""
    from sqlalchemy import select, update
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    from src.config import get_settings
    from src.database.models import Agent, BacktestSession

    settings = get_settings()
    engine = create_async_engine(str(settings.DATABASE_URL), echo=False)

    async with AsyncSession(engine) as session:
        # Find sessions missing agent_id
        stmt = select(BacktestSession).where(BacktestSession.agent_id.is_(None))
        result = await session.execute(stmt)
        orphan_sessions = result.scalars().all()

        if not orphan_sessions:
            logger.info("backfill.no_orphans", message="All backtest sessions already have agent_id.")
            return

        logger.info("backfill.found_orphans", count=len(orphan_sessions))

        updated = 0
        skipped = 0

        for bt_session in orphan_sessions:
            # Find the first agent for this account
            agent_stmt = (
                select(Agent.id)
                .where(Agent.account_id == bt_session.account_id)
                .order_by(Agent.created_at.asc())
                .limit(1)
            )
            agent_result = await session.execute(agent_stmt)
            agent_id = agent_result.scalar_one_or_none()

            if agent_id is None:
                logger.warning(
                    "backfill.no_agent_for_account",
                    session_id=str(bt_session.id),
                    account_id=str(bt_session.account_id),
                )
                skipped += 1
                continue

            update_stmt = (
                update(BacktestSession)
                .where(BacktestSession.id == bt_session.id)
                .values(agent_id=agent_id)
            )
            await session.execute(update_stmt)
            updated += 1

        await session.commit()
        logger.info(
            "backfill.complete",
            updated=updated,
            skipped=skipped,
            total=len(orphan_sessions),
        )

    await engine.dispose()


def main() -> None:
    """Entry point."""
    asyncio.run(backfill())


if __name__ == "__main__":
    main()
