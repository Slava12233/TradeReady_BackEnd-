"""
Custom exception hierarchy for the AI Agent Crypto Trading Platform.

Every domain error maps to an error code (used in JSON responses) and an HTTP
status code.  Raise the most-specific subclass; the API middleware catches
``TradingPlatformError`` and serialises it with the correct HTTP status.

Error code → HTTP status mapping mirrors Section 15 of the development plan.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class TradingPlatformError(Exception):
    """Base class for all platform-specific errors.

    Args:
        message: Human-readable description of the error.
        code: Machine-readable error code (UPPER_SNAKE_CASE).
        http_status: HTTP status code to return to the client.
        details: Optional structured detail payload included in the response.

    Example:
        raise TradingPlatformError("Something went wrong", code="INTERNAL_ERROR", http_status=500)
    """

    code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        http_status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.details: dict[str, Any] = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the standard API error envelope.

        Returns:
            A dict with a single ``"error"`` key containing ``code``,
            ``message``, and ``details``.
        """
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return {"error": payload}


# ---------------------------------------------------------------------------
# Authentication & authorisation (4xx)
# ---------------------------------------------------------------------------


class AuthenticationError(TradingPlatformError):
    """Raised when an API key or JWT is missing, invalid, or inactive.

    Error code: ``INVALID_API_KEY``
    HTTP status: 401
    """

    code = "INVALID_API_KEY"
    http_status = 401

    def __init__(self, message: str = "Invalid or missing API key.") -> None:
        super().__init__(message)


class InvalidTokenError(TradingPlatformError):
    """Raised when a JWT token cannot be verified or has expired.

    Error code: ``INVALID_TOKEN``
    HTTP status: 401
    """

    code = "INVALID_TOKEN"
    http_status = 401

    def __init__(self, message: str = "JWT token is invalid or has expired.") -> None:
        super().__init__(message)


class AccountSuspendedError(TradingPlatformError):
    """Raised when a suspended account attempts an operation that requires
    an active status (e.g. placing orders).

    Error code: ``ACCOUNT_SUSPENDED``
    HTTP status: 403

    Args:
        account_id: The suspended account's UUID (optional, for logging).

    Example:
        raise AccountSuspendedError(account_id=account.id)
    """

    code = "ACCOUNT_SUSPENDED"
    http_status = 403

    def __init__(
        self,
        message: str = "Account is suspended.",
        *,
        account_id: UUID | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if account_id is not None:
            details["account_id"] = str(account_id)
        super().__init__(message, details=details)


class PermissionDeniedError(TradingPlatformError):
    """Raised when an account attempts an action it is not authorised to
    perform (e.g. accessing another account's data).

    Error code: ``PERMISSION_DENIED``
    HTTP status: 403
    """

    code = "PERMISSION_DENIED"
    http_status = 403

    def __init__(self, message: str = "You do not have permission to perform this action.") -> None:
        super().__init__(message)


# ---------------------------------------------------------------------------
# Rate limiting (429)
# ---------------------------------------------------------------------------


class RateLimitExceededError(TradingPlatformError):
    """Raised when a client exceeds the allowed request rate.

    Error code: ``RATE_LIMIT_EXCEEDED``
    HTTP status: 429

    Args:
        limit: The request limit that was exceeded.
        window_seconds: The sliding window length in seconds.
        retry_after: Seconds until the window resets.

    Example:
        raise RateLimitExceededError(limit=100, window_seconds=60, retry_after=12)
    """

    code = "RATE_LIMIT_EXCEEDED"
    http_status = 429

    def __init__(
        self,
        message: str = "Too many requests.",
        *,
        limit: int | None = None,
        window_seconds: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if limit is not None:
            details["limit"] = limit
        if window_seconds is not None:
            details["window_seconds"] = window_seconds
        if retry_after is not None:
            details["retry_after_seconds"] = retry_after
        super().__init__(message, details=details)


# ---------------------------------------------------------------------------
# Balance & funds (400)
# ---------------------------------------------------------------------------


class InsufficientBalanceError(TradingPlatformError):
    """Raised when an account does not have enough funds to execute a trade
    or to lock funds for a limit order.

    Error code: ``INSUFFICIENT_BALANCE``
    HTTP status: 400

    Args:
        asset: The asset that has insufficient funds (e.g. ``"USDT"``).
        required: The amount needed.
        available: The amount currently available.

    Example:
        raise InsufficientBalanceError(asset="USDT", required=Decimal("5000"), available=Decimal("3241.5"))
    """

    code = "INSUFFICIENT_BALANCE"
    http_status = 400

    def __init__(
        self,
        message: str | None = None,
        *,
        asset: str | None = None,
        required: Decimal | None = None,
        available: Decimal | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if asset is not None:
            details["asset"] = asset
        if required is not None:
            details["required"] = str(required)
        if available is not None:
            details["available"] = str(available)
        if message is None:
            if asset and required and available:
                message = (
                    f"Not enough {asset}. Required: {required}, Available: {available}"
                )
            else:
                message = "Insufficient balance to complete this operation."
        super().__init__(message, details=details)


# ---------------------------------------------------------------------------
# Order errors (400 / 404)
# ---------------------------------------------------------------------------


class OrderRejectedError(TradingPlatformError):
    """Raised when the order engine or risk manager rejects a new order.

    Error code: ``ORDER_REJECTED``
    HTTP status: 400

    Args:
        reason: Short machine-readable rejection reason
            (e.g. ``"insufficient_balance"``, ``"position_limit"``).

    Example:
        raise OrderRejectedError("Order size below minimum.", reason="min_order_size")
    """

    code = "ORDER_REJECTED"
    http_status = 400

    def __init__(
        self,
        message: str = "Order was rejected.",
        *,
        reason: str | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if reason is not None:
            details["reason"] = reason
        super().__init__(message, details=details)


class InvalidOrderTypeError(TradingPlatformError):
    """Raised when an unsupported order type is requested.

    Error code: ``INVALID_ORDER_TYPE``
    HTTP status: 400

    Args:
        order_type: The invalid order type string provided by the client.

    Example:
        raise InvalidOrderTypeError(order_type="trailing_stop")
    """

    code = "INVALID_ORDER_TYPE"
    http_status = 400

    def __init__(
        self,
        message: str | None = None,
        *,
        order_type: str | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if order_type is not None:
            details["order_type"] = order_type
        if message is None:
            supported = "market, limit, stop_loss, take_profit"
            message = (
                f"Unsupported order type '{order_type}'. Supported: {supported}"
                if order_type
                else f"Unsupported order type. Supported: {supported}"
            )
        super().__init__(message, details=details)


class InvalidQuantityError(TradingPlatformError):
    """Raised when an order quantity is below the minimum, above the maximum,
    or otherwise invalid.

    Error code: ``INVALID_QUANTITY``
    HTTP status: 400

    Args:
        quantity: The quantity that failed validation.
        min_qty: The minimum allowed quantity (if applicable).
        max_qty: The maximum allowed quantity (if applicable).

    Example:
        raise InvalidQuantityError(quantity=Decimal("0"), min_qty=Decimal("0.001"))
    """

    code = "INVALID_QUANTITY"
    http_status = 400

    def __init__(
        self,
        message: str | None = None,
        *,
        quantity: Decimal | None = None,
        min_qty: Decimal | None = None,
        max_qty: Decimal | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if quantity is not None:
            details["quantity"] = str(quantity)
        if min_qty is not None:
            details["min_qty"] = str(min_qty)
        if max_qty is not None:
            details["max_qty"] = str(max_qty)
        if message is None:
            message = "Order quantity is invalid."
        super().__init__(message, details=details)


class OrderNotFoundError(TradingPlatformError):
    """Raised when an order cannot be found by the given ID.

    Error code: ``ORDER_NOT_FOUND``
    HTTP status: 404

    Args:
        order_id: The UUID of the missing order.

    Example:
        raise OrderNotFoundError(order_id=some_uuid)
    """

    code = "ORDER_NOT_FOUND"
    http_status = 404

    def __init__(
        self,
        message: str | None = None,
        *,
        order_id: UUID | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if order_id is not None:
            details["order_id"] = str(order_id)
        if message is None:
            message = (
                f"Order '{order_id}' not found." if order_id else "Order not found."
            )
        super().__init__(message, details=details)


class TradeNotFoundError(TradingPlatformError):
    """Raised when a trade cannot be found by the given ID.

    Error code: ``TRADE_NOT_FOUND``
    HTTP status: 404

    Args:
        trade_id: The UUID of the missing trade.

    Example:
        raise TradeNotFoundError(trade_id=some_uuid)
    """

    code = "TRADE_NOT_FOUND"
    http_status = 404

    def __init__(
        self,
        message: str | None = None,
        *,
        trade_id: UUID | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if trade_id is not None:
            details["trade_id"] = str(trade_id)
        if message is None:
            message = (
                f"Trade '{trade_id}' not found." if trade_id else "Trade not found."
            )
        super().__init__(message, details=details)


class OrderNotCancellableError(TradingPlatformError):
    """Raised when a cancel request targets an order that is already filled,
    cancelled, or otherwise terminal.

    Error code: ``ORDER_NOT_CANCELLABLE``
    HTTP status: 400

    Args:
        order_id: The UUID of the non-cancellable order.
        current_status: The order's current status string.

    Example:
        raise OrderNotCancellableError(order_id=order.id, current_status="filled")
    """

    code = "ORDER_NOT_CANCELLABLE"
    http_status = 400

    def __init__(
        self,
        message: str | None = None,
        *,
        order_id: UUID | None = None,
        current_status: str | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if order_id is not None:
            details["order_id"] = str(order_id)
        if current_status is not None:
            details["current_status"] = current_status
        if message is None:
            message = (
                f"Order '{order_id}' cannot be cancelled (status: {current_status})."
                if order_id and current_status
                else "Order is not in a cancellable state."
            )
        super().__init__(message, details=details)


# ---------------------------------------------------------------------------
# Market / symbol errors (400)
# ---------------------------------------------------------------------------


class InvalidSymbolError(TradingPlatformError):
    """Raised when a requested trading pair symbol does not exist or is not
    active on the platform.

    Error code: ``INVALID_SYMBOL``
    HTTP status: 400

    Args:
        symbol: The invalid symbol string provided by the client.

    Example:
        raise InvalidSymbolError(symbol="FOOBARUSDT")
    """

    code = "INVALID_SYMBOL"
    http_status = 400

    def __init__(
        self,
        message: str | None = None,
        *,
        symbol: str | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if symbol is not None:
            details["symbol"] = symbol
        if message is None:
            message = (
                f"Trading pair '{symbol}' is not available."
                if symbol
                else "Trading pair not found."
            )
        super().__init__(message, details=details)


class PriceNotAvailableError(TradingPlatformError):
    """Raised when the current price for a symbol is not available in the
    Redis cache (e.g. the pair is stale or the ingestion service is down).

    Error code: ``PRICE_NOT_AVAILABLE``
    HTTP status: 503

    Args:
        symbol: The symbol whose price is unavailable.

    Example:
        raise PriceNotAvailableError(symbol="BTCUSDT")
    """

    code = "PRICE_NOT_AVAILABLE"
    http_status = 503

    def __init__(
        self,
        message: str | None = None,
        *,
        symbol: str | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if symbol is not None:
            details["symbol"] = symbol
        if message is None:
            message = (
                f"Current price for '{symbol}' is not available."
                if symbol
                else "Price data is not available."
            )
        super().__init__(message, details=details)


# ---------------------------------------------------------------------------
# Risk management (400 / 403)
# ---------------------------------------------------------------------------


class RiskLimitExceededError(TradingPlatformError):
    """Raised by the risk manager when an order would breach a risk limit
    (position size, max open orders, etc.).

    Error code: ``POSITION_LIMIT_EXCEEDED``
    HTTP status: 400

    Args:
        limit_type: Which limit was breached (e.g. ``"position_size"``,
            ``"max_open_orders"``).
        current_value: The current value of the breached metric.
        max_value: The maximum allowed value.

    Example:
        raise RiskLimitExceededError(limit_type="position_size", current_value=Decimal("0.26"), max_value=Decimal("0.25"))
    """

    code = "POSITION_LIMIT_EXCEEDED"
    http_status = 400

    def __init__(
        self,
        message: str = "Order would exceed risk limits.",
        *,
        limit_type: str | None = None,
        current_value: Decimal | None = None,
        max_value: Decimal | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if limit_type is not None:
            details["limit_type"] = limit_type
        if current_value is not None:
            details["current_value"] = str(current_value)
        if max_value is not None:
            details["max_value"] = str(max_value)
        super().__init__(message, details=details)


class DailyLossLimitError(TradingPlatformError):
    """Raised by the circuit breaker when the daily loss limit has been
    reached and trading is halted for the account.

    Error code: ``DAILY_LOSS_LIMIT``
    HTTP status: 403

    Args:
        account_id: The account whose trading is halted.
        daily_pnl: The current accumulated daily PnL (negative when in loss).
        loss_limit_pct: The configured loss limit as a percentage of starting balance.

    Example:
        raise DailyLossLimitError(account_id=account.id, daily_pnl=Decimal("-2500"), loss_limit_pct=Decimal("25"))
    """

    code = "DAILY_LOSS_LIMIT"
    http_status = 403

    def __init__(
        self,
        message: str = "Daily loss limit reached. Trading is halted until midnight UTC.",
        *,
        account_id: UUID | None = None,
        daily_pnl: Decimal | None = None,
        loss_limit_pct: Decimal | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if account_id is not None:
            details["account_id"] = str(account_id)
        if daily_pnl is not None:
            details["daily_pnl"] = str(daily_pnl)
        if loss_limit_pct is not None:
            details["loss_limit_pct"] = str(loss_limit_pct)
        super().__init__(message, details=details)


# ---------------------------------------------------------------------------
# Account management errors (400 / 404 / 409)
# ---------------------------------------------------------------------------


class AccountNotFoundError(TradingPlatformError):
    """Raised when an account cannot be found by ID or API key.

    Error code: ``ACCOUNT_NOT_FOUND``
    HTTP status: 404

    Args:
        account_id: The missing account's UUID (optional).

    Example:
        raise AccountNotFoundError(account_id=some_uuid)
    """

    code = "ACCOUNT_NOT_FOUND"
    http_status = 404

    def __init__(
        self,
        message: str | None = None,
        *,
        account_id: UUID | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if account_id is not None:
            details["account_id"] = str(account_id)
        if message is None:
            message = (
                f"Account '{account_id}' not found." if account_id else "Account not found."
            )
        super().__init__(message, details=details)


class DuplicateAccountError(TradingPlatformError):
    """Raised when registration fails because the email is already in use.

    Error code: ``DUPLICATE_ACCOUNT``
    HTTP status: 409

    Args:
        email: The duplicate email address.

    Example:
        raise DuplicateAccountError(email="dev@example.com")
    """

    code = "DUPLICATE_ACCOUNT"
    http_status = 409

    def __init__(
        self,
        message: str | None = None,
        *,
        email: str | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if email is not None:
            details["email"] = email
        if message is None:
            message = (
                f"An account with email '{email}' already exists."
                if email
                else "An account with that email already exists."
            )
        super().__init__(message, details=details)


# ---------------------------------------------------------------------------
# Validation errors (422)
# ---------------------------------------------------------------------------


class ValidationError(TradingPlatformError):
    """Raised for generic request payload validation failures that are not
    covered by a more specific exception.

    Error code: ``VALIDATION_ERROR``
    HTTP status: 422

    Args:
        field: The specific field that failed validation (optional).

    Example:
        raise ValidationError("'side' must be 'buy' or 'sell'.", field="side")
    """

    code = "VALIDATION_ERROR"
    http_status = 422

    def __init__(
        self,
        message: str = "Request validation failed.",
        *,
        field: str | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if field is not None:
            details["field"] = field
        super().__init__(message, details=details)


# ---------------------------------------------------------------------------
# Infrastructure / internal errors (500 / 503)
# ---------------------------------------------------------------------------


class DatabaseError(TradingPlatformError):
    """Raised when a database operation fails unexpectedly.

    Error code: ``DATABASE_ERROR``
    HTTP status: 500
    """

    code = "DATABASE_ERROR"
    http_status = 500

    def __init__(self, message: str = "A database error occurred.") -> None:
        super().__init__(message)


class CacheError(TradingPlatformError):
    """Raised when a Redis operation fails unexpectedly.

    Error code: ``CACHE_ERROR``
    HTTP status: 500
    """

    code = "CACHE_ERROR"
    http_status = 500

    def __init__(self, message: str = "A cache error occurred.") -> None:
        super().__init__(message)


class ServiceUnavailableError(TradingPlatformError):
    """Raised when a required downstream service (Redis, DB, Binance feed) is
    temporarily unavailable.

    Error code: ``SERVICE_UNAVAILABLE``
    HTTP status: 503
    """

    code = "SERVICE_UNAVAILABLE"
    http_status = 503

    def __init__(self, message: str = "Service is temporarily unavailable.") -> None:
        super().__init__(message)


# ---------------------------------------------------------------------------
# Public surface — everything callers need to import
# ---------------------------------------------------------------------------

__all__ = [
    # Base
    "TradingPlatformError",
    # Auth
    "AuthenticationError",
    "InvalidTokenError",
    "AccountSuspendedError",
    "PermissionDeniedError",
    # Rate limiting
    "RateLimitExceededError",
    # Balance
    "InsufficientBalanceError",
    # Orders
    "OrderRejectedError",
    "InvalidOrderTypeError",
    "InvalidQuantityError",
    "OrderNotFoundError",
    "OrderNotCancellableError",
    "TradeNotFoundError",
    # Market
    "InvalidSymbolError",
    "PriceNotAvailableError",
    # Risk
    "RiskLimitExceededError",
    "DailyLossLimitError",
    # Accounts
    "AccountNotFoundError",
    "DuplicateAccountError",
    # Validation
    "ValidationError",
    # Infrastructure
    "DatabaseError",
    "CacheError",
    "ServiceUnavailableError",
]
