"""Unit tests for src/order_engine/validators.py — order pre-flight checks."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.order_engine.validators import OrderRequest, OrderValidator
from src.utils.exceptions import (
    InputValidationError,
    InvalidOrderTypeError,
    InvalidQuantityError,
    InvalidSymbolError,
)


def _make_request(**overrides) -> OrderRequest:
    """Build a valid OrderRequest, overriding any fields."""
    defaults = {
        "symbol": "BTCUSDT",
        "side": "buy",
        "type": "market",
        "quantity": Decimal("0.5"),
        "price": None,
    }
    defaults.update(overrides)
    return OrderRequest(**defaults)


def _make_pair(*, symbol="BTCUSDT", status="active", min_qty=None, max_qty=None, min_notional=None):
    """Return a mock TradingPair row."""
    pair = MagicMock()
    pair.symbol = symbol
    pair.status = status
    pair.min_qty = min_qty
    pair.max_qty = max_qty
    pair.min_notional = min_notional
    pair.base_asset = symbol.replace("USDT", "")
    pair.quote_asset = "USDT"
    return pair


def _mock_session_returning(pair):
    """Return a mock AsyncSession whose execute() returns the given pair."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = pair
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


# ---------------------------------------------------------------------------
# Side validation
# ---------------------------------------------------------------------------


class TestSideValidation:
    async def test_invalid_side_raises(self):
        session = _mock_session_returning(_make_pair())
        v = OrderValidator(session)
        with pytest.raises(InputValidationError, match="side"):
            await v.validate(_make_request(side="hold"))


# ---------------------------------------------------------------------------
# Type validation
# ---------------------------------------------------------------------------


class TestTypeValidation:
    async def test_invalid_type_raises(self):
        session = _mock_session_returning(_make_pair())
        v = OrderValidator(session)
        with pytest.raises(InvalidOrderTypeError):
            await v.validate(_make_request(type="trailing_stop"))


# ---------------------------------------------------------------------------
# Quantity validation
# ---------------------------------------------------------------------------


class TestQuantityValidation:
    async def test_zero_quantity_raises(self):
        session = _mock_session_returning(_make_pair())
        v = OrderValidator(session)
        with pytest.raises(InvalidQuantityError):
            await v.validate(_make_request(quantity=Decimal("0")))

    async def test_negative_quantity_raises(self):
        session = _mock_session_returning(_make_pair())
        v = OrderValidator(session)
        with pytest.raises(InvalidQuantityError):
            await v.validate(_make_request(quantity=Decimal("-1")))


# ---------------------------------------------------------------------------
# Price validation
# ---------------------------------------------------------------------------


class TestPriceValidation:
    async def test_limit_order_missing_price_raises(self):
        session = _mock_session_returning(_make_pair())
        v = OrderValidator(session)
        with pytest.raises(InputValidationError, match="price"):
            await v.validate(_make_request(type="limit", price=None))

    async def test_limit_order_zero_price_raises(self):
        session = _mock_session_returning(_make_pair())
        v = OrderValidator(session)
        with pytest.raises(InputValidationError, match="price"):
            await v.validate(_make_request(type="limit", price=Decimal("0")))

    async def test_stop_loss_missing_price_raises(self):
        session = _mock_session_returning(_make_pair())
        v = OrderValidator(session)
        with pytest.raises(InputValidationError, match="price"):
            await v.validate(_make_request(type="stop_loss", price=None))

    async def test_take_profit_missing_price_raises(self):
        session = _mock_session_returning(_make_pair())
        v = OrderValidator(session)
        with pytest.raises(InputValidationError, match="price"):
            await v.validate(_make_request(type="take_profit", price=None))

    async def test_market_order_price_ignored(self):
        pair = _make_pair()
        session = _mock_session_returning(pair)
        v = OrderValidator(session)
        # price=Decimal("100") should be silently ignored for market orders
        result = await v.validate(_make_request(type="market", price=Decimal("100")))
        assert result.symbol == "BTCUSDT"


# ---------------------------------------------------------------------------
# Symbol validation
# ---------------------------------------------------------------------------


class TestSymbolValidation:
    async def test_symbol_not_found_raises(self):
        session = _mock_session_returning(None)
        v = OrderValidator(session)
        with pytest.raises(InvalidSymbolError):
            await v.validate(_make_request(symbol="FOOBAR"))

    async def test_symbol_inactive_raises(self):
        pair = _make_pair(status="delisted")
        session = _mock_session_returning(pair)
        v = OrderValidator(session)
        with pytest.raises(InvalidSymbolError, match="not active"):
            await v.validate(_make_request())


# ---------------------------------------------------------------------------
# Pair limits
# ---------------------------------------------------------------------------


class TestPairLimits:
    async def test_quantity_below_min_qty_raises(self):
        pair = _make_pair(min_qty=Decimal("0.01"))
        session = _mock_session_returning(pair)
        v = OrderValidator(session)
        with pytest.raises(InvalidQuantityError, match="below the minimum"):
            await v.validate(_make_request(quantity=Decimal("0.001")))

    async def test_notional_below_min_notional_raises(self):
        pair = _make_pair(min_notional=Decimal("10"))
        session = _mock_session_returning(pair)
        v = OrderValidator(session)
        # quantity=0.0001 * price=100 = 0.01 notional, below 10
        with pytest.raises(InvalidQuantityError, match="notional"):
            await v.validate(_make_request(type="limit", quantity=Decimal("0.0001"), price=Decimal("100")))


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestHappyPath:
    async def test_valid_market_buy_passes(self):
        pair = _make_pair()
        session = _mock_session_returning(pair)
        v = OrderValidator(session)
        result = await v.validate(_make_request())
        assert result.symbol == "BTCUSDT"

    async def test_valid_limit_sell_passes(self):
        pair = _make_pair()
        session = _mock_session_returning(pair)
        v = OrderValidator(session)
        result = await v.validate(_make_request(side="sell", type="limit", price=Decimal("65000")))
        assert result.symbol == "BTCUSDT"
