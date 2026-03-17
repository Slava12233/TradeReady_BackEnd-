"""Unit tests for SnapshotEngine unrealized PnL calculation (Phase 4)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.battles.snapshot_engine import SnapshotEngine


def _make_position(
    symbol: str,
    quantity: Decimal,
    avg_entry_price: Decimal,
    agent_id=None,
) -> MagicMock:
    """Create a mock Position object."""
    pos = MagicMock()
    pos.symbol = symbol
    pos.quantity = quantity
    pos.avg_entry_price = avg_entry_price
    pos.agent_id = agent_id or uuid4()
    return pos


@pytest.fixture
def mock_session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_price_cache() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def engine(mock_session: AsyncMock, mock_price_cache: AsyncMock) -> SnapshotEngine:
    with patch("src.battles.snapshot_engine.BattleRepository"):
        return SnapshotEngine(mock_session, mock_price_cache)


class TestGetUnrealizedPnl:
    """Tests for _get_unrealized_pnl."""

    async def test_two_open_positions_correct_sum(
        self,
        engine: SnapshotEngine,
        mock_price_cache: AsyncMock,
    ) -> None:
        agent_id = uuid4()
        positions = [
            _make_position("BTCUSDT", Decimal("0.5"), Decimal("60000"), agent_id),
            _make_position("ETHUSDT", Decimal("10"), Decimal("3000"), agent_id),
        ]
        engine._get_open_positions = AsyncMock(return_value=positions)  # type: ignore[method-assign]

        mock_price_cache.get_price = AsyncMock(
            side_effect=lambda s: {
                "BTCUSDT": Decimal("62000"),
                "ETHUSDT": Decimal("3200"),
            }.get(s)
        )

        result = await engine._get_unrealized_pnl(agent_id)

        # BTC: (62000 - 60000) * 0.5 = 1000
        # ETH: (3200 - 3000) * 10 = 2000
        assert result == Decimal("3000")

    async def test_no_positions_returns_zero(
        self,
        engine: SnapshotEngine,
    ) -> None:
        agent_id = uuid4()
        engine._get_open_positions = AsyncMock(return_value=[])  # type: ignore[method-assign]

        result = await engine._get_unrealized_pnl(agent_id)

        assert result == Decimal("0")

    async def test_price_unavailable_skips_position(
        self,
        engine: SnapshotEngine,
        mock_price_cache: AsyncMock,
    ) -> None:
        agent_id = uuid4()
        positions = [
            _make_position("BTCUSDT", Decimal("1"), Decimal("60000"), agent_id),
            _make_position("XYZUSDT", Decimal("100"), Decimal("5"), agent_id),
        ]
        engine._get_open_positions = AsyncMock(return_value=positions)  # type: ignore[method-assign]

        mock_price_cache.get_price = AsyncMock(
            side_effect=lambda s: {
                "BTCUSDT": Decimal("61000"),
                "XYZUSDT": None,
            }.get(s)
        )

        result = await engine._get_unrealized_pnl(agent_id)

        # Only BTC counted: (61000 - 60000) * 1 = 1000
        assert result == Decimal("1000")

    async def test_negative_unrealized_pnl(
        self,
        engine: SnapshotEngine,
        mock_price_cache: AsyncMock,
    ) -> None:
        agent_id = uuid4()
        positions = [
            _make_position("BTCUSDT", Decimal("2"), Decimal("65000"), agent_id),
        ]
        engine._get_open_positions = AsyncMock(return_value=positions)  # type: ignore[method-assign]

        mock_price_cache.get_price = AsyncMock(return_value=Decimal("60000"))

        result = await engine._get_unrealized_pnl(agent_id)

        # (60000 - 65000) * 2 = -10000
        assert result == Decimal("-10000")

    async def test_price_cache_exception_handled_gracefully(
        self,
        engine: SnapshotEngine,
        mock_price_cache: AsyncMock,
    ) -> None:
        agent_id = uuid4()
        positions = [
            _make_position("BTCUSDT", Decimal("1"), Decimal("60000"), agent_id),
        ]
        engine._get_open_positions = AsyncMock(return_value=positions)  # type: ignore[method-assign]

        mock_price_cache.get_price = AsyncMock(side_effect=Exception("Redis down"))

        result = await engine._get_unrealized_pnl(agent_id)

        # Exception caught, returns 0 for that position
        assert result == Decimal("0")


class TestGetOpenPositions:
    """Tests for _get_open_positions."""

    async def test_returns_positions_from_db(
        self,
        engine: SnapshotEngine,
        mock_session: AsyncMock,
    ) -> None:
        agent_id = uuid4()
        mock_pos = _make_position("BTCUSDT", Decimal("1"), Decimal("60000"), agent_id)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_pos]
        mock_session.execute.return_value = mock_result

        result = await engine._get_open_positions(agent_id)

        assert len(result) == 1
        assert result[0].symbol == "BTCUSDT"
        mock_session.execute.assert_called_once()
