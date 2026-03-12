"""Unit tests for src/order_engine/matching.py — limit order matcher."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from src.order_engine.matching import LimitOrderMatcher, _condition_met


def _make_order(*, order_type="limit", side="buy", price="60000", symbol="BTCUSDT"):
    """Return a mock Order row."""
    order = MagicMock()
    order.id = MagicMock()
    order.type = order_type
    order.side = side
    order.price = Decimal(price) if price else None
    order.symbol = symbol
    order.account_id = MagicMock()
    return order


# ---------------------------------------------------------------------------
# _condition_met — pure function
# ---------------------------------------------------------------------------


class TestConditionMet:
    def test_limit_buy_price_below(self):
        order = _make_order(order_type="limit", side="buy", price="60000")
        assert _condition_met(order, Decimal("59000"), Decimal("60000")) is True

    def test_limit_buy_price_above(self):
        order = _make_order(order_type="limit", side="buy", price="60000")
        assert _condition_met(order, Decimal("61000"), Decimal("60000")) is False

    def test_limit_buy_price_equal(self):
        order = _make_order(order_type="limit", side="buy", price="60000")
        assert _condition_met(order, Decimal("60000"), Decimal("60000")) is True

    def test_limit_sell_price_above(self):
        order = _make_order(order_type="limit", side="sell", price="60000")
        assert _condition_met(order, Decimal("61000"), Decimal("60000")) is True

    def test_limit_sell_price_below(self):
        order = _make_order(order_type="limit", side="sell", price="60000")
        assert _condition_met(order, Decimal("59000"), Decimal("60000")) is False

    def test_stop_loss_triggers(self):
        order = _make_order(order_type="stop_loss", price="55000")
        assert _condition_met(order, Decimal("54000"), Decimal("55000")) is True

    def test_stop_loss_not_triggered(self):
        order = _make_order(order_type="stop_loss", price="55000")
        assert _condition_met(order, Decimal("56000"), Decimal("55000")) is False

    def test_take_profit_triggers(self):
        order = _make_order(order_type="take_profit", price="70000")
        assert _condition_met(order, Decimal("71000"), Decimal("70000")) is True

    def test_take_profit_not_triggered(self):
        order = _make_order(order_type="take_profit", price="70000")
        assert _condition_met(order, Decimal("69000"), Decimal("70000")) is False

    def test_unknown_type_returns_false(self):
        order = _make_order(order_type="trailing_stop", price="60000")
        assert _condition_met(order, Decimal("60000"), Decimal("60000")) is False


# ---------------------------------------------------------------------------
# check_order
# ---------------------------------------------------------------------------


class TestCheckOrder:
    def _make_matcher(self, price_return=None):
        price_cache = AsyncMock()
        price_cache.get_price = AsyncMock(return_value=price_return)
        session_factory = AsyncMock()
        matcher = LimitOrderMatcher(
            session_factory=session_factory,
            price_cache=price_cache,
            balance_manager_factory=MagicMock(),
            slippage_calculator=MagicMock(),
        )
        return matcher

    async def test_no_price_available_skips(self):
        matcher = self._make_matcher(price_return=None)
        order = _make_order(price="60000")
        result = await matcher.check_order(order)
        assert result is None

    async def test_missing_order_price_skips(self):
        matcher = self._make_matcher(price_return=Decimal("60000"))
        order = _make_order(price=None)
        order.price = None
        result = await matcher.check_order(order)
        assert result is None


# ---------------------------------------------------------------------------
# check_all_pending
# ---------------------------------------------------------------------------


class TestCheckAllPending:
    async def test_empty_orders(self):
        price_cache = AsyncMock()
        session_factory = AsyncMock()
        matcher = LimitOrderMatcher(
            session_factory=session_factory,
            price_cache=price_cache,
            balance_manager_factory=MagicMock(),
            slippage_calculator=MagicMock(),
        )
        matcher._fetch_pending_page = AsyncMock(return_value=[])

        stats = await matcher.check_all_pending()
        assert stats.orders_checked == 0
        assert stats.orders_filled == 0
