"""Portfolio Tracker — Component 6.

Provides real-time valuation of every agent's holdings by combining live
Redis prices with the position and balance data stored in TimescaleDB.

Classes
-------
PositionView
    Lightweight read-only view of a single open position valued at the
    current market price.  The ORM :class:`~src.database.models.Position`
    model is not returned directly so that callers receive ``Decimal``
    values and computed fields instead of raw ORM rows.

PnLBreakdown
    Detailed PnL decomposition: unrealized, realized, total, and daily.

PortfolioSummary
    Top-level portfolio snapshot: equity, cash, position value, PnL, ROI,
    and the full list of :class:`PositionView` objects.

PortfolioTracker
    Async service that builds the above dataclasses on demand.

Dependency direction::

    API routes / SnapshotService → PortfolioTracker
        → BalanceRepository (balances)
        → TradeRepository (realized PnL)
        → Position rows via AsyncSession (SQLAlchemy)
        → PriceCache (current market prices from Redis)

All methods accept an injected ``AsyncSession`` so they participate in
the caller's unit of work without issuing extra commits.

Example::

    async with session_factory() as session:
        tracker = PortfolioTracker(session, price_cache, settings)
        summary = await tracker.get_portfolio(account_id)
        print(summary.total_equity)
        print(summary.roi_pct)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.cache.price_cache import PriceCache
from src.config import Settings
from src.database.models import Account, Balance, Position
from src.database.repositories.balance_repo import BalanceRepository
from src.database.repositories.trade_repo import TradeRepository
from src.utils.exceptions import AccountNotFoundError, CacheError, DatabaseError

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_USDT = "USDT"


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class PositionView:
    """Read-only view of one open position valued at the current market price.

    All monetary fields use ``Decimal`` for exact arithmetic.

    Attributes:
        symbol:              Trading pair, e.g. ``"BTCUSDT"``.
        asset:               Base asset, e.g. ``"BTC"`` (symbol minus ``"USDT"``).
        quantity:            Held base-asset quantity.
        avg_entry_price:     Weighted-average entry price in USDT.
        current_price:       Latest price from Redis (or ``None`` if unavailable).
        market_value:        ``quantity × current_price`` in USDT.
        cost_basis:          ``quantity × avg_entry_price`` (total invested).
        unrealized_pnl:      ``market_value − cost_basis``.
        unrealized_pnl_pct:  ``unrealized_pnl / cost_basis × 100`` (or ``0``
                             when ``cost_basis`` is zero).
        realized_pnl:        Cumulative realised PnL from partial closes of
                             this position.
        price_available:     ``True`` when a live price was found in Redis.
    """

    symbol: str
    asset: str
    quantity: Decimal
    avg_entry_price: Decimal
    current_price: Decimal
    market_value: Decimal
    cost_basis: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: Decimal
    realized_pnl: Decimal
    price_available: bool


@dataclass(slots=True, frozen=True)
class PnLBreakdown:
    """Detailed PnL decomposition for an account.

    Attributes:
        unrealized_pnl:   Sum of unrealized PnL across all open positions.
        realized_pnl:     Cumulative realized PnL from all closed trade fills
                          (summed from the ``trades`` table).
        total_pnl:        ``unrealized_pnl + realized_pnl``.
        daily_realized:   Realised PnL for the current UTC calendar day.
    """

    unrealized_pnl: Decimal
    realized_pnl: Decimal
    total_pnl: Decimal
    daily_realized: Decimal


@dataclass(slots=True, frozen=True)
class PortfolioSummary:
    """Complete real-time portfolio snapshot for one account.

    Attributes:
        account_id:           UUID of the account.
        total_equity:         ``available_cash + locked_cash + total_position_value``
                              — the total portfolio value in USDT.
        available_cash:       Free USDT balance (can place new orders).
        locked_cash:          USDT locked in pending orders.
        total_position_value: Sum of ``market_value`` across all open positions.
        unrealized_pnl:       Aggregate open PnL across all positions.
        realized_pnl:         Cumulative realised PnL from all trade fills.
        total_pnl:            ``unrealized_pnl + realized_pnl``.
        roi_pct:              ``total_pnl / starting_balance × 100`` — return
                              on the original starting balance.
        starting_balance:     USDT balance credited at account registration.
        positions:            List of :class:`PositionView` for all open positions
                              (quantity > 0).
    """

    account_id: UUID
    total_equity: Decimal
    available_cash: Decimal
    locked_cash: Decimal
    total_position_value: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    total_pnl: Decimal
    roi_pct: Decimal
    starting_balance: Decimal
    positions: list[PositionView] = field(default_factory=list)


# ---------------------------------------------------------------------------
# PortfolioTracker
# ---------------------------------------------------------------------------


class PortfolioTracker:
    """Real-time portfolio valuation service.

    Combines live Redis prices with balance and position data from
    TimescaleDB to produce on-demand equity snapshots and PnL breakdowns.

    Args:
        session:     An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        price_cache: Initialised :class:`~src.cache.price_cache.PriceCache`
                     backed by the running Redis instance.
        settings:    Application :class:`~src.config.Settings` (used for
                     ``default_starting_balance``).

    Example::

        tracker = PortfolioTracker(session, price_cache, settings)
        summary  = await tracker.get_portfolio(account_id)
        positions = await tracker.get_positions(account_id)
        pnl      = await tracker.get_pnl(account_id)
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
        self._balance_repo = BalanceRepository(session)
        self._trade_repo = TradeRepository(session)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_portfolio(self, account_id: UUID, *, agent_id: UUID | None = None) -> PortfolioSummary:
        """Return a complete real-time portfolio snapshot for *account_id*.

        Fetches all open positions, valuates them using current Redis prices,
        aggregates USDT balances, and computes total equity, PnL, and ROI.

        Args:
            account_id: UUID of the account to query.

        Returns:
            A fully-populated :class:`PortfolioSummary`.

        Raises:
            AccountNotFoundError: If no account row exists for *account_id*.
            DatabaseError:        On any SQLAlchemy / database error.
            CacheError:           On any Redis error while fetching prices.

        Example::

            summary = await tracker.get_portfolio(account_id)
            print(f"Equity: {summary.total_equity} USDT")
            print(f"ROI: {summary.roi_pct:.2f}%")
        """
        starting_balance = await self._get_starting_balance(account_id, agent_id=agent_id)
        usdt_balance = await self._get_usdt_balance(account_id, agent_id=agent_id)
        available_cash = Decimal(str(usdt_balance.available)) if usdt_balance else _ZERO
        locked_cash = Decimal(str(usdt_balance.locked)) if usdt_balance else _ZERO

        positions = await self.get_positions(account_id, agent_id=agent_id)

        total_position_value = sum((p.market_value for p in positions), _ZERO)
        unrealized_pnl = sum((p.unrealized_pnl for p in positions), _ZERO)
        realized_pnl = await self._sum_realized_pnl(account_id, agent_id=agent_id)

        total_equity = available_cash + locked_cash + total_position_value
        total_pnl = unrealized_pnl + realized_pnl
        roi_pct = (total_pnl / starting_balance * _HUNDRED) if starting_balance else _ZERO

        logger.debug(
            "portfolio.get_portfolio",
            extra={
                "account_id": str(account_id),
                "total_equity": str(total_equity),
                "roi_pct": str(roi_pct),
                "open_positions": len(positions),
            },
        )
        return PortfolioSummary(
            account_id=account_id,
            total_equity=total_equity,
            available_cash=available_cash,
            locked_cash=locked_cash,
            total_position_value=total_position_value,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            total_pnl=total_pnl,
            roi_pct=roi_pct,
            starting_balance=starting_balance,
            positions=positions,
        )

    async def get_positions(self, account_id: UUID, *, agent_id: UUID | None = None) -> list[PositionView]:
        """Return all open positions for *account_id* valued at current prices.

        Only positions with ``quantity > 0`` are returned.  Each position is
        enriched with the current market price from Redis; when a price is not
        available the ``market_value`` and ``unrealized_pnl`` fall back to the
        cost-basis values and ``price_available`` is set to ``False``.

        Args:
            account_id: UUID of the account to query.

        Returns:
            A list of :class:`PositionView` objects, one per open position.
            Returns an empty list if no positions exist.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
            CacheError:    On any Redis error while fetching prices.

        Example::

            positions = await tracker.get_positions(account_id)
            for pos in positions:
                print(f"{pos.symbol}: {pos.quantity} @ {pos.current_price}")
        """
        orm_positions = await self._fetch_positions(account_id, agent_id=agent_id)
        views: list[PositionView] = []

        for pos in orm_positions:
            qty = Decimal(str(pos.quantity))
            avg_entry = Decimal(str(pos.avg_entry_price))
            cost_basis = qty * avg_entry

            current_price, price_available = await self._get_price_safe(pos.symbol)

            market_value = qty * current_price if price_available else cost_basis
            unrealized_pnl = market_value - cost_basis
            unrealized_pnl_pct = (unrealized_pnl / cost_basis * _HUNDRED) if cost_basis else _ZERO
            realized_pnl_pos = Decimal(str(pos.realized_pnl))
            asset = _symbol_to_asset(pos.symbol)

            views.append(
                PositionView(
                    symbol=pos.symbol,
                    asset=asset,
                    quantity=qty,
                    avg_entry_price=avg_entry,
                    current_price=current_price,
                    market_value=market_value,
                    cost_basis=cost_basis,
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_pct=unrealized_pnl_pct,
                    realized_pnl=realized_pnl_pos,
                    price_available=price_available,
                )
            )

        return views

    async def get_pnl(self, account_id: UUID, *, agent_id: UUID | None = None) -> PnLBreakdown:
        """Return a detailed PnL breakdown for *account_id*.

        Computes unrealized PnL from open positions at current market prices,
        total realized PnL from all historical trade fills, and daily realized
        PnL for the current UTC calendar day.

        Args:
            account_id: UUID of the account to query.

        Returns:
            A :class:`PnLBreakdown` with unrealized, realized, total, and
            daily PnL figures.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.
            CacheError:    On any Redis error while fetching prices.

        Example::

            pnl = await tracker.get_pnl(account_id)
            print(f"Unrealized: {pnl.unrealized_pnl}")
            print(f"Realized:   {pnl.realized_pnl}")
            print(f"Daily:      {pnl.daily_realized}")
        """
        positions = await self.get_positions(account_id, agent_id=agent_id)
        unrealized_pnl = sum((p.unrealized_pnl for p in positions), _ZERO)
        realized_pnl = await self._sum_realized_pnl(account_id, agent_id=agent_id)
        daily_realized = await self._sum_daily_realized_pnl(account_id, agent_id=agent_id)
        total_pnl = unrealized_pnl + realized_pnl

        logger.debug(
            "portfolio.get_pnl",
            extra={
                "account_id": str(account_id),
                "unrealized_pnl": str(unrealized_pnl),
                "realized_pnl": str(realized_pnl),
                "daily_realized": str(daily_realized),
            },
        )
        return PnLBreakdown(
            unrealized_pnl=unrealized_pnl,
            realized_pnl=realized_pnl,
            total_pnl=total_pnl,
            daily_realized=daily_realized,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_starting_balance(self, account_id: UUID, *, agent_id: UUID | None = None) -> Decimal:
        """Fetch the starting_balance column from the accounts table.

        Falls back to ``settings.default_starting_balance`` when the account
        row cannot be found (defensive for unit-test scenarios where the
        full Account table may not be seeded).

        Raises:
            AccountNotFoundError: If account row does not exist.
            DatabaseError:        On SQLAlchemy failure.
        """
        try:
            if agent_id is not None:
                from src.database.models import Agent  # noqa: PLC0415

                stmt = select(Agent.starting_balance).where(Agent.id == agent_id)
                result = await self._session.execute(stmt)
                raw = result.scalar_one_or_none()
                if raw is not None:
                    return Decimal(str(raw))
            stmt = select(Account.starting_balance).where(Account.id == account_id)
            result = await self._session.execute(stmt)
            raw = result.scalar_one_or_none()
        except SQLAlchemyError as exc:
            logger.exception(
                "portfolio.get_starting_balance.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError(f"Failed to fetch starting balance for account '{account_id}'.") from exc

        if raw is None:
            raise AccountNotFoundError(account_id=account_id)
        return Decimal(str(raw))

    async def _get_usdt_balance(self, account_id: UUID, *, agent_id: UUID | None = None) -> Balance | None:
        """Return the USDT Balance row for *account_id*, or ``None``.

        Raises:
            DatabaseError: On SQLAlchemy failure.
        """
        try:
            if agent_id is not None:
                return await self._balance_repo.get_by_agent(agent_id, _USDT)
            return await self._balance_repo.get(account_id, _USDT)
        except DatabaseError:
            raise
        except SQLAlchemyError as exc:
            logger.exception(
                "portfolio.get_usdt_balance.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError(f"Failed to fetch USDT balance for account '{account_id}'.") from exc

    async def _fetch_positions(self, account_id: UUID, *, agent_id: UUID | None = None) -> list[Position]:
        """Return all ORM Position rows with quantity > 0 for *account_id*.

        Raises:
            DatabaseError: On SQLAlchemy failure.
        """
        try:
            filters = [Position.account_id == account_id, Position.quantity > 0]
            if agent_id is not None:
                filters.append(Position.agent_id == agent_id)
            stmt = select(Position).where(*filters).order_by(Position.symbol)
            result = await self._session.execute(stmt)
            return list(result.scalars().all())
        except SQLAlchemyError as exc:
            logger.exception(
                "portfolio.fetch_positions.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError(f"Failed to fetch positions for account '{account_id}'.") from exc

    async def _sum_realized_pnl(self, account_id: UUID, *, agent_id: UUID | None = None) -> Decimal:
        """Return cumulative realized PnL from all trade fills.

        Delegates to :meth:`_sum_all_realized_pnl` which issues a direct
        aggregate query across the ``trades`` table scoped by agent when provided.

        Raises:
            DatabaseError: On SQLAlchemy failure.
        """
        return await self._sum_all_realized_pnl(account_id, agent_id=agent_id)

    async def _sum_all_realized_pnl(self, account_id: UUID, *, agent_id: UUID | None = None) -> Decimal:
        """Sum realized_pnl across Trade rows, scoped by agent when provided.

        Uses a direct aggregate query since TradeRepository.sum_daily_realized_pnl
        is scoped to a single calendar day.

        Raises:
            DatabaseError: On SQLAlchemy failure.
        """
        from sqlalchemy import func as sa_func

        from src.database.models import Trade

        try:
            filters = [Trade.account_id == account_id]
            if agent_id is not None:
                filters.append(Trade.agent_id == agent_id)
            stmt = select(sa_func.coalesce(sa_func.sum(Trade.realized_pnl), 0)).where(*filters)
            result = await self._session.execute(stmt)
            raw = result.scalar_one()
            return Decimal(str(raw))
        except SQLAlchemyError as exc:
            logger.exception(
                "portfolio.sum_all_realized_pnl.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError(f"Failed to sum realized PnL for account '{account_id}'.") from exc

    async def _sum_daily_realized_pnl(self, account_id: UUID, *, agent_id: UUID | None = None) -> Decimal:
        """Return today's realized PnL via TradeRepository.

        Raises:
            DatabaseError: On SQLAlchemy failure.
        """
        raw_float = await self._trade_repo.sum_daily_realized_pnl(account_id, agent_id=agent_id)
        return Decimal(str(raw_float))

    async def _get_price_safe(self, symbol: str) -> tuple[Decimal, bool]:
        """Fetch the current price for *symbol* from Redis.

        Returns ``(price, True)`` on success, or ``(Decimal('0'), False)``
        when the symbol is not in the cache.  Never raises on a missing
        price — that is a legitimate edge case (e.g. pair was de-listed or
        ingestion is starting up).

        Raises:
            CacheError: Only on a Redis connectivity failure (not on a
                cache-miss).
        """
        try:
            price = await self._price_cache.get_price(symbol)
        except Exception as exc:
            logger.exception(
                "portfolio.get_price_safe.cache_error",
                extra={"symbol": symbol, "error": str(exc)},
            )
            raise CacheError(f"Redis error while fetching price for '{symbol}'.") from exc

        if price is None:
            logger.warning(
                "portfolio.get_price_safe.price_missing",
                extra={"symbol": symbol},
            )
            return _ZERO, False
        return price, True


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _symbol_to_asset(symbol: str) -> str:
    """Derive the base asset ticker from a USDT trading pair symbol.

    Strips the ``USDT`` suffix.  Falls back to returning the full symbol
    unchanged for non-USDT pairs (which should not appear in Phase 2 but
    are handled defensively).

    Args:
        symbol: Uppercase trading pair, e.g. ``"BTCUSDT"``.

    Returns:
        Base asset, e.g. ``"BTC"``.

    Example::

        >>> _symbol_to_asset("BTCUSDT")
        'BTC'
        >>> _symbol_to_asset("ETHUSDT")
        'ETH'
    """
    if symbol.endswith(_USDT):
        return symbol[: -len(_USDT)]
    return symbol
