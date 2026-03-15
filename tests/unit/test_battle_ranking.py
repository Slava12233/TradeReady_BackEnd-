"""Unit tests for RankingCalculator — all 5 metrics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.battles.ranking import RankingCalculator


@pytest.fixture
def calc():
    return RankingCalculator()


class TestROI:
    def test_positive_roi(self, calc):
        result = calc.calculate_roi(Decimal("10000"), Decimal("11000"))
        assert result == Decimal("10")

    def test_negative_roi(self, calc):
        result = calc.calculate_roi(Decimal("10000"), Decimal("8000"))
        assert result == Decimal("-20")

    def test_zero_balance(self, calc):
        result = calc.calculate_roi(Decimal("0"), Decimal("100"))
        assert result == Decimal("0")

    def test_breakeven(self, calc):
        result = calc.calculate_roi(Decimal("10000"), Decimal("10000"))
        assert result == Decimal("0")


class TestTotalPnL:
    def test_positive_pnl(self, calc):
        result = calc.calculate_total_pnl(Decimal("10000"), Decimal("12500"))
        assert result == Decimal("2500")

    def test_negative_pnl(self, calc):
        result = calc.calculate_total_pnl(Decimal("10000"), Decimal("7500"))
        assert result == Decimal("-2500")


class TestSharpeRatio:
    def test_no_snapshots(self, calc):
        result = calc.calculate_sharpe_ratio([])
        assert result == Decimal("0")

    def test_single_snapshot(self, calc):
        snap = MagicMock()
        snap.equity = Decimal("10000")
        result = calc.calculate_sharpe_ratio([snap])
        assert result == Decimal("0")

    def test_constant_equity(self, calc):
        snaps = []
        for i in range(10):
            snap = MagicMock()
            snap.equity = Decimal("10000")
            snaps.append(snap)
        result = calc.calculate_sharpe_ratio(snaps)
        assert result == Decimal("0")

    def test_increasing_equity(self, calc):
        snaps = []
        for i in range(100):
            snap = MagicMock()
            snap.equity = Decimal(str(10000 + i * 10))
            snaps.append(snap)
        result = calc.calculate_sharpe_ratio(snaps)
        assert result > Decimal("0")


class TestWinRate:
    def test_no_trades(self, calc):
        result = calc.calculate_win_rate([])
        assert result == Decimal("0")

    def test_all_winners(self, calc):
        trades = []
        for _ in range(5):
            t = MagicMock()
            t.realized_pnl = Decimal("100")
            trades.append(t)
        result = calc.calculate_win_rate(trades)
        assert result == Decimal("100.0")

    def test_mixed_trades(self, calc):
        winners = [MagicMock(realized_pnl=Decimal("100")) for _ in range(3)]
        losers = [MagicMock(realized_pnl=Decimal("-50")) for _ in range(2)]
        result = calc.calculate_win_rate(winners + losers)
        assert result == Decimal("60.0")

    def test_no_pnl_trades(self, calc):
        trades = [MagicMock(realized_pnl=None) for _ in range(3)]
        result = calc.calculate_win_rate(trades)
        assert result == Decimal("0")


class TestProfitFactor:
    def test_no_trades(self, calc):
        result = calc.calculate_profit_factor([])
        assert result == Decimal("0")

    def test_only_profits(self, calc):
        trades = [MagicMock(realized_pnl=Decimal("100")) for _ in range(3)]
        result = calc.calculate_profit_factor(trades)
        assert result == Decimal("999.99")

    def test_mixed_trades(self, calc):
        trades = [
            MagicMock(realized_pnl=Decimal("300")),
            MagicMock(realized_pnl=Decimal("-100")),
        ]
        result = calc.calculate_profit_factor(trades)
        assert result == Decimal("3.0")


class TestMaxDrawdown:
    def test_no_snapshots(self, calc):
        result = calc.calculate_max_drawdown([])
        assert result == Decimal("0")

    def test_monotonic_increase(self, calc):
        snaps = []
        for i in range(10):
            snap = MagicMock()
            snap.equity = Decimal(str(10000 + i * 100))
            snaps.append(snap)
        result = calc.calculate_max_drawdown(snaps)
        assert result == Decimal("0")

    def test_drawdown_with_recovery(self, calc):
        equities = [10000, 11000, 9000, 10500]
        snaps = []
        for eq in equities:
            snap = MagicMock()
            snap.equity = Decimal(str(eq))
            snaps.append(snap)
        result = calc.calculate_max_drawdown(snaps)
        # Max DD: from 11000 to 9000 = ~18.18%
        assert result > Decimal("18")
        assert result < Decimal("19")


class TestRankParticipants:
    def test_rank_by_roi(self, calc):
        m1 = MagicMock(agent_id=uuid4(), roi_pct=Decimal("10"))
        m2 = MagicMock(agent_id=uuid4(), roi_pct=Decimal("20"))
        m3 = MagicMock(agent_id=uuid4(), roi_pct=Decimal("5"))

        ranked = calc.rank_participants([m1, m2, m3], "roi_pct")
        assert ranked[0].roi_pct == Decimal("20")
        assert ranked[1].roi_pct == Decimal("10")
        assert ranked[2].roi_pct == Decimal("5")

    def test_rank_by_win_rate(self, calc):
        m1 = MagicMock(agent_id=uuid4(), win_rate=Decimal("60"))
        m2 = MagicMock(agent_id=uuid4(), win_rate=Decimal("80"))

        ranked = calc.rank_participants([m1, m2], "win_rate")
        assert ranked[0].win_rate == Decimal("80")
