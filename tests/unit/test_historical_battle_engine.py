"""Unit tests for HistoricalBattleEngine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.battles.historical_engine import (
    HistoricalBattleEngine,
    _active_engines,
    get_engine,
    register_engine,
    remove_engine,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def battle_config():
    """Standard historical battle config."""
    now = datetime.now(UTC)
    return {
        "start_time": (now - timedelta(hours=1)).isoformat(),
        "end_time": now.isoformat(),
        "candle_interval": 60,
        "pairs": ["BTCUSDT", "ETHUSDT"],
    }


@pytest.fixture()
def agent_ids():
    """Two agent UUIDs."""
    return [uuid4(), uuid4()]


@pytest.fixture()
def mock_db():
    """Mock AsyncSession."""
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture()
def engine(battle_config, agent_ids):
    """Create an uninitialized engine."""
    return HistoricalBattleEngine(
        battle_id=str(uuid4()),
        config=battle_config,
        participant_agent_ids=agent_ids,
        starting_balance=Decimal("10000"),
        ranking_metric="roi_pct",
    )


@pytest.fixture(autouse=True)
def _clear_active_engines():
    """Ensure module-level engine registry is clean between tests."""
    _active_engines.clear()
    yield
    _active_engines.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_mock_agent():
    """Create a mock Agent ORM object."""
    mock_agent = MagicMock()
    mock_agent.risk_profile = {}
    mock_agent.account_id = uuid4()
    return mock_agent


def _setup_db_for_agent(mock_db, mock_agent):
    """Wire mock_db.execute to return a mock agent."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_agent
    mock_db.execute = AsyncMock(return_value=mock_result)


async def _initialize_engine(engine, mock_db):
    """Helper to initialize an engine with mocks."""
    mock_agent = _make_mock_agent()
    _setup_db_for_agent(mock_db, mock_agent)

    with patch("src.battles.historical_engine.DataReplayer") as mock_replayer_cls:
        mock_replayer = mock_replayer_cls.return_value
        mock_replayer.preload_range = AsyncMock(return_value=100)
        mock_replayer.load_prices = AsyncMock(return_value={"BTCUSDT": Decimal("50000"), "ETHUSDT": Decimal("3000")})
        await engine.initialize(mock_db)
        # Keep the mock replayer accessible for step calls
        engine._replayer = mock_replayer


# ── Module-level tracking tests ──────────────────────────────────────────────


class TestModuleLevelTracking:
    def test_register_and_get_engine(self, engine):
        battle_id = "test-123"
        register_engine(battle_id, engine)
        assert get_engine(battle_id) is engine
        remove_engine(battle_id)
        assert get_engine(battle_id) is None

    def test_get_nonexistent_engine(self):
        assert get_engine("nonexistent") is None

    def test_remove_nonexistent_is_safe(self):
        remove_engine("nonexistent")  # Should not raise


# ── Initialization tests ────────────────────────────────────────────────────


class TestInitialize:
    async def test_not_initialized_step_raises(self, engine):
        with pytest.raises(RuntimeError, match="not been initialized"):
            await engine.step()

    async def test_not_initialized_place_order_raises(self, engine, agent_ids):
        with pytest.raises(RuntimeError, match="not been initialized"):
            engine.place_order(agent_ids[0], "BTCUSDT", "buy", "market", Decimal("1"))

    async def test_not_initialized_complete_raises(self, engine, mock_db):
        with pytest.raises(RuntimeError, match="not been initialized"):
            await engine.complete(mock_db)

    async def test_not_initialized_get_agent_portfolio_raises(self, engine, agent_ids):
        with pytest.raises(RuntimeError, match="not been initialized"):
            engine.get_agent_portfolio(agent_ids[0])

    async def test_initialize_creates_sandboxes(self, engine, agent_ids, mock_db):
        mock_agent = _make_mock_agent()
        _setup_db_for_agent(mock_db, mock_agent)

        with patch("src.battles.historical_engine.DataReplayer") as mock_replayer_cls:
            mock_replayer = mock_replayer_cls.return_value
            mock_replayer.preload_range = AsyncMock(return_value=100)
            mock_replayer.load_prices = AsyncMock(
                return_value={"BTCUSDT": Decimal("50000"), "ETHUSDT": Decimal("3000")}
            )

            await engine.initialize(mock_db)

        assert engine.is_initialized
        assert len(engine._sandboxes) == len(agent_ids)
        for aid in agent_ids:
            assert aid in engine._sandboxes

    async def test_initialize_no_data_raises(self, engine, mock_db):
        mock_agent = _make_mock_agent()
        _setup_db_for_agent(mock_db, mock_agent)

        with patch("src.battles.historical_engine.DataReplayer") as mock_replayer_cls:
            mock_replayer = mock_replayer_cls.return_value
            mock_replayer.preload_range = AsyncMock(return_value=0)

            with pytest.raises(ValueError, match="No historical data"):
                await engine.initialize(mock_db)

    async def test_initialize_sets_virtual_time(self, engine, mock_db):
        await _initialize_engine(engine, mock_db)

        assert engine.virtual_time is not None

    async def test_uninitialized_virtual_time_is_none(self, engine):
        assert engine.virtual_time is None

    async def test_initialize_loads_initial_prices(self, engine, mock_db):
        await _initialize_engine(engine, mock_db)

        prices = engine.current_prices
        assert "BTCUSDT" in prices
        assert "ETHUSDT" in prices
        assert prices["BTCUSDT"] == Decimal("50000")


# ── Step tests ───────────────────────────────────────────────────────────────


class TestStep:
    async def test_step_advances_all_agents(self, engine, agent_ids, mock_db):
        await _initialize_engine(engine, mock_db)

        result = await engine.step()

        assert result.step == 1
        assert not result.is_complete
        assert len(result.agent_states) == len(agent_ids)
        for aid in agent_ids:
            state = result.agent_states[str(aid)]
            assert state.equity == Decimal("10000")
            assert state.trade_count == 0

    async def test_step_returns_prices(self, engine, mock_db):
        await _initialize_engine(engine, mock_db)

        result = await engine.step()

        assert "BTCUSDT" in result.prices
        assert "ETHUSDT" in result.prices

    async def test_step_batch(self, engine, agent_ids, mock_db):
        await _initialize_engine(engine, mock_db)

        result = await engine.step_batch(5)

        assert result.step == 5
        assert len(result.agent_states) == len(agent_ids)

    async def test_step_batch_stops_at_completion(self, engine, mock_db):
        await _initialize_engine(engine, mock_db)

        # Request more steps than total (60 steps for 1 hour at 60s interval)
        result = await engine.step_batch(1000)

        assert result.is_complete

    async def test_step_after_completion_raises(self, engine, mock_db):
        await _initialize_engine(engine, mock_db)

        # Run to completion
        await engine.step_batch(1000)

        with pytest.raises(ValueError, match="already completed"):
            await engine.step()

    async def test_step_progress_increases(self, engine, mock_db):
        await _initialize_engine(engine, mock_db)

        result1 = await engine.step()
        result2 = await engine.step()

        assert result2.step > result1.step
        assert result2.progress_pct > result1.progress_pct


# ── Order tests ──────────────────────────────────────────────────────────────


class TestPlaceOrder:
    async def test_place_order_routes_to_correct_sandbox(self, engine, agent_ids, mock_db):
        await _initialize_engine(engine, mock_db)

        result = engine.place_order(
            agent_id=agent_ids[0],
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            quantity=Decimal("0.1"),
        )

        assert result.status == "filled"
        # Agent 0 should have a trade, agent 1 should not
        assert engine._sandboxes[agent_ids[0]].total_trades == 1
        assert engine._sandboxes[agent_ids[1]].total_trades == 0

    async def test_place_order_nonparticipant_raises(self, engine, mock_db):
        await _initialize_engine(engine, mock_db)

        non_participant = uuid4()
        with pytest.raises(ValueError, match="not a participant"):
            engine.place_order(
                agent_id=non_participant,
                symbol="BTCUSDT",
                side="buy",
                order_type="market",
                quantity=Decimal("0.1"),
            )

    async def test_place_limit_order(self, engine, agent_ids, mock_db):
        await _initialize_engine(engine, mock_db)

        result = engine.place_order(
            agent_id=agent_ids[0],
            symbol="BTCUSDT",
            side="buy",
            order_type="limit",
            quantity=Decimal("0.1"),
            price=Decimal("40000"),
        )

        # Limit buy below current price should be pending
        assert result.status == "pending"

    async def test_multiple_agents_trade_independently(self, engine, agent_ids, mock_db):
        await _initialize_engine(engine, mock_db)

        # Agent 0 buys BTC
        engine.place_order(
            agent_id=agent_ids[0],
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            quantity=Decimal("0.1"),
        )

        # Agent 1 buys ETH
        engine.place_order(
            agent_id=agent_ids[1],
            symbol="ETHUSDT",
            side="buy",
            order_type="market",
            quantity=Decimal("1"),
        )

        assert engine._sandboxes[agent_ids[0]].total_trades == 1
        assert engine._sandboxes[agent_ids[1]].total_trades == 1


# ── Portfolio tests ──────────────────────────────────────────────────────────


class TestGetAgentPortfolio:
    async def test_get_agent_portfolio(self, engine, agent_ids, mock_db):
        await _initialize_engine(engine, mock_db)

        portfolio = engine.get_agent_portfolio(agent_ids[0])

        assert portfolio.total_equity == Decimal("10000")

    async def test_get_agent_portfolio_nonparticipant_raises(self, engine, mock_db):
        await _initialize_engine(engine, mock_db)

        with pytest.raises(ValueError, match="not a participant"):
            engine.get_agent_portfolio(uuid4())


# ── Complete tests ───────────────────────────────────────────────────────────


class TestComplete:
    async def test_complete_returns_ranked_results(self, engine, agent_ids, mock_db):
        await _initialize_engine(engine, mock_db)

        # Advance a few steps so there is state
        await engine.step_batch(5)

        # Agent 0 makes a profitable trade
        engine.place_order(
            agent_id=agent_ids[0],
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            quantity=Decimal("0.1"),
        )

        # The complete() method uses lazy imports, so patch the models at
        # their source (src.database.models) where the lazy import resolves.
        mock_session_instance = MagicMock()
        mock_session_instance.id = uuid4()

        with (
            patch("src.database.models.BacktestSession", return_value=mock_session_instance),
            patch("src.database.models.BacktestTrade", side_effect=lambda **kw: MagicMock()),
            patch("src.database.models.BacktestSnapshot", side_effect=lambda **kw: MagicMock()),
            patch("src.database.models.BattleSnapshot", side_effect=lambda **kw: MagicMock()),
        ):
            results = await engine.complete(mock_db)

        assert len(results) == len(agent_ids)
        # Results should be sorted (ranked)
        assert all("agent_id" in r for r in results)
        assert all("roi_pct" in r for r in results)
        assert all("final_equity" in r for r in results)
        assert all("total_pnl" in r for r in results)

    async def test_complete_persists_to_db(self, engine, agent_ids, mock_db):
        await _initialize_engine(engine, mock_db)
        await engine.step_batch(3)

        mock_session_instance = MagicMock()
        mock_session_instance.id = uuid4()

        with (
            patch("src.database.models.BacktestSession", return_value=mock_session_instance),
            patch("src.database.models.BacktestTrade", side_effect=lambda **kw: MagicMock()),
            patch("src.database.models.BacktestSnapshot", side_effect=lambda **kw: MagicMock()),
            patch("src.database.models.BattleSnapshot", side_effect=lambda **kw: MagicMock()),
        ):
            await engine.complete(mock_db)

        # db.add should be called (sessions, snapshots, battle snapshots)
        assert mock_db.add.call_count > 0
        # flush should be called at least twice (per-agent + final)
        assert mock_db.flush.await_count >= 2
