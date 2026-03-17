"""Ranking calculator for battle results.

Calculates final rankings for all metrics: ROI %, Total PnL,
Sharpe Ratio, Sortino Ratio, Win Rate, Profit Factor, and Max Drawdown.
Delegates metric computation to the unified calculator in
``src.metrics.calculator``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from src.database.models import BattleSnapshot, Trade
from src.metrics.adapters import from_battle_snapshots, from_db_trades
from src.metrics.calculator import calculate_unified_metrics


@dataclass(slots=True)
class ParticipantMetrics:
    """Computed metrics for a single battle participant.

    Attributes:
        agent_id:                  The participant's agent UUID.
        start_equity:              Starting balance.
        final_equity:              Final portfolio equity.
        roi_pct:                   Return on investment percentage.
        total_pnl:                 Absolute PnL in USDT.
        sharpe_ratio:              Risk-adjusted return from equity curve.
        sortino_ratio:             Sortino ratio (downside deviation only).
        win_rate:                  Percentage of winning trades.
        profit_factor:             Gross profits / gross losses.
        total_trades:              Total trade count.
        max_drawdown:              Maximum drawdown percentage.
        max_drawdown_duration_days: Duration of max drawdown in days.
    """

    agent_id: UUID
    start_equity: Decimal
    final_equity: Decimal
    roi_pct: Decimal
    total_pnl: Decimal
    sharpe_ratio: Decimal
    sortino_ratio: Decimal | None
    win_rate: Decimal
    profit_factor: Decimal
    total_trades: int
    max_drawdown: Decimal
    max_drawdown_duration_days: Decimal


class RankingCalculator:
    """Calculate final rankings for a completed battle."""

    def compute_participant_metrics(
        self,
        agent_id: UUID,
        start_balance: Decimal,
        final_equity: Decimal,
        snapshots: Sequence[BattleSnapshot],
        trades: Sequence[Trade],
    ) -> ParticipantMetrics:
        """Compute all metrics for a single participant.

        Uses the unified metrics calculator for consistent results
        across backtesting and battles.
        """
        metric_trades = from_db_trades(trades)
        metric_snapshots = from_battle_snapshots(snapshots)

        # Estimate duration from snapshots
        if len(snapshots) >= 2:
            duration_seconds = (snapshots[-1].timestamp - snapshots[0].timestamp).total_seconds()
            duration_days = Decimal(str(max(duration_seconds / 86400, Decimal("0.001"))))
        else:
            duration_days = Decimal("1")

        um = calculate_unified_metrics(
            trades=metric_trades,
            snapshots=metric_snapshots,
            starting_balance=start_balance,
            duration_days=duration_days,
            snapshot_interval_seconds=5,
        )

        return ParticipantMetrics(
            agent_id=agent_id,
            start_equity=start_balance,
            final_equity=final_equity,
            roi_pct=um.roi_pct,
            total_pnl=um.total_pnl,
            sharpe_ratio=um.sharpe_ratio if um.sharpe_ratio is not None else Decimal("0"),
            sortino_ratio=um.sortino_ratio,
            win_rate=um.win_rate,
            profit_factor=um.profit_factor if um.profit_factor is not None else Decimal("0"),
            total_trades=um.total_trades,
            max_drawdown=um.max_drawdown_pct,
            max_drawdown_duration_days=um.max_drawdown_duration_days,
        )

    @staticmethod
    def rank_participants(
        metrics: list[ParticipantMetrics],
        ranking_metric: str,
    ) -> list[ParticipantMetrics]:
        """Sort participants by the specified metric (descending = better).

        Args:
            metrics: List of computed participant metrics.
            ranking_metric: One of roi_pct, total_pnl, sharpe_ratio, win_rate, profit_factor.

        Returns:
            Sorted list with best performer first.
        """
        metric_attr = {
            "roi_pct": "roi_pct",
            "total_pnl": "total_pnl",
            "sharpe_ratio": "sharpe_ratio",
            "win_rate": "win_rate",
            "profit_factor": "profit_factor",
        }

        attr = metric_attr.get(ranking_metric, "roi_pct")
        return sorted(metrics, key=lambda m: getattr(m, attr), reverse=True)
