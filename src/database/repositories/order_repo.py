"""Repository for Order CRUD and lifecycle operations.

All database access for :class:`~src.database.models.Order` rows goes
through :class:`OrderRepository`.  Service classes must never issue raw
SQLAlchemy queries for orders directly.

The :meth:`OrderRepository.cancel` method enforces the state-machine
constraint that only ``pending`` (and ``partially_filled``) orders may be
cancelled; attempting to cancel a terminal order raises
:class:`~src.utils.exceptions.OrderNotCancellableError`.

Dependency direction:
    OrderEngine → OrderRepository → AsyncSession → TimescaleDB
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import func as sa_func
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.database.models import Order
from src.utils.exceptions import (
    DatabaseError,
    OrderNotCancellableError,
    OrderNotFoundError,
)

logger = structlog.get_logger(__name__)

# Statuses from which an order can be cancelled.
_CANCELLABLE_STATUSES: frozenset[str] = frozenset({"pending", "partially_filled"})

# All terminal statuses — orders in these states require no further action.
_TERMINAL_STATUSES: frozenset[str] = frozenset({"filled", "cancelled", "rejected", "expired"})


class OrderRepository:
    """Async CRUD repository for the ``orders`` table.

    Every method operates within the injected session.  Callers are
    responsible for committing; this repository never calls
    ``session.commit()`` so that multiple repo operations can participate in
    a single atomic transaction (e.g. updating an order status *and* executing
    balance changes in one commit).

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.

    Example::

        async with session_factory() as session:
            repo = OrderRepository(session)
            order = await repo.get_by_id(some_uuid)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def create(self, order: Order) -> Order:
        """Persist a new :class:`Order` row and flush to obtain server defaults.

        The ``id``, ``created_at``, and ``updated_at`` columns are populated
        by the database on flush.  The caller must commit the session to make
        the row durable.

        Args:
            order: A fully-populated (but not yet persisted) Order instance.
                   ``account_id``, ``symbol``, ``side``, ``type``, and
                   ``quantity`` must be set.

        Returns:
            The same ``order`` instance with server-generated columns filled.

        Raises:
            DatabaseError: On any SQLAlchemy / database error (including
                constraint violations from invalid ``side``, ``type``, or
                ``status`` values).

        Example::

            from decimal import Decimal
            order = Order(
                account_id=acct.id,
                symbol="BTCUSDT",
                side="buy",
                type="market",
                quantity=Decimal("0.01"),
            )
            created = await repo.create(order)
            await session.commit()
        """
        try:
            self._session.add(order)
            await self._session.flush()
            await self._session.refresh(order)
            logger.info(
                "order.created",
                extra={
                    "order_id": str(order.id),
                    "account_id": str(order.account_id),
                    "symbol": order.symbol,
                    "side": order.side,
                    "type": order.type,
                    "quantity": str(order.quantity),
                    "status": order.status,
                },
            )
            return order
        except IntegrityError as exc:
            await self._session.rollback()
            logger.exception(
                "order.create.integrity_error",
                extra={"account_id": str(order.account_id), "error": str(exc)},
            )
            raise DatabaseError(f"Integrity error while creating order: {exc}") from exc
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "order.create.db_error",
                extra={"account_id": str(order.account_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to create order.") from exc

    async def update_status(
        self,
        order_id: UUID,
        status: str,
        *,
        extra_fields: dict[str, Any] | None = None,
    ) -> Order:
        """Update the ``status`` column and any additional fields for an order.

        Used by the order engine to transition an order through its lifecycle
        (e.g. ``pending`` → ``filled``).  Pass ``extra_fields`` to update
        execution data in the same statement (e.g. ``executed_price``,
        ``executed_qty``, ``fee``, ``slippage_pct``, ``filled_at``).

        Args:
            order_id: Primary key of the order to update.
            status: New status string.  Must satisfy the ``ck_orders_status``
                    check constraint.
            extra_fields: Optional mapping of additional column names to new
                values (e.g. ``{"executed_price": Decimal("50000"),
                "filled_at": datetime.now(tz=timezone.utc)}``).

        Returns:
            The refreshed :class:`Order` instance with all updated columns.

        Raises:
            OrderNotFoundError: If no order exists with ``order_id``.
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            from datetime import datetime, timezone
            from decimal import Decimal

            filled = await repo.update_status(
                order.id,
                "filled",
                extra_fields={
                    "executed_price": Decimal("50100.00"),
                    "executed_qty": Decimal("0.01"),
                    "fee": Decimal("5.01"),
                    "slippage_pct": Decimal("0.002"),
                    "filled_at": datetime.now(tz=timezone.utc),
                },
            )
            await session.commit()
        """
        values: dict[str, Any] = {"status": status}
        if extra_fields:
            values.update(extra_fields)
        try:
            stmt = update(Order).where(Order.id == order_id).values(**values).returning(Order)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise OrderNotFoundError(order_id=order_id)
            logger.info(
                "order.status_updated",
                extra={
                    "order_id": str(order_id),
                    "new_status": status,
                    "extra_fields": list(extra_fields.keys()) if extra_fields else [],
                },
            )
            return row
        except OrderNotFoundError:
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "order.update_status.db_error",
                extra={"order_id": str(order_id), "status": status, "error": str(exc)},
            )
            raise DatabaseError("Failed to update order status.") from exc

    async def cancel(self, order_id: UUID, account_id: UUID) -> Order:
        """Cancel a ``pending`` or ``partially_filled`` order.

        Validates that the order belongs to ``account_id`` (prevents
        cross-account cancellation) and that it is in a cancellable state
        before transitioning it to ``cancelled``.

        Args:
            order_id:   Primary key of the order to cancel.
            account_id: The owning account's UUID (ownership check).

        Returns:
            The refreshed :class:`Order` instance with ``status="cancelled"``.

        Raises:
            OrderNotFoundError: If no order with ``order_id`` exists or it
                does not belong to ``account_id``.
            OrderNotCancellableError: If the order is already in a terminal
                state (``filled``, ``cancelled``, ``rejected``, ``expired``).
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            cancelled = await repo.cancel(order.id, account.id)
            await session.commit()
        """
        order = await self.get_by_id(order_id, account_id=account_id)

        if order.status not in _CANCELLABLE_STATUSES:
            raise OrderNotCancellableError(
                order_id=order_id,
                current_status=order.status,
            )

        try:
            stmt = update(Order).where(Order.id == order_id).values(status="cancelled").returning(Order)
            result = await self._session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                raise OrderNotFoundError(order_id=order_id)
            logger.info(
                "order.cancelled",
                extra={
                    "order_id": str(order_id),
                    "account_id": str(account_id),
                    "previous_status": order.status,
                },
            )
            return row
        except (OrderNotFoundError, OrderNotCancellableError):
            raise
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.exception(
                "order.cancel.db_error",
                extra={"order_id": str(order_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to cancel order.") from exc

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def get_by_id(
        self,
        order_id: UUID,
        *,
        account_id: UUID | None = None,
    ) -> Order:
        """Fetch a single order by its primary-key UUID.

        When ``account_id`` is provided the query adds an ownership filter,
        so that agents cannot read another account's orders.

        Args:
            order_id:   The order's UUID primary key.
            account_id: Optional owning account UUID for ownership enforcement.

        Returns:
            The matching :class:`Order` instance.

        Raises:
            OrderNotFoundError: If no order with ``order_id`` exists (or it
                does not belong to ``account_id`` when supplied).
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            order = await repo.get_by_id(uuid.UUID("..."))
            # with ownership check:
            order = await repo.get_by_id(uuid.UUID("..."), account_id=acct.id)
        """
        try:
            stmt = select(Order).where(Order.id == order_id)
            if account_id is not None:
                stmt = stmt.where(Order.account_id == account_id)
            result = await self._session.execute(stmt)
            order = result.scalars().first()
            if order is None:
                raise OrderNotFoundError(order_id=order_id)
            return order
        except OrderNotFoundError:
            raise
        except SQLAlchemyError as exc:
            logger.exception(
                "order.get_by_id.db_error",
                extra={"order_id": str(order_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to fetch order by ID.") from exc

    async def list_by_account(
        self,
        account_id: UUID,
        *,
        agent_id: UUID | None = None,
        status: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Order]:
        """Return a paginated list of orders for an account.

        Results are ordered by ``created_at`` descending (newest first) so
        agents see their most recent activity at the top.

        Args:
            account_id: The owning account's UUID.
            status:     Optional filter; only return orders with this status.
            symbol:     Optional filter; only return orders for this symbol.
            limit:      Maximum number of rows to return (default 100).
            offset:     Number of rows to skip for pagination (default 0).

        Returns:
            A (possibly empty) sequence of :class:`Order` instances.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            # All orders for account
            orders = await repo.list_by_account(acct.id)
            # Only open (pending) orders for BTCUSDT
            orders = await repo.list_by_account(
                acct.id, status="pending", symbol="BTCUSDT", limit=50
            )
        """
        try:
            stmt = (
                select(Order)
                .where(Order.account_id == account_id)
                .order_by(Order.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if agent_id is not None:
                stmt = stmt.where(Order.agent_id == agent_id)
            if status is not None:
                stmt = stmt.where(Order.status == status)
            if symbol is not None:
                stmt = stmt.where(Order.symbol == symbol)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "order.list_by_account.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to list orders for account.") from exc

    async def list_pending(
        self,
        *,
        symbol: str | None = None,
        limit: int = 500,
        after_id: UUID | None = None,
    ) -> Sequence[Order]:
        """Return all ``pending`` orders, optionally filtered by symbol.

        Uses keyset pagination (``WHERE id > after_id``) rather than OFFSET to
        avoid skipping orders that are inserted between page fetches.  Orders
        are returned in ascending ``id`` order so the cursor advances
        monotonically.

        Used by the background limit-order matcher to find orders that need
        price checks.  The partial index ``idx_orders_symbol_status``
        (``WHERE status = 'pending'``) makes this query very fast even with
        millions of historical orders.

        Args:
            symbol:   Optional symbol filter (e.g. ``"BTCUSDT"``).  When
                      ``None``, all pending orders across all symbols are
                      returned (used during a full matcher sweep).
            limit:    Maximum rows to fetch per call (default 500).
            after_id: Keyset cursor — only rows with ``id > after_id`` are
                      returned.  Pass ``None`` for the first page.

        Returns:
            A (possibly empty) sequence of :class:`Order` instances with
            ``status="pending"``.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            # All pending orders (matcher full sweep)
            pending = await repo.list_pending()

            # Pending orders for a specific symbol
            pending_btc = await repo.list_pending(symbol="BTCUSDT")
        """
        try:
            stmt = select(Order).where(Order.status == "pending").order_by(Order.id.asc()).limit(limit)
            if after_id is not None:
                stmt = stmt.where(Order.id > after_id)
            if symbol is not None:
                stmt = stmt.where(Order.symbol == symbol)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "order.list_pending.db_error",
                extra={"symbol": symbol, "error": str(exc)},
            )
            raise DatabaseError("Failed to list pending orders.") from exc

    async def list_open_by_account(
        self,
        account_id: UUID,
        *,
        agent_id: UUID | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> Sequence[Order]:
        """Return all open (``pending`` + ``partially_filled``) orders for an account.

        Convenience wrapper over :meth:`list_by_account` for the common API
        endpoint ``GET /trade/orders/open``.

        Args:
            account_id: The owning account's UUID.
            limit:      Maximum rows to return (default 200).
            offset:     Rows to skip (default 0).

        Returns:
            A (possibly empty) sequence of open :class:`Order` instances,
            newest first.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            open_orders = await repo.list_open_by_account(acct.id)
        """
        try:
            stmt = (
                select(Order)
                .where(
                    Order.account_id == account_id,
                    Order.status.in_(list(_CANCELLABLE_STATUSES)),
                )
                .order_by(Order.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if agent_id is not None:
                stmt = stmt.where(Order.agent_id == agent_id)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception(
                "order.list_open_by_account.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to list open orders for account.") from exc

    async def count_open_by_account(self, account_id: UUID) -> int:
        """Count open (``pending`` + ``partially_filled``) orders for an account.

        Used by the risk manager to enforce the ``max_open_orders`` limit
        before accepting a new order.

        Args:
            account_id: The owning account's UUID.

        Returns:
            The number of currently open orders.

        Raises:
            DatabaseError: On any SQLAlchemy / database error.

        Example::

            open_count = await repo.count_open_by_account(acct.id)
            if open_count >= risk_profile.max_open_orders:
                raise RiskLimitExceededError(...)
        """
        try:
            stmt = (
                select(sa_func.count())
                .select_from(Order)
                .where(
                    Order.account_id == account_id,
                    Order.status.in_(list(_CANCELLABLE_STATUSES)),
                )
            )
            result = await self._session.execute(stmt)
            count: int = result.scalar_one()
            return count
        except SQLAlchemyError as exc:
            logger.exception(
                "order.count_open_by_account.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError("Failed to count open orders for account.") from exc

    # ------------------------------------------------------------------
    # Agent-scoped queries (multi-agent transition)
    # ------------------------------------------------------------------

    async def list_by_agent(
        self,
        agent_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[Order]:
        """Return orders belonging to a specific agent."""
        try:
            stmt = (
                select(Order)
                .where(Order.agent_id == agent_id)
                .order_by(Order.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("order.list_by_agent.db_error", extra={"agent_id": str(agent_id)})
            raise DatabaseError("Failed to list orders by agent.") from exc

    async def list_open_by_agent(self, agent_id: UUID) -> Sequence[Order]:
        """Return all open orders for a specific agent."""
        try:
            stmt = (
                select(Order)
                .where(
                    Order.agent_id == agent_id,
                    Order.status.in_(list(_CANCELLABLE_STATUSES)),
                )
                .order_by(Order.created_at.desc())
            )
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except SQLAlchemyError as exc:
            logger.exception("order.list_open_by_agent.db_error", extra={"agent_id": str(agent_id)})
            raise DatabaseError("Failed to list open orders by agent.") from exc

    async def count_open_by_agent(self, agent_id: UUID) -> int:
        """Count open orders for a specific agent."""
        try:
            stmt = (
                select(sa_func.count())
                .select_from(Order)
                .where(
                    Order.agent_id == agent_id,
                    Order.status.in_(list(_CANCELLABLE_STATUSES)),
                )
            )
            result = await self._session.execute(stmt)
            return result.scalar_one()
        except SQLAlchemyError as exc:
            logger.exception("order.count_open_by_agent.db_error", extra={"agent_id": str(agent_id)})
            raise DatabaseError("Failed to count open orders by agent.") from exc
