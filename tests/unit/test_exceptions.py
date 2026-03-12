"""Unit tests for src/utils/exceptions.py — the platform exception hierarchy.

Validates the API error contract (code, http_status, to_dict) used by every endpoint.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from src.utils.exceptions import (
    AccountSuspendedError,
    AuthenticationError,
    BacktestInvalidStateError,
    InsufficientBalanceError,
    OrderRejectedError,
    RateLimitExceededError,
    TradingPlatformError,
)

# ---------------------------------------------------------------------------
# Base error
# ---------------------------------------------------------------------------


class TestTradingPlatformError:
    def test_to_dict_default(self):
        err = TradingPlatformError("boom")
        d = err.to_dict()
        assert d == {"error": {"code": "INTERNAL_ERROR", "message": "boom"}}

    def test_to_dict_with_details(self):
        err = TradingPlatformError("boom", details={"foo": "bar"})
        d = err.to_dict()
        assert d["error"]["details"] == {"foo": "bar"}

    def test_to_dict_no_details_when_empty(self):
        err = TradingPlatformError("boom", details={})
        d = err.to_dict()
        assert "details" not in d["error"]

    def test_custom_code_and_status(self):
        err = TradingPlatformError("nope", code="CUSTOM", http_status=418)
        assert err.code == "CUSTOM"
        assert err.http_status == 418
        assert err.message == "nope"


# ---------------------------------------------------------------------------
# Auth errors
# ---------------------------------------------------------------------------


class TestAuthenticationError:
    def test_defaults(self):
        err = AuthenticationError()
        assert err.code == "INVALID_API_KEY"
        assert err.http_status == 401
        assert "Invalid or missing API key" in err.message


class TestInvalidTokenError:
    def test_defaults(self):
        from src.utils.exceptions import InvalidTokenError

        err = InvalidTokenError()
        assert err.code == "INVALID_TOKEN"
        assert err.http_status == 401


class TestAccountSuspendedError:
    def test_details_with_account_id(self):
        aid = uuid4()
        err = AccountSuspendedError(account_id=aid)
        assert err.http_status == 403
        assert err.details["account_id"] == str(aid)

    def test_no_details_without_account_id(self):
        err = AccountSuspendedError()
        assert err.details == {}


# ---------------------------------------------------------------------------
# Balance / order errors
# ---------------------------------------------------------------------------


class TestInsufficientBalanceError:
    def test_details(self):
        err = InsufficientBalanceError(
            asset="USDT",
            required=Decimal("5000"),
            available=Decimal("3000"),
        )
        assert err.http_status == 400
        assert err.details["asset"] == "USDT"
        assert err.details["required"] == "5000"
        assert err.details["available"] == "3000"
        assert "USDT" in err.message


class TestOrderRejectedError:
    def test_reason_in_details(self):
        err = OrderRejectedError("Too small", reason="min_order_size")
        assert err.code == "ORDER_REJECTED"
        assert err.details["reason"] == "min_order_size"


class TestRateLimitExceededError:
    def test_details(self):
        err = RateLimitExceededError(limit=100, window_seconds=60, retry_after=12)
        assert err.http_status == 429
        assert err.details["limit"] == 100
        assert err.details["retry_after_seconds"] == 12


# ---------------------------------------------------------------------------
# Backtest errors
# ---------------------------------------------------------------------------


class TestBacktestInvalidStateError:
    def test_details(self):
        err = BacktestInvalidStateError(
            current_status="completed",
            required_status="running",
        )
        assert err.code == "BACKTEST_INVALID_STATE"
        assert err.http_status == 409
        assert err.details["current_status"] == "completed"
        assert err.details["required_status"] == "running"


# ---------------------------------------------------------------------------
# All subclasses
# ---------------------------------------------------------------------------


def test_all_subclasses_have_correct_http_status():
    """Every concrete exception subclass must have an http_status in the valid HTTP range."""
    subclasses = TradingPlatformError.__subclasses__()
    assert len(subclasses) > 10, "Expected many subclasses"
    for cls in subclasses:
        assert 400 <= cls.http_status <= 599, f"{cls.__name__} has unexpected http_status={cls.http_status}"
