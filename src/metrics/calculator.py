"""Unified metrics calculator for backtesting and battles.

Provides a single source of truth for all performance metrics so that
backtesting and battles produce consistent, comparable results.
All calculations use ``Decimal`` for precision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
import math

_QUANT4 = Decimal("0.0001")
_QUANT2 = Decimal("0.01")
_QUANT8 = Decimal("0.00000001")
_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class MetricTradeInput:
    """Normalised trade input for metrics calculation."""

    realized_pnl: Decimal | None
    quote_amount: Decimal
    symbol: str
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class MetricSnapshotInput:
    """Normalised equity snapshot input for metrics calculation."""

    timestamp: datetime
    equity: Decimal


@dataclass(frozen=True, slots=True)
class UnifiedMetrics:
    """Full set of performance metrics computed by the unified calculator."""

    roi_pct: Decimal
    total_pnl: Decimal
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    max_drawdown_pct: Decimal
    max_drawdown_duration_days: Decimal
    win_rate: Decimal
    profit_factor: Decimal | None
    total_trades: int
    trades_per_day: Decimal
    avg_win: Decimal
    avg_loss: Decimal
    best_trade: Decimal
    worst_trade: Decimal


def calculate_unified_metrics(
    trades: list[MetricTradeInput],
    snapshots: list[MetricSnapshotInput],
    starting_balance: Decimal,
    duration_days: Decimal,
    snapshot_interval_seconds: int = 86400,
) -> UnifiedMetrics:
    """Compute all performance metrics from normalised inputs.

    Args:
        trades:                    Normalised trade inputs.
        snapshots:                 Normalised equity snapshots.
        starting_balance:          Initial USDT balance.
        duration_days:             Total duration in days.
        snapshot_interval_seconds: Interval between snapshots for Sharpe
                                   annualisation.  86400 for daily snapshots,
                                   5 for battle 5-second snapshots.

    Returns:
        :class:`UnifiedMetrics` with all computed values.
    """
    # ── ROI & PnL ─────────────────────────────────────────────────────────
    final_equity = snapshots[-1].equity if snapshots else starting_balance
    total_pnl = final_equity - starting_balance
    roi_pct = ((total_pnl / starting_balance) * Decimal("100")).quantize(_QUANT2) if starting_balance > _ZERO else _ZERO

    # ── Trade PnL classification ──────────────────────────────────────────
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

    trades_per_day = (Decimal(len(trades)) / duration_days).quantize(_QUANT2) if duration_days > _ZERO else _ZERO

    # ── Drawdown from equity curve ────────────────────────────────────────
    max_dd_pct = _ZERO
    max_dd_duration_days = _ZERO

    if snapshots:
        peak = snapshots[0].equity
        current_dd_start = 0
        dd_start_idx = 0

        for i, snap in enumerate(snapshots):
            if snap.equity > peak:
                peak = snap.equity
                current_dd_start = i

            if peak > _ZERO:
                dd = ((peak - snap.equity) / peak * Decimal("100")).quantize(_QUANT2)
                if dd > max_dd_pct:
                    max_dd_pct = dd
                    dd_start_idx = current_dd_start

        if dd_start_idx < len(snapshots) - 1:
            dd_seconds = (snapshots[-1].timestamp - snapshots[dd_start_idx].timestamp).total_seconds()
            max_dd_duration_days = (Decimal(str(dd_seconds)) / Decimal("86400")).quantize(_QUANT2)

    # ── Sharpe & Sortino ──────────────────────────────────────────────────
    annualize = Decimal(str(math.sqrt(365.25 * 86400 / snapshot_interval_seconds)))
    sharpe = _compute_ratio(snapshots, annualize, downside_only=False)
    sortino = _compute_ratio(snapshots, annualize, downside_only=True)

    return UnifiedMetrics(
        roi_pct=roi_pct,
        total_pnl=total_pnl,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_duration_days=max_dd_duration_days,
        win_rate=win_rate,
        profit_factor=profit_factor,
        total_trades=len(trades),
        trades_per_day=trades_per_day,
        avg_win=avg_win,
        avg_loss=avg_loss,
        best_trade=best_trade,
        worst_trade=worst_trade,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _compute_returns(snapshots: list[MetricSnapshotInput]) -> list[Decimal]:
    """Extract per-period returns from consecutive snapshot equity values."""
    if len(snapshots) < 2:
        return []

    returns: list[Decimal] = []
    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1].equity
        if prev > _ZERO:
            ret = (snapshots[i].equity - prev) / prev
            returns.append(ret)
    return returns


def _compute_ratio(
    snapshots: list[MetricSnapshotInput],
    annualize: Decimal,
    *,
    downside_only: bool,
) -> Decimal | None:
    """Compute Sharpe or Sortino ratio from snapshot returns.

    Args:
        snapshots:     Equity snapshots.
        annualize:     Annualisation factor (sqrt of periods per year).
        downside_only: If True compute Sortino (downside deviation only),
                       otherwise Sharpe (full standard deviation).

    Returns:
        Annualised ratio, or ``None`` if insufficient data.
    """
    returns = _compute_returns(snapshots)
    if len(returns) < 2:
        return None

    mean_ret = sum(returns) / Decimal(len(returns))

    if downside_only:
        downside = [r for r in returns if r < _ZERO]
        if not downside:
            return None
        variance = sum(r**2 for r in downside) / Decimal(len(downside))
    else:
        variance = sum((r - mean_ret) ** 2 for r in returns) / Decimal(len(returns) - 1)

    std_dev = Decimal(str(math.sqrt(float(variance))))
    if std_dev == _ZERO:
        return None

    ratio = (mean_ret / std_dev) * annualize
    return ratio.quantize(_QUANT4, rounding=ROUND_HALF_UP)
