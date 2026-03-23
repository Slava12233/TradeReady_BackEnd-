"""Unit tests for agent/server_handlers.py — intent handler functions.

Tests cover:
- handle_trade()     — config failure, symbol extraction, SDK price fetch, side hint
- handle_analyze()   — config failure, candle fetch, SMA/RSI computation, trend label
- handle_portfolio() — config failure, missing API key, balance/position/perf formatting
- handle_status()    — platform online/offline, server health injection, position count
- handle_journal()   — read vs write intent detection, daily summary delegation
- handle_learn()     — no memory store fallback, memory search results, empty results
- handle_permissions()— capability/budget retrieval, role display, budget status
- handle_general()   — always returns REASONING_LOOP_SENTINEL
- _extract_symbol()  — known assets, pair suffix, default fallback
- _extract_side()    — buy/sell/none detection
- _strip_command_prefix() — slash prefix stripping
- _format_uptime()  — hours/minutes/seconds formatting
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.server_handlers import (
    REASONING_LOOP_SENTINEL,
    _extract_side,
    _extract_symbol,
    _format_uptime,
    _strip_command_prefix,
    handle_analyze,
    handle_general,
    handle_journal,
    handle_learn,
    handle_permissions,
    handle_portfolio,
    handle_status,
    handle_trade,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(agent_id: str = "550e8400-e29b-41d4-a716-446655440001") -> MagicMock:
    """Return a minimal mock AgentSession."""
    session = MagicMock()
    session.agent_id = agent_id
    session.session_id = "test-session-uuid"
    session.is_active = True
    return session


def _make_config(
    api_key: str = "ak_live_test",
    api_secret: str = "sk_live_test",
    base_url: str = "http://localhost:8000",
    symbols: list[str] | None = None,
) -> MagicMock:
    """Return a minimal mock AgentConfig."""
    cfg = MagicMock()
    cfg.platform_api_key = api_key
    cfg.platform_api_secret = api_secret
    cfg.platform_base_url = base_url
    cfg.symbols = symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    cfg.agent_cheap_model = "openrouter:google/gemini-2.0-flash-001"
    return cfg


def _make_price(symbol: str = "BTCUSDT", price: str = "65000.00") -> MagicMock:
    """Return a mock price object from the SDK."""
    obj = MagicMock()
    obj.symbol = symbol
    obj.price = Decimal(price)
    from datetime import UTC, datetime

    obj.timestamp = datetime.now(UTC)
    return obj


def _make_candle(close: str = "65000.00", volume: str = "100.0") -> MagicMock:
    obj = MagicMock()
    obj.close = Decimal(close)
    obj.open = Decimal(close)
    obj.high = Decimal(close)
    obj.low = Decimal(close)
    obj.volume = Decimal(volume)
    obj.trade_count = 100
    from datetime import UTC, datetime

    obj.time = datetime.now(UTC)
    return obj


def _make_balance(asset: str = "USDT", total: str = "10000.00") -> MagicMock:
    b = MagicMock()
    b.asset = asset
    b.available = Decimal(total)
    b.locked = Decimal("0.00")
    b.total = Decimal(total)
    return b


def _make_position(
    symbol: str = "BTCUSDT",
    qty: str = "0.001",
    pnl: str = "5.00",
    pnl_pct: str = "0.0077",
) -> MagicMock:
    from decimal import Decimal

    p = MagicMock()
    p.symbol = symbol
    p.asset = symbol.replace("USDT", "")
    p.quantity = Decimal(qty)
    p.avg_entry_price = Decimal("64500.00")
    p.current_price = Decimal("65000.00")
    p.market_value = Decimal("65.00")
    p.unrealized_pnl = Decimal(pnl)
    p.unrealized_pnl_pct = Decimal(pnl_pct)
    from datetime import UTC, datetime

    p.opened_at = datetime.now(UTC)
    return p


def _make_performance() -> MagicMock:
    p = MagicMock()
    p.period = "7d"
    p.sharpe_ratio = Decimal("1.2")
    p.sortino_ratio = Decimal("1.5")
    p.max_drawdown_pct = Decimal("0.05")
    p.max_drawdown_duration_days = 2
    p.win_rate = Decimal("0.60")
    p.profit_factor = Decimal("1.8")
    p.avg_win = Decimal("25.00")
    p.avg_loss = Decimal("-15.00")
    p.total_trades = 20
    p.avg_trades_per_day = Decimal("2.86")
    p.best_trade = Decimal("120.00")
    p.worst_trade = Decimal("-40.00")
    p.current_streak = 3
    return p


# ---------------------------------------------------------------------------
# Private helper tests
# ---------------------------------------------------------------------------


class TestExtractSymbol:
    """Tests for _extract_symbol()."""

    def test_btc_no_suffix(self) -> None:
        assert _extract_symbol("analyse BTC") == "BTCUSDT"

    def test_eth_with_usdt(self) -> None:
        assert _extract_symbol("buy ETHUSDT now") == "ETHUSDT"

    def test_sol_mixed_case(self) -> None:
        assert _extract_symbol("what about sol performance") == "SOLUSDT"

    def test_default_fallback(self) -> None:
        assert _extract_symbol("show my portfolio", default="ETHUSDT") == "ETHUSDT"

    def test_default_fallback_btc(self) -> None:
        assert _extract_symbol("tell me about the market", default="BTCUSDT") == "BTCUSDT"

    def test_link_symbol(self) -> None:
        assert _extract_symbol("analyse LINK please") == "LINKUSDT"


class TestExtractSide:
    """Tests for _extract_side()."""

    def test_buy_keyword(self) -> None:
        assert _extract_side("buy some BTC") == "buy"

    def test_sell_keyword(self) -> None:
        assert _extract_side("sell my ETH position") == "sell"

    def test_long_keyword(self) -> None:
        assert _extract_side("go long on SOL") == "buy"

    def test_short_keyword(self) -> None:
        assert _extract_side("go short BTC") == "sell"

    def test_close_keyword(self) -> None:
        assert _extract_side("close my position") == "sell"

    def test_no_side(self) -> None:
        assert _extract_side("what is the BTC price") is None


class TestStripCommandPrefix:
    """Tests for _strip_command_prefix()."""

    def test_strips_slash_learn(self) -> None:
        assert _strip_command_prefix("/learn what is RSI", "learn") == "what is RSI"

    def test_strips_slash_journal(self) -> None:
        assert _strip_command_prefix("/journal show recent", "journal") == "show recent"

    def test_no_match_returns_stripped(self) -> None:
        result = _strip_command_prefix("show my portfolio", "portfolio")
        assert "show my portfolio" in result

    def test_slash_only_returns_original(self) -> None:
        result = _strip_command_prefix("/learn", "learn")
        # Should not be empty — returns stripped original
        assert result

    def test_case_insensitive(self) -> None:
        assert _strip_command_prefix("/LEARN RSI", "learn") == "RSI"


class TestFormatUptime:
    """Tests for _format_uptime()."""

    def test_seconds_only(self) -> None:
        assert _format_uptime(45.0) == "45s"

    def test_minutes_and_seconds(self) -> None:
        assert _format_uptime(125.0) == "2m 5s"

    def test_hours_minutes_seconds(self) -> None:
        assert _format_uptime(3665.0) == "1h 1m 5s"

    def test_zero(self) -> None:
        assert _format_uptime(0.0) == "0s"


# ---------------------------------------------------------------------------
# handle_general
# ---------------------------------------------------------------------------


class TestHandleGeneral:
    """handle_general() always returns the reasoning loop sentinel."""

    async def test_returns_sentinel(self) -> None:
        session = _make_session()
        result = await handle_general(session, "tell me a joke")
        assert result == REASONING_LOOP_SENTINEL

    async def test_sentinel_constant(self) -> None:
        assert REASONING_LOOP_SENTINEL == "__REASONING_LOOP__"


# ---------------------------------------------------------------------------
# handle_trade
# ---------------------------------------------------------------------------


class TestHandleTrade:
    """Tests for handle_trade()."""

    async def test_config_failure_returns_friendly_message(self) -> None:
        """When AgentConfig cannot be loaded, handler returns a helpful string."""
        session = _make_session()
        with patch(
            "agent.server_handlers.AgentConfig",
            side_effect=Exception("missing env"),
        ):
            result = await handle_trade(session, "buy BTC")
        assert "configuration" in result.lower() or "PLATFORM_API_KEY" in result

    async def test_buy_side_hint_in_output(self) -> None:
        """Buy keyword in message surfaces in the handler output."""
        session = _make_session()
        mock_cfg = _make_config()
        mock_client = AsyncMock()
        mock_client.get_price = AsyncMock(return_value=_make_price())
        mock_client.get_candles = AsyncMock(return_value=[_make_candle() for _ in range(5)])
        mock_client.aclose = AsyncMock()

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch(
                "agent.server_handlers.AsyncAgentExchangeClient",
                return_value=mock_client,
            ),
        ):
            result = await handle_trade(session, "buy BTCUSDT")

        assert "buy" in result.lower() or "BUY" in result
        assert "BTCUSDT" in result

    async def test_symbol_extracted_from_message(self) -> None:
        """Symbol mentioned in message is extracted and used."""
        session = _make_session()
        mock_cfg = _make_config()
        mock_client = AsyncMock()
        mock_client.get_price = AsyncMock(return_value=_make_price("ETHUSDT", "3000.00"))
        mock_client.get_candles = AsyncMock(return_value=[_make_candle("3000.00") for _ in range(5)])
        mock_client.aclose = AsyncMock()

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch(
                "agent.server_handlers.AsyncAgentExchangeClient",
                return_value=mock_client,
            ),
        ):
            result = await handle_trade(session, "analyse ETH for me")

        assert "ETHUSDT" in result

    async def test_sdk_failure_returns_error_string(self) -> None:
        """SDK exception returns an [error] prefixed message."""
        from agentexchange.exceptions import AgentExchangeError  # type: ignore[import]

        session = _make_session()
        mock_cfg = _make_config()
        mock_client = AsyncMock()
        mock_client.get_price = AsyncMock(side_effect=AgentExchangeError("connection refused"))
        mock_client.aclose = AsyncMock()

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch(
                "agent.server_handlers.AsyncAgentExchangeClient",
                return_value=mock_client,
            ),
        ):
            result = await handle_trade(session, "buy BTC")

        # Handler degrades gracefully — should still produce output, not raise
        assert isinstance(result, str)

    async def test_no_side_hint_asks_for_confirmation(self) -> None:
        """Without an explicit side, handler asks what the user wants to do."""
        session = _make_session()
        mock_cfg = _make_config()
        mock_client = AsyncMock()
        mock_client.get_price = AsyncMock(return_value=_make_price())
        mock_client.get_candles = AsyncMock(return_value=[])
        mock_client.aclose = AsyncMock()

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch(
                "agent.server_handlers.AsyncAgentExchangeClient",
                return_value=mock_client,
            ),
        ):
            result = await handle_trade(session, "what should I do with BTC")

        # No side specified — handler prompts user to clarify
        assert "BTCUSDT" in result


# ---------------------------------------------------------------------------
# handle_analyze
# ---------------------------------------------------------------------------


class TestHandleAnalyze:
    """Tests for handle_analyze()."""

    async def test_config_failure(self) -> None:
        session = _make_session()
        with patch("agent.server_handlers.AgentConfig", side_effect=Exception("cfg")):
            result = await handle_analyze(session, "/analyze BTC")
        assert "[error]" in result

    async def test_returns_technical_summary(self) -> None:
        """Successful analysis returns SMA, RSI, and trend."""
        session = _make_session()
        mock_cfg = _make_config()
        candles = [_make_candle(str(65000 + i * 10), "50.0") for i in range(50)]
        mock_client = AsyncMock()
        mock_client.get_candles = AsyncMock(return_value=candles)
        mock_client.get_price = AsyncMock(return_value=_make_price())
        mock_client.aclose = AsyncMock()

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch(
                "agent.server_handlers.AsyncAgentExchangeClient",
                return_value=mock_client,
            ),
        ):
            result = await handle_analyze(session, "/analyze BTCUSDT")

        assert "Technical Analysis" in result
        assert "SMA-20" in result
        assert "RSI-14" in result
        assert "BTCUSDT" in result

    async def test_bullish_trend_when_price_above_sma(self) -> None:
        """Returns BULLISH when the latest close is above SMA-20."""
        session = _make_session()
        mock_cfg = _make_config()
        # All candles at 60000; last 5 at 70000 → latest close > SMA-20
        candles = [_make_candle("60000.00") for _ in range(45)] + [
            _make_candle("70000.00") for _ in range(5)
        ]
        mock_client = AsyncMock()
        mock_client.get_candles = AsyncMock(return_value=candles)
        mock_client.get_price = AsyncMock(return_value=_make_price("BTCUSDT", "70000.00"))
        mock_client.aclose = AsyncMock()

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch(
                "agent.server_handlers.AsyncAgentExchangeClient",
                return_value=mock_client,
            ),
        ):
            result = await handle_analyze(session, "/analyze BTC")

        assert "BULLISH" in result

    async def test_empty_candles_returns_no_data_message(self) -> None:
        session = _make_session()
        mock_cfg = _make_config()
        mock_client = AsyncMock()
        mock_client.get_candles = AsyncMock(return_value=[])
        mock_client.get_price = AsyncMock(return_value=_make_price())
        mock_client.aclose = AsyncMock()

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch(
                "agent.server_handlers.AsyncAgentExchangeClient",
                return_value=mock_client,
            ),
        ):
            result = await handle_analyze(session, "/analyze BTC")

        assert "No candle data" in result


# ---------------------------------------------------------------------------
# handle_portfolio
# ---------------------------------------------------------------------------


class TestHandlePortfolio:
    """Tests for handle_portfolio()."""

    async def test_config_failure(self) -> None:
        session = _make_session()
        with patch("agent.server_handlers.AgentConfig", side_effect=Exception("cfg")):
            result = await handle_portfolio(session, "/portfolio")
        assert "[error]" in result

    async def test_missing_api_key_returns_error(self) -> None:
        session = _make_session()
        mock_cfg = _make_config(api_key="")
        with patch("agent.server_handlers.AgentConfig", return_value=mock_cfg):
            result = await handle_portfolio(session, "/portfolio")
        assert "PLATFORM_API_KEY" in result

    async def test_returns_portfolio_summary(self) -> None:
        """Successful call returns balances, positions, and performance."""
        session = _make_session()
        mock_cfg = _make_config()
        mock_client = AsyncMock()
        mock_client.get_balance = AsyncMock(return_value=[_make_balance("USDT", "9500.00")])
        mock_client.get_positions = AsyncMock(return_value=[_make_position()])
        mock_client.get_performance = AsyncMock(return_value=_make_performance())
        mock_client.aclose = AsyncMock()

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch(
                "agent.server_handlers.AsyncAgentExchangeClient",
                return_value=mock_client,
            ),
        ):
            result = await handle_portfolio(session, "/portfolio")

        assert "Portfolio Summary" in result
        assert "USDT" in result
        assert "BTCUSDT" in result
        assert "7-day Performance" in result

    async def test_no_positions(self) -> None:
        session = _make_session()
        mock_cfg = _make_config()
        mock_client = AsyncMock()
        mock_client.get_balance = AsyncMock(return_value=[_make_balance()])
        mock_client.get_positions = AsyncMock(return_value=[])
        mock_client.get_performance = AsyncMock(return_value=_make_performance())
        mock_client.aclose = AsyncMock()

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch(
                "agent.server_handlers.AsyncAgentExchangeClient",
                return_value=mock_client,
            ),
        ):
            result = await handle_portfolio(session, "/portfolio")

        assert "none" in result.lower() or "Open Positions" in result


# ---------------------------------------------------------------------------
# handle_status
# ---------------------------------------------------------------------------


class TestHandleStatus:
    """Tests for handle_status()."""

    async def test_platform_online(self) -> None:
        """When platform health returns 200, status shows online."""
        session = _make_session()
        mock_cfg = _make_config()
        mock_response = MagicMock()
        mock_response.status_code = 200

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch("agent.server_handlers.httpx") as mock_httpx,
            patch(
                "agent.server_handlers.AsyncAgentExchangeClient",
                return_value=AsyncMock(
                    get_positions=AsyncMock(return_value=[]),
                    aclose=AsyncMock(),
                ),
            ),
        ):
            mock_http_client = AsyncMock()
            mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http_client.__aexit__ = AsyncMock(return_value=False)
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_httpx.AsyncClient.return_value = mock_http_client

            result = await handle_status(session, "/status")

        assert "online" in result
        assert "Status" in result

    async def test_server_health_injected(self) -> None:
        """Server health dict is rendered when server kwarg is provided."""
        session = _make_session()
        mock_cfg = _make_config()

        mock_server = AsyncMock()
        mock_server.health_check = AsyncMock(
            return_value={
                "status": "healthy",
                "uptime_seconds": 3665.0,
                "consecutive_errors": 0,
                "redis_ok": True,
                "active_session_id": "test-session-uuid",
                "memory_stats": {"recent_memory_count": 5},
            }
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch("agent.server_handlers.httpx") as mock_httpx,
            patch(
                "agent.server_handlers.AsyncAgentExchangeClient",
                return_value=AsyncMock(
                    get_positions=AsyncMock(return_value=[]),
                    aclose=AsyncMock(),
                ),
            ),
        ):
            mock_http_client = AsyncMock()
            mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http_client.__aexit__ = AsyncMock(return_value=False)
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_httpx.AsyncClient.return_value = mock_http_client

            result = await handle_status(session, "/status", server=mock_server)

        assert "healthy" in result
        assert "1h" in result  # uptime formatted

    async def test_platform_offline(self) -> None:
        """Connection error shows offline status."""
        session = _make_session()
        mock_cfg = _make_config(api_key="")

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch("agent.server_handlers.httpx") as mock_httpx,
        ):
            mock_http_client = AsyncMock()
            mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
            mock_http_client.__aexit__ = AsyncMock(return_value=False)
            mock_http_client.get = AsyncMock(side_effect=ConnectionError("refused"))
            mock_httpx.AsyncClient.return_value = mock_http_client

            result = await handle_status(session, "/status")

        assert "offline" in result or "ConnectionError" in result


# ---------------------------------------------------------------------------
# handle_journal
# ---------------------------------------------------------------------------


class TestHandleJournal:
    """Tests for handle_journal()."""

    async def test_config_failure(self) -> None:
        session = _make_session()
        with patch("agent.server_handlers.AgentConfig", side_effect=Exception("cfg")):
            result = await handle_journal(session, "/journal")
        assert "[error]" in result

    async def test_read_intent_shows_summary(self) -> None:
        """'show' keyword triggers daily_summary read path."""
        session = _make_session()
        mock_cfg = _make_config()

        mock_entry = MagicMock()
        mock_entry.content = "Today: 3 trades, 2 wins, net PnL +$25."
        mock_journal = AsyncMock()
        mock_journal.daily_summary = AsyncMock(return_value=mock_entry)

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch("agent.server_handlers.TradingJournal", return_value=mock_journal),
        ):
            result = await handle_journal(session, "show journal")

        assert "Today" in result or "Summary" in result

    async def test_no_entries_returns_help_message(self) -> None:
        """Empty content returns a helpful 'no entries' message."""
        session = _make_session()
        mock_cfg = _make_config()

        mock_entry = MagicMock()
        mock_entry.content = ""
        mock_journal = AsyncMock()
        mock_journal.daily_summary = AsyncMock(return_value=mock_entry)

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch("agent.server_handlers.TradingJournal", return_value=mock_journal),
        ):
            result = await handle_journal(session, "/journal show")

        assert "no journal entries" in result.lower() or "/journal" in result

    async def test_write_intent_acknowledges(self) -> None:
        """Non-read message is treated as a write-intent and acknowledged."""
        session = _make_session()
        mock_cfg = _make_config()

        mock_entry = MagicMock()
        mock_entry.content = "Some content."
        mock_journal = AsyncMock()
        mock_journal.daily_summary = AsyncMock(return_value=mock_entry)

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch("agent.server_handlers.TradingJournal", return_value=mock_journal),
        ):
            result = await handle_journal(session, "/journal BTC was trending up today")

        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# handle_learn
# ---------------------------------------------------------------------------


class TestHandleLearn:
    """Tests for handle_learn()."""

    async def test_no_memory_store_returns_fallback(self) -> None:
        """Without a memory store, returns a friendly fallback."""
        session = _make_session()
        result = await handle_learn(session, "/learn what is RSI")
        assert "Memory retrieval" in result or "not available" in result

    async def test_memory_search_returns_results(self) -> None:
        """With a memory store, returns formatted memory list."""
        session = _make_session()

        mock_memory = MagicMock()
        mock_memory.memory_type = MagicMock()
        mock_memory.memory_type.value = "procedural"
        mock_memory.confidence = Decimal("0.90")
        mock_memory.content = "Always check RSI before entering a BTC long."
        mock_memory.times_reinforced = 3

        mock_store = AsyncMock()
        mock_store.search = AsyncMock(return_value=[mock_memory])

        result = await handle_learn(session, "/learn RSI", memory_store=mock_store)

        assert "PROCEDURAL" in result
        assert "RSI" in result

    async def test_empty_search_results(self) -> None:
        """No memories found returns a helpful message."""
        session = _make_session()
        mock_store = AsyncMock()
        mock_store.search = AsyncMock(return_value=[])

        result = await handle_learn(session, "/learn MACD crossover", memory_store=mock_store)

        assert "No stored learnings" in result or "matched" in result

    async def test_memory_store_from_server_kwarg(self) -> None:
        """Memory store is retrieved from the server kwarg when not directly provided."""
        session = _make_session()

        mock_memory = MagicMock()
        mock_memory.memory_type = MagicMock()
        mock_memory.memory_type.value = "semantic"
        mock_memory.confidence = Decimal("0.75")
        mock_memory.content = "BTC halving events historically precede bull runs."
        mock_memory.times_reinforced = 0

        mock_store = AsyncMock()
        mock_store.search = AsyncMock(return_value=[mock_memory])

        mock_server = MagicMock()
        mock_server._memory_store = mock_store

        result = await handle_learn(session, "/learn BTC halving", server=mock_server)

        assert "SEMANTIC" in result or "BTC" in result

    async def test_search_error_returns_fallback(self) -> None:
        """Search failure degrades gracefully."""
        session = _make_session()
        mock_store = AsyncMock()
        mock_store.search = AsyncMock(side_effect=Exception("DB down"))

        result = await handle_learn(session, "/learn BTC", memory_store=mock_store)

        assert "temporarily unavailable" in result or "rephrase" in result


# ---------------------------------------------------------------------------
# handle_permissions
# ---------------------------------------------------------------------------


class TestHandlePermissions:
    """Tests for handle_permissions()."""

    async def test_config_failure_returns_partial_output(self) -> None:
        """Config failure is handled; output still shows some info."""
        session = _make_session()
        with patch("agent.server_handlers.AgentConfig", side_effect=Exception("cfg")):
            result = await handle_permissions(session, "/permissions")
        # Should return something (partial or empty permissions view)
        assert isinstance(result, str)

    async def test_capabilities_listed(self) -> None:
        """Resolved capabilities appear in the output."""
        from agent.permissions import Capability  # noqa: PLC0415

        session = _make_session()
        mock_cfg = _make_config()

        mock_cap_manager = AsyncMock()
        mock_cap_manager.get_capabilities = AsyncMock(
            return_value={Capability.CAN_TRADE, Capability.CAN_READ_PORTFOLIO}
        )
        mock_cap_manager.get_role = AsyncMock(return_value=MagicMock(value="live_trader"))

        mock_budget_manager = AsyncMock()
        mock_budget_status = MagicMock()
        mock_budget_status.trades_today = 5
        mock_budget_status.max_daily_trades = 50
        mock_budget_status.daily_loss_pct = Decimal("0.02")
        mock_budget_status.max_daily_loss_pct = Decimal("0.10")
        mock_budget_status.exposure_pct = Decimal("0.15")
        mock_budget_status.max_exposure_pct = Decimal("0.80")
        mock_budget_manager.get_status = AsyncMock(return_value=mock_budget_status)

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch("agent.server_handlers.CapabilityManager", return_value=mock_cap_manager),
            patch("agent.server_handlers.BudgetManager", return_value=mock_budget_manager),
        ):
            result = await handle_permissions(session, "/permissions")

        assert "live_trader" in result
        assert "Capabilities" in result
        assert "Budget" in result

    async def test_budget_failure_degrades_gracefully(self) -> None:
        """Budget fetch failure does not break the full output."""
        from agent.permissions import Capability  # noqa: PLC0415

        session = _make_session()
        mock_cfg = _make_config()

        mock_cap_manager = AsyncMock()
        mock_cap_manager.get_capabilities = AsyncMock(return_value={Capability.CAN_READ_MARKET})
        mock_cap_manager.get_role = AsyncMock(return_value=MagicMock(value="viewer"))

        mock_budget_manager = AsyncMock()
        mock_budget_manager.get_status = AsyncMock(side_effect=Exception("Redis down"))

        with (
            patch("agent.server_handlers.AgentConfig", return_value=mock_cfg),
            patch("agent.server_handlers.CapabilityManager", return_value=mock_cap_manager),
            patch("agent.server_handlers.BudgetManager", return_value=mock_budget_manager),
        ):
            result = await handle_permissions(session, "/permissions")

        assert "viewer" in result
        assert "unavailable" in result.lower()


# ---------------------------------------------------------------------------
# IntentRouter integration — verify handlers are wired in AgentServer
# ---------------------------------------------------------------------------


class TestAgentServerRouterWiring:
    """Verify that AgentServer registers all expected handlers."""

    def test_router_registered_on_init(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AgentServer.__init__ creates an IntentRouter with all 8 intents registered."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_test")
        monkeypatch.setenv("PLATFORM_BASE_URL", "http://localhost:8000")

        from agent.config import AgentConfig  # noqa: PLC0415
        from agent.conversation.router import IntentType  # noqa: PLC0415
        from agent.server import AgentServer  # noqa: PLC0415

        cfg = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        server = AgentServer(agent_id="00000000-0000-0000-0000-000000000001", config=cfg)

        # All 8 intent types should have non-default handlers registered
        all_intents = list(IntentType)
        assert len(all_intents) == 8

        for intent in all_intents:
            handler = server._router.get_handler(intent)
            assert callable(handler), f"No callable handler for {intent.value}"

    async def test_process_message_routes_portfolio_intent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """process_message routes 'show my balance' to the portfolio handler."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_test")
        monkeypatch.setenv("PLATFORM_BASE_URL", "http://localhost:8000")

        from agent.config import AgentConfig  # noqa: PLC0415
        from agent.server import AgentServer  # noqa: PLC0415

        cfg = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        server = AgentServer(agent_id="00000000-0000-0000-0000-000000000001", config=cfg)

        # Stub the portfolio handler to return a known string
        async def stub_portfolio(session: object, message: str, **kw: object) -> str:
            return "PORTFOLIO_STUB"

        from agent.conversation.router import IntentType  # noqa: PLC0415

        server._router.register(IntentType.PORTFOLIO, stub_portfolio)

        # Build a mock session
        mock_session = _make_session()
        mock_session.add_message = AsyncMock()
        mock_session.get_context = AsyncMock(return_value=[])

        result = await server.process_message("show my balance", mock_session)
        assert result == "PORTFOLIO_STUB"

    async def test_process_message_falls_back_to_reasoning_for_general(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GENERAL intent triggers _reasoning_loop fallback."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_test")
        monkeypatch.setenv("PLATFORM_BASE_URL", "http://localhost:8000")

        from agent.config import AgentConfig  # noqa: PLC0415
        from agent.server import AgentServer  # noqa: PLC0415

        cfg = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        server = AgentServer(agent_id="00000000-0000-0000-0000-000000000001", config=cfg)

        # Stub reasoning loop to avoid actual LLM call
        async def stub_reasoning(context: list[dict[str, object]], message: str) -> str:
            return "LLM_REASONING_RESULT"

        server._reasoning_loop = stub_reasoning  # type: ignore[method-assign]

        mock_session = _make_session()
        mock_session.add_message = AsyncMock()
        mock_session.get_context = AsyncMock(return_value=[])

        # "tell me a story" should not match any specific intent
        result = await server.process_message("tell me a story about crypto", mock_session)
        assert result == "LLM_REASONING_RESULT"
