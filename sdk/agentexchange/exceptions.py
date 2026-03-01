"""
SDK exception hierarchy for the AgentExchange Python client.

Every HTTP error from the platform REST API maps to a typed exception so
callers can write precise ``except`` blocks instead of inspecting raw
status codes.

Usage::

    from agentexchange.exceptions import (
        AgentExchangeError,
        AuthenticationError,
        RateLimitError,
        raise_for_response,
    )

    try:
        order = client.place_market_order("BTCUSDT", "buy", 0.5)
    except InsufficientBalanceError as exc:
        print(f"Need more funds: {exc.details}")
    except RateLimitError as exc:
        time.sleep(exc.retry_after or 1)
    except AgentExchangeError as exc:
        print(f"API error [{exc.code}]: {exc.message}")
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class AgentExchangeError(Exception):
    """Base class for all AgentExchange SDK errors.

    All SDK-raised exceptions are subclasses of this class, allowing a single
    ``except AgentExchangeError`` to catch any platform error.

    Args:
        message: Human-readable description of the error.
        code: Machine-readable error code from the API (UPPER_SNAKE_CASE).
        status_code: HTTP status code returned by the server.
        details: Optional structured detail payload from the API response.

    Example:
        try:
            client.get_price("BTCUSDT")
        except AgentExchangeError as exc:
            print(exc.code, exc.message)
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "UNKNOWN_ERROR",
        status_code: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details: dict[str, Any] = details or {}

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(message={self.message!r}, "
            f"code={self.code!r}, status_code={self.status_code})"
        )

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


# ---------------------------------------------------------------------------
# Authentication (401 / 403)
# ---------------------------------------------------------------------------


class AuthenticationError(AgentExchangeError):
    """Raised when the API key or JWT is missing, invalid, or the account is
    suspended.

    Platform error codes: ``INVALID_API_KEY``, ``INVALID_TOKEN``,
    ``ACCOUNT_SUSPENDED``, ``PERMISSION_DENIED``.
    HTTP status: 401 or 403.

    Example:
        except AuthenticationError:
            # re-login or refresh credentials
    """


# ---------------------------------------------------------------------------
# Rate limiting (429)
# ---------------------------------------------------------------------------


class RateLimitError(AgentExchangeError):
    """Raised when the client has exceeded the allowed request rate.

    Platform error code: ``RATE_LIMIT_EXCEEDED``.
    HTTP status: 429.

    Attributes:
        retry_after: Seconds to wait before retrying, when provided by the
            server in the ``Retry-After`` header or ``details`` payload.

    Example:
        except RateLimitError as exc:
            time.sleep(exc.retry_after or 5)
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "RATE_LIMIT_EXCEEDED",
        status_code: int = 429,
        details: dict[str, Any] | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)
        self.retry_after: int | None = retry_after


# ---------------------------------------------------------------------------
# Insufficient funds (400)
# ---------------------------------------------------------------------------


class InsufficientBalanceError(AgentExchangeError):
    """Raised when the account does not have enough funds to place an order.

    Platform error code: ``INSUFFICIENT_BALANCE``.
    HTTP status: 400.

    Attributes:
        asset: The asset with insufficient funds (e.g. ``"USDT"``).
        required: String-formatted amount required.
        available: String-formatted amount currently available.

    Example:
        except InsufficientBalanceError as exc:
            print(f"Need {exc.required} {exc.asset}, have {exc.available}")
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "INSUFFICIENT_BALANCE",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)
        self.asset: str | None = (details or {}).get("asset")
        self.required: str | None = (details or {}).get("required")
        self.available: str | None = (details or {}).get("available")


# ---------------------------------------------------------------------------
# Order errors (400 / 404)
# ---------------------------------------------------------------------------


class OrderError(AgentExchangeError):
    """Raised for all order-related failures (rejection, not found,
    not cancellable, invalid type/quantity).

    Platform error codes: ``ORDER_REJECTED``, ``ORDER_NOT_FOUND``,
    ``ORDER_NOT_CANCELLABLE``, ``INVALID_ORDER_TYPE``, ``INVALID_QUANTITY``.
    HTTP status: 400 or 404.

    Example:
        except OrderError as exc:
            print(f"Order error {exc.code}: {exc.message}")
    """


# ---------------------------------------------------------------------------
# Symbol / market errors (400 / 503)
# ---------------------------------------------------------------------------


class InvalidSymbolError(AgentExchangeError):
    """Raised when the requested trading pair does not exist or is inactive.

    Platform error codes: ``INVALID_SYMBOL``, ``PRICE_NOT_AVAILABLE``.
    HTTP status: 400 or 503.

    Attributes:
        symbol: The invalid symbol string, when provided in the API response.

    Example:
        except InvalidSymbolError as exc:
            print(f"Unknown pair: {exc.symbol}")
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "INVALID_SYMBOL",
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)
        self.symbol: str | None = (details or {}).get("symbol")


# ---------------------------------------------------------------------------
# Not found (404)
# ---------------------------------------------------------------------------


class NotFoundError(AgentExchangeError):
    """Raised when a requested resource (account, order, trade) cannot be
    found.

    Platform error codes: ``ACCOUNT_NOT_FOUND``, ``ORDER_NOT_FOUND``,
    ``TRADE_NOT_FOUND``.
    HTTP status: 404.

    Example:
        except NotFoundError as exc:
            print(f"Resource not found: {exc.code}")
    """


# ---------------------------------------------------------------------------
# Validation errors (422)
# ---------------------------------------------------------------------------


class ValidationError(AgentExchangeError):
    """Raised when the request payload fails server-side validation (wrong
    field types, missing required parameters, out-of-range values).

    Platform error code: ``VALIDATION_ERROR``.
    HTTP status: 422.

    Attributes:
        field: The specific field that failed validation, when provided.

    Example:
        except ValidationError as exc:
            print(f"Bad field: {exc.field} — {exc.message}")
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "VALIDATION_ERROR",
        status_code: int = 422,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, code=code, status_code=status_code, details=details)
        self.field: str | None = (details or {}).get("field")


# ---------------------------------------------------------------------------
# Server-side errors (500 / 503)
# ---------------------------------------------------------------------------


class ServerError(AgentExchangeError):
    """Raised when the platform returns a 5xx response that is not a
    transient service-unavailability (those are retried internally).

    Platform error codes: ``INTERNAL_ERROR``, ``DATABASE_ERROR``,
    ``CACHE_ERROR``, ``SERVICE_UNAVAILABLE``.
    HTTP status: 500 or 503.

    Example:
        except ServerError as exc:
            logging.error("Platform error: %s", exc)
    """


# ---------------------------------------------------------------------------
# Connection / transport errors (no HTTP status)
# ---------------------------------------------------------------------------


class ConnectionError(AgentExchangeError):
    """Raised when a network-level error prevents the SDK from reaching the
    platform (DNS failure, connection refused, TLS error, timeout).

    This is not an HTTP error — ``status_code`` will be 0.

    Example:
        except ConnectionError:
            # check network / base_url config
    """


# ---------------------------------------------------------------------------
# Conflict (409)
# ---------------------------------------------------------------------------


class ConflictError(AgentExchangeError):
    """Raised when the request conflicts with existing state on the server
    (e.g. duplicate account registration).

    Platform error code: ``DUPLICATE_ACCOUNT``.
    HTTP status: 409.
    """


# ---------------------------------------------------------------------------
# Factory: raise_for_response
# ---------------------------------------------------------------------------

# Maps platform API error codes to specific exception classes.
_CODE_TO_EXCEPTION: dict[str, type[AgentExchangeError]] = {
    # Auth
    "INVALID_API_KEY": AuthenticationError,
    "INVALID_TOKEN": AuthenticationError,
    "ACCOUNT_SUSPENDED": AuthenticationError,
    "PERMISSION_DENIED": AuthenticationError,
    # Rate limit
    "RATE_LIMIT_EXCEEDED": RateLimitError,
    # Balance
    "INSUFFICIENT_BALANCE": InsufficientBalanceError,
    # Order
    "ORDER_REJECTED": OrderError,
    "ORDER_NOT_FOUND": OrderError,
    "ORDER_NOT_CANCELLABLE": OrderError,
    "INVALID_ORDER_TYPE": OrderError,
    "INVALID_QUANTITY": OrderError,
    # Symbol / market
    "INVALID_SYMBOL": InvalidSymbolError,
    "PRICE_NOT_AVAILABLE": InvalidSymbolError,
    # Not found
    "ACCOUNT_NOT_FOUND": NotFoundError,
    "TRADE_NOT_FOUND": NotFoundError,
    # Validation
    "VALIDATION_ERROR": ValidationError,
    # Conflict
    "DUPLICATE_ACCOUNT": ConflictError,
    # Server
    "INTERNAL_ERROR": ServerError,
    "DATABASE_ERROR": ServerError,
    "CACHE_ERROR": ServerError,
    "SERVICE_UNAVAILABLE": ServerError,
}

# Maps HTTP status codes to fallback exception classes when no API code is
# available (e.g. a gateway or proxy returned a bare non-JSON error).
_STATUS_TO_EXCEPTION: dict[int, type[AgentExchangeError]] = {
    401: AuthenticationError,
    403: AuthenticationError,
    404: NotFoundError,
    409: ConflictError,
    422: ValidationError,
    429: RateLimitError,
}


def raise_for_response(
    status_code: int,
    body: dict[str, Any] | None,
    *,
    retry_after: int | None = None,
) -> None:
    """Parse a platform error response and raise the appropriate exception.

    Called by the SDK clients after every non-2xx response.  Does nothing
    (returns ``None``) if ``status_code`` is in the 2xx range.

    Args:
        status_code: HTTP status code from the response.
        body: Parsed JSON body, expected to contain
            ``{"error": {"code": "...", "message": "...", "details": {...}}}``.
            May be ``None`` for empty or non-JSON responses.
        retry_after: Value of the ``Retry-After`` response header (seconds),
            forwarded to :class:`RateLimitError` when applicable.

    Raises:
        AuthenticationError: For 401 / 403 responses.
        RateLimitError: For 429 responses; ``retry_after`` is attached.
        InsufficientBalanceError: For ``INSUFFICIENT_BALANCE`` errors.
        OrderError: For order-related 400 / 404 responses.
        InvalidSymbolError: For invalid/unavailable symbol errors.
        NotFoundError: For generic 404 responses.
        ValidationError: For 422 responses.
        ConflictError: For 409 responses.
        ServerError: For 5xx responses.
        AgentExchangeError: Fallback for any unrecognised error.

    Example:
        raise_for_response(response.status_code, response.json())
    """
    if 200 <= status_code < 300:
        return

    # Extract structured error envelope.
    error_payload: dict[str, Any] = {}
    if body and isinstance(body, dict):
        error_payload = body.get("error", {}) or {}

    code: str = error_payload.get("code", "")
    message: str = error_payload.get("message", f"HTTP {status_code} error")
    details: dict[str, Any] = error_payload.get("details", {}) or {}

    # Resolve exception class: exact code match first, then HTTP-status fallback.
    exc_class: type[AgentExchangeError]
    if code in _CODE_TO_EXCEPTION:
        exc_class = _CODE_TO_EXCEPTION[code]
    elif status_code >= 500:
        exc_class = ServerError
    else:
        exc_class = _STATUS_TO_EXCEPTION.get(status_code, AgentExchangeError)

    # Build kwargs; only RateLimitError accepts retry_after.
    kwargs: dict[str, Any] = {
        "code": code or f"HTTP_{status_code}",
        "status_code": status_code,
        "details": details,
    }
    if exc_class is RateLimitError and retry_after is not None:
        kwargs["retry_after"] = retry_after

    raise exc_class(message, **kwargs)


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = [
    "AgentExchangeError",
    "AuthenticationError",
    "RateLimitError",
    "InsufficientBalanceError",
    "OrderError",
    "InvalidSymbolError",
    "NotFoundError",
    "ValidationError",
    "ConflictError",
    "ServerError",
    "ConnectionError",
    "raise_for_response",
]
