"""Order Validation Rules — Component 4.

Pre-flight checks applied to every incoming :class:`OrderRequest` *before* the
order engine touches balances or risk limits.  All checks are pure (no side
effects) except for the symbol-exists / pair-is-active check, which does a
single async database read.

Validation sequence (short-circuits on the first failure):

1. ``side``     — must be ``"buy"`` or ``"sell"`` (case-insensitive).
2. ``type``     — must be one of the four supported order types.
3. ``quantity`` — must be a positive ``Decimal``.
4. ``price``    — required (and positive) for ``limit``, ``stop_loss``, ``take_profit``
                  orders; ignored for ``market`` orders.
5. Symbol       — the trading pair must exist in the ``trading_pairs`` table
                  AND have ``status = 'active'``.

Raises a domain-specific exception for each failure so the API layer can
serialise the correct HTTP response body without any additional mapping.

Example::

    validator = OrderValidator(session)
    await validator.validate(order_request)
    # raises InvalidOrderTypeError, InvalidQuantityError, InvalidSymbolError,
    # or ValidationError on failure; returns None on success
"""

from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import TradingPair
from src.utils.exceptions import (
    DatabaseError,
    InvalidOrderTypeError,
    InvalidQuantityError,
    InvalidSymbolError,
    ValidationError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SIDES: frozenset[str] = frozenset({"buy", "sell"})

VALID_ORDER_TYPES: frozenset[str] = frozenset(
    {"market", "limit", "stop_loss", "take_profit"}
)

# Order types that require an explicit price field.
PRICE_REQUIRED_TYPES: frozenset[str] = frozenset(
    {"limit", "stop_loss", "take_profit"}
)


# ---------------------------------------------------------------------------
# Request dataclass (lightweight; Pydantic schemas live in api/schemas)
# ---------------------------------------------------------------------------


class OrderRequest:
    """Minimal order descriptor passed to the validator and engine.

    Use this class (not Pydantic) inside the engine layer to keep the engine
    independent of FastAPI schema concerns.  The API layer constructs an
    :class:`OrderRequest` from the Pydantic ``OrderRequest`` schema before
    passing it downstream.

    Attributes:
        symbol:   Uppercase trading pair, e.g. ``"BTCUSDT"``.
        side:     ``"buy"`` or ``"sell"`` (case-insensitive; normalised on init).
        type:     One of ``"market"``, ``"limit"``, ``"stop_loss"``,
                  ``"take_profit"`` (case-insensitive; normalised on init).
        quantity: Amount of the *base* asset to trade.
        price:    Target / trigger price for non-market orders; ``None`` for
                  market orders.

    Example::

        req = OrderRequest(
            symbol="BTCUSDT",
            side="buy",
            type="limit",
            quantity=Decimal("0.5"),
            price=Decimal("60000"),
        )
    """

    __slots__ = ("symbol", "side", "type", "quantity", "price")

    def __init__(
        self,
        *,
        symbol: str,
        side: str,
        type: str,  # noqa: A002 — mirrors plan field name
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> None:
        self.symbol: str = symbol.upper().strip()
        self.side: str = side.lower().strip()
        self.type: str = type.lower().strip()
        self.quantity: Decimal = quantity
        self.price: Decimal | None = price

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<OrderRequest symbol={self.symbol!r} side={self.side!r} "
            f"type={self.type!r} qty={self.quantity} price={self.price}>"
        )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


class OrderValidator:
    """Stateless order validator with one async database lookup per call.

    The validator owns no state beyond the injected session.  Inject a new
    :class:`OrderValidator` per request (same lifetime as the ``AsyncSession``).

    Args:
        session: Open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.  Used
            only for the symbol-exists check; no writes are performed.

    Example::

        validator = OrderValidator(session)
        await validator.validate(order_request)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def validate(self, order: OrderRequest) -> TradingPair:
        """Run all validation checks against *order*.

        Returns the matching :class:`~src.database.models.TradingPair` row on
        success so callers can reuse the pair metadata (``base_asset``,
        ``quote_asset``, ``min_qty``, etc.) without a second database round
        trip.

        Args:
            order: The order request to validate.

        Returns:
            The active :class:`~src.database.models.TradingPair` for
            ``order.symbol``.

        Raises:
            ValidationError: If ``side`` is not ``"buy"`` or ``"sell"``.
            InvalidOrderTypeError: If ``type`` is not a supported order type.
            InvalidQuantityError: If ``quantity`` is not a positive ``Decimal``.
            ValidationError: If ``price`` is missing or non-positive for a
                limit/stop/tp order.
            InvalidSymbolError: If the symbol does not exist in
                ``trading_pairs`` or is not active.
            DatabaseError: If the database lookup fails unexpectedly.

        Example::

            pair = await validator.validate(order_request)
            base_asset = pair.base_asset   # e.g. "BTC"
        """
        self._check_side(order)
        self._check_type(order)
        self._check_quantity(order)
        self._check_price(order)
        pair = await self._check_symbol(order)
        return pair

    # ------------------------------------------------------------------
    # Individual checks (synchronous where possible)
    # ------------------------------------------------------------------

    @staticmethod
    def _check_side(order: OrderRequest) -> None:
        """Raise :class:`ValidationError` if side is not ``buy`` or ``sell``."""
        if order.side not in VALID_SIDES:
            raise ValidationError(
                f"'side' must be 'buy' or 'sell'; got {order.side!r}.",
                field="side",
            )

    @staticmethod
    def _check_type(order: OrderRequest) -> None:
        """Raise :class:`InvalidOrderTypeError` if type is not supported."""
        if order.type not in VALID_ORDER_TYPES:
            raise InvalidOrderTypeError(order_type=order.type)

    @staticmethod
    def _check_quantity(order: OrderRequest) -> None:
        """Raise :class:`InvalidQuantityError` if quantity is not positive."""
        if order.quantity <= Decimal("0"):
            raise InvalidQuantityError(
                "Order quantity must be greater than zero.",
                quantity=order.quantity,
                min_qty=Decimal("0"),
            )

    @staticmethod
    def _check_price(order: OrderRequest) -> None:
        """Raise :class:`ValidationError` if price is missing or non-positive
        for order types that require it."""
        if order.type not in PRICE_REQUIRED_TYPES:
            return

        if order.price is None:
            raise ValidationError(
                f"'price' is required for '{order.type}' orders.",
                field="price",
            )
        if order.price <= Decimal("0"):
            raise ValidationError(
                f"'price' must be a positive value for '{order.type}' orders; "
                f"got {order.price}.",
                field="price",
            )

    async def _check_symbol(self, order: OrderRequest) -> TradingPair:
        """Return the active :class:`TradingPair` or raise :class:`InvalidSymbolError`.

        Raises:
            InvalidSymbolError: If the symbol does not exist in the database
                or its ``status`` is not ``'active'``.
            DatabaseError: If the database query fails.
        """
        try:
            result = await self._session.execute(
                select(TradingPair).where(TradingPair.symbol == order.symbol)
            )
        except SQLAlchemyError as exc:
            logger.exception(
                "Database error while validating symbol %r", order.symbol
            )
            raise DatabaseError(
                f"Failed to look up trading pair '{order.symbol}'."
            ) from exc

        pair: TradingPair | None = result.scalar_one_or_none()

        if pair is None:
            raise InvalidSymbolError(symbol=order.symbol)

        if pair.status != "active":
            raise InvalidSymbolError(
                f"Trading pair '{order.symbol}' is not active (status: {pair.status!r}).",
                symbol=order.symbol,
            )

        return pair
