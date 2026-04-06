"""Unit tests for src.backtesting.sandbox.BacktestSandbox."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from src.backtesting.sandbox import BacktestSandbox
from src.utils.exceptions import InsufficientBalanceError


@pytest.fixture
def sandbox() -> BacktestSandbox:
    """Sandbox with 10,000 USDT starting balance."""
    return BacktestSandbox(
        session_id="test-session-1",
        starting_balance=Decimal("10000"),
    )


@pytest.fixture
def prices() -> dict[str, Decimal]:
    return {"BTCUSDT": Decimal("50000"), "ETHUSDT": Decimal("3000")}


@pytest.fixture
def vtime() -> datetime:
    return datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


def test_initial_balance_correct(sandbox: BacktestSandbox) -> None:
    balances = sandbox.get_balance()
    assert len(balances) == 1
    assert balances[0].asset == "USDT"
    assert balances[0].available == Decimal("10000")


def test_market_buy_execution(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
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
    assert result.executed_price is not None
    assert result.fee is not None
    assert result.fee > Decimal("0")

    # Should have BTC position
    positions = sandbox.get_positions()
    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].quantity == Decimal("0.1")


def test_market_sell_execution(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    # Buy first
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    # Sell
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
    assert result.realized_pnl is not None

    # Position should be closed
    positions = sandbox.get_positions()
    assert len(positions) == 0


def test_limit_order_pending_then_triggered(
    sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime
) -> None:
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="limit",
        quantity=Decimal("0.1"),
        price=Decimal("49000"),
        current_prices=prices,
        virtual_time=vtime,
    )
    assert result.status == "pending"

    # Price drops to trigger limit buy
    low_prices = {"BTCUSDT": Decimal("48500"), "ETHUSDT": Decimal("3000")}
    filled = sandbox.check_pending_orders(low_prices, vtime)
    assert len(filled) == 1
    assert filled[0].status == "filled"


def test_stop_loss_triggers(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    # Buy BTC first
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    # Place stop-loss sell
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="sell",
        order_type="stop_loss",
        quantity=Decimal("0.1"),
        price=Decimal("48000"),
        current_prices=prices,
        virtual_time=vtime,
    )
    assert result.status == "pending"

    # Price drops below stop
    low_prices = {"BTCUSDT": Decimal("47000"), "ETHUSDT": Decimal("3000")}
    filled = sandbox.check_pending_orders(low_prices, vtime)
    assert len(filled) == 1
    assert filled[0].status == "filled"


def test_insufficient_balance_rejected(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    with pytest.raises(InsufficientBalanceError):
        sandbox.place_order(
            symbol="BTCUSDT",
            side="buy",
            order_type="market",
            quantity=Decimal("1"),  # 50,000 USDT > 10,000 balance
            price=None,
            current_prices=prices,
            virtual_time=vtime,
        )


def test_position_tracking(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    # Buy BTC twice
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.05"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.05"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    positions = sandbox.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == Decimal("0.1")


def test_pnl_calculation(sandbox: BacktestSandbox, vtime: datetime) -> None:
    buy_prices = {"BTCUSDT": Decimal("50000")}
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=buy_prices,
        virtual_time=vtime,
    )
    # Sell at higher price
    sell_prices = {"BTCUSDT": Decimal("55000")}
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="sell",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=sell_prices,
        virtual_time=vtime,
    )
    # PnL should be positive (bought at ~50k, sold at ~55k)
    assert result.realized_pnl is not None
    assert result.realized_pnl > Decimal("0")


def test_close_all_positions(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.05"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    sandbox.place_order(
        symbol="ETHUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.5"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )

    trades = sandbox.close_all_positions(prices, vtime)
    assert len(trades) == 2
    assert len(sandbox.get_positions()) == 0


def test_export_results(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.05"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    sandbox.capture_snapshot(prices, vtime)

    results = sandbox.export_results()
    assert "trades" in results
    assert "snapshots" in results
    assert results["total_trades"] == 1
    assert Decimal(results["total_fees"]) > Decimal("0")


def test_cancel_order(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="limit",
        quantity=Decimal("0.1"),
        price=Decimal("49000"),
        current_prices=prices,
        virtual_time=vtime,
    )
    cancelled = sandbox.cancel_order(result.order_id)
    assert cancelled is True

    # Should not be in pending
    pending = sandbox.get_orders(status="pending")
    assert len(pending) == 0


def test_snapshot_capture(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    snapshot = sandbox.capture_snapshot(prices, vtime)
    assert snapshot.total_equity == Decimal("10000")
    assert snapshot.available_cash == Decimal("10000")
    assert snapshot.position_value == Decimal("0")

    assert len(sandbox.snapshots) == 1


def test_cancel_nonexistent_order(sandbox: BacktestSandbox) -> None:
    assert sandbox.cancel_order("nonexistent-id") is False


def test_order_with_no_price_data(sandbox: BacktestSandbox, vtime: datetime) -> None:
    result = sandbox.place_order(
        symbol="XYZUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("1"),
        price=None,
        current_prices={},
        virtual_time=vtime,
    )
    assert result.status == "rejected"


# ---------------------------------------------------------------------------
# P2 expansion tests
# ---------------------------------------------------------------------------


def test_take_profit_triggers(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    # Buy BTC first
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    # Place take-profit sell
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="sell",
        order_type="take_profit",
        quantity=Decimal("0.1"),
        price=Decimal("52000"),
        current_prices=prices,
        virtual_time=vtime,
    )
    assert result.status == "pending"

    # Price rises above target
    high_prices = {"BTCUSDT": Decimal("53000"), "ETHUSDT": Decimal("3000")}
    filled = sandbox.check_pending_orders(high_prices, vtime)
    assert len(filled) == 1
    assert filled[0].status == "filled"


def test_get_orders_all_statuses(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    # Place a market order (filled) and a limit order (pending)
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.01"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="limit",
        quantity=Decimal("0.01"),
        price=Decimal("49000"),
        current_prices=prices,
        virtual_time=vtime,
    )

    all_orders = sandbox.get_orders()
    assert len(all_orders) == 2

    filled_orders = sandbox.get_orders(status="filled")
    assert len(filled_orders) == 1
    pending_orders = sandbox.get_orders(status="pending")
    assert len(pending_orders) == 1


def test_get_trades_returns_filled_history(
    sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime
) -> None:
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.01"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    assert len(sandbox.trades) == 1
    assert sandbox.trades[0].symbol == "BTCUSDT"


def test_get_portfolio_summary(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    portfolio = sandbox.get_portfolio(prices)
    assert portfolio.total_equity == Decimal("10000")
    assert portfolio.available_cash == Decimal("10000")
    assert portfolio.position_value == Decimal("0")


def test_multiple_symbols_positions(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.01"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    sandbox.place_order(
        symbol="ETHUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.5"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    positions = sandbox.get_positions()
    symbols = {p.symbol for p in positions}
    assert symbols == {"BTCUSDT", "ETHUSDT"}


def test_partial_sell_position(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    # Sell half
    sandbox.place_order(
        symbol="BTCUSDT",
        side="sell",
        order_type="market",
        quantity=Decimal("0.05"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    positions = sandbox.get_positions()
    assert len(positions) == 1
    assert positions[0].quantity == Decimal("0.05")


# ---------------------------------------------------------------------------
# Stop-price / locked_cost regression tests
# ---------------------------------------------------------------------------


def test_stop_loss_sell_triggers_on_price_drop(
    sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime
) -> None:
    """A stop-loss sell placed at 85000 must fill when price drops to 84000."""
    # Buy BTC at 50000 first so we hold a position
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    # Place stop-loss sell at 85000 (above current price — won't trigger yet)
    high_prices = {"BTCUSDT": Decimal("90000"), "ETHUSDT": Decimal("3000")}
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="sell",
        order_type="stop_loss",
        quantity=Decimal("0.1"),
        price=Decimal("85000"),
        current_prices=high_prices,
        virtual_time=vtime,
    )
    assert result.status == "pending"

    # Price drops below the stop trigger
    drop_prices = {"BTCUSDT": Decimal("84000"), "ETHUSDT": Decimal("3000")}
    filled = sandbox.check_pending_orders(drop_prices, vtime)
    assert len(filled) == 1
    assert filled[0].status == "filled"


def test_stop_price_preserved_on_fill(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    """After a stop-loss fills, the SandboxOrder record retains stop_price."""
    # Buy first so we have BTC to sell
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    sandbox.place_order(
        symbol="BTCUSDT",
        side="sell",
        order_type="stop_loss",
        quantity=Decimal("0.1"),
        price=Decimal("48000"),
        current_prices=prices,
        virtual_time=vtime,
    )

    # Trigger the stop
    low_prices = {"BTCUSDT": Decimal("47000"), "ETHUSDT": Decimal("3000")}
    sandbox.check_pending_orders(low_prices, vtime)

    # The filled order (now in _orders with status "filled") should have stop_price set
    filled_orders = sandbox.get_orders(status="filled")
    # Filter to the stop-loss order (the market buy was filled first)
    stop_orders = [o for o in filled_orders if o.type == "stop_loss"]
    assert len(stop_orders) == 1
    assert stop_orders[0].stop_price == Decimal("48000")


def test_filled_order_has_execution_price(
    sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime
) -> None:
    """A filled order must have a non-None executed_price."""
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.05"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    assert result.status == "filled"
    assert result.executed_price is not None
    assert result.executed_price > Decimal("0")


def test_stop_price_in_pending_order(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    """A pending stop-loss order must have stop_price set on the SandboxOrder."""
    # Buy first so we hold BTC
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="sell",
        order_type="stop_loss",
        quantity=Decimal("0.1"),
        price=Decimal("48000"),
        current_prices=prices,
        virtual_time=vtime,
    )
    assert result.status == "pending"

    pending_orders = sandbox.get_orders(status="pending")
    assert len(pending_orders) == 1
    assert pending_orders[0].stop_price == Decimal("48000")


def test_cancel_preserves_stop_price(sandbox: BacktestSandbox, prices: dict[str, Decimal], vtime: datetime) -> None:
    """After cancelling a stop-loss order, the cancelled record keeps stop_price."""
    # Buy first so we hold BTC to sell
    sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="market",
        quantity=Decimal("0.1"),
        price=None,
        current_prices=prices,
        virtual_time=vtime,
    )
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="sell",
        order_type="stop_loss",
        quantity=Decimal("0.1"),
        price=Decimal("48000"),
        current_prices=prices,
        virtual_time=vtime,
    )
    assert result.status == "pending"

    cancelled = sandbox.cancel_order(result.order_id)
    assert cancelled is True

    cancelled_orders = sandbox.get_orders(status="cancelled")
    stop_orders = [o for o in cancelled_orders if o.type == "stop_loss"]
    assert len(stop_orders) == 1
    assert stop_orders[0].stop_price == Decimal("48000")


def test_locked_cost_used_for_unlock(sandbox: BacktestSandbox, vtime: datetime) -> None:
    """Buy-side pending order: USDT is locked at the ref price (locked_cost)
    and correctly unlocked when the order is cancelled."""
    entry_prices = {"BTCUSDT": Decimal("40000")}

    # Place a limit buy — this will lock funds at the ref price
    result = sandbox.place_order(
        symbol="BTCUSDT",
        side="buy",
        order_type="limit",
        quantity=Decimal("0.1"),
        price=Decimal("39000"),  # limit target
        current_prices=entry_prices,
        virtual_time=vtime,
    )
    assert result.status == "pending"

    balance_before_cancel = sandbox.get_balance()
    usdt_before = next(b for b in balance_before_cancel if b.asset == "USDT")
    locked_before = usdt_before.locked
    assert locked_before > Decimal("0"), "USDT should be locked while order is pending"

    # Cancel — funds must be fully unlocked
    cancelled = sandbox.cancel_order(result.order_id)
    assert cancelled is True

    balance_after = sandbox.get_balance()
    usdt_after = next(b for b in balance_after if b.asset == "USDT")
    assert usdt_after.locked == Decimal("0"), "Locked USDT should be zero after cancel"
    # Available should be back to starting balance (no fee charged for pending orders)
    assert usdt_after.available == Decimal("10000")


# ── stop_price persistence tests ────────────────────────────────────────


def test_stop_loss_trade_carries_stop_price(sandbox, prices, vtime):
    """Stop-loss fill should carry stop_price on the resulting SandboxTrade."""
    # Buy first so we have a position to stop-loss
    sandbox.place_order("BTCUSDT", "buy", "market", Decimal("0.1"), None, prices, vtime)

    # Place stop-loss sell at 45000
    sl = sandbox.place_order(
        "BTCUSDT",
        "sell",
        "stop_loss",
        Decimal("0.1"),
        Decimal("45000"),
        prices,
        vtime,
    )
    assert sl.status == "pending"

    # Price drops below stop → trigger
    drop_prices = {"BTCUSDT": Decimal("44000"), "ETHUSDT": Decimal("3000")}
    filled = sandbox.check_pending_orders(drop_prices, vtime)
    assert len(filled) == 1

    # The trade record must carry stop_price
    trades = sandbox.get_trades()
    sl_trade = [t for t in trades if t.type == "stop_loss"]
    assert len(sl_trade) == 1
    assert sl_trade[0].stop_price == Decimal("45000")


def test_take_profit_trade_carries_stop_price(sandbox, prices, vtime):
    """Take-profit fill should carry stop_price on the resulting SandboxTrade."""
    sandbox.place_order("BTCUSDT", "buy", "market", Decimal("0.1"), None, prices, vtime)

    tp = sandbox.place_order(
        "BTCUSDT",
        "sell",
        "take_profit",
        Decimal("0.1"),
        Decimal("55000"),
        prices,
        vtime,
    )
    assert tp.status == "pending"

    rise_prices = {"BTCUSDT": Decimal("56000"), "ETHUSDT": Decimal("3000")}
    filled = sandbox.check_pending_orders(rise_prices, vtime)
    assert len(filled) == 1

    trades = sandbox.get_trades()
    tp_trade = [t for t in trades if t.type == "take_profit"]
    assert len(tp_trade) == 1
    assert tp_trade[0].stop_price == Decimal("55000")


def test_market_order_trade_has_no_stop_price(sandbox, prices, vtime):
    """Market orders should have stop_price=None on the trade record."""
    sandbox.place_order("BTCUSDT", "buy", "market", Decimal("0.1"), None, prices, vtime)
    trades = sandbox.get_trades()
    assert len(trades) == 1
    assert trades[0].stop_price is None


def test_limit_order_trade_has_no_stop_price(sandbox, prices, vtime):
    """Limit orders should have stop_price=None on the trade record."""
    sandbox.place_order(
        "BTCUSDT",
        "buy",
        "limit",
        Decimal("0.1"),
        Decimal("49000"),
        prices,
        vtime,
    )
    # Trigger the limit
    low_prices = {"BTCUSDT": Decimal("48000"), "ETHUSDT": Decimal("3000")}
    filled = sandbox.check_pending_orders(low_prices, vtime)
    assert len(filled) == 1

    trades = sandbox.get_trades()
    limit_trade = [t for t in trades if t.type == "limit"]
    assert len(limit_trade) == 1
    assert limit_trade[0].stop_price is None
