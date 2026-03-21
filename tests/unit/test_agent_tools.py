"""Tests for agent/tools/agent_tools.py — all 5 enhanced agent tools.

Tests cover:
- reflect_on_trade: successful reflection, trade not found, incomplete trade (no exit)
- review_portfolio: healthy portfolio, concentrated portfolio, empty portfolio
- scan_opportunities: matches found, no matches, criteria edge cases
- journal_entry: normal entry, auto-tagging, market context capture
- request_platform_feature: new request, duplicate detection, category/priority mapping

All external dependencies (SDK client, Redis, DB sessions, repos) are mocked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Patch path constants (kept short so patch() calls stay under 120 chars)
# ---------------------------------------------------------------------------

_SESSION_FACTORY = "src.database.session.get_session_factory"
_OBS_REPO = (
    "src.database.repositories.agent_observation_repo"
    ".AgentObservationRepository"
)
_JOURNAL_REPO = (
    "src.database.repositories.agent_journal_repo"
    ".AgentJournalRepository"
)
_LEARNING_REPO = (
    "src.database.repositories.agent_learning_repo"
    ".AgentLearningRepository"
)
_BUDGET_REPO = (
    "src.database.repositories.agent_budget_repo"
    ".AgentBudgetRepository"
)
_BUDGET_NOT_FOUND = (
    "src.database.repositories.agent_budget_repo"
    ".AgentBudgetNotFoundError"
)
_FEEDBACK_REPO = (
    "src.database.repositories.agent_feedback_repo"
    ".AgentFeedbackRepository"
)
_AGENT_JOURNAL_MODEL = "src.database.models.AgentJournal"
_AGENT_LEARNING_MODEL = "src.database.models.AgentLearning"
_AGENT_FEEDBACK_MODEL = "src.database.models.AgentFeedback"
_DB_ERROR = "src.utils.exceptions.DatabaseError"
_REDIS_CLIENT = "src.cache.redis_client.get_redis_client"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build a minimal AgentConfig with required env vars."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_test")
    monkeypatch.setenv("PLATFORM_API_SECRET", "sk_live_test")
    monkeypatch.setenv("PLATFORM_BASE_URL", "http://localhost:8000")
    from agent.config import AgentConfig

    return AgentConfig(_env_file=None)  # type: ignore[call-arg]


def _make_ctx() -> MagicMock:
    """Return a dummy Pydantic AI run context object."""
    return MagicMock()


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _make_trade_obj(
    trade_id: str | None = None,
    symbol: str = "BTCUSDT",
    side: str = "buy",
    quantity: str = "0.01",
    price: str = "60000.00",
    fee: str = "0.60",
    total: str = "600.60",
) -> MagicMock:
    """Build a mock SDK trade response object."""
    t = MagicMock()
    t.trade_id = trade_id or str(uuid4())
    t.symbol = symbol
    t.side = side
    t.quantity = Decimal(quantity)
    t.price = Decimal(price)
    t.fee = Decimal(fee)
    t.total = Decimal(total)
    t.executed_at = _utcnow()
    return t


def _make_price_obj(symbol: str = "BTCUSDT", price: str = "61000.00") -> MagicMock:
    """Build a mock SDK price response object."""
    p = MagicMock()
    p.symbol = symbol
    p.price = Decimal(price)
    p.timestamp = _utcnow()
    return p


def _make_candle_obj() -> MagicMock:
    """Build a mock SDK candle response object."""
    c = MagicMock()
    c.open = Decimal("60000.00")
    c.high = Decimal("62000.00")
    c.low = Decimal("59000.00")
    c.close = Decimal("61000.00")
    c.volume = Decimal("100.50")
    c.trade_count = 300
    c.time = _utcnow()
    return c


def _make_balance_obj(asset: str = "USDT", total: str = "10000.00") -> MagicMock:
    """Build a mock SDK balance response object."""
    b = MagicMock()
    b.asset = asset
    b.available = Decimal(total)
    b.locked = Decimal("0")
    b.total = Decimal(total)
    return b


def _make_position_obj(
    symbol: str = "BTCUSDT",
    market_value: str = "500.00",
    unrealized_pnl: str = "10.00",
) -> MagicMock:
    """Build a mock SDK position response object."""
    p = MagicMock()
    p.symbol = symbol
    p.market_value = Decimal(market_value)
    p.unrealized_pnl = Decimal(unrealized_pnl)
    return p


def _make_mock_sdk_client() -> AsyncMock:
    """Return an AsyncMock SDK client with sensible defaults."""
    mock_client = AsyncMock()
    mock_client.get_trade_history.return_value = []
    mock_client.get_price.return_value = _make_price_obj()
    mock_client.get_candles.return_value = [_make_candle_obj()]
    mock_client.get_balance.return_value = [_make_balance_obj()]
    mock_client.get_positions.return_value = []
    return mock_client


def _build_tools(mock_client: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch SDK client, open_session, DB imports; return tool map."""
    config = _make_config(monkeypatch)
    agent_id = str(uuid4())

    with (
        patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=mock_client),
        patch("agentexchange.exceptions.AgentExchangeError", Exception),
    ):
        from agent.tools.agent_tools import get_agent_tools

        tools = get_agent_tools(config, agent_id=agent_id)

    return {t.__name__: t for t in tools}, agent_id


# ---------------------------------------------------------------------------
# TestReflectOnTrade
# ---------------------------------------------------------------------------


class TestReflectOnTrade:
    """Tests for the reflect_on_trade tool."""

    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, AsyncMock, str]:
        """Return (tool_fn, mock_sdk_client, agent_id)."""
        mock_client = _make_mock_sdk_client()
        tool_map, agent_id = _build_tools(mock_client, monkeypatch)
        return tool_map["reflect_on_trade"], mock_client, agent_id

    async def test_successful_reflection_returns_trade_reflection_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """reflect_on_trade returns a TradeReflection dict when trade is found."""
        tool_fn, mock_client, agent_id = self._setup(monkeypatch)

        trade_id = str(uuid4())
        entry_trade = _make_trade_obj(trade_id=trade_id, side="buy", price="60000.00")
        exit_trade = _make_trade_obj(symbol="BTCUSDT", side="sell", price="62000.00")
        # entry_trade at index 1; exit_trade at index 0 (more recent)
        mock_client.get_trade_history.return_value = [exit_trade, entry_trade]
        mock_client.get_price.return_value = _make_price_obj(price="61000.00")

        # Patch DB interactions so they succeed silently
        mock_session = AsyncMock()
        mock_journal_repo = AsyncMock()
        mock_learning_repo = AsyncMock()
        mock_obs_repo = AsyncMock()
        mock_obs_repo.get_range.return_value = []

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(_OBS_REPO, return_value=mock_obs_repo),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_LEARNING_REPO, return_value=mock_learning_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_AGENT_LEARNING_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx(), trade_id)

        assert "error" not in result
        assert result["trade_id"] == trade_id
        assert result["symbol"] == "BTCUSDT"
        assert result["entry_quality"] in ("good", "neutral", "poor")
        assert result["exit_quality"] in ("good", "neutral", "poor")
        assert "pnl" in result
        assert "learnings" in result
        assert isinstance(result["learnings"], list)
        assert "would_take_again" in result

    async def test_trade_not_found_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """reflect_on_trade returns error dict when trade_id is not in history."""
        tool_fn, mock_client, _agent_id = self._setup(monkeypatch)

        # Trade history contains trades with different IDs
        mock_client.get_trade_history.return_value = [
            _make_trade_obj(trade_id=str(uuid4())),
            _make_trade_obj(trade_id=str(uuid4())),
        ]

        result = await tool_fn(_make_ctx(), "nonexistent-trade-id-999")

        assert "error" in result
        assert "not found" in result["error"].lower()

    async def test_incomplete_trade_no_exit_returns_neutral_quality(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """reflect_on_trade handles open position (no exit trade) gracefully."""
        tool_fn, mock_client, _agent_id = self._setup(monkeypatch)

        trade_id = str(uuid4())
        # Only entry trade, no exit
        mock_client.get_trade_history.return_value = [
            _make_trade_obj(trade_id=trade_id, side="buy"),
        ]
        mock_client.get_price.return_value = _make_price_obj(price="59000.00")

        mock_session = AsyncMock()
        mock_journal_repo = AsyncMock()
        mock_learning_repo = AsyncMock()
        mock_obs_repo = AsyncMock()
        mock_obs_repo.get_range.return_value = []

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(_OBS_REPO, return_value=mock_obs_repo),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_LEARNING_REPO, return_value=mock_learning_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_AGENT_LEARNING_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx(), trade_id)

        assert "error" not in result
        assert result["entry_quality"] == "neutral"
        assert result["exit_quality"] == "neutral"
        # Learnings should mention no matched exit trade
        assert any("no matched exit" in item.lower() for item in result["learnings"])

    async def test_sdk_error_returns_error_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """reflect_on_trade returns error dict when SDK raises."""
        tool_fn, mock_client, _agent_id = self._setup(monkeypatch)

        from agentexchange.exceptions import AgentExchangeError

        mock_client.get_trade_history.side_effect = AgentExchangeError("connection refused")

        result = await tool_fn(_make_ctx(), "any-trade-id")

        assert "error" in result

    async def test_profitable_trade_generates_positive_learning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Profitable trade produces would_take_again=True and positive learnings."""
        tool_fn, mock_client, _agent_id = self._setup(monkeypatch)

        trade_id = str(uuid4())
        entry_trade = _make_trade_obj(trade_id=trade_id, side="buy", price="50000.00", fee="0.50")
        exit_trade = _make_trade_obj(symbol="BTCUSDT", side="sell", price="55000.00")
        mock_client.get_trade_history.return_value = [exit_trade, entry_trade]
        mock_client.get_price.return_value = _make_price_obj(price="54000.00")

        mock_session = AsyncMock()
        mock_journal_repo = AsyncMock()
        mock_learning_repo = AsyncMock()
        mock_obs_repo = AsyncMock()
        mock_obs_repo.get_range.return_value = []

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(_OBS_REPO, return_value=mock_obs_repo),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_LEARNING_REPO, return_value=mock_learning_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_AGENT_LEARNING_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx(), trade_id)

        assert result["would_take_again"] is True
        assert result["entry_quality"] == "good"

    async def test_losing_trade_sets_would_take_again_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Losing trade produces would_take_again=False and improvement_notes."""
        tool_fn, mock_client, _agent_id = self._setup(monkeypatch)

        trade_id = str(uuid4())
        entry_trade = _make_trade_obj(trade_id=trade_id, side="buy", price="65000.00", fee="0.65")
        exit_trade = _make_trade_obj(symbol="BTCUSDT", side="sell", price="60000.00")
        mock_client.get_trade_history.return_value = [exit_trade, entry_trade]
        mock_client.get_price.return_value = _make_price_obj(price="59000.00")

        mock_session = AsyncMock()
        mock_journal_repo = AsyncMock()
        mock_learning_repo = AsyncMock()
        mock_obs_repo = AsyncMock()
        mock_obs_repo.get_range.return_value = []

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(_OBS_REPO, return_value=mock_obs_repo),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_LEARNING_REPO, return_value=mock_learning_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_AGENT_LEARNING_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx(), trade_id)

        assert result["would_take_again"] is False
        assert result["entry_quality"] == "poor"
        assert len(result["improvement_notes"]) > 0


# ---------------------------------------------------------------------------
# TestReviewPortfolio
# ---------------------------------------------------------------------------


class TestReviewPortfolio:
    """Tests for the review_portfolio tool."""

    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, AsyncMock]:
        mock_client = _make_mock_sdk_client()
        tool_map, _agent_id = _build_tools(mock_client, monkeypatch)
        return tool_map["review_portfolio"], mock_client

    def _mock_budget_repo(self, trades_today: int = 5, max_trades: int = 50) -> MagicMock:
        """Build a mock budget repo with a budget row."""
        budget_row = MagicMock()
        budget_row.trades_today = trades_today
        budget_row.max_trades_per_day = max_trades
        budget_row.loss_today = Decimal("50.00")
        budget_row.max_exposure_pct = Decimal("25.00")
        budget_row.exposure_today = Decimal("500.00")
        budget_row.max_daily_loss_pct = Decimal("5.00")
        repo = AsyncMock()
        repo.get_by_agent.return_value = budget_row
        return repo

    async def test_healthy_portfolio_returns_review_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """review_portfolio returns a PortfolioReview dict for a healthy portfolio."""
        tool_fn, mock_client = self._setup(monkeypatch)

        mock_client.get_balance.return_value = [_make_balance_obj("USDT", "9000.00")]
        mock_client.get_positions.return_value = [
            _make_position_obj("BTCUSDT", "500.00", "20.00"),
        ]

        mock_session = AsyncMock()
        mock_budget_repo = self._mock_budget_repo()
        mock_journal_repo = AsyncMock()

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(
                _BUDGET_REPO,
                return_value=mock_budget_repo,
            ),
            patch(
                _BUDGET_NOT_FOUND,
                Exception,
            ),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx())

        assert "error" not in result
        assert "total_value" in result
        assert "health_score" in result
        assert "recommendations" in result
        assert "risk_flags" in result
        assert isinstance(result["recommendations"], list)
        assert 0.0 <= result["health_score"] <= 1.0

    async def test_concentrated_portfolio_triggers_risk_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Extreme concentration (>50% single asset) adds a risk flag."""
        tool_fn, mock_client = self._setup(monkeypatch)

        # 1000 USDT free, 6000 USDT in BTC — BTC is ~86% of portfolio
        mock_client.get_balance.return_value = [_make_balance_obj("USDT", "1000.00")]
        mock_client.get_positions.return_value = [
            _make_position_obj("BTCUSDT", "6000.00", "200.00"),
        ]

        mock_session = AsyncMock()
        mock_budget_repo = self._mock_budget_repo()
        mock_journal_repo = AsyncMock()

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(
                _BUDGET_REPO,
                return_value=mock_budget_repo,
            ),
            patch(
                _BUDGET_NOT_FOUND,
                Exception,
            ),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx())

        assert len(result["risk_flags"]) > 0
        # At least one flag should mention concentration
        concentration_flags = [f for f in result["risk_flags"] if "concentration" in f.lower()]
        assert len(concentration_flags) > 0
        # Health score should be degraded
        assert result["health_score"] < 1.0

    async def test_empty_portfolio_recommends_scanning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty portfolio (no positions) adds a recommendation to scan for opportunities."""
        tool_fn, mock_client = self._setup(monkeypatch)

        mock_client.get_balance.return_value = [_make_balance_obj("USDT", "10000.00")]
        mock_client.get_positions.return_value = []

        mock_session = AsyncMock()
        mock_budget_repo = self._mock_budget_repo()
        mock_journal_repo = AsyncMock()

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(
                _BUDGET_REPO,
                return_value=mock_budget_repo,
            ),
            patch(
                _BUDGET_NOT_FOUND,
                Exception,
            ),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx())

        assert result["num_open_positions"] == 0
        scan_recs = [r for r in result["recommendations"] if "scan" in r.lower() or "opportunit" in r.lower()]
        assert len(scan_recs) > 0

    async def test_sdk_error_returns_error_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """review_portfolio returns error dict when SDK raises."""
        tool_fn, mock_client = self._setup(monkeypatch)

        from agentexchange.exceptions import AgentExchangeError

        mock_client.get_balance.side_effect = AgentExchangeError("unauthorized")

        result = await tool_fn(_make_ctx())

        assert "error" in result

    async def test_budget_exhausted_adds_risk_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Daily trade budget exhausted triggers a risk flag and recommendation."""
        tool_fn, mock_client = self._setup(monkeypatch)

        mock_client.get_balance.return_value = [_make_balance_obj("USDT", "10000.00")]
        mock_client.get_positions.return_value = []

        mock_session = AsyncMock()
        # trades_today == max_trades → budget fully exhausted
        mock_budget_repo = self._mock_budget_repo(trades_today=50, max_trades=50)
        mock_journal_repo = AsyncMock()

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(
                _BUDGET_REPO,
                return_value=mock_budget_repo,
            ),
            patch(
                _BUDGET_NOT_FOUND,
                Exception,
            ),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx())

        assert result["budget_utilization_pct"] >= 1.0
        exhausted_flags = [f for f in result["risk_flags"] if "limit" in f.lower() or "budget" in f.lower()]
        assert len(exhausted_flags) > 0


# ---------------------------------------------------------------------------
# TestScanOpportunities
# ---------------------------------------------------------------------------


class TestScanOpportunities:
    """Tests for the scan_opportunities tool."""

    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, AsyncMock]:
        mock_client = _make_mock_sdk_client()
        tool_map, _agent_id = _build_tools(mock_client, monkeypatch)
        return tool_map["scan_opportunities"], mock_client

    def _mock_redis_with_prices(self, prices: dict[str, str]) -> AsyncMock:
        """Build a mock Redis client that returns the given prices from hgetall."""
        mock_redis = AsyncMock()
        mock_redis.hgetall.side_effect = lambda key: prices if key == "prices" else {}
        return mock_redis

    async def test_matches_found_returns_opportunity_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """scan_opportunities returns a list of Opportunity dicts when matches exist."""
        tool_fn, mock_client = self._setup(monkeypatch)

        # Prices with strong change signals
        prices = {"BTCUSDT": "60000.00", "ETHUSDT": "3000.00", "SOLUSDT": "150.00"}
        mock_redis = self._mock_redis_with_prices(prices)
        mock_client.get_positions.return_value = []

        # Ticker data showing strong moves
        ticker_data: dict[str, dict] = {
            "BTCUSDT": {"change_pct": "8.5"},
            "ETHUSDT": {"change_pct": "5.0"},
            "SOLUSDT": {"change_pct": "3.2"},
        }

        async def mock_hgetall(key: str) -> dict:
            if key == "prices":
                return prices
            sym = key.replace("ticker:", "")
            return ticker_data.get(sym, {})

        mock_redis.hgetall.side_effect = mock_hgetall

        with patch(_REDIS_CLIENT, return_value=mock_redis):
            result = await tool_fn(_make_ctx(), {})

        assert isinstance(result, list)
        assert len(result) > 0
        # Each result should be an Opportunity dict
        for opp in result:
            assert "symbol" in opp
            assert "direction" in opp
            assert "signal_strength" in opp
            assert "entry_price" in opp
            assert "stop_loss_price" in opp
            assert "take_profit_price" in opp

    async def test_no_matches_returns_empty_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """scan_opportunities returns empty list when all symbols are in open positions."""
        tool_fn, mock_client = self._setup(monkeypatch)

        prices = {"BTCUSDT": "60000.00", "ETHUSDT": "3000.00"}
        mock_redis = self._mock_redis_with_prices(prices)
        # All symbols already open
        pos_btc = MagicMock()
        pos_btc.symbol = "BTCUSDT"
        pos_eth = MagicMock()
        pos_eth.symbol = "ETHUSDT"
        mock_client.get_positions.return_value = [pos_btc, pos_eth]

        ticker_data = {
            "BTCUSDT": {"change_pct": "5.0"},
            "ETHUSDT": {"change_pct": "4.0"},
        }

        async def mock_hgetall(key: str) -> dict:
            if key == "prices":
                return prices
            sym = key.replace("ticker:", "")
            return ticker_data.get(sym, {})

        mock_redis.hgetall.side_effect = mock_hgetall

        with patch(_REDIS_CLIENT, return_value=mock_redis):
            result = await tool_fn(_make_ctx(), {})

        # Should return empty or only non-open-position symbols
        open_symbols = {"BTCUSDT", "ETHUSDT"}
        for opp in result:
            assert opp.get("symbol") not in open_symbols

    async def test_no_price_data_returns_error_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """scan_opportunities returns [{'error': ...}] when no price data is available."""
        tool_fn, mock_client = self._setup(monkeypatch)

        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}  # empty prices
        mock_client.get_positions.return_value = []
        # SDK fallback also fails
        from agentexchange.exceptions import AgentExchangeError

        mock_client.get_price.side_effect = AgentExchangeError("no data")

        with patch(_REDIS_CLIENT, return_value=mock_redis):
            result = await tool_fn(_make_ctx(), {})

        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]

    async def test_criteria_min_price_filters_out_low_price_symbols(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """min_price criterion filters symbols below the threshold."""
        tool_fn, mock_client = self._setup(monkeypatch)

        prices = {"BTCUSDT": "60000.00", "SHIB1000USDT": "0.01"}
        mock_client.get_positions.return_value = []

        ticker_data = {
            "BTCUSDT": {"change_pct": "8.0"},
            "SHIB1000USDT": {"change_pct": "9.0"},
        }

        async def mock_hgetall(key: str) -> dict:
            if key == "prices":
                return prices
            sym = key.replace("ticker:", "")
            return ticker_data.get(sym, {})

        mock_redis = AsyncMock()
        mock_redis.hgetall.side_effect = mock_hgetall

        with patch(_REDIS_CLIENT, return_value=mock_redis):
            result = await tool_fn(_make_ctx(), {"min_price": "100"})

        for opp in result:
            assert opp.get("symbol") != "SHIB1000USDT"

    async def test_explicit_symbols_criteria_restricts_scan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """symbols=[...] criterion restricts the scan to specified symbols only."""
        tool_fn, mock_client = self._setup(monkeypatch)

        prices = {"BTCUSDT": "60000.00", "ETHUSDT": "3000.00", "SOLUSDT": "150.00"}
        mock_client.get_positions.return_value = []

        async def mock_hgetall(key: str) -> dict:
            if key == "prices":
                return prices
            return {}

        mock_redis = AsyncMock()
        mock_redis.hgetall.side_effect = mock_hgetall

        with patch(_REDIS_CLIENT, return_value=mock_redis):
            result = await tool_fn(_make_ctx(), {"symbols": ["BTCUSDT"]})

        # Result should only contain BTCUSDT (if it passes other filters)
        for opp in result:
            assert opp["symbol"] == "BTCUSDT"

    async def test_trending_down_criterion_sets_short_direction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """trending_down=True sets direction='short' for returned opportunities."""
        tool_fn, mock_client = self._setup(monkeypatch)

        prices = {"BTCUSDT": "60000.00"}
        mock_client.get_positions.return_value = []

        ticker_data = {"BTCUSDT": {"change_pct": "-8.0"}}

        async def mock_hgetall(key: str) -> dict:
            if key == "prices":
                return prices
            sym = key.replace("ticker:", "")
            return ticker_data.get(sym, {})

        mock_redis = AsyncMock()
        mock_redis.hgetall.side_effect = mock_hgetall

        with patch(_REDIS_CLIENT, return_value=mock_redis):
            result = await tool_fn(_make_ctx(), {"trending_down": True})

        for opp in result:
            if opp.get("symbol") == "BTCUSDT":
                assert opp["direction"] == "short"


# ---------------------------------------------------------------------------
# TestJournalEntry
# ---------------------------------------------------------------------------


class TestJournalEntry:
    """Tests for the journal_entry tool."""

    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, AsyncMock]:
        mock_client = _make_mock_sdk_client()
        tool_map, _agent_id = _build_tools(mock_client, monkeypatch)
        return tool_map["journal_entry"], mock_client

    async def test_normal_entry_returns_journal_entry_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """journal_entry returns a JournalEntry dict on normal write."""
        tool_fn, mock_client = self._setup(monkeypatch)

        content = "Today's trading session went well. I observed a strong momentum signal."
        mock_client.get_positions.return_value = []

        mock_session = AsyncMock()
        mock_saved_row = MagicMock()
        mock_saved_row.id = uuid4()
        mock_saved_row.created_at = _utcnow()
        mock_journal_repo = AsyncMock()
        mock_journal_repo.create.return_value = mock_saved_row

        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {"BTCUSDT": "60000.00"}

        with (
            patch(_REDIS_CLIENT, return_value=mock_redis),
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx(), content)

        assert "error" not in result
        assert result["content"] == content
        assert "entry_type" in result
        assert "tags" in result
        assert isinstance(result["tags"], list)
        assert "market_context" in result
        assert "created_at" in result

    async def test_auto_tagging_detects_risk_keywords(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """journal_entry auto-tags content containing risk keywords."""
        tool_fn, mock_client = self._setup(monkeypatch)

        content = "I need to review my stop loss placement and reduce drawdown exposure."
        mock_client.get_positions.return_value = []

        mock_session = AsyncMock()
        mock_saved_row = MagicMock()
        mock_saved_row.id = uuid4()
        mock_saved_row.created_at = _utcnow()
        mock_journal_repo = AsyncMock()
        mock_journal_repo.create.return_value = mock_saved_row

        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}

        with (
            patch(_REDIS_CLIENT, return_value=mock_redis),
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx(), content)

        # "risk" tag expected from keywords: stop, loss, drawdown
        assert "risk" in result["tags"]

    async def test_auto_tagging_detects_momentum_keywords(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """journal_entry auto-tags content containing momentum keywords."""
        tool_fn, mock_client = self._setup(monkeypatch)

        content = "Strong breakout on BTCUSDT with high volume and momentum trending upward."
        mock_client.get_positions.return_value = []

        mock_session = AsyncMock()
        mock_saved_row = MagicMock()
        mock_saved_row.id = uuid4()
        mock_saved_row.created_at = _utcnow()
        mock_journal_repo = AsyncMock()
        mock_journal_repo.create.return_value = mock_saved_row

        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}

        with (
            patch(_REDIS_CLIENT, return_value=mock_redis),
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx(), content)

        assert "momentum" in result["tags"]

    async def test_market_context_captured_when_redis_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """journal_entry captures market prices from Redis into market_context."""
        tool_fn, mock_client = self._setup(monkeypatch)

        content = "Quick observation entry."
        mock_client.get_positions.return_value = []

        mock_session = AsyncMock()
        mock_saved_row = MagicMock()
        mock_saved_row.id = uuid4()
        mock_saved_row.created_at = _utcnow()
        mock_journal_repo = AsyncMock()
        mock_journal_repo.create.return_value = mock_saved_row

        prices = {"BTCUSDT": "60000.00", "ETHUSDT": "3000.00"}
        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = prices

        with (
            patch(_REDIS_CLIENT, return_value=mock_redis),
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx(), content)

        ctx = result["market_context"]
        assert "total_pairs_tracked" in ctx
        assert ctx["total_pairs_tracked"] == len(prices)

    async def test_entry_type_default_is_reflection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """journal_entry defaults to entry_type='reflection' when not specified."""
        tool_fn, mock_client = self._setup(monkeypatch)

        content = "My thoughts on today's session."
        mock_client.get_positions.return_value = []

        mock_session = AsyncMock()
        mock_saved_row = MagicMock()
        mock_saved_row.id = uuid4()
        mock_saved_row.created_at = _utcnow()
        mock_journal_repo = AsyncMock()
        mock_journal_repo.create.return_value = mock_saved_row

        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}

        with (
            patch(_REDIS_CLIENT, return_value=mock_redis),
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx(), content)

        assert result["entry_type"] == "reflection"

    async def test_custom_entry_type_is_preserved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """journal_entry preserves the caller-supplied entry_type in output."""
        tool_fn, mock_client = self._setup(monkeypatch)

        content = "Weekly summary of performance."
        mock_client.get_positions.return_value = []

        mock_session = AsyncMock()
        mock_saved_row = MagicMock()
        mock_saved_row.id = uuid4()
        mock_saved_row.created_at = _utcnow()
        mock_journal_repo = AsyncMock()
        mock_journal_repo.create.return_value = mock_saved_row

        mock_redis = AsyncMock()
        mock_redis.hgetall.return_value = {}

        with (
            patch(_REDIS_CLIENT, return_value=mock_redis),
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(_JOURNAL_REPO, return_value=mock_journal_repo),
            patch(_AGENT_JOURNAL_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
        ):
            result = await tool_fn(_make_ctx(), content, entry_type="weekly_review")

        assert result["entry_type"] == "weekly_review"


# ---------------------------------------------------------------------------
# TestRequestPlatformFeature
# ---------------------------------------------------------------------------


class TestRequestPlatformFeature:
    """Tests for the request_platform_feature tool."""

    def _setup(self, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, AsyncMock]:
        mock_client = _make_mock_sdk_client()
        tool_map, _agent_id = _build_tools(mock_client, monkeypatch)
        return tool_map["request_platform_feature"], mock_client

    def _mock_feedback_db(
        self, existing_feedback: MagicMock | None = None
    ) -> tuple[AsyncMock, AsyncMock, MagicMock]:
        """Return (mock_session, mock_feedback_repo, mock_stmt) triple.

        The mock_session.execute is pre-wired to return a result whose
        scalars().first() resolves to existing_feedback (or None).
        sqlalchemy.select is patched externally by each test so the lazy
        `from sqlalchemy import select` inside the tool resolves to a
        MagicMock that returns mock_stmt.
        """
        mock_session = AsyncMock()
        mock_feedback_repo = AsyncMock()

        # DB query result
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = existing_feedback
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Default: repo.create returns a row with id and created_at
        mock_saved = MagicMock()
        mock_saved.id = uuid4()
        mock_saved.created_at = _utcnow()
        mock_feedback_repo.create.return_value = mock_saved

        # A chainable mock statement so select(...).where(...).order_by(...).limit(...) works
        mock_stmt = MagicMock()
        mock_stmt.where.return_value = mock_stmt
        mock_stmt.order_by.return_value = mock_stmt
        mock_stmt.limit.return_value = mock_stmt

        return mock_session, mock_feedback_repo, mock_stmt

    async def test_new_request_creates_and_returns_feedback_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """request_platform_feature creates a new entry when no duplicate exists."""
        tool_fn, _mock_client = self._setup(monkeypatch)

        description = "Please add support for trailing stop orders in the backtest engine."
        mock_session, mock_feedback_repo, mock_stmt = self._mock_feedback_db(existing_feedback=None)

        mock_select = MagicMock(return_value=mock_stmt)

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(
                _FEEDBACK_REPO,
                return_value=mock_feedback_repo,
            ),
            patch(_AGENT_FEEDBACK_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
            patch("sqlalchemy.select", mock_select),
        ):
            result = await tool_fn(_make_ctx(), description)

        assert "error" not in result
        assert result["description"] == description
        assert result["is_duplicate"] is False
        assert result["duplicate_of"] is None
        assert result["category"] == "feature_request"
        assert result["priority"] == "medium"

    async def test_duplicate_detection_returns_existing_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """request_platform_feature detects a duplicate and returns existing entry."""
        tool_fn, _mock_client = self._setup(monkeypatch)

        existing_id = uuid4()
        existing_fb = MagicMock()
        existing_fb.id = existing_id
        existing_fb.description = "Please add support for trailing stop orders."
        existing_fb.created_at = _utcnow()

        mock_session, mock_feedback_repo, mock_stmt = self._mock_feedback_db(existing_feedback=existing_fb)

        description = "Please add support for trailing stop orders in the backtest engine."
        mock_select = MagicMock(return_value=mock_stmt)

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(
                _FEEDBACK_REPO,
                return_value=mock_feedback_repo,
            ),
            patch(_AGENT_FEEDBACK_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
            patch("sqlalchemy.select", mock_select),
        ):
            result = await tool_fn(_make_ctx(), description)

        assert result["is_duplicate"] is True
        assert result["duplicate_of"] == str(existing_id)
        # No new row should have been created
        mock_feedback_repo.create.assert_not_called()

    async def test_bug_report_category_maps_to_high_priority(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bug reports receive 'high' priority automatically."""
        tool_fn, _mock_client = self._setup(monkeypatch)

        description = "The portfolio endpoint returns incorrect unrealized PnL values."
        mock_session, mock_feedback_repo, mock_stmt = self._mock_feedback_db(existing_feedback=None)
        mock_select = MagicMock(return_value=mock_stmt)

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(
                _FEEDBACK_REPO,
                return_value=mock_feedback_repo,
            ),
            patch(_AGENT_FEEDBACK_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
            patch("sqlalchemy.select", mock_select),
        ):
            result = await tool_fn(_make_ctx(), description, category="bug_report")

        assert result["priority"] == "high"
        assert result["category"] == "bug_report"

    async def test_ux_category_maps_to_low_priority(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """UX category receives 'low' priority."""
        tool_fn, _mock_client = self._setup(monkeypatch)

        description = "The backtest results page could benefit from a clearer chart layout."
        mock_session, mock_feedback_repo, mock_stmt = self._mock_feedback_db(existing_feedback=None)
        mock_select = MagicMock(return_value=mock_stmt)

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(
                _FEEDBACK_REPO,
                return_value=mock_feedback_repo,
            ),
            patch(_AGENT_FEEDBACK_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
            patch("sqlalchemy.select", mock_select),
        ):
            result = await tool_fn(_make_ctx(), description, category="ux")

        assert result["priority"] == "low"

    async def test_database_error_returns_error_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """request_platform_feature returns error dict when DB raises DatabaseError."""
        tool_fn, _mock_client = self._setup(monkeypatch)

        description = "Add advanced order types."

        class FakeDBError(Exception):
            pass

        mock_session = AsyncMock()
        mock_session.execute.side_effect = FakeDBError("connection lost")

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(
                _FEEDBACK_REPO,
                return_value=AsyncMock(),
            ),
            patch(_AGENT_FEEDBACK_MODEL, MagicMock()),
            patch(_DB_ERROR, FakeDBError),
        ):
            result = await tool_fn(_make_ctx(), description)

        assert "error" in result

    async def test_performance_category_maps_to_medium_priority(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Performance category receives 'medium' priority."""
        tool_fn, _mock_client = self._setup(monkeypatch)

        description = "The market data endpoint is slow when requesting 600+ pairs."
        mock_session, mock_feedback_repo, mock_stmt = self._mock_feedback_db(existing_feedback=None)
        mock_select = MagicMock(return_value=mock_stmt)

        with (
            patch(_SESSION_FACTORY, return_value=lambda: mock_session),
            patch(
                _FEEDBACK_REPO,
                return_value=mock_feedback_repo,
            ),
            patch(_AGENT_FEEDBACK_MODEL, MagicMock()),
            patch(_DB_ERROR, Exception),
            patch("sqlalchemy.select", mock_select),
        ):
            result = await tool_fn(_make_ctx(), description, category="performance")

        assert result["priority"] == "medium"
        assert result["category"] == "performance"


# ---------------------------------------------------------------------------
# TestGetAgentToolsStructure
# ---------------------------------------------------------------------------


class TestGetAgentToolsStructure:
    """Tests for the get_agent_tools() factory function structure."""

    def test_returns_five_callables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_agent_tools() returns exactly 5 callable tool functions."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_test")
        monkeypatch.setenv("PLATFORM_API_SECRET", "sk_live_test")
        monkeypatch.setenv("PLATFORM_BASE_URL", "http://localhost:8000")
        from agent.config import AgentConfig

        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]

        mock_client = AsyncMock()
        with patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=mock_client):
            from agent.tools.agent_tools import get_agent_tools

            tools = get_agent_tools(config, agent_id=str(uuid4()))

        assert len(tools) == 5
        for tool in tools:
            assert callable(tool)

    def test_tool_names_match_expected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_agent_tools() returns tools with the expected function names."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        monkeypatch.setenv("PLATFORM_API_KEY", "ak_live_test")
        monkeypatch.setenv("PLATFORM_API_SECRET", "sk_live_test")
        monkeypatch.setenv("PLATFORM_BASE_URL", "http://localhost:8000")
        from agent.config import AgentConfig

        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]

        mock_client = AsyncMock()
        with patch("agentexchange.async_client.AsyncAgentExchangeClient", return_value=mock_client):
            from agent.tools.agent_tools import get_agent_tools

            tools = get_agent_tools(config, agent_id=str(uuid4()))

        names = {t.__name__ for t in tools}
        assert names == {
            "reflect_on_trade",
            "review_portfolio",
            "scan_opportunities",
            "journal_entry",
            "request_platform_feature",
        }
