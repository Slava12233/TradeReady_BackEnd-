"""MCP tool definitions for the AI Agent Crypto Trading Platform.

Defines all 12 trading tools per Section 17 of the development plan.
Each tool maps to a REST API endpoint via an ``httpx.AsyncClient`` that
is injected at registration time by ``server.py``.

Tools
-----
1.  get_price           — GET /api/v1/market/price/{symbol}
2.  get_all_prices      — GET /api/v1/market/prices
3.  get_candles         — GET /api/v1/market/candles/{symbol}
4.  get_balance         — GET /api/v1/account/balance
5.  get_positions       — GET /api/v1/account/positions
6.  place_order         — POST /api/v1/trade/order
7.  cancel_order        — DELETE /api/v1/trade/order/{order_id}
8.  get_order_status    — GET /api/v1/trade/order/{order_id}
9.  get_portfolio       — GET /api/v1/account/portfolio
10. get_trade_history   — GET /api/v1/trade/history
11. get_performance     — GET /api/v1/analytics/performance
12. reset_account       — POST /api/v1/account/reset

Usage::

    import httpx
    from mcp.server import Server
    from src.mcp.tools import register_tools

    server = Server("agentexchange")
    http_client = httpx.AsyncClient(base_url="http://localhost:8000", ...)
    register_tools(server, http_client)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from mcp.server import Server
import mcp.types as types

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_TOOL_DEFINITIONS: list[types.Tool] = [
    types.Tool(
        name="get_price",
        description="Get the current price of a cryptocurrency trading pair.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading pair symbol, e.g. BTCUSDT",
                },
            },
            "required": ["symbol"],
        },
    ),
    types.Tool(
        name="get_all_prices",
        description="Get current prices for all available trading pairs.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    types.Tool(
        name="get_candles",
        description="Get historical OHLCV candle data for a trading pair.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading pair symbol, e.g. BTCUSDT",
                },
                "interval": {
                    "type": "string",
                    "description": "Candle interval",
                    "enum": ["1m", "5m", "15m", "1h", "4h", "1d"],
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of candles to return (default 100, max 1000)",
                    "default": 100,
                },
            },
            "required": ["symbol", "interval"],
        },
    ),
    types.Tool(
        name="get_balance",
        description="Get your current account balances for all assets.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    types.Tool(
        name="get_positions",
        description="Get your current open trading positions with unrealized PnL.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    types.Tool(
        name="place_order",
        description=(
            "Place a buy or sell order for a cryptocurrency. "
            "For limit, stop_loss, and take_profit orders the 'price' field is required."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Trading pair symbol, e.g. BTCUSDT",
                },
                "side": {
                    "type": "string",
                    "description": "Order direction",
                    "enum": ["buy", "sell"],
                },
                "type": {
                    "type": "string",
                    "description": "Order type",
                    "enum": ["market", "limit", "stop_loss", "take_profit"],
                },
                "quantity": {
                    "type": "number",
                    "description": "Order quantity in base asset",
                },
                "price": {
                    "type": "number",
                    "description": ("Limit / trigger price. Required for limit, stop_loss, and take_profit orders."),
                },
            },
            "required": ["symbol", "side", "type", "quantity"],
        },
    ),
    types.Tool(
        name="cancel_order",
        description="Cancel a pending order by its order ID.",
        inputSchema={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "UUID of the order to cancel",
                },
            },
            "required": ["order_id"],
        },
    ),
    types.Tool(
        name="get_order_status",
        description="Check the current status and details of an order.",
        inputSchema={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "UUID of the order to look up",
                },
            },
            "required": ["order_id"],
        },
    ),
    types.Tool(
        name="get_portfolio",
        description=(
            "Get complete portfolio summary including total equity, cash balance, open positions, and unrealized PnL."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    types.Tool(
        name="get_trade_history",
        description="Get your historical trade executions.",
        inputSchema={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Filter by trading pair symbol (optional)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of trades to return (default 50)",
                    "default": 50,
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_performance",
        description=("Get trading performance metrics including Sharpe ratio, win rate, max drawdown, and ROI."),
        inputSchema={
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "Time period for metrics (default: all)",
                    "enum": ["1d", "7d", "30d", "90d", "all"],
                    "default": "all",
                },
            },
            "required": [],
        },
    ),
    types.Tool(
        name="reset_account",
        description=(
            "Reset your trading account to starting balance. "
            "All open positions will be closed and trade history cleared. "
            "This action is irreversible."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to execute the reset",
                },
            },
            "required": ["confirm"],
        },
    ),
]


# ---------------------------------------------------------------------------
# REST call helpers
# ---------------------------------------------------------------------------


async def _call_api(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute an HTTP request and return the parsed JSON body.

    Args:
        client: Authenticated ``httpx.AsyncClient`` pointed at the platform.
        method: HTTP method in uppercase (``GET``, ``POST``, ``DELETE``).
        path: URL path relative to the client's base URL, e.g. ``/api/v1/market/price/BTCUSDT``.
        params: Optional query-string parameters.
        json: Optional JSON request body.

    Returns:
        Parsed JSON response as a dictionary.

    Raises:
        httpx.HTTPStatusError: Propagated so the tool handler can format
            a user-readable error message.
    """
    response = await client.request(method, path, params=params, json=json)
    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]


def _error_content(exc: Exception) -> list[types.TextContent]:
    """Format an exception as a single MCP TextContent error message.

    Args:
        exc: The exception that was raised.

    Returns:
        A list containing one ``TextContent`` with the error description.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            body = exc.response.json()
            detail = body.get("detail") or body.get("error", {}).get("message") or str(exc)
        except Exception:
            detail = str(exc)
        return [types.TextContent(type="text", text=f"API error: {detail}")]
    return [types.TextContent(type="text", text=f"Error: {exc}")]


def _json_content(data: dict[str, Any] | list[Any]) -> list[types.TextContent]:
    """Wrap a JSON-serialisable value as MCP TextContent.

    Args:
        data: The API response data to serialise.

    Returns:
        A list containing one ``TextContent`` with the JSON string.
    """
    import json

    return [types.TextContent(type="text", text=json.dumps(data, indent=2))]


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


def register_tools(server: Server, http_client: httpx.AsyncClient) -> None:
    """Register all 12 trading tools on *server*.

    This function wires the tool list and the call handler to the MCP
    ``Server`` instance.  Call it once during server initialisation after
    the ``http_client`` is configured with the correct base URL and
    authentication headers.

    Args:
        server: The ``mcp.server.Server`` instance to register tools on.
        http_client: An ``httpx.AsyncClient`` already configured with
            ``base_url`` and ``X-API-Key`` / ``Authorization`` headers.
    """

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        """Return all available trading tools."""
        return _TOOL_DEFINITIONS

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict[str, Any]
    ) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
        """Dispatch a tool call to the corresponding REST endpoint.

        Args:
            name: The tool name as registered in ``_TOOL_DEFINITIONS``.
            arguments: Key-value mapping of tool input parameters.

        Returns:
            A list of MCP content items (always ``TextContent`` here).
        """
        logger.debug("MCP tool call: %s  args=%s", name, arguments)

        try:
            return await _dispatch(name, arguments, http_client)
        except httpx.HTTPStatusError as exc:
            logger.warning("Tool %s HTTP error: %s", name, exc)
            return _error_content(exc)
        except Exception as exc:
            logger.exception("Tool %s unexpected error: %s", name, exc)
            return _error_content(exc)


async def _dispatch(
    name: str,
    args: dict[str, Any],
    client: httpx.AsyncClient,
) -> list[types.TextContent]:
    """Route a validated tool call to the appropriate REST endpoint.

    Args:
        name: Tool name.
        args: Validated input arguments from the MCP caller.
        client: Authenticated HTTP client.

    Returns:
        MCP ``TextContent`` list with JSON response payload.

    Raises:
        ValueError: When *name* does not match any known tool.
    """
    match name:
        # ------------------------------------------------------------------
        # Market data
        # ------------------------------------------------------------------
        case "get_price":
            symbol: str = args["symbol"].upper()
            data = await _call_api(client, "GET", f"/api/v1/market/price/{symbol}")
            return _json_content(data)

        case "get_all_prices":
            data = await _call_api(client, "GET", "/api/v1/market/prices")
            return _json_content(data)

        case "get_candles":
            symbol = args["symbol"].upper()
            params: dict[str, Any] = {"interval": args["interval"]}
            if "limit" in args:
                params["limit"] = int(args["limit"])
            data = await _call_api(client, "GET", f"/api/v1/market/candles/{symbol}", params=params)
            return _json_content(data)

        # ------------------------------------------------------------------
        # Account
        # ------------------------------------------------------------------
        case "get_balance":
            data = await _call_api(client, "GET", "/api/v1/account/balance")
            return _json_content(data)

        case "get_positions":
            data = await _call_api(client, "GET", "/api/v1/account/positions")
            return _json_content(data)

        case "get_portfolio":
            data = await _call_api(client, "GET", "/api/v1/account/portfolio")
            return _json_content(data)

        case "reset_account":
            confirm: bool = args.get("confirm", False)
            if not confirm:
                return [
                    types.TextContent(
                        type="text",
                        text=("Account reset aborted: 'confirm' must be true. Pass confirm=true to execute the reset."),
                    )
                ]
            data = await _call_api(client, "POST", "/api/v1/account/reset", json={"confirm": True})
            return _json_content(data)

        # ------------------------------------------------------------------
        # Trading
        # ------------------------------------------------------------------
        case "place_order":
            body: dict[str, Any] = {
                "symbol": args["symbol"].upper(),
                "side": args["side"],
                "type": args["type"],
                "quantity": str(args["quantity"]),
            }
            if "price" in args and args["price"] is not None:
                body["price"] = str(args["price"])
            data = await _call_api(client, "POST", "/api/v1/trade/order", json=body)
            return _json_content(data)

        case "cancel_order":
            order_id: str = args["order_id"]
            data = await _call_api(client, "DELETE", f"/api/v1/trade/order/{order_id}")
            return _json_content(data)

        case "get_order_status":
            order_id = args["order_id"]
            data = await _call_api(client, "GET", f"/api/v1/trade/order/{order_id}")
            return _json_content(data)

        case "get_trade_history":
            params = {}
            if "symbol" in args and args["symbol"]:
                params["symbol"] = args["symbol"].upper()
            if "limit" in args:
                params["limit"] = int(args["limit"])
            data = await _call_api(client, "GET", "/api/v1/trade/history", params=params)
            return _json_content(data)

        # ------------------------------------------------------------------
        # Analytics
        # ------------------------------------------------------------------
        case "get_performance":
            params = {}
            if "period" in args and args["period"]:
                params["period"] = args["period"]
            data = await _call_api(client, "GET", "/api/v1/analytics/performance", params=params)
            return _json_content(data)

        case _:
            raise ValueError(f"Unknown tool: {name!r}")
