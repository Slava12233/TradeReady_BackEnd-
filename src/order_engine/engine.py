"""Order Execution Engine — Component 4.

Supported order types:

1. **MARKET**      — Executed immediately at the current Redis price + slippage.
2. **LIMIT**       — Funds locked up-front; queued as ``pending`` until the
                     background matcher triggers execution at the target price.
3. **STOP_LOSS**   — Queued as ``pending``; executed as a market order when the
                     current price drops *at or below* the trigger price.
4. **TAKE_PROFIT** — Queued as ``pending``; executed as a market order when the
                     current price rises *at or above* the trigger price.

Order lifecycle
---------------
1. Agent calls :meth:`OrderEngine.place_order`.
2. :class:`~src.order_engine.validators.OrderValidator` validates symbol,
   side, type, quantity, and price fields.
3. Price is fetched from Redis; :class:`PriceNotAvailableError` if missing.
4. For **market** orders: slippage is calculated, balances settled, a
   :class:`~src.database.models.Trade` row is created, the order status is
   set to ``filled``, and an :class:`OrderResult` is returned immediately.
5. For **limit / stop_loss / take_profit** orders: the required funds are
   locked via :class:`~src.accounts.balance_manager.BalanceManager`, the
   order is persisted with ``status="pending"``, and an :class:`OrderResult`
   with ``status="pending"`` is returned.
6. The background matcher (:mod:`src.order_engine.matching`) later calls
   :meth:`OrderEngine.execute_pending_order` when price conditions are met.

:meth:`cancel_order` and :meth:`cancel_all_orders` reverse locked funds and
transition the order to ``cancelled``.

Example::

    engine = OrderEngine(
        session=session,
        price_cache=price_cache,
        balance_manager=balance_manager,
        slippage_calculator=slippage_calculator,
        order_repo=order_repo,
        trade_repo=trade_repo,
    )
    result = await engine.place_order(
        account_id=account.id,
        order=OrderRequest(
            symbol="BTCUSDT",
            side="buy",
            type="market",
            quantity=Decimal("0.01"),
        ),
    )
    print(result.status)          # "filled"
    print(result.executed_price)  # e.g. Decimal("64003.20")
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.accounts.balance_manager import BalanceManager
from src.cache.price_cache import PriceCache
from src.database.models import Order, Position, Trade
from src.database.repositories.order_repo import OrderRepository
from src.database.repositories.trade_repo import TradeRepository
from src.order_engine.slippage import SlippageCalculator
from src.order_engine.validators import OrderRequest, OrderValidator
from src.utils.exceptions import (
    CacheError,
    DatabaseError,
    InsufficientBalanceError,
    OrderNotCancellableError,
    OrderNotFoundError,
    PriceNotAvailableError,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OrderResult:
    """Outcome returned by every :class:`OrderEngine` operation.

    Attributes:
        order_id:          UUID of the created or affected order.
        status:            Final status: ``"filled"``, ``"pending"``, or
                           ``"cancelled"``.
        executed_price:    Effective fill price after slippage (``None`` for
                           pending/cancelled orders).
        executed_quantity: Filled quantity (``None`` for pending/cancelled).
        slippage_pct:      Slippage percentage (``None`` for pending/cancelled).
        fee:               Trading fee deducted in the quote asset.  ``None``
                           for pending orders; ``Decimal("0")`` for cancelled.
        timestamp:         UTC datetime of the result.
        rejection_reason:  Short machine-readable reason when the order was
                           rejected (unused in the current flow — rejections
                           raise exceptions).

    Example::

        result = await engine.place_order(account_id, order_request)
        if result.status == "filled":
            print(result.executed_price)
    """

    order_id: UUID
    status: str
    executed_price: Decimal | None
    executed_quantity: Decimal | None
    slippage_pct: Decimal | None
    fee: Decimal | None
    timestamp: datetime
    rejection_reason: str | None = None


# ---------------------------------------------------------------------------
# OrderEngine
# ---------------------------------------------------------------------------


class OrderEngine:
    """Central coordinator for all order placement, execution, and cancellation.

    This class is the *only* authoritative path for placing and cancelling
    orders.  It owns the full transactional boundary: every method that writes
    to the database opens a savepoint-compatible sequence of repository calls
    and commits via the injected ``session``.

    Dependency injection allows unit tests to replace any collaborator with a
    mock without patching module-level symbols.

    Args:
        session:              Open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.
        price_cache:          Live :class:`~src.cache.price_cache.PriceCache`.
        balance_manager:      :class:`~src.accounts.balance_manager.BalanceManager`
                              wired to the same session.
        slippage_calculator:  :class:`~src.order_engine.slippage.SlippageCalculator`.
        order_repo:           :class:`~src.database.repositories.order_repo.OrderRepository`
                              wired to the same session.
        trade_repo:           :class:`~src.database.repositories.trade_repo.TradeRepository`
                              wired to the same session.

    Example::

        async with session_factory() as session:
            engine = OrderEngine(
                session=session,
                price_cache=price_cache,
                balance_manager=BalanceManager(session, settings),
                slippage_calculator=SlippageCalculator(price_cache),
                order_repo=OrderRepository(session),
                trade_repo=TradeRepository(session),
            )
            result = await engine.place_order(account_id, order_request)
    """

    def __init__(
        self,
        session: AsyncSession,
        price_cache: PriceCache,
        balance_manager: BalanceManager,
        slippage_calculator: SlippageCalculator,
        order_repo: OrderRepository,
        trade_repo: TradeRepository,
    ) -> None:
        self._session = session
        self._price_cache = price_cache
        self._balance_manager = balance_manager
        self._slippage_calculator = slippage_calculator
        self._order_repo = order_repo
        self._trade_repo = trade_repo
        self._validator = OrderValidator(session)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def place_order(
        self,
        account_id: UUID,
        order: OrderRequest,
    ) -> OrderResult:
        """Validate and place an order on behalf of an account.

        Market orders are executed immediately.  Limit, stop-loss, and
        take-profit orders lock the required funds and queue as ``pending``.

        Args:
            account_id: The owning account's UUID.
            order:      A fully-populated :class:`~src.order_engine.validators.OrderRequest`.

        Returns:
            An :class:`OrderResult` with ``status="filled"`` for market orders
            or ``status="pending"`` for queued orders.

        Raises:
            InputValidationError:    From the validator for bad field values.
            InvalidOrderTypeError:   From the validator for unsupported type.
            InvalidQuantityError:    From the validator for non-positive qty.
            InvalidSymbolError:      From the validator if the pair is inactive.
            PriceNotAvailableError:  If Redis has no price for the symbol.
            InsufficientBalanceError: If the account lacks funds.
            DatabaseError:           On any unexpected database failure.

        Example::

            result = await engine.place_order(
                account_id,
                OrderRequest(symbol="BTCUSDT", side="buy", type="market", quantity=Decimal("0.01")),
            )
        """
        pair = await self._validator.validate(order)

        try:
            reference_price = await self._price_cache.get_price(order.symbol)
        except Exception as exc:
            raise CacheError(f"Failed to fetch price for {order.symbol} from cache.") from exc
        if reference_price is None:
            raise PriceNotAvailableError(symbol=order.symbol)

        if order.type == "market":
            return await self._place_market_order(
                account_id=account_id,
                order=order,
                base_asset=pair.base_asset,
                quote_asset=pair.quote_asset,
                reference_price=reference_price,
            )

        # limit / stop_loss / take_profit
        return await self._place_queued_order(
            account_id=account_id,
            order=order,
            base_asset=pair.base_asset,
            quote_asset=pair.quote_asset,
            market_price=reference_price,
        )

    async def cancel_order(self, account_id: UUID, order_id: UUID) -> bool:
        """Cancel a single pending order and release its locked funds.

        Args:
            account_id: The owning account's UUID (ownership check).
            order_id:   UUID of the order to cancel.

        Returns:
            ``True`` if the order was cancelled successfully.

        Raises:
            OrderNotFoundError:       If the order does not exist or does not
                                      belong to ``account_id``.
            OrderNotCancellableError: If the order is already in a terminal state.
            DatabaseError:            On any unexpected database failure.

        Example::

            cancelled = await engine.cancel_order(account_id, order.id)
        """
        # cancel() raises OrderNotCancellableError if the order is already in a
        # terminal state (e.g. filled by the matcher between our fetch and now).
        # In that case _release_locked_funds must NOT be called — the funds were
        # already settled as part of the fill.  Using the order returned by
        # cancel() (rather than a pre-fetched copy) ensures we release exactly
        # the amount that was locked, avoiding any TOCTOU inconsistency.
        order = await self._order_repo.cancel(order_id, account_id)
        await self._release_locked_funds(account_id=account_id, order=order)

        try:
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "engine.cancel_order.commit_error",
                extra={"order_id": str(order_id), "account_id": str(account_id)},
            )
            raise DatabaseError("Failed to commit order cancellation.") from exc

        logger.info(
            "engine.order_cancelled",
            extra={
                "order_id": str(order_id),
                "account_id": str(account_id),
                "symbol": order.symbol,
                "type": order.type,
            },
        )
        return True

    async def cancel_all_orders(self, account_id: UUID) -> int:
        """Cancel all open (pending / partially-filled) orders for an account.

        For each open order the locked funds are released before the order
        status is transitioned to ``cancelled``.  All cancellations commit in
        a single database transaction for atomicity.

        Args:
            account_id: The owning account's UUID.

        Returns:
            The number of orders that were cancelled.

        Raises:
            DatabaseError: On any unexpected database failure.

        Example::

            count = await engine.cancel_all_orders(account_id)
            print(f"{count} orders cancelled")
        """
        open_orders: Sequence[Order] = await self._order_repo.list_open_by_account(account_id)

        cancelled_count = 0
        failed_order_ids: list[str] = []
        for order in open_orders:
            try:
                cancelled = await self._order_repo.cancel(order.id, account_id)
                await self._release_locked_funds(account_id=account_id, order=cancelled)
                cancelled_count += 1
            except (OrderNotFoundError, OrderNotCancellableError, InsufficientBalanceError):
                # Order was already filled/cancelled or funds state is inconsistent;
                # skip and continue so the remaining orders are still cancelled.
                logger.warning(
                    "engine.cancel_all.single_cancel_skipped",
                    extra={
                        "order_id": str(order.id),
                        "account_id": str(account_id),
                    },
                )
                failed_order_ids.append(str(order.id))
            except SQLAlchemyError:
                logger.exception(
                    "engine.cancel_all.single_cancel_db_error",
                    extra={
                        "order_id": str(order.id),
                        "account_id": str(account_id),
                    },
                )
                failed_order_ids.append(str(order.id))

        if cancelled_count > 0:
            try:
                await self._session.commit()
            except SQLAlchemyError as exc:
                await self._session.rollback()
                logger.exception(
                    "engine.cancel_all.commit_error",
                    extra={"account_id": str(account_id)},
                )
                raise DatabaseError("Failed to commit bulk order cancellation.") from exc

        logger.info(
            "engine.cancel_all_orders",
            extra={
                "account_id": str(account_id),
                "cancelled": cancelled_count,
                "failed": len(failed_order_ids),
                "failed_ids": failed_order_ids,
            },
        )
        return cancelled_count

    async def execute_pending_order(
        self,
        order_id: UUID,
        current_price: Decimal,
    ) -> OrderResult:
        """Execute a previously queued pending order at *current_price*.

        Called by the background limit-order matcher
        (:class:`~src.order_engine.matching.LimitOrderMatcher`) when price
        conditions are met.  The order must already be in ``pending`` status;
        this method performs the fill, settles balances, records the trade,
        and commits.

        For **limit** orders the pre-locked funds (``from_locked=True``) are
        used for settlement.  For **stop_loss / take_profit** orders the
        execution also draws from locked funds.

        Args:
            order_id:      UUID of the pending order to fill.
            current_price: The price at which to execute (trigger price or
                           best available market price at trigger time).

        Returns:
            An :class:`OrderResult` with ``status="filled"``.

        Raises:
            OrderNotFoundError:      If the order does not exist.
            PriceNotAvailableError:  If *current_price* is zero or negative.
            InsufficientBalanceError: If locked funds are somehow insufficient.
            DatabaseError:           On any unexpected database failure.

        Example::

            result = await engine.execute_pending_order(order.id, Decimal("60000"))
        """
        if current_price <= Decimal("0"):
            raise PriceNotAvailableError(
                message=f"Execution price must be positive; got {current_price}",
            )

        order = await self._order_repo.get_by_id(order_id)

        slippage = await self._slippage_calculator.calculate(
            symbol=order.symbol,
            side=order.side,
            quantity=Decimal(str(order.quantity)),
            reference_price=current_price,
        )

        settlement = await self._balance_manager.execute_trade(
            order.account_id,
            symbol=order.symbol,
            side=order.side,
            base_asset=_base_asset_from_order(order),
            quote_asset=_quote_asset_from_order(order),
            quantity=Decimal(str(order.quantity)),
            execution_price=slippage.execution_price,
            from_locked=True,
        )

        filled_at = datetime.now(tz=UTC)
        await self._order_repo.update_status(
            order_id,
            "filled",
            extra_fields={
                "executed_price": slippage.execution_price,
                "executed_qty": Decimal(str(order.quantity)),
                "slippage_pct": slippage.slippage_pct,
                "fee": settlement.fee_charged,
                "filled_at": filled_at,
            },
        )

        trade = Trade(
            account_id=order.account_id,
            order_id=order.id,
            session_id=order.session_id,
            symbol=order.symbol,
            side=order.side,
            quantity=Decimal(str(order.quantity)),
            price=slippage.execution_price,
            quote_amount=settlement.quote_amount,
            fee=settlement.fee_charged,
        )
        await self._trade_repo.create(trade)

        rpnl = await self._upsert_position(
            account_id=order.account_id,
            symbol=order.symbol,
            side=order.side,
            fill_qty=Decimal(str(order.quantity)),
            fill_price=slippage.execution_price,
        )
        if rpnl is not None:
            trade.realized_pnl = rpnl

        try:
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "engine.execute_pending.commit_error",
                extra={"order_id": str(order_id)},
            )
            raise DatabaseError("Failed to commit pending order execution.") from exc

        logger.info(
            "engine.pending_order_filled",
            extra={
                "order_id": str(order_id),
                "account_id": str(order.account_id),
                "symbol": order.symbol,
                "side": order.side,
                "type": order.type,
                "executed_price": str(slippage.execution_price),
                "fee": str(settlement.fee_charged),
            },
        )

        return OrderResult(
            order_id=order_id,
            status="filled",
            executed_price=slippage.execution_price,
            executed_quantity=Decimal(str(order.quantity)),
            slippage_pct=slippage.slippage_pct,
            fee=settlement.fee_charged,
            timestamp=filled_at,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _place_market_order(
        self,
        account_id: UUID,
        order: OrderRequest,
        base_asset: str,
        quote_asset: str,
        reference_price: Decimal,
    ) -> OrderResult:
        """Create, execute, and commit a market order in a single transaction.

        Slippage is calculated against *reference_price* (from Redis).
        Balance settlement is atomic via :class:`BalanceManager`.

        Args:
            account_id:      The owning account's UUID.
            order:           The validated order request.
            base_asset:      Base asset ticker (e.g. ``"BTC"``).
            quote_asset:     Quote asset ticker (e.g. ``"USDT"``).
            reference_price: Current Redis price for the pair.

        Returns:
            :class:`OrderResult` with ``status="filled"``.

        Raises:
            PriceNotAvailableError:   If *reference_price* is zero.
            InsufficientBalanceError: If the account lacks funds.
            DatabaseError:            On commit failure.
        """
        slippage = await self._slippage_calculator.calculate(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            reference_price=reference_price,
        )

        # Pre-flight balance check before any writes.
        if order.side == "buy":
            gross_cost = order.quantity * slippage.execution_price
            fee_estimate = slippage.fee
            required = gross_cost + fee_estimate
            asset_to_check = quote_asset
        else:
            required = order.quantity
            asset_to_check = base_asset

        if not await self._balance_manager.has_sufficient_balance(account_id, asset=asset_to_check, amount=required):
            balance = await self._balance_manager.get_balance(account_id, asset_to_check)
            available = Decimal(str(balance.available)) if balance is not None else Decimal("0")
            raise InsufficientBalanceError(
                asset=asset_to_check,
                required=required,
                available=available,
            )

        db_order = Order(
            account_id=account_id,
            symbol=order.symbol,
            side=order.side,
            type=order.type,
            quantity=order.quantity,
            status="pending",
        )
        db_order = await self._order_repo.create(db_order)

        settlement = await self._balance_manager.execute_trade(
            account_id,
            symbol=order.symbol,
            side=order.side,
            base_asset=base_asset,
            quote_asset=quote_asset,
            quantity=order.quantity,
            execution_price=slippage.execution_price,
            from_locked=False,
        )

        filled_at = datetime.now(tz=UTC)
        await self._order_repo.update_status(
            db_order.id,
            "filled",
            extra_fields={
                "executed_price": slippage.execution_price,
                "executed_qty": order.quantity,
                "slippage_pct": slippage.slippage_pct,
                "fee": settlement.fee_charged,
                "filled_at": filled_at,
            },
        )

        trade = Trade(
            account_id=account_id,
            order_id=db_order.id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=slippage.execution_price,
            quote_amount=settlement.quote_amount,
            fee=settlement.fee_charged,
        )
        await self._trade_repo.create(trade)

        rpnl = await self._upsert_position(
            account_id=account_id,
            symbol=order.symbol,
            side=order.side,
            fill_qty=order.quantity,
            fill_price=slippage.execution_price,
        )
        if rpnl is not None:
            trade.realized_pnl = rpnl

        try:
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "engine.market_order.commit_error",
                extra={"account_id": str(account_id), "symbol": order.symbol},
            )
            raise DatabaseError("Failed to commit market order.") from exc

        logger.info(
            "engine.market_order_filled",
            extra={
                "order_id": str(db_order.id),
                "account_id": str(account_id),
                "symbol": order.symbol,
                "side": order.side,
                "quantity": str(order.quantity),
                "reference_price": str(reference_price),
                "executed_price": str(slippage.execution_price),
                "slippage_pct": str(slippage.slippage_pct),
                "fee": str(settlement.fee_charged),
            },
        )

        return OrderResult(
            order_id=db_order.id,
            status="filled",
            executed_price=slippage.execution_price,
            executed_quantity=order.quantity,
            slippage_pct=slippage.slippage_pct,
            fee=settlement.fee_charged,
            timestamp=filled_at,
        )

    async def _place_queued_order(
        self,
        account_id: UUID,
        order: OrderRequest,
        base_asset: str,
        quote_asset: str,
        market_price: Decimal,
    ) -> OrderResult:
        """Create a pending (limit/stop_loss/take_profit) order and lock funds.

        For buy orders the estimated quote cost is locked; for sell orders the
        base asset is locked.  The estimate uses *order.price* (the trigger /
        limit price) rather than the current market price so that the locked
        amount exactly matches the expected fill cost.

        Args:
            account_id:  The owning account's UUID.
            order:       The validated order request (must have ``price``).
            base_asset:  Base asset ticker.
            quote_asset: Quote asset ticker.
            market_price: Current market price at placement time (logged for
                          observability; not used for locking calculation).

        Returns:
            :class:`OrderResult` with ``status="pending"``.

        Raises:
            InsufficientBalanceError: If the account lacks funds to lock.
            DatabaseError:            On commit failure.
        """
        # order.price is guaranteed non-None by OrderValidator._check_price.
        limit_price: Decimal = order.price  # type: ignore[assignment]

        # Calculate lock amount: for buy → quote cost at limit price + fee
        # estimate; for sell → base quantity.
        if order.side == "buy":
            gross_cost = order.quantity * limit_price
            # Conservative fee estimate based on limit price.
            fee_fraction = Decimal("0.001")
            fee_estimate = gross_cost * fee_fraction
            lock_asset = quote_asset
            lock_amount = gross_cost + fee_estimate
        else:
            lock_asset = base_asset
            lock_amount = order.quantity

        if not await self._balance_manager.has_sufficient_balance(account_id, asset=lock_asset, amount=lock_amount):
            balance = await self._balance_manager.get_balance(account_id, lock_asset)
            available = Decimal(str(balance.available)) if balance is not None else Decimal("0")
            raise InsufficientBalanceError(
                asset=lock_asset,
                required=lock_amount,
                available=available,
            )

        db_order = Order(
            account_id=account_id,
            symbol=order.symbol,
            side=order.side,
            type=order.type,
            quantity=order.quantity,
            price=limit_price,
            status="pending",
        )
        db_order = await self._order_repo.create(db_order)

        await self._balance_manager.lock(account_id, asset=lock_asset, amount=lock_amount)

        try:
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "engine.queued_order.commit_error",
                extra={"account_id": str(account_id), "symbol": order.symbol},
            )
            raise DatabaseError("Failed to commit queued order.") from exc

        logger.info(
            "engine.order_queued",
            extra={
                "order_id": str(db_order.id),
                "account_id": str(account_id),
                "symbol": order.symbol,
                "side": order.side,
                "type": order.type,
                "quantity": str(order.quantity),
                "price": str(limit_price),
                "lock_asset": lock_asset,
                "lock_amount": str(lock_amount),
                "market_price": str(market_price),
            },
        )

        return OrderResult(
            order_id=db_order.id,
            status="pending",
            executed_price=None,
            executed_quantity=None,
            slippage_pct=None,
            fee=None,
            timestamp=datetime.now(tz=UTC),
        )

    async def _upsert_position(
        self,
        account_id: UUID,
        symbol: str,
        side: str,
        fill_qty: Decimal,
        fill_price: Decimal,
    ) -> Decimal | None:
        """Create or update the Position row for *account_id* / *symbol* after a fill.

        For buy fills the weighted-average entry price is recalculated and the
        quantity is increased.  For sell fills the quantity is reduced and the
        realised PnL portion for the closed quantity is accumulated.  Positions
        with ``quantity <= 0`` are zeroed out rather than deleted so that the
        realised-PnL history is preserved on the row.

        This method must be called **before** the surrounding transaction
        commits so that the position update is atomic with the balance and
        trade writes.

        Args:
            account_id: Owning account UUID.
            symbol:     Trading pair (e.g. ``"BTCUSDT"``).
            side:       ``"buy"`` or ``"sell"``.
            fill_qty:   Quantity filled in base asset.
            fill_price: Effective execution price (post-slippage).

        Returns:
            The realized PnL for this fill (sell side only), or ``None``
            for buy fills and sells with no existing position.
        """
        stmt = select(Position).where(
            Position.account_id == account_id,
            Position.symbol == symbol,
        )
        result = await self._session.execute(stmt)
        pos: Position | None = result.scalar_one_or_none()

        if side == "buy":
            if pos is None:
                pos = Position(
                    account_id=account_id,
                    symbol=symbol,
                    side="long",
                    quantity=fill_qty,
                    avg_entry_price=fill_price,
                    total_cost=fill_qty * fill_price,
                    realized_pnl=Decimal("0"),
                )
                self._session.add(pos)
            else:
                old_qty = Decimal(str(pos.quantity))
                old_cost = Decimal(str(pos.total_cost))
                fill_cost = fill_qty * fill_price
                new_qty = old_qty + fill_qty
                new_total_cost = old_cost + fill_cost
                new_avg_entry = new_total_cost / new_qty if new_qty else fill_price
                pos.quantity = new_qty
                pos.avg_entry_price = new_avg_entry
                pos.total_cost = new_total_cost
            return None
        else:  # sell
            if pos is None:
                logger.warning(
                    "engine.upsert_position.sell_no_position",
                    extra={"account_id": str(account_id), "symbol": symbol},
                )
                return None
            old_qty = Decimal(str(pos.quantity))
            avg_entry = Decimal(str(pos.avg_entry_price))
            realised_increment = (fill_price - avg_entry) * fill_qty
            new_qty = old_qty - fill_qty
            new_qty = max(new_qty, Decimal("0"))
            new_total_cost = new_qty * avg_entry
            pos.quantity = new_qty
            pos.total_cost = new_total_cost
            pos.realized_pnl = Decimal(str(pos.realized_pnl)) + realised_increment
            return realised_increment

    async def _release_locked_funds(
        self,
        account_id: UUID,
        order: Order,
    ) -> None:
        """Unlock funds reserved for a pending order on cancellation.

        For buy orders the locked quote asset is released; for sell orders the
        locked base asset is released.  This method mirrors the locking logic
        in :meth:`_place_queued_order`.

        Only ``pending`` / ``partially_filled`` orders have locked funds;
        for any other status this is a no-op.

        Args:
            account_id: The owning account's UUID.
            order:      The ORM :class:`~src.database.models.Order` being cancelled.
        """
        # Only pending orders have funds locked.  Market orders go straight to
        # ``filled`` and never enter the cancellable state, so a ``None`` price
        # here indicates a data inconsistency (e.g. migration edge case).
        # Raise rather than silently skip so the caller knows funds may be stuck.
        if order.price is None:
            logger.warning(
                "engine.release_locked_funds.no_price",
                extra={"order_id": str(order.id), "account_id": str(account_id)},
            )
            raise DatabaseError(
                f"Cannot release locked funds for order {order.id}: order has no "
                "price field (possible data inconsistency; locked funds may be stuck)."
            )

        try:
            if order.side == "buy":
                gross_cost = Decimal(str(order.quantity)) * Decimal(str(order.price))
                fee_fraction = Decimal("0.001")
                fee_estimate = gross_cost * fee_fraction
                lock_amount = gross_cost + fee_estimate
                lock_asset = _quote_asset_from_order(order)
            else:
                lock_amount = Decimal(str(order.quantity))
                lock_asset = _base_asset_from_order(order)

            await self._balance_manager.unlock(account_id, asset=lock_asset, amount=lock_amount)
        except Exception:
            logger.exception(
                "engine.release_locked_funds.error",
                extra={"order_id": str(order.id), "account_id": str(account_id)},
            )
            raise


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _base_asset_from_order(order: Order) -> str:
    """Derive the base asset ticker from the order's symbol.

    Assumes all symbols are of the form ``<BASE>USDT`` and strips the
    ``USDT`` suffix.  This is a best-effort fallback for when the caller
    does not have a :class:`~src.database.models.TradingPair` reference
    handy (e.g. inside :meth:`OrderEngine.execute_pending_order`).

    For pairs that are not ``*USDT`` the caller should pass ``base_asset``
    explicitly (see :meth:`_place_market_order`).

    Args:
        order: The ORM :class:`~src.database.models.Order` row.

    Returns:
        The base asset string, e.g. ``"BTC"`` for ``"BTCUSDT"``.
    """
    symbol: str = order.symbol
    # Use str.removesuffix (Python 3.9+) to avoid silent wrong-length stripping.
    for quote in ("USDT", "BTC", "ETH", "BNB"):
        base = symbol.removesuffix(quote)
        if base != symbol:  # suffix was present
            return base
    # Unknown quote currency — log and fall back to USDT-length strip.
    logger.warning("engine.unknown_symbol_format", extra={"symbol": symbol})
    return symbol[:-4]


def _quote_asset_from_order(order: Order) -> str:
    """Derive the quote asset ticker from the order's symbol.

    Mirrors :func:`_base_asset_from_order`.  Covers the most common quote
    assets on the platform.

    Args:
        order: The ORM :class:`~src.database.models.Order` row.

    Returns:
        The quote asset string, e.g. ``"USDT"`` for ``"BTCUSDT"``.
    """
    symbol: str = order.symbol
    for quote in ("USDT", "BTC", "ETH", "BNB"):
        if symbol.endswith(quote):
            return quote
    return "USDT"
