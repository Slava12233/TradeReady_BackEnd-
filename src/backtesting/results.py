"""Backtest performance metrics calculator.

Computes risk-adjusted returns, drawdown, and per-pair statistics from
backtest trades and equity snapshots.  Internally delegates to the unified
metrics calculator in ``src.metrics.calculator``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from src.backtesting.sandbox import SandboxSnapshot, SandboxTrade
from src.metrics.adapters import from_sandbox_snapshots, from_sandbox_trades
from src.metrics.calculator import UnifiedMetrics, calculate_unified_metrics

_QUANT4 = Decimal("0.0001")
_QUANT2 = Decimal("0.01")
_QUANT8 = Decimal("0.00000001")
_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    """Full performance metrics for a completed backtest."""

    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    max_drawdown_pct: Decimal
    max_drawdown_duration_days: Decimal
    win_rate: Decimal
    profit_factor: Decimal | None
    avg_win: Decimal
    avg_loss: Decimal
    best_trade: Decimal
    worst_trade: Decimal
    avg_trade_duration_minutes: Decimal
    trades_per_day: Decimal

    def to_dict(self) -> dict[str, Any]:
        """Serialise to JSON-safe dict."""
        return {
            "sharpe_ratio": str(self.sharpe_ratio) if self.sharpe_ratio is not None else None,
            "sortino_ratio": str(self.sortino_ratio) if self.sortino_ratio is not None else None,
            "max_drawdown_pct": str(self.max_drawdown_pct),
            "max_drawdown_duration_days": str(self.max_drawdown_duration_days),
            "win_rate": str(self.win_rate),
            "profit_factor": str(self.profit_factor) if self.profit_factor is not None else None,
            "avg_win": str(self.avg_win),
            "avg_loss": str(self.avg_loss),
            "best_trade": str(self.best_trade),
            "worst_trade": str(self.worst_trade),
            "avg_trade_duration_minutes": str(self.avg_trade_duration_minutes),
            "trades_per_day": str(self.trades_per_day),
        }


@dataclass(frozen=True, slots=True)
class PairStats:
    """Per-pair breakdown."""

    symbol: str
    trades: int
    wins: int
    losses: int
    win_rate: Decimal
    net_pnl: Decimal
    total_volume: Decimal


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """A single point on the equity curve."""

    timestamp: str
    equity: str


def _unified_to_backtest_metrics(um: UnifiedMetrics, avg_trade_duration: Decimal) -> BacktestMetrics:
    """Map UnifiedMetrics to the BacktestMetrics dataclass."""
    return BacktestMetrics(
        sharpe_ratio=um.sharpe_ratio,
        sortino_ratio=um.sortino_ratio,
        max_drawdown_pct=um.max_drawdown_pct,
        max_drawdown_duration_days=um.max_drawdown_duration_days,
        win_rate=um.win_rate,
        profit_factor=um.profit_factor,
        avg_win=um.avg_win,
        avg_loss=um.avg_loss,
        best_trade=um.best_trade,
        worst_trade=um.worst_trade,
        avg_trade_duration_minutes=avg_trade_duration,
        trades_per_day=um.trades_per_day,
    )


def calculate_metrics(
    trades: list[SandboxTrade],
    snapshots: list[SandboxSnapshot],
    starting_balance: Decimal,
    duration_days: Decimal,
) -> BacktestMetrics:
    """Compute all backtest performance metrics.

    Args:
        trades:           List of executed trades.
        snapshots:        List of equity snapshots.
        starting_balance: Initial USDT balance.
        duration_days:    Total simulated days.

    Returns:
        :class:`BacktestMetrics` with all computed values.
    """
    # Convert to unified inputs and compute
    metric_trades = from_sandbox_trades(trades)
    metric_snapshots = from_sandbox_snapshots(snapshots)

    um = calculate_unified_metrics(
        trades=metric_trades,
        snapshots=metric_snapshots,
        starting_balance=starting_balance,
        duration_days=duration_days,
        snapshot_interval_seconds=86400,
    )

    # Compute avg trade duration (backtest-specific, not in unified metrics)
    avg_trade_duration = _ZERO
    if len(trades) >= 2:
        durations: list[Decimal] = []
        for i in range(1, len(trades)):
            dt = (trades[i].simulated_at - trades[i - 1].simulated_at).total_seconds()
            durations.append(Decimal(str(dt)) / Decimal("60"))
        if durations:
            avg_trade_duration = (sum(durations, _ZERO) / Decimal(len(durations))).quantize(_QUANT2)

    return _unified_to_backtest_metrics(um, avg_trade_duration)


def calculate_per_pair_stats(trades: list[SandboxTrade]) -> list[PairStats]:
    """Compute per-pair performance breakdown.

    Args:
        trades: All executed backtest trades.

    Returns:
        List of :class:`PairStats`, one per traded symbol.
    """
    by_symbol: dict[str, list[SandboxTrade]] = {}
    for t in trades:
        by_symbol.setdefault(t.symbol, []).append(t)

    results: list[PairStats] = []
    for symbol, symbol_trades in sorted(by_symbol.items()):
        pnls = [t.realized_pnl for t in symbol_trades if t.realized_pnl is not None]
        wins = sum(1 for p in pnls if p > _ZERO)
        losses_count = sum(1 for p in pnls if p < _ZERO)
        net_pnl = sum(pnls, _ZERO)
        wr = (Decimal(wins) / Decimal(len(pnls)) * Decimal("100")).quantize(_QUANT2) if pnls else _ZERO
        total_vol = sum((t.quote_amount for t in symbol_trades), _ZERO)

        results.append(
            PairStats(
                symbol=symbol,
                trades=len(symbol_trades),
                wins=wins,
                losses=losses_count,
                win_rate=wr,
                net_pnl=net_pnl.quantize(_QUANT8),
                total_volume=total_vol.quantize(_QUANT8),
            )
        )
    return results


def generate_equity_curve(snapshots: list[SandboxSnapshot], interval: int = 1) -> list[EquityPoint]:
    """Generate equity curve points from snapshots.

    Args:
        snapshots: Equity snapshots from the sandbox.
        interval:  Take every Nth snapshot (1 = all).

    Returns:
        List of :class:`EquityPoint`.
    """
    return [
        EquityPoint(
            timestamp=snap.simulated_at.isoformat(),
            equity=str(snap.total_equity),
        )
        for i, snap in enumerate(snapshots)
        if i % interval == 0
    ]
