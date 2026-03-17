"""Unit tests for TickRepository read-only operations.

Tests that TickRepository correctly delegates to the AsyncSession
and handles time range queries, VWAP, and empty results.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from src.database.models import Tick
from src.database.repositories.tick_repo import TickRepository
from src.utils.exceptions import DatabaseError


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def repo(mock_session: AsyncMock) -> TickRepository:
    return TickRepository(mock_session)


def _make_tick_model(
    symbol="BTCUSDT",
    price="50000.00000000",
    quantity="0.01000000",
    time=None,
) -> MagicMock:
    """Create a mock Tick row for testing."""
    tick = MagicMock(spec=Tick)
    tick.symbol = symbol
    tick.price = Decimal(price)
    tick.quantity = Decimal(quantity)
    tick.time = time or datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
    return tick


class TestGetLatest:
    async def test_get_latest_returns_tick(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """get_latest returns the most recent tick for a symbol."""
        tick = _make_tick_model()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = tick
        mock_session.execute.return_value = mock_result

        result = await repo.get_latest("BTCUSDT")

        assert result is tick
        assert result.symbol == "BTCUSDT"

    async def test_get_latest_no_ticks_returns_none(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """get_latest returns None when no tick exists for symbol."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repo.get_latest("FOOBARUSDT")

        assert result is None

    async def test_get_latest_db_error_raises(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """get_latest raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.get_latest("BTCUSDT")


class TestGetRange:
    async def test_get_range_returns_ticks(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """get_range returns ticks within time range."""
        ticks = [_make_tick_model(), _make_tick_model(price="50100.00000000")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ticks
        mock_session.execute.return_value = mock_result

        since = datetime(2026, 3, 15, 11, 0, tzinfo=UTC)
        until = datetime(2026, 3, 15, 13, 0, tzinfo=UTC)
        result = await repo.get_range("BTCUSDT", since=since, until=until)

        assert len(result) == 2

    async def test_get_range_with_limit(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """get_range with limit parameter respects the limit."""
        ticks = [_make_tick_model()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ticks
        mock_session.execute.return_value = mock_result

        since = datetime(2026, 3, 15, 11, 0, tzinfo=UTC)
        result = await repo.get_range("BTCUSDT", since=since, limit=1)

        assert len(result) == 1

    async def test_get_range_empty_returns_empty_list(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """get_range returns empty list when no ticks in range."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        since = datetime(2020, 1, 1, tzinfo=UTC)
        until = datetime(2020, 1, 2, tzinfo=UTC)
        result = await repo.get_range("BTCUSDT", since=since, until=until)

        assert result == []

    async def test_get_range_db_error_raises(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """get_range raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.get_range("BTCUSDT", since=datetime(2026, 1, 1, tzinfo=UTC))


class TestGetPriceAt:
    async def test_get_price_at_returns_tick(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """get_price_at returns tick closest to target time."""
        tick = _make_tick_model()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = tick
        mock_session.execute.return_value = mock_result

        result = await repo.get_price_at("BTCUSDT", at=datetime(2026, 3, 15, 12, 0, tzinfo=UTC))

        assert result is tick

    async def test_get_price_at_no_data_returns_none(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """get_price_at returns None when no tick exists before target time."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repo.get_price_at("BTCUSDT", at=datetime(2020, 1, 1, tzinfo=UTC))

        assert result is None


class TestCountInRange:
    async def test_count_in_range_returns_count(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """count_in_range returns integer count."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 150
        mock_session.execute.return_value = mock_result

        since = datetime(2026, 3, 15, 11, 0, tzinfo=UTC)
        result = await repo.count_in_range("BTCUSDT", since=since)

        assert result == 150

    async def test_count_in_range_empty_returns_zero(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """count_in_range returns 0 when no ticks in range."""
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 0
        mock_session.execute.return_value = mock_result

        since = datetime(2020, 1, 1, tzinfo=UTC)
        result = await repo.count_in_range("BTCUSDT", since=since)

        assert result == 0


class TestGetVwap:
    async def test_get_vwap_returns_decimal(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """get_vwap returns volume-weighted average price as Decimal."""
        # total_value = 501.00, total_qty = 0.01
        mock_result = MagicMock()
        mock_result.one.return_value = (Decimal("501.00"), Decimal("0.01"))
        mock_session.execute.return_value = mock_result

        since = datetime(2026, 3, 15, 11, 0, tzinfo=UTC)
        result = await repo.get_vwap("BTCUSDT", since=since)

        assert result == Decimal("50100.00")

    async def test_get_vwap_no_ticks_returns_none(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """get_vwap returns None when no ticks in range."""
        mock_result = MagicMock()
        mock_result.one.return_value = (None, None)
        mock_session.execute.return_value = mock_result

        since = datetime(2020, 1, 1, tzinfo=UTC)
        result = await repo.get_vwap("BTCUSDT", since=since)

        assert result is None

    async def test_get_vwap_db_error_raises(self, repo: TickRepository, mock_session: AsyncMock) -> None:
        """get_vwap raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.get_vwap("BTCUSDT", since=datetime(2026, 1, 1, tzinfo=UTC))
