"""Unit tests for RankingCalculator — compute_participant_metrics and rank_participants."""

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


def _make_snapshot(timestamp: datetime, equity: Decimal) -> MagicMock:
    """Create a mock BattleSnapshot with .timestamp and .equity."""
    snap = MagicMock()
    snap.timestamp = timestamp
    snap.equity = equity
    return snap


def _make_trade(
    realized_pnl: Decimal | None,
    quote_amount: Decimal = Decimal("100"),
    symbol: str = "BTCUSDT",
    created_at: datetime | None = None,
) -> MagicMock:
    """Create a mock Trade with required attrs for the adapters."""
    t = MagicMock()
    t.realized_pnl = realized_pnl
    t.quote_amount = quote_amount
    t.symbol = symbol
    t.created_at = created_at or datetime(2025, 1, 1, tzinfo=UTC)
    return t


class TestPositiveROI:
    """compute_participant_metrics returns positive roi/pnl when equity grows."""

    def test_positive_metrics(self, calc: RankingCalculator) -> None:
        agent_id = uuid4()
        start = Decimal("10000")
        final = Decimal("11000")
        base_time = datetime(2025, 1, 1, tzinfo=UTC)

        snapshots = [
            _make_snapshot(base_time, Decimal("10000")),
            _make_snapshot(base_time + timedelta(seconds=5), Decimal("10500")),
            _make_snapshot(base_time + timedelta(seconds=10), Decimal("11000")),
        ]

        result = calc.compute_participant_metrics(
            agent_id=agent_id,
            start_balance=start,
            final_equity=final,
            snapshots=snapshots,
            trades=[],
        )

        assert result.agent_id == agent_id
        assert result.start_equity == start
        assert result.final_equity == final
        assert result.roi_pct > Decimal("0")
        assert result.total_pnl > Decimal("0")


class TestNegativeROI:
    """compute_participant_metrics returns negative roi/pnl when equity drops."""

    def test_negative_metrics(self, calc: RankingCalculator) -> None:
        agent_id = uuid4()
        start = Decimal("10000")
        final = Decimal("8000")
        base_time = datetime(2025, 1, 1, tzinfo=UTC)

        snapshots = [
            _make_snapshot(base_time, Decimal("10000")),
            _make_snapshot(base_time + timedelta(seconds=5), Decimal("9000")),
            _make_snapshot(base_time + timedelta(seconds=10), Decimal("8000")),
        ]

        result = calc.compute_participant_metrics(
            agent_id=agent_id,
            start_balance=start,
            final_equity=final,
            snapshots=snapshots,
            trades=[],
        )

        assert result.roi_pct < Decimal("0")
        assert result.total_pnl < Decimal("0")


class TestNoTradesNoSnapshots:
    """compute_participant_metrics returns zeroed metrics with empty inputs."""

    def test_zeroed_metrics(self, calc: RankingCalculator) -> None:
        agent_id = uuid4()
        start = Decimal("10000")

        result = calc.compute_participant_metrics(
            agent_id=agent_id,
            start_balance=start,
            final_equity=start,
            snapshots=[],
            trades=[],
        )

        assert result.roi_pct == Decimal("0")
        assert result.total_pnl == Decimal("0")
        assert result.total_trades == 0
        assert result.win_rate == Decimal("0")
        assert result.max_drawdown == Decimal("0")


class TestWinningTrades:
    """compute_participant_metrics calculates win_rate > 0 with winners."""

    def test_win_rate_positive(self, calc: RankingCalculator) -> None:
        agent_id = uuid4()
        start = Decimal("10000")
        base_time = datetime(2025, 1, 1, tzinfo=UTC)

        snapshots = [
            _make_snapshot(base_time, Decimal("10000")),
            _make_snapshot(base_time + timedelta(seconds=5), Decimal("10300")),
        ]

        trades = [
            _make_trade(Decimal("100"), created_at=base_time + timedelta(seconds=1)),
            _make_trade(Decimal("200"), created_at=base_time + timedelta(seconds=2)),
        ]

        result = calc.compute_participant_metrics(
            agent_id=agent_id,
            start_balance=start,
            final_equity=Decimal("10300"),
            snapshots=snapshots,
            trades=trades,
        )

        assert result.win_rate == Decimal("100.00")
        assert result.total_trades == 2


class TestMixedTrades:
    """compute_participant_metrics calculates profit_factor from mixed trades."""

    def test_profit_factor(self, calc: RankingCalculator) -> None:
        agent_id = uuid4()
        start = Decimal("10000")
        base_time = datetime(2025, 1, 1, tzinfo=UTC)

        snapshots = [
            _make_snapshot(base_time, Decimal("10000")),
            _make_snapshot(base_time + timedelta(seconds=5), Decimal("10200")),
        ]

        # 300 gross profit, 100 gross loss → profit_factor = 3.0
        trades = [
            _make_trade(Decimal("300"), created_at=base_time + timedelta(seconds=1)),
            _make_trade(Decimal("-100"), created_at=base_time + timedelta(seconds=2)),
        ]

        result = calc.compute_participant_metrics(
            agent_id=agent_id,
            start_balance=start,
            final_equity=Decimal("10200"),
            snapshots=snapshots,
            trades=trades,
        )

        assert result.profit_factor == Decimal("3.0000")
        assert result.win_rate == Decimal("50.00")
        assert result.total_trades == 2


class TestDrawdown:
    """compute_participant_metrics detects drawdown from equity curve."""

    def test_max_drawdown_positive(self, calc: RankingCalculator) -> None:
        agent_id = uuid4()
        start = Decimal("10000")
        base_time = datetime(2025, 1, 1, tzinfo=UTC)

        # Peak at 11000, trough at 9000 → ~18.18% drawdown
        snapshots = [
            _make_snapshot(base_time, Decimal("10000")),
            _make_snapshot(base_time + timedelta(seconds=5), Decimal("11000")),
            _make_snapshot(base_time + timedelta(seconds=10), Decimal("9000")),
            _make_snapshot(base_time + timedelta(seconds=15), Decimal("10500")),
        ]

        result = calc.compute_participant_metrics(
            agent_id=agent_id,
            start_balance=start,
            final_equity=Decimal("10500"),
            snapshots=snapshots,
            trades=[],
        )

        assert result.max_drawdown > Decimal("18")
        assert result.max_drawdown < Decimal("19")


class TestRankParticipants:
    def test_rank_by_roi(self, calc: RankingCalculator) -> None:
        m1 = MagicMock(agent_id=uuid4(), roi_pct=Decimal("10"))
        m2 = MagicMock(agent_id=uuid4(), roi_pct=Decimal("20"))
        m3 = MagicMock(agent_id=uuid4(), roi_pct=Decimal("5"))

        ranked = calc.rank_participants([m1, m2, m3], "roi_pct")
        assert ranked[0].roi_pct == Decimal("20")
        assert ranked[1].roi_pct == Decimal("10")
        assert ranked[2].roi_pct == Decimal("5")

    def test_rank_by_win_rate(self, calc: RankingCalculator) -> None:
        m1 = MagicMock(agent_id=uuid4(), win_rate=Decimal("60"))
        m2 = MagicMock(agent_id=uuid4(), win_rate=Decimal("80"))

        ranked = calc.rank_participants([m1, m2], "win_rate")
        assert ranked[0].win_rate == Decimal("80")
