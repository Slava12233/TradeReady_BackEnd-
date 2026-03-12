"""Unit tests for src/portfolio/tracker.py — portfolio valuation."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.portfolio.tracker import PortfolioTracker
from src.utils.exceptions import AccountNotFoundError


def _make_settings():
    s = MagicMock()
    s.default_starting_balance = Decimal("10000")
    return s


def _make_position(*, symbol="BTCUSDT", quantity="0.5", avg_entry="60000", realized_pnl="0"):
    pos = MagicMock()
    pos.symbol = symbol
    pos.quantity = Decimal(quantity)
    pos.avg_entry_price = Decimal(avg_entry)
    pos.realized_pnl = Decimal(realized_pnl)
    return pos


def _make_balance(*, available="8000", locked="500"):
    bal = MagicMock()
    bal.available = Decimal(available)
    bal.locked = Decimal(locked)
    return bal


def _make_tracker(*, session=None, price_cache=None, settings=None):
    if session is None:
        session = AsyncMock()
    if price_cache is None:
        price_cache = AsyncMock()
    if settings is None:
        settings = _make_settings()
    return PortfolioTracker(session, price_cache, settings)


# ---------------------------------------------------------------------------
# get_positions
# ---------------------------------------------------------------------------


class TestGetPositions:
    async def test_empty(self):
        tracker = _make_tracker()
        tracker._fetch_positions = AsyncMock(return_value=[])
        positions = await tracker.get_positions(uuid4())
        assert positions == []

    async def test_with_positions_valued_at_current_price(self):
        tracker = _make_tracker()
        tracker._fetch_positions = AsyncMock(
            return_value=[
                _make_position(symbol="BTCUSDT", quantity="1", avg_entry="60000"),
            ]
        )
        tracker._get_price_safe = AsyncMock(return_value=(Decimal("65000"), True))

        positions = await tracker.get_positions(uuid4())
        assert len(positions) == 1
        assert positions[0].market_value == Decimal("65000")
        assert positions[0].unrealized_pnl == Decimal("5000")
        assert positions[0].price_available is True

    async def test_price_unavailable(self):
        tracker = _make_tracker()
        tracker._fetch_positions = AsyncMock(
            return_value=[
                _make_position(symbol="BTCUSDT", quantity="1", avg_entry="60000"),
            ]
        )
        tracker._get_price_safe = AsyncMock(return_value=(Decimal("0"), False))

        positions = await tracker.get_positions(uuid4())
        assert positions[0].price_available is False
        # Falls back to cost basis
        assert positions[0].market_value == Decimal("60000")

    async def test_unrealized_pnl_calculation(self):
        tracker = _make_tracker()
        tracker._fetch_positions = AsyncMock(
            return_value=[
                _make_position(quantity="2", avg_entry="100"),
            ]
        )
        tracker._get_price_safe = AsyncMock(return_value=(Decimal("120"), True))

        positions = await tracker.get_positions(uuid4())
        # cost_basis=200, market_value=240, unrealized_pnl=40
        assert positions[0].unrealized_pnl == Decimal("40")


# ---------------------------------------------------------------------------
# get_portfolio
# ---------------------------------------------------------------------------


class TestGetPortfolio:
    async def test_no_positions(self):
        tracker = _make_tracker()
        aid = uuid4()
        tracker._get_starting_balance = AsyncMock(return_value=Decimal("10000"))
        tracker._get_usdt_balance = AsyncMock(return_value=_make_balance(available="10000", locked="0"))
        tracker.get_positions = AsyncMock(return_value=[])
        tracker._sum_realized_pnl = AsyncMock(return_value=Decimal("0"))

        summary = await tracker.get_portfolio(aid)
        assert summary.total_equity == Decimal("10000")
        assert summary.total_position_value == Decimal("0")

    async def test_with_positions(self):
        tracker = _make_tracker()
        aid = uuid4()
        tracker._get_starting_balance = AsyncMock(return_value=Decimal("10000"))
        tracker._get_usdt_balance = AsyncMock(return_value=_make_balance(available="5000", locked="0"))

        from src.portfolio.tracker import PositionView

        pos = PositionView(
            symbol="BTCUSDT",
            asset="BTC",
            quantity=Decimal("1"),
            avg_entry_price=Decimal("60000"),
            current_price=Decimal("65000"),
            market_value=Decimal("65000"),
            cost_basis=Decimal("60000"),
            unrealized_pnl=Decimal("5000"),
            unrealized_pnl_pct=Decimal("8.33"),
            realized_pnl=Decimal("0"),
            price_available=True,
        )
        tracker.get_positions = AsyncMock(return_value=[pos])
        tracker._sum_realized_pnl = AsyncMock(return_value=Decimal("100"))

        summary = await tracker.get_portfolio(aid)
        assert summary.total_equity == Decimal("70000")
        assert summary.total_position_value == Decimal("65000")
        assert summary.realized_pnl == Decimal("100")


# ---------------------------------------------------------------------------
# get_pnl
# ---------------------------------------------------------------------------


class TestGetPnl:
    async def test_combines_unrealized_and_realized(self):
        tracker = _make_tracker()
        tracker.get_positions = AsyncMock(return_value=[])
        tracker._sum_realized_pnl = AsyncMock(return_value=Decimal("500"))
        tracker._sum_daily_realized_pnl = AsyncMock(return_value=Decimal("200"))

        pnl = await tracker.get_pnl(uuid4())
        assert pnl.realized_pnl == Decimal("500")
        assert pnl.daily_realized == Decimal("200")
        assert pnl.total_pnl == Decimal("500")  # no unrealized


# ---------------------------------------------------------------------------
# _get_starting_balance
# ---------------------------------------------------------------------------


class TestGetStartingBalance:
    async def test_not_found_raises(self):
        session = AsyncMock()
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result)

        tracker = _make_tracker(session=session)
        with pytest.raises(AccountNotFoundError):
            await tracker._get_starting_balance(uuid4())
