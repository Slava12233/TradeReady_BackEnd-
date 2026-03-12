"""Unit tests for src.backtesting.engine.BacktestEngine.

Uses mocked DB sessions and replayer to test the orchestrator logic
without requiring a live database.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.backtesting.engine import BacktestConfig, BacktestEngine


@pytest.fixture
def config() -> BacktestConfig:
    return BacktestConfig(
        start_time=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc),
        starting_balance=Decimal("10000"),
        candle_interval=60,
        strategy_label="test_strategy_v1",
    )


@pytest.fixture
def engine() -> BacktestEngine:
    return BacktestEngine(session_factory=MagicMock())


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.fixture
def mock_session_model():
    """Create a mock BacktestSession ORM model."""
    session = MagicMock()
    session.id = uuid4()
    session.account_id = uuid4()
    session.status = "created"
    session.strategy_label = "test_v1"
    session.candle_interval = 60
    session.start_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    session.end_time = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
    session.starting_balance = Decimal("10000")
    session.pairs = None
    session.total_steps = 60
    return session


async def test_create_session(
    engine: BacktestEngine, config: BacktestConfig, mock_db: AsyncMock
) -> None:
    account_id = uuid4()

    with patch("src.backtesting.engine.DataReplayer") as MockReplayer:
        replayer = MockReplayer.return_value
        replayer.get_data_range = AsyncMock(return_value=MagicMock(
            earliest=datetime(2025, 1, 1, tzinfo=timezone.utc),
            latest=datetime(2026, 12, 31, tzinfo=timezone.utc),
        ))

        session = await engine.create_session(account_id, config, mock_db)

        assert session is not None
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()


async def test_start_initializes_sandbox(
    engine: BacktestEngine, mock_db: AsyncMock, mock_session_model: MagicMock
) -> None:
    session_id = str(mock_session_model.id)

    # Mock DB load
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_session_model
    mock_db.execute.return_value = mock_result

    with patch("src.backtesting.engine.DataReplayer") as MockReplayer:
        replayer = MockReplayer.return_value
        replayer.load_prices = AsyncMock(return_value={
            "BTCUSDT": Decimal("50000"),
        })

        await engine.start(session_id, mock_db)

        assert engine.is_active(session_id)
        assert mock_session_model.status == "running"


async def test_step_returns_correct_data(
    engine: BacktestEngine, mock_db: AsyncMock, mock_session_model: MagicMock
) -> None:
    session_id = str(mock_session_model.id)

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_session_model
    mock_db.execute.return_value = mock_result

    with patch("src.backtesting.engine.DataReplayer") as MockReplayer:
        replayer = MockReplayer.return_value
        replayer.load_prices = AsyncMock(return_value={
            "BTCUSDT": Decimal("50000"),
        })

        await engine.start(session_id, mock_db)
        result = await engine.step(session_id, mock_db)

        assert result.step == 1
        assert result.total_steps == 60
        assert "BTCUSDT" in result.prices
        assert result.is_complete is False


async def test_step_batch_advances_correctly(
    engine: BacktestEngine, mock_db: AsyncMock, mock_session_model: MagicMock
) -> None:
    session_id = str(mock_session_model.id)

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_session_model
    mock_db.execute.return_value = mock_result

    with patch("src.backtesting.engine.DataReplayer") as MockReplayer:
        replayer = MockReplayer.return_value
        replayer.load_prices = AsyncMock(return_value={
            "BTCUSDT": Decimal("50000"),
        })

        await engine.start(session_id, mock_db)
        result = await engine.step_batch(session_id, 10, mock_db)

        assert result.step == 10
        assert result.remaining_steps == 50


async def test_order_during_backtest(
    engine: BacktestEngine, mock_db: AsyncMock, mock_session_model: MagicMock
) -> None:
    session_id = str(mock_session_model.id)

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_session_model
    mock_db.execute.return_value = mock_result

    with patch("src.backtesting.engine.DataReplayer") as MockReplayer:
        replayer = MockReplayer.return_value
        replayer.load_prices = AsyncMock(return_value={
            "BTCUSDT": Decimal("50000"),
        })

        await engine.start(session_id, mock_db)

        order_result = await engine.execute_order(
            session_id, "BTCUSDT", "buy", "market",
            Decimal("0.1"), None,
        )
        assert order_result.status == "filled"


async def test_concurrent_sessions_isolated(
    engine: BacktestEngine, mock_db: AsyncMock
) -> None:
    """Two sessions should not interfere with each other."""
    models = []
    for i in range(2):
        m = MagicMock()
        m.id = uuid4()
        m.account_id = uuid4()
        m.status = "created"
        m.strategy_label = f"strategy_{i}"
        m.candle_interval = 60
        m.start_time = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        m.end_time = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
        m.starting_balance = Decimal("10000")
        m.pairs = None
        m.total_steps = 60
        models.append(m)

    with patch("src.backtesting.engine.DataReplayer") as MockReplayer:
        replayer = MockReplayer.return_value
        replayer.load_prices = AsyncMock(return_value={
            "BTCUSDT": Decimal("50000"),
        })

        for model in models:
            mock_result = MagicMock()
            mock_result.scalars.return_value.first.return_value = model
            mock_db.execute.return_value = mock_result
            await engine.start(str(model.id), mock_db)

        assert engine.is_active(str(models[0].id))
        assert engine.is_active(str(models[1].id))

        # Order in session 0 doesn't affect session 1
        await engine.execute_order(
            str(models[0].id), "BTCUSDT", "buy", "market",
            Decimal("0.1"), None,
        )

        portfolio_1 = await engine.get_portfolio(str(models[1].id))
        assert portfolio_1.total_equity == Decimal("10000")
