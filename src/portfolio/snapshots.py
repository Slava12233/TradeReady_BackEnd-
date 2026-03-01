"""Portfolio Snapshot Service — Component 6.

Background service that captures periodic portfolio snapshots for charting and
analysis.  Snapshots are written to the ``portfolio_snapshots`` TimescaleDB
hypertable at three granularities:

* **minute** — Quick equity snapshot; no metrics.  Captured every 1 minute by
  a Celery beat task.
* **hourly** — Full position breakdown with serialised position data.  Metrics
  are omitted to keep the hot path fast; a separate analytics query can be run
  on demand.  Captured every 1 hour.
* **daily** — Comprehensive performance report including serialised metrics.
  Captured once per UTC calendar day.

Dependency direction::

    Celery tasks / API routes → SnapshotService
        → PortfolioTracker   (current equity, positions, PnL)
        → PerformanceMetrics (metrics for daily snapshots)
        → SnapshotRepository (DB persistence)
        → AsyncSession

Classes
-------
Snapshot
    Lightweight read-only view of a persisted snapshot row — returned by
    :meth:`SnapshotService.get_snapshot_history` so callers receive typed
    ``Decimal`` values instead of raw ORM objects.

SnapshotService
    Async service for capturing and querying periodic portfolio snapshots.

Example::

    async with session_factory() as session:
        svc = SnapshotService(session, price_cache, settings)
        await svc.capture_minute_snapshot(account_id)
        await session.commit()

    history = await svc.get_snapshot_history(account_id, "hourly", limit=24)
    for snap in history:
        print(snap.total_equity, snap.created_at)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.cache.price_cache import PriceCache
from src.config import Settings
from src.database.models import PortfolioSnapshot
from src.database.repositories.snapshot_repo import SnapshotRepository
from src.portfolio.metrics import PerformanceMetrics
from src.portfolio.tracker import PortfolioTracker
from src.utils.exceptions import AccountNotFoundError, CacheError, DatabaseError

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")

# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class Snapshot:
    """Read-only view of a persisted portfolio snapshot row.

    Returned by :meth:`SnapshotService.get_snapshot_history` so API routes and
    Celery tasks receive typed ``Decimal`` values and do not depend on the ORM
    model directly.

    Attributes:
        id:              UUID of the snapshot row.
        account_id:      UUID of the owning account.
        snapshot_type:   Granularity: ``"minute"``, ``"hourly"``, or
                         ``"daily"``.
        total_equity:    Total portfolio value in USDT at capture time.
        available_cash:  Free USDT balance at capture time.
        position_value:  Market value of all non-USDT holdings.
        unrealized_pnl:  Aggregate open PnL across all positions.
        realized_pnl:    Cumulative realised PnL at capture time.
        positions:       Serialised position data (``None`` for minute
                         snapshots).
        metrics:         Serialised performance metrics (daily snapshots only;
                         ``None`` otherwise).
        created_at:      UTC timestamp of when the snapshot was captured.
    """

    id: UUID
    account_id: UUID
    snapshot_type: str
    total_equity: Decimal
    available_cash: Decimal
    position_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    positions: list[dict[str, Any]] | None
    metrics: dict[str, Any] | None
    created_at: datetime


# ---------------------------------------------------------------------------
# SnapshotService
# ---------------------------------------------------------------------------


class SnapshotService:
    """Periodic portfolio snapshot capture and history query service.

    Captures three tiers of snapshot granularity:

    * :meth:`capture_minute_snapshot` — fast equity-only capture (no positions
      JSON, no metrics).  Designed to run every minute via Celery beat.
    * :meth:`capture_hourly_snapshot` — equity + full serialised positions.
      Designed to run every hour.
    * :meth:`capture_daily_snapshot` — equity + positions + serialised
      performance metrics.  Designed to run once per UTC day.

    All *capture_* methods create and flush the new
    :class:`~src.database.models.PortfolioSnapshot` row via
    :class:`~src.database.repositories.snapshot_repo.SnapshotRepository` but
    do **not** commit — the caller (Celery task or route handler) is
    responsible for the final ``session.commit()``.

    Args:
        session:     An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        price_cache: Initialised :class:`~src.cache.price_cache.PriceCache`.
        settings:    Application :class:`~src.config.Settings`.

    Example::

        async with session_factory() as session:
            svc = SnapshotService(session, price_cache, settings)
            await svc.capture_daily_snapshot(account_id)
            await session.commit()
    """

    def __init__(
        self,
        session: AsyncSession,
        price_cache: PriceCache,
        settings: Settings,
    ) -> None:
        self._session = session
        self._price_cache = price_cache
        self._settings = settings
        self._tracker = PortfolioTracker(session, price_cache, settings)
        self._perf = PerformanceMetrics(session)
        self._repo = SnapshotRepository(session)

    # ------------------------------------------------------------------
    # Public API — capture
    # ------------------------------------------------------------------

    async def capture_minute_snapshot(self, account_id: UUID) -> None:
        """Capture a lightweight equity-only snapshot for *account_id*.

        Fetches the current portfolio summary from :class:`PortfolioTracker`
        and persists a ``"minute"``-granularity row.  The ``positions`` and
        ``metrics`` JSONB columns are left ``None`` to keep the write as cheap
        as possible.

        Args:
            account_id: UUID of the account to snapshot.

        Raises:
            AccountNotFoundError: If no account row exists for *account_id*.
            DatabaseError:        On any SQLAlchemy / database error.
            CacheError:           On any Redis connectivity error.

        Example::

            await svc.capture_minute_snapshot(account_id)
            await session.commit()
        """
        summary = await self._tracker.get_portfolio(account_id)

        snap = PortfolioSnapshot(
            account_id=account_id,
            snapshot_type="minute",
            total_equity=float(summary.total_equity),
            available_cash=float(summary.available_cash),
            position_value=float(summary.total_position_value),
            unrealized_pnl=float(summary.unrealized_pnl),
            realized_pnl=float(summary.realized_pnl),
            positions=None,
            metrics=None,
        )
        await self._repo.create(snap)
        logger.info(
            "snapshot.minute.captured",
            extra={
                "account_id": str(account_id),
                "total_equity": str(summary.total_equity),
            },
        )

    async def capture_hourly_snapshot(self, account_id: UUID) -> None:
        """Capture a full position-breakdown snapshot for *account_id*.

        Fetches the current portfolio summary and all open positions, serialises
        them to JSON-compatible dicts, and persists an ``"hourly"``-granularity
        row.  The ``metrics`` column is left ``None`` — hourly metrics are
        computed on demand by :class:`~src.portfolio.metrics.PerformanceMetrics`.

        Args:
            account_id: UUID of the account to snapshot.

        Raises:
            AccountNotFoundError: If no account row exists for *account_id*.
            DatabaseError:        On any SQLAlchemy / database error.
            CacheError:           On any Redis connectivity error.

        Example::

            await svc.capture_hourly_snapshot(account_id)
            await session.commit()
        """
        summary = await self._tracker.get_portfolio(account_id)
        positions_data = _serialise_positions(summary.positions)

        snap = PortfolioSnapshot(
            account_id=account_id,
            snapshot_type="hourly",
            total_equity=float(summary.total_equity),
            available_cash=float(summary.available_cash),
            position_value=float(summary.total_position_value),
            unrealized_pnl=float(summary.unrealized_pnl),
            realized_pnl=float(summary.realized_pnl),
            positions=positions_data,
            metrics=None,
        )
        await self._repo.create(snap)
        logger.info(
            "snapshot.hourly.captured",
            extra={
                "account_id": str(account_id),
                "total_equity": str(summary.total_equity),
                "open_positions": len(summary.positions),
            },
        )

    async def capture_daily_snapshot(self, account_id: UUID) -> None:
        """Capture a comprehensive daily performance snapshot for *account_id*.

        Fetches the current portfolio summary, open positions, and all-time
        performance metrics, serialises them, and persists a ``"daily"``-
        granularity row.  The ``metrics`` JSONB column contains the full output
        of :meth:`~src.portfolio.metrics.PerformanceMetrics.calculate` for the
        ``"all"`` period.

        Args:
            account_id: UUID of the account to snapshot.

        Raises:
            AccountNotFoundError: If no account row exists for *account_id*.
            DatabaseError:        On any SQLAlchemy / database error.
            CacheError:           On any Redis connectivity error.

        Example::

            await svc.capture_daily_snapshot(account_id)
            await session.commit()
        """
        summary = await self._tracker.get_portfolio(account_id)
        positions_data = _serialise_positions(summary.positions)
        m = await self._perf.calculate(account_id, period="all")
        metrics_data = _serialise_metrics(m)

        snap = PortfolioSnapshot(
            account_id=account_id,
            snapshot_type="daily",
            total_equity=float(summary.total_equity),
            available_cash=float(summary.available_cash),
            position_value=float(summary.total_position_value),
            unrealized_pnl=float(summary.unrealized_pnl),
            realized_pnl=float(summary.realized_pnl),
            positions=positions_data,
            metrics=metrics_data,
        )
        await self._repo.create(snap)
        logger.info(
            "snapshot.daily.captured",
            extra={
                "account_id": str(account_id),
                "total_equity": str(summary.total_equity),
                "total_trades": m.total_trades,
                "sharpe_ratio": m.sharpe_ratio,
            },
        )

    # ------------------------------------------------------------------
    # Public API — query
    # ------------------------------------------------------------------

    async def get_snapshot_history(
        self,
        account_id: UUID,
        snapshot_type: str,
        limit: int = 100,
    ) -> list[Snapshot]:
        """Return a time-ordered list of snapshots for *account_id*.

        Delegates to :meth:`~src.database.repositories.snapshot_repo.SnapshotRepository.get_history`
        and converts the ORM rows to :class:`Snapshot` dataclass instances so
        callers receive typed ``Decimal`` values and do not hold open ORM state.

        Results are ordered newest-first (``created_at`` descending).

        Args:
            account_id:    UUID of the account to query.
            snapshot_type: Granularity to query: ``"minute"``, ``"hourly"``,
                           or ``"daily"``.
            limit:         Maximum number of rows to return (default 100).

        Returns:
            A list of :class:`Snapshot` objects, newest first.  Returns an
            empty list if no snapshots of the requested type exist.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            history = await svc.get_snapshot_history(account_id, "hourly", limit=24)
            for snap in history:
                print(f"{snap.created_at.isoformat()} equity={snap.total_equity}")
        """
        rows = await self._repo.get_history(
            account_id,
            snapshot_type,
            limit=limit,
        )
        return [_orm_to_snapshot(row) for row in rows]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _serialise_positions(
    positions: list,
) -> list[dict[str, Any]]:
    """Convert a list of :class:`~src.portfolio.tracker.PositionView` objects
    to a JSON-serialisable list of dicts.

    All ``Decimal`` fields are converted to ``str`` to survive round-tripping
    through PostgreSQL JSONB without loss of precision.

    Args:
        positions: List of ``PositionView`` dataclass instances.

    Returns:
        A list of plain dicts suitable for JSONB storage.
    """
    result: list[dict[str, Any]] = []
    for pos in positions:
        result.append(
            {
                "symbol": pos.symbol,
                "asset": pos.asset,
                "quantity": str(pos.quantity),
                "avg_entry_price": str(pos.avg_entry_price),
                "current_price": str(pos.current_price),
                "market_value": str(pos.market_value),
                "cost_basis": str(pos.cost_basis),
                "unrealized_pnl": str(pos.unrealized_pnl),
                "unrealized_pnl_pct": str(pos.unrealized_pnl_pct),
                "realized_pnl": str(pos.realized_pnl),
                "price_available": pos.price_available,
            }
        )
    return result


def _serialise_metrics(m: Any) -> dict[str, Any]:
    """Convert a :class:`~src.portfolio.metrics.Metrics` dataclass to a
    JSON-serialisable dict.

    ``Decimal`` fields are converted to ``str``; all other fields (``float``,
    ``int``, ``str``) are copied as-is.

    Args:
        m: A fully-populated :class:`~src.portfolio.metrics.Metrics` instance.

    Returns:
        A plain dict suitable for JSONB storage.
    """
    return {
        "period": m.period,
        "sharpe_ratio": m.sharpe_ratio,
        "sortino_ratio": m.sortino_ratio,
        "max_drawdown": m.max_drawdown,
        "max_drawdown_duration": m.max_drawdown_duration,
        "win_rate": m.win_rate,
        "profit_factor": m.profit_factor,
        "avg_win": str(m.avg_win),
        "avg_loss": str(m.avg_loss),
        "total_trades": m.total_trades,
        "avg_trades_per_day": m.avg_trades_per_day,
        "best_trade": str(m.best_trade),
        "worst_trade": str(m.worst_trade),
        "current_streak": m.current_streak,
    }


def _orm_to_snapshot(row: PortfolioSnapshot) -> Snapshot:
    """Convert a :class:`~src.database.models.PortfolioSnapshot` ORM row to a
    :class:`Snapshot` dataclass.

    All numeric columns stored as ``float`` / ``Numeric`` are cast to
    ``Decimal`` for exact arithmetic in downstream code.

    Args:
        row: A hydrated :class:`~src.database.models.PortfolioSnapshot`
             instance retrieved from the database.

    Returns:
        A typed, immutable :class:`Snapshot` dataclass.
    """
    return Snapshot(
        id=row.id,
        account_id=row.account_id,
        snapshot_type=row.snapshot_type,
        total_equity=Decimal(str(row.total_equity)),
        available_cash=Decimal(str(row.available_cash)),
        position_value=Decimal(str(row.position_value)),
        unrealized_pnl=Decimal(str(row.unrealized_pnl)),
        realized_pnl=Decimal(str(row.realized_pnl)),
        positions=row.positions,
        metrics=row.metrics,
        created_at=row.created_at,
    )
