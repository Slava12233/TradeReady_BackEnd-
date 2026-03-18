"""Unit tests for TestAggregator."""

from __future__ import annotations

from src.strategies.test_aggregator import TestAggregator


def _make_episode(roi: float = 5.0, sharpe: float = 1.0, drawdown: float = 3.0,
                  trades: int = 10, win_rate: float = 0.6) -> dict:
    return {
        "roi_pct": roi,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": drawdown,
        "total_trades": trades,
        "win_rate": win_rate,
    }


def test_empty_episodes():
    """Empty list returns zero-value results."""
    result = TestAggregator.aggregate([])
    assert result["episodes_completed"] == 0
    assert result["avg_roi_pct"] == 0


def test_single_episode():
    """Single episode returns its own metrics."""
    result = TestAggregator.aggregate([_make_episode(roi=5.0, sharpe=1.2, drawdown=3.0, trades=10)])
    assert result["episodes_completed"] == 1
    assert result["avg_roi_pct"] == 5.0
    assert result["best_roi_pct"] == 5.0
    assert result["worst_roi_pct"] == 5.0
    assert result["total_trades"] == 10


def test_multiple_episodes_averages():
    """Multiple episodes are averaged correctly."""
    episodes = [
        _make_episode(roi=10.0, sharpe=1.5, drawdown=5.0, trades=20, win_rate=0.7),
        _make_episode(roi=-2.0, sharpe=0.3, drawdown=8.0, trades=15, win_rate=0.4),
        _make_episode(roi=6.0, sharpe=1.0, drawdown=4.0, trades=12, win_rate=0.6),
    ]
    result = TestAggregator.aggregate(episodes)
    assert result["episodes_completed"] == 3
    assert result["episodes_profitable"] == 2
    assert abs(result["avg_roi_pct"] - (10 - 2 + 6) / 3) < 0.01
    assert result["best_roi_pct"] == 10.0
    assert result["worst_roi_pct"] == -2.0
    assert result["total_trades"] == 47


def test_profitable_percentage():
    """Profitable episode percentage is calculated correctly."""
    episodes = [
        _make_episode(roi=5.0),
        _make_episode(roi=-1.0),
        _make_episode(roi=3.0),
        _make_episode(roi=-2.0),
    ]
    result = TestAggregator.aggregate(episodes)
    assert result["episodes_profitable_pct"] == 50.0


def test_std_roi():
    """Standard deviation is calculated for multiple episodes."""
    episodes = [
        _make_episode(roi=10.0),
        _make_episode(roi=20.0),
    ]
    result = TestAggregator.aggregate(episodes)
    assert result["std_roi_pct"] > 0
