"""Repository for backtest session, trade, and snapshot persistence.

All database access for backtesting models goes through
:class:`BacktestRepository`.  Service classes must never issue raw
SQLAlchemy queries for backtest data directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import BacktestSession, BacktestSnapshot, BacktestTrade
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class BacktestRepository:
    """Async repository for backtesting database operations.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Session CRUD ─────────────────────────────────────────────────────

    async def create_session(self, bt_session: BacktestSession) -> BacktestSession:
        """Persist a new backtest session."""
        try:
            self._session.add(bt_session)
            await self._session.flush()
            return bt_session
        except SQLAlchemyError as exc:
            logger.exception("backtest_repo.create_session.error", error=str(exc))
            raise DatabaseError("Failed to create backtest session.") from exc

    async def get_session(
        self,
        session_id: UUID,
        account_id: UUID | None = None,
        agent_id: UUID | None = None,
    ) -> BacktestSession | None:
        """Fetch a backtest session by ID, optionally scoped to account or agent."""
        try:
            stmt = select(BacktestSession).where(BacktestSession.id == session_id)
            if account_id is not None:
                stmt = stmt.where(BacktestSession.account_id == account_id)
            if agent_id is not None:
                stmt = stmt.where(BacktestSession.agent_id == agent_id)
            result = await self._session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as exc:
            logger.exception("backtest_repo.get_session.error", error=str(exc))
            raise DatabaseError("Failed to fetch backtest session.") from exc

    async def update_session(self, session_id: UUID, **fields: object) -> None:
        """Update specific fields on a backtest session."""
        try:
            stmt = (
                update(BacktestSession)
                .where(BacktestSession.id == session_id)
                .values(**fields, updated_at=datetime.now(tz=UTC))
            )
            await self._session.execute(stmt)
            await self._session.flush()
        except SQLAlchemyError as exc:
            logger.exception("backtest_repo.update_session.error", error=str(exc))
            raise DatabaseError("Failed to update backtest session.") from exc

    async def list_sessions(
        self,
        account_id: UUID,
        *,
        agent_id: UUID | None = None,
        strategy_label: str | None = None,
        status: str | None = None,
        sort_by: str = "created_at",
        limit: int = 50,
    ) -> Sequence[BacktestSession]:
        """List backtest sessions for an account with optional filters."""
        try:
            stmt = select(BacktestSession).where(BacktestSession.account_id == account_id)
            if agent_id is not None:
                stmt = stmt.where(BacktestSession.agent_id == agent_id)
            if strategy_label is not None:
                stmt = stmt.where(BacktestSession.strategy_label == strategy_label)
            if status is not None:
                stmt = stmt.where(BacktestSession.status == status)

            # Sort
            sort_col = getattr(BacktestSession, sort_by, BacktestSession.created_at)
            if sort_by in ("roi_pct", "total_trades"):
                stmt = stmt.order_by(sort_col.desc().nullslast())
            else:
                stmt = stmt.order_by(sort_col.desc())

            stmt = stmt.limit(limit)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("backtest_repo.list_sessions.error", error=str(exc))
            raise DatabaseError("Failed to list backtest sessions.") from exc

    # ── Trades ───────────────────────────────────────────────────────────

    async def save_trades(self, session_id: UUID, trades: list[BacktestTrade]) -> None:
        """Bulk insert trades for a session."""
        try:
            for trade in trades:
                trade.session_id = session_id
                self._session.add(trade)
            await self._session.flush()
        except SQLAlchemyError as exc:
            logger.exception("backtest_repo.save_trades.error", error=str(exc))
            raise DatabaseError("Failed to save backtest trades.") from exc

    async def get_trades(self, session_id: UUID, *, limit: int = 1000, offset: int = 0) -> Sequence[BacktestTrade]:
        """Get trades for a session, ordered by simulated_at."""
        try:
            stmt = (
                select(BacktestTrade)
                .where(BacktestTrade.session_id == session_id)
                .order_by(BacktestTrade.simulated_at.asc())
                .offset(offset)
                .limit(limit)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("backtest_repo.get_trades.error", error=str(exc))
            raise DatabaseError("Failed to fetch backtest trades.") from exc

    # ── Snapshots ────────────────────────────────────────────────────────

    async def save_snapshots(self, session_id: UUID, snapshots: list[BacktestSnapshot]) -> None:
        """Bulk insert snapshots for a session."""
        try:
            for snap in snapshots:
                snap.session_id = session_id
                self._session.add(snap)
            await self._session.flush()
        except SQLAlchemyError as exc:
            logger.exception("backtest_repo.save_snapshots.error", error=str(exc))
            raise DatabaseError("Failed to save backtest snapshots.") from exc

    async def get_snapshots(self, session_id: UUID) -> Sequence[BacktestSnapshot]:
        """Get all snapshots for a session, ordered by simulated_at."""
        try:
            stmt = (
                select(BacktestSnapshot)
                .where(BacktestSnapshot.session_id == session_id)
                .order_by(BacktestSnapshot.simulated_at.asc())
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("backtest_repo.get_snapshots.error", error=str(exc))
            raise DatabaseError("Failed to fetch backtest snapshots.") from exc

    # ── Analytics ────────────────────────────────────────────────────────

    async def get_best_session(
        self,
        account_id: UUID,
        metric: str = "roi_pct",
        strategy_label: str | None = None,
        agent_id: UUID | None = None,
    ) -> BacktestSession | None:
        """Find the best completed session by a given metric."""
        try:
            stmt = select(BacktestSession).where(
                BacktestSession.account_id == account_id,
                BacktestSession.status == "completed",
            )
            if agent_id is not None:
                stmt = stmt.where(BacktestSession.agent_id == agent_id)
            if strategy_label is not None:
                stmt = stmt.where(BacktestSession.strategy_label == strategy_label)

            sort_col = getattr(BacktestSession, metric, BacktestSession.roi_pct)
            stmt = stmt.order_by(sort_col.desc().nullslast()).limit(1)

            result = await self._session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as exc:
            logger.exception("backtest_repo.get_best_session.error", error=str(exc))
            raise DatabaseError("Failed to fetch best backtest session.") from exc

    async def get_sessions_for_compare(
        self,
        session_ids: list[UUID],
        agent_id: UUID | None = None,
    ) -> Sequence[BacktestSession]:
        """Fetch multiple sessions for side-by-side comparison."""
        try:
            stmt = select(BacktestSession).where(BacktestSession.id.in_(session_ids))
            if agent_id is not None:
                stmt = stmt.where(BacktestSession.agent_id == agent_id)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("backtest_repo.get_sessions_for_compare.error", error=str(exc))
            raise DatabaseError("Failed to fetch sessions for comparison.") from exc

    # ── Cleanup ──────────────────────────────────────────────────────────

    async def delete_old_detail_data(self, days: int = 90) -> int:
        """Delete trades and snapshots older than *days*, keeping session summaries.

        Returns:
            Total number of rows deleted.
        """
        try:
            cutoff = datetime.now(tz=UTC) - timedelta(days=days)

            # Find old completed sessions
            old_sessions = select(BacktestSession.id).where(
                BacktestSession.status.in_(["completed", "cancelled", "failed"]),
                BacktestSession.completed_at < cutoff,
            )

            trades_stmt = delete(BacktestTrade).where(BacktestTrade.session_id.in_(old_sessions))
            snaps_stmt = delete(BacktestSnapshot).where(BacktestSnapshot.session_id.in_(old_sessions))

            r1 = await self._session.execute(trades_stmt)
            r2 = await self._session.execute(snaps_stmt)
            await self._session.flush()

            total = (r1.rowcount or 0) + (r2.rowcount or 0)
            logger.info(
                "backtest_repo.cleanup",
                deleted_rows=total,
                cutoff=cutoff.isoformat(),
            )
            return total
        except SQLAlchemyError as exc:
            logger.exception("backtest_repo.delete_old_detail_data.error", error=str(exc))
            raise DatabaseError("Failed to clean up old backtest data.") from exc
