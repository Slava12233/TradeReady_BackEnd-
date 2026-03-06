"""Repository for Trade CRUD and history query operations.

All database access for :class:`~src.database.models.Trade` rows goes
through :class:`TradeRepository`.  Service classes must never issue raw
SQLAlchemy queries for trades directly.

``TradeRepository`` is insert-only: trades are immutable once created.
The only write operation is :meth:`create`; the read methods cover the
query patterns used by the order engine, portfolio tracker, risk manager,
and REST API routes.

Dependency direction:
    OrderEngine / PortfolioTracker → TradeRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

import structlog
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Sequence
from uuid import UUID

from sqlalchemy import func as sa_func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Trade
from src.utils.exceptions import DatabaseError, TradeNotFoundError

logger = structlog.get_logger(__name__)


class TradeRepository:
    """Async CRUD repository for the ``trades`` table.

    All methods operate within the injected ``AsyncSession``.  Callers are
    responsible for committing; this repository never calls
    ``session.commit()`` so that multiple repo operations can participate in
    a single atomic transaction (e.g. recording a trade *and* updating
    balances in one commit).

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.

    Example::

        async with session_factory() as session:
            repo = TradeRepository(session)
            trade = await repo.create(new_trade)
            await session.commit()
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(self, trade: Trade) -> Trade:
        """Persist a new :class:`Trade` row and flush to obtain server defaults.

        The ``id`` and ``created_at`` columns are populated by the database
        on flush.  The caller must commit the session to make the row
        durable.

        Args:
            trade: A fully-populated (but not yet persisted) Trade instance.
                   ``account_id``, ``order_id``, ``symbol``, ``side``,
                   ``quantity``, ``price``, ``quote_amount``, and ``fee``
                   must be set.

        Returns:
            The same ``trade`` instance with server-generated columns filled.

        Raises:
            DatabaseError: On any SQLAlchemy / database error (including
                foreign-key violations for missing ``account_id`` or
                ``order_id``).

        Example::

            from decimal import Decimal
            trade = Trade(
                account_id=acct.id,
                order_id=order.id,
                session_id=session_id,
                symbol="BTCUSDT",
                side="buy",
                quantity=Decimal("0.01"),
                price=Decimal("50100.00"),
                quote_amount=Decimal("501.00"),
                fee=Decimal("0.501"),
                realized_pnl=None,
            )
            created = await repo.create(trade)
            await session.commit()
        """
        try:
            self._session.add(trade)
            await self._session.flush()
            await self._session.refresh(trade)
            logger.info(
                "trade.created",
                extra={
                    "trade_id": str(trade.id),
                    "account_id": str(trade.account_id),
                    "order_id": str(trade.order_id),
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "quantity": str(trade.quantity),
                    "price": str(trade.price),
                    "fee": str(trade.fee),
                },
            )
            return trade
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception(
                "trade.create.integrity_error",
                extra={
                    "account_id": str(trade.account_id),
                    "order_id": str(trade.order_id),
                    "error": str(exc),
                },
            )
            raise DatabaseError(
                f"Integrity error while creating trade: {exc}"
            ) from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "trade.create.db_error",
                extra={"account_id": str(trade.account_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to create trade.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(self, trade_id: UUID, *, account_id: UUID | None = None) -> Trade:
        """Fetch a single trade by its primary-key UUID.

        When ``account_id`` is provided an ownership filter is added, so that
        agents cannot read another account's trade records.

        Args:
            trade_id:   The trade's UUID primary key.
            account_id: Optional owning account UUID for ownership enforcement.

        Returns:
            The matching :class:`Trade` instance.

        Raises:
            TradeNotFoundError: If no trade with ``trade_id`` exists (or it
                does not belong to ``account_id`` when supplied).
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            trade = await repo.get_by_id(uuid.UUID("..."))
            # with ownership check:
            trade = await repo.get_by_id(uuid.UUID("..."), account_id=acct.id)
        """
        try:
            stmt = select(Trade).where(Trade.id == trade_id)
            if account_id is not None:
                stmt = stmt.where(Trade.account_id == account_id)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise TradeNotFoundError(trade_id=trade_id)
            return row
        except TradeNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception(
                "trade.get_by_id.db_error",
                extra={"trade_id": str(trade_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to fetch trade by ID.") from exc

    async def list_by_account(
        self,
        account_id: UUID,
        *,
        symbol: str | None = None,
        side: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Trade]:
        """Return a paginated list of trades for an account.

        Results are ordered by ``created_at`` descending (newest first) so
        agents see their most recent activity at the top.

        Uses the composite index ``idx_trades_account_time`` on
        ``(account_id, created_at)`` for efficient filtering and ordering.

        Args:
            account_id: The owning account's UUID.
            symbol:     Optional filter; only return trades for this symbol
                        (e.g. ``"BTCUSDT"``).
            side:       Optional filter; only return ``"buy"`` or ``"sell"``
                        trades.
            limit:      Maximum number of rows to return (default 100).
            offset:     Number of rows to skip for pagination (default 0).

        Returns:
            A (possibly empty) sequence of :class:`Trade` instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            # All trades for account
            trades = await repo.list_by_account(acct.id)

            # Buy trades for BTCUSDT, newest 50
            trades = await repo.list_by_account(
                acct.id, symbol="BTCUSDT", side="buy", limit=50
            )
        """
        try:
            stmt = (
                select(Trade)
                .where(Trade.account_id == account_id)
                .order_by(Trade.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if symbol is not None:
                stmt = stmt.where(Trade.symbol == symbol)
            if side is not None:
                stmt = stmt.where(Trade.side == side)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "trade.list_by_account.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to list trades for account.") from exc

    async def count_by_account(
        self,
        account_id: UUID,
        *,
        symbol: str | None = None,
        side: str | None = None,
    ) -> int:
        """Return the total number of trades for an account (with optional filters).

        Args:
            account_id: The owning account's UUID.
            symbol:     Optional symbol filter.
            side:       Optional side filter.

        Returns:
            Integer count of matching trades.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
        """
        try:
            stmt = select(sa_func.count()).select_from(Trade).where(
                Trade.account_id == account_id,
            )
            if symbol is not None:
                stmt = stmt.where(Trade.symbol == symbol)
            if side is not None:
                stmt = stmt.where(Trade.side == side)
            result = await self._session.execute(stmt)
            return result.scalar_one()
        except SQLAlchemyError as exc:
            logger.exception(
                "trade.count_by_account.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to count trades for account.") from exc

    async def list_by_symbol(
        self,
        symbol: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Trade]:
        """Return a paginated list of trades across all accounts for a symbol.

        Results are ordered by ``created_at`` descending.  This is used by
        the ``GET /market/trades/{symbol}`` endpoint to show the platform's
        recent execution history for a trading pair.

        Uses the composite index ``idx_trades_symbol`` on
        ``(symbol, created_at)`` for efficient filtering.

        Args:
            symbol: The trading pair to query (e.g. ``"BTCUSDT"``).
            limit:  Maximum number of rows to return (default 100).
            offset: Number of rows to skip for pagination (default 0).

        Returns:
            A (possibly empty) sequence of :class:`Trade` instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            recent_btc_trades = await repo.list_by_symbol("BTCUSDT", limit=50)
        """
        try:
            stmt = (
                select(Trade)
                .where(Trade.symbol == symbol)
                .order_by(Trade.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "trade.list_by_symbol.db_error",
                extra={"symbol": symbol, "error": str(exc)},
            )
            raise DatabaseError(f"Failed to list trades for symbol '{symbol}'.") from exc

    async def get_daily_trades(
        self,
        account_id: UUID,
        *,
        day: date | None = None,
    ) -> Sequence[Trade]:
        """Return all trades executed by an account within a UTC calendar day.

        Used by the risk manager and circuit breaker to calculate the
        accumulated daily PnL and trade count for an account.

        When ``day`` is ``None``, defaults to today's UTC date.  The query
        is bounded to the half-open interval ``[midnight, midnight+1day)`` in
        UTC so results are always deterministic regardless of when the call
        is made.

        Uses the composite index ``idx_trades_account_time`` on
        ``(account_id, created_at)`` so the range scan is efficient even
        with a large trade history.

        Args:
            account_id: The owning account's UUID.
            day:        The calendar day to query (UTC).  Defaults to today.

        Returns:
            A (possibly empty) sequence of :class:`Trade` instances for the
            given day, ordered by ``created_at`` ascending (oldest first).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            from datetime import date
            # Today's trades (UTC)
            todays = await repo.get_daily_trades(acct.id)
            # A specific date
            historical = await repo.get_daily_trades(
                acct.id, day=date(2026, 2, 14)
            )
        """
        if day is None:
            day = datetime.now(tz=timezone.utc).date()

        day_start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        try:
            stmt = (
                select(Trade)
                .where(
                    Trade.account_id == account_id,
                    Trade.created_at >= day_start,
                    Trade.created_at < day_end,
                )
                .order_by(Trade.created_at.asc())
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "trade.get_daily_trades.db_error",
                extra={
                    "account_id": str(account_id),
                    "day": str(day),
                    "error": str(exc),
                },
            )
            raise DatabaseError(
                f"Failed to fetch daily trades for account '{account_id}'."
            ) from exc

    async def sum_daily_realized_pnl(
        self,
        account_id: UUID,
        *,
        day: date | None = None,
    ) -> Decimal:
        """Return the total realised PnL for an account within a UTC calendar day.

        Aggregates ``realized_pnl`` for all trades on the given day.
        Trades where ``realized_pnl`` is ``NULL`` (i.e. opening trades that
        don't close an existing position) are treated as zero by the
        ``COALESCE`` in the SQL sum.

        Used by the circuit breaker to determine whether the daily loss limit
        has been reached.

        Args:
            account_id: The owning account's UUID.
            day:        The calendar day to aggregate (UTC).  Defaults to today.

        Returns:
            The summed realised PnL as a ``Decimal`` (``Decimal("0")`` when
            there are no trades or all ``realized_pnl`` values are ``NULL``).

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            daily_pnl = await repo.sum_daily_realized_pnl(acct.id)
            if daily_pnl < -loss_limit:
                raise DailyLossLimitError(...)
        """
        if day is None:
            day = datetime.now(tz=timezone.utc).date()

        day_start = datetime.combine(day, time.min, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        try:
            stmt = select(
                sa_func.coalesce(sa_func.sum(Trade.realized_pnl), 0)
            ).where(
                Trade.account_id == account_id,
                Trade.created_at >= day_start,
                Trade.created_at < day_end,
            )
            result = await self._session.execute(stmt)
            total = result.scalar_one()
            return Decimal(str(total))
        except SQLAlchemyError as exc:
            logger.exception(
                "trade.sum_daily_realized_pnl.db_error",
                extra={
                    "account_id": str(account_id),
                    "day": str(day),
                    "error": str(exc),
                },
            )
            raise DatabaseError(
                f"Failed to aggregate daily PnL for account '{account_id}'."
            ) from exc
