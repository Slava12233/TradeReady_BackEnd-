"""Ranking calculator for battle results.

Calculates final rankings for all 5 metrics: ROI %, Total PnL,
Sharpe Ratio, Win Rate, and Profit Factor.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
import math
from uuid import UUID

from src.database.models import BattleSnapshot, Trade


@dataclass(slots=True)
class ParticipantMetrics:
    """Computed metrics for a single battle participant.

    Attributes:
        agent_id:       The participant's agent UUID.
        start_equity:   Starting balance.
        final_equity:   Final portfolio equity.
        roi_pct:        Return on investment percentage.
        total_pnl:      Absolute PnL in USDT.
        sharpe_ratio:   Risk-adjusted return from equity curve.
        win_rate:       Percentage of winning trades.
        profit_factor:  Gross profits / gross losses.
        total_trades:   Total trade count.
        max_drawdown:   Maximum drawdown percentage.
    """

    agent_id: UUID
    start_equity: Decimal
    final_equity: Decimal
    roi_pct: Decimal
    total_pnl: Decimal
    sharpe_ratio: Decimal
    win_rate: Decimal
    profit_factor: Decimal
    total_trades: int
    max_drawdown: Decimal


class RankingCalculator:
    """Calculate final rankings for a completed battle."""

    @staticmethod
    def calculate_roi(start_balance: Decimal, final_equity: Decimal) -> Decimal:
        """Calculate ROI percentage."""
        if start_balance == 0:
            return Decimal("0")
        return ((final_equity - start_balance) / start_balance) * 100

    @staticmethod
    def calculate_total_pnl(start_balance: Decimal, final_equity: Decimal) -> Decimal:
        """Calculate absolute PnL."""
        return final_equity - start_balance

    @staticmethod
    def calculate_sharpe_ratio(
        equity_snapshots: Sequence[BattleSnapshot],
        risk_free_rate: float = 0.0,
    ) -> Decimal:
        """Calculate Sharpe ratio from equity curve snapshots.

        Uses period returns derived from consecutive equity values.
        Annualized assuming 5-second intervals.
        """
        if len(equity_snapshots) < 2:
            return Decimal("0")

        equities = [float(s.equity) for s in equity_snapshots]
        returns = []
        for i in range(1, len(equities)):
            if equities[i - 1] != 0:
                ret = (equities[i] - equities[i - 1]) / equities[i - 1]
                returns.append(ret)

        if not returns:
            return Decimal("0")

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_dev = math.sqrt(variance) if variance > 0 else 0

        if std_dev == 0:
            return Decimal("0")

        # Annualize: ~6.3M 5-second periods per year
        periods_per_year = 365.25 * 24 * 3600 / 5
        annualization_factor = math.sqrt(periods_per_year)

        sharpe = ((mean_return - risk_free_rate) / std_dev) * annualization_factor
        return Decimal(str(round(sharpe, 4)))

    @staticmethod
    def calculate_win_rate(trades: Sequence[Trade]) -> Decimal:
        """Calculate win rate from trades."""
        if not trades:
            return Decimal("0")

        winning = sum(1 for t in trades if t.realized_pnl is not None and t.realized_pnl > 0)
        return Decimal(str(round((winning / len(trades)) * 100, 2)))

    @staticmethod
    def calculate_profit_factor(trades: Sequence[Trade]) -> Decimal:
        """Calculate profit factor: gross profits / gross losses."""
        gross_profit = Decimal("0")
        gross_loss = Decimal("0")

        for trade in trades:
            if trade.realized_pnl is not None:
                if trade.realized_pnl > 0:
                    gross_profit += trade.realized_pnl
                elif trade.realized_pnl < 0:
                    gross_loss += abs(trade.realized_pnl)

        if gross_loss == 0:
            return Decimal("999.99") if gross_profit > 0 else Decimal("0")

        return Decimal(str(round(float(gross_profit / gross_loss), 4)))

    @staticmethod
    def calculate_max_drawdown(equity_snapshots: Sequence[BattleSnapshot]) -> Decimal:
        """Calculate maximum drawdown percentage from equity curve."""
        if len(equity_snapshots) < 2:
            return Decimal("0")

        peak = float(equity_snapshots[0].equity)
        max_dd = 0.0

        for snap in equity_snapshots:
            equity = float(snap.equity)
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (peak - equity) / peak * 100
                if dd > max_dd:
                    max_dd = dd

        return Decimal(str(round(max_dd, 4)))

    def compute_participant_metrics(
        self,
        agent_id: UUID,
        start_balance: Decimal,
        final_equity: Decimal,
        snapshots: Sequence[BattleSnapshot],
        trades: Sequence[Trade],
    ) -> ParticipantMetrics:
        """Compute all metrics for a single participant."""
        return ParticipantMetrics(
            agent_id=agent_id,
            start_equity=start_balance,
            final_equity=final_equity,
            roi_pct=self.calculate_roi(start_balance, final_equity),
            total_pnl=self.calculate_total_pnl(start_balance, final_equity),
            sharpe_ratio=self.calculate_sharpe_ratio(snapshots),
            win_rate=self.calculate_win_rate(trades),
            profit_factor=self.calculate_profit_factor(trades),
            total_trades=len(trades),
            max_drawdown=self.calculate_max_drawdown(snapshots),
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
