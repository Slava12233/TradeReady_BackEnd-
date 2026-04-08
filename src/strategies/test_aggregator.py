"""Test result aggregation for multi-episode strategy testing.

Computes aggregate statistics across multiple backtest episodes and
provides per-pair breakdowns for strategy analysis.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from src.metrics.deflated_sharpe import MIN_RETURNS, compute_deflated_sharpe

logger = logging.getLogger(__name__)


class TestAggregator:
    """Aggregates results from multiple test episodes into summary statistics."""

    @staticmethod
    def aggregate(
        episodes: list[dict[str, Any]],
        num_trials: int = 1,
    ) -> dict[str, Any]:
        """Aggregate episode metrics into summary statistics.

        When at least ``MIN_RETURNS`` episodes with a Sharpe ratio are available,
        this method also computes the Deflated Sharpe Ratio (DSR) to correct for
        multiple-testing bias.  The DSR result is stored under the
        ``"deflated_sharpe"`` key.

        Args:
            episodes: List of episode metric dicts, each containing at minimum:
                ``roi_pct``, ``sharpe_ratio``, ``max_drawdown_pct``,
                ``total_trades``, ``win_rate``.
            num_trials: Number of strategy variants tested before selecting this
                one.  Used as the selection-bias factor in the DSR computation.
                Defaults to ``1`` (no selection bias correction).

        Returns:
            Aggregated results dict with overall and per-pair breakdowns.
            When DSR can be computed, the dict includes a ``"deflated_sharpe"``
            sub-dict with ``observed_sharpe``, ``deflated_sharpe``,
            ``p_value``, ``is_significant``, and ``num_trials``.
        """
        if not episodes:
            return TestAggregator._empty_results()

        rois = [float(e.get("roi_pct", 0)) for e in episodes]
        sharpes = [float(e.get("sharpe_ratio", 0)) for e in episodes if e.get("sharpe_ratio") is not None]
        drawdowns = [float(e.get("max_drawdown_pct", 0)) for e in episodes]
        trade_counts = [int(e.get("total_trades", 0)) for e in episodes]
        win_rates = [float(e.get("win_rate", 0)) for e in episodes if e.get("win_rate") is not None]

        profitable = [r for r in rois if r > 0]

        roi_arr = np.array(rois)

        results: dict[str, Any] = {
            "episodes_completed": len(episodes),
            "episodes_profitable": len(profitable),
            "episodes_profitable_pct": round(len(profitable) / len(episodes) * 100, 2) if episodes else 0,
            "avg_roi_pct": round(float(np.mean(roi_arr)), 4),
            "median_roi_pct": round(float(np.median(roi_arr)), 4),
            "best_roi_pct": round(float(np.max(roi_arr)), 4),
            "worst_roi_pct": round(float(np.min(roi_arr)), 4),
            "std_roi_pct": round(float(np.std(roi_arr, ddof=1)), 4) if len(rois) > 1 else 0,
            "avg_sharpe": round(float(np.mean(sharpes)), 4) if sharpes else None,
            "avg_max_drawdown_pct": round(float(np.mean(drawdowns)), 4) if drawdowns else 0,
            "avg_trades_per_episode": round(float(np.mean(trade_counts)), 2) if trade_counts else 0,
            "total_trades": int(np.sum(trade_counts)),
            "avg_win_rate": round(float(np.mean(win_rates)), 4) if win_rates else None,
        }

        # Deflated Sharpe Ratio — requires at least MIN_RETURNS episode Sharpes.
        # Each episode Sharpe is treated as a single "return observation".
        # This corrects for multiple-testing bias when num_trials > 1.
        if len(sharpes) >= MIN_RETURNS:
            try:
                dsr = compute_deflated_sharpe(
                    returns=sharpes,
                    num_trials=max(1, num_trials),
                    # One observation per episode (not daily), so annualisation
                    # factor = 1 — DSR is already in per-episode units.
                    annualization_factor=1,
                )
                results["deflated_sharpe"] = {
                    "observed_sharpe": round(dsr.observed_sharpe, 6),
                    "expected_max_sharpe": round(dsr.expected_max_sharpe, 6),
                    "deflated_sharpe": round(dsr.deflated_sharpe, 6),
                    "p_value": round(dsr.p_value, 6),
                    "is_significant": dsr.is_significant,
                    "num_trials": dsr.num_trials,
                    "num_returns": dsr.num_returns,
                    "skewness": round(dsr.skewness, 6),
                    "kurtosis": round(dsr.kurtosis, 6),
                }
            except ValueError as exc:
                logger.warning(
                    "DSR computation skipped: %s (episodes=%d, num_trials=%d)",
                    exc,
                    len(sharpes),
                    num_trials,
                )

        # Per-pair breakdown
        by_pair = TestAggregator._compute_by_pair(episodes)
        if by_pair:
            results["by_pair"] = by_pair

        return results

    @staticmethod
    def _compute_by_pair(episodes: list[dict[str, Any]]) -> dict[str, Any]:
        """Group and aggregate metrics by trading pair."""
        pair_data: dict[str, list[dict[str, Any]]] = {}

        for ep in episodes:
            per_pair = ep.get("per_pair", ep.get("by_pair", {}))
            if isinstance(per_pair, dict):
                for pair, metrics in per_pair.items():
                    if pair not in pair_data:
                        pair_data[pair] = []
                    pair_data[pair].append(metrics)
            elif isinstance(per_pair, list):
                for item in per_pair:
                    pair = item.get("symbol", item.get("pair", "unknown"))
                    if pair not in pair_data:
                        pair_data[pair] = []
                    pair_data[pair].append(item)

        result: dict[str, Any] = {}
        for pair, metrics_list in pair_data.items():
            rois = [float(m.get("roi_pct", m.get("net_pnl", 0))) for m in metrics_list]
            trades = [int(m.get("total_trades", m.get("trade_count", 0))) for m in metrics_list]
            result[pair] = {
                "avg_roi_pct": round(float(np.mean(rois)), 4) if rois else 0,
                "total_trades": int(np.sum(trades)),
                "episodes_with_trades": sum(1 for t in trades if t > 0),
            }

        return result

    @staticmethod
    def _empty_results() -> dict[str, Any]:
        """Return empty results when no episodes are available."""
        return {
            "episodes_completed": 0,
            "episodes_profitable": 0,
            "episodes_profitable_pct": 0,
            "avg_roi_pct": 0,
            "median_roi_pct": 0,
            "best_roi_pct": 0,
            "worst_roi_pct": 0,
            "std_roi_pct": 0,
            "avg_sharpe": None,
            "avg_max_drawdown_pct": 0,
            "avg_trades_per_episode": 0,
            "total_trades": 0,
            "avg_win_rate": None,
        }
