"""Trading routes for the AI Agent Crypto Trading Platform.

Implements authenticated order management endpoints (Section 15.3):

- ``POST   /api/v1/trade/order``          — place a market/limit/stop-loss/take-profit order
- ``GET    /api/v1/trade/order/{order_id}``   — fetch a single order by ID
- ``GET    /api/v1/trade/orders``         — list all orders with optional filters
- ``GET    /api/v1/trade/orders/open``    — list all open (pending) orders
- ``DELETE /api/v1/trade/order/{order_id}``   — cancel a single pending order
- ``DELETE /api/v1/trade/orders/open``    — cancel all open orders
- ``GET    /api/v1/trade/history``        — paginated trade execution history

All endpoints require authentication via ``X-API-Key`` or ``Authorization: Bearer``.
The :class:`~src.api.middleware.auth.AuthMiddleware` resolves the account before the
handler runs; routes retrieve it through the :func:`get_current_account` dependency.

Order flow::

    POST /api/v1/trade/order
      → RiskManager.validate_order()  (8-step risk check)
      → OrderEngine.place_order()     (execution / queuing)
      → OrderResponse (HTTP 201)

Example::

    # Place a market buy order
    POST /api/v1/trade/order
    X-API-Key: ak_live_...
    {"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.001"}

    # Cancel all open orders
    DELETE /api/v1/trade/orders/open
    X-API-Key: ak_live_...
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from src.api.middleware.auth import CurrentAccountDep
from src.api.schemas.trading import (
    CancelAllResponse,
    CancelResponse,
    OrderDetailResponse,
    OrderListResponse,
    OrderRequest,
    OrderResponse,
    TradeHistoryItem,
    TradeHistoryResponse,
)
from src.database.models import Account, Order, Trade
from src.dependencies import (
    OrderEngineDep,
    OrderRepoDep,
    RiskManagerDep,
    TradeRepoDep,
)
from src.order_engine.validators import OrderRequest as EngineOrderRequest
from src.utils.exceptions import OrderRejectedError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/trade", tags=["trading"])


# ---------------------------------------------------------------------------
# Helpers: ORM → schema conversion
# ---------------------------------------------------------------------------


def _order_to_detail(order: Order) -> OrderDetailResponse:
    """Convert an ORM :class:`~src.database.models.Order` to :class:`OrderDetailResponse`.

    Args:
        order: The ORM order instance.

    Returns:
        A fully-populated :class:`OrderDetailResponse` schema.
    """
    return OrderDetailResponse(
        order_id=order.id,
        status=order.status,  # type: ignore[arg-type]
        symbol=order.symbol,
        side=order.side,  # type: ignore[arg-type]
        type=order.type,  # type: ignore[arg-type]
        quantity=Decimal(str(order.quantity)),
        price=Decimal(str(order.price)) if order.price is not None else None,
        executed_price=Decimal(str(order.executed_price)) if order.executed_price is not None else None,
        executed_qty=Decimal(str(order.executed_qty)) if order.executed_qty is not None else None,
        slippage_pct=Decimal(str(order.slippage_pct)) if order.slippage_pct is not None else None,
        fee=Decimal(str(order.fee)) if order.fee is not None else None,
        created_at=order.created_at,
        filled_at=order.filled_at if hasattr(order, "filled_at") else None,
    )


def _trade_to_item(trade: Trade) -> TradeHistoryItem:
    """Convert an ORM :class:`~src.database.models.Trade` to :class:`TradeHistoryItem`.

    Args:
        trade: The ORM trade instance.

    Returns:
        A fully-populated :class:`TradeHistoryItem` schema.
    """
    return TradeHistoryItem(
        trade_id=trade.id,
        order_id=trade.order_id,
        symbol=trade.symbol,
        side=trade.side,  # type: ignore[arg-type]
        quantity=Decimal(str(trade.quantity)),
        price=Decimal(str(trade.price)),
        fee=Decimal(str(trade.fee)),
        total=Decimal(str(trade.quote_amount)),
        executed_at=trade.created_at,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/trade/order — place a new order
# ---------------------------------------------------------------------------


@router.post(
    "/order",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Place a new order",
    description=(
        "Place a market, limit, stop-loss, or take-profit order.  "
        "The request is first validated by the risk manager (8-step check) "
        "then executed or queued by the order engine.  "
        "Market orders fill immediately; all other types are queued as ``pending``."
    ),
)
async def place_order(
    body: OrderRequest,
    account: CurrentAccountDep,
    risk: RiskManagerDep,
    engine: OrderEngineDep,
) -> OrderResponse:
    """Validate and place an order on behalf of the authenticated account.

    Steps:
    1. Construct an :class:`~src.order_engine.validators.OrderRequest` from the
       Pydantic request body (keeps the engine layer independent of FastAPI schemas).
    2. Run the 8-step risk check via :meth:`~src.risk.manager.RiskManager.validate_order`.
       Reject with ``ORDER_REJECTED`` (HTTP 400) if any limit is exceeded.
    3. Delegate to :meth:`~src.order_engine.engine.OrderEngine.place_order`.
    4. Map the :class:`~src.order_engine.engine.OrderResult` to an
       :class:`~src.api.schemas.trading.OrderResponse` (HTTP 201).

    Args:
        body:    Validated order request body.
        account: Injected authenticated account.
        risk:    Injected :class:`~src.risk.manager.RiskManager`.
        engine:  Injected :class:`~src.order_engine.engine.OrderEngine`.

    Returns:
        :class:`~src.api.schemas.trading.OrderResponse` with fill details
        (market orders) or collateral lock details (pending orders).

    Raises:
        :exc:`~src.utils.exceptions.OrderRejectedError`: If the risk check fails (HTTP 400).
        :exc:`~src.utils.exceptions.InsufficientBalanceError`: If funds are insufficient (HTTP 400).
        :exc:`~src.utils.exceptions.PriceNotAvailableError`: If the symbol has no live price (HTTP 503).
        :exc:`~src.utils.exceptions.InvalidSymbolError`: If the trading pair is unknown (HTTP 404).
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected DB failure (HTTP 500).

    Example::

        POST /api/v1/trade/order
        {"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": "0.001"}
        →  HTTP 201
        {"order_id": "...", "status": "filled", "executed_price": "64525.18", ...}
    """
    engine_request = EngineOrderRequest(
        symbol=body.symbol.upper(),
        side=body.side,
        type=body.type,
        quantity=body.quantity,
        price=body.price,
    )

    # Step 1: risk validation
    risk_result = await risk.validate_order(account.id, engine_request)
    if not risk_result.approved:
        logger.warning(
            "trading.place_order.risk_rejected",
            extra={
                "account_id": str(account.id),
                "symbol": body.symbol,
                "reason": risk_result.rejection_reason,
            },
        )
        raise OrderRejectedError(
            risk_result.rejection_reason or "Order rejected by risk manager.",
            reason=risk_result.rejection_reason,
        )

    # Step 2: execute / queue
    result = await engine.place_order(account.id, engine_request)

    logger.info(
        "trading.place_order.success",
        extra={
            "account_id": str(account.id),
            "order_id": str(result.order_id),
            "symbol": body.symbol,
            "side": body.side,
            "type": body.type,
            "status": result.status,
        },
    )

    if result.status == "filled":
        total_cost: Decimal | None = None
        if result.executed_price is not None and result.executed_quantity is not None:
            raw_cost = result.executed_price * result.executed_quantity
            fee_val = result.fee or Decimal("0")
            total_cost = raw_cost + fee_val if body.side == "buy" else raw_cost - fee_val

        return OrderResponse(
            order_id=result.order_id,
            status="filled",
            symbol=body.symbol.upper(),
            side=body.side,
            type=body.type,
            requested_quantity=body.quantity,
            executed_quantity=result.executed_quantity,
            executed_price=result.executed_price,
            slippage_pct=result.slippage_pct,
            fee=result.fee,
            total_cost=total_cost,
            filled_at=result.timestamp,
        )

    # pending order
    locked_amount: Decimal | None = None
    if body.price is not None:
        if body.side == "buy":
            fee_fraction = Decimal("0.001")
            gross = body.quantity * body.price
            locked_amount = gross + gross * fee_fraction
        else:
            locked_amount = body.quantity

    return OrderResponse(
        order_id=result.order_id,
        status="pending",
        symbol=body.symbol.upper(),
        side=body.side,
        type=body.type,
        quantity=body.quantity,
        price=body.price,
        locked_amount=locked_amount,
        created_at=result.timestamp,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/trade/order/{order_id} — fetch a single order
# ---------------------------------------------------------------------------


@router.get(
    "/order/{order_id}",
    response_model=OrderDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get order by ID",
    description="Fetch a single order by its UUID.  The order must belong to the authenticated account.",
)
async def get_order(
    order_id: UUID,
    account: CurrentAccountDep,
    order_repo: OrderRepoDep,
) -> OrderDetailResponse:
    """Fetch a single order by its UUID with an ownership check.

    Args:
        order_id:   UUID path parameter.
        account:    Injected authenticated account.
        order_repo: Injected :class:`~src.database.repositories.order_repo.OrderRepository`.

    Returns:
        :class:`~src.api.schemas.trading.OrderDetailResponse` for the matching order.

    Raises:
        :exc:`~src.utils.exceptions.OrderNotFoundError`: If the order does not
            exist or does not belong to the authenticated account (HTTP 404).
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected DB failure (HTTP 500).

    Example::

        GET /api/v1/trade/order/660e8400-e29b-41d4-a716-446655440001
        →  HTTP 200
        {"order_id": "...", "status": "filled", "symbol": "BTCUSDT", ...}
    """
    order = await order_repo.get_by_id(order_id, account_id=account.id)
    return _order_to_detail(order)


# ---------------------------------------------------------------------------
# GET /api/v1/trade/orders — list orders with filters
# ---------------------------------------------------------------------------


@router.get(
    "/orders",
    response_model=OrderListResponse,
    status_code=status.HTTP_200_OK,
    summary="List orders",
    description=(
        "Return a paginated list of orders for the authenticated account.  "
        "Filter by ``status`` and/or ``symbol``."
    ),
)
async def list_orders(
    account: CurrentAccountDep,
    order_repo: OrderRepoDep,
    status_filter: Annotated[
        str | None,
        Query(
            alias="status",
            description="Filter by order status (e.g. 'filled', 'pending', 'cancelled').",
            examples=["filled"],
        ),
    ] = None,
    symbol: Annotated[
        str | None,
        Query(
            description="Filter by trading pair symbol (e.g. 'BTCUSDT').",
            examples=["BTCUSDT"],
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of orders to return."),
    ] = 100,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of orders to skip for pagination."),
    ] = 0,
) -> OrderListResponse:
    """Return a paginated list of orders for the authenticated account.

    Args:
        account:       Injected authenticated account.
        order_repo:    Injected :class:`~src.database.repositories.order_repo.OrderRepository`.
        status_filter: Optional status filter (query param ``status``).
        symbol:        Optional symbol filter.
        limit:         Page size (1–500, default 100).
        offset:        Pagination offset (default 0).

    Returns:
        :class:`~src.api.schemas.trading.OrderListResponse` with paginated orders.

    Raises:
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected DB failure (HTTP 500).

    Example::

        GET /api/v1/trade/orders?status=filled&symbol=BTCUSDT&limit=50
        →  HTTP 200
        {"orders": [...], "total": 42, "limit": 50, "offset": 0}
    """
    orders = await order_repo.list_by_account(
        account.id,
        status=status_filter,
        symbol=symbol.upper() if symbol else None,
        limit=limit,
        offset=offset,
    )
    return OrderListResponse(
        orders=[_order_to_detail(o) for o in orders],
        total=len(orders),
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/trade/orders/open — list open orders
# ---------------------------------------------------------------------------


@router.get(
    "/orders/open",
    response_model=OrderListResponse,
    status_code=status.HTTP_200_OK,
    summary="List open orders",
    description="Return all open (pending / partially-filled) orders for the authenticated account.",
)
async def list_open_orders(
    account: CurrentAccountDep,
    order_repo: OrderRepoDep,
    limit: Annotated[
        int,
        Query(ge=1, le=200, description="Maximum number of open orders to return."),
    ] = 100,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of orders to skip for pagination."),
    ] = 0,
) -> OrderListResponse:
    """Return all open orders for the authenticated account.

    Args:
        account:    Injected authenticated account.
        order_repo: Injected :class:`~src.database.repositories.order_repo.OrderRepository`.
        limit:      Page size (1–200, default 100).
        offset:     Pagination offset (default 0).

    Returns:
        :class:`~src.api.schemas.trading.OrderListResponse` containing only
        ``pending`` and ``partially_filled`` orders.

    Raises:
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected DB failure (HTTP 500).

    Example::

        GET /api/v1/trade/orders/open
        →  HTTP 200
        {"orders": [...], "total": 3, "limit": 100, "offset": 0}
    """
    orders = await order_repo.list_open_by_account(
        account.id,
        limit=limit,
        offset=offset,
    )
    return OrderListResponse(
        orders=[_order_to_detail(o) for o in orders],
        total=len(orders),
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/trade/order/{order_id} — cancel a single order
# ---------------------------------------------------------------------------


@router.delete(
    "/order/{order_id}",
    response_model=CancelResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an order",
    description=(
        "Cancel a single pending order and release its locked collateral.  "
        "Only ``pending`` and ``partially_filled`` orders can be cancelled."
    ),
)
async def cancel_order(
    order_id: UUID,
    account: CurrentAccountDep,
    order_repo: OrderRepoDep,
    engine: OrderEngineDep,
) -> CancelResponse:
    """Cancel a single pending order and unlock its reserved funds.

    Steps:
    1. Fetch the order to determine the locked amount before cancellation.
    2. Delegate to :meth:`~src.order_engine.engine.OrderEngine.cancel_order`
       which unlocks funds and transitions the order to ``cancelled``.
    3. Return the unlock amount and cancellation timestamp.

    Args:
        order_id:   UUID path parameter of the order to cancel.
        account:    Injected authenticated account.
        order_repo: Injected :class:`~src.database.repositories.order_repo.OrderRepository`.
        engine:     Injected :class:`~src.order_engine.engine.OrderEngine`.

    Returns:
        :class:`~src.api.schemas.trading.CancelResponse` with the unlocked collateral amount.

    Raises:
        :exc:`~src.utils.exceptions.OrderNotFoundError`: If the order does not
            exist or does not belong to the authenticated account (HTTP 404).
        :exc:`~src.utils.exceptions.OrderNotCancellableError`: If the order is
            in a terminal state (HTTP 409).
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected DB failure (HTTP 500).

    Example::

        DELETE /api/v1/trade/order/660e8400-e29b-41d4-a716-446655440001
        →  HTTP 200
        {"order_id": "...", "status": "cancelled", "unlocked_amount": "31515.00", ...}
    """
    # Fetch the order first to compute the unlocked amount for the response.
    order = await order_repo.get_by_id(order_id, account_id=account.id)

    # Calculate the amount that will be unlocked (mirrors engine._release_locked_funds).
    unlocked_amount = Decimal("0")
    if order.price is not None:
        if order.side == "buy":
            gross = Decimal(str(order.quantity)) * Decimal(str(order.price))
            fee_fraction = Decimal("0.001")
            unlocked_amount = gross + gross * fee_fraction
        else:
            unlocked_amount = Decimal(str(order.quantity))

    await engine.cancel_order(account.id, order_id)

    cancelled_at = datetime.now(tz=timezone.utc)
    logger.info(
        "trading.cancel_order.success",
        extra={"account_id": str(account.id), "order_id": str(order_id)},
    )

    return CancelResponse(
        order_id=order_id,
        status="cancelled",
        unlocked_amount=unlocked_amount,
        cancelled_at=cancelled_at,
    )


# ---------------------------------------------------------------------------
# DELETE /api/v1/trade/orders/open — cancel all open orders
# ---------------------------------------------------------------------------


@router.delete(
    "/orders/open",
    response_model=CancelAllResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel all open orders",
    description=(
        "Cancel all pending / partially-filled orders for the authenticated account "
        "and release all locked collateral in a single atomic operation."
    ),
)
async def cancel_all_orders(
    account: CurrentAccountDep,
    order_repo: OrderRepoDep,
    engine: OrderEngineDep,
) -> CancelAllResponse:
    """Cancel all open orders for the authenticated account.

    Steps:
    1. Fetch all open orders to compute the total unlocked amount before cancellation.
    2. Delegate to :meth:`~src.order_engine.engine.OrderEngine.cancel_all_orders`.
    3. Return the count and total unlocked collateral.

    Args:
        account:    Injected authenticated account.
        order_repo: Injected :class:`~src.database.repositories.order_repo.OrderRepository`.
        engine:     Injected :class:`~src.order_engine.engine.OrderEngine`.

    Returns:
        :class:`~src.api.schemas.trading.CancelAllResponse` with count and total unlocked.

    Raises:
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected DB failure (HTTP 500).

    Example::

        DELETE /api/v1/trade/orders/open
        →  HTTP 200
        {"cancelled_count": 5, "total_unlocked": "45230.00"}
    """
    # Snapshot open orders before cancellation to compute total_unlocked.
    open_orders = await order_repo.list_open_by_account(account.id, limit=500)

    total_unlocked = Decimal("0")
    for order in open_orders:
        if order.price is not None:
            if order.side == "buy":
                gross = Decimal(str(order.quantity)) * Decimal(str(order.price))
                fee_fraction = Decimal("0.001")
                total_unlocked += gross + gross * fee_fraction
            else:
                total_unlocked += Decimal(str(order.quantity))

    cancelled_count = await engine.cancel_all_orders(account.id)

    logger.info(
        "trading.cancel_all_orders.success",
        extra={
            "account_id": str(account.id),
            "cancelled_count": cancelled_count,
            "total_unlocked": str(total_unlocked),
        },
    )

    return CancelAllResponse(
        cancelled_count=cancelled_count,
        total_unlocked=total_unlocked,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/trade/history — trade execution history
# ---------------------------------------------------------------------------


@router.get(
    "/history",
    response_model=TradeHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Trade execution history",
    description=(
        "Return a paginated list of executed trade fills for the authenticated account.  "
        "Filter by ``symbol`` and/or ``side``."
    ),
)
async def trade_history(
    account: CurrentAccountDep,
    trade_repo: TradeRepoDep,
    symbol: Annotated[
        str | None,
        Query(
            description="Filter by trading pair symbol (e.g. 'BTCUSDT').",
            examples=["BTCUSDT"],
        ),
    ] = None,
    side: Annotated[
        str | None,
        Query(
            description="Filter by trade direction: 'buy' or 'sell'.",
            examples=["buy"],
        ),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Maximum number of trades to return."),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of trades to skip for pagination."),
    ] = 0,
) -> TradeHistoryResponse:
    """Return a paginated trade execution history for the authenticated account.

    Args:
        account:    Injected authenticated account.
        trade_repo: Injected :class:`~src.database.repositories.trade_repo.TradeRepository`.
        symbol:     Optional symbol filter (query param).
        side:       Optional side filter: ``"buy"`` or ``"sell"`` (query param).
        limit:      Page size (1–500, default 50).
        offset:     Pagination offset (default 0).

    Returns:
        :class:`~src.api.schemas.trading.TradeHistoryResponse` with paginated trades.

    Raises:
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected DB failure (HTTP 500).

    Example::

        GET /api/v1/trade/history?symbol=BTCUSDT&side=buy&limit=20
        →  HTTP 200
        {"trades": [...], "total": 120, "limit": 20, "offset": 0}
    """
    sym = symbol.upper() if symbol else None
    trades = await trade_repo.list_by_account(
        account.id,
        symbol=sym,
        side=side,
        limit=limit,
        offset=offset,
    )
    total = await trade_repo.count_by_account(
        account.id,
        symbol=sym,
        side=side,
    )
    return TradeHistoryResponse(
        trades=[_trade_to_item(t) for t in trades],
        total=total,
        limit=limit,
        offset=offset,
    )
