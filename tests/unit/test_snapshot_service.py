"""Unit tests for src/portfolio/snapshots.py — SnapshotService."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.portfolio.snapshots import SnapshotService


def _make_portfolio_summary(
    *,
    total_equity=Decimal("10000"),
    available_cash=Decimal("9000"),
    total_position_value=Decimal("1000"),
    unrealized_pnl=Decimal("50"),
    realized_pnl=Decimal("100"),
    positions=None,
):
    summary = MagicMock()
    summary.total_equity = total_equity
    summary.available_cash = available_cash
    summary.total_position_value = total_position_value
    summary.unrealized_pnl = unrealized_pnl
    summary.realized_pnl = realized_pnl
    summary.positions = positions or []
    return summary


def _make_service():
    session = AsyncMock()
    price_cache = AsyncMock()
    settings = MagicMock()
    settings.default_starting_balance = Decimal("10000")

    svc = SnapshotService(session, price_cache, settings)
    svc._repo = AsyncMock()
    svc._repo.create = AsyncMock()
    svc._repo.get_history = AsyncMock(return_value=[])
    return svc


class TestCaptureMinuteSnapshot:
    async def test_creates_row(self):
        svc = _make_service()
        svc._tracker = AsyncMock()
        svc._tracker.get_portfolio = AsyncMock(return_value=_make_portfolio_summary())

        await svc.capture_minute_snapshot(uuid4())
        svc._repo.create.assert_called_once()
        # Verify snapshot_type
        snap = svc._repo.create.call_args[0][0]
        assert snap.snapshot_type == "minute"
        assert snap.positions is None
        assert snap.metrics is None


class TestCaptureHourlySnapshot:
    async def test_includes_positions(self):
        svc = _make_service()
        pos = MagicMock()
        pos.symbol = "BTCUSDT"
        pos.asset = "BTC"
        pos.quantity = Decimal("0.1")
        pos.avg_entry_price = Decimal("60000")
        pos.current_price = Decimal("65000")
        pos.market_value = Decimal("6500")
        pos.cost_basis = Decimal("6000")
        pos.unrealized_pnl = Decimal("500")
        pos.unrealized_pnl_pct = Decimal("8.33")
        pos.realized_pnl = Decimal("0")
        pos.price_available = True

        svc._tracker = AsyncMock()
        svc._tracker.get_portfolio = AsyncMock(return_value=_make_portfolio_summary(positions=[pos]))

        await svc.capture_hourly_snapshot(uuid4())
        snap = svc._repo.create.call_args[0][0]
        assert snap.snapshot_type == "hourly"
        assert snap.positions is not None
        assert len(snap.positions) == 1
        assert snap.metrics is None


class TestCaptureDailySnapshot:
    async def test_includes_metrics(self):
        svc = _make_service()
        svc._tracker = AsyncMock()
        svc._tracker.get_portfolio = AsyncMock(return_value=_make_portfolio_summary())

        metrics = MagicMock()
        metrics.period = "all"
        metrics.sharpe_ratio = 1.5
        metrics.sortino_ratio = 2.0
        metrics.max_drawdown = 5.0
        metrics.max_drawdown_duration = 3
        metrics.win_rate = 60.0
        metrics.profit_factor = 1.8
        metrics.avg_win = Decimal("100")
        metrics.avg_loss = Decimal("-50")
        metrics.total_trades = 20
        metrics.avg_trades_per_day = 2.0
        metrics.best_trade = Decimal("500")
        metrics.worst_trade = Decimal("-200")
        metrics.current_streak = 3
        svc._perf = AsyncMock()
        svc._perf.calculate = AsyncMock(return_value=metrics)

        await svc.capture_daily_snapshot(uuid4())
        snap = svc._repo.create.call_args[0][0]
        assert snap.snapshot_type == "daily"
        assert snap.metrics is not None
        assert snap.positions is not None


class TestGetSnapshotHistory:
    async def test_returns_typed_snapshots(self):
        svc = _make_service()
        row = MagicMock()
        row.id = uuid4()
        row.account_id = uuid4()
        row.snapshot_type = "minute"
        row.total_equity = 10000.0
        row.available_cash = 9000.0
        row.position_value = 1000.0
        row.unrealized_pnl = 50.0
        row.realized_pnl = 100.0
        row.positions = None
        row.metrics = None
        row.created_at = datetime.now(tz=UTC)
        svc._repo.get_history = AsyncMock(return_value=[row])

        result = await svc.get_snapshot_history(uuid4(), "minute", limit=10)
        assert len(result) == 1
        assert isinstance(result[0].total_equity, Decimal)
        assert result[0].snapshot_type == "minute"
