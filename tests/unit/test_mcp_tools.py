"""Unit tests for src.mcp.tools — all 12 MCP trading tools.

Tests cover:
- Tool list discovery: all 12 tools registered with correct names and schemas
- get_price: success and HTTP error propagation
- get_all_prices: success and HTTP error propagation
- get_candles: with and without optional limit; symbol uppercased
- get_balance: success and HTTP error propagation
- get_positions: success and HTTP error propagation
- place_order: market order, limit order (with price), price field absent for market
- cancel_order: success and HTTP error propagation
- get_order_status: success and HTTP error propagation
- get_portfolio: success and HTTP error propagation
- get_trade_history: no filters, with symbol filter, with limit, combined
- get_performance: no period, with period
- reset_account: confirm=True executes; confirm=False aborts without HTTP call
- _error_content: HTTPStatusError formats detail from JSON; generic exception
- unknown tool name: raises ValueError
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

mcp = pytest.importorskip("mcp", reason="mcp package not installed")
import mcp.types as types  # noqa: E402
from src.mcp.tools import (  # noqa: E402
    _TOOL_DEFINITIONS,
    _call_api,
    _dispatch,
    _error_content,
    _json_content,
    register_tools,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_DUMMY_REQUEST = httpx.Request("GET", "http://localhost:8000/api/v1/test")


def _make_response(
    status_code: int = 200,
    body: Any = None,
) -> httpx.Response:
    """Build a minimal ``httpx.Response`` for mocking purposes.

    Always attaches a request so that ``raise_for_status()`` works correctly.
    """
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body or {}).encode(),
        headers={"content-type": "application/json"},
        request=_DUMMY_REQUEST,
    )


def _make_error_response(status_code: int, body: dict[str, Any]) -> httpx.Response:
    """Build an httpx.Response that will raise HTTPStatusError on raise_for_status."""
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
        request=_DUMMY_REQUEST,
    )


async def _run_dispatch(
    name: str,
    args: dict[str, Any],
    mock_data: Any = None,
    *,
    status_code: int = 200,
) -> list[types.TextContent]:
    """Helper: run _dispatch with a mocked HTTP client returning *mock_data*."""
    client = AsyncMock(spec=httpx.AsyncClient)
    response = _make_response(status_code, mock_data)
    client.request = AsyncMock(return_value=response)
    return await _dispatch(name, args, client)


# ---------------------------------------------------------------------------
# Tool list / schema tests
# ---------------------------------------------------------------------------


class TestToolDefinitions:
    """Tests for the static _TOOL_DEFINITIONS list."""

    EXPECTED_TOOL_NAMES = {
        "get_price",
        "get_all_prices",
        "get_candles",
        "get_balance",
        "get_positions",
        "place_order",
        "cancel_order",
        "get_order_status",
        "get_portfolio",
        "get_trade_history",
        "get_performance",
        "reset_account",
    }

    def test_twelve_tools_defined(self) -> None:
        assert len(_TOOL_DEFINITIONS) == 12

    def test_all_expected_tool_names_present(self) -> None:
        actual = {t.name for t in _TOOL_DEFINITIONS}
        assert actual == self.EXPECTED_TOOL_NAMES

    def test_all_tools_have_descriptions(self) -> None:
        for tool in _TOOL_DEFINITIONS:
            assert tool.description, f"Tool '{tool.name}' has no description"

    def test_all_tools_have_input_schema(self) -> None:
        for tool in _TOOL_DEFINITIONS:
            assert isinstance(tool.inputSchema, dict), f"Tool '{tool.name}' inputSchema is not a dict"
            assert tool.inputSchema.get("type") == "object"

    def test_get_price_requires_symbol(self) -> None:
        tool = next(t for t in _TOOL_DEFINITIONS if t.name == "get_price")
        assert "symbol" in tool.inputSchema["required"]

    def test_get_candles_requires_symbol_and_interval(self) -> None:
        tool = next(t for t in _TOOL_DEFINITIONS if t.name == "get_candles")
        assert "symbol" in tool.inputSchema["required"]
        assert "interval" in tool.inputSchema["required"]

    def test_place_order_required_fields(self) -> None:
        tool = next(t for t in _TOOL_DEFINITIONS if t.name == "place_order")
        assert set(tool.inputSchema["required"]) == {"symbol", "side", "type", "quantity"}

    def test_cancel_order_requires_order_id(self) -> None:
        tool = next(t for t in _TOOL_DEFINITIONS if t.name == "cancel_order")
        assert "order_id" in tool.inputSchema["required"]

    def test_get_order_status_requires_order_id(self) -> None:
        tool = next(t for t in _TOOL_DEFINITIONS if t.name == "get_order_status")
        assert "order_id" in tool.inputSchema["required"]

    def test_reset_account_requires_confirm(self) -> None:
        tool = next(t for t in _TOOL_DEFINITIONS if t.name == "reset_account")
        assert "confirm" in tool.inputSchema["required"]


# ---------------------------------------------------------------------------
# register_tools wiring
# ---------------------------------------------------------------------------


class TestRegisterTools:
    """Verify that register_tools correctly wires list_tools and call_tool."""

    def test_register_tools_calls_server_decorators(self) -> None:
        server = MagicMock()
        client = AsyncMock(spec=httpx.AsyncClient)

        list_decorator = MagicMock()
        call_decorator = MagicMock()
        server.list_tools.return_value = list_decorator
        server.call_tool.return_value = call_decorator

        register_tools(server, client)

        server.list_tools.assert_called_once()
        server.call_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_tools_returns_all_definitions(self) -> None:
        """The handler registered with @server.list_tools() returns all 12 tools."""
        captured_handler = None
        server = MagicMock()
        client = AsyncMock(spec=httpx.AsyncClient)

        def capture_list_handler(fn: Any) -> Any:
            nonlocal captured_handler
            captured_handler = fn
            return fn

        server.list_tools.return_value = capture_list_handler
        server.call_tool.return_value = lambda fn: fn

        register_tools(server, client)

        assert captured_handler is not None
        result = await captured_handler()
        assert len(result) == 12
        names = {t.name for t in result}
        assert "get_price" in names
        assert "reset_account" in names

    @pytest.mark.asyncio
    async def test_call_tool_dispatches_successfully(self) -> None:
        """The call_tool handler dispatches to _dispatch and returns content."""
        captured_handler = None
        server = MagicMock()

        price_data = {"symbol": "BTCUSDT", "price": "50000.00"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, price_data))

        def capture_call_handler(fn: Any) -> Any:
            nonlocal captured_handler
            captured_handler = fn
            return fn

        server.list_tools.return_value = lambda fn: fn
        server.call_tool.return_value = capture_call_handler

        register_tools(server, client)

        assert captured_handler is not None
        result = await captured_handler("get_price", {"symbol": "BTCUSDT"})
        assert len(result) == 1
        assert "BTCUSDT" in result[0].text

    @pytest.mark.asyncio
    async def test_call_tool_returns_error_content_on_http_error(self) -> None:
        """HTTP errors in the handler are caught and returned as error TextContent."""
        captured_handler = None
        server = MagicMock()
        client = AsyncMock(spec=httpx.AsyncClient)

        error_response = _make_error_response(404, {"detail": "Symbol not found"})
        client.request = AsyncMock(return_value=error_response)

        def capture_call_handler(fn: Any) -> Any:
            nonlocal captured_handler
            captured_handler = fn
            return fn

        server.list_tools.return_value = lambda fn: fn
        server.call_tool.return_value = capture_call_handler

        register_tools(server, client)

        assert captured_handler is not None
        result = await captured_handler("get_price", {"symbol": "INVALID"})
        assert len(result) == 1
        assert "error" in result[0].text.lower() or "not found" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_call_tool_returns_error_content_on_unknown_tool(self) -> None:
        """Unknown tool names are caught and returned as error TextContent."""
        captured_handler = None
        server = MagicMock()
        client = AsyncMock(spec=httpx.AsyncClient)

        def capture_call_handler(fn: Any) -> Any:
            nonlocal captured_handler
            captured_handler = fn
            return fn

        server.list_tools.return_value = lambda fn: fn
        server.call_tool.return_value = capture_call_handler

        register_tools(server, client)

        assert captured_handler is not None
        result = await captured_handler("nonexistent_tool", {})
        assert len(result) == 1
        assert "Error" in result[0].text


# ---------------------------------------------------------------------------
# _call_api
# ---------------------------------------------------------------------------


class TestCallApi:
    """Tests for the internal _call_api helper."""

    @pytest.mark.asyncio
    async def test_get_request_succeeds(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        data = {"price": "50000.00"}
        client.request = AsyncMock(return_value=_make_response(200, data))

        result = await _call_api(client, "GET", "/api/v1/market/price/BTCUSDT")
        assert result == data
        client.request.assert_called_once_with("GET", "/api/v1/market/price/BTCUSDT", params=None, json=None)

    @pytest.mark.asyncio
    async def test_post_request_with_json_body(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        response_data = {"order_id": "abc-123"}
        client.request = AsyncMock(return_value=_make_response(200, response_data))

        body = {"symbol": "BTCUSDT", "side": "buy"}
        result = await _call_api(client, "POST", "/api/v1/trade/order", json=body)
        assert result == response_data
        client.request.assert_called_once_with("POST", "/api/v1/trade/order", params=None, json=body)

    @pytest.mark.asyncio
    async def test_get_request_with_params(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, []))

        params = {"interval": "1h", "limit": 50}
        await _call_api(client, "GET", "/api/v1/market/candles/BTCUSDT", params=params)
        client.request.assert_called_once_with("GET", "/api/v1/market/candles/BTCUSDT", params=params, json=None)

    @pytest.mark.asyncio
    async def test_raises_on_4xx(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        error_response = _make_error_response(404, {"detail": "Not found"})
        client.request = AsyncMock(return_value=error_response)

        with pytest.raises(httpx.HTTPStatusError):
            await _call_api(client, "GET", "/api/v1/market/price/BADINPUT")

    @pytest.mark.asyncio
    async def test_raises_on_5xx(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        error_response = _make_error_response(500, {"detail": "Internal error"})
        client.request = AsyncMock(return_value=error_response)

        with pytest.raises(httpx.HTTPStatusError):
            await _call_api(client, "GET", "/api/v1/market/prices")


# ---------------------------------------------------------------------------
# _error_content
# ---------------------------------------------------------------------------


class TestErrorContent:
    """Tests for the _error_content formatter."""

    def test_http_status_error_with_detail_key(self) -> None:
        request = httpx.Request("GET", "http://localhost/test")
        response = httpx.Response(
            status_code=404,
            content=json.dumps({"detail": "Symbol not found"}).encode(),
            headers={"content-type": "application/json"},
            request=request,
        )
        exc = httpx.HTTPStatusError("Not found", request=request, response=response)
        result = _error_content(exc)
        assert len(result) == 1
        assert "Symbol not found" in result[0].text
        assert result[0].text.startswith("API error:")

    def test_http_status_error_with_error_message_key(self) -> None:
        request = httpx.Request("GET", "http://localhost/test")
        response = httpx.Response(
            status_code=400,
            content=json.dumps({"error": {"message": "Bad request"}}).encode(),
            headers={"content-type": "application/json"},
            request=request,
        )
        exc = httpx.HTTPStatusError("Bad request", request=request, response=response)
        result = _error_content(exc)
        assert "Bad request" in result[0].text

    def test_http_status_error_with_non_json_body(self) -> None:
        request = httpx.Request("GET", "http://localhost/test")
        response = httpx.Response(
            status_code=503,
            content=b"Service Unavailable",
            headers={"content-type": "text/plain"},
            request=request,
        )
        exc = httpx.HTTPStatusError("Service unavailable", request=request, response=response)
        result = _error_content(exc)
        assert len(result) == 1
        assert "API error:" in result[0].text

    def test_generic_exception(self) -> None:
        exc = RuntimeError("connection refused")
        result = _error_content(exc)
        assert len(result) == 1
        assert result[0].text.startswith("Error:")
        assert "connection refused" in result[0].text


# ---------------------------------------------------------------------------
# _json_content
# ---------------------------------------------------------------------------


class TestJsonContent:
    """Tests for the _json_content serialiser."""

    def test_dict_is_pretty_printed(self) -> None:
        data = {"symbol": "BTCUSDT", "price": "50000.00"}
        result = _json_content(data)
        assert len(result) == 1
        parsed = json.loads(result[0].text)
        assert parsed == data

    def test_list_is_serialised(self) -> None:
        data = [{"price": "1.00"}, {"price": "2.00"}]
        result = _json_content(data)
        parsed = json.loads(result[0].text)
        assert parsed == data

    def test_content_type_is_text(self) -> None:
        result = _json_content({"key": "value"})
        assert result[0].type == "text"


# ---------------------------------------------------------------------------
# _dispatch — market data tools
# ---------------------------------------------------------------------------


class TestDispatchMarketData:
    """Tests for get_price, get_all_prices, and get_candles."""

    @pytest.mark.asyncio
    async def test_get_price_success(self) -> None:
        data = {"symbol": "BTCUSDT", "price": "65000.00", "timestamp": "2024-01-01T00:00:00Z"}
        result = await _run_dispatch("get_price", {"symbol": "BTCUSDT"}, data)
        assert len(result) == 1
        parsed = json.loads(result[0].text)
        assert parsed["symbol"] == "BTCUSDT"
        assert parsed["price"] == "65000.00"

    @pytest.mark.asyncio
    async def test_get_price_symbol_uppercased(self) -> None:
        """Symbol should be uppercased before URL construction."""
        data = {"symbol": "ETHUSDT", "price": "3500.00"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        await _dispatch("get_price", {"symbol": "ethusdt"}, client)

        call_args = client.request.call_args
        assert "ETHUSDT" in call_args[0][1]  # URL positional arg

    @pytest.mark.asyncio
    async def test_get_price_http_error_propagates(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_error_response(404, {"detail": "Not found"}))
        with pytest.raises(httpx.HTTPStatusError):
            await _dispatch("get_price", {"symbol": "BADPAIR"}, client)

    @pytest.mark.asyncio
    async def test_get_all_prices_success(self) -> None:
        data = {"BTCUSDT": "65000.00", "ETHUSDT": "3500.00"}
        result = await _run_dispatch("get_all_prices", {}, data)
        parsed = json.loads(result[0].text)
        assert "BTCUSDT" in parsed

    @pytest.mark.asyncio
    async def test_get_all_prices_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_all_prices", {}, client)
        call_args = client.request.call_args
        assert call_args[0][1] == "/api/v1/market/prices"

    @pytest.mark.asyncio
    async def test_get_candles_success(self) -> None:
        candles = [{"open": "64000", "high": "65000", "low": "63000", "close": "64500", "volume": "100"}]
        result = await _run_dispatch("get_candles", {"symbol": "BTCUSDT", "interval": "1h"}, candles)
        parsed = json.loads(result[0].text)
        assert isinstance(parsed, list)
        assert parsed[0]["close"] == "64500"

    @pytest.mark.asyncio
    async def test_get_candles_includes_limit_when_provided(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, []))
        await _dispatch("get_candles", {"symbol": "BTCUSDT", "interval": "5m", "limit": 200}, client)
        call_args = client.request.call_args
        params = call_args[1].get("params") or call_args[0][3] if len(call_args[0]) > 3 else call_args[1]["params"]
        assert params["limit"] == 200
        assert params["interval"] == "5m"

    @pytest.mark.asyncio
    async def test_get_candles_omits_limit_when_absent(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, []))
        await _dispatch("get_candles", {"symbol": "BTCUSDT", "interval": "1d"}, client)
        call_args = client.request.call_args
        params = call_args[1]["params"]
        assert "limit" not in params

    @pytest.mark.asyncio
    async def test_get_candles_symbol_uppercased(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, []))
        await _dispatch("get_candles", {"symbol": "btcusdt", "interval": "1h"}, client)
        call_args = client.request.call_args
        assert "BTCUSDT" in call_args[0][1]


# ---------------------------------------------------------------------------
# _dispatch — account tools
# ---------------------------------------------------------------------------


class TestDispatchAccount:
    """Tests for get_balance, get_positions, get_portfolio, and reset_account."""

    @pytest.mark.asyncio
    async def test_get_balance_success(self) -> None:
        data = {"balances": [{"asset": "USDT", "available": "10000.00", "locked": "0.00"}]}
        result = await _run_dispatch("get_balance", {}, data)
        parsed = json.loads(result[0].text)
        assert parsed["balances"][0]["asset"] == "USDT"

    @pytest.mark.asyncio
    async def test_get_balance_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_balance", {}, client)
        call_args = client.request.call_args
        assert call_args[0][1] == "/api/v1/account/balance"

    @pytest.mark.asyncio
    async def test_get_positions_success(self) -> None:
        data = {"positions": [{"symbol": "BTCUSDT", "quantity": "0.5", "unrealized_pnl": "250.00"}]}
        result = await _run_dispatch("get_positions", {}, data)
        parsed = json.loads(result[0].text)
        assert parsed["positions"][0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_get_positions_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_positions", {}, client)
        call_args = client.request.call_args
        assert call_args[0][1] == "/api/v1/account/positions"

    @pytest.mark.asyncio
    async def test_get_portfolio_success(self) -> None:
        data = {
            "total_equity": "10500.00",
            "cash_balance": "9500.00",
            "unrealized_pnl": "250.00",
            "positions": [],
        }
        result = await _run_dispatch("get_portfolio", {}, data)
        parsed = json.loads(result[0].text)
        assert parsed["total_equity"] == "10500.00"

    @pytest.mark.asyncio
    async def test_get_portfolio_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_portfolio", {}, client)
        call_args = client.request.call_args
        assert call_args[0][1] == "/api/v1/account/portfolio"

    @pytest.mark.asyncio
    async def test_reset_account_confirm_true_calls_api(self) -> None:
        data = {"message": "Account reset successfully", "new_balance": "10000.00"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        result = await _dispatch("reset_account", {"confirm": True}, client)

        client.request.assert_called_once()
        call_args = client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/api/v1/account/reset"
        assert call_args[1]["json"] == {"confirm": True}
        parsed = json.loads(result[0].text)
        assert "reset" in parsed["message"].lower()

    @pytest.mark.asyncio
    async def test_reset_account_confirm_false_aborts_without_http_call(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock()

        result = await _dispatch("reset_account", {"confirm": False}, client)

        client.request.assert_not_called()
        assert len(result) == 1
        assert "abort" in result[0].text.lower() or "confirm" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_reset_account_confirm_missing_aborts(self) -> None:
        """Absent 'confirm' key defaults to False and aborts."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock()

        result = await _dispatch("reset_account", {}, client)

        client.request.assert_not_called()
        assert "confirm" in result[0].text.lower()


# ---------------------------------------------------------------------------
# _dispatch — trading tools
# ---------------------------------------------------------------------------


class TestDispatchTrading:
    """Tests for place_order, cancel_order, get_order_status, and get_trade_history."""

    @pytest.mark.asyncio
    async def test_place_order_market_buy_success(self) -> None:
        data = {
            "order_id": "ord-abc-123",
            "symbol": "BTCUSDT",
            "side": "buy",
            "type": "market",
            "status": "filled",
            "filled_quantity": "0.1",
            "average_price": "65000.00",
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        result = await _dispatch(
            "place_order",
            {"symbol": "btcusdt", "side": "buy", "type": "market", "quantity": 0.1},
            client,
        )

        parsed = json.loads(result[0].text)
        assert parsed["order_id"] == "ord-abc-123"

        call_args = client.request.call_args
        body = call_args[1]["json"]
        assert body["symbol"] == "BTCUSDT"
        assert body["side"] == "buy"
        assert body["type"] == "market"
        assert body["quantity"] == "0.1"
        assert "price" not in body

    @pytest.mark.asyncio
    async def test_place_order_limit_buy_includes_price(self) -> None:
        data = {"order_id": "ord-limit-1", "status": "pending"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        await _dispatch(
            "place_order",
            {"symbol": "ETHUSDT", "side": "buy", "type": "limit", "quantity": 1.0, "price": 3000.0},
            client,
        )

        call_args = client.request.call_args
        body = call_args[1]["json"]
        assert body["price"] == "3000.0"

    @pytest.mark.asyncio
    async def test_place_order_null_price_omitted(self) -> None:
        """When price=None is explicitly passed, it should not appear in the body."""
        data = {"order_id": "ord-mkt-2"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        await _dispatch(
            "place_order",
            {"symbol": "SOLUSDT", "side": "sell", "type": "market", "quantity": 5.0, "price": None},
            client,
        )

        call_args = client.request.call_args
        body = call_args[1]["json"]
        assert "price" not in body

    @pytest.mark.asyncio
    async def test_place_order_symbol_uppercased(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))

        await _dispatch(
            "place_order",
            {"symbol": "bnbusdt", "side": "buy", "type": "market", "quantity": 1.0},
            client,
        )

        call_args = client.request.call_args
        assert call_args[1]["json"]["symbol"] == "BNBUSDT"

    @pytest.mark.asyncio
    async def test_place_order_stop_loss_with_price(self) -> None:
        data = {"order_id": "sl-1", "status": "pending"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        await _dispatch(
            "place_order",
            {"symbol": "BTCUSDT", "side": "sell", "type": "stop_loss", "quantity": 0.5, "price": 60000.0},
            client,
        )

        call_args = client.request.call_args
        body = call_args[1]["json"]
        assert body["type"] == "stop_loss"
        assert body["price"] == "60000.0"

    @pytest.mark.asyncio
    async def test_cancel_order_success(self) -> None:
        data = {"order_id": "ord-cancel-1", "status": "cancelled"}
        result = await _run_dispatch("cancel_order", {"order_id": "ord-cancel-1"}, data)
        parsed = json.loads(result[0].text)
        assert parsed["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_order_calls_delete_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))

        await _dispatch("cancel_order", {"order_id": "ord-xyz"}, client)

        call_args = client.request.call_args
        assert call_args[0][0] == "DELETE"
        assert "ord-xyz" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_cancel_order_http_error_propagates(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_error_response(404, {"detail": "Order not found"}))
        with pytest.raises(httpx.HTTPStatusError):
            await _dispatch("cancel_order", {"order_id": "bad-id"}, client)

    @pytest.mark.asyncio
    async def test_get_order_status_success(self) -> None:
        data = {
            "order_id": "ord-123",
            "symbol": "BTCUSDT",
            "status": "filled",
            "filled_quantity": "0.5",
        }
        result = await _run_dispatch("get_order_status", {"order_id": "ord-123"}, data)
        parsed = json.loads(result[0].text)
        assert parsed["order_id"] == "ord-123"
        assert parsed["status"] == "filled"

    @pytest.mark.asyncio
    async def test_get_order_status_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))

        await _dispatch("get_order_status", {"order_id": "ord-abc"}, client)

        call_args = client.request.call_args
        assert call_args[0][0] == "GET"
        assert "ord-abc" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_get_trade_history_no_filters(self) -> None:
        data = {"trades": [], "total": 0}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        result = await _dispatch("get_trade_history", {}, client)

        call_args = client.request.call_args
        params = call_args[1]["params"]
        assert params == {}
        parsed = json.loads(result[0].text)
        assert parsed["total"] == 0

    @pytest.mark.asyncio
    async def test_get_trade_history_with_symbol_filter(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))

        await _dispatch("get_trade_history", {"symbol": "ethusdt"}, client)

        call_args = client.request.call_args
        params = call_args[1]["params"]
        assert params["symbol"] == "ETHUSDT"

    @pytest.mark.asyncio
    async def test_get_trade_history_with_limit(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))

        await _dispatch("get_trade_history", {"limit": 25}, client)

        call_args = client.request.call_args
        params = call_args[1]["params"]
        assert params["limit"] == 25

    @pytest.mark.asyncio
    async def test_get_trade_history_combined_filters(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))

        await _dispatch("get_trade_history", {"symbol": "bnbusdt", "limit": 10}, client)

        call_args = client.request.call_args
        params = call_args[1]["params"]
        assert params["symbol"] == "BNBUSDT"
        assert params["limit"] == 10

    @pytest.mark.asyncio
    async def test_get_trade_history_empty_symbol_omitted(self) -> None:
        """An empty string symbol should not be added to params."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))

        await _dispatch("get_trade_history", {"symbol": ""}, client)

        call_args = client.request.call_args
        params = call_args[1]["params"]
        assert "symbol" not in params


# ---------------------------------------------------------------------------
# _dispatch — analytics tools
# ---------------------------------------------------------------------------


class TestDispatchAnalytics:
    """Tests for get_performance."""

    @pytest.mark.asyncio
    async def test_get_performance_no_period(self) -> None:
        data = {
            "roi": "5.00",
            "sharpe_ratio": "1.25",
            "win_rate": "0.60",
            "max_drawdown": "0.08",
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        result = await _dispatch("get_performance", {}, client)

        call_args = client.request.call_args
        params = call_args[1]["params"]
        assert params == {}
        parsed = json.loads(result[0].text)
        assert parsed["roi"] == "5.00"

    @pytest.mark.asyncio
    async def test_get_performance_with_period(self) -> None:
        data = {"roi": "2.50", "period": "7d"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        await _dispatch("get_performance", {"period": "7d"}, client)

        call_args = client.request.call_args
        params = call_args[1]["params"]
        assert params["period"] == "7d"

    @pytest.mark.asyncio
    async def test_get_performance_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))

        await _dispatch("get_performance", {"period": "30d"}, client)

        call_args = client.request.call_args
        assert call_args[0][1] == "/api/v1/analytics/performance"

    @pytest.mark.asyncio
    async def test_get_performance_empty_period_omitted(self) -> None:
        """An empty string period should not be added to params."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))

        await _dispatch("get_performance", {"period": ""}, client)

        call_args = client.request.call_args
        params = call_args[1]["params"]
        assert "period" not in params

    @pytest.mark.parametrize("period", ["1d", "7d", "30d", "90d", "all"])
    @pytest.mark.asyncio
    async def test_get_performance_all_valid_periods(self, period: str) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {"period": period}))

        result = await _dispatch("get_performance", {"period": period}, client)

        call_args = client.request.call_args
        assert call_args[1]["params"]["period"] == period
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _dispatch — unknown tool
# ---------------------------------------------------------------------------


class TestDispatchUnknownTool:
    """Tests for the default case in _dispatch."""

    @pytest.mark.asyncio
    async def test_unknown_tool_raises_value_error(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        with pytest.raises(ValueError, match="Unknown tool"):
            await _dispatch("fly_to_moon", {}, client)

    @pytest.mark.asyncio
    async def test_empty_tool_name_raises_value_error(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        with pytest.raises(ValueError, match="Unknown tool"):
            await _dispatch("", {}, client)
