"""Backtest performance metrics calculator.

Computes risk-adjusted returns, drawdown, and per-pair statistics from
backtest trades and equity snapshots.  All calculations use ``Decimal``
for precision.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
import math
from typing import Any

from src.backtesting.sandbox import SandboxSnapshot, SandboxTrade

_QUANT4 = Decimal("0.0001")
_QUANT2 = Decimal("0.01")
_QUANT8 = Decimal("0.00000001")
_ZERO = Decimal("0")
_ANNUALIZE = Decimal(str(math.sqrt(365)))


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
    # ── Trade PnL classification ─────────────────────────────────────────
    pnls: list[Decimal] = []
    for t in trades:
        if t.realized_pnl is not None:
            pnls.append(t.realized_pnl)

    wins = [p for p in pnls if p > _ZERO]
    losses = [p for p in pnls if p < _ZERO]

    win_rate = (Decimal(len(wins)) / Decimal(len(pnls)) * Decimal("100")).quantize(_QUANT2) if pnls else _ZERO

    avg_win = (sum(wins, _ZERO) / Decimal(len(wins))).quantize(_QUANT8) if wins else _ZERO
    avg_loss = (sum(losses, _ZERO) / Decimal(len(losses))).quantize(_QUANT8) if losses else _ZERO

    gross_profit = sum(wins, _ZERO)
    gross_loss = abs(sum(losses, _ZERO))
    profit_factor = (gross_profit / gross_loss).quantize(_QUANT4) if gross_loss > _ZERO else None

    best_trade = max(pnls) if pnls else _ZERO
    worst_trade = min(pnls) if pnls else _ZERO

    # ── Trade duration (avg minutes between consecutive trades) ──────────
    avg_trade_duration = _ZERO
    if len(trades) >= 2:
        durations = []
        for i in range(1, len(trades)):
            dt = (trades[i].simulated_at - trades[i - 1].simulated_at).total_seconds()
            durations.append(Decimal(str(dt)) / Decimal("60"))
        if durations:
            avg_trade_duration = (sum(durations, _ZERO) / Decimal(len(durations))).quantize(_QUANT2)

    trades_per_day = (Decimal(len(trades)) / duration_days).quantize(_QUANT2) if duration_days > _ZERO else _ZERO

    # ── Drawdown from equity curve ───────────────────────────────────────
    max_dd_pct = _ZERO
    max_dd_duration_days = _ZERO

    if snapshots:
        peak = snapshots[0].total_equity
        dd_start_idx = 0
        current_dd_start = 0

        for i, snap in enumerate(snapshots):
            if snap.total_equity > peak:
                peak = snap.total_equity
                current_dd_start = i

            if peak > _ZERO:
                dd = ((peak - snap.total_equity) / peak * Decimal("100")).quantize(_QUANT2)
                if dd > max_dd_pct:
                    max_dd_pct = dd
                    dd_start_idx = current_dd_start

        # Duration of max drawdown in days
        if dd_start_idx < len(snapshots) - 1:
            dd_seconds = (snapshots[-1].simulated_at - snapshots[dd_start_idx].simulated_at).total_seconds()
            max_dd_duration_days = (Decimal(str(dd_seconds)) / Decimal("86400")).quantize(_QUANT2)

    # ── Sharpe & Sortino from daily returns ──────────────────────────────
    sharpe = _compute_sharpe(snapshots)
    sortino = _compute_sortino(snapshots)

    return BacktestMetrics(
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_duration_days=max_dd_duration_days,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_win=avg_win,
        avg_loss=avg_loss,
        best_trade=best_trade,
        worst_trade=worst_trade,
        avg_trade_duration_minutes=avg_trade_duration,
        trades_per_day=trades_per_day,
    )


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


# ── Internal helpers ─────────────────────────────────────────────────────────


def _compute_daily_returns(snapshots: list[SandboxSnapshot]) -> list[Decimal]:
    """Extract daily returns from snapshot equity values."""
    if len(snapshots) < 2:
        return []

    # Group by date, take last snapshot per day
    daily: dict[str, Decimal] = {}
    for snap in snapshots:
        day_key = snap.simulated_at.strftime("%Y-%m-%d")
        daily[day_key] = snap.total_equity

    equities = list(daily.values())
    if len(equities) < 2:
        return []

    returns: list[Decimal] = []
    for i in range(1, len(equities)):
        if equities[i - 1] > _ZERO:
            ret = (equities[i] - equities[i - 1]) / equities[i - 1]
            returns.append(ret)
    return returns


def _compute_sharpe(snapshots: list[SandboxSnapshot]) -> Decimal | None:
    """Annualised Sharpe ratio (risk-free rate = 0)."""
    returns = _compute_daily_returns(snapshots)
    if len(returns) < 2:
        return None

    mean_ret = sum(returns) / Decimal(len(returns))
    variance = sum((r - mean_ret) ** 2 for r in returns) / Decimal(len(returns) - 1)

    std_dev = Decimal(str(math.sqrt(float(variance))))
    if std_dev == _ZERO:
        return None

    sharpe = (mean_ret / std_dev) * _ANNUALIZE
    return sharpe.quantize(_QUANT4, rounding=ROUND_HALF_UP)


def _compute_sortino(snapshots: list[SandboxSnapshot]) -> Decimal | None:
    """Annualised Sortino ratio (downside deviation only)."""
    returns = _compute_daily_returns(snapshots)
    if len(returns) < 2:
        return None

    mean_ret = sum(returns) / Decimal(len(returns))
    downside = [r for r in returns if r < _ZERO]

    if not downside:
        return None

    downside_var = sum(r**2 for r in downside) / Decimal(len(downside))
    downside_std = Decimal(str(math.sqrt(float(downside_var))))

    if downside_std == _ZERO:
        return None

    sortino = (mean_ret / downside_std) * _ANNUALIZE
    return sortino.quantize(_QUANT4, rounding=ROUND_HALF_UP)
