"""Snapshot engine for recording battle participant equity at regular intervals.

Designed to be called as a Celery beat task every 5 seconds for each active
battle.  Records equity, unrealized PnL, realized PnL, trade count, and
open positions for each participant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.cache.price_cache import PriceCache
from src.database.models import (
    Balance,
    BattleSnapshot,
    Position,
    Trade,
)
from src.database.repositories.battle_repo import BattleRepository

logger = structlog.get_logger(__name__)


class SnapshotEngine:
    """Records periodic snapshots for all participants in active battles.

    Args:
        session: An open AsyncSession.
        price_cache: Redis-backed price cache for current market prices.
    """

    def __init__(self, session: AsyncSession, price_cache: PriceCache) -> None:
        self._session = session
        self._price_cache = price_cache
        self._battle_repo = BattleRepository(session)

    async def capture_battle_snapshots(self, battle_id: UUID) -> int:
        """Capture a snapshot for every participant in a battle.

        Returns the number of snapshots created.
        """
        participants = await self._battle_repo.get_participants(battle_id)
        now = datetime.now(UTC)
        snapshots: list[BattleSnapshot] = []

        for participant in participants:
            if participant.status not in ("active",):
                continue

            agent_id = participant.agent_id

            equity = await self._get_agent_equity(agent_id)
            unrealized = await self._get_unrealized_pnl(agent_id)
            realized = await self._get_realized_pnl(agent_id)
            trade_count = await self._get_trade_count(agent_id)
            open_pos = await self._get_open_position_count(agent_id)

            snapshot = BattleSnapshot(
                battle_id=battle_id,
                agent_id=agent_id,
                timestamp=now,
                equity=equity,
                unrealized_pnl=unrealized,
                realized_pnl=realized,
                trade_count=trade_count,
                open_positions=open_pos,
            )
            snapshots.append(snapshot)

        if snapshots:
            await self._battle_repo.insert_snapshots_bulk(snapshots)
            logger.debug(
                "battle.snapshots_captured",
                battle_id=str(battle_id),
                count=len(snapshots),
            )

        return len(snapshots)

    async def capture_all_active_battles(self) -> int:
        """Capture snapshots for ALL active battles.

        Returns total number of snapshots created across all battles.
        """
        from src.database.models import Battle  # noqa: PLC0415

        stmt = select(Battle).where(Battle.status == "active")
        result = await self._session.execute(stmt)
        battles = result.scalars().all()

        total = 0
        for battle in battles:
            try:
                count = await self.capture_battle_snapshots(battle.id)
                total += count
            except Exception:  # noqa: BLE001
                logger.exception(
                    "battle.snapshot_capture_failed",
                    battle_id=str(battle.id),
                )

        return total

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_agent_equity(self, agent_id: UUID) -> Decimal:
        """Total available + locked across all balances for an agent."""
        stmt = select(
            func.coalesce(func.sum(Balance.available + Balance.locked), Decimal("0"))
        ).where(Balance.agent_id == agent_id)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def _get_unrealized_pnl(self, agent_id: UUID) -> Decimal:
        """Calculate unrealized PnL from open positions using current Redis prices."""
        positions = await self._get_open_positions(agent_id)
        if not positions:
            return Decimal("0")

        total_unrealized = Decimal("0")
        for pos in positions:
            try:
                current_price = await self._price_cache.get_price(pos.symbol)
                if current_price is None:
                    logger.warning(
                        "snapshot.price_unavailable",
                        agent_id=str(agent_id),
                        symbol=pos.symbol,
                    )
                    continue
                if pos.avg_entry_price and pos.quantity:
                    unrealized = (current_price - pos.avg_entry_price) * pos.quantity
                    total_unrealized += unrealized
            except Exception:  # noqa: BLE001
                logger.exception(
                    "snapshot.unrealized_pnl_error",
                    agent_id=str(agent_id),
                    symbol=pos.symbol,
                )

        return total_unrealized

    async def _get_open_positions(self, agent_id: UUID) -> list[Position]:
        """Return all open positions for an agent."""
        stmt = select(Position).where(
            Position.agent_id == agent_id,
            Position.quantity > 0,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _get_realized_pnl(self, agent_id: UUID) -> Decimal:
        """Sum of realized PnL from all trades for this agent."""
        stmt = select(
            func.coalesce(func.sum(Trade.realized_pnl), Decimal("0"))
        ).where(Trade.agent_id == agent_id)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def _get_trade_count(self, agent_id: UUID) -> int:
        """Count of all trades for this agent."""
        stmt = select(func.count()).select_from(Trade).where(Trade.agent_id == agent_id)
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def _get_open_position_count(self, agent_id: UUID) -> int:
        """Count of open positions for this agent."""
        stmt = (
            select(func.count())
            .select_from(Position)
            .where(Position.agent_id == agent_id, Position.quantity > 0)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one()
