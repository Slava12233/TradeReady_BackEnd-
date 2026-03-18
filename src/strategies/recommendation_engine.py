"""Recommendation engine for strategy improvement suggestions.

Analyzes aggregated test results and generates actionable recommendations
based on 10+ rules covering performance, risk, and trade frequency.
"""

from __future__ import annotations

from typing import Any


def generate_recommendations(
    results: dict[str, Any],
    by_pair: dict[str, Any],
    definition: dict[str, Any],
) -> list[str]:
    """Generate improvement recommendations from test results.

    Args:
        results: Aggregated test results from ``TestAggregator.aggregate()``.
        by_pair: Per-pair breakdown dict.
        definition: Strategy definition dict.

    Returns:
        List of human-readable recommendation strings.
    """
    recs: list[str] = []

    avg_roi = results.get("avg_roi_pct", 0)
    avg_sharpe = results.get("avg_sharpe")
    avg_drawdown = results.get("avg_max_drawdown_pct", 0)
    avg_trades = results.get("avg_trades_per_episode", 0)
    avg_win_rate = results.get("avg_win_rate")
    exit_conditions = definition.get("exit_conditions", {})
    entry_conditions = definition.get("entry_conditions", {})

    # Rule 1: Pair performance disparity
    if by_pair and len(by_pair) > 1:
        rois = {pair: data.get("avg_roi_pct", 0) for pair, data in by_pair.items()}
        best_pair = max(rois, key=rois.get)  # type: ignore[arg-type]
        worst_pair = min(rois, key=rois.get)  # type: ignore[arg-type]
        disparity = rois[best_pair] - rois[worst_pair]
        if disparity > 5:
            recs.append(
                f"Pair performance disparity: {best_pair} outperforms {worst_pair} by "
                f"{disparity:.1f}% ROI. Consider removing {worst_pair} from the strategy."
            )

    # Rule 2: Low win rate
    if avg_win_rate is not None and avg_win_rate < 0.5:
        recs.append(
            f"Win rate is {avg_win_rate:.1%} (below 50%). Consider tightening entry conditions "
            "or widening take-profit targets to improve win rate."
        )

    # Rule 3: High win rate — could loosen entry
    if avg_win_rate is not None and avg_win_rate > 0.75:
        recs.append(
            f"Win rate is {avg_win_rate:.1%} (above 75%). Entry conditions may be too strict. "
            "Consider relaxing them to capture more trading opportunities."
        )

    # Rule 4: High drawdown
    if avg_drawdown > 15:
        recs.append(
            f"Average max drawdown is {avg_drawdown:.1f}% (above 15%). Consider tightening "
            "the stop-loss percentage to reduce drawdown risk."
        )

    # Rule 5: Very low drawdown — could loosen SL
    if 0 < avg_drawdown < 3:
        recs.append(
            f"Average max drawdown is only {avg_drawdown:.1f}% (below 3%). The stop-loss may be "
            "too tight, causing premature exits. Consider loosening it for potential gains."
        )

    # Rule 6: Few trades per episode
    if avg_trades < 3:
        recs.append(
            f"Average {avg_trades:.1f} trades per episode is very low. Entry conditions may be "
            "too restrictive. Consider relaxing one or more entry conditions."
        )

    # Rule 7: Too many trades per episode
    if avg_trades > 50:
        recs.append(
            f"Average {avg_trades:.1f} trades per episode is very high. Consider adding filters "
            "(e.g., ADX trend strength) to reduce overtrading."
        )

    # Rule 8: Low Sharpe ratio
    if avg_sharpe is not None and avg_sharpe < 0.5:
        recs.append(
            f"Average Sharpe ratio is {avg_sharpe:.2f} (below 0.5). Risk-adjusted returns are poor. "
            "Consider reducing position size or improving entry timing."
        )

    # Rule 9: ADX analysis
    adx_threshold = entry_conditions.get("adx_above")
    if adx_threshold is not None:
        if float(adx_threshold) > 30:
            recs.append(
                f"ADX entry threshold is {adx_threshold} (high). This filters out many trades. "
                "Consider lowering to 20-25 to capture more trending moves."
            )
        elif float(adx_threshold) < 15:
            recs.append(
                f"ADX entry threshold is {adx_threshold} (low). This allows entries in ranging markets. "
                "Consider raising to 20+ to trade only in trending conditions."
            )

    # Rule 10: Stop loss vs take profit ratio
    sl = exit_conditions.get("stop_loss_pct")
    tp = exit_conditions.get("take_profit_pct")
    if sl is not None and tp is not None:
        sl_val = float(sl)
        tp_val = float(tp)
        if sl_val > 0 and tp_val > 0:
            rr_ratio = tp_val / sl_val
            if rr_ratio < 1.5:
                recs.append(
                    f"Risk/reward ratio is {rr_ratio:.1f}:1 (below 1.5:1). Consider widening "
                    "take-profit or tightening stop-loss for better risk/reward."
                )

    # Rule 11: Negative average ROI
    if avg_roi < 0:
        recs.append(
            f"Average ROI is negative ({avg_roi:.2f}%). The strategy is losing money on average. "
            "Review both entry and exit conditions for fundamental issues."
        )

    return recs
