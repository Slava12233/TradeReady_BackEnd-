"""Unit tests for src.mcp.tools — all 43 MCP trading tools.

Tests cover:
- Tool list discovery: all 43 tools registered with correct names and schemas
- Market data tools (7): get_price, get_all_prices, get_candles, get_pairs,
  get_ticker, get_orderbook, get_recent_trades
- Account tools (5): get_balance, get_positions, get_portfolio, get_account_info,
  reset_account
- Trading tools (7): place_order, cancel_order, get_order_status, get_trade_history,
  get_open_orders, cancel_all_orders, list_orders
- Analytics tools (4): get_performance, get_pnl, get_portfolio_history, get_leaderboard
- Backtesting tools (8): get_data_range, create_backtest, start_backtest, step_backtest,
  step_backtest_batch, backtest_trade, get_backtest_results, list_backtests
- Agent management tools (6): list_agents, create_agent, get_agent, reset_agent,
  update_agent_risk, get_agent_skill
- Battle tools (6): create_battle, list_battles, start_battle, get_battle_live,
  get_battle_results, get_battle_replay
- Helper functions: _error_content, _json_content, _text_content, _call_api, _call_api_text
- Unknown tool name raises ValueError
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
    TOOL_COUNT,
    _call_api,
    _call_api_text,
    _dispatch,
    _error_content,
    _json_content,
    _text_content,
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
    """Build a minimal ``httpx.Response`` for mocking purposes."""
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body or {}).encode(),
        headers={"content-type": "application/json"},
        request=_DUMMY_REQUEST,
    )


def _make_text_response(
    status_code: int = 200,
    text: str = "",
) -> httpx.Response:
    """Build an httpx.Response with text content."""
    return httpx.Response(
        status_code=status_code,
        content=text.encode(),
        headers={"content-type": "text/plain"},
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


async def _run_dispatch_text(
    name: str,
    args: dict[str, Any],
    text: str = "",
) -> list[types.TextContent]:
    """Helper: run _dispatch with a mocked HTTP client returning text."""
    client = AsyncMock(spec=httpx.AsyncClient)
    text_response = _make_text_response(200, text)
    # For text endpoints, mock request to return text response
    client.request = AsyncMock(return_value=text_response)
    return await _dispatch(name, args, client)


# ---------------------------------------------------------------------------
# Tool list / schema tests
# ---------------------------------------------------------------------------


class TestToolDefinitions:
    """Tests for the static _TOOL_DEFINITIONS list."""

    EXPECTED_TOOL_NAMES = {
        # Market data (7)
        "get_price", "get_all_prices", "get_candles", "get_pairs",
        "get_ticker", "get_orderbook", "get_recent_trades",
        # Account (5)
        "get_balance", "get_positions", "get_portfolio", "get_account_info",
        "reset_account",
        # Trading (7)
        "place_order", "cancel_order", "get_order_status", "get_trade_history",
        "get_open_orders", "cancel_all_orders", "list_orders",
        # Analytics (4)
        "get_performance", "get_pnl", "get_portfolio_history", "get_leaderboard",
        # Backtesting (8)
        "get_data_range", "create_backtest", "start_backtest", "step_backtest",
        "step_backtest_batch", "backtest_trade", "get_backtest_results", "list_backtests",
        # Agent management (6)
        "list_agents", "create_agent", "get_agent", "reset_agent",
        "update_agent_risk", "get_agent_skill",
        # Battles (6)
        "create_battle", "list_battles", "start_battle", "get_battle_live",
        "get_battle_results", "get_battle_replay",
    }

    def test_tool_count_constant_matches(self) -> None:
        assert TOOL_COUNT == 43
        assert len(_TOOL_DEFINITIONS) == TOOL_COUNT

    def test_forty_three_tools_defined(self) -> None:
        assert len(_TOOL_DEFINITIONS) == 43

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

    def test_create_backtest_requires_time_range(self) -> None:
        tool = next(t for t in _TOOL_DEFINITIONS if t.name == "create_backtest")
        assert "start_time" in tool.inputSchema["required"]
        assert "end_time" in tool.inputSchema["required"]

    def test_step_backtest_requires_session_id(self) -> None:
        tool = next(t for t in _TOOL_DEFINITIONS if t.name == "step_backtest")
        assert "session_id" in tool.inputSchema["required"]

    def test_step_backtest_batch_requires_session_and_steps(self) -> None:
        tool = next(t for t in _TOOL_DEFINITIONS if t.name == "step_backtest_batch")
        assert "session_id" in tool.inputSchema["required"]
        assert "steps" in tool.inputSchema["required"]

    def test_backtest_trade_required_fields(self) -> None:
        tool = next(t for t in _TOOL_DEFINITIONS if t.name == "backtest_trade")
        required = set(tool.inputSchema["required"])
        assert {"session_id", "symbol", "side", "quantity"} == required

    def test_create_agent_requires_display_name(self) -> None:
        tool = next(t for t in _TOOL_DEFINITIONS if t.name == "create_agent")
        assert "display_name" in tool.inputSchema["required"]

    def test_create_battle_requires_name(self) -> None:
        tool = next(t for t in _TOOL_DEFINITIONS if t.name == "create_battle")
        assert "name" in tool.inputSchema["required"]

    def test_start_battle_requires_battle_id(self) -> None:
        tool = next(t for t in _TOOL_DEFINITIONS if t.name == "start_battle")
        assert "battle_id" in tool.inputSchema["required"]


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
        assert len(result) == 43
        names = {t.name for t in result}
        assert "get_price" in names
        assert "create_backtest" in names
        assert "create_battle" in names

    @pytest.mark.asyncio
    async def test_call_tool_dispatches_successfully(self) -> None:
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


class TestCallApiText:
    """Tests for the _call_api_text helper."""

    @pytest.mark.asyncio
    async def test_returns_text_content(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_text_response(200, "# Skill File\nContent here"))

        result = await _call_api_text(client, "GET", "/api/v1/agents/123/skill.md")
        assert result == "# Skill File\nContent here"

    @pytest.mark.asyncio
    async def test_raises_on_error(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_error_response(404, {"detail": "Not found"}))

        with pytest.raises(httpx.HTTPStatusError):
            await _call_api_text(client, "GET", "/api/v1/agents/bad-id/skill.md")


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
# _json_content and _text_content
# ---------------------------------------------------------------------------


class TestContentHelpers:
    """Tests for _json_content and _text_content."""

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

    def test_text_content_returns_plain_text(self) -> None:
        result = _text_content("Hello, world!")
        assert len(result) == 1
        assert result[0].text == "Hello, world!"
        assert result[0].type == "text"


# ---------------------------------------------------------------------------
# _dispatch — market data tools
# ---------------------------------------------------------------------------


class TestDispatchMarketData:
    """Tests for market data tools (7 tools)."""

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
        data = {"symbol": "ETHUSDT", "price": "3500.00"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        await _dispatch("get_price", {"symbol": "ethusdt"}, client)

        call_args = client.request.call_args
        assert "ETHUSDT" in call_args[0][1]

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

    # --- get_pairs ---

    @pytest.mark.asyncio
    async def test_get_pairs_no_filters(self) -> None:
        data = {"pairs": [{"symbol": "BTCUSDT", "status": "active"}]}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))
        await _dispatch("get_pairs", {}, client)
        call_args = client.request.call_args
        assert call_args[0][1] == "/api/v1/market/pairs"
        assert call_args[1]["params"] == {}

    @pytest.mark.asyncio
    async def test_get_pairs_with_exchange_filter(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_pairs", {"exchange": "binance"}, client)
        params = client.request.call_args[1]["params"]
        assert params["exchange"] == "binance"

    # --- get_ticker ---

    @pytest.mark.asyncio
    async def test_get_ticker_success(self) -> None:
        data = {"symbol": "BTCUSDT", "open": "64000", "high": "66000", "low": "63000", "close": "65000"}
        result = await _run_dispatch("get_ticker", {"symbol": "BTCUSDT"}, data)
        parsed = json.loads(result[0].text)
        assert parsed["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_get_ticker_symbol_uppercased(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_ticker", {"symbol": "ethusdt"}, client)
        assert "ETHUSDT" in client.request.call_args[0][1]

    # --- get_orderbook ---

    @pytest.mark.asyncio
    async def test_get_orderbook_success(self) -> None:
        data = {"bids": [["64999", "1.5"]], "asks": [["65001", "2.0"]]}
        result = await _run_dispatch("get_orderbook", {"symbol": "BTCUSDT"}, data)
        parsed = json.loads(result[0].text)
        assert "bids" in parsed

    @pytest.mark.asyncio
    async def test_get_orderbook_with_limit(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_orderbook", {"symbol": "BTCUSDT", "limit": 50}, client)
        params = client.request.call_args[1]["params"]
        assert params["limit"] == 50

    @pytest.mark.asyncio
    async def test_get_orderbook_symbol_uppercased(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_orderbook", {"symbol": "ethusdt"}, client)
        assert "ETHUSDT" in client.request.call_args[0][1]

    # --- get_recent_trades ---

    @pytest.mark.asyncio
    async def test_get_recent_trades_success(self) -> None:
        data = {"trades": [{"price": "65000", "quantity": "0.1"}]}
        result = await _run_dispatch("get_recent_trades", {"symbol": "BTCUSDT"}, data)
        parsed = json.loads(result[0].text)
        assert "trades" in parsed

    @pytest.mark.asyncio
    async def test_get_recent_trades_with_limit(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_recent_trades", {"symbol": "BTCUSDT", "limit": 100}, client)
        params = client.request.call_args[1]["params"]
        assert params["limit"] == 100


# ---------------------------------------------------------------------------
# _dispatch — account tools
# ---------------------------------------------------------------------------


class TestDispatchAccount:
    """Tests for account tools (5 tools)."""

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
        assert client.request.call_args[0][1] == "/api/v1/account/balance"

    @pytest.mark.asyncio
    async def test_get_positions_success(self) -> None:
        data = {"positions": [{"symbol": "BTCUSDT", "quantity": "0.5", "unrealized_pnl": "250.00"}]}
        result = await _run_dispatch("get_positions", {}, data)
        parsed = json.loads(result[0].text)
        assert parsed["positions"][0]["symbol"] == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_get_portfolio_success(self) -> None:
        data = {"total_equity": "10500.00", "cash_balance": "9500.00", "positions": []}
        result = await _run_dispatch("get_portfolio", {}, data)
        parsed = json.loads(result[0].text)
        assert parsed["total_equity"] == "10500.00"

    @pytest.mark.asyncio
    async def test_get_account_info_success(self) -> None:
        data = {"account_id": "abc-123", "status": "active", "email": "test@test.com"}
        result = await _run_dispatch("get_account_info", {}, data)
        parsed = json.loads(result[0].text)
        assert parsed["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_account_info_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_account_info", {}, client)
        assert client.request.call_args[0][1] == "/api/v1/account/info"

    @pytest.mark.asyncio
    async def test_reset_account_confirm_true_calls_api(self) -> None:
        data = {"message": "Account reset successfully", "new_balance": "10000.00"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        await _dispatch("reset_account", {"confirm": True}, client)

        client.request.assert_called_once()
        call_args = client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/api/v1/account/reset"
        assert call_args[1]["json"] == {"confirm": True}

    @pytest.mark.asyncio
    async def test_reset_account_confirm_false_aborts_without_http_call(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock()
        result = await _dispatch("reset_account", {"confirm": False}, client)
        client.request.assert_not_called()
        assert "abort" in result[0].text.lower() or "confirm" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_reset_account_confirm_missing_aborts(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock()
        result = await _dispatch("reset_account", {}, client)
        client.request.assert_not_called()
        assert "confirm" in result[0].text.lower()


# ---------------------------------------------------------------------------
# _dispatch — trading tools
# ---------------------------------------------------------------------------


class TestDispatchTrading:
    """Tests for trading tools (7 tools)."""

    @pytest.mark.asyncio
    async def test_place_order_market_buy_success(self) -> None:
        data = {"order_id": "ord-abc-123", "status": "filled"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        result = await _dispatch(
            "place_order",
            {"symbol": "btcusdt", "side": "buy", "type": "market", "quantity": 0.1},
            client,
        )
        parsed = json.loads(result[0].text)
        assert parsed["order_id"] == "ord-abc-123"
        body = client.request.call_args[1]["json"]
        assert body["symbol"] == "BTCUSDT"
        assert body["quantity"] == "0.1"
        assert "price" not in body

    @pytest.mark.asyncio
    async def test_place_order_limit_includes_price(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch(
            "place_order",
            {"symbol": "ETHUSDT", "side": "buy", "type": "limit", "quantity": 1.0, "price": 3000.0},
            client,
        )
        body = client.request.call_args[1]["json"]
        assert body["price"] == "3000.0"

    @pytest.mark.asyncio
    async def test_cancel_order_success(self) -> None:
        data = {"order_id": "ord-cancel-1", "status": "cancelled"}
        result = await _run_dispatch("cancel_order", {"order_id": "ord-cancel-1"}, data)
        parsed = json.loads(result[0].text)
        assert parsed["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_order_calls_delete(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("cancel_order", {"order_id": "ord-xyz"}, client)
        call_args = client.request.call_args
        assert call_args[0][0] == "DELETE"
        assert "ord-xyz" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_get_order_status_success(self) -> None:
        data = {"order_id": "ord-123", "status": "filled"}
        result = await _run_dispatch("get_order_status", {"order_id": "ord-123"}, data)
        parsed = json.loads(result[0].text)
        assert parsed["status"] == "filled"

    @pytest.mark.asyncio
    async def test_get_trade_history_no_filters(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {"trades": [], "total": 0}))
        await _dispatch("get_trade_history", {}, client)
        params = client.request.call_args[1]["params"]
        assert params == {}

    @pytest.mark.asyncio
    async def test_get_trade_history_with_symbol_filter(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_trade_history", {"symbol": "ethusdt"}, client)
        params = client.request.call_args[1]["params"]
        assert params["symbol"] == "ETHUSDT"

    @pytest.mark.asyncio
    async def test_get_trade_history_empty_symbol_omitted(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_trade_history", {"symbol": ""}, client)
        params = client.request.call_args[1]["params"]
        assert "symbol" not in params

    # --- get_open_orders ---

    @pytest.mark.asyncio
    async def test_get_open_orders_success(self) -> None:
        data = {"orders": [{"order_id": "o1", "status": "pending"}]}
        result = await _run_dispatch("get_open_orders", {}, data)
        parsed = json.loads(result[0].text)
        assert parsed["orders"][0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_get_open_orders_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_open_orders", {}, client)
        assert client.request.call_args[0][1] == "/api/v1/trade/orders/open"

    # --- cancel_all_orders ---

    @pytest.mark.asyncio
    async def test_cancel_all_orders_confirm_true(self) -> None:
        data = {"cancelled": 5}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))
        await _dispatch("cancel_all_orders", {"confirm": True}, client)
        call_args = client.request.call_args
        assert call_args[0][0] == "DELETE"
        assert call_args[0][1] == "/api/v1/trade/orders/open"

    @pytest.mark.asyncio
    async def test_cancel_all_orders_confirm_false_aborts(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        result = await _dispatch("cancel_all_orders", {"confirm": False}, client)
        client.request.assert_not_called()
        assert "abort" in result[0].text.lower() or "confirm" in result[0].text.lower()

    # --- list_orders ---

    @pytest.mark.asyncio
    async def test_list_orders_no_filters(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {"orders": []}))
        await _dispatch("list_orders", {}, client)
        assert client.request.call_args[0][1] == "/api/v1/trade/orders"
        assert client.request.call_args[1]["params"] == {}

    @pytest.mark.asyncio
    async def test_list_orders_with_filters(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("list_orders", {"status": "filled", "symbol": "btcusdt", "limit": 10}, client)
        params = client.request.call_args[1]["params"]
        assert params["status"] == "filled"
        assert params["symbol"] == "BTCUSDT"
        assert params["limit"] == 10


# ---------------------------------------------------------------------------
# _dispatch — analytics tools
# ---------------------------------------------------------------------------


class TestDispatchAnalytics:
    """Tests for analytics tools (4 tools)."""

    @pytest.mark.asyncio
    async def test_get_performance_no_period(self) -> None:
        data = {"roi": "5.00", "sharpe_ratio": "1.25"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))
        await _dispatch("get_performance", {}, client)
        params = client.request.call_args[1]["params"]
        assert params == {}

    @pytest.mark.asyncio
    async def test_get_performance_with_period(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_performance", {"period": "7d"}, client)
        params = client.request.call_args[1]["params"]
        assert params["period"] == "7d"

    @pytest.mark.asyncio
    async def test_get_performance_empty_period_omitted(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_performance", {"period": ""}, client)
        params = client.request.call_args[1]["params"]
        assert "period" not in params

    @pytest.mark.parametrize("period", ["1d", "7d", "30d", "90d", "all"])
    @pytest.mark.asyncio
    async def test_get_performance_all_valid_periods(self, period: str) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {"period": period}))
        result = await _dispatch("get_performance", {"period": period}, client)
        assert client.request.call_args[1]["params"]["period"] == period
        assert len(result) == 1

    # --- get_pnl ---

    @pytest.mark.asyncio
    async def test_get_pnl_success(self) -> None:
        data = {"realized_pnl": "500.00", "unrealized_pnl": "100.00"}
        result = await _run_dispatch("get_pnl", {}, data)
        parsed = json.loads(result[0].text)
        assert parsed["realized_pnl"] == "500.00"

    @pytest.mark.asyncio
    async def test_get_pnl_with_period(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_pnl", {"period": "7d"}, client)
        params = client.request.call_args[1]["params"]
        assert params["period"] == "7d"

    @pytest.mark.asyncio
    async def test_get_pnl_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_pnl", {}, client)
        assert client.request.call_args[0][1] == "/api/v1/account/pnl"

    # --- get_portfolio_history ---

    @pytest.mark.asyncio
    async def test_get_portfolio_history_success(self) -> None:
        data = {"snapshots": [{"timestamp": "2025-01-01T00:00:00Z", "equity": "10500"}]}
        result = await _run_dispatch("get_portfolio_history", {}, data)
        parsed = json.loads(result[0].text)
        assert "snapshots" in parsed

    @pytest.mark.asyncio
    async def test_get_portfolio_history_with_params(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_portfolio_history", {"interval": "1d", "limit": 30}, client)
        params = client.request.call_args[1]["params"]
        assert params["interval"] == "1d"
        assert params["limit"] == 30

    @pytest.mark.asyncio
    async def test_get_portfolio_history_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_portfolio_history", {}, client)
        assert client.request.call_args[0][1] == "/api/v1/analytics/portfolio/history"

    # --- get_leaderboard ---

    @pytest.mark.asyncio
    async def test_get_leaderboard_success(self) -> None:
        data = {"rankings": [{"account_id": "a1", "roi_pct": "15.5"}]}
        result = await _run_dispatch("get_leaderboard", {}, data)
        parsed = json.loads(result[0].text)
        assert "rankings" in parsed

    @pytest.mark.asyncio
    async def test_get_leaderboard_with_limit(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_leaderboard", {"limit": 10}, client)
        params = client.request.call_args[1]["params"]
        assert params["limit"] == 10

    @pytest.mark.asyncio
    async def test_get_leaderboard_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_leaderboard", {}, client)
        assert client.request.call_args[0][1] == "/api/v1/analytics/leaderboard"


# ---------------------------------------------------------------------------
# _dispatch — backtesting tools
# ---------------------------------------------------------------------------


class TestDispatchBacktesting:
    """Tests for backtesting tools (8 tools)."""

    # --- get_data_range ---

    @pytest.mark.asyncio
    async def test_get_data_range_success(self) -> None:
        data = {"earliest": "2024-01-01", "latest": "2025-03-01", "total_pairs": 600}
        result = await _run_dispatch("get_data_range", {}, data)
        parsed = json.loads(result[0].text)
        assert parsed["total_pairs"] == 600

    @pytest.mark.asyncio
    async def test_get_data_range_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_data_range", {}, client)
        assert client.request.call_args[0][1] == "/api/v1/market/data-range"

    # --- create_backtest ---

    @pytest.mark.asyncio
    async def test_create_backtest_minimal(self) -> None:
        data = {"session_id": "bt-123", "status": "created", "total_steps": 1440}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        result = await _dispatch(
            "create_backtest",
            {"start_time": "2025-01-01T00:00:00Z", "end_time": "2025-02-01T00:00:00Z"},
            client,
        )
        parsed = json.loads(result[0].text)
        assert parsed["session_id"] == "bt-123"

        body = client.request.call_args[1]["json"]
        assert body["start_time"] == "2025-01-01T00:00:00Z"
        assert body["end_time"] == "2025-02-01T00:00:00Z"

    @pytest.mark.asyncio
    async def test_create_backtest_with_all_options(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))

        await _dispatch(
            "create_backtest",
            {
                "start_time": "2025-01-01T00:00:00Z",
                "end_time": "2025-02-01T00:00:00Z",
                "starting_balance": 50000,
                "candle_interval": 3600,
                "pairs": ["BTCUSDT", "ETHUSDT"],
                "strategy_label": "momentum_v1",
                "exchange": "okx",
            },
            client,
        )

        body = client.request.call_args[1]["json"]
        assert body["starting_balance"] == "50000"
        assert body["candle_interval"] == 3600
        assert body["pairs"] == ["BTCUSDT", "ETHUSDT"]
        assert body["strategy_label"] == "momentum_v1"
        assert body["exchange"] == "okx"

    # --- start_backtest ---

    @pytest.mark.asyncio
    async def test_start_backtest_success(self) -> None:
        data = {"status": "running", "session_id": "bt-123"}
        result = await _run_dispatch("start_backtest", {"session_id": "bt-123"}, data)
        parsed = json.loads(result[0].text)
        assert parsed["status"] == "running"

    @pytest.mark.asyncio
    async def test_start_backtest_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("start_backtest", {"session_id": "bt-abc"}, client)
        call_args = client.request.call_args
        assert call_args[0][0] == "POST"
        assert "bt-abc" in call_args[0][1]
        assert call_args[0][1] == "/api/v1/backtest/bt-abc/start"

    # --- step_backtest ---

    @pytest.mark.asyncio
    async def test_step_backtest_success(self) -> None:
        data = {
            "virtual_time": "2025-01-01T01:00:00Z",
            "step": 1,
            "total_steps": 100,
            "is_complete": False,
            "prices": {"BTCUSDT": "65000"},
            "portfolio": {"total_equity": "10000"},
        }
        result = await _run_dispatch("step_backtest", {"session_id": "bt-123"}, data)
        parsed = json.loads(result[0].text)
        assert parsed["step"] == 1
        assert parsed["is_complete"] is False

    @pytest.mark.asyncio
    async def test_step_backtest_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("step_backtest", {"session_id": "bt-xyz"}, client)
        call_args = client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/api/v1/backtest/bt-xyz/step"

    # --- step_backtest_batch ---

    @pytest.mark.asyncio
    async def test_step_backtest_batch_success(self) -> None:
        data = {"step": 50, "total_steps": 100, "is_complete": False}
        result = await _run_dispatch("step_backtest_batch", {"session_id": "bt-123", "steps": 50}, data)
        parsed = json.loads(result[0].text)
        assert parsed["step"] == 50

    @pytest.mark.asyncio
    async def test_step_backtest_batch_sends_steps_in_body(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("step_backtest_batch", {"session_id": "bt-123", "steps": 100}, client)
        call_args = client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/api/v1/backtest/bt-123/step/batch"
        assert call_args[1]["json"] == {"steps": 100}

    # --- backtest_trade ---

    @pytest.mark.asyncio
    async def test_backtest_trade_market_buy(self) -> None:
        data = {"order_id": "bt-ord-1", "status": "filled", "executed_price": "65000"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        result = await _dispatch(
            "backtest_trade",
            {"session_id": "bt-123", "symbol": "btcusdt", "side": "buy", "quantity": 0.1},
            client,
        )
        parsed = json.loads(result[0].text)
        assert parsed["order_id"] == "bt-ord-1"

        body = client.request.call_args[1]["json"]
        assert body["symbol"] == "BTCUSDT"
        assert body["side"] == "buy"
        assert body["quantity"] == "0.1"
        assert "price" not in body

    @pytest.mark.asyncio
    async def test_backtest_trade_limit_with_price(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch(
            "backtest_trade",
            {"session_id": "bt-123", "symbol": "BTCUSDT", "side": "buy", "type": "limit",
             "quantity": 0.1, "price": 60000},
            client,
        )
        body = client.request.call_args[1]["json"]
        assert body["type"] == "limit"
        assert body["price"] == "60000"

    @pytest.mark.asyncio
    async def test_backtest_trade_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch(
            "backtest_trade",
            {"session_id": "bt-abc", "symbol": "BTCUSDT", "side": "buy", "quantity": 1.0},
            client,
        )
        assert client.request.call_args[0][1] == "/api/v1/backtest/bt-abc/trade/order"

    # --- get_backtest_results ---

    @pytest.mark.asyncio
    async def test_get_backtest_results_success(self) -> None:
        data = {
            "session_id": "bt-123",
            "status": "completed",
            "metrics": {"sharpe_ratio": "1.5", "max_drawdown_pct": "5.2"},
            "summary": {"roi_pct": "12.5", "total_trades": 42},
        }
        result = await _run_dispatch("get_backtest_results", {"session_id": "bt-123"}, data)
        parsed = json.loads(result[0].text)
        assert parsed["status"] == "completed"
        assert parsed["metrics"]["sharpe_ratio"] == "1.5"

    @pytest.mark.asyncio
    async def test_get_backtest_results_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_backtest_results", {"session_id": "bt-xyz"}, client)
        assert client.request.call_args[0][1] == "/api/v1/backtest/bt-xyz/results"

    # --- list_backtests ---

    @pytest.mark.asyncio
    async def test_list_backtests_no_filters(self) -> None:
        data = {"backtests": [], "total": 0}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))
        await _dispatch("list_backtests", {}, client)
        assert client.request.call_args[0][1] == "/api/v1/backtest/list"
        assert client.request.call_args[1]["params"] == {}

    @pytest.mark.asyncio
    async def test_list_backtests_with_filters(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("list_backtests", {"status": "completed", "strategy_label": "v1", "limit": 10}, client)
        params = client.request.call_args[1]["params"]
        assert params["status"] == "completed"
        assert params["strategy_label"] == "v1"
        assert params["limit"] == 10


# ---------------------------------------------------------------------------
# _dispatch — agent management tools
# ---------------------------------------------------------------------------


class TestDispatchAgentManagement:
    """Tests for agent management tools (6 tools)."""

    # --- list_agents ---

    @pytest.mark.asyncio
    async def test_list_agents_success(self) -> None:
        data = {"agents": [{"id": "a1", "display_name": "AlphaBot"}], "total": 1}
        result = await _run_dispatch("list_agents", {}, data)
        parsed = json.loads(result[0].text)
        assert parsed["agents"][0]["display_name"] == "AlphaBot"

    @pytest.mark.asyncio
    async def test_list_agents_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("list_agents", {}, client)
        assert client.request.call_args[0][1] == "/api/v1/agents"

    @pytest.mark.asyncio
    async def test_list_agents_with_params(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("list_agents", {"include_archived": True, "limit": 10}, client)
        params = client.request.call_args[1]["params"]
        assert params["include_archived"] == "true"
        assert params["limit"] == 10

    # --- create_agent ---

    @pytest.mark.asyncio
    async def test_create_agent_minimal(self) -> None:
        data = {"id": "agent-1", "display_name": "TestBot", "api_key": "ak_live_xyz"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        result = await _dispatch("create_agent", {"display_name": "TestBot"}, client)
        parsed = json.loads(result[0].text)
        assert parsed["display_name"] == "TestBot"

        body = client.request.call_args[1]["json"]
        assert body["display_name"] == "TestBot"

    @pytest.mark.asyncio
    async def test_create_agent_with_all_options(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))

        await _dispatch(
            "create_agent",
            {
                "display_name": "AlphaBot",
                "starting_balance": 50000,
                "llm_model": "claude-sonnet-4-20250514",
                "framework": "langchain",
                "strategy_tags": ["momentum", "mean-reversion"],
            },
            client,
        )

        body = client.request.call_args[1]["json"]
        assert body["display_name"] == "AlphaBot"
        assert body["starting_balance"] == "50000"
        assert body["llm_model"] == "claude-sonnet-4-20250514"
        assert body["framework"] == "langchain"
        assert body["strategy_tags"] == ["momentum", "mean-reversion"]

    @pytest.mark.asyncio
    async def test_create_agent_calls_post(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("create_agent", {"display_name": "Bot"}, client)
        assert client.request.call_args[0][0] == "POST"
        assert client.request.call_args[0][1] == "/api/v1/agents"

    # --- get_agent ---

    @pytest.mark.asyncio
    async def test_get_agent_success(self) -> None:
        data = {"id": "agent-1", "display_name": "TestBot", "balance": "10000"}
        result = await _run_dispatch("get_agent", {"agent_id": "agent-1"}, data)
        parsed = json.loads(result[0].text)
        assert parsed["id"] == "agent-1"

    @pytest.mark.asyncio
    async def test_get_agent_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_agent", {"agent_id": "agent-xyz"}, client)
        assert client.request.call_args[0][1] == "/api/v1/agents/agent-xyz"

    # --- reset_agent ---

    @pytest.mark.asyncio
    async def test_reset_agent_success(self) -> None:
        data = {"message": "Agent reset successfully"}
        result = await _run_dispatch("reset_agent", {"agent_id": "agent-1"}, data)
        parsed = json.loads(result[0].text)
        assert "reset" in parsed["message"].lower()

    @pytest.mark.asyncio
    async def test_reset_agent_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("reset_agent", {"agent_id": "agent-abc"}, client)
        call_args = client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/api/v1/agents/agent-abc/reset"

    # --- update_agent_risk ---

    @pytest.mark.asyncio
    async def test_update_agent_risk_success(self) -> None:
        data = {"max_position_size_pct": 25, "daily_loss_limit_pct": 5}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        await _dispatch(
            "update_agent_risk",
            {"agent_id": "agent-1", "max_position_size_pct": 25, "daily_loss_limit_pct": 5},
            client,
        )
        body = client.request.call_args[1]["json"]
        assert body["max_position_size_pct"] == 25
        assert body["daily_loss_limit_pct"] == 5

    @pytest.mark.asyncio
    async def test_update_agent_risk_calls_put(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("update_agent_risk", {"agent_id": "a1"}, client)
        call_args = client.request.call_args
        assert call_args[0][0] == "PUT"
        assert call_args[0][1] == "/api/v1/agents/a1/risk-profile"

    # --- get_agent_skill ---

    @pytest.mark.asyncio
    async def test_get_agent_skill_returns_text(self) -> None:
        skill_content = "# Agent Skill File\nAPI Key: ak_live_xyz\n..."
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_text_response(200, skill_content))

        result = await _dispatch("get_agent_skill", {"agent_id": "agent-1"}, client)
        assert len(result) == 1
        assert result[0].text == skill_content

    @pytest.mark.asyncio
    async def test_get_agent_skill_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_text_response(200, ""))
        await _dispatch("get_agent_skill", {"agent_id": "agent-abc"}, client)
        assert client.request.call_args[0][1] == "/api/v1/agents/agent-abc/skill.md"


# ---------------------------------------------------------------------------
# _dispatch — battle tools
# ---------------------------------------------------------------------------


class TestDispatchBattles:
    """Tests for battle tools (6 tools)."""

    # --- create_battle ---

    @pytest.mark.asyncio
    async def test_create_battle_minimal(self) -> None:
        data = {"id": "battle-1", "name": "Test Battle", "status": "draft"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        result = await _dispatch("create_battle", {"name": "Test Battle"}, client)
        parsed = json.loads(result[0].text)
        assert parsed["name"] == "Test Battle"
        assert parsed["status"] == "draft"

    @pytest.mark.asyncio
    async def test_create_battle_with_options(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))

        await _dispatch(
            "create_battle",
            {
                "name": "BTC Showdown",
                "battle_mode": "historical",
                "ranking_metric": "sharpe_ratio",
                "preset": "quick_5min",
                "config": {"duration": 300, "pairs": ["BTCUSDT"]},
            },
            client,
        )

        body = client.request.call_args[1]["json"]
        assert body["name"] == "BTC Showdown"
        assert body["battle_mode"] == "historical"
        assert body["ranking_metric"] == "sharpe_ratio"
        assert body["preset"] == "quick_5min"
        assert body["config"]["duration"] == 300

    @pytest.mark.asyncio
    async def test_create_battle_calls_post(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("create_battle", {"name": "Test"}, client)
        assert client.request.call_args[0][0] == "POST"
        assert client.request.call_args[0][1] == "/api/v1/battles"

    # --- list_battles ---

    @pytest.mark.asyncio
    async def test_list_battles_no_filters(self) -> None:
        data = {"battles": [], "total": 0}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))
        await _dispatch("list_battles", {}, client)
        assert client.request.call_args[0][1] == "/api/v1/battles"
        assert client.request.call_args[1]["params"] == {}

    @pytest.mark.asyncio
    async def test_list_battles_with_status_filter(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("list_battles", {"status": "active", "limit": 10}, client)
        params = client.request.call_args[1]["params"]
        assert params["status"] == "active"
        assert params["limit"] == 10

    # --- start_battle ---

    @pytest.mark.asyncio
    async def test_start_battle_success(self) -> None:
        data = {"id": "battle-1", "status": "active"}
        result = await _run_dispatch("start_battle", {"battle_id": "battle-1"}, data)
        parsed = json.loads(result[0].text)
        assert parsed["status"] == "active"

    @pytest.mark.asyncio
    async def test_start_battle_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("start_battle", {"battle_id": "battle-abc"}, client)
        call_args = client.request.call_args
        assert call_args[0][0] == "POST"
        assert call_args[0][1] == "/api/v1/battles/battle-abc/start"

    # --- get_battle_live ---

    @pytest.mark.asyncio
    async def test_get_battle_live_success(self) -> None:
        data = {"battle_id": "b1", "participants": [{"agent_id": "a1", "equity": "10500"}]}
        result = await _run_dispatch("get_battle_live", {"battle_id": "b1"}, data)
        parsed = json.loads(result[0].text)
        assert parsed["participants"][0]["equity"] == "10500"

    @pytest.mark.asyncio
    async def test_get_battle_live_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_battle_live", {"battle_id": "b-xyz"}, client)
        assert client.request.call_args[0][1] == "/api/v1/battles/b-xyz/live"

    # --- get_battle_results ---

    @pytest.mark.asyncio
    async def test_get_battle_results_success(self) -> None:
        data = {"battle_id": "b1", "status": "completed", "rankings": [{"rank": 1, "agent_id": "a1"}]}
        result = await _run_dispatch("get_battle_results", {"battle_id": "b1"}, data)
        parsed = json.loads(result[0].text)
        assert parsed["rankings"][0]["rank"] == 1

    @pytest.mark.asyncio
    async def test_get_battle_results_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_battle_results", {"battle_id": "b-xyz"}, client)
        assert client.request.call_args[0][1] == "/api/v1/battles/b-xyz/results"

    # --- get_battle_replay ---

    @pytest.mark.asyncio
    async def test_get_battle_replay_success(self) -> None:
        data = {"battle_id": "b1", "snapshots": [{"timestamp": "2025-01-01T00:00:00Z"}]}
        result = await _run_dispatch("get_battle_replay", {"battle_id": "b1"}, data)
        parsed = json.loads(result[0].text)
        assert "snapshots" in parsed

    @pytest.mark.asyncio
    async def test_get_battle_replay_calls_correct_endpoint(self) -> None:
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, {}))
        await _dispatch("get_battle_replay", {"battle_id": "b-xyz"}, client)
        assert client.request.call_args[0][1] == "/api/v1/battles/b-xyz/replay"


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
