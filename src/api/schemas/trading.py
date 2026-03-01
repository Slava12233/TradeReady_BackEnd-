"""Pydantic v2 request/response schemas for trading endpoints.

Covers the following REST endpoints (Section 15.3):
- ``POST /api/v1/trade/order``
- ``GET  /api/v1/trade/order/{order_id}``
- ``GET  /api/v1/trade/orders``
- ``GET  /api/v1/trade/orders/open``
- ``DELETE /api/v1/trade/order/{order_id}``
- ``DELETE /api/v1/trade/orders/open``
- ``GET  /api/v1/trade/history``

All ``Decimal`` price/quantity/fee fields serialise as strings to preserve
full 8-decimal precision without floating-point rounding.

Example::

    from src.api.schemas.trading import OrderRequest, OrderResponse

    req = OrderRequest(symbol="BTCUSDT", side="buy", type="market", quantity=Decimal("0.5"))
    # Limit order with price:
    req = OrderRequest(
        symbol="BTCUSDT", side="buy", type="limit",
        quantity=Decimal("0.5"), price=Decimal("63000.00"),
    )
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator


# ---------------------------------------------------------------------------
# Shared config base
# ---------------------------------------------------------------------------


class _BaseSchema(BaseModel):
    """Base schema with shared Pydantic v2 configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ---------------------------------------------------------------------------
# Order placement — request
# ---------------------------------------------------------------------------

OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop_loss", "take_profit"]
OrderStatus = Literal["pending", "filled", "partially_filled", "cancelled", "rejected", "expired"]

# Order types that require a price field
_PRICE_REQUIRED: frozenset[str] = frozenset({"limit", "stop_loss", "take_profit"})


class OrderRequest(_BaseSchema):
    """Request body for ``POST /api/v1/trade/order``.

    Market orders must NOT include ``price``; limit, stop_loss, and
    take_profit orders MUST include ``price``.

    Attributes:
        symbol:   Uppercase trading pair, e.g. ``"BTCUSDT"``.
        side:     ``"buy"`` or ``"sell"``.
        type:     One of ``"market"``, ``"limit"``, ``"stop_loss"``,
                  ``"take_profit"``.
        quantity: Base-asset quantity to trade (must be > 0).
        price:    Target / trigger price; required for non-market orders,
                  forbidden for market orders.

    Example::

        # Market order
        OrderRequest(symbol="BTCUSDT", side="buy", type="market", quantity=Decimal("0.5"))

        # Limit order
        OrderRequest(
            symbol="BTCUSDT", side="buy", type="limit",
            quantity=Decimal("0.5"), price=Decimal("63000.00"),
        )
    """

    symbol: str = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Uppercase trading pair symbol, e.g. 'BTCUSDT'.",
        examples=["BTCUSDT"],
    )
    side: OrderSide = Field(
        ...,
        description="Order direction: 'buy' or 'sell'.",
        examples=["buy"],
    )
    type: OrderType = Field(
        ...,
        description="Order type: 'market', 'limit', 'stop_loss', or 'take_profit'.",
        examples=["market"],
    )
    quantity: Decimal = Field(
        ...,
        gt=Decimal("0"),
        description="Base-asset quantity to trade (must be > 0).",
        examples=["0.50000000"],
    )
    price: Decimal | None = Field(
        default=None,
        gt=Decimal("0"),
        description=(
            "Target/trigger price. Required for 'limit', 'stop_loss', "
            "'take_profit' orders. Must be omitted for 'market' orders."
        ),
        examples=["63000.00"],
    )

    @model_validator(mode="after")
    def _validate_price_requirement(self) -> "OrderRequest":
        """Enforce price presence rules based on order type."""
        if self.type in _PRICE_REQUIRED and self.price is None:
            raise ValueError(f"'price' is required for '{self.type}' orders.")
        if self.type == "market" and self.price is not None:
            raise ValueError("'price' must not be set for 'market' orders.")
        return self

    @field_serializer("quantity")
    def _serialize_quantity(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)

    @field_serializer("price")
    def _serialize_price(self, value: Decimal | None) -> str | None:  # noqa: PLR6301
        return str(value) if value is not None else None


# ---------------------------------------------------------------------------
# Order placement — response (covers both filled and pending states)
# ---------------------------------------------------------------------------


class OrderResponse(_BaseSchema):
    """Response body for ``POST /api/v1/trade/order`` (HTTP 201).

    Fields present for a *filled* (market) order:
        ``executed_price``, ``executed_quantity``, ``slippage_pct``,
        ``fee``, ``total_cost``, ``filled_at``

    Fields present for a *pending* (limit/stop) order:
        ``price``, ``locked_amount``, ``created_at``

    All Decimal fields are serialised as strings.

    Attributes:
        order_id:           UUID of the order.
        status:             Current order status.
        symbol:             Trading pair.
        side:               ``"buy"`` or ``"sell"``.
        type:               Order type.
        requested_quantity: Original quantity from the request (filled orders).
        executed_quantity:  Actual filled quantity (filled orders).
        executed_price:     Effective fill price after slippage (filled orders).
        slippage_pct:       Realised slippage percentage (filled orders).
        fee:                Trading fee in the quote asset (filled orders).
        total_cost:         Total USDT cost/proceeds including fee (filled orders).
        filled_at:          UTC timestamp of fill (filled orders).
        quantity:           Requested quantity (pending orders).
        price:              Limit/trigger price (pending orders).
        locked_amount:      USDT reserved as collateral (pending orders).
        created_at:         UTC submission timestamp (pending orders).
    """

    order_id: UUID = Field(
        ...,
        description="UUID of the order.",
        examples=["660e8400-e29b-41d4-a716-446655440001"],
    )
    status: OrderStatus = Field(
        ...,
        description="Current order status.",
        examples=["filled"],
    )
    symbol: str = Field(
        ...,
        description="Trading pair symbol.",
        examples=["BTCUSDT"],
    )
    side: OrderSide = Field(
        ...,
        description="Order direction.",
        examples=["buy"],
    )
    type: OrderType = Field(
        ...,
        description="Order type.",
        examples=["market"],
    )

    # --- Filled order fields ---
    requested_quantity: Decimal | None = Field(
        default=None,
        description="Original requested quantity (filled market orders).",
        examples=["0.50000000"],
    )
    executed_quantity: Decimal | None = Field(
        default=None,
        description="Actual filled quantity.",
        examples=["0.50000000"],
    )
    executed_price: Decimal | None = Field(
        default=None,
        description="Effective fill price after slippage.",
        examples=["64525.18"],
    )
    slippage_pct: Decimal | None = Field(
        default=None,
        description="Realised slippage as a percentage.",
        examples=["0.006"],
    )
    fee: Decimal | None = Field(
        default=None,
        description="Trading fee deducted in the quote asset.",
        examples=["32.26"],
    )
    total_cost: Decimal | None = Field(
        default=None,
        description="Total USDT cost/proceeds including the fee.",
        examples=["32294.85"],
    )
    filled_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when the order was filled.",
        examples=["2026-02-23T15:30:45.456Z"],
    )

    # --- Pending order fields ---
    quantity: Decimal | None = Field(
        default=None,
        description="Requested base-asset quantity (pending orders).",
        examples=["0.50000000"],
    )
    price: Decimal | None = Field(
        default=None,
        description="Limit/trigger price (pending orders).",
        examples=["63000.00"],
    )
    locked_amount: Decimal | None = Field(
        default=None,
        description="USDT reserved as collateral for the pending order.",
        examples=["31515.00"],
    )
    created_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of order submission.",
        examples=["2026-02-23T15:30:45.456Z"],
    )

    @field_serializer(
        "requested_quantity", "executed_quantity", "executed_price",
        "slippage_pct", "fee", "total_cost", "quantity", "price", "locked_amount",
    )
    def _serialize_decimal(self, value: Decimal | None) -> str | None:  # noqa: PLR6301
        return str(value) if value is not None else None


# ---------------------------------------------------------------------------
# Order detail — GET /trade/order/{order_id}
# ---------------------------------------------------------------------------


class OrderDetailResponse(_BaseSchema):
    """Response body for ``GET /api/v1/trade/order/{order_id}`` (HTTP 200).

    Combines all fields for any order state into a single flat representation.

    Attributes:
        order_id:         UUID of the order.
        status:           Current order status.
        symbol:           Trading pair.
        side:             ``"buy"`` or ``"sell"``.
        type:             Order type.
        quantity:         Requested base-asset quantity.
        price:            Limit/trigger price (``None`` for market orders).
        executed_price:   Actual fill price (``None`` for pending/cancelled).
        executed_qty:     Actual filled quantity (``None`` for pending/cancelled).
        slippage_pct:     Realised slippage percentage (``None`` for pending).
        fee:              Trading fee in quote asset (``None`` for pending).
        created_at:       UTC timestamp of submission.
        filled_at:        UTC timestamp of fill (``None`` for pending/cancelled).
    """

    order_id: UUID = Field(
        ...,
        description="UUID of the order.",
        examples=["660e8400-e29b-41d4-a716-446655440001"],
    )
    status: OrderStatus = Field(
        ...,
        description="Current order status.",
        examples=["filled"],
    )
    symbol: str = Field(
        ...,
        description="Trading pair symbol.",
        examples=["BTCUSDT"],
    )
    side: OrderSide = Field(
        ...,
        description="Order direction.",
        examples=["buy"],
    )
    type: OrderType = Field(
        ...,
        description="Order type.",
        examples=["market"],
    )
    quantity: Decimal = Field(
        ...,
        description="Requested base-asset quantity.",
        examples=["0.50000000"],
    )
    price: Decimal | None = Field(
        default=None,
        description="Limit/trigger price (None for market orders).",
        examples=["63000.00"],
    )
    executed_price: Decimal | None = Field(
        default=None,
        description="Actual fill price after slippage.",
        examples=["64525.18"],
    )
    executed_qty: Decimal | None = Field(
        default=None,
        description="Actual filled quantity.",
        examples=["0.50000000"],
    )
    slippage_pct: Decimal | None = Field(
        default=None,
        description="Realised slippage as a percentage.",
        examples=["0.006"],
    )
    fee: Decimal | None = Field(
        default=None,
        description="Trading fee in quote asset.",
        examples=["32.26"],
    )
    created_at: datetime = Field(
        ...,
        description="UTC timestamp of order submission.",
        examples=["2026-02-23T15:30:45.456Z"],
    )
    filled_at: datetime | None = Field(
        default=None,
        description="UTC timestamp of fill.",
        examples=["2026-02-23T15:30:45.456Z"],
    )

    @field_serializer("quantity", "price", "executed_price", "executed_qty", "slippage_pct", "fee")
    def _serialize_decimal(self, value: Decimal | None) -> str | None:  # noqa: PLR6301
        return str(value) if value is not None else None


# ---------------------------------------------------------------------------
# Order list — GET /trade/orders, GET /trade/orders/open
# ---------------------------------------------------------------------------


class OrderListResponse(_BaseSchema):
    """Response body for ``GET /api/v1/trade/orders`` and
    ``GET /api/v1/trade/orders/open`` (HTTP 200).

    Attributes:
        orders: List of order detail objects.
        total:  Total number of matching orders (for pagination).
        limit:  Page size used in the query.
        offset: Pagination offset used in the query.
    """

    orders: list[OrderDetailResponse] = Field(
        default_factory=list,
        description="List of orders matching the query filters.",
    )
    total: int = Field(
        ...,
        ge=0,
        description="Total number of matching orders (before pagination).",
        examples=[42],
    )
    limit: int = Field(
        ...,
        ge=1,
        le=500,
        description="Page size used in the query.",
        examples=[50],
    )
    offset: int = Field(
        ...,
        ge=0,
        description="Pagination offset used in the query.",
        examples=[0],
    )


# ---------------------------------------------------------------------------
# Cancel single order — DELETE /trade/order/{order_id}
# ---------------------------------------------------------------------------


class CancelResponse(_BaseSchema):
    """Response body for ``DELETE /api/v1/trade/order/{order_id}`` (HTTP 200).

    Attributes:
        order_id:        UUID of the cancelled order.
        status:          Always ``"cancelled"``.
        unlocked_amount: USDT collateral released back to available balance.
        cancelled_at:    UTC timestamp of the cancellation.
    """

    order_id: UUID = Field(
        ...,
        description="UUID of the cancelled order.",
        examples=["660e8400-e29b-41d4-a716-446655440002"],
    )
    status: Literal["cancelled"] = Field(
        default="cancelled",
        description="Terminal status confirming cancellation.",
        examples=["cancelled"],
    )
    unlocked_amount: Decimal = Field(
        ...,
        description="USDT collateral released back to available balance.",
        examples=["31515.00"],
    )
    cancelled_at: datetime = Field(
        ...,
        description="UTC timestamp of cancellation.",
        examples=["2026-02-23T15:35:00.000Z"],
    )

    @field_serializer("unlocked_amount")
    def _serialize_unlocked(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


# ---------------------------------------------------------------------------
# Cancel all open orders — DELETE /trade/orders/open
# ---------------------------------------------------------------------------


class CancelAllResponse(_BaseSchema):
    """Response body for ``DELETE /api/v1/trade/orders/open`` (HTTP 200).

    Attributes:
        cancelled_count: Number of orders that were cancelled.
        total_unlocked:  Total USDT collateral released across all cancellations.
    """

    cancelled_count: int = Field(
        ...,
        ge=0,
        description="Number of pending orders that were cancelled.",
        examples=[5],
    )
    total_unlocked: Decimal = Field(
        ...,
        description="Total USDT collateral released back to available balance.",
        examples=["45230.00"],
    )

    @field_serializer("total_unlocked")
    def _serialize_total(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


# ---------------------------------------------------------------------------
# Trade history — GET /trade/history
# ---------------------------------------------------------------------------


class TradeHistoryItem(_BaseSchema):
    """A single executed trade record in the history response.

    Attributes:
        trade_id:       UUID of the trade record.
        order_id:       UUID of the originating order.
        symbol:         Trading pair.
        side:           ``"buy"`` or ``"sell"``.
        quantity:       Executed base-asset quantity.
        price:          Actual fill price after slippage.
        fee:            Trading fee in the quote asset.
        total:          Total quote-asset cost/proceeds including fee.
        executed_at:    UTC timestamp of execution.
    """

    trade_id: UUID = Field(
        ...,
        description="UUID of the trade record.",
        examples=["770e8400-e29b-41d4-a716-446655440010"],
    )
    order_id: UUID = Field(
        ...,
        description="UUID of the originating order.",
        examples=["660e8400-e29b-41d4-a716-446655440001"],
    )
    symbol: str = Field(
        ...,
        description="Trading pair symbol.",
        examples=["BTCUSDT"],
    )
    side: OrderSide = Field(
        ...,
        description="Trade direction.",
        examples=["buy"],
    )
    quantity: Decimal = Field(
        ...,
        description="Executed base-asset quantity.",
        examples=["0.50000000"],
    )
    price: Decimal = Field(
        ...,
        description="Actual fill price after slippage.",
        examples=["64525.18"],
    )
    fee: Decimal = Field(
        ...,
        description="Trading fee deducted in the quote asset.",
        examples=["32.26"],
    )
    total: Decimal = Field(
        ...,
        description="Total quote-asset cost/proceeds including fee.",
        examples=["32294.85"],
    )
    executed_at: datetime = Field(
        ...,
        description="UTC timestamp when the trade was executed.",
        examples=["2026-02-23T15:30:45.456Z"],
    )

    @field_serializer("quantity", "price", "fee", "total")
    def _serialize_decimal(self, value: Decimal) -> str:  # noqa: PLR6301
        return str(value)


class TradeHistoryResponse(_BaseSchema):
    """Response body for ``GET /api/v1/trade/history`` (HTTP 200).

    Attributes:
        trades: List of executed trade records.
        total:  Total number of matching trades (for pagination).
        limit:  Page size used in the query.
        offset: Pagination offset used in the query.
    """

    trades: list[TradeHistoryItem] = Field(
        default_factory=list,
        description="List of executed trade records matching the query filters.",
    )
    total: int = Field(
        ...,
        ge=0,
        description="Total number of matching trades (before pagination).",
        examples=[120],
    )
    limit: int = Field(
        ...,
        ge=1,
        le=500,
        description="Page size used in the query.",
        examples=[50],
    )
    offset: int = Field(
        ...,
        ge=0,
        description="Pagination offset used in the query.",
        examples=[0],
    )
