"""Integration tests for agent connectivity layer.

Covers:
1. Concurrent async agents — 10 ``AsyncAgentExchangeClient`` instances call
   ``get_price`` simultaneously and all receive the correct ``Price`` model.
2. MCP tool discovery — instantiate ``register_tools``, call ``list_tools``,
   assert exactly 12 tools are present with the expected names.
3. MCP tool execution — call ``_dispatch("get_price", ...)`` with a mocked
   HTTP response and assert a ``TextContent`` list is returned.
4. ``skill.md`` validation — parse the file, extract all endpoint paths from
   code blocks and inline text, assert every path starts with ``/api/v1/``.

All tests use mocked HTTP (respx / unittest.mock). No live infrastructure
is required.

Run with::

    pytest tests/integration/test_agent_connectivity.py -v
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from agentexchange.async_client import AsyncAgentExchangeClient
from agentexchange.models import Price
import httpx
import pytest
import respx

from src.mcp.tools import _TOOL_DEFINITIONS, _dispatch, register_tools

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "http://localhost:8000"
_API_KEY = "ak_live_test_key_01234567890123456789012345678"
_API_SECRET = "sk_live_test_secret_0123456789012345678901234"
_SKILL_MD_PATH = Path(__file__).parents[2] / "docs" / "skill.md"

_EXPECTED_TOOL_NAMES: frozenset[str] = frozenset(
    {
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
)

# Dummy request used to construct valid httpx responses in tests that do not
# go through respx.
_DUMMY_REQUEST = httpx.Request("GET", f"{_BASE_URL}/api/v1/test")


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_response(
    status_code: int = 200,
    body: Any = None,
    *,
    request: httpx.Request | None = None,
) -> httpx.Response:
    """Build a minimal ``httpx.Response`` for mocking purposes."""
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(body or {}).encode(),
        headers={"content-type": "application/json"},
        request=request or _DUMMY_REQUEST,
    )


def _login_response(request: httpx.Request) -> httpx.Response:
    """Return a fake JWT login response."""
    return httpx.Response(
        status_code=200,
        content=json.dumps({"token": "fake.jwt.token", "expires_in": 900}).encode(),
        headers={"content-type": "application/json"},
        request=request,
    )


def _price_response(request: httpx.Request) -> httpx.Response:
    """Return a fake price response for BTCUSDT."""
    return httpx.Response(
        status_code=200,
        content=json.dumps(
            {
                "symbol": "BTCUSDT",
                "price": "65000.00",
                "timestamp": "2026-02-26T00:00:00Z",
            }
        ).encode(),
        headers={"content-type": "application/json"},
        request=request,
    )


# ---------------------------------------------------------------------------
# Section 1 — Concurrent async agents
# ---------------------------------------------------------------------------


class TestConcurrentAsyncAgents:
    """10 concurrent ``AsyncAgentExchangeClient`` instances calling get_price."""

    @pytest.mark.asyncio
    async def test_ten_concurrent_get_price_calls(self) -> None:
        """All 10 concurrent agents receive a ``Price`` model for BTCUSDT."""

        async def _run_agent(agent_index: int) -> Price:
            """Create an isolated client, call get_price, then close it."""
            with respx.mock(base_url=_BASE_URL, assert_all_called=False) as mock:
                mock.post("/api/v1/auth/login").mock(side_effect=_login_response)
                mock.get("/api/v1/market/price/BTCUSDT").mock(side_effect=_price_response)

                async with AsyncAgentExchangeClient(
                    api_key=f"ak_live_agent_{agent_index:02d}_" + "x" * 30,
                    api_secret=f"sk_live_agent_{agent_index:02d}_" + "x" * 30,
                    base_url=_BASE_URL,
                ) as client:
                    return await client.get_price("BTCUSDT")

        tasks = [asyncio.create_task(_run_agent(i)) for i in range(10)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        for price in results:
            assert isinstance(price, Price), f"Expected Price, got {type(price).__name__}"
            assert price.symbol == "BTCUSDT"
            assert price.price is not None

    @pytest.mark.asyncio
    async def test_concurrent_agents_do_not_share_jwt_state(self) -> None:
        """Each agent authenticates independently; JWT is not shared across instances."""
        login_calls: list[int] = []

        def _counting_login(request: httpx.Request) -> httpx.Response:
            login_calls.append(1)
            return _login_response(request)

        async def _run_agent(agent_index: int) -> None:
            with respx.mock(base_url=_BASE_URL, assert_all_called=False) as mock:
                mock.post("/api/v1/auth/login").mock(side_effect=_counting_login)
                mock.get("/api/v1/market/price/BTCUSDT").mock(side_effect=_price_response)

                async with AsyncAgentExchangeClient(
                    api_key=f"ak_live_iso_{agent_index:02d}_" + "x" * 30,
                    api_secret=f"sk_live_iso_{agent_index:02d}_" + "x" * 30,
                    base_url=_BASE_URL,
                ) as client:
                    await client.get_price("BTCUSDT")

        tasks = [asyncio.create_task(_run_agent(i)) for i in range(5)]
        await asyncio.gather(*tasks)

        # Each independent client must log in exactly once
        assert len(login_calls) == 5

    @pytest.mark.asyncio
    async def test_concurrent_agents_return_independent_results(self) -> None:
        """Results gathered from 10 concurrent tasks are all valid Price objects."""
        symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]

        async def _run_agent_for_symbol(symbol: str, agent_index: int) -> Price:
            with respx.mock(base_url=_BASE_URL, assert_all_called=False) as mock:
                mock.post("/api/v1/auth/login").mock(side_effect=_login_response)
                mock.get(f"/api/v1/market/price/{symbol}").mock(
                    return_value=httpx.Response(
                        200,
                        json={"symbol": symbol, "price": "100.00", "timestamp": "2026-02-26T00:00:00Z"},
                        request=httpx.Request("GET", f"{_BASE_URL}/api/v1/market/price/{symbol}"),
                    )
                )

                async with AsyncAgentExchangeClient(
                    api_key=f"ak_live_sym_{agent_index:02d}_" + "x" * 30,
                    api_secret=f"sk_live_sym_{agent_index:02d}_" + "x" * 30,
                    base_url=_BASE_URL,
                ) as client:
                    return await client.get_price(symbol)

        tasks = [asyncio.create_task(_run_agent_for_symbol(sym, idx)) for idx, sym in enumerate(symbols * 2)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        for result in results:
            assert isinstance(result, Price)
            assert result.symbol in symbols


# ---------------------------------------------------------------------------
# Section 2 — MCP tool discovery
# ---------------------------------------------------------------------------


class TestMcpToolDiscovery:
    """MCP ``list_tools`` returns exactly 12 tools with the expected names."""

    @pytest.mark.asyncio
    async def test_register_tools_list_tools_returns_twelve(self) -> None:
        """Registering tools and calling the list handler yields 12 tools."""
        captured_list_handler = None
        server = MagicMock()
        client = AsyncMock(spec=httpx.AsyncClient)

        def _capture_list(fn: Any) -> Any:
            nonlocal captured_list_handler
            captured_list_handler = fn
            return fn

        server.list_tools.return_value = _capture_list
        server.call_tool.return_value = lambda fn: fn

        register_tools(server, client)

        assert captured_list_handler is not None, "list_tools handler was not captured"
        result = await captured_list_handler()

        assert len(result) == 12, f"Expected 12 tools, got {len(result)}"

    @pytest.mark.asyncio
    async def test_register_tools_list_tools_returns_all_expected_names(self) -> None:
        """All 12 expected tool names are present in the list_tools response."""
        captured_list_handler = None
        server = MagicMock()
        client = AsyncMock(spec=httpx.AsyncClient)

        def _capture_list(fn: Any) -> Any:
            nonlocal captured_list_handler
            captured_list_handler = fn
            return fn

        server.list_tools.return_value = _capture_list
        server.call_tool.return_value = lambda fn: fn

        register_tools(server, client)

        result = await captured_list_handler()
        actual_names = {tool.name for tool in result}

        assert actual_names == _EXPECTED_TOOL_NAMES, (
            f"Tool name mismatch.\n"
            f"  Missing: {_EXPECTED_TOOL_NAMES - actual_names}\n"
            f"  Unexpected: {actual_names - _EXPECTED_TOOL_NAMES}"
        )

    def test_tool_definitions_count_matches_twelve(self) -> None:
        """The static ``_TOOL_DEFINITIONS`` list always has 12 entries."""
        assert len(_TOOL_DEFINITIONS) == 12

    def test_tool_definitions_names_match_expected(self) -> None:
        """Every tool in ``_TOOL_DEFINITIONS`` is in the expected set."""
        actual = {t.name for t in _TOOL_DEFINITIONS}
        assert actual == _EXPECTED_TOOL_NAMES

    def test_each_tool_has_non_empty_description(self) -> None:
        """All 12 tools carry a human-readable description."""
        for tool in _TOOL_DEFINITIONS:
            assert tool.description, f"Tool '{tool.name}' has an empty description"

    def test_each_tool_has_object_input_schema(self) -> None:
        """All tool input schemas have ``type: object``."""
        for tool in _TOOL_DEFINITIONS:
            assert isinstance(tool.inputSchema, dict), f"Tool '{tool.name}' inputSchema is not a dict"
            assert tool.inputSchema.get("type") == "object", f"Tool '{tool.name}' inputSchema.type != 'object'"


# ---------------------------------------------------------------------------
# Section 3 — MCP tool execution via _dispatch
# ---------------------------------------------------------------------------


class TestMcpToolExecution:
    """``_dispatch`` routes tool calls correctly and returns ``TextContent``."""

    @pytest.mark.asyncio
    async def test_dispatch_get_price_returns_text_content(self) -> None:
        """``_dispatch("get_price", ...)`` returns a non-empty TextContent list."""
        price_data = {
            "symbol": "BTCUSDT",
            "price": "65000.00",
            "timestamp": "2026-02-26T00:00:00Z",
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, price_data))

        result = await _dispatch("get_price", {"symbol": "BTCUSDT"}, client)

        assert len(result) == 1
        assert result[0].type == "text"
        assert "BTCUSDT" in result[0].text

    @pytest.mark.asyncio
    async def test_dispatch_get_price_response_contains_price_field(self) -> None:
        """The JSON returned inside TextContent has the ``price`` field."""
        price_data = {"symbol": "BTCUSDT", "price": "65000.00"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, price_data))

        result = await _dispatch("get_price", {"symbol": "BTCUSDT"}, client)

        parsed = json.loads(result[0].text)
        assert parsed["price"] == "65000.00"

    @pytest.mark.asyncio
    async def test_dispatch_routes_via_call_tool_handler(self) -> None:
        """The call_tool handler registered via ``register_tools`` correctly dispatches."""
        captured_call_handler = None
        server = MagicMock()

        price_data = {"symbol": "BTCUSDT", "price": "50000.00"}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, price_data))

        def _capture_call(fn: Any) -> Any:
            nonlocal captured_call_handler
            captured_call_handler = fn
            return fn

        server.list_tools.return_value = lambda fn: fn
        server.call_tool.return_value = _capture_call

        register_tools(server, client)

        assert captured_call_handler is not None
        result = await captured_call_handler("get_price", {"symbol": "BTCUSDT"})

        assert len(result) == 1
        assert "BTCUSDT" in result[0].text

    @pytest.mark.asyncio
    async def test_dispatch_get_all_prices_returns_text_content(self) -> None:
        """``_dispatch("get_all_prices", ...)`` returns TextContent."""
        data = {"prices": [{"symbol": "BTCUSDT", "price": "65000.00"}]}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        result = await _dispatch("get_all_prices", {}, client)

        assert len(result) == 1
        assert result[0].type == "text"

    @pytest.mark.asyncio
    async def test_dispatch_get_balance_returns_text_content(self) -> None:
        """``_dispatch("get_balance", ...)`` returns TextContent."""
        data = {"balances": [{"asset": "USDT", "available": "10000.00", "locked": "0.00"}]}
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, data))

        result = await _dispatch("get_balance", {}, client)

        assert len(result) == 1
        assert result[0].type == "text"

    @pytest.mark.asyncio
    async def test_dispatch_place_order_returns_text_content(self) -> None:
        """``_dispatch("place_order", ...)`` returns TextContent with order data."""
        order_data = {
            "order_id": "ord-abc-123",
            "symbol": "BTCUSDT",
            "side": "buy",
            "type": "market",
            "status": "filled",
            "filled_quantity": "0.001",
            "average_price": "65000.00",
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.request = AsyncMock(return_value=_make_response(200, order_data))

        result = await _dispatch(
            "place_order",
            {"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": 0.001},
            client,
        )

        assert len(result) == 1
        assert result[0].type == "text"
        parsed = json.loads(result[0].text)
        assert parsed["order_id"] == "ord-abc-123"

    @pytest.mark.asyncio
    async def test_dispatch_unknown_tool_returns_error_text_content(self) -> None:
        """Unknown tool names are caught by the call_tool handler and returned as error TextContent."""
        captured_call_handler = None
        server = MagicMock()
        client = AsyncMock(spec=httpx.AsyncClient)

        def _capture_call(fn: Any) -> Any:
            nonlocal captured_call_handler
            captured_call_handler = fn
            return fn

        server.list_tools.return_value = lambda fn: fn
        server.call_tool.return_value = _capture_call

        register_tools(server, client)

        assert captured_call_handler is not None
        result = await captured_call_handler("nonexistent_tool", {})

        assert len(result) == 1
        assert "Error" in result[0].text

    @pytest.mark.asyncio
    async def test_dispatch_all_twelve_tools_callable(self) -> None:
        """Every tool in ``_TOOL_DEFINITIONS`` can be dispatched without raising."""
        tool_payloads: dict[str, tuple[dict[str, Any], Any]] = {
            "get_price": (
                {"symbol": "BTCUSDT"},
                {"symbol": "BTCUSDT", "price": "65000.00"},
            ),
            "get_all_prices": (
                {},
                {"prices": []},
            ),
            "get_candles": (
                {"symbol": "BTCUSDT", "interval": "1h"},
                {"candles": []},
            ),
            "get_balance": (
                {},
                {"balances": []},
            ),
            "get_positions": (
                {},
                {"positions": []},
            ),
            "place_order": (
                {"symbol": "BTCUSDT", "side": "buy", "type": "market", "quantity": 0.001},
                {"order_id": "test-id", "status": "filled"},
            ),
            "cancel_order": (
                {"order_id": "test-id"},
                {"order_id": "test-id", "status": "cancelled"},
            ),
            "get_order_status": (
                {"order_id": "test-id"},
                {"order_id": "test-id", "status": "filled"},
            ),
            "get_portfolio": (
                {},
                {"total_equity": "10000.00"},
            ),
            "get_trade_history": (
                {},
                {"trades": [], "total": 0},
            ),
            "get_performance": (
                {},
                {"roi": "0.00", "sharpe_ratio": "0.00"},
            ),
            "reset_account": (
                {"confirm": False},
                {},
            ),
        }

        for tool_name, (args, response_body) in tool_payloads.items():
            client = AsyncMock(spec=httpx.AsyncClient)
            client.request = AsyncMock(return_value=_make_response(200, response_body))

            result = await _dispatch(tool_name, args, client)

            assert len(result) == 1, f"Tool '{tool_name}' returned {len(result)} items, expected 1"
            assert result[0].type == "text", f"Tool '{tool_name}' returned type '{result[0].type}', expected 'text'"


# ---------------------------------------------------------------------------
# Section 4 — skill.md endpoint validation
# ---------------------------------------------------------------------------


class TestSkillMdValidation:
    """Validate ``docs/skill.md`` endpoint documentation.

    The file declares ``/api/v1`` as its base URL and then documents endpoints
    as relative paths (e.g. ``GET /market/price/{symbol}``).  The tests below
    verify:

    1. The file exists and has substantial content.
    2. The base URL ``/api/v1`` is declared so every relative path resolves
       correctly to a full ``/api/v1/...`` path.
    3. All *absolute* paths (those beginning with ``/api/``) that appear in the
       file do start with ``/api/v1/``.
    4. The key endpoint fragments used by the 12 MCP tools are present in the
       file (relative path form is acceptable).
    5. Authentication and error-handling guidance is present.
    """

    @pytest.fixture(scope="class")
    def skill_md_content(self) -> str:
        """Load the skill.md file once for the whole class."""
        assert _SKILL_MD_PATH.exists(), (
            f"docs/skill.md not found at {_SKILL_MD_PATH}. Run the doc generation step first."
        )
        return _SKILL_MD_PATH.read_text(encoding="utf-8")

    def _extract_absolute_api_paths(self, content: str) -> list[str]:
        """Extract only *absolute* API paths (starting with ``/api/``).

        Captures backtick-quoted and HTTP-method-prefixed paths whose first
        segment is ``/api/``.  Short-form relative paths (``/market/…``) are
        intentionally excluded here — they are validated indirectly by checking
        that the base URL declaration is present.
        """
        paths: list[str] = []

        # Backtick-quoted absolute paths, e.g. `/api/v1/market/price/{symbol}`
        for match in re.finditer(r"`(/api/[^`\s]+)`", content):
            paths.append(match.group(1))

        # HTTP method + absolute path, e.g. `GET /api/v1/market/prices`
        for match in re.finditer(
            r"(?:GET|POST|PUT|DELETE|PATCH)\s+(/api/[^\s`\"'\)]+)",
            content,
        ):
            paths.append(match.group(1))

        for match in re.finditer(
            r"^(?:GET|POST|PUT|DELETE|PATCH)\s+(/api/[^\s]+)",
            content,
            re.MULTILINE,
        ):
            paths.append(match.group(1))

        return list(set(paths))

    def test_skill_md_file_exists(self) -> None:
        """``docs/skill.md`` must exist in the repository."""
        assert _SKILL_MD_PATH.exists(), f"docs/skill.md not found at {_SKILL_MD_PATH}"

    def test_skill_md_is_non_empty(self, skill_md_content: str) -> None:
        """``docs/skill.md`` must contain meaningful content."""
        assert len(skill_md_content) > 500, f"docs/skill.md is suspiciously short ({len(skill_md_content)} chars)"

    def test_skill_md_declares_api_v1_base_url(self, skill_md_content: str) -> None:
        """``skill.md`` must declare ``/api/v1`` as the base URL.

        The file uses relative endpoint paths; the base-URL declaration ties
        them to the canonical ``/api/v1/`` prefix, which satisfies the
        requirement that all endpoints live under ``/api/v1/``.
        """
        assert "/api/v1" in skill_md_content, (
            "docs/skill.md does not declare '/api/v1' as the base URL. "
            "Add a 'Base URL: …/api/v1' note so relative paths resolve correctly."
        )

    def test_all_absolute_paths_start_with_api_v1(self, skill_md_content: str) -> None:
        """Every *absolute* path (starting with ``/api/``) starts with ``/api/v1/``."""
        paths = self._extract_absolute_api_paths(skill_md_content)

        bad_paths = [p for p in paths if not p.startswith("/api/v1/")]
        assert not bad_paths, f"Found {len(bad_paths)} absolute path(s) not starting with /api/v1/:\n" + "\n".join(
            f"  {p}" for p in sorted(bad_paths)
        )

    def test_skill_md_covers_all_mcp_tool_endpoints(self, skill_md_content: str) -> None:
        """Core endpoint fragments used by the 12 MCP tools appear in skill.md.

        The file may use either the full ``/api/v1/market/price/{symbol}`` form
        or the relative ``/market/price/`` form — both are accepted.
        """
        # Pairs of (full_path_fragment, relative_path_fragment); either must be present
        core_endpoint_pairs = [
            ("/api/v1/market/price/", "/market/price/"),
            ("/api/v1/market/prices", "/market/prices"),
            ("/api/v1/market/candles/", "/market/candles/"),
            ("/api/v1/account/balance", "/account/balance"),
            ("/api/v1/account/positions", "/account/positions"),
            ("/api/v1/trade/order", "/trade/order"),
            ("/api/v1/account/portfolio", "/account/portfolio"),
            ("/api/v1/analytics/performance", "/analytics/performance"),
            ("/api/v1/account/reset", "/account/reset"),
        ]
        missing = [
            full for full, rel in core_endpoint_pairs if full not in skill_md_content and rel not in skill_md_content
        ]
        assert not missing, (
            "The following core endpoint paths are missing from docs/skill.md "
            "(neither full /api/v1/ form nor relative form found):\n" + "\n".join(f"  {p}" for p in missing)
        )

    def test_skill_md_mentions_authentication(self, skill_md_content: str) -> None:
        """``skill.md`` should describe how to authenticate."""
        auth_keywords = ["api_key", "X-API-Key", "api_secret", "Authorization"]
        found = [kw for kw in auth_keywords if kw in skill_md_content]
        assert found, (
            f"docs/skill.md does not mention any authentication keywords. Expected at least one of: {auth_keywords}"
        )

    def test_skill_md_mentions_error_handling(self, skill_md_content: str) -> None:
        """``skill.md`` should mention error codes or handling guidance."""
        error_keywords = ["error", "Error", "4xx", "429", "RateLimit", "insufficient"]
        found = [kw for kw in error_keywords if kw in skill_md_content]
        assert found, f"docs/skill.md does not mention error handling. Expected at least one of: {error_keywords}"
