"""Repository for PortfolioSnapshot CRUD and history query operations.

All database access for :class:`~src.database.models.PortfolioSnapshot` rows
goes through :class:`SnapshotRepository`.  Service classes must never issue raw
SQLAlchemy queries for portfolio snapshots directly.

``SnapshotRepository`` is insert-oriented: snapshots are immutable once created
(they form an append-only time-series for charting).  The primary write
operation is :meth:`create`; the read methods cover the query patterns used by
the portfolio tracker, analytics routes, and Celery snapshot tasks.

Dependency direction:
    PortfolioTracker / SnapshotTask → SnapshotRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

import structlog
from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import PortfolioSnapshot
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)

#: Valid snapshot granularities as defined by the DB check constraint.
_VALID_TYPES: frozenset[str] = frozenset({"minute", "hourly", "daily"})


class SnapshotRepository:
    """Async CRUD repository for the ``portfolio_snapshots`` hypertable.

    All methods operate within the injected ``AsyncSession``.  Callers are
    responsible for committing; this repository never calls
    ``session.commit()`` so that multiple repo operations can participate in
    a single atomic transaction.

    ``portfolio_snapshots`` is a TimescaleDB hypertable partitioned by
    ``created_at`` (1-day chunks).  The composite index
    ``idx_snapshots_account_type`` on ``(account_id, snapshot_type,
    created_at)`` is used for all filtered history queries.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.

    Example::

        async with session_factory() as session:
            repo = SnapshotRepository(session)
            snap = await repo.create(new_snapshot)
            await session.commit()
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(self, snapshot: PortfolioSnapshot) -> PortfolioSnapshot:
        """Persist a new :class:`PortfolioSnapshot` row and flush for server defaults.

        The ``id`` and ``created_at`` columns are populated by the database on
        flush.  The caller must commit the session to make the row durable.

        Args:
            snapshot: A fully-populated (but not yet persisted)
                ``PortfolioSnapshot`` instance.  ``account_id``,
                ``snapshot_type``, ``total_equity``, ``available_cash``,
                ``position_value``, ``unrealized_pnl``, and ``realized_pnl``
                must be set.

        Returns:
            The same ``snapshot`` instance with server-generated columns
            filled (``id``, ``created_at``).

        Raises:
            DatabaseError: On any SQLAlchemy / database error, including
                foreign-key violations for a missing ``account_id`` or a
                ``snapshot_type`` value that violates the check constraint.

        Example::

            from decimal import Decimal
            snap = PortfolioSnapshot(
                account_id=acct.id,
                snapshot_type="minute",
                total_equity=Decimal("10523.45"),
                available_cash=Decimal("5000.00"),
                position_value=Decimal("5523.45"),
                unrealized_pnl=Decimal("523.45"),
                realized_pnl=Decimal("0.00"),
            )
            created = await repo.create(snap)
            await session.commit()
        """
        try:
            self._session.add(snapshot)
            await self._session.flush()
            await self._session.refresh(snapshot)
            logger.info(
                "snapshot.created",
                extra={
                    "snapshot_id": str(snapshot.id),
                    "account_id": str(snapshot.account_id),
                    "snapshot_type": snapshot.snapshot_type,
                    "total_equity": str(snapshot.total_equity),
                    "created_at": snapshot.created_at.isoformat()
                    if snapshot.created_at
                    else None,
                },
            )
            return snapshot
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception(
                "snapshot.create.integrity_error",
                extra={
                    "account_id": str(snapshot.account_id),
                    "snapshot_type": snapshot.snapshot_type,
                    "error": str(exc),
                },
            )
            raise DatabaseError(
                f"Integrity error while creating portfolio snapshot: {exc}"
            ) from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "snapshot.create.db_error",
                extra={
                    "account_id": str(snapshot.account_id),
                    "error": str(exc),
                },
            )
            raise DatabaseError("Failed to create portfolio snapshot.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_history(
        self,
        account_id: UUID,
        snapshot_type: str,
        *,
        limit: int = 100,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> Sequence[PortfolioSnapshot]:
        """Return a time-ordered history of snapshots for one account and type.

        Results are ordered by ``created_at`` descending (newest first) so
        charting consumers always receive the most recent equity points at the
        top of the response.

        Uses the composite index ``idx_snapshots_account_type`` on
        ``(account_id, snapshot_type, created_at)`` for efficient filtering.

        Args:
            account_id:     The owning account's UUID.
            snapshot_type:  Granularity to query: ``"minute"``, ``"hourly"``,
                            or ``"daily"``.
            limit:          Maximum number of rows to return (default 100).
            since:          Optional inclusive lower bound on ``created_at``
                            (UTC).  Useful for fetching snapshots after a
                            known timestamp (e.g. last chart refresh).
            until:          Optional inclusive upper bound on ``created_at``
                            (UTC).  Useful for paginating backward in time.

        Returns:
            A (possibly empty) sequence of :class:`PortfolioSnapshot`
            instances, ordered by ``created_at`` descending.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            # Most recent 60 minute-granularity snapshots
            history = await repo.get_history(acct.id, "minute", limit=60)

            # Hourly snapshots in a specific window
            from datetime import datetime, timezone
            history = await repo.get_history(
                acct.id,
                "hourly",
                since=datetime(2026, 2, 1, tzinfo=timezone.utc),
                until=datetime(2026, 2, 24, tzinfo=timezone.utc),
                limit=24,
            )
        """
        try:
            stmt = (
                select(PortfolioSnapshot)
                .where(
                    PortfolioSnapshot.account_id == account_id,
                    PortfolioSnapshot.snapshot_type == snapshot_type,
                )
                .order_by(PortfolioSnapshot.created_at.desc())
                .limit(limit)
            )
            if since is not None:
                stmt = stmt.where(PortfolioSnapshot.created_at >= since)
            if until is not None:
                stmt = stmt.where(PortfolioSnapshot.created_at <= until)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "snapshot.get_history.db_error",
                extra={
                    "account_id": str(account_id),
                    "snapshot_type": snapshot_type,
                    "error": str(exc),
                },
            )
            raise DatabaseError(
                f"Failed to fetch snapshot history for account '{account_id}'."
            ) from exc

    async def get_latest(
        self,
        account_id: UUID,
        snapshot_type: str,
    ) -> PortfolioSnapshot | None:
        """Return the single most-recent snapshot for an account and type.

        Used by the portfolio tracker to read the last known equity value
        before generating a diff or capturing a new snapshot.

        Args:
            account_id:    The owning account's UUID.
            snapshot_type: Granularity: ``"minute"``, ``"hourly"``, or
                           ``"daily"``.

        Returns:
            The most recent :class:`PortfolioSnapshot`, or ``None`` if no
            snapshot of the given type exists for the account yet.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            latest = await repo.get_latest(acct.id, "hourly")
            if latest:
                print(f"Last hourly equity: {latest.total_equity}")
        """
        try:
            stmt = (
                select(PortfolioSnapshot)
                .where(
                    PortfolioSnapshot.account_id == account_id,
                    PortfolioSnapshot.snapshot_type == snapshot_type,
                )
                .order_by(PortfolioSnapshot.created_at.desc())
                .limit(1)
            )
            result = await self._session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as exc:
            logger.exception(
                "snapshot.get_latest.db_error",
                extra={
                    "account_id": str(account_id),
                    "snapshot_type": snapshot_type,
                    "error": str(exc),
                },
            )
            raise DatabaseError(
                f"Failed to fetch latest snapshot for account '{account_id}'."
            ) from exc

    async def list_by_account(
        self,
        account_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[PortfolioSnapshot]:
        """Return a paginated list of all snapshot types for an account.

        Useful for admin dashboards and account history views that need an
        unfiltered view across all granularities.  Results are ordered by
        ``created_at`` descending.

        Args:
            account_id: The owning account's UUID.
            limit:      Maximum number of rows to return (default 100).
            offset:     Number of rows to skip for pagination (default 0).

        Returns:
            A (possibly empty) sequence of :class:`PortfolioSnapshot`
            instances across all snapshot types, ordered newest-first.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            all_snaps = await repo.list_by_account(acct.id, limit=200)
        """
        try:
            stmt = (
                select(PortfolioSnapshot)
                .where(PortfolioSnapshot.account_id == account_id)
                .order_by(PortfolioSnapshot.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "snapshot.list_by_account.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError(
                f"Failed to list snapshots for account '{account_id}'."
            ) from exc

    async def delete_before(
        self,
        account_id: UUID,
        snapshot_type: str,
        cutoff: datetime,
    ) -> int:
        """Delete snapshots older than ``cutoff`` for a given account and type.

        Used by the cleanup Celery task to prune high-frequency ``"minute"``
        snapshots after they have been rolled up into hourly/daily aggregates,
        keeping the hypertable from growing unboundedly.

        The ``cutoff`` should always be a timezone-aware UTC datetime.

        Args:
            account_id:    The owning account's UUID.
            snapshot_type: Granularity whose old rows will be pruned.
            cutoff:        Delete rows where ``created_at < cutoff``.

        Returns:
            The number of rows deleted.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            from datetime import datetime, timedelta, timezone
            cutoff = datetime.now(tz=timezone.utc) - timedelta(days=2)
            deleted = await repo.delete_before(acct.id, "minute", cutoff)
            await session.commit()
        """
        from sqlalchemy import delete as sa_delete  # local import avoids shadowing

        try:
            stmt = sa_delete(PortfolioSnapshot).where(
                PortfolioSnapshot.account_id == account_id,
                PortfolioSnapshot.snapshot_type == snapshot_type,
                PortfolioSnapshot.created_at < cutoff,
            )
            result = await self._session.execute(stmt)
            deleted: int = result.rowcount  # type: ignore[assignment]
            logger.info(
                "snapshot.delete_before.done",
                extra={
                    "account_id": str(account_id),
                    "snapshot_type": snapshot_type,
                    "cutoff": cutoff.isoformat(),
                    "deleted_rows": deleted,
                },
            )
            return deleted
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "snapshot.delete_before.db_error",
                extra={
                    "account_id": str(account_id),
                    "snapshot_type": snapshot_type,
                    "cutoff": cutoff.isoformat(),
                    "error": str(exc),
                },
            )
            raise DatabaseError(
                f"Failed to prune snapshots for account '{account_id}'."
            ) from exc
