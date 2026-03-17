"""Unit tests for BacktestSandbox risk limit enforcement (Phase 3)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.backtesting.sandbox import BacktestSandbox


@pytest.fixture
def vtime() -> datetime:
    return datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def prices() -> dict[str, Decimal]:
    return {"BTCUSDT": Decimal("50000"), "ETHUSDT": Decimal("3000")}


# ── No risk limits (backward compat) ─────────────────────────────────


def test_no_risk_limits_all_orders_pass(vtime: datetime, prices: dict[str, Decimal]) -> None:
    """When risk_limits is None, all orders should pass (backward compat)."""
    sandbox = BacktestSandbox(
        session_id="test-no-limits",
        starting_balance=Decimal("10000"),
        risk_limits=None,
    )
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    assert result.status == "filled"


# ── Max order size ────────────────────────────────────────────────────


def test_order_rejected_exceeding_max_order_size(vtime: datetime, prices: dict[str, Decimal]) -> None:
    """Order value exceeding max_order_size_pct should be rejected."""
    sandbox = BacktestSandbox(
        session_id="test-max-order",
        starting_balance=Decimal("10000"),
        risk_limits={"max_order_size_pct": 10},  # max 10% of equity per order
    )
    # 0.1 BTC * 50000 = 5000 USDT = 50% of 10000 equity → rejected
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    assert result.status == "rejected"


def test_order_passes_within_max_order_size(vtime: datetime, prices: dict[str, Decimal]) -> None:
    """Order within max_order_size_pct should pass."""
    sandbox = BacktestSandbox(
        session_id="test-max-order-ok",
        starting_balance=Decimal("10000"),
        risk_limits={"max_order_size_pct": 10},  # max 10% = 1000 USDT
    )
    # 0.01 BTC * 50000 = 500 USDT = 5% of equity → pass
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.01"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    assert result.status == "filled"


# ── Max position size ─────────────────────────────────────────────────


def test_order_rejected_position_exceeds_max(vtime: datetime, prices: dict[str, Decimal]) -> None:
    """Buy that would push position above max_position_size_pct should be rejected."""
    sandbox = BacktestSandbox(
        session_id="test-max-pos",
        starting_balance=Decimal("100000"),
        risk_limits={"max_position_size_pct": 20},  # max 20% of equity in one position
    )
    # First buy: 0.2 BTC * 50000 = 10000 = 10% → OK
    r1 = sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.2"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    assert r1.status == "filled"

    # Second buy: 0.3 BTC * 50000 = 15000 → total ~25000 ≈ 25% → rejected
    r2 = sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.3"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    assert r2.status == "rejected"


def test_sell_order_bypasses_position_size_check(vtime: datetime, prices: dict[str, Decimal]) -> None:
    """Sell orders should not be blocked by max_position_size_pct."""
    sandbox = BacktestSandbox(
        session_id="test-sell-bypass",
        starting_balance=Decimal("100000"),
        risk_limits={"max_position_size_pct": 20},
    )
    # Buy some BTC first
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    # Sell should always be allowed (reduces position)
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="sell",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    assert result.status == "filled"


# ── Daily loss limit ──────────────────────────────────────────────────


def test_order_rejected_after_daily_loss_limit(prices: dict[str, Decimal]) -> None:
    """Orders should be rejected after daily realized loss exceeds limit."""
    sandbox = BacktestSandbox(
        session_id="test-daily-loss",
        starting_balance=Decimal("10000"),
        risk_limits={"daily_loss_limit_pct": 5},  # 5% = 500 USDT max daily loss
    )
    vtime = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)

    # Buy BTC
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )

    # Sell at a lower price to realize a loss
    loss_prices = {"BTCUSDT": Decimal("43000"), "ETHUSDT": Decimal("3000")}
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="sell",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=loss_prices,
        virtual_time=datetime(2026, 1, 15, 11, 0, tzinfo=UTC),
    )
    assert result.status == "filled"
    # Realized loss ~700 USDT (price dropped from ~50005 to ~42995.7 with slippage)
    assert result.realized_pnl is not None
    assert result.realized_pnl < Decimal("0")

    # Now try to place another order — should be rejected due to daily loss
    next_result = sandbox.place_order(
        symbol="ETHUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("1"),
        price=None,
        current_prices=loss_prices,
        virtual_time=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
    )
    assert next_result.status == "rejected"


def test_daily_loss_resets_next_day(prices: dict[str, Decimal]) -> None:
    """Daily loss tracking resets on a new day."""
    sandbox = BacktestSandbox(
        session_id="test-daily-reset",
        starting_balance=Decimal("10000"),
        risk_limits={"daily_loss_limit_pct": 5},
    )
    day1 = datetime(2026, 1, 15, 10, 0, tzinfo=UTC)

    # Buy and sell at loss on day 1
    sandbox.place_order(
        symbol="BTCUSDT", side="buy", order_type="market",
        quantity=Decimal("0.1"), price=None, current_prices=prices, virtual_time=day1,
    )
    loss_prices = {"BTCUSDT": Decimal("43000"), "ETHUSDT": Decimal("3000")}
    sandbox.place_order(
        symbol="BTCUSDT", side="sell", order_type="market",
        quantity=Decimal("0.1"), price=None, current_prices=loss_prices,
        virtual_time=datetime(2026, 1, 15, 11, 0, tzinfo=UTC),
    )

    # Day 1 order should be rejected
    r_day1 = sandbox.place_order(
        symbol="ETHUSDT", side="buy", order_type="market",
        quantity=Decimal("1"), price=None, current_prices=loss_prices,
        virtual_time=datetime(2026, 1, 15, 12, 0, tzinfo=UTC),
    )
    assert r_day1.status == "rejected"

    # Day 2 order should pass (new day, loss counter resets)
    day2 = datetime(2026, 1, 16, 10, 0, tzinfo=UTC)
    r_day2 = sandbox.place_order(
        symbol="ETHUSDT", side="buy", order_type="market",
        quantity=Decimal("1"), price=None, current_prices=loss_prices,
        virtual_time=day2,
    )
    assert r_day2.status == "filled"


# ── Combined limits ───────────────────────────────────────────────────


def test_orders_pass_when_within_all_limits(vtime: datetime, prices: dict[str, Decimal]) -> None:
    """Orders within all risk limits should pass normally."""
    sandbox = BacktestSandbox(
        session_id="test-all-limits-ok",
        starting_balance=Decimal("100000"),
        risk_limits={
            "max_order_size_pct": 20,
            "max_position_size_pct": 50,
            "daily_loss_limit_pct": 10,
        },
    )
    # 0.1 BTC * 50000 = 5000 = 5% order size, 5% position → within all limits
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    assert result.status == "filled"


def test_empty_risk_limits_dict_is_no_op(vtime: datetime, prices: dict[str, Decimal]) -> None:
    """Empty risk_limits dict should behave like no limits."""
    sandbox = BacktestSandbox(
        session_id="test-empty-limits",
        starting_balance=Decimal("10000"),
        risk_limits={},
    )
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    assert result.status == "filled"
