"""Unit tests for src.backtesting.results — metrics calculator."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.backtesting.results import (
    calculate_metrics,
    calculate_per_pair_stats,
    generate_equity_curve,
)
from src.backtesting.sandbox import SandboxSnapshot, SandboxTrade


def _trade(
    symbol: str = "BTCUSDT",
    side: str = "sell",
    pnl: Decimal | None = None,
    minutes_offset: int = 0,
) -> SandboxTrade:
    return SandboxTrade(
        id=f"t-{minutes_offset}",
        symbol=symbol,
        side=side,
        type="market",
        quantity=Decimal("0.1"),
        price=Decimal("50000"),
        quote_amount=Decimal("5000"),
        fee=Decimal("5"),
        slippage_pct=Decimal("0.01"),
        realized_pnl=pnl,
        simulated_at=datetime(2026, 1, 1, 0, minutes_offset, tzinfo=timezone.utc),
    )


def _snapshot(equity: Decimal, hours_offset: int = 0) -> SandboxSnapshot:
    return SandboxSnapshot(
        simulated_at=datetime(2026, 1, 1, hours_offset, 0, tzinfo=timezone.utc),
        total_equity=equity,
        available_cash=equity,
        position_value=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        positions={},
    )


def test_win_rate_calculation() -> None:
    trades = [
        _trade(pnl=Decimal("100"), minutes_offset=0),
        _trade(pnl=Decimal("200"), minutes_offset=1),
        _trade(pnl=Decimal("-50"), minutes_offset=2),
        _trade(pnl=Decimal("150"), minutes_offset=3),
    ]
    metrics = calculate_metrics(trades, [], Decimal("10000"), Decimal("7"))
    assert metrics.win_rate == Decimal("75.00")


def test_profit_factor_calculation() -> None:
    trades = [
        _trade(pnl=Decimal("300"), minutes_offset=0),
        _trade(pnl=Decimal("-100"), minutes_offset=1),
    ]
    metrics = calculate_metrics(trades, [], Decimal("10000"), Decimal("7"))
    assert metrics.profit_factor == Decimal("3.0000")


def test_max_drawdown_calculation() -> None:
    snapshots = [
        _snapshot(Decimal("10000"), 0),
        _snapshot(Decimal("11000"), 1),  # peak
        _snapshot(Decimal("9900"), 2),   # drawdown = (11000-9900)/11000 = 10%
        _snapshot(Decimal("10500"), 3),
    ]
    metrics = calculate_metrics([], snapshots, Decimal("10000"), Decimal("1"))
    assert metrics.max_drawdown_pct == Decimal("10.00")


def test_sharpe_ratio_calculation() -> None:
    # 5 days of returns to get a Sharpe
    snapshots = [
        _snapshot(Decimal("10000"), 0),
    ]
    # Add daily snapshots over 5 days
    for day in range(1, 6):
        equity = Decimal("10000") + Decimal(str(day * 100))
        snapshots.append(SandboxSnapshot(
            simulated_at=datetime(2026, 1, 1 + day, 0, 0, tzinfo=timezone.utc),
            total_equity=equity,
            available_cash=equity,
            position_value=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            positions={},
        ))

    metrics = calculate_metrics([], snapshots, Decimal("10000"), Decimal("5"))
    assert metrics.sharpe_ratio is not None
    assert metrics.sharpe_ratio > Decimal("0")


def test_sortino_ratio_calculation() -> None:
    # Mix of up and down days
    snapshots = [
        _snapshot(Decimal("10000"), 0),
    ]
    values = [10100, 10050, 9900, 10200, 10000]
    for i, val in enumerate(values):
        snapshots.append(SandboxSnapshot(
            simulated_at=datetime(2026, 1, 2 + i, 0, 0, tzinfo=timezone.utc),
            total_equity=Decimal(str(val)),
            available_cash=Decimal(str(val)),
            position_value=Decimal("0"),
            unrealized_pnl=Decimal("0"),
            realized_pnl=Decimal("0"),
            positions={},
        ))

    metrics = calculate_metrics([], snapshots, Decimal("10000"), Decimal("5"))
    assert metrics.sortino_ratio is not None


def test_per_pair_stats() -> None:
    trades = [
        _trade("BTCUSDT", pnl=Decimal("100"), minutes_offset=0),
        _trade("BTCUSDT", pnl=Decimal("-50"), minutes_offset=1),
        _trade("ETHUSDT", pnl=Decimal("200"), minutes_offset=2),
    ]
    stats = calculate_per_pair_stats(trades)
    assert len(stats) == 2

    btc_stat = next(s for s in stats if s.symbol == "BTCUSDT")
    assert btc_stat.trades == 2
    assert btc_stat.wins == 1
    assert btc_stat.net_pnl == Decimal("50.00000000")

    eth_stat = next(s for s in stats if s.symbol == "ETHUSDT")
    assert eth_stat.trades == 1
    assert eth_stat.wins == 1


def test_equity_curve_generation() -> None:
    snapshots = [_snapshot(Decimal(str(10000 + i * 100)), i) for i in range(10)]
    curve = generate_equity_curve(snapshots, interval=2)
    assert len(curve) == 5  # every 2nd snapshot


def test_empty_trades_edge_case() -> None:
    metrics = calculate_metrics([], [], Decimal("10000"), Decimal("7"))
    assert metrics.win_rate == Decimal("0")
    assert metrics.avg_win == Decimal("0")
    assert metrics.avg_loss == Decimal("0")
    assert metrics.best_trade == Decimal("0")
    assert metrics.worst_trade == Decimal("0")
    assert metrics.profit_factor is None
    assert metrics.sharpe_ratio is None


def test_avg_win_avg_loss() -> None:
    trades = [
        _trade(pnl=Decimal("100"), minutes_offset=0),
        _trade(pnl=Decimal("200"), minutes_offset=1),
        _trade(pnl=Decimal("-50"), minutes_offset=2),
        _trade(pnl=Decimal("-150"), minutes_offset=3),
    ]
    metrics = calculate_metrics(trades, [], Decimal("10000"), Decimal("7"))
    assert metrics.avg_win == Decimal("150.00000000")
    assert metrics.avg_loss == Decimal("-100.00000000")
    assert metrics.best_trade == Decimal("200")
    assert metrics.worst_trade == Decimal("-150")
