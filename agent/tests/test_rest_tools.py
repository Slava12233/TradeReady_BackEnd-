"""Tests for agent/tools/rest_tools.py :: PlatformRESTClient and get_rest_tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent.config import AgentConfig
from agent.tools.rest_tools import PlatformRESTClient, get_rest_tools

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    """Build a minimal valid AgentConfig from environment variables."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_testkey")
    monkeypatch.setenv("PLATFORM_API_SECRET", "sk_live_testsecret")
    monkeypatch.setenv("PLATFORM_BASE_URL", "http://localhost:8000")
    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    """Build a mock httpx.Response that returns the given JSON and status."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    resp.content = b"..." if json_data else b""
    # raise_for_status() is a no-op for 2xx; raises for others
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# PlatformRESTClient — auth header
# ---------------------------------------------------------------------------


class TestPlatformRESTClientAuth:
    """Tests that PlatformRESTClient sets the X-API-Key header correctly."""

    def test_api_key_header_set_on_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The httpx.AsyncClient is initialised with X-API-Key from the config."""
        config = _make_config(monkeypatch)
        with patch("httpx.AsyncClient") as mock_cls:
            PlatformRESTClient(config)
            call_kwargs = mock_cls.call_args.kwargs
            assert call_kwargs["headers"]["X-API-Key"] == "ak_live_testkey"

    def test_base_url_trailing_slash_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Trailing slash on platform_base_url is stripped."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_key")
        monkeypatch.setenv("PLATFORM_BASE_URL", "http://localhost:8000/")
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        with patch("httpx.AsyncClient") as mock_cls:
            PlatformRESTClient(config)
            call_kwargs = mock_cls.call_args.kwargs
            assert not call_kwargs["base_url"].endswith("/")


# ---------------------------------------------------------------------------
# PlatformRESTClient — async context manager
# ---------------------------------------------------------------------------


class TestPlatformRESTClientContextManager:
    """Tests for __aenter__ / __aexit__ / close lifecycle."""

    async def test_aenter_returns_self(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """__aenter__ returns the client instance itself."""
        config = _make_config(monkeypatch)
        with patch("httpx.AsyncClient"):
            client = PlatformRESTClient(config)
            result = await client.__aenter__()
            assert result is client

    async def test_aexit_calls_close(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """__aexit__ calls close(), which calls aclose() on the underlying httpx client."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            await client.__aexit__(None, None, None)
            mock_httpx.aclose.assert_called_once()


# ---------------------------------------------------------------------------
# PlatformRESTClient — _get and _post helpers
# ---------------------------------------------------------------------------


class TestPlatformRESTClientHelpers:
    """Tests for the internal _get and _post helper methods."""

    async def test_get_returns_parsed_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get returns the parsed JSON dict from a 200 response."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.get.return_value = _mock_response({"session_id": "abc123"})
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            result = await client._get("/api/v1/backtest/abc123/results")
        assert result == {"session_id": "abc123"}

    async def test_get_raises_on_http_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_get raises httpx.HTTPStatusError on a 404 response."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.get.return_value = _mock_response({}, status_code=404)
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            with pytest.raises(httpx.HTTPStatusError):
                await client._get("/api/v1/backtest/nonexistent/results")

    async def test_post_returns_parsed_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_post returns parsed JSON from a 200 response."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.post.return_value = _mock_response({"status": "created"})
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            result = await client._post("/api/v1/backtest/create", {"symbols": ["BTCUSDT"]})
        assert result == {"status": "created"}

    async def test_post_empty_body_returns_empty_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_post returns {} when the response body is empty (e.g. 204)."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        empty_resp = _mock_response({})
        empty_resp.content = b""
        mock_httpx.post.return_value = empty_resp
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            result = await client._post("/api/v1/some/endpoint")
        assert result == {}

    async def test_post_raises_on_server_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_post raises httpx.HTTPStatusError on a 500 response."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.post.return_value = _mock_response({}, status_code=500)
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            with pytest.raises(httpx.HTTPStatusError):
                await client._post("/api/v1/backtest/create", {})


# ---------------------------------------------------------------------------
# PlatformRESTClient — backtest methods
# ---------------------------------------------------------------------------


class TestPlatformRESTClientBacktest:
    """Tests for PlatformRESTClient backtest method calls."""

    async def _client_with_post(self, monkeypatch: pytest.MonkeyPatch, response_data: dict) -> PlatformRESTClient:
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.post.return_value = _mock_response(response_data)
        mock_httpx.get.return_value = _mock_response(response_data)
        # Store mock on client for assertion
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            client._mock_httpx = mock_httpx  # type: ignore[attr-defined]
        return client

    async def test_create_backtest_sends_correct_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """create_backtest sends the expected JSON body to the correct endpoint."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.post.return_value = _mock_response({"session_id": "sess-1"})
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            result = await client.create_backtest(
                start_time="2024-01-01T00:00:00Z",
                end_time="2024-03-01T00:00:00Z",
                symbols=["BTCUSDT"],
                interval=60,
            )
        assert result == {"session_id": "sess-1"}
        called_path = mock_httpx.post.call_args.args[0]
        assert "/api/v1/backtest/create" in called_path

    async def test_start_backtest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """start_backtest posts to the correct session endpoint."""
        config = _make_config(monkeypatch)
        session_id = "sess-abc"
        mock_httpx = AsyncMock()
        mock_httpx.post.return_value = _mock_response({"status": "running", "session_id": session_id})
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            result = await client.start_backtest(session_id)
        assert result["status"] == "running"
        called_path = mock_httpx.post.call_args.args[0]
        assert session_id in called_path
        assert "start" in called_path

    async def test_get_backtest_results_uses_get(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_backtest_results uses a GET request."""
        config = _make_config(monkeypatch)
        session_id = "sess-xyz"
        mock_httpx = AsyncMock()
        mock_httpx.get.return_value = _mock_response({"session_id": session_id, "status": "completed"})
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            result = await client.get_backtest_results(session_id)
        assert result["status"] == "completed"
        called_path = mock_httpx.get.call_args.args[0]
        assert session_id in called_path
        assert "results" in called_path

    async def test_backtest_trade_includes_price_when_provided(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """backtest_trade includes price in the body for limit orders."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.post.return_value = _mock_response({"order_id": "ord-1", "status": "queued"})
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            await client.backtest_trade(
                "sess-1", "BTCUSDT", "buy", "0.01", order_type="limit", price="60000"
            )
        body = mock_httpx.post.call_args.kwargs.get("json")
        assert body is not None
        assert body["price"] == "60000"

    async def test_backtest_trade_omits_price_when_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """backtest_trade omits the price key for market orders."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.post.return_value = _mock_response({"order_id": "ord-2", "status": "filled"})
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            await client.backtest_trade("sess-1", "BTCUSDT", "sell", "0.01")
        body = mock_httpx.post.call_args.kwargs.get("json")
        assert "price" not in body


# ---------------------------------------------------------------------------
# PlatformRESTClient — strategy methods
# ---------------------------------------------------------------------------


class TestPlatformRESTClientStrategy:
    """Tests for PlatformRESTClient strategy/test method calls."""

    async def test_create_strategy_sends_name_and_definition(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """create_strategy sends name and definition fields in the body."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.post.return_value = _mock_response({"strategy_id": "strat-1"})
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            result = await client.create_strategy(
                name="RSI Crossover",
                description="Buy on RSI dip",
                definition={"pairs": ["BTCUSDT"], "timeframe": "1h",
                             "entry_conditions": {}, "exit_conditions": {}},
            )
        assert result == {"strategy_id": "strat-1"}
        body = mock_httpx.post.call_args.kwargs.get("json")
        assert body["name"] == "RSI Crossover"
        assert "definition" in body

    async def test_create_strategy_omits_empty_description(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """create_strategy omits description from body when it is an empty string."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.post.return_value = _mock_response({"strategy_id": "strat-2"})
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            await client.create_strategy(
                name="No Desc",
                description="",
                definition={"pairs": [], "timeframe": "1h",
                             "entry_conditions": {}, "exit_conditions": {}},
            )
        body = mock_httpx.post.call_args.kwargs.get("json")
        assert "description" not in body

    async def test_get_test_results_uses_get_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_test_results issues a GET to the correct path."""
        config = _make_config(monkeypatch)
        strategy_id = "strat-abc"
        test_id = "test-xyz"
        mock_httpx = AsyncMock()
        mock_httpx.get.return_value = _mock_response({"test_run_id": test_id, "status": "completed"})
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            result = await client.get_test_results(strategy_id, test_id)
        assert result["status"] == "completed"
        called_path = mock_httpx.get.call_args.args[0]
        assert strategy_id in called_path
        assert test_id in called_path

    async def test_compare_versions_passes_v1_v2_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """compare_versions passes v1 and v2 as query params."""
        config = _make_config(monkeypatch)
        strategy_id = "strat-cmp"
        mock_httpx = AsyncMock()
        mock_httpx.get.return_value = _mock_response({"verdict": "v2 is better"})
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            client = PlatformRESTClient(config)
            result = await client.compare_versions(strategy_id, v1=1, v2=2)
        assert result["verdict"] == "v2 is better"
        params = mock_httpx.get.call_args.kwargs.get("params")
        assert params == {"v1": 1, "v2": 2}


# ---------------------------------------------------------------------------
# get_rest_tools — factory and tool error handling
# ---------------------------------------------------------------------------


class TestGetRestTools:
    """Tests for the get_rest_tools() factory function."""

    def test_returns_list_of_callables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_rest_tools() returns a list of callable functions."""
        config = _make_config(monkeypatch)
        with patch("httpx.AsyncClient"):
            tools = get_rest_tools(config)
        assert isinstance(tools, list)
        for t in tools:
            assert callable(t)

    def test_returns_eleven_tools(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_rest_tools() returns exactly 11 tool functions."""
        config = _make_config(monkeypatch)
        with patch("httpx.AsyncClient"):
            tools = get_rest_tools(config)
        assert len(tools) == 11

    def test_expected_tool_names_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returned tools have the expected function names."""
        config = _make_config(monkeypatch)
        with patch("httpx.AsyncClient"):
            tools = get_rest_tools(config)
        names = {t.__name__ for t in tools}
        expected = {
            "create_backtest",
            "start_backtest",
            "step_backtest_batch",
            "backtest_trade",
            "get_backtest_results",
            "get_backtest_candles",
            "create_strategy",
            "test_strategy",
            "get_test_results",
            "create_strategy_version",
            "compare_strategy_versions",
        }
        assert names == expected

    async def test_create_backtest_tool_returns_error_on_http_status_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """create_backtest tool returns {'error': '...'} on HTTPStatusError."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        bad_resp = _mock_response({}, status_code=400)
        mock_httpx.post.return_value = bad_resp
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            tools = get_rest_tools(config)
        tool_map = {t.__name__: t for t in tools}

        result = await tool_map["create_backtest"](
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-03-01T00:00:00Z",
            symbols=["BTCUSDT"],
        )

        assert "error" in result

    async def test_start_backtest_tool_returns_error_on_request_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """start_backtest tool returns {'error': '...'} on network RequestError."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.post.side_effect = httpx.ConnectError("connection refused")
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            tools = get_rest_tools(config)
        tool_map = {t.__name__: t for t in tools}

        result = await tool_map["start_backtest"](session_id="sess-abc")

        assert "error" in result

    async def test_create_strategy_tool_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """create_strategy tool returns the parsed response dict on success."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.post.return_value = _mock_response({"strategy_id": "strat-999"})
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            tools = get_rest_tools(config)
        tool_map = {t.__name__: t for t in tools}

        result = await tool_map["create_strategy"](
            name="Test Strategy",
            description="A test strategy",
            definition={"pairs": ["BTCUSDT"], "timeframe": "1h",
                         "entry_conditions": {}, "exit_conditions": {}},
        )

        assert result == {"strategy_id": "strat-999"}

    async def test_get_backtest_results_tool_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_backtest_results tool returns the results dict on success."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.get.return_value = _mock_response({"session_id": "sess-ok", "status": "completed"})
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            tools = get_rest_tools(config)
        tool_map = {t.__name__: t for t in tools}

        result = await tool_map["get_backtest_results"](session_id="sess-ok")

        assert result["status"] == "completed"

    async def test_compare_strategy_versions_tool_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """compare_strategy_versions returns {'error': '...'} on 404."""
        config = _make_config(monkeypatch)
        mock_httpx = AsyncMock()
        mock_httpx.get.return_value = _mock_response({}, status_code=404)
        with patch("httpx.AsyncClient", return_value=mock_httpx):
            tools = get_rest_tools(config)
        tool_map = {t.__name__: t for t in tools}

        result = await tool_map["compare_strategy_versions"](
            strategy_id="strat-missing", v1=1, v2=2
        )

        assert "error" in result
