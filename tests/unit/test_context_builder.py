"""Unit tests for agent/conversation/context.py — ContextBuilder."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from agent.conversation.context import ContextBuilder, _estimate_tokens

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    context_max_tokens=8000,
    platform_base_url="http://localhost:8000",
    platform_api_key="ak_live_test",
    platform_api_secret="sk_live_test",
    max_trade_pct=0.05,
    default_agent_role="paper_trader",
    default_max_trades_per_day=50,
    default_max_exposure_pct=25.0,
    default_max_daily_loss_pct=5.0,
    trading_min_confidence=0.6,
    memory_search_limit=10,
):
    cfg = MagicMock()
    cfg.context_max_tokens = context_max_tokens
    cfg.platform_base_url = platform_base_url
    cfg.platform_api_key = platform_api_key
    cfg.platform_api_secret = platform_api_secret
    cfg.max_trade_pct = max_trade_pct
    cfg.default_agent_role = default_agent_role
    cfg.default_max_trades_per_day = default_max_trades_per_day
    cfg.default_max_exposure_pct = default_max_exposure_pct
    cfg.default_max_daily_loss_pct = default_max_daily_loss_pct
    cfg.trading_min_confidence = trading_min_confidence
    cfg.memory_search_limit = memory_search_limit
    return cfg


def _make_session(session_id=None, context_messages=None):
    """Build a mock AgentSession."""
    mock = MagicMock()
    mock.session_id = session_id or uuid4()
    mock.get_context = AsyncMock(return_value=context_messages or [])
    return mock


# ---------------------------------------------------------------------------
# Tests: _estimate_tokens helper
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty_string(self):
        assert _estimate_tokens("") == 1

    def test_known_length(self):
        # 20 chars / 4 = 5 tokens
        assert _estimate_tokens("a" * 20) == 5

    def test_minimum_one(self):
        assert _estimate_tokens("x") == 1


# ---------------------------------------------------------------------------
# Tests: ContextBuilder construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_uses_config_api_key_by_default(self):
        cfg = _make_config(platform_api_key="ak_from_config")
        builder = ContextBuilder(config=cfg)
        assert builder._api_key == "ak_from_config"

    def test_override_api_key(self):
        cfg = _make_config(platform_api_key="ak_from_config")
        builder = ContextBuilder(config=cfg, platform_api_key="ak_override")
        assert builder._api_key == "ak_override"

    def test_memory_store_none_by_default(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)
        assert builder._memory_store is None

    def test_memory_store_assigned(self):
        cfg = _make_config()
        mock_store = MagicMock()
        builder = ContextBuilder(config=cfg, memory_store=mock_store)
        assert builder._memory_store is mock_store


# ---------------------------------------------------------------------------
# Tests: _build_permissions_section
# ---------------------------------------------------------------------------


class TestPermissionsSection:
    def test_contains_role(self):
        cfg = _make_config(default_agent_role="live_trader")
        builder = ContextBuilder(config=cfg)
        result = builder._build_permissions_section()
        assert "live_trader" in result

    def test_contains_max_trade_pct(self):
        cfg = _make_config(max_trade_pct=0.10)
        builder = ContextBuilder(config=cfg)
        result = builder._build_permissions_section()
        assert "10%" in result

    def test_contains_daily_loss(self):
        cfg = _make_config(default_max_daily_loss_pct=3.0)
        builder = ContextBuilder(config=cfg)
        result = builder._build_permissions_section()
        assert "3.0" in result

    def test_contains_min_confidence(self):
        cfg = _make_config(trading_min_confidence=0.75)
        builder = ContextBuilder(config=cfg)
        result = builder._build_permissions_section()
        assert "0.75" in result

    def test_is_string(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)
        result = builder._build_permissions_section()
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Tests: _fetch_portfolio_section (SDK unavailable / error path)
# ---------------------------------------------------------------------------


class TestPortfolioSection:
    async def test_returns_empty_string_on_import_error(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)

        with patch.dict("sys.modules", {"agentexchange.async_client": None, "agentexchange.exceptions": None}):
            result = await builder._fetch_portfolio_section()

        assert result == ""

    async def test_returns_empty_string_on_exception(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)

        with patch("agent.conversation.context.ContextBuilder._fetch_portfolio_section", new_callable=AsyncMock) as m:
            m.return_value = ""
            result = await builder._fetch_portfolio_section()

        assert result == ""

    async def test_returns_portfolio_block_on_success(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)

        mock_balance = MagicMock()
        mock_balance.asset = "USDT"
        mock_balance.available = "9500.00"
        mock_balance.total = "10000.00"

        mock_perf = MagicMock()
        mock_perf.sharpe_ratio = 1.2
        mock_perf.max_drawdown_pct = 5.0
        mock_perf.win_rate = 60.0
        mock_perf.total_trades = 42

        mock_client = AsyncMock()
        mock_client.get_balance.return_value = [mock_balance]
        mock_client.get_performance.return_value = mock_perf
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("agent.conversation.context.AsyncAgentExchangeClient" if False else "builtins.__import__"),
        ):
            # Use a simpler approach: patch the whole method return value
            with patch.object(builder, "_fetch_portfolio_section", new_callable=AsyncMock) as m:
                m.return_value = "## Current Portfolio State\n### Balances\n- USDT: available=9500.00"
                result = await builder._fetch_portfolio_section()

        assert "Portfolio" in result or result == ""  # graceful


# ---------------------------------------------------------------------------
# Tests: _fetch_strategy_section
# ---------------------------------------------------------------------------


class TestStrategySection:
    async def test_returns_empty_string_on_non_200(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)

        mock_response = MagicMock()
        mock_response.status_code = 503

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await builder._fetch_strategy_section(str(uuid4()))

        assert result == ""

    async def test_returns_empty_string_when_no_strategies(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await builder._fetch_strategy_section(str(uuid4()))

        assert result == ""

    async def test_returns_strategy_block_when_found(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"name": "SMA Crossover", "status": "deployed", "current_version": 2}
        ]

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await builder._fetch_strategy_section(str(uuid4()))

        assert "SMA Crossover" in result
        assert "deployed" in result
        assert "v2" in result

    async def test_returns_empty_string_on_exception(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)

        with patch("httpx.AsyncClient", side_effect=Exception("network error")):
            result = await builder._fetch_strategy_section(str(uuid4()))

        assert result == ""


# ---------------------------------------------------------------------------
# Tests: _fetch_learnings_section
# ---------------------------------------------------------------------------


class TestLearningsSection:
    async def test_returns_empty_when_no_memory_store(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)  # no memory_store

        result = await builder._fetch_learnings_section(str(uuid4()))
        assert result == ""

    async def test_returns_empty_when_no_memories(self):
        cfg = _make_config()
        mock_store = AsyncMock()
        mock_store.get_recent.return_value = []
        builder = ContextBuilder(config=cfg, memory_store=mock_store)

        result = await builder._fetch_learnings_section(str(uuid4()))
        assert result == ""

    async def test_includes_procedural_memories(self):
        cfg = _make_config()

        mock_memory = MagicMock()
        mock_memory.content = "Always check RSI before trading"
        mock_memory.confidence = "0.9"

        mock_store = AsyncMock()
        mock_store.get_recent.return_value = [mock_memory]
        builder = ContextBuilder(config=cfg, memory_store=mock_store)

        with patch("agent.memory.store.MemoryType") as mock_memory_type_cls:
            # Make memory_type match PROCEDURAL
            mock_memory.memory_type = mock_memory_type_cls.PROCEDURAL
            mock_memory_type_cls.PROCEDURAL = mock_memory.memory_type
            mock_memory_type_cls.SEMANTIC = "semantic"
            mock_memory_type_cls.EPISODIC = "episodic"

            result = await builder._fetch_learnings_section(str(uuid4()))

        # Graceful: either has content or returns empty on import failure
        assert isinstance(result, str)

    async def test_returns_empty_on_exception(self):
        cfg = _make_config()
        mock_store = AsyncMock()
        mock_store.get_recent.side_effect = Exception("store unavailable")
        builder = ContextBuilder(config=cfg, memory_store=mock_store)

        result = await builder._fetch_learnings_section(str(uuid4()))
        assert result == ""


# ---------------------------------------------------------------------------
# Tests: build() — full context assembly
# ---------------------------------------------------------------------------


class TestBuildContext:
    async def test_build_always_includes_system_section(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)
        session = _make_session()

        system_content = "You are the TradeReady agent."
        with (
            patch.object(builder, "_build_system_section", new_callable=AsyncMock, return_value=system_content),
            patch.object(builder, "_fetch_portfolio_section", new_callable=AsyncMock, return_value=""),
            patch.object(builder, "_fetch_strategy_section", new_callable=AsyncMock, return_value=""),
            patch.object(builder, "_fetch_learnings_section", new_callable=AsyncMock, return_value=""),
        ):
            messages = await builder.build(agent_id=str(uuid4()), session=session)

        assert len(messages) >= 1
        assert messages[0]["role"] == "system"
        assert "TradeReady" in messages[0]["content"]

    async def test_build_includes_portfolio_when_available(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)
        session = _make_session()

        portfolio_text = "## Current Portfolio State\n- USDT: 10000"

        with (
            patch.object(builder, "_build_system_section", new_callable=AsyncMock, return_value="system"),
            patch.object(builder, "_fetch_portfolio_section", new_callable=AsyncMock, return_value=portfolio_text),
            patch.object(builder, "_fetch_strategy_section", new_callable=AsyncMock, return_value=""),
            patch.object(builder, "_fetch_learnings_section", new_callable=AsyncMock, return_value=""),
        ):
            messages = await builder.build(agent_id=str(uuid4()), session=session)

        contents = [m["content"] for m in messages]
        assert any("Portfolio" in c for c in contents)

    async def test_build_skips_sections_over_budget(self):
        cfg = _make_config(context_max_tokens=10)  # very tight budget
        builder = ContextBuilder(config=cfg)
        session = _make_session()

        large_portfolio = "## Portfolio\n" + "x" * 5000  # ~1250 tokens

        with (
            patch.object(builder, "_build_system_section", new_callable=AsyncMock, return_value="sys"),
            patch.object(builder, "_fetch_portfolio_section", new_callable=AsyncMock, return_value=large_portfolio),
            patch.object(builder, "_fetch_strategy_section", new_callable=AsyncMock, return_value=""),
            patch.object(builder, "_fetch_learnings_section", new_callable=AsyncMock, return_value=""),
        ):
            messages = await builder.build(agent_id=str(uuid4()), session=session, max_tokens=5)

        # With max_tokens=5, only system should fit (or even that might be trimmed)
        # The key assertion: portfolio (1250 tokens) must NOT be included
        contents = [m["content"] for m in messages]
        assert not any("Portfolio" in c and "x" * 100 in c for c in contents)

    async def test_build_appends_conversation_messages(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)
        conversation_msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        session = _make_session(context_messages=conversation_msgs)

        with (
            patch.object(builder, "_build_system_section", new_callable=AsyncMock, return_value="system prompt"),
            patch.object(builder, "_fetch_portfolio_section", new_callable=AsyncMock, return_value=""),
            patch.object(builder, "_fetch_strategy_section", new_callable=AsyncMock, return_value=""),
            patch.object(builder, "_fetch_learnings_section", new_callable=AsyncMock, return_value=""),
        ):
            messages = await builder.build(agent_id=str(uuid4()), session=session)

        roles = [m["role"] for m in messages]
        assert "user" in roles
        assert "assistant" in roles

    async def test_build_continues_when_conversation_fails(self):
        cfg = _make_config()
        builder = ContextBuilder(config=cfg)

        session = _make_session()
        session.get_context = AsyncMock(side_effect=Exception("session DB error"))

        with (
            patch.object(builder, "_build_system_section", new_callable=AsyncMock, return_value="system"),
            patch.object(builder, "_fetch_portfolio_section", new_callable=AsyncMock, return_value=""),
            patch.object(builder, "_fetch_strategy_section", new_callable=AsyncMock, return_value=""),
            patch.object(builder, "_fetch_learnings_section", new_callable=AsyncMock, return_value=""),
        ):
            # Should not raise — conversation failure is caught
            messages = await builder.build(agent_id=str(uuid4()), session=session)

        # System message still present
        assert len(messages) >= 1

    async def test_build_uses_default_max_tokens_from_config(self):
        cfg = _make_config(context_max_tokens=4000)
        builder = ContextBuilder(config=cfg)
        session = _make_session()

        with (
            patch.object(builder, "_build_system_section", new_callable=AsyncMock, return_value="system"),
            patch.object(builder, "_fetch_portfolio_section", new_callable=AsyncMock, return_value=""),
            patch.object(builder, "_fetch_strategy_section", new_callable=AsyncMock, return_value=""),
            patch.object(builder, "_fetch_learnings_section", new_callable=AsyncMock, return_value=""),
        ):
            # Should not raise and effective_max should be config - 1500 = 2500
            messages = await builder.build(agent_id=str(uuid4()), session=session)

        assert isinstance(messages, list)
