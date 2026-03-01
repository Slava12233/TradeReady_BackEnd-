"""Limit Order Matcher — Component 4.

Background task that sweeps all pending orders every second and executes any
whose price conditions have been met in the live Redis price feed.

Matching rules
--------------
- **LIMIT buy**:      execute when ``current_price <= order.price``
- **LIMIT sell**:     execute when ``current_price >= order.price``
- **STOP_LOSS**:      execute when ``current_price <= order.price``  (trigger)
- **TAKE_PROFIT**:    execute when ``current_price >= order.price``  (trigger)

Each sweep fetches all ``pending`` orders from the database, reads their
symbols' current prices from Redis in a single pipeline call, evaluates the
conditions above, and dispatches matched orders to
:meth:`~src.order_engine.engine.OrderEngine.execute_pending_order`.

A fresh database session and :class:`~src.order_engine.engine.OrderEngine`
instance are created for each sweep so that any order that fails mid-execution
does not roll back the rest of the batch.

Celery integration
------------------
The public function :func:`run_matcher_once` is the entry point for the Celery
beat task scheduled every 1 second (``src/tasks/limit_order_monitor.py``).
For standalone testing the :meth:`LimitOrderMatcher.start` loop can be used
directly.

Example::

    matcher = LimitOrderMatcher(
        session_factory=get_session_factory(),
        price_cache=price_cache,
        balance_manager_factory=lambda session: BalanceManager(session, settings),
        slippage_calculator=SlippageCalculator(price_cache),
    )
    results = await matcher.check_all_pending()
    print(f"Filled {len(results)} orders this sweep.")
"""

from __future__ import annotations

import asyncio
import structlog
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Callable, Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.accounts.balance_manager import BalanceManager
from src.cache.price_cache import PriceCache
from src.config import Settings
from src.database.models import Order
from src.database.repositories.order_repo import OrderRepository
from src.database.repositories.trade_repo import TradeRepository
from src.order_engine.engine import OrderEngine, OrderResult
from src.order_engine.slippage import SlippageCalculator
from src.utils.exceptions import (
    DatabaseError,
    OrderNotFoundError,
    PriceNotAvailableError,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------

#: Factory signature for creating a :class:`BalanceManager` from a session.
BalanceManagerFactory = Callable[[AsyncSession], BalanceManager]


@dataclass(frozen=True, slots=True)
class MatcherStats:
    """Summary of a single matcher sweep.

    Attributes:
        swept_at:      UTC timestamp when the sweep started.
        orders_checked: Total number of pending orders evaluated.
        orders_filled:  Number of orders that were matched and filled.
        orders_errored: Number of orders where execution raised an exception.
        duration_ms:    Wall-clock time for the sweep in milliseconds.

    Example::

        stats = await matcher.check_all_pending()
        print(f"Swept {stats.orders_checked} orders, filled {stats.orders_filled}")
    """

    swept_at: datetime
    orders_checked: int
    orders_filled: int
    orders_errored: int
    duration_ms: float
    filled_results: list[OrderResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# LimitOrderMatcher
# ---------------------------------------------------------------------------


class LimitOrderMatcher:
    """Background sweeper that matches pending orders against live prices.

    Each call to :meth:`check_all_pending` is a single sweep:

    1. Fetch all ``pending`` orders from the database (up to ``page_size``
       rows at a time to bound memory usage).
    2. For each order, read the current price from :class:`PriceCache`.
    3. Evaluate the matching condition for the order type.
    4. On match, delegate execution to a fresh :class:`OrderEngine` instance
       (own session) so that one failure never prevents the others from filling.

    Args:
        session_factory:        SQLAlchemy ``async_sessionmaker`` used to open a
                                DB session per sweep (or per order for isolation).
        price_cache:            Live :class:`~src.cache.price_cache.PriceCache`.
        balance_manager_factory: Callable that produces a :class:`BalanceManager`
                                 bound to a given session.
        slippage_calculator:    Shared :class:`~src.order_engine.slippage.SlippageCalculator`.
        page_size:              Maximum pending orders to load per DB query
                                (default 500, matching ``OrderRepository.list_pending``).

    Example::

        matcher = LimitOrderMatcher(
            session_factory=get_session_factory(),
            price_cache=price_cache,
            balance_manager_factory=lambda s: BalanceManager(s, settings),
            slippage_calculator=SlippageCalculator(price_cache),
        )
        stats = await matcher.check_all_pending()
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        price_cache: PriceCache,
        balance_manager_factory: BalanceManagerFactory,
        slippage_calculator: SlippageCalculator,
        page_size: int = 500,
    ) -> None:
        self._session_factory = session_factory
        self._price_cache = price_cache
        self._balance_manager_factory = balance_manager_factory
        self._slippage_calculator = slippage_calculator
        self._page_size = page_size
        # Tracks execution errors for the current sweep; reset at sweep start.
        self._sweep_execution_errors: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_all_pending(self) -> MatcherStats:
        """Run one full sweep over all pending orders.

        Fetches pending orders in pages of ``page_size`` using keyset
        pagination (``WHERE id > last_seen_id``) to avoid the shifting-offset
        problem when new orders are inserted mid-sweep.  Evaluates each order
        against the current Redis price and executes matched orders.

        Returns:
            A :class:`MatcherStats` summary for this sweep.

        Example::

            stats = await matcher.check_all_pending()
            print(stats.orders_filled)
        """
        started_at = datetime.now(tz=timezone.utc)
        t0 = asyncio.get_running_loop().time()

        self._sweep_execution_errors = 0
        checked = 0
        filled = 0
        filled_results: list[OrderResult] = []

        last_id: UUID | None = None
        while True:
            pending_orders = await self._fetch_pending_page(after_id=last_id)
            if not pending_orders:
                break

            last_id = pending_orders[-1].id  # advance keyset cursor

            for order in pending_orders:
                checked += 1
                result = await self.check_order(order)
                if result is not None:
                    filled += 1
                    filled_results.append(result)

            if len(pending_orders) < self._page_size:
                # Last page — no more orders to process.
                break

        errored = self._sweep_execution_errors
        duration_ms = (asyncio.get_running_loop().time() - t0) * 1000

        stats = MatcherStats(
            swept_at=started_at,
            orders_checked=checked,
            orders_filled=filled,
            orders_errored=errored,
            duration_ms=duration_ms,
            filled_results=filled_results,
        )

        if checked > 0 or filled > 0:
            logger.info(
                "matcher.sweep_complete",
                extra={
                    "orders_checked": checked,
                    "orders_filled": filled,
                    "orders_errored": errored,
                    "duration_ms": round(duration_ms, 2),
                },
            )

        return stats

    async def check_order(self, order: Order) -> OrderResult | None:
        """Evaluate a single pending order against the current market price.

        Reads the current price for ``order.symbol`` from Redis and checks
        whether the order's trigger condition is satisfied.  If matched, the
        order is executed via a fresh :class:`OrderEngine` instance.

        Args:
            order: A ``pending`` :class:`~src.database.models.Order` row.

        Returns:
            An :class:`OrderResult` if the order was filled, or ``None`` if
            the condition was not met or if a non-fatal error occurred.

        Example::

            result = await matcher.check_order(order)
            if result:
                print(f"Order {order.id} filled at {result.executed_price}")
        """
        order_price = _order_trigger_price(order)
        if order_price is None:
            # Pending order with no price field — data inconsistency; skip.
            logger.warning(
                "matcher.order_missing_price",
                extra={"order_id": str(order.id), "type": order.type},
            )
            return None

        current_price = await self._price_cache.get_price(order.symbol)
        if current_price is None:
            # No live price for this symbol yet; skip without error.
            logger.debug(
                "matcher.no_price_for_symbol",
                extra={"order_id": str(order.id), "symbol": order.symbol},
            )
            return None

        if not _condition_met(order, current_price, order_price):
            return None

        # Price condition satisfied — execute the order.
        logger.info(
            "matcher.order_condition_met",
            extra={
                "order_id": str(order.id),
                "account_id": str(order.account_id),
                "symbol": order.symbol,
                "type": order.type,
                "side": order.side,
                "order_price": str(order_price),
                "current_price": str(current_price),
            },
        )
        return await self._execute_matched_order(order.id, current_price)

    async def start(self, interval_seconds: float = 1.0) -> None:
        """Run the matcher loop indefinitely at *interval_seconds* cadence.

        Designed for direct use in development or standalone processes.
        In production the Celery beat scheduler drives :func:`run_matcher_once`
        instead.  The loop exits cleanly on :exc:`asyncio.CancelledError`.

        Error handling: if a sweep raises an unhandled exception (e.g. the
        database is temporarily down) the failure is logged and the loop backs
        off exponentially (1 s → 2 s → 4 s … capped at 60 s) before retrying.
        Consecutive-failure count resets to 0 after any successful sweep.

        Args:
            interval_seconds: Pause between successful sweeps (default 1.0).

        Example::

            async def main():
                matcher = LimitOrderMatcher(...)
                await matcher.start(interval_seconds=1.0)
        """
        logger.info(
            "matcher.loop_started",
            extra={"interval_seconds": interval_seconds},
        )
        consecutive_failures = 0
        try:
            while True:
                try:
                    await self.check_all_pending()
                    consecutive_failures = 0
                    await asyncio.sleep(interval_seconds)
                except Exception:
                    consecutive_failures += 1
                    backoff = min(
                        interval_seconds * (2 ** (consecutive_failures - 1)), 60.0
                    )
                    logger.exception(
                        "matcher.sweep_unhandled_error",
                        extra={
                            "consecutive_failures": consecutive_failures,
                            "backoff_seconds": backoff,
                        },
                    )
                    await asyncio.sleep(backoff)
        except asyncio.CancelledError:
            logger.info("matcher.loop_cancelled")
            raise

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_pending_page(self, after_id: UUID | None) -> Sequence[Order]:
        """Load one page of pending orders using keyset pagination.

        Uses ``after_id`` (last seen order ID from the previous page) to avoid
        the shifting-offset problem when new orders are inserted mid-sweep.

        Args:
            after_id: The ``id`` of the last order returned by the previous
                      page, or ``None`` for the first page.

        Returns:
            A (possibly empty) sequence of :class:`Order` rows.
        """
        async with self._session_factory() as session:
            repo = OrderRepository(session)
            try:
                return await repo.list_pending(
                    limit=self._page_size,
                    after_id=after_id,
                )
            except DatabaseError:
                logger.exception(
                    "matcher.fetch_pending.db_error",
                    extra={"after_id": str(after_id) if after_id else None},
                )
                return []

    async def _execute_matched_order(
        self,
        order_id: UUID,
        current_price: Decimal,
    ) -> OrderResult | None:
        """Open a fresh session and execute a single matched order.

        Using a dedicated session per execution ensures that a failure (e.g.
        ``InsufficientBalanceError``, ``OrderNotFoundError``) is isolated to
        that single order and never contaminates the rest of the sweep.

        Args:
            order_id:      UUID of the order to fill.
            current_price: The live price at the moment of matching.

        Returns:
            :class:`OrderResult` on success, ``None`` on any handled error.
        """
        async with self._session_factory() as session:
            balance_manager = self._balance_manager_factory(session)
            order_repo = OrderRepository(session)
            trade_repo = TradeRepository(session)

            engine = OrderEngine(
                session=session,
                price_cache=self._price_cache,
                balance_manager=balance_manager,
                slippage_calculator=self._slippage_calculator,
                order_repo=order_repo,
                trade_repo=trade_repo,
            )

            try:
                result = await engine.execute_pending_order(
                    order_id=order_id,
                    current_price=current_price,
                )
                logger.info(
                    "matcher.order_filled",
                    extra={
                        "order_id": str(order_id),
                        "executed_price": str(result.executed_price),
                        "fee": str(result.fee),
                    },
                )
                return result

            except OrderNotFoundError:
                # Order may have been cancelled between the fetch and now.
                logger.info(
                    "matcher.order_not_found_on_execute",
                    extra={"order_id": str(order_id)},
                )
                return None

            except PriceNotAvailableError:
                logger.warning(
                    "matcher.price_unavailable_on_execute",
                    extra={"order_id": str(order_id)},
                )
                return None

            except Exception:
                logger.exception(
                    "matcher.execute_error",
                    extra={
                        "order_id": str(order_id),
                        "current_price": str(current_price),
                    },
                )
                self._sweep_execution_errors += 1
                return None


# ---------------------------------------------------------------------------
# Module-level convenience function (Celery entry point)
# ---------------------------------------------------------------------------


async def run_matcher_once(
    session_factory: async_sessionmaker[AsyncSession],
    price_cache: PriceCache,
    settings: Settings,
) -> MatcherStats:
    """Create a :class:`LimitOrderMatcher` and run one sweep.

    Intended as the async body of the Celery beat task
    ``src/tasks/limit_order_monitor.py``.  The caller provides the
    application-level singletons; this function builds the matcher and
    returns the sweep statistics.

    Args:
        session_factory: Module-level SQLAlchemy ``async_sessionmaker``.
        price_cache:     Application-level :class:`~src.cache.price_cache.PriceCache`.
        settings:        Application :class:`~src.config.Settings` (used to
                         build the :class:`BalanceManager`).

    Returns:
        A :class:`MatcherStats` summary for the sweep.

    Example::

        from src.database.session import get_session_factory
        from src.cache.price_cache import PriceCache
        from src.config import get_settings

        stats = await run_matcher_once(
            session_factory=get_session_factory(),
            price_cache=price_cache,
            settings=get_settings(),
        )
    """
    slippage_calculator = SlippageCalculator(
        price_cache,
        default_factor=settings.default_slippage_factor,
    )

    def _make_balance_manager(session: AsyncSession) -> BalanceManager:
        return BalanceManager(session, settings)

    matcher = LimitOrderMatcher(
        session_factory=session_factory,
        price_cache=price_cache,
        balance_manager_factory=_make_balance_manager,
        slippage_calculator=slippage_calculator,
    )
    return await matcher.check_all_pending()


# ---------------------------------------------------------------------------
# Pure helper functions (no I/O)
# ---------------------------------------------------------------------------


def _order_trigger_price(order: Order) -> Decimal | None:
    """Extract the trigger/limit price from an order row.

    All non-market order types store their target price in ``order.price``.
    Returns ``None`` when the field is missing (defensive guard).

    Args:
        order: ORM :class:`~src.database.models.Order` row.

    Returns:
        The trigger price as :class:`Decimal`, or ``None``.
    """
    if order.price is None:
        return None
    return Decimal(str(order.price))


def _condition_met(
    order: Order,
    current_price: Decimal,
    order_price: Decimal,
) -> bool:
    """Return ``True`` when the matching condition for *order* is satisfied.

    Matching rules:

    - **LIMIT buy**:   ``current_price <= order_price``
    - **LIMIT sell**:  ``current_price >= order_price``
    - **STOP_LOSS**:   ``current_price <= order_price``  (price fell to trigger)
    - **TAKE_PROFIT**: ``current_price >= order_price``  (price rose to trigger)

    Any unknown order type returns ``False`` so the order is safely skipped.

    Args:
        order:         The pending order being evaluated.
        current_price: Live price from Redis.
        order_price:   The order's trigger/limit price.

    Returns:
        ``True`` if the order should be executed now.
    """
    order_type = order.type
    side = order.side

    if order_type == "limit":
        if side == "buy":
            return current_price <= order_price
        if side == "sell":
            return current_price >= order_price

    elif order_type == "stop_loss":
        # Stop-loss fires when price drops to or below the stop price.
        return current_price <= order_price

    elif order_type == "take_profit":
        # Take-profit fires when price rises to or above the target.
        return current_price >= order_price

    logger.warning(
        "matcher.unknown_order_type",
        extra={"order_id": str(order.id), "type": order_type},
    )
    return False


