"""Celery tasks for battle snapshot capture and auto-completion.

Beat schedule:
- ``capture_battle_snapshots`` — every 5 seconds for all active battles
- ``check_battle_completion``  — every 10 seconds, auto-complete expired battles
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from src.tasks.celery_app import app


@app.task(
    name="src.tasks.battle_snapshots.capture_battle_snapshots",
    soft_time_limit=10,
    time_limit=15,
)
def capture_battle_snapshots() -> int:
    """Capture equity snapshots for all active battle participants.

    Returns the total number of snapshots created.
    """
    return asyncio.get_event_loop().run_until_complete(_capture_snapshots_async())


async def _capture_snapshots_async() -> int:
    """Async implementation of snapshot capture."""
    from src.battles.snapshot_engine import SnapshotEngine  # noqa: PLC0415
    from src.cache.price_cache import PriceCache  # noqa: PLC0415
    from src.cache.redis_client import get_redis_client  # noqa: PLC0415
    from src.database.session import get_session_factory  # noqa: PLC0415

    redis = await get_redis_client()
    price_cache = PriceCache(redis)
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            engine = SnapshotEngine(session, price_cache)
            total = await engine.capture_all_active_battles()
            await session.commit()
            return total
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@app.task(
    name="src.tasks.battle_snapshots.check_battle_completion",
    soft_time_limit=30,
    time_limit=45,
)
def check_battle_completion() -> int:
    """Check for battles that have exceeded their configured duration and auto-complete them.

    Returns the number of battles auto-completed.
    """
    return asyncio.get_event_loop().run_until_complete(_check_completion_async())


async def _check_completion_async() -> int:
    """Async implementation of battle auto-completion check."""
    from sqlalchemy import select  # noqa: PLC0415

    from src.battles.service import BattleService  # noqa: PLC0415
    from src.config import get_settings  # noqa: PLC0415
    from src.database.models import Battle  # noqa: PLC0415
    from src.database.session import get_session_factory  # noqa: PLC0415

    settings = get_settings()
    session_factory = get_session_factory()
    completed = 0

    async with session_factory() as session:
        try:
            stmt = select(Battle).where(Battle.status == "active")
            result = await session.execute(stmt)
            battles = result.scalars().all()

            now = datetime.now(UTC)

            for battle in battles:
                config = battle.config if isinstance(battle.config, dict) else {}
                duration_type = config.get("duration_type", "unlimited")
                duration_seconds = config.get("duration_seconds")

                if duration_type == "fixed" and duration_seconds and battle.started_at:
                    elapsed = (now - battle.started_at).total_seconds()
                    if elapsed >= duration_seconds:
                        service = BattleService(session, settings)
                        await service.stop_battle(battle.id, battle.account_id)
                        completed += 1

            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    return completed
