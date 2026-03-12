"""Repository for querying raw tick data from the TimescaleDB hypertable.

All database access for :class:`~src.database.models.Tick` rows goes
through :class:`TickRepository`.  Service classes — analytics, portfolio
tracker, candle builders — must never issue raw SQLAlchemy queries for
ticks directly.

``TickRepository`` is read-only: ticks are written exclusively by the price
ingestion service via asyncpg ``COPY`` (see ``src/price_ingestion/tick_buffer.py``).
No write methods are provided here.

TimescaleDB query notes:
    - Always filter ``Tick.symbol`` first; the composite index
      ``idx_ticks_symbol_time`` on ``(symbol, time DESC)`` enables chunk
      exclusion and avoids full hypertable scans.
    - Prefer bounded time ranges over unbounded queries to allow TimescaleDB
      to skip irrelevant chunks.
    - ``get_latest`` uses ``LIMIT 1`` with descending time — this is the
      fast path for slippage calculations and health checks.

Dependency direction:
    Analytics / Portfolio / Slippage → TickRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import Tick
from src.utils.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class TickRepository:
    """Async read-only repository for the ``ticks`` hypertable.

    All methods operate within the injected ``AsyncSession``.  Because this
    repository never writes, no commit is required by the caller.

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.

    Example::

        async with session_factory() as session:
            repo = TickRepository(session)
            ticks = await repo.get_range("BTCUSDT", since=start_dt, until=end_dt)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_latest(self, symbol: str) -> Tick | None:
        """Return the single most-recent tick for *symbol*.

        Uses ``idx_ticks_symbol_time`` (symbol + time DESC) so TimescaleDB
        can satisfy this query from the latest chunk without a full scan.

        Args:
            symbol: The trading pair to query, e.g. ``"BTCUSDT"``.

        Returns:
            The most recent :class:`Tick` instance, or ``None`` if no tick
            has been recorded for this symbol yet.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            tick = await repo.get_latest("ETHUSDT")
            if tick is None:
                raise PriceNotAvailableError(symbol="ETHUSDT")
            current_price = tick.price
        """
        try:
            stmt = select(Tick).where(Tick.symbol == symbol).order_by(Tick.time.desc()).limit(1)
            result = await self._session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as exc:
            logger.exception(
                "tick_repo.get_latest.db_error",
                extra={"symbol": symbol, "error": str(exc)},
            )
            raise DatabaseError(f"Failed to fetch latest tick for symbol '{symbol}'.") from exc

    async def get_range(
        self,
        symbol: str,
        *,
        since: datetime,
        until: datetime | None = None,
        limit: int | None = None,
    ) -> Sequence[Tick]:
        """Return ticks for *symbol* within a UTC time range, oldest first.

        Results are ordered ``time ASC`` so callers can iterate
        chronologically (e.g. when building OHLCV candles or computing
        time-series metrics).

        The query always filters ``symbol`` first so TimescaleDB's composite
        index on ``(symbol, time DESC)`` can prune irrelevant chunks before
        the range predicate is applied.

        Args:
            symbol: Trading pair to query, e.g. ``"BTCUSDT"``.
            since:  Lower bound (inclusive).  Must be timezone-aware (UTC).
            until:  Upper bound (inclusive).  Defaults to the current UTC
                    moment when ``None``.
            limit:  Optional cap on the number of rows returned.  When
                    ``None``, all ticks within the range are returned —
                    use with caution on large windows.

        Returns:
            A (possibly empty) sequence of :class:`Tick` instances ordered
            by ``time`` ascending.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            from datetime import datetime, timezone, timedelta

            now = datetime.now(tz=timezone.utc)
            ticks = await repo.get_range(
                "BTCUSDT",
                since=now - timedelta(minutes=5),
                until=now,
            )
        """
        if until is None:
            until = datetime.now(tz=UTC)

        try:
            stmt = (
                select(Tick)
                .where(
                    Tick.symbol == symbol,
                    Tick.time >= since,
                    Tick.time <= until,
                )
                .order_by(Tick.time.asc())
            )
            if limit is not None:
                stmt = stmt.limit(limit)

            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "tick_repo.get_range.db_error",
                extra={
                    "symbol": symbol,
                    "since": since.isoformat(),
                    "until": until.isoformat(),
                    "error": str(exc),
                },
            )
            raise DatabaseError(f"Failed to fetch tick range for symbol '{symbol}'.") from exc

    async def get_price_at(self, symbol: str, *, at: datetime) -> Tick | None:
        """Return the tick closest to (but not after) *at* for *symbol*.

        This is the "price-at-time" lookup used by analytics to reconstruct
        historical portfolio valuations.  It selects the last tick whose
        ``time <= at``, which gives the best available execution price at
        the requested moment.

        Args:
            symbol: Trading pair to query, e.g. ``"BTCUSDT"``.
            at:     Target timestamp (timezone-aware, UTC).

        Returns:
            The most recent :class:`Tick` at or before *at*, or ``None``
            if no tick exists in the database up to that point.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            from datetime import datetime, timezone

            snapshot_time = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)
            tick = await repo.get_price_at("SOLUSDT", at=snapshot_time)
            price_then = tick.price if tick else None
        """
        try:
            stmt = (
                select(Tick)
                .where(
                    Tick.symbol == symbol,
                    Tick.time <= at,
                )
                .order_by(Tick.time.desc())
                .limit(1)
            )
            result = await self._session.execute(stmt)
            return result.scalars().first()
        except SQLAlchemyError as exc:
            logger.exception(
                "tick_repo.get_price_at.db_error",
                extra={
                    "symbol": symbol,
                    "at": at.isoformat(),
                    "error": str(exc),
                },
            )
            raise DatabaseError(f"Failed to fetch tick at timestamp for symbol '{symbol}'.") from exc

    async def count_in_range(
        self,
        symbol: str,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> int:
        """Return the number of ticks for *symbol* within a UTC time range.

        Used by health checks to verify that ticks are flowing for a pair
        (e.g. ``count_in_range("BTCUSDT", since=now - 60s) > 0``).

        Args:
            symbol: Trading pair to query.
            since:  Lower bound (inclusive), timezone-aware UTC.
            until:  Upper bound (inclusive).  Defaults to the current UTC
                    moment when ``None``.

        Returns:
            Integer count of matching ticks (``0`` if none).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            from datetime import datetime, timezone, timedelta

            now = datetime.now(tz=timezone.utc)
            count = await repo.count_in_range(
                "BTCUSDT", since=now - timedelta(seconds=60)
            )
            is_fresh = count > 0
        """
        if until is None:
            until = datetime.now(tz=UTC)

        try:
            stmt = select(sa_func.count()).where(
                Tick.symbol == symbol,
                Tick.time >= since,
                Tick.time <= until,
            )
            result = await self._session.execute(stmt)
            return int(result.scalar_one())
        except SQLAlchemyError as exc:
            logger.exception(
                "tick_repo.count_in_range.db_error",
                extra={
                    "symbol": symbol,
                    "since": since.isoformat(),
                    "until": until.isoformat(),
                    "error": str(exc),
                },
            )
            raise DatabaseError(f"Failed to count ticks in range for symbol '{symbol}'.") from exc

    async def get_vwap(
        self,
        symbol: str,
        *,
        since: datetime,
        until: datetime | None = None,
    ) -> Decimal | None:
        """Compute the volume-weighted average price (VWAP) for *symbol*.

        VWAP = SUM(price * quantity) / SUM(quantity) over the requested
        window.  Returns ``None`` when there are no ticks in the range (to
        distinguish "no data" from a zero price).

        Used by the slippage calculator and portfolio tracker to estimate
        a realistic average execution price for large orders.

        Args:
            symbol: Trading pair to query, e.g. ``"BTCUSDT"``.
            since:  Start of the VWAP window (inclusive, UTC-aware).
            until:  End of the VWAP window (inclusive).  Defaults to the
                    current UTC moment when ``None``.

        Returns:
            VWAP as a ``Decimal``, or ``None`` if the window contains no ticks.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            from datetime import datetime, timezone, timedelta

            now = datetime.now(tz=timezone.utc)
            vwap = await repo.get_vwap(
                "BTCUSDT", since=now - timedelta(hours=1)
            )
            if vwap is None:
                raise PriceNotAvailableError(symbol="BTCUSDT")
        """
        if until is None:
            until = datetime.now(tz=UTC)

        try:
            stmt = select(
                sa_func.sum(Tick.price * Tick.quantity),
                sa_func.sum(Tick.quantity),
            ).where(
                Tick.symbol == symbol,
                Tick.time >= since,
                Tick.time <= until,
            )
            result = await self._session.execute(stmt)
            row = result.one()
            total_value, total_qty = row[0], row[1]

            if total_qty is None or total_qty == 0:
                return None
            return Decimal(str(total_value)) / Decimal(str(total_qty))
        except SQLAlchemyError as exc:
            logger.exception(
                "tick_repo.get_vwap.db_error",
                extra={
                    "symbol": symbol,
                    "since": since.isoformat(),
                    "until": until.isoformat(),
                    "error": str(exc),
                },
            )
            raise DatabaseError(f"Failed to compute VWAP for symbol '{symbol}'.") from exc
