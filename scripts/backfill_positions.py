"""Backfill the ``positions`` table from trade history.

Replays all trades in chronological order for every account and reconstructs
the current Position state (quantity + weighted-average entry price) exactly
as the OrderEngine would have done had position tracking been active.

Run once after deploying the position-tracking fix::

    python scripts/backfill_positions.py

Existing Position rows are deleted first so the script is safe to re-run.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Allow running from repo root without installing the package.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.models import Account, Position, Trade  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

_ZERO = Decimal("0")


def _get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        # Try loading from .env
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DATABASE_URL="):
                        url = line.split("=", 1)[1].strip().strip('"').strip("'")
                        break
    if not url:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    # asyncpg driver required
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


async def _rebuild_positions_for_account(
    session: AsyncSession,
    account_id: UUID,
) -> dict[str, Position]:
    """Replay all trades for *account_id* and return the reconstructed positions."""
    stmt = (
        select(Trade)
        .where(Trade.account_id == account_id)
        .order_by(Trade.created_at.asc())
    )
    result = await session.execute(stmt)
    trades = result.scalars().all()

    positions: dict[str, dict] = {}  # symbol → {qty, avg_entry, total_cost, realized_pnl}

    for trade in trades:
        symbol = trade.symbol
        side = trade.side
        fill_qty = Decimal(str(trade.quantity))
        fill_price = Decimal(str(trade.price))

        if symbol not in positions:
            positions[symbol] = {
                "qty": _ZERO,
                "avg_entry": _ZERO,
                "total_cost": _ZERO,
                "realized_pnl": _ZERO,
            }

        p = positions[symbol]

        if side == "buy":
            fill_cost = fill_qty * fill_price
            new_qty = p["qty"] + fill_qty
            new_total_cost = p["total_cost"] + fill_cost
            new_avg_entry = new_total_cost / new_qty if new_qty else fill_price
            p["qty"] = new_qty
            p["total_cost"] = new_total_cost
            p["avg_entry"] = new_avg_entry
        else:  # sell
            avg_entry = p["avg_entry"]
            realized_increment = (fill_price - avg_entry) * fill_qty
            new_qty = max(p["qty"] - fill_qty, _ZERO)
            p["qty"] = new_qty
            p["total_cost"] = new_qty * avg_entry
            p["realized_pnl"] += realized_increment

    # Build Position ORM objects for non-zero quantities
    orm_positions: dict[str, Position] = {}
    for symbol, data in positions.items():
        if data["qty"] > _ZERO:
            orm_positions[symbol] = Position(
                account_id=account_id,
                symbol=symbol,
                side="long",
                quantity=data["qty"],
                avg_entry_price=data["avg_entry"],
                total_cost=data["total_cost"],
                realized_pnl=data["realized_pnl"],
            )

    return orm_positions


async def main() -> None:
    db_url = _get_database_url()
    engine = create_async_engine(db_url, echo=False)
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        # Fetch all account IDs
        result = await session.execute(select(Account.id, Account.display_name))
        accounts = result.all()

        if not accounts:
            log.info("No accounts found — nothing to backfill.")
            return

        log.info("Found %d account(s). Clearing existing positions...", len(accounts))
        await session.execute(delete(Position))
        await session.flush()

        total_positions = 0
        for account_id, display_name in accounts:
            rebuilt = await _rebuild_positions_for_account(session, account_id)
            for pos in rebuilt.values():
                session.add(pos)
            total_positions += len(rebuilt)
            log.info(
                "  Account %-30s → %d open position(s)",
                display_name,
                len(rebuilt),
            )

        await session.commit()
        log.info("Backfill complete. %d position row(s) written.", total_positions)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
