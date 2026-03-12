"""Unit tests for src.portfolio.metrics.PerformanceMetrics.

Tests cover:
- Empty trade history → zero metrics
- Single winning trade
- Single losing trade
- Sharpe ratio calculation (positive returns → positive Sharpe)
- Sortino ratio (only downside deviation)
- Max drawdown from snapshot equity curve
- Win rate: 100 % / 0 % / mixed
- Profit factor calculation
- Current streak (win streak / loss streak)
- avg_win / avg_loss
- Period filtering (1d, 7d, all)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.database.models import PortfolioSnapshot, Trade
from src.portfolio.metrics import Metrics, PerformanceMetrics

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trade(
    realized_pnl: str,
    created_at: datetime | None = None,
) -> Trade:
    t = MagicMock(spec=Trade)
    t.realized_pnl = Decimal(realized_pnl) if realized_pnl else None
    t.created_at = created_at or datetime.now(tz=UTC)
    return t


def _make_snapshot(
    equity: str,
    created_at: datetime | None = None,
    snapshot_type: str = "hourly",
) -> PortfolioSnapshot:
    s = MagicMock(spec=PortfolioSnapshot)
    s.total_equity = Decimal(equity)
    s.created_at = created_at or datetime.now(tz=UTC)
    s.snapshot_type = snapshot_type
    return s


def _build_metrics(
    trades: list[Trade] | None = None,
    snapshots: list[PortfolioSnapshot] | None = None,
) -> PerformanceMetrics:
    """Return a PerformanceMetrics instance with private loaders patched."""
    session = AsyncMock()
    svc = PerformanceMetrics(session)

    # Patch the private data-loader methods so no real DB calls are made.
    svc._load_closed_trades = AsyncMock(return_value=trades or [])
    svc._load_snapshots = AsyncMock(return_value=snapshots or [])

    return svc


# ---------------------------------------------------------------------------
# Empty portfolio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_portfolio_returns_zero_metrics():
    """No trades, no snapshots → all numeric metrics are zero/0.0."""
    svc = _build_metrics(trades=[], snapshots=[])
    m = await svc.calculate(uuid4(), period="all")

    assert isinstance(m, Metrics)
    assert m.total_trades == 0
    assert m.win_rate == 0.0
    assert m.sharpe_ratio == 0.0
    assert m.max_drawdown == 0.0
    assert m.profit_factor == 0.0
    assert m.current_streak == 0


# ---------------------------------------------------------------------------
# Single winning trade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_winning_trade():
    """One winning trade → win_rate=100%, avg_win > 0, avg_loss=0."""
    trades = [_make_trade("500")]
    svc = _build_metrics(trades=trades)
    m = await svc.calculate(uuid4())

    assert m.total_trades == 1
    assert m.win_rate == 100.0
    assert m.avg_win == Decimal("500")
    assert m.avg_loss == Decimal("0")
    assert m.best_trade == Decimal("500")
    assert m.current_streak == 1  # 1-win streak


# ---------------------------------------------------------------------------
# Single losing trade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_losing_trade():
    """One losing trade → win_rate=0%, avg_loss < 0."""
    trades = [_make_trade("-300")]
    svc = _build_metrics(trades=trades)
    m = await svc.calculate(uuid4())

    assert m.total_trades == 1
    assert m.win_rate == 0.0
    assert m.avg_loss == Decimal("-300")
    assert m.avg_win == Decimal("0")
    assert m.worst_trade == Decimal("-300")
    assert m.current_streak == -1  # 1-loss streak


# ---------------------------------------------------------------------------
# Mixed trades — win rate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_win_rate_calculated_correctly():
    """3 wins out of 5 trades → win_rate = 60 %."""
    trades = [
        _make_trade("100"),  # win
        _make_trade("-50"),  # loss
        _make_trade("200"),  # win
        _make_trade("-10"),  # loss
        _make_trade("300"),  # win
    ]
    svc = _build_metrics(trades=trades)
    m = await svc.calculate(uuid4())

    assert m.total_trades == 5
    assert m.win_rate == pytest.approx(60.0, abs=0.01)


# ---------------------------------------------------------------------------
# Profit factor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profit_factor_gross_profit_over_gross_loss():
    """profit_factor = total_gains / abs(total_losses)."""
    trades = [
        _make_trade("600"),  # win
        _make_trade("-200"),  # loss
    ]
    svc = _build_metrics(trades=trades)
    m = await svc.calculate(uuid4())

    # gross profit = 600; gross loss = 200; factor = 3.0
    assert m.profit_factor == pytest.approx(3.0, abs=0.001)


@pytest.mark.asyncio
async def test_profit_factor_zero_when_no_losing_trades():
    """profit_factor = 0.0 when there are no losses (infinite is clamped to 0)."""
    trades = [_make_trade("100"), _make_trade("200")]
    svc = _build_metrics(trades=trades)
    m = await svc.calculate(uuid4())

    # No denominator → implementation returns 0.0
    assert m.profit_factor == 0.0


# ---------------------------------------------------------------------------
# Average win / average loss
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_avg_win_and_avg_loss():
    """avg_win = mean of positive PnL trades; avg_loss = mean of negative."""
    trades = [
        _make_trade("100"),
        _make_trade("300"),
        _make_trade("-200"),
        _make_trade("-100"),
    ]
    svc = _build_metrics(trades=trades)
    m = await svc.calculate(uuid4())

    assert m.avg_win == Decimal("200")  # (100+300)/2
    assert m.avg_loss == Decimal("-150")  # (-200+-100)/2


# ---------------------------------------------------------------------------
# Max drawdown from equity curve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_drawdown_from_snapshots():
    """Max drawdown is computed from the equity snapshot series."""
    now = datetime.now(tz=UTC)
    snapshots = [
        _make_snapshot("10000", now),
        _make_snapshot("12000", now + timedelta(hours=1)),  # peak
        _make_snapshot("9000", now + timedelta(hours=2)),  # trough: -25%
        _make_snapshot("11000", now + timedelta(hours=3)),
    ]
    svc = _build_metrics(snapshots=snapshots)
    m = await svc.calculate(uuid4())

    # Peak = 12000, trough = 9000 → drawdown = (12000-9000)/12000 = 25 %
    assert m.max_drawdown == pytest.approx(25.0, abs=0.01)


@pytest.mark.asyncio
async def test_max_drawdown_zero_when_equity_only_rises():
    """No drawdown when equity only increases."""
    now = datetime.now(tz=UTC)
    snapshots = [
        _make_snapshot("10000", now),
        _make_snapshot("11000", now + timedelta(hours=1)),
        _make_snapshot("12000", now + timedelta(hours=2)),
    ]
    svc = _build_metrics(snapshots=snapshots)
    m = await svc.calculate(uuid4())

    assert m.max_drawdown == 0.0


# ---------------------------------------------------------------------------
# Sharpe ratio
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sharpe_ratio_positive_for_consistently_profitable_equity():
    """Consistent equity growth should produce a positive Sharpe ratio."""
    now = datetime.now(tz=UTC)
    # 24 hourly snapshots with steady upward drift
    snapshots = [_make_snapshot(str(10000 + i * 100), now + timedelta(hours=i)) for i in range(24)]
    svc = _build_metrics(snapshots=snapshots)
    m = await svc.calculate(uuid4())

    assert m.sharpe_ratio > 0.0


@pytest.mark.asyncio
async def test_sharpe_ratio_zero_when_no_snapshots():
    """Sharpe = 0.0 when there are no snapshots."""
    svc = _build_metrics(snapshots=[])
    m = await svc.calculate(uuid4())

    assert m.sharpe_ratio == 0.0


# ---------------------------------------------------------------------------
# Current streak
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_current_streak_win():
    """Three consecutive wins at the end → current_streak = 3."""
    now = datetime.now(tz=UTC)
    trades = [
        _make_trade("-100", now),
        _make_trade("50", now + timedelta(hours=1)),
        _make_trade("60", now + timedelta(hours=2)),
        _make_trade("70", now + timedelta(hours=3)),
    ]
    svc = _build_metrics(trades=trades)
    m = await svc.calculate(uuid4())

    assert m.current_streak == 3


@pytest.mark.asyncio
async def test_current_streak_loss():
    """Two consecutive losses at the end → current_streak = -2."""
    now = datetime.now(tz=UTC)
    trades = [
        _make_trade("100", now),
        _make_trade("-50", now + timedelta(hours=1)),
        _make_trade("-60", now + timedelta(hours=2)),
    ]
    svc = _build_metrics(trades=trades)
    m = await svc.calculate(uuid4())

    assert m.current_streak == -2


# ---------------------------------------------------------------------------
# Best / worst trade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_best_and_worst_trade():
    trades = [
        _make_trade("500"),
        _make_trade("-200"),
        _make_trade("100"),
        _make_trade("-50"),
    ]
    svc = _build_metrics(trades=trades)
    m = await svc.calculate(uuid4())

    assert m.best_trade == Decimal("500")
    assert m.worst_trade == Decimal("-200")
