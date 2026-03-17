"""Unit tests for src.metrics.calculator — unified metrics calculator."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from src.metrics.calculator import (
    MetricSnapshotInput,
    MetricTradeInput,
    calculate_unified_metrics,
)

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _trade(
    pnl: Decimal | None = None,
    quote: Decimal = Decimal("5000"),
    symbol: str = "BTCUSDT",
    minutes_offset: int = 0,
) -> MetricTradeInput:
    return MetricTradeInput(
        realized_pnl=pnl,
        quote_amount=quote,
        symbol=symbol,
        timestamp=_BASE + timedelta(minutes=minutes_offset),
    )


def _snapshot(equity: Decimal, hours_offset: int = 0) -> MetricSnapshotInput:
    return MetricSnapshotInput(
        timestamp=_BASE + timedelta(hours=hours_offset),
        equity=equity,
    )


class TestTradeMetrics:
    """Tests for trade-based metrics (win rate, profit factor, etc.)."""

    def test_known_trades_win_rate(self) -> None:
        trades = [
            _trade(pnl=Decimal("100"), minutes_offset=0),
            _trade(pnl=Decimal("200"), minutes_offset=1),
            _trade(pnl=Decimal("-50"), minutes_offset=2),
            _trade(pnl=Decimal("-30"), minutes_offset=3),
        ]
        snaps = [_snapshot(Decimal("10000"), 0), _snapshot(Decimal("10220"), 24)]

        result = calculate_unified_metrics(
            trades=trades,
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        # 2 wins out of 4 trades = 50%
        assert result.win_rate == Decimal("50.00")
        assert result.total_trades == 4

    def test_known_trades_profit_factor(self) -> None:
        trades = [
            _trade(pnl=Decimal("300"), minutes_offset=0),
            _trade(pnl=Decimal("-100"), minutes_offset=1),
        ]
        snaps = [_snapshot(Decimal("10000"), 0), _snapshot(Decimal("10200"), 24)]

        result = calculate_unified_metrics(
            trades=trades,
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        # profit_factor = 300 / 100 = 3.0
        assert result.profit_factor == Decimal("3.0000")

    def test_known_trades_avg_win_loss(self) -> None:
        trades = [
            _trade(pnl=Decimal("100"), minutes_offset=0),
            _trade(pnl=Decimal("200"), minutes_offset=1),
            _trade(pnl=Decimal("-50"), minutes_offset=2),
        ]
        snaps = [_snapshot(Decimal("10000"), 0), _snapshot(Decimal("10250"), 24)]

        result = calculate_unified_metrics(
            trades=trades,
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        assert result.avg_win == Decimal("150.00000000")
        assert result.avg_loss == Decimal("-50.00000000")
        assert result.best_trade == Decimal("200")
        assert result.worst_trade == Decimal("-50")

    def test_empty_trades_safe_defaults(self) -> None:
        result = calculate_unified_metrics(
            trades=[],
            snapshots=[_snapshot(Decimal("10000"), 0)],
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        assert result.win_rate == Decimal("0")
        assert result.profit_factor is None
        assert result.avg_win == Decimal("0")
        assert result.avg_loss == Decimal("0")
        assert result.best_trade == Decimal("0")
        assert result.worst_trade == Decimal("0")
        assert result.total_trades == 0
        assert result.trades_per_day == Decimal("0.00")

    def test_no_losses_profit_factor_none(self) -> None:
        trades = [_trade(pnl=Decimal("100"), minutes_offset=0)]
        snaps = [_snapshot(Decimal("10000"), 0), _snapshot(Decimal("10100"), 24)]

        result = calculate_unified_metrics(
            trades=trades,
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        # No losses → profit_factor is None
        assert result.profit_factor is None


class TestDrawdownMetrics:
    """Tests for drawdown calculation."""

    def test_max_drawdown(self) -> None:
        snaps = [
            _snapshot(Decimal("10000"), 0),
            _snapshot(Decimal("11000"), 1),  # peak
            _snapshot(Decimal("9900"), 2),  # 10% drawdown from 11000
            _snapshot(Decimal("10500"), 3),
        ]

        result = calculate_unified_metrics(
            trades=[],
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        assert result.max_drawdown_pct == Decimal("10.00")

    def test_no_drawdown(self) -> None:
        snaps = [
            _snapshot(Decimal("10000"), 0),
            _snapshot(Decimal("10500"), 1),
            _snapshot(Decimal("11000"), 2),
        ]

        result = calculate_unified_metrics(
            trades=[],
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        assert result.max_drawdown_pct == Decimal("0")


class TestSharpeAndSortino:
    """Tests for Sharpe and Sortino ratio computation."""

    def test_single_snapshot_returns_none(self) -> None:
        result = calculate_unified_metrics(
            trades=[],
            snapshots=[_snapshot(Decimal("10000"), 0)],
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        assert result.sharpe_ratio is None
        assert result.sortino_ratio is None

    def test_two_snapshots_insufficient_returns_none(self) -> None:
        """Two snapshots give only 1 return → need at least 2 returns."""
        snaps = [_snapshot(Decimal("10000"), 0), _snapshot(Decimal("10100"), 1)]

        result = calculate_unified_metrics(
            trades=[],
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        assert result.sharpe_ratio is None
        assert result.sortino_ratio is None

    def test_positive_returns_sharpe_positive(self) -> None:
        snaps = [
            _snapshot(Decimal("10000"), 0),
            _snapshot(Decimal("10100"), 1),
            _snapshot(Decimal("10250"), 2),
            _snapshot(Decimal("10400"), 3),
        ]

        result = calculate_unified_metrics(
            trades=[],
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        assert result.sharpe_ratio is not None
        assert result.sharpe_ratio > Decimal("0")

    def test_all_positive_returns_sortino_none(self) -> None:
        """All positive returns → no downside deviation → Sortino is None."""
        snaps = [
            _snapshot(Decimal("10000"), 0),
            _snapshot(Decimal("10100"), 1),
            _snapshot(Decimal("10200"), 2),
            _snapshot(Decimal("10300"), 3),
        ]

        result = calculate_unified_metrics(
            trades=[],
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        assert result.sortino_ratio is None

    def test_mixed_returns_sortino_computed(self) -> None:
        snaps = [
            _snapshot(Decimal("10000"), 0),
            _snapshot(Decimal("10100"), 1),
            _snapshot(Decimal("9900"), 2),
            _snapshot(Decimal("10200"), 3),
        ]

        result = calculate_unified_metrics(
            trades=[],
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        assert result.sortino_ratio is not None


class TestAnnualization:
    """Tests for different snapshot_interval_seconds values."""

    def test_different_intervals_produce_different_sharpe(self) -> None:
        snaps = [
            _snapshot(Decimal("10000"), 0),
            _snapshot(Decimal("10100"), 1),
            _snapshot(Decimal("9950"), 2),
            _snapshot(Decimal("10200"), 3),
        ]

        result_daily = calculate_unified_metrics(
            trades=[],
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
            snapshot_interval_seconds=86400,
        )

        result_5s = calculate_unified_metrics(
            trades=[],
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
            snapshot_interval_seconds=5,
        )

        # Both should have Sharpe values but different due to annualization
        assert result_daily.sharpe_ratio is not None
        assert result_5s.sharpe_ratio is not None
        assert result_daily.sharpe_ratio != result_5s.sharpe_ratio


class TestRoiAndPnl:
    """Tests for ROI and PnL calculation."""

    def test_roi_calculation(self) -> None:
        snaps = [_snapshot(Decimal("10000"), 0), _snapshot(Decimal("11000"), 24)]

        result = calculate_unified_metrics(
            trades=[],
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        assert result.roi_pct == Decimal("10.00")
        assert result.total_pnl == Decimal("1000")

    def test_negative_roi(self) -> None:
        snaps = [_snapshot(Decimal("10000"), 0), _snapshot(Decimal("9000"), 24)]

        result = calculate_unified_metrics(
            trades=[],
            snapshots=snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        assert result.roi_pct == Decimal("-10.00")
        assert result.total_pnl == Decimal("-1000")
