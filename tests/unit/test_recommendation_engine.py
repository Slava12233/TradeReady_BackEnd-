"""Unit tests for RecommendationEngine."""

from __future__ import annotations

from src.strategies.recommendation_engine import generate_recommendations

BASE_DEFINITION = {
    "pairs": ["BTCUSDT"],
    "entry_conditions": {"rsi_below": 30},
    "exit_conditions": {"stop_loss_pct": 2, "take_profit_pct": 5},
}


def test_pair_disparity():
    """Recommendation generated for pair performance disparity > 5%."""
    results = {
        "avg_roi_pct": 5,
        "avg_win_rate": 0.6,
        "avg_max_drawdown_pct": 5,
        "avg_trades_per_episode": 10,
        "avg_sharpe": 1.0,
    }
    by_pair = {"BTCUSDT": {"avg_roi_pct": 10}, "ETHUSDT": {"avg_roi_pct": 2}}
    recs = generate_recommendations(results, by_pair, BASE_DEFINITION)
    assert any("disparity" in r.lower() for r in recs)


def test_low_win_rate():
    """Recommendation for win rate < 50%."""
    results = {
        "avg_roi_pct": 2,
        "avg_win_rate": 0.35,
        "avg_max_drawdown_pct": 5,
        "avg_trades_per_episode": 10,
        "avg_sharpe": 1.0,
    }
    recs = generate_recommendations(results, {}, BASE_DEFINITION)
    assert any("win rate" in r.lower() for r in recs)


def test_high_win_rate():
    """Recommendation for win rate > 75%."""
    results = {
        "avg_roi_pct": 8,
        "avg_win_rate": 0.85,
        "avg_max_drawdown_pct": 3,
        "avg_trades_per_episode": 5,
        "avg_sharpe": 1.5,
    }
    recs = generate_recommendations(results, {}, BASE_DEFINITION)
    assert any("75%" in r for r in recs)


def test_high_drawdown():
    """Recommendation for drawdown > 15%."""
    results = {
        "avg_roi_pct": 5,
        "avg_win_rate": 0.6,
        "avg_max_drawdown_pct": 20,
        "avg_trades_per_episode": 10,
        "avg_sharpe": 1.0,
    }
    recs = generate_recommendations(results, {}, BASE_DEFINITION)
    assert any("drawdown" in r.lower() for r in recs)


def test_low_drawdown():
    """Recommendation for drawdown < 3%."""
    results = {
        "avg_roi_pct": 2,
        "avg_win_rate": 0.6,
        "avg_max_drawdown_pct": 1.5,
        "avg_trades_per_episode": 10,
        "avg_sharpe": 1.0,
    }
    recs = generate_recommendations(results, {}, BASE_DEFINITION)
    assert any("tight" in r.lower() for r in recs)


def test_few_trades():
    """Recommendation for < 3 trades per episode."""
    results = {
        "avg_roi_pct": 2,
        "avg_win_rate": 0.6,
        "avg_max_drawdown_pct": 5,
        "avg_trades_per_episode": 1.5,
        "avg_sharpe": 1.0,
    }
    recs = generate_recommendations(results, {}, BASE_DEFINITION)
    assert any("restrictive" in r.lower() for r in recs)


def test_low_sharpe():
    """Recommendation for Sharpe < 0.5."""
    results = {
        "avg_roi_pct": 2,
        "avg_win_rate": 0.6,
        "avg_max_drawdown_pct": 5,
        "avg_trades_per_episode": 10,
        "avg_sharpe": 0.3,
    }
    recs = generate_recommendations(results, {}, BASE_DEFINITION)
    assert any("sharpe" in r.lower() for r in recs)


def test_risk_reward_ratio():
    """Recommendation for poor risk/reward ratio."""
    defn = {**BASE_DEFINITION, "exit_conditions": {"stop_loss_pct": 5, "take_profit_pct": 5}}
    results = {
        "avg_roi_pct": 2,
        "avg_win_rate": 0.6,
        "avg_max_drawdown_pct": 5,
        "avg_trades_per_episode": 10,
        "avg_sharpe": 1.0,
    }
    recs = generate_recommendations(results, {}, defn)
    assert any("risk/reward" in r.lower() for r in recs)


def test_negative_roi():
    """Recommendation for negative average ROI."""
    results = {
        "avg_roi_pct": -3,
        "avg_win_rate": 0.4,
        "avg_max_drawdown_pct": 10,
        "avg_trades_per_episode": 10,
        "avg_sharpe": -0.2,
    }
    recs = generate_recommendations(results, {}, BASE_DEFINITION)
    assert any("negative" in r.lower() for r in recs)


def test_no_recommendations_for_good_strategy():
    """A well-performing strategy gets minimal recommendations."""
    results = {
        "avg_roi_pct": 8,
        "avg_win_rate": 0.65,
        "avg_max_drawdown_pct": 5,
        "avg_trades_per_episode": 15,
        "avg_sharpe": 1.5,
    }
    defn = {**BASE_DEFINITION, "exit_conditions": {"stop_loss_pct": 2, "take_profit_pct": 6}}
    recs = generate_recommendations(results, {}, defn)
    # A good strategy should have few or no recommendations
    assert len(recs) <= 2
