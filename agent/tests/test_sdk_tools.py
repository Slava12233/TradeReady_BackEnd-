"""Tests for agent/tools/sdk_tools.py :: get_sdk_tools and individual tool functions."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.config import AgentConfig

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    """Build an AgentConfig with required env vars set."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_test")
    monkeypatch.setenv("PLATFORM_API_SECRET", "sk_live_test")
    monkeypatch.setenv("PLATFORM_BASE_URL", "http://localhost:8000")
    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _make_ctx() -> MagicMock:
    """Return a dummy Pydantic AI run context object."""
    return MagicMock()


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


# ---------------------------------------------------------------------------
# get_sdk_tools structure
# ---------------------------------------------------------------------------


class TestGetSdkToolsStructure:
    """Tests for the get_sdk_tools() factory function."""

    def test_returns_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_sdk_tools() returns a list."""
        config = _make_config(monkeypatch)
        with patch("agentexchange.async_client.AsyncAgentExchangeClient"):
            from agent.tools.sdk_tools import get_sdk_tools

            tools = get_sdk_tools(config)
        assert isinstance(tools, list)

    def test_returns_seven_callables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_sdk_tools() returns exactly 7 callable tool functions."""
        config = _make_config(monkeypatch)
        with patch("agentexchange.async_client.AsyncAgentExchangeClient"):
            from agent.tools.sdk_tools import get_sdk_tools

            tools = get_sdk_tools(config)
        assert len(tools) == 7
        for tool in tools:
            assert callable(tool)

    def test_tool_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returned tools have the expected function names."""
        config = _make_config(monkeypatch)
        with patch("agentexchange.async_client.AsyncAgentExchangeClient"):
            from agent.tools.sdk_tools import get_sdk_tools

            tools = get_sdk_tools(config)
        names = {t.__name__ for t in tools}
        assert names == {
            "get_price",
            "get_candles",
            "get_balance",
            "get_positions",
            "get_performance",
            "get_trade_history",
            "place_market_order",
        }


# ---------------------------------------------------------------------------
# get_price
# ---------------------------------------------------------------------------


class TestGetPrice:
    """Tests for the get_price tool function."""

    def _setup(self, monkeypatch: pytest.MonkeyPatch):
        """Create config + mock client and return (tools_dict, mock_client)."""
        config = _make_config(monkeypatch)
        mock_client = AsyncMock()

        with patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=mock_client):
            from agent.tools.sdk_tools import get_sdk_tools

            tools = get_sdk_tools(config)

        tool_map = {t.__name__: t for t in tools}
        return tool_map, mock_client

    async def test_returns_correct_dict_structure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_price returns dict with symbol, price, and timestamp keys."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_result = MagicMock()
        mock_result.symbol = "BTCUSDT"
        mock_result.price = Decimal("64521.30")
        mock_result.timestamp = _utcnow()
        mock_client.get_price.return_value = mock_result

        result = await tool_map["get_price"](_make_ctx(), "BTCUSDT")

        assert result["symbol"] == "BTCUSDT"
        assert result["price"] == "64521.30"
        assert "timestamp" in result

    async def test_error_handling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_price returns {'error': '...'} when SDK raises AgentExchangeError."""
        from agentexchange.exceptions import AgentExchangeError

        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_price.side_effect = AgentExchangeError("symbol not found")

        result = await tool_map["get_price"](_make_ctx(), "INVALID")

        assert "error" in result
        assert "symbol not found" in result["error"]

    async def test_calls_sdk_with_correct_symbol(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_price calls client.get_price with the supplied symbol."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_result = MagicMock()
        mock_result.symbol = "ETHUSDT"
        mock_result.price = Decimal("3100.00")
        mock_result.timestamp = _utcnow()
        mock_client.get_price.return_value = mock_result

        await tool_map["get_price"](_make_ctx(), "ETHUSDT")

        mock_client.get_price.assert_called_once_with("ETHUSDT")


# ---------------------------------------------------------------------------
# get_candles
# ---------------------------------------------------------------------------


class TestGetCandles:
    """Tests for the get_candles tool function."""

    def _setup(self, monkeypatch: pytest.MonkeyPatch):
        config = _make_config(monkeypatch)
        mock_client = AsyncMock()
        with patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=mock_client):
            from agent.tools.sdk_tools import get_sdk_tools

            tools = get_sdk_tools(config)
        return {t.__name__: t for t in tools}, mock_client

    def _make_candle(self) -> MagicMock:
        c = MagicMock()
        c.time = _utcnow()
        c.open = Decimal("60000.00")
        c.high = Decimal("61000.00")
        c.low = Decimal("59000.00")
        c.close = Decimal("60500.00")
        c.volume = Decimal("100.5")
        c.trade_count = 250
        return c

    async def test_returns_list_of_dicts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_candles returns a list of OHLCV dicts on success."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_candles.return_value = [self._make_candle(), self._make_candle()]

        result = await tool_map["get_candles"](_make_ctx(), "BTCUSDT")

        assert isinstance(result, list)
        assert len(result) == 2
        assert "open" in result[0]
        assert "close" in result[0]
        assert result[0]["trade_count"] == 250

    async def test_candle_values_are_strings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Decimal price fields are converted to strings in the output."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_candles.return_value = [self._make_candle()]

        result = await tool_map["get_candles"](_make_ctx(), "BTCUSDT")

        assert isinstance(result[0]["open"], str)
        assert isinstance(result[0]["volume"], str)

    async def test_error_returns_error_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_candles returns {'error': '...'} when SDK raises."""
        from agentexchange.exceptions import AgentExchangeError

        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_candles.side_effect = AgentExchangeError("no candle data")

        result = await tool_map["get_candles"](_make_ctx(), "BTCUSDT")

        assert isinstance(result, dict)
        assert "error" in result

    async def test_passes_interval_and_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_candles forwards interval and limit to the SDK client."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_candles.return_value = []

        await tool_map["get_candles"](_make_ctx(), "SOLUSDT", interval="4h", limit=100)

        mock_client.get_candles.assert_called_once_with("SOLUSDT", interval="4h", limit=100)


# ---------------------------------------------------------------------------
# get_balance
# ---------------------------------------------------------------------------


class TestGetBalance:
    """Tests for the get_balance tool function."""

    def _setup(self, monkeypatch: pytest.MonkeyPatch):
        config = _make_config(monkeypatch)
        mock_client = AsyncMock()
        with patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=mock_client):
            from agent.tools.sdk_tools import get_sdk_tools

            tools = get_sdk_tools(config)
        return {t.__name__: t for t in tools}, mock_client

    def _make_balance_item(self, asset: str = "USDT") -> MagicMock:
        b = MagicMock()
        b.asset = asset
        b.available = Decimal("9500.00")
        b.locked = Decimal("500.00")
        b.total = Decimal("10000.00")
        return b

    async def test_returns_list_of_balance_dicts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_balance returns a list of balance dicts."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_balance.return_value = [self._make_balance_item("USDT"), self._make_balance_item("BTC")]

        result = await tool_map["get_balance"](_make_ctx())

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["asset"] == "USDT"
        assert result[0]["available"] == "9500.00"

    async def test_balance_values_are_strings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Decimal balance fields are serialised as strings."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_balance.return_value = [self._make_balance_item()]

        result = await tool_map["get_balance"](_make_ctx())

        assert isinstance(result[0]["total"], str)

    async def test_error_returns_error_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_balance returns {'error': '...'} when SDK raises."""
        from agentexchange.exceptions import AgentExchangeError

        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_balance.side_effect = AgentExchangeError("unauthorized")

        result = await tool_map["get_balance"](_make_ctx())

        assert isinstance(result, dict)
        assert "error" in result


# ---------------------------------------------------------------------------
# get_positions
# ---------------------------------------------------------------------------


class TestGetPositions:
    """Tests for the get_positions tool function."""

    def _setup(self, monkeypatch: pytest.MonkeyPatch):
        config = _make_config(monkeypatch)
        mock_client = AsyncMock()
        with patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=mock_client):
            from agent.tools.sdk_tools import get_sdk_tools

            tools = get_sdk_tools(config)
        return {t.__name__: t for t in tools}, mock_client

    def _make_position(self) -> MagicMock:
        p = MagicMock()
        p.symbol = "BTCUSDT"
        p.asset = "BTC"
        p.quantity = Decimal("0.01")
        p.avg_entry_price = Decimal("60000.00")
        p.current_price = Decimal("62000.00")
        p.market_value = Decimal("620.00")
        p.unrealized_pnl = Decimal("20.00")
        p.unrealized_pnl_pct = Decimal("0.0333")
        p.opened_at = _utcnow()
        return p

    async def test_returns_list_of_position_dicts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_positions returns a list of position dicts on success."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_positions.return_value = [self._make_position()]

        result = await tool_map["get_positions"](_make_ctx())

        assert isinstance(result, list)
        assert result[0]["symbol"] == "BTCUSDT"
        assert "unrealized_pnl" in result[0]
        assert "opened_at" in result[0]

    async def test_error_returns_error_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_positions returns {'error': '...'} on SDK failure."""
        from agentexchange.exceptions import AgentExchangeError

        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_positions.side_effect = AgentExchangeError("session expired")

        result = await tool_map["get_positions"](_make_ctx())

        assert "error" in result


# ---------------------------------------------------------------------------
# get_performance
# ---------------------------------------------------------------------------


class TestGetPerformance:
    """Tests for the get_performance tool function."""

    def _setup(self, monkeypatch: pytest.MonkeyPatch):
        config = _make_config(monkeypatch)
        mock_client = AsyncMock()
        with patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=mock_client):
            from agent.tools.sdk_tools import get_sdk_tools

            tools = get_sdk_tools(config)
        return {t.__name__: t for t in tools}, mock_client

    def _make_perf(self) -> MagicMock:
        p = MagicMock()
        p.period = "all"
        p.sharpe_ratio = Decimal("1.25")
        p.sortino_ratio = Decimal("1.80")
        p.max_drawdown_pct = Decimal("0.12")
        p.max_drawdown_duration_days = 5
        p.win_rate = Decimal("0.58")
        p.profit_factor = Decimal("1.40")
        p.avg_win = Decimal("45.00")
        p.avg_loss = Decimal("22.00")
        p.total_trades = 100
        p.avg_trades_per_day = Decimal("2.5")
        p.best_trade = Decimal("200.00")
        p.worst_trade = Decimal("-80.00")
        p.current_streak = 3
        return p

    async def test_returns_performance_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_performance returns a dict with expected keys."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_performance.return_value = self._make_perf()

        result = await tool_map["get_performance"](_make_ctx())

        assert isinstance(result, dict)
        assert result["period"] == "all"
        assert "sharpe_ratio" in result
        assert "win_rate" in result
        assert result["total_trades"] == 100
        assert result["current_streak"] == 3

    async def test_passes_period_to_sdk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_performance forwards the period argument to the SDK client."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_performance.return_value = self._make_perf()

        await tool_map["get_performance"](_make_ctx(), period="7d")

        mock_client.get_performance.assert_called_once_with(period="7d")

    async def test_error_returns_error_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_performance returns {'error': '...'} on SDK failure."""
        from agentexchange.exceptions import AgentExchangeError

        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_performance.side_effect = AgentExchangeError("rate limited")

        result = await tool_map["get_performance"](_make_ctx())

        assert "error" in result


# ---------------------------------------------------------------------------
# get_trade_history
# ---------------------------------------------------------------------------


class TestGetTradeHistory:
    """Tests for the get_trade_history tool function."""

    def _setup(self, monkeypatch: pytest.MonkeyPatch):
        config = _make_config(monkeypatch)
        mock_client = AsyncMock()
        with patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=mock_client):
            from agent.tools.sdk_tools import get_sdk_tools

            tools = get_sdk_tools(config)
        return {t.__name__: t for t in tools}, mock_client

    def _make_trade(self) -> MagicMock:
        t = MagicMock()
        t.trade_id = uuid4()
        t.order_id = uuid4()
        t.symbol = "BTCUSDT"
        t.side = "buy"
        t.quantity = Decimal("0.01")
        t.price = Decimal("60000.00")
        t.fee = Decimal("0.60")
        t.total = Decimal("600.60")
        t.executed_at = _utcnow()
        return t

    async def test_returns_list_of_trade_dicts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_trade_history returns a list of trade dicts on success."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_trade_history.return_value = [self._make_trade(), self._make_trade()]

        result = await tool_map["get_trade_history"](_make_ctx())

        assert isinstance(result, list)
        assert len(result) == 2
        assert "trade_id" in result[0]
        assert "executed_at" in result[0]

    async def test_error_returns_error_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_trade_history returns {'error': '...'} on SDK failure."""
        from agentexchange.exceptions import AgentExchangeError

        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.get_trade_history.side_effect = AgentExchangeError("unauthorized")

        result = await tool_map["get_trade_history"](_make_ctx())

        assert "error" in result


# ---------------------------------------------------------------------------
# place_market_order
# ---------------------------------------------------------------------------


class TestPlaceMarketOrder:
    """Tests for the place_market_order tool function."""

    def _setup(self, monkeypatch: pytest.MonkeyPatch):
        config = _make_config(monkeypatch)
        mock_client = AsyncMock()
        with patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=mock_client):
            from agent.tools.sdk_tools import get_sdk_tools

            tools = get_sdk_tools(config)
        return {t.__name__: t for t in tools}, mock_client

    def _make_order(self, filled: bool = True) -> MagicMock:
        o = MagicMock()
        o.order_id = uuid4()
        o.status = "filled" if filled else "pending"
        o.symbol = "BTCUSDT"
        o.side = "buy"
        o.type = "market"
        o.executed_price = Decimal("60100.00") if filled else None
        o.executed_quantity = Decimal("0.01") if filled else None
        o.fee = Decimal("0.60") if filled else None
        o.total_cost = Decimal("601.60") if filled else None
        o.filled_at = _utcnow() if filled else None
        return o

    async def test_returns_order_dict_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """place_market_order returns an order dict with all expected keys."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.place_market_order.return_value = self._make_order()

        result = await tool_map["place_market_order"](_make_ctx(), "BTCUSDT", "buy", "0.01")

        assert result["status"] == "filled"
        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "buy"
        assert "executed_price" in result
        assert result["executed_price"] is not None

    async def test_none_fields_serialise_as_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Optional fields that are None are returned as None (not missing)."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.place_market_order.return_value = self._make_order(filled=False)

        result = await tool_map["place_market_order"](_make_ctx(), "BTCUSDT", "buy", "0.01")

        assert result["executed_price"] is None
        assert result["filled_at"] is None

    async def test_error_returns_error_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """place_market_order returns {'error': '...'} on SDK failure."""
        from agentexchange.exceptions import AgentExchangeError

        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.place_market_order.side_effect = AgentExchangeError("insufficient balance")

        result = await tool_map["place_market_order"](_make_ctx(), "BTCUSDT", "buy", "99999")

        assert "error" in result
        assert "insufficient balance" in result["error"]

    async def test_calls_sdk_with_correct_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """place_market_order passes symbol, side, quantity through to SDK."""
        tool_map, mock_client = self._setup(monkeypatch)
        mock_client.place_market_order.return_value = self._make_order()

        await tool_map["place_market_order"](_make_ctx(), "ETHUSDT", "sell", "0.5")

        mock_client.place_market_order.assert_called_once_with("ETHUSDT", "sell", "0.5")
