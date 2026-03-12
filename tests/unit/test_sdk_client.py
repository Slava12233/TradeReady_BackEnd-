"""Unit tests for the AgentExchange Python SDK clients.

Tests cover:
- All 22 sync methods on AgentExchangeClient return the correct model type
- _login stores JWT; _ensure_auth refreshes when expired
- 5xx triggers retry × 3 with back-off; 4th attempt raises typed exception
- raise_for_response maps each HTTP status / error code to the right exception class
- AgentExchangeWS decorator registration (on_ticker, on_order_update, on_portfolio)
  and _dispatch routing
- Transport errors after all retries raise ConnectionError

Uses ``respx`` to mock httpx for both sync and async clients.
Uses ``unittest.mock`` for WebSocket client tests.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
import json
import time
from typing import Any
from unittest.mock import patch
from uuid import UUID

from agentexchange.async_client import AsyncAgentExchangeClient
from agentexchange.client import AgentExchangeClient
from agentexchange.exceptions import (
    AgentExchangeError,
    AuthenticationError,
    ConflictError,
    ConnectionError,
    InsufficientBalanceError,
    InvalidSymbolError,
    NotFoundError,
    OrderError,
    RateLimitError,
    ServerError,
    ValidationError,
    raise_for_response,
)
from agentexchange.models import (
    AccountInfo,
    Balance,
    Candle,
    LeaderboardEntry,
    Order,
    Performance,
    PnL,
    Portfolio,
    Position,
    Price,
    Snapshot,
    Ticker,
    Trade,
)
from agentexchange.ws_client import AgentExchangeWS
import httpx
import pytest
import respx

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE = "http://testserver"
_API_KEY = "ak_live_testkey"
_API_SECRET = "sk_live_testsecret"
_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.test"
_ORDER_ID = "550e8400-e29b-41d4-a716-446655440000"
_ACCOUNT_ID = "660e8400-e29b-41d4-a716-446655440001"
_SESSION_ID = "770e8400-e29b-41d4-a716-446655440002"
_TRADE_ID = "880e8400-e29b-41d4-a716-446655440003"
_TS = "2026-02-25T10:00:00+00:00"

_LOGIN_BODY: dict[str, Any] = {"token": _TOKEN, "expires_in": 900}

# ── Canned response payloads ────────────────────────────────────────────────

_PRICE_BODY: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "price": "64521.30",
    "timestamp": _TS,
}

_PRICES_BODY: dict[str, Any] = {
    "prices": [
        {"symbol": "BTCUSDT", "price": "64521.30", "timestamp": _TS},
        {"symbol": "ETHUSDT", "price": "3200.00", "timestamp": _TS},
    ]
}

_CANDLE: dict[str, Any] = {
    "time": _TS,
    "open": "64000.00",
    "high": "65000.00",
    "low": "63000.00",
    "close": "64521.30",
    "volume": "100.50",
    "trade_count": 500,
}
_CANDLES_BODY: dict[str, Any] = {"candles": [_CANDLE]}

_TICKER_BODY: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "open": "63000.00",
    "high": "65000.00",
    "low": "62000.00",
    "close": "64521.30",
    "volume": "5000.00",
    "quote_volume": "320000000.00",
    "change": "1521.30",
    "change_pct": "2.41",
    "trade_count": 15000,
    "timestamp": _TS,
}

_TRADES_BODY: dict[str, Any] = {
    "trades": [{"price": "64521.30", "quantity": "0.001", "side": "buy", "executed_at": _TS}]
}

_ORDERBOOK_BODY: dict[str, Any] = {
    "bids": [["64520.00", "0.5"]],
    "asks": [["64522.00", "0.3"]],
}

_ORDER_BODY: dict[str, Any] = {
    "order_id": _ORDER_ID,
    "status": "filled",
    "symbol": "BTCUSDT",
    "side": "buy",
    "type": "market",
    "quantity": "0.001",
    "price": None,
    "executed_price": "64521.30",
    "executed_quantity": "0.001",
    "requested_quantity": "0.001",
    "slippage_pct": "0.05",
    "fee": "6.45",
    "total_cost": "64527.75",
    "locked_amount": None,
    "created_at": _TS,
    "filled_at": _TS,
}

_OPEN_ORDERS_BODY: dict[str, Any] = {"orders": [_ORDER_BODY]}
_CANCEL_ALL_BODY: dict[str, Any] = {"cancelled_count": 3}

_TRADE_HISTORY_BODY: dict[str, Any] = {
    "trades": [
        {
            "trade_id": _TRADE_ID,
            "order_id": _ORDER_ID,
            "symbol": "BTCUSDT",
            "side": "buy",
            "quantity": "0.001",
            "price": "64521.30",
            "fee": "6.45",
            "total": "64527.75",
            "executed_at": _TS,
        }
    ]
}

_ACCOUNT_INFO_BODY: dict[str, Any] = {
    "account_id": _ACCOUNT_ID,
    "display_name": "TestAgent",
    "status": "active",
    "starting_balance": "10000.00",
    "created_at": _TS,
    "current_session": {
        "session_id": _SESSION_ID,
        "started_at": _TS,
    },
    "risk_profile": {
        "max_position_size_pct": 20,
        "daily_loss_limit_pct": 5,
        "max_open_orders": 10,
    },
}

_BALANCE_BODY: dict[str, Any] = {
    "balances": [
        {
            "asset": "USDT",
            "available": "9900.00",
            "locked": "100.00",
            "total": "10000.00",
        }
    ]
}

_POSITION: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "asset": "BTC",
    "quantity": "0.001",
    "avg_entry_price": "64521.30",
    "current_price": "65000.00",
    "market_value": "65.00",
    "unrealized_pnl": "0.48",
    "unrealized_pnl_pct": "0.74",
    "opened_at": _TS,
}
_POSITIONS_BODY: dict[str, Any] = {"positions": [_POSITION]}

_PORTFOLIO_BODY: dict[str, Any] = {
    "total_equity": "10065.00",
    "available_cash": "9900.00",
    "locked_cash": "100.00",
    "total_position_value": "65.00",
    "unrealized_pnl": "0.48",
    "realized_pnl": "0.00",
    "total_pnl": "0.48",
    "roi_pct": "0.65",
    "starting_balance": "10000.00",
    "positions": [_POSITION],
    "timestamp": _TS,
}

_PNL_BODY: dict[str, Any] = {
    "period": "all",
    "realized_pnl": "100.00",
    "unrealized_pnl": "0.48",
    "total_pnl": "100.48",
    "fees_paid": "6.45",
    "net_pnl": "94.03",
    "winning_trades": 10,
    "losing_trades": 2,
    "win_rate": "83.33",
}

_RESET_BODY: dict[str, Any] = {
    "session_id": _SESSION_ID,
    "starting_balance": "10000.00",
    "started_at": _TS,
}

_PERFORMANCE_BODY: dict[str, Any] = {
    "period": "all",
    "sharpe_ratio": "1.52",
    "sortino_ratio": "2.10",
    "max_drawdown_pct": "5.23",
    "max_drawdown_duration_days": 3,
    "win_rate": "83.33",
    "profit_factor": "2.50",
    "avg_win": "15.00",
    "avg_loss": "-6.00",
    "total_trades": 12,
    "avg_trades_per_day": "1.20",
    "best_trade": "50.00",
    "worst_trade": "-12.00",
    "current_streak": 3,
}

_SNAPSHOT: dict[str, Any] = {
    "time": _TS,
    "total_equity": "10065.00",
    "unrealized_pnl": "0.48",
    "realized_pnl": "100.00",
}
_HISTORY_BODY: dict[str, Any] = {"snapshots": [_SNAPSHOT]}

_LEADERBOARD_BODY: dict[str, Any] = {
    "rankings": [
        {
            "rank": 1,
            "account_id": _ACCOUNT_ID,
            "display_name": "TestAgent",
            "roi_pct": "12.50",
            "sharpe_ratio": "1.52",
            "total_trades": 12,
            "win_rate": "83.33",
        }
    ]
}


def _error_body(
    code: str,
    message: str = "error",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an API error response envelope."""
    return {"error": {"code": code, "message": message, "details": details or {}}}


# ---------------------------------------------------------------------------
# Sync client factory
# ---------------------------------------------------------------------------


def _make_client() -> AgentExchangeClient:
    return AgentExchangeClient(
        api_key=_API_KEY,
        api_secret=_API_SECRET,
        base_url=_BASE,
        timeout=5.0,
    )


# ===========================================================================
# Class: TestLogin
# ===========================================================================


class TestLogin:
    """Tests for _login and _ensure_auth JWT lifecycle."""

    def test_login_stores_jwt(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            client = _make_client()
            client._login()
            assert client._jwt == _TOKEN
            client.close()

    def test_login_sets_expiry_with_buffer(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(
                return_value=httpx.Response(200, json={"token": _TOKEN, "expires_in": 600})
            )
            client = _make_client()
            before = time.time()
            client._login()
            after = time.time()
            # expiry = time.time() + 600 - 30 (570s window)
            assert before + 570 <= client._jwt_expires_at <= after + 570
            client.close()

    def test_login_defaults_900s_expiry_when_missing(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json={"token": _TOKEN}))
            client = _make_client()
            before = time.time()
            client._login()
            after = time.time()
            assert before + 870 <= client._jwt_expires_at <= after + 870
            client.close()

    def test_ensure_auth_calls_login_when_no_jwt(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            client = _make_client()
            assert client._jwt is None
            client._ensure_auth()
            assert client._jwt == _TOKEN
            client.close()

    def test_ensure_auth_refreshes_expired_token(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            client = _make_client()
            client._jwt = "old_token"
            client._jwt_expires_at = time.time() - 1
            client._ensure_auth()
            assert client._jwt == _TOKEN
            client.close()

    def test_ensure_auth_skips_login_when_valid(self) -> None:
        # Use assert_all_called=False so the unused login route does not fail the test
        with respx.mock(base_url=_BASE, assert_all_called=False) as mock:
            login_route = mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            client = _make_client()
            client._jwt = "valid_token"
            client._jwt_expires_at = time.time() + 600
            client._ensure_auth()
            assert login_route.call_count == 0
            assert client._jwt == "valid_token"
            client.close()


# ===========================================================================
# Class: TestRetryAndErrors
# ===========================================================================


class TestRetryAndErrors:
    """Tests for 5xx retry logic and exception mapping."""

    def test_5xx_retries_then_raises_server_error(self) -> None:
        """On persistent 5xx, client retries 3 times then raises ServerError."""
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            price_route = mock.get("/api/v1/market/price/BTCUSDT").mock(
                return_value=httpx.Response(500, json=_error_body("INTERNAL_ERROR", "internal server error"))
            )
            client = _make_client()
            with patch("time.sleep"):
                with pytest.raises(ServerError):
                    client.get_price("BTCUSDT")
            # Initial + 3 retries = 4 total attempts
            assert price_route.call_count == 4
            client.close()

    def test_transport_error_after_all_retries_raises_connection_error(self) -> None:
        """Network transport failures exhaust retries and raise ConnectionError."""
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/price/BTCUSDT").mock(side_effect=httpx.ConnectError("Connection refused"))
            client = _make_client()
            with patch("time.sleep"):
                with pytest.raises(ConnectionError):
                    client.get_price("BTCUSDT")
            client.close()

    def test_4xx_does_not_retry(self) -> None:
        """4xx errors should NOT be retried — raise immediately after 1 attempt."""
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            price_route = mock.get("/api/v1/market/price/BTCUSDT").mock(
                return_value=httpx.Response(404, json=_error_body("ACCOUNT_NOT_FOUND"))
            )
            client = _make_client()
            with pytest.raises(NotFoundError):
                client.get_price("BTCUSDT")
            assert price_route.call_count == 1
            client.close()

    def test_204_no_content_cancel_returns_true(self) -> None:
        """A 204 response with no body should not raise and cancel_order returns True."""
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.delete(f"/api/v1/trade/order/{_ORDER_ID}").mock(return_value=httpx.Response(204, content=b""))
            client = _make_client()
            result = client.cancel_order(_ORDER_ID)
            assert result is True
            client.close()

    def test_5xx_recovery_on_second_attempt(self) -> None:
        """If 5xx on first attempt but 200 on retry, succeed."""
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            # First call → 500, second call → 200
            mock.get("/api/v1/market/price/BTCUSDT").mock(
                side_effect=[
                    httpx.Response(500, json=_error_body("INTERNAL_ERROR")),
                    httpx.Response(200, json=_PRICE_BODY),
                ]
            )
            client = _make_client()
            with patch("time.sleep"):
                result = client.get_price("BTCUSDT")
            assert isinstance(result, Price)
            client.close()


# ===========================================================================
# Class: TestRaiseForResponse
# ===========================================================================


class TestRaiseForResponse:
    """Tests for the raise_for_response factory function."""

    def test_2xx_does_not_raise(self) -> None:
        for status in (200, 201, 204):
            raise_for_response(status, None)

    def test_401_raises_authentication_error(self) -> None:
        with pytest.raises(AuthenticationError) as exc_info:
            raise_for_response(401, _error_body("INVALID_TOKEN", "bad token"))
        assert exc_info.value.status_code == 401
        assert exc_info.value.code == "INVALID_TOKEN"

    def test_403_raises_authentication_error(self) -> None:
        with pytest.raises(AuthenticationError):
            raise_for_response(403, _error_body("PERMISSION_DENIED"))

    def test_invalid_api_key_code(self) -> None:
        with pytest.raises(AuthenticationError) as exc_info:
            raise_for_response(401, _error_body("INVALID_API_KEY"))
        assert exc_info.value.code == "INVALID_API_KEY"

    def test_account_suspended_code(self) -> None:
        with pytest.raises(AuthenticationError) as exc_info:
            raise_for_response(403, _error_body("ACCOUNT_SUSPENDED"))
        assert exc_info.value.code == "ACCOUNT_SUSPENDED"

    def test_429_raises_rate_limit_error_with_retry_after(self) -> None:
        with pytest.raises(RateLimitError) as exc_info:
            raise_for_response(
                429,
                _error_body("RATE_LIMIT_EXCEEDED", "too many requests"),
                retry_after=10,
            )
        err = exc_info.value
        assert err.status_code == 429
        assert err.retry_after == 10

    def test_429_rate_limit_without_retry_after(self) -> None:
        with pytest.raises(RateLimitError) as exc_info:
            raise_for_response(429, _error_body("RATE_LIMIT_EXCEEDED"))
        assert exc_info.value.retry_after is None

    def test_insufficient_balance_populates_details(self) -> None:
        body = _error_body(
            "INSUFFICIENT_BALANCE",
            "not enough USDT",
            {"asset": "USDT", "required": "1000.00", "available": "500.00"},
        )
        with pytest.raises(InsufficientBalanceError) as exc_info:
            raise_for_response(400, body)
        err = exc_info.value
        assert err.asset == "USDT"
        assert err.required == "1000.00"
        assert err.available == "500.00"

    def test_order_rejected_code(self) -> None:
        with pytest.raises(OrderError) as exc_info:
            raise_for_response(400, _error_body("ORDER_REJECTED"))
        assert exc_info.value.code == "ORDER_REJECTED"

    def test_order_not_found_code(self) -> None:
        with pytest.raises(OrderError):
            raise_for_response(404, _error_body("ORDER_NOT_FOUND"))

    def test_order_not_cancellable_code(self) -> None:
        with pytest.raises(OrderError):
            raise_for_response(400, _error_body("ORDER_NOT_CANCELLABLE"))

    def test_invalid_order_type_code(self) -> None:
        with pytest.raises(OrderError):
            raise_for_response(400, _error_body("INVALID_ORDER_TYPE"))

    def test_invalid_quantity_code(self) -> None:
        with pytest.raises(OrderError):
            raise_for_response(400, _error_body("INVALID_QUANTITY"))

    def test_invalid_symbol_populates_symbol(self) -> None:
        body = _error_body("INVALID_SYMBOL", "unknown pair", {"symbol": "FAKEUSDT"})
        with pytest.raises(InvalidSymbolError) as exc_info:
            raise_for_response(400, body)
        assert exc_info.value.symbol == "FAKEUSDT"

    def test_price_not_available_code(self) -> None:
        with pytest.raises(InvalidSymbolError):
            raise_for_response(503, _error_body("PRICE_NOT_AVAILABLE"))

    def test_account_not_found_code(self) -> None:
        with pytest.raises(NotFoundError):
            raise_for_response(404, _error_body("ACCOUNT_NOT_FOUND"))

    def test_generic_404_raises_not_found_error(self) -> None:
        with pytest.raises(NotFoundError):
            raise_for_response(404, None)

    def test_validation_error_populates_field(self) -> None:
        body = _error_body("VALIDATION_ERROR", "invalid field", {"field": "quantity"})
        with pytest.raises(ValidationError) as exc_info:
            raise_for_response(422, body)
        assert exc_info.value.field == "quantity"

    def test_generic_422_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            raise_for_response(422, None)

    def test_duplicate_account_code(self) -> None:
        with pytest.raises(ConflictError):
            raise_for_response(409, _error_body("DUPLICATE_ACCOUNT"))

    def test_generic_409_raises_conflict_error(self) -> None:
        with pytest.raises(ConflictError):
            raise_for_response(409, None)

    def test_500_raises_server_error(self) -> None:
        with pytest.raises(ServerError) as exc_info:
            raise_for_response(500, _error_body("INTERNAL_ERROR"))
        assert exc_info.value.status_code == 500

    def test_503_with_service_unavailable_code(self) -> None:
        with pytest.raises(ServerError):
            raise_for_response(503, _error_body("SERVICE_UNAVAILABLE"))

    def test_database_error_code(self) -> None:
        with pytest.raises(ServerError):
            raise_for_response(500, _error_body("DATABASE_ERROR"))

    def test_bare_5xx_no_body(self) -> None:
        with pytest.raises(ServerError):
            raise_for_response(502, None)

    def test_unknown_code_falls_back_to_base_exception(self) -> None:
        with pytest.raises(AgentExchangeError):
            raise_for_response(400, _error_body("COMPLETELY_UNKNOWN_CODE"))

    def test_none_body_auth_fallback(self) -> None:
        with pytest.raises(AuthenticationError):
            raise_for_response(401, None)

    def test_error_message_extracted_from_body(self) -> None:
        with pytest.raises(AgentExchangeError) as exc_info:
            raise_for_response(401, _error_body("INVALID_TOKEN", "my custom message"))
        assert "my custom message" in str(exc_info.value)


# ===========================================================================
# Class: TestSyncMarketMethods
# ===========================================================================


class TestSyncMarketMethods:
    """Tests for the 6 sync market-data methods."""

    def test_get_price_returns_price_model(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/price/BTCUSDT").mock(return_value=httpx.Response(200, json=_PRICE_BODY))
            client = _make_client()
            result = client.get_price("BTCUSDT")
            assert isinstance(result, Price)
            assert result.symbol == "BTCUSDT"
            assert result.price == Decimal("64521.30")
            client.close()

    def test_get_all_prices_returns_list_of_price(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/prices").mock(return_value=httpx.Response(200, json=_PRICES_BODY))
            client = _make_client()
            result = client.get_all_prices()
            assert isinstance(result, list)
            assert len(result) == 2
            assert all(isinstance(p, Price) for p in result)
            client.close()

    def test_get_all_prices_empty_list(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/prices").mock(return_value=httpx.Response(200, json={"prices": []}))
            client = _make_client()
            assert client.get_all_prices() == []
            client.close()

    def test_get_candles_returns_list_of_candle(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/candles/BTCUSDT").mock(return_value=httpx.Response(200, json=_CANDLES_BODY))
            client = _make_client()
            result = client.get_candles("BTCUSDT", interval="1h", limit=24)
            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], Candle)
            assert result[0].close == Decimal("64521.30")
            client.close()

    def test_get_ticker_returns_ticker_model(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/ticker/BTCUSDT").mock(return_value=httpx.Response(200, json=_TICKER_BODY))
            client = _make_client()
            result = client.get_ticker("BTCUSDT")
            assert isinstance(result, Ticker)
            assert result.symbol == "BTCUSDT"
            assert result.trade_count == 15000
            client.close()

    def test_get_recent_trades_returns_list_of_dicts(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/trades/BTCUSDT").mock(return_value=httpx.Response(200, json=_TRADES_BODY))
            client = _make_client()
            result = client.get_recent_trades("BTCUSDT", limit=10)
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0]["side"] == "buy"
            client.close()

    def test_get_orderbook_returns_dict_with_bids_asks(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/orderbook/BTCUSDT").mock(return_value=httpx.Response(200, json=_ORDERBOOK_BODY))
            client = _make_client()
            result = client.get_orderbook("BTCUSDT", depth=5)
            assert isinstance(result, dict)
            assert "bids" in result
            assert "asks" in result
            client.close()


# ===========================================================================
# Class: TestSyncTradingMethods
# ===========================================================================


class TestSyncTradingMethods:
    """Tests for the 9 sync trading methods (including get_trade_history)."""

    def test_place_market_order_returns_filled_order(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.post("/api/v1/trade/order").mock(return_value=httpx.Response(200, json=_ORDER_BODY))
            client = _make_client()
            result = client.place_market_order("BTCUSDT", "buy", Decimal("0.001"))
            assert isinstance(result, Order)
            assert result.order_id == UUID(_ORDER_ID)
            assert result.status == "filled"
            assert result.type == "market"
            client.close()

    def test_place_market_order_sends_correct_body(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            order_route = mock.post("/api/v1/trade/order").mock(return_value=httpx.Response(200, json=_ORDER_BODY))
            client = _make_client()
            client.place_market_order("BTCUSDT", "buy", "0.001")
            sent = json.loads(order_route.calls.last.request.content)
            assert sent["type"] == "market"
            assert sent["symbol"] == "BTCUSDT"
            assert sent["side"] == "buy"
            assert "price" not in sent
            client.close()

    def test_place_limit_order_returns_pending_order(self) -> None:
        limit_order = {**_ORDER_BODY, "type": "limit", "status": "pending", "price": "60000.00"}
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.post("/api/v1/trade/order").mock(return_value=httpx.Response(200, json=limit_order))
            client = _make_client()
            result = client.place_limit_order("BTCUSDT", "buy", "0.001", 60000)
            assert isinstance(result, Order)
            assert result.type == "limit"
            assert result.status == "pending"
            client.close()

    def test_place_limit_order_sends_price_in_body(self) -> None:
        limit_order = {**_ORDER_BODY, "type": "limit", "status": "pending", "price": "60000"}
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            order_route = mock.post("/api/v1/trade/order").mock(return_value=httpx.Response(200, json=limit_order))
            client = _make_client()
            client.place_limit_order("BTCUSDT", "buy", "0.001", "60000")
            sent = json.loads(order_route.calls.last.request.content)
            assert sent["type"] == "limit"
            assert "price" in sent
            assert sent["price"] == "60000"
            client.close()

    def test_place_stop_loss_returns_order(self) -> None:
        sl_order = {**_ORDER_BODY, "type": "stop_loss", "status": "pending"}
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.post("/api/v1/trade/order").mock(return_value=httpx.Response(200, json=sl_order))
            client = _make_client()
            result = client.place_stop_loss("BTCUSDT", "sell", "0.001", 58000)
            assert isinstance(result, Order)
            assert result.type == "stop_loss"
            client.close()

    def test_place_take_profit_returns_order(self) -> None:
        tp_order = {**_ORDER_BODY, "type": "take_profit", "status": "pending"}
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.post("/api/v1/trade/order").mock(return_value=httpx.Response(200, json=tp_order))
            client = _make_client()
            result = client.place_take_profit("BTCUSDT", "sell", "0.001", 70000)
            assert isinstance(result, Order)
            assert result.type == "take_profit"
            client.close()

    def test_get_order_returns_order(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get(f"/api/v1/trade/order/{_ORDER_ID}").mock(return_value=httpx.Response(200, json=_ORDER_BODY))
            client = _make_client()
            result = client.get_order(_ORDER_ID)
            assert isinstance(result, Order)
            assert str(result.order_id) == _ORDER_ID
            client.close()

    def test_get_open_orders_returns_list_of_order(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/trade/orders/open").mock(return_value=httpx.Response(200, json=_OPEN_ORDERS_BODY))
            client = _make_client()
            result = client.get_open_orders()
            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], Order)
            client.close()

    def test_cancel_order_returns_true(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.delete(f"/api/v1/trade/order/{_ORDER_ID}").mock(return_value=httpx.Response(204, content=b""))
            client = _make_client()
            assert client.cancel_order(_ORDER_ID) is True
            client.close()

    def test_cancel_all_orders_returns_count(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.delete("/api/v1/trade/orders/open").mock(return_value=httpx.Response(200, json=_CANCEL_ALL_BODY))
            client = _make_client()
            assert client.cancel_all_orders() == 3
            client.close()

    def test_get_trade_history_returns_list_of_trade(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/trade/history").mock(return_value=httpx.Response(200, json=_TRADE_HISTORY_BODY))
            client = _make_client()
            result = client.get_trade_history(symbol="BTCUSDT", limit=100)
            assert isinstance(result, list)
            assert len(result) == 1
            t = result[0]
            assert isinstance(t, Trade)
            assert t.trade_id == UUID(_TRADE_ID)
            assert t.symbol == "BTCUSDT"
            client.close()


# ===========================================================================
# Class: TestSyncAccountMethods
# ===========================================================================


class TestSyncAccountMethods:
    """Tests for the 6 sync account methods."""

    def test_get_account_info_returns_account_info(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/account/info").mock(return_value=httpx.Response(200, json=_ACCOUNT_INFO_BODY))
            client = _make_client()
            result = client.get_account_info()
            assert isinstance(result, AccountInfo)
            assert result.display_name == "TestAgent"
            assert result.status == "active"
            assert result.max_open_orders == 10
            client.close()

    def test_get_balance_returns_list_of_balance(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/account/balance").mock(return_value=httpx.Response(200, json=_BALANCE_BODY))
            client = _make_client()
            result = client.get_balance()
            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], Balance)
            assert result[0].asset == "USDT"
            assert result[0].available == Decimal("9900.00")
            client.close()

    def test_get_positions_returns_list_of_position(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/account/positions").mock(return_value=httpx.Response(200, json=_POSITIONS_BODY))
            client = _make_client()
            result = client.get_positions()
            assert isinstance(result, list)
            assert isinstance(result[0], Position)
            assert result[0].symbol == "BTCUSDT"
            client.close()

    def test_get_portfolio_returns_portfolio(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/account/portfolio").mock(return_value=httpx.Response(200, json=_PORTFOLIO_BODY))
            client = _make_client()
            result = client.get_portfolio()
            assert isinstance(result, Portfolio)
            assert result.total_equity == Decimal("10065.00")
            assert len(result.positions) == 1
            client.close()

    def test_get_pnl_returns_pnl(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/account/pnl").mock(return_value=httpx.Response(200, json=_PNL_BODY))
            client = _make_client()
            result = client.get_pnl(period="all")
            assert isinstance(result, PnL)
            assert result.period == "all"
            assert result.winning_trades == 10
            client.close()

    def test_reset_account_returns_dict_with_session_id(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.post("/api/v1/account/reset").mock(return_value=httpx.Response(200, json=_RESET_BODY))
            client = _make_client()
            result = client.reset_account(starting_balance=Decimal("10000"))
            assert isinstance(result, dict)
            assert result["session_id"] == _SESSION_ID
            client.close()


# ===========================================================================
# Class: TestSyncAnalyticsMethods
# ===========================================================================


class TestSyncAnalyticsMethods:
    """Tests for the 3 sync analytics methods."""

    def test_get_performance_returns_performance(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/analytics/performance").mock(return_value=httpx.Response(200, json=_PERFORMANCE_BODY))
            client = _make_client()
            result = client.get_performance(period="all")
            assert isinstance(result, Performance)
            assert result.total_trades == 12
            assert result.current_streak == 3
            client.close()

    def test_get_portfolio_history_returns_list_of_snapshot(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/analytics/portfolio/history").mock(return_value=httpx.Response(200, json=_HISTORY_BODY))
            client = _make_client()
            result = client.get_portfolio_history(interval="1h", limit=168)
            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], Snapshot)
            assert result[0].total_equity == Decimal("10065.00")
            client.close()

    def test_get_leaderboard_returns_list_of_entries(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/analytics/leaderboard").mock(return_value=httpx.Response(200, json=_LEADERBOARD_BODY))
            client = _make_client()
            result = client.get_leaderboard(period="all", limit=20)
            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], LeaderboardEntry)
            assert result[0].rank == 1
            assert result[0].display_name == "TestAgent"
            client.close()


# ===========================================================================
# Class: TestContextManager
# ===========================================================================


class TestContextManager:
    """Tests for the sync client context manager."""

    def test_context_manager_closes_on_exit(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/price/BTCUSDT").mock(return_value=httpx.Response(200, json=_PRICE_BODY))
            with AgentExchangeClient(api_key=_API_KEY, api_secret=_API_SECRET, base_url=_BASE) as client:
                price = client.get_price("BTCUSDT")
                assert isinstance(price, Price)
            # After __exit__ the underlying httpx client is closed; further requests fail
            with pytest.raises(Exception):  # noqa: B017
                client.get_price("BTCUSDT")


# ===========================================================================
# Class: TestWSHandlerRegistration
# ===========================================================================


class TestWSHandlerRegistration:
    """Tests for AgentExchangeWS decorator registration."""

    def test_on_ticker_specific_symbol_registers_handler(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)

        @ws.on_ticker("BTCUSDT")
        async def handler(data: dict) -> None:  # noqa: RUF029
            pass

        assert "ticker:BTCUSDT" in ws._subscriptions
        assert handler in ws._handlers["ticker:BTCUSDT"]

    def test_on_ticker_all_uses_wildcard_channel(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)

        @ws.on_ticker("all")
        async def handler(data: dict) -> None:  # noqa: RUF029
            pass

        assert "ticker:all" in ws._subscriptions
        assert handler in ws._handlers["ticker:all"]

    def test_on_ticker_case_insensitive_all(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)

        @ws.on_ticker("ALL")
        async def handler(data: dict) -> None:  # noqa: RUF029
            pass

        assert "ticker:all" in ws._subscriptions

    def test_on_candles_registers_handler(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)

        @ws.on_candles("ETHUSDT", "1m")
        async def handler(data: dict) -> None:  # noqa: RUF029
            pass

        assert "candles:ETHUSDT:1m" in ws._subscriptions
        assert handler in ws._handlers["candles:ETHUSDT:1m"]

    def test_on_order_update_registers_handler(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)

        @ws.on_order_update()
        async def handler(data: dict) -> None:  # noqa: RUF029
            pass

        assert "orders" in ws._subscriptions
        assert handler in ws._handlers["orders"]

    def test_on_portfolio_registers_handler(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)

        @ws.on_portfolio()
        async def handler(data: dict) -> None:  # noqa: RUF029
            pass

        assert "portfolio" in ws._subscriptions
        assert handler in ws._handlers["portfolio"]

    def test_multiple_handlers_for_same_channel(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)

        @ws.on_order_update()
        async def handler_a(data: dict) -> None:  # noqa: RUF029
            pass

        @ws.on_order_update()
        async def handler_b(data: dict) -> None:  # noqa: RUF029
            pass

        assert len(ws._handlers["orders"]) == 2

    def test_decorator_returns_original_function(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)

        async def my_handler(data: dict) -> None:  # noqa: RUF029
            pass

        result = ws.on_ticker("BTCUSDT")(my_handler)
        assert result is my_handler

    def test_subscribe_adds_channel(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)
        ws.subscribe("candles:BTCUSDT:5m")
        assert "candles:BTCUSDT:5m" in ws._subscriptions

    def test_unsubscribe_removes_channel(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)
        ws.subscribe("orders")
        ws.unsubscribe("orders")
        assert "orders" not in ws._subscriptions


# ===========================================================================
# Class: TestWSDispatch
# ===========================================================================


@pytest.mark.asyncio
class TestWSDispatch:
    """Tests for AgentExchangeWS._dispatch message routing."""

    async def test_dispatch_ticker_by_type_field(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)
        received: list[dict] = []

        @ws.on_ticker("BTCUSDT")
        async def handler(data: dict) -> None:
            received.append(data)

        await ws._dispatch({"type": "ticker", "symbol": "BTCUSDT", "price": "64521.30"})
        assert len(received) == 1
        assert received[0]["symbol"] == "BTCUSDT"

    async def test_dispatch_ticker_to_wildcard_all_handler(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)
        all_received: list[dict] = []
        specific_received: list[dict] = []

        @ws.on_ticker("all")
        async def all_handler(data: dict) -> None:
            all_received.append(data)

        @ws.on_ticker("BTCUSDT")
        async def specific_handler(data: dict) -> None:
            specific_received.append(data)

        await ws._dispatch({"type": "ticker", "symbol": "BTCUSDT", "price": "64521.30"})
        assert len(all_received) == 1
        assert len(specific_received) == 1

    async def test_dispatch_ticker_all_does_not_double_fire(self) -> None:
        """A ticker:all message should not trigger the wildcard handler twice."""
        ws = AgentExchangeWS(api_key=_API_KEY)
        calls: list[dict] = []

        @ws.on_ticker("all")
        async def handler(data: dict) -> None:
            calls.append(data)

        await ws._dispatch({"type": "ticker", "channel": "ticker:all", "price": "1.00"})
        assert len(calls) == 1

    async def test_dispatch_candle_message(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)
        received: list[dict] = []

        @ws.on_candles("ETHUSDT", "1m")
        async def handler(data: dict) -> None:
            received.append(data)

        await ws._dispatch({"type": "candle", "symbol": "ETHUSDT", "interval": "1m", "close": "3200.00"})
        assert len(received) == 1

    async def test_dispatch_order_update_message(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)
        received: list[dict] = []

        @ws.on_order_update()
        async def handler(data: dict) -> None:
            received.append(data)

        await ws._dispatch({"type": "order_update", "order_id": _ORDER_ID, "status": "filled"})
        assert len(received) == 1

    async def test_dispatch_order_type_also_routes_to_orders(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)
        received: list[dict] = []

        @ws.on_order_update()
        async def handler(data: dict) -> None:
            received.append(data)

        await ws._dispatch({"type": "order", "order_id": _ORDER_ID, "status": "pending"})
        assert len(received) == 1

    async def test_dispatch_portfolio_message(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)
        received: list[dict] = []

        @ws.on_portfolio()
        async def handler(data: dict) -> None:
            received.append(data)

        await ws._dispatch({"type": "portfolio", "total_value": "10065.00"})
        assert len(received) == 1

    async def test_dispatch_explicit_channel_field_routes_correctly(self) -> None:
        """When message has an explicit 'channel' field, use it for routing."""
        ws = AgentExchangeWS(api_key=_API_KEY)
        received: list[dict] = []

        @ws.on_ticker("BTCUSDT")
        async def handler(data: dict) -> None:
            received.append(data)

        await ws._dispatch({"type": "update", "channel": "ticker:BTCUSDT", "price": "64521.30"})
        assert len(received) == 1

    async def test_dispatch_unknown_type_is_silently_ignored(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)
        await ws._dispatch({"type": "unknown_message_type", "data": "x"})

    async def test_dispatch_handler_exception_does_not_propagate(self) -> None:
        """A handler that raises should not crash the dispatch loop."""
        ws = AgentExchangeWS(api_key=_API_KEY)
        good_received: list[dict] = []

        @ws.on_ticker("BTCUSDT")
        async def bad_handler(data: dict) -> None:
            raise RuntimeError("handler crash")

        @ws.on_ticker("BTCUSDT")
        async def good_handler(data: dict) -> None:
            good_received.append(data)

        await ws._dispatch({"type": "ticker", "symbol": "BTCUSDT", "price": "64521.30"})
        assert len(good_received) == 1

    async def test_dispatch_no_handler_registered_does_not_raise(self) -> None:
        """Dispatch with no matching handler should silently skip."""
        ws = AgentExchangeWS(api_key=_API_KEY)
        ws.subscribe("orders")
        await ws._dispatch({"type": "order_update", "order_id": _ORDER_ID})


# ===========================================================================
# Class: TestWSLifecycle
# ===========================================================================


class TestWSLifecycle:
    """Tests for AgentExchangeWS disconnect and repr."""

    def test_disconnect_sets_running_false(self) -> None:
        ws = AgentExchangeWS(api_key=_API_KEY)
        ws._running = True
        asyncio.run(ws.disconnect())
        assert ws._running is False

    def test_repr_contains_key_preview_and_ellipsis(self) -> None:
        ws = AgentExchangeWS(api_key="ak_live_testkey123456")
        r = repr(ws)
        assert "ak_live_tes" in r
        assert "..." in r

    def test_repr_short_key_no_truncation(self) -> None:
        ws = AgentExchangeWS(api_key="short")
        r = repr(ws)
        assert "short" in r


# ===========================================================================
# Class: TestAsyncClientAllMethods
# ===========================================================================


@pytest.mark.asyncio
class TestAsyncClientAllMethods:
    """Verify all 22 async methods on AsyncAgentExchangeClient return the
    correct model type, using respx to mock httpx.AsyncClient."""

    async def _make(self) -> AsyncAgentExchangeClient:
        return AsyncAgentExchangeClient(
            api_key=_API_KEY,
            api_secret=_API_SECRET,
            base_url=_BASE,
            timeout=5.0,
        )

    # ── Market (6) ───────────────────────────────────────────────────────────

    async def test_get_price(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/price/BTCUSDT").mock(return_value=httpx.Response(200, json=_PRICE_BODY))
            client = await self._make()
            result = await client.get_price("BTCUSDT")
            assert isinstance(result, Price)
            assert result.symbol == "BTCUSDT"
            await client.aclose()

    async def test_get_all_prices(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/prices").mock(return_value=httpx.Response(200, json=_PRICES_BODY))
            client = await self._make()
            result = await client.get_all_prices()
            assert isinstance(result, list)
            assert all(isinstance(p, Price) for p in result)
            await client.aclose()

    async def test_get_candles(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/candles/BTCUSDT").mock(return_value=httpx.Response(200, json=_CANDLES_BODY))
            client = await self._make()
            result = await client.get_candles("BTCUSDT")
            assert isinstance(result, list)
            assert isinstance(result[0], Candle)
            await client.aclose()

    async def test_get_ticker(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/ticker/BTCUSDT").mock(return_value=httpx.Response(200, json=_TICKER_BODY))
            client = await self._make()
            result = await client.get_ticker("BTCUSDT")
            assert isinstance(result, Ticker)
            await client.aclose()

    async def test_get_recent_trades(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/trades/BTCUSDT").mock(return_value=httpx.Response(200, json=_TRADES_BODY))
            client = await self._make()
            result = await client.get_recent_trades("BTCUSDT")
            assert isinstance(result, list)
            await client.aclose()

    async def test_get_orderbook(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/orderbook/BTCUSDT").mock(return_value=httpx.Response(200, json=_ORDERBOOK_BODY))
            client = await self._make()
            result = await client.get_orderbook("BTCUSDT")
            assert isinstance(result, dict)
            await client.aclose()

    # ── Trading (8) ──────────────────────────────────────────────────────────

    async def test_place_market_order(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.post("/api/v1/trade/order").mock(return_value=httpx.Response(200, json=_ORDER_BODY))
            client = await self._make()
            result = await client.place_market_order("BTCUSDT", "buy", Decimal("0.001"))
            assert isinstance(result, Order)
            assert result.status == "filled"
            await client.aclose()

    async def test_place_limit_order(self) -> None:
        limit_order = {**_ORDER_BODY, "type": "limit", "status": "pending", "price": "60000.00"}
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.post("/api/v1/trade/order").mock(return_value=httpx.Response(200, json=limit_order))
            client = await self._make()
            result = await client.place_limit_order("BTCUSDT", "buy", "0.001", 60000)
            assert isinstance(result, Order)
            await client.aclose()

    async def test_place_stop_loss(self) -> None:
        sl_order = {**_ORDER_BODY, "type": "stop_loss", "status": "pending"}
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.post("/api/v1/trade/order").mock(return_value=httpx.Response(200, json=sl_order))
            client = await self._make()
            result = await client.place_stop_loss("BTCUSDT", "sell", "0.001", 58000)
            assert isinstance(result, Order)
            await client.aclose()

    async def test_place_take_profit(self) -> None:
        tp_order = {**_ORDER_BODY, "type": "take_profit", "status": "pending"}
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.post("/api/v1/trade/order").mock(return_value=httpx.Response(200, json=tp_order))
            client = await self._make()
            result = await client.place_take_profit("BTCUSDT", "sell", "0.001", 70000)
            assert isinstance(result, Order)
            await client.aclose()

    async def test_get_order(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get(f"/api/v1/trade/order/{_ORDER_ID}").mock(return_value=httpx.Response(200, json=_ORDER_BODY))
            client = await self._make()
            result = await client.get_order(_ORDER_ID)
            assert isinstance(result, Order)
            await client.aclose()

    async def test_get_open_orders(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/trade/orders/open").mock(return_value=httpx.Response(200, json=_OPEN_ORDERS_BODY))
            client = await self._make()
            result = await client.get_open_orders()
            assert isinstance(result, list)
            assert isinstance(result[0], Order)
            await client.aclose()

    async def test_cancel_order(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.delete(f"/api/v1/trade/order/{_ORDER_ID}").mock(return_value=httpx.Response(204, content=b""))
            client = await self._make()
            result = await client.cancel_order(_ORDER_ID)
            assert result is True
            await client.aclose()

    async def test_cancel_all_orders(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.delete("/api/v1/trade/orders/open").mock(return_value=httpx.Response(200, json=_CANCEL_ALL_BODY))
            client = await self._make()
            result = await client.cancel_all_orders()
            assert result == 3
            await client.aclose()

    async def test_get_trade_history(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/trade/history").mock(return_value=httpx.Response(200, json=_TRADE_HISTORY_BODY))
            client = await self._make()
            result = await client.get_trade_history(limit=50)
            assert isinstance(result, list)
            assert isinstance(result[0], Trade)
            await client.aclose()

    # ── Account (5) ──────────────────────────────────────────────────────────

    async def test_get_account_info(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/account/info").mock(return_value=httpx.Response(200, json=_ACCOUNT_INFO_BODY))
            client = await self._make()
            result = await client.get_account_info()
            assert isinstance(result, AccountInfo)
            await client.aclose()

    async def test_get_balance(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/account/balance").mock(return_value=httpx.Response(200, json=_BALANCE_BODY))
            client = await self._make()
            result = await client.get_balance()
            assert isinstance(result, list)
            assert isinstance(result[0], Balance)
            await client.aclose()

    async def test_get_positions(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/account/positions").mock(return_value=httpx.Response(200, json=_POSITIONS_BODY))
            client = await self._make()
            result = await client.get_positions()
            assert isinstance(result, list)
            assert isinstance(result[0], Position)
            await client.aclose()

    async def test_get_portfolio(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/account/portfolio").mock(return_value=httpx.Response(200, json=_PORTFOLIO_BODY))
            client = await self._make()
            result = await client.get_portfolio()
            assert isinstance(result, Portfolio)
            await client.aclose()

    async def test_get_pnl(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/account/pnl").mock(return_value=httpx.Response(200, json=_PNL_BODY))
            client = await self._make()
            result = await client.get_pnl()
            assert isinstance(result, PnL)
            await client.aclose()

    async def test_reset_account(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.post("/api/v1/account/reset").mock(return_value=httpx.Response(200, json=_RESET_BODY))
            client = await self._make()
            result = await client.reset_account()
            assert isinstance(result, dict)
            await client.aclose()

    # ── Analytics (3) ────────────────────────────────────────────────────────

    async def test_get_performance(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/analytics/performance").mock(return_value=httpx.Response(200, json=_PERFORMANCE_BODY))
            client = await self._make()
            result = await client.get_performance()
            assert isinstance(result, Performance)
            await client.aclose()

    async def test_get_portfolio_history(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/analytics/portfolio/history").mock(return_value=httpx.Response(200, json=_HISTORY_BODY))
            client = await self._make()
            result = await client.get_portfolio_history()
            assert isinstance(result, list)
            assert isinstance(result[0], Snapshot)
            await client.aclose()

    async def test_get_leaderboard(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/analytics/leaderboard").mock(return_value=httpx.Response(200, json=_LEADERBOARD_BODY))
            client = await self._make()
            result = await client.get_leaderboard()
            assert isinstance(result, list)
            assert isinstance(result[0], LeaderboardEntry)
            await client.aclose()

    # ── Context manager ───────────────────────────────────────────────────────

    async def test_async_context_manager(self) -> None:
        with respx.mock(base_url=_BASE) as mock:
            mock.post("/api/v1/auth/login").mock(return_value=httpx.Response(200, json=_LOGIN_BODY))
            mock.get("/api/v1/market/price/BTCUSDT").mock(return_value=httpx.Response(200, json=_PRICE_BODY))
            async with AsyncAgentExchangeClient(api_key=_API_KEY, api_secret=_API_SECRET, base_url=_BASE) as client:
                price = await client.get_price("BTCUSDT")
                assert isinstance(price, Price)
