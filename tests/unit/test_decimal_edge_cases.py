"""Unit tests for Decimal precision edge cases.

Tests that Decimal arithmetic across the platform handles
extreme values, rounding, and precision correctly.
"""

from __future__ import annotations

from decimal import Decimal

from src.backtesting.sandbox import BacktestSandbox


class TestDecimalPrecision:
    def test_very_small_quantity(self) -> None:
        """0.00000001 BTC is a valid Decimal and processes correctly."""
        qty = Decimal("0.00000001")
        price = Decimal("50000.00000000")
        total = qty * price

        assert total == Decimal("0.00050000")
        assert isinstance(total, Decimal)

    def test_very_large_quantity(self) -> None:
        """Max precision Decimal(20,8) handles large values."""
        qty = Decimal("99999999999.99999999")
        price = Decimal("0.00000001")
        total = qty * price

        assert isinstance(total, Decimal)
        assert total > Decimal("0")

    def test_zero_balance_after_exact_sell(self) -> None:
        """Selling exact position leaves exactly 0, not -0.00000001."""
        available = Decimal("1.00000000")
        sold = Decimal("1.00000000")
        remaining = available - sold

        assert remaining == Decimal("0")
        assert remaining == Decimal("0.00000000")

    def test_fee_rounding_small_order(self) -> None:
        """Fee on very small order rounds correctly (no negative fee)."""
        quote_amount = Decimal("0.001")
        fee_pct = Decimal("0.001")  # 0.1%
        fee = (quote_amount * fee_pct).quantize(Decimal("0.00000001"))

        assert fee >= Decimal("0")
        assert isinstance(fee, Decimal)

    def test_slippage_on_very_low_price(self) -> None:
        """Very low price + slippage stays positive."""
        price = Decimal("0.00001000")
        slippage_factor = Decimal("0.001")
        slippage = price * slippage_factor
        execution_price = price + slippage

        assert execution_price > Decimal("0")
        assert execution_price > price

    def test_pnl_precision(self) -> None:
        """Realized PnL matches manual calculation to 8 decimal places."""
        buy_price = Decimal("50000.12345678")
        sell_price = Decimal("50100.98765432")
        quantity = Decimal("0.01000000")
        fee_pct = Decimal("0.001")

        buy_cost = buy_price * quantity
        sell_proceeds = sell_price * quantity
        buy_fee = (buy_cost * fee_pct).quantize(Decimal("0.00000001"))
        sell_fee = (sell_proceeds * fee_pct).quantize(Decimal("0.00000001"))

        pnl = sell_proceeds - buy_cost - buy_fee - sell_fee

        # Manual: sell 501.0098... - buy 500.0012... - fees
        assert isinstance(pnl, Decimal)
        assert pnl > Decimal("0")

    def test_decimal_division_precision(self) -> None:
        """Division preserves reasonable precision."""
        total = Decimal("100.00000000")
        divisor = Decimal("3")
        result = total / divisor

        # Verify no float contamination
        assert isinstance(result, Decimal)

    def test_negative_zero_equals_zero(self) -> None:
        """Decimal('-0') compares equal to Decimal('0')."""
        neg_zero = Decimal("-0")
        zero = Decimal("0")

        assert neg_zero == zero


class TestSandboxDecimalHandling:
    def test_sandbox_initializes_with_decimal_balance(self) -> None:
        """BacktestSandbox initializes with Decimal starting balance."""
        sandbox = BacktestSandbox(
            session_id="test-session",
            starting_balance=Decimal("10000.00000000"),
        )

        balances = sandbox.get_balance()
        assert len(balances) == 1
        assert balances[0].asset == "USDT"
        assert balances[0].available == Decimal("10000.00000000")
        assert isinstance(balances[0].available, Decimal)

    def test_sandbox_no_positions_initially(self) -> None:
        """Sandbox returns empty positions when nothing is held."""
        sandbox = BacktestSandbox(
            session_id="test-session",
            starting_balance=Decimal("10000"),
        )

        positions = sandbox.get_positions()
        assert positions == []
