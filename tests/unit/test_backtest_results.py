"""Unit tests for src.backtesting.results — metrics calculator."""

from datetime import UTC, datetime
from decimal import Decimal

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
        simulated_at=datetime(2026, 1, 1, 0, minutes_offset, tzinfo=UTC),
    )


def _snapshot(equity: Decimal, hours_offset: int = 0) -> SandboxSnapshot:
    return SandboxSnapshot(
        simulated_at=datetime(2026, 1, 1, hours_offset, 0, tzinfo=UTC),
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
        _snapshot(Decimal("9900"), 2),  # drawdown = (11000-9900)/11000 = 10%
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
        snapshots.append(
            SandboxSnapshot(
                simulated_at=datetime(2026, 1, 1 + day, 0, 0, tzinfo=UTC),
                total_equity=equity,
                available_cash=equity,
                position_value=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
                positions={},
            )
        )

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
        snapshots.append(
            SandboxSnapshot(
                simulated_at=datetime(2026, 1, 2 + i, 0, 0, tzinfo=UTC),
                total_equity=Decimal(str(val)),
                available_cash=Decimal(str(val)),
                position_value=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                realized_pnl=Decimal("0"),
                positions={},
            )
        )

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


# ---------------------------------------------------------------------------
# P2 expansion tests
# ---------------------------------------------------------------------------


def test_all_losses_profit_factor_zero() -> None:
    trades = [
        _trade(pnl=Decimal("-100"), minutes_offset=0),
        _trade(pnl=Decimal("-200"), minutes_offset=1),
    ]
    metrics = calculate_metrics(trades, [], Decimal("10000"), Decimal("7"))
    # When no gross profit, profit_factor should be 0 or None
    assert metrics.profit_factor == Decimal("0") or metrics.profit_factor is None


def test_single_trade_metrics() -> None:
    trades = [_trade(pnl=Decimal("500"), minutes_offset=0)]
    metrics = calculate_metrics(trades, [], Decimal("10000"), Decimal("7"))
    assert metrics.win_rate == Decimal("100.00")
    assert metrics.best_trade == Decimal("500")
    assert metrics.worst_trade == Decimal("500")


def test_equity_curve_interval() -> None:
    snapshots = [_snapshot(Decimal(str(10000 + i * 50)), i) for i in range(20)]
    curve = generate_equity_curve(snapshots, interval=5)
    assert len(curve) == 4  # 20 / 5 = 4


def test_per_pair_stats_multiple_pairs() -> None:
    trades = [
        _trade("BTCUSDT", pnl=Decimal("100"), minutes_offset=0),
        _trade("BTCUSDT", pnl=Decimal("-50"), minutes_offset=1),
        _trade("ETHUSDT", pnl=Decimal("200"), minutes_offset=2),
        _trade("ETHUSDT", pnl=Decimal("-30"), minutes_offset=3),
        _trade("SOLUSDT", pnl=Decimal("50"), minutes_offset=4),
    ]
    stats = calculate_per_pair_stats(trades)
    assert len(stats) == 3

    sol_stat = next(s for s in stats if s.symbol == "SOLUSDT")
    assert sol_stat.trades == 1
    assert sol_stat.wins == 1


def test_trades_per_day_calculation() -> None:
    trades = [_trade(pnl=Decimal("100"), minutes_offset=i) for i in range(10)]
    metrics = calculate_metrics(trades, [], Decimal("10000"), Decimal("7"))
    # 10 trades over 7 days ≈ 1.43 trades/day
    assert metrics.trades_per_day is not None
    assert metrics.trades_per_day > Decimal("0")


# ---------------------------------------------------------------------------
# BacktestMetrics.to_dict() per_pair regression tests
# ---------------------------------------------------------------------------


def test_metrics_to_dict_includes_by_pair() -> None:
    """to_dict(per_pair=...) must include a 'by_pair' key with per-symbol data."""
    trades = [
        _trade("BTCUSDT", pnl=Decimal("100"), minutes_offset=0),
        _trade("ETHUSDT", pnl=Decimal("-30"), minutes_offset=1),
    ]
    metrics = calculate_metrics(trades, [], Decimal("10000"), Decimal("1"))
    per_pair = calculate_per_pair_stats(trades)

    result = metrics.to_dict(per_pair=per_pair)

    assert "by_pair" in result
    assert isinstance(result["by_pair"], list)
    assert len(result["by_pair"]) == 2

    symbols = {entry["symbol"] for entry in result["by_pair"]}
    assert symbols == {"BTCUSDT", "ETHUSDT"}

    # Spot-check the structure of one entry
    btc_entry = next(e for e in result["by_pair"] if e["symbol"] == "BTCUSDT")
    assert "trades" in btc_entry
    assert "wins" in btc_entry
    assert "losses" in btc_entry
    assert "win_rate" in btc_entry
    assert "net_pnl" in btc_entry
    assert "total_volume" in btc_entry


def test_metrics_to_dict_without_per_pair() -> None:
    """to_dict() called without per_pair must NOT include a 'by_pair' key."""
    trades = [_trade(pnl=Decimal("100"), minutes_offset=0)]
    metrics = calculate_metrics(trades, [], Decimal("10000"), Decimal("1"))

    result = metrics.to_dict()

    assert "by_pair" not in result
    # Standard metric keys must still be present
    assert "sharpe_ratio" in result
    assert "win_rate" in result
    assert "max_drawdown_pct" in result
