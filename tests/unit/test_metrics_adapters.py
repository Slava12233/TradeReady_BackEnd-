"""Unit tests for unified metrics adapters.

Tests that adapter functions correctly convert domain-specific types
into normalized MetricTradeInput / MetricSnapshotInput.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

from src.database.models import BattleSnapshot, Trade
from src.metrics.adapters import (
    from_battle_snapshots,
    from_db_trades,
    from_sandbox_snapshots,
    from_sandbox_trades,
)
from src.metrics.calculator import MetricSnapshotInput, MetricTradeInput


def _make_sandbox_trade(**kwargs) -> MagicMock:
    """Create a mock SandboxTrade."""
    trade = MagicMock()
    trade.realized_pnl = kwargs.get("realized_pnl", Decimal("50.00"))
    trade.quote_amount = kwargs.get("quote_amount", Decimal("500.00"))
    trade.symbol = kwargs.get("symbol", "BTCUSDT")
    trade.simulated_at = kwargs.get("simulated_at", datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
    return trade


def _make_sandbox_snapshot(**kwargs) -> MagicMock:
    """Create a mock SandboxSnapshot."""
    snap = MagicMock()
    snap.simulated_at = kwargs.get("simulated_at", datetime(2026, 3, 15, 12, 0, tzinfo=UTC))
    snap.total_equity = kwargs.get("total_equity", Decimal("10500.00"))
    return snap


class TestFromSandboxTrades:
    def test_converts_fields(self) -> None:
        """SandboxTrade fields are mapped to MetricTradeInput correctly."""
        trade = _make_sandbox_trade()
        result = from_sandbox_trades([trade])

        assert len(result) == 1
        assert isinstance(result[0], MetricTradeInput)
        assert result[0].realized_pnl == Decimal("50.00")
        assert result[0].quote_amount == Decimal("500.00")
        assert result[0].symbol == "BTCUSDT"
        assert result[0].timestamp == datetime(2026, 3, 15, 12, 0, tzinfo=UTC)

    def test_empty_list(self) -> None:
        """Empty input returns empty output."""
        result = from_sandbox_trades([])

        assert result == []

    def test_multiple_trades_preserves_order(self) -> None:
        """Output order matches input order."""
        t1 = _make_sandbox_trade(symbol="BTCUSDT")
        t2 = _make_sandbox_trade(symbol="ETHUSDT")
        result = from_sandbox_trades([t1, t2])

        assert result[0].symbol == "BTCUSDT"
        assert result[1].symbol == "ETHUSDT"


class TestFromSandboxSnapshots:
    def test_converts_fields(self) -> None:
        """SandboxSnapshot fields are mapped to MetricSnapshotInput correctly."""
        snap = _make_sandbox_snapshot()
        result = from_sandbox_snapshots([snap])

        assert len(result) == 1
        assert isinstance(result[0], MetricSnapshotInput)
        assert result[0].equity == Decimal("10500.00")
        assert result[0].timestamp == datetime(2026, 3, 15, 12, 0, tzinfo=UTC)

    def test_empty_list(self) -> None:
        """Empty input returns empty output."""
        result = from_sandbox_snapshots([])

        assert result == []

    def test_preserves_order(self) -> None:
        """Output order matches input order."""
        s1 = _make_sandbox_snapshot(total_equity=Decimal("10000"))
        s2 = _make_sandbox_snapshot(total_equity=Decimal("10500"))
        result = from_sandbox_snapshots([s1, s2])

        assert result[0].equity == Decimal("10000")
        assert result[1].equity == Decimal("10500")


class TestFromDbTrades:
    def test_converts_fields(self) -> None:
        """DB Trade model fields are mapped to MetricTradeInput correctly."""
        trade = MagicMock(spec=Trade)
        trade.realized_pnl = Decimal("75.50")
        trade.quote_amount = Decimal("1000.00")
        trade.symbol = "ETHUSDT"
        trade.created_at = datetime(2026, 3, 15, 14, 0, tzinfo=UTC)

        result = from_db_trades([trade])

        assert len(result) == 1
        assert isinstance(result[0], MetricTradeInput)
        assert result[0].realized_pnl == Decimal("75.50")
        assert result[0].quote_amount == Decimal("1000.00")
        assert result[0].symbol == "ETHUSDT"
        assert result[0].timestamp == datetime(2026, 3, 15, 14, 0, tzinfo=UTC)

    def test_handles_none_pnl(self) -> None:
        """Trade with None realized_pnl passes through as None."""
        trade = MagicMock(spec=Trade)
        trade.realized_pnl = None
        trade.quote_amount = Decimal("500.00")
        trade.symbol = "BTCUSDT"
        trade.created_at = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)

        result = from_db_trades([trade])

        assert result[0].realized_pnl is None

    def test_empty_list(self) -> None:
        """Empty input returns empty output."""
        result = from_db_trades([])

        assert result == []


class TestFromBattleSnapshots:
    def test_converts_fields(self) -> None:
        """BattleSnapshot fields are mapped to MetricSnapshotInput correctly."""
        snap = MagicMock(spec=BattleSnapshot)
        snap.timestamp = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        snap.equity = Decimal("10200.00")

        result = from_battle_snapshots([snap])

        assert len(result) == 1
        assert isinstance(result[0], MetricSnapshotInput)
        assert result[0].equity == Decimal("10200.00")
        assert result[0].timestamp == datetime(2026, 3, 15, 12, 0, tzinfo=UTC)

    def test_decimal_passthrough(self) -> None:
        """Already-Decimal values are not double-converted."""
        snap = MagicMock(spec=BattleSnapshot)
        snap.timestamp = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        snap.equity = Decimal("10523.45678901")

        result = from_battle_snapshots([snap])

        assert result[0].equity == Decimal("10523.45678901")

    def test_non_decimal_equity_converted(self) -> None:
        """Non-Decimal equity (e.g., float from JSONB) is converted to Decimal."""
        snap = MagicMock(spec=BattleSnapshot)
        snap.timestamp = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
        snap.equity = 10500.50  # float, not Decimal

        result = from_battle_snapshots([snap])

        assert isinstance(result[0].equity, Decimal)
        assert result[0].equity == Decimal("10500.5")

    def test_empty_list(self) -> None:
        """Empty input returns empty output."""
        result = from_battle_snapshots([])

        assert result == []
