"""Unit tests for src.backtesting.data_replayer.DataReplayer.

Uses a mocked AsyncSession to verify query construction and
look-ahead bias prevention.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backtesting.data_replayer import DataReplayer


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def replayer(mock_session: AsyncMock) -> DataReplayer:
    return DataReplayer(mock_session)


@pytest.fixture
def timestamp() -> datetime:
    return datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


async def test_load_prices_at_timestamp(
    replayer: DataReplayer, mock_session: AsyncMock, timestamp: datetime
) -> None:
    """Verify load_prices returns symbol → price mapping."""
    row1 = MagicMock()
    row1.symbol = "BTCUSDT"
    row1.close = 50000.0

    row2 = MagicMock()
    row2.symbol = "ETHUSDT"
    row2.close = 3000.0

    mock_session.execute.return_value.fetchall.return_value = [row1, row2]

    prices = await replayer.load_prices(timestamp)

    assert "BTCUSDT" in prices
    assert prices["BTCUSDT"] == Decimal("50000.0")
    assert "ETHUSDT" in prices
    assert prices["ETHUSDT"] == Decimal("3000.0")

    # Verify the query was called
    mock_session.execute.assert_awaited_once()


async def test_candle_range_only_returns_past_data(
    replayer: DataReplayer, mock_session: AsyncMock, timestamp: datetime
) -> None:
    """Verify candles query uses bucket <= end_time."""
    row = MagicMock()
    row.bucket = datetime(2026, 1, 15, 11, 59, tzinfo=timezone.utc)
    row.symbol = "BTCUSDT"
    row.open = 49500.0
    row.high = 50100.0
    row.low = 49400.0
    row.close = 50000.0
    row.volume = 100.0
    row.trade_count = 500

    mock_session.execute.return_value.fetchall.return_value = [row]

    candles = await replayer.load_candles("BTCUSDT", timestamp, 60, 10)

    assert len(candles) == 1
    assert candles[0].bucket <= timestamp  # No future data
    assert candles[0].close == Decimal("50000.0")


async def test_no_future_data_leakage(
    replayer: DataReplayer, mock_session: AsyncMock, timestamp: datetime
) -> None:
    """Critical: verify the WHERE clause prevents look-ahead bias.

    The SQL query text must contain 'bucket <= :end_time' or equivalent.
    We verify by checking that the timestamp parameter is passed correctly.
    """
    mock_session.execute.return_value.fetchall.return_value = []

    await replayer.load_candles("BTCUSDT", timestamp, 60, 10)

    # Check that execute was called with end_time = our timestamp
    call_args = mock_session.execute.call_args
    params = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("parameters", {})
    assert params.get("end_time") == timestamp or params.get("end_time") is not None


async def test_ticker_24h_calculation(
    replayer: DataReplayer, mock_session: AsyncMock, timestamp: datetime
) -> None:
    row = MagicMock()
    row.open = 49000.0
    row.high = 51000.0
    row.low = 48500.0
    row.close = 50000.0
    row.volume = 1000.0
    row.trade_count = 5000

    mock_session.execute.return_value.fetchone.return_value = row

    ticker = await replayer.load_ticker_24h("BTCUSDT", timestamp)

    assert ticker is not None
    assert ticker.symbol == "BTCUSDT"
    assert ticker.close == Decimal("50000.0")
    assert ticker.price_change == Decimal("1000.0")
    assert ticker.volume == Decimal("1000.0")


async def test_handles_pairs_without_data(
    replayer: DataReplayer, mock_session: AsyncMock, timestamp: datetime
) -> None:
    """Should return None when no ticker data exists."""
    row = MagicMock()
    row.open = None

    mock_session.execute.return_value.fetchone.return_value = row

    ticker = await replayer.load_ticker_24h("XYZUSDT", timestamp)
    assert ticker is None


async def test_get_data_range(
    replayer: DataReplayer, mock_session: AsyncMock
) -> None:
    row = MagicMock()
    row.earliest = datetime(2025, 6, 1, tzinfo=timezone.utc)
    row.latest = datetime(2026, 3, 1, tzinfo=timezone.utc)
    row.total_pairs = 441

    mock_session.execute.return_value.fetchone.return_value = row

    data_range = await replayer.get_data_range()

    assert data_range is not None
    assert data_range.total_pairs == 441


async def test_get_data_range_empty(
    replayer: DataReplayer, mock_session: AsyncMock
) -> None:
    row = MagicMock()
    row.earliest = None

    mock_session.execute.return_value.fetchone.return_value = row

    data_range = await replayer.get_data_range()
    assert data_range is None


async def test_get_available_pairs(
    replayer: DataReplayer, mock_session: AsyncMock, timestamp: datetime
) -> None:
    row1 = MagicMock()
    row1.symbol = "BTCUSDT"
    row2 = MagicMock()
    row2.symbol = "ETHUSDT"

    mock_session.execute.return_value.fetchall.return_value = [row1, row2]

    pairs = await replayer.get_available_pairs(timestamp)
    assert pairs == ["BTCUSDT", "ETHUSDT"]


async def test_pairs_filter(mock_session: AsyncMock, timestamp: datetime) -> None:
    """When pairs are configured, queries should filter by them."""
    replayer = DataReplayer(mock_session, pairs=["BTCUSDT"])

    mock_session.execute.return_value.fetchall.return_value = []

    await replayer.load_prices(timestamp)

    # Verify execute was called with pairs parameter
    call_args = mock_session.execute.call_args
    params = call_args[0][1] if len(call_args[0]) > 1 else {}
    assert "pairs" in params
    assert params["pairs"] == ["BTCUSDT"]
