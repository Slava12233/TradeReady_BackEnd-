"""Tests for agent/trading/strategy_manager.py.

Covers:
- StrategyManager construction and threshold configuration
- record_strategy_result: window growth, capping, and persistence trigger
- get_performance: single strategy, all strategies, unknown strategy, invalid period
- detect_degradation: insufficient trades guard, per-metric thresholds (warning/critical/disable),
  no alerts on healthy strategy
- suggest_adjustments: no data, healthy strategy, low win-rate, low Sharpe,
  consecutive losses, conservative values
- compare_strategies: no data, invalid period, single strategy, Sharpe ranking
- Pure helpers: _compute_sharpe, _compute_max_drawdown,
  _compute_trailing_consecutive_losses, _count_completed_trades, _count_winning_trades,
  _compute_metrics, _validate_period, _build_comparison_recommendation
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from decimal import Decimal
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.trading.signal_generator import TradingSignal
from agent.trading.strategy_manager import (
    StrategyManager,
    _build_comparison_recommendation,
    _compute_max_drawdown,
    _compute_metrics,
    _compute_sharpe,
    _compute_trailing_consecutive_losses,
    _count_completed_trades,
    _count_winning_trades,
    _TradeRecord,
    _validate_period,
)

# ── Test helpers ──────────────────────────────────────────────────────────────


def _make_signal(action: str = "buy", confidence: float = 0.7) -> TradingSignal:
    """Build a minimal TradingSignal for testing."""
    return TradingSignal(
        symbol="BTCUSDT",
        action=action,
        confidence=confidence,
        agreement_rate=0.67,
        generated_at=datetime.now(UTC),
    )


def _make_record(
    *,
    outcome_pnl: Decimal | None = None,
    action: str = "buy",
    strategy_name: str = "test_strategy",
) -> _TradeRecord:
    """Build a _TradeRecord for testing."""
    return _TradeRecord(
        strategy_name=strategy_name,
        signal=_make_signal(action=action),
        outcome_pnl=outcome_pnl,
        recorded_at=datetime.now(UTC),
    )


def _make_window(pnls: list[Decimal | None], action: str = "buy") -> deque[_TradeRecord]:
    """Build a deque of _TradeRecord from a list of PnL values."""
    window: deque[_TradeRecord] = deque()
    for pnl in pnls:
        window.append(_make_record(outcome_pnl=pnl, action=action))
    return window


# ── _validate_period ──────────────────────────────────────────────────────────


class TestValidatePeriod:
    def test_daily_accepted(self) -> None:
        _validate_period("daily")  # no exception

    def test_weekly_accepted(self) -> None:
        _validate_period("weekly")

    def test_monthly_accepted(self) -> None:
        _validate_period("monthly")

    def test_invalid_period_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid period"):
            _validate_period("hourly")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            _validate_period("")


# ── _compute_sharpe ──────────────────────────────────────────────────────────


class TestComputeSharpe:
    def test_empty_series_returns_zero(self) -> None:
        assert _compute_sharpe([]) == 0.0

    def test_single_element_returns_zero(self) -> None:
        assert _compute_sharpe([100.0]) == 0.0

    def test_constant_series_returns_zero(self) -> None:
        # All identical PnLs → std dev = 0 → Sharpe = 0.0
        assert _compute_sharpe([10.0, 10.0, 10.0]) == 0.0

    def test_positive_mean_positive_sharpe(self) -> None:
        sharpe = _compute_sharpe([10.0, 12.0, 8.0, 15.0, 9.0])
        assert sharpe > 0.0

    def test_negative_mean_negative_sharpe(self) -> None:
        sharpe = _compute_sharpe([-10.0, -12.0, -8.0, -15.0, -9.0])
        assert sharpe < 0.0

    def test_annualisation_scales_by_sqrt_factor(self) -> None:
        pnls = [1.0, 2.0, 3.0, 4.0, 5.0]
        sharpe_252 = _compute_sharpe(pnls, annualisation_factor=252.0)
        sharpe_1 = _compute_sharpe(pnls, annualisation_factor=1.0)
        assert abs(sharpe_252 / sharpe_1 - math.sqrt(252)) < 0.01

    def test_two_distinct_elements_computable(self) -> None:
        # Minimum viable: two non-equal values should not return 0.0
        assert _compute_sharpe([10.0, 20.0]) != 0.0


# ── _compute_max_drawdown ─────────────────────────────────────────────────────


class TestComputeMaxDrawdown:
    def test_empty_series_returns_zero(self) -> None:
        assert _compute_max_drawdown([]) == 0.0

    def test_single_element_returns_zero(self) -> None:
        assert _compute_max_drawdown([100.0]) == 0.0

    def test_monotone_gain_no_drawdown(self) -> None:
        assert _compute_max_drawdown([100.0, 200.0, 300.0]) == 0.0

    def test_small_dip_produces_expected_drawdown(self) -> None:
        # Peak = 10100 after first +100; trough = 9900 after -200; dd ≈ 1.98%
        dd = _compute_max_drawdown([100.0, -200.0, 100.0], starting_balance=10_000.0)
        assert 0.01 < dd < 0.03

    def test_total_loss_capped_at_one(self) -> None:
        dd = _compute_max_drawdown([-10_000.0, -100.0], starting_balance=10_000.0)
        assert dd == pytest.approx(1.0, rel=0.01)

    def test_result_bounded_between_zero_and_one(self) -> None:
        dd = _compute_max_drawdown([100.0, -500.0, 200.0, -300.0, 400.0], starting_balance=10_000.0)
        assert 0.0 <= dd <= 1.0


# ── _compute_trailing_consecutive_losses ──────────────────────────────────────


class TestComputeTrailingConsecutiveLosses:
    def test_all_wins_returns_zero(self) -> None:
        window = _make_window([Decimal("10"), Decimal("20"), Decimal("5")])
        assert _compute_trailing_consecutive_losses(window) == 0

    def test_all_losses_returns_full_count(self) -> None:
        window = _make_window([Decimal("-5"), Decimal("-10"), Decimal("-3")])
        assert _compute_trailing_consecutive_losses(window) == 3

    def test_trailing_win_resets_streak(self) -> None:
        window = _make_window([Decimal("-5"), Decimal("-10"), Decimal("15")])
        assert _compute_trailing_consecutive_losses(window) == 0

    def test_only_trailing_losses_counted(self) -> None:
        window = _make_window([Decimal("10"), Decimal("-5"), Decimal("-8"), Decimal("-2")])
        assert _compute_trailing_consecutive_losses(window) == 3

    def test_zero_pnl_counts_as_loss(self) -> None:
        window = _make_window([Decimal("0"), Decimal("-1")])
        assert _compute_trailing_consecutive_losses(window) == 2

    def test_open_positions_skipped_in_streak(self) -> None:
        # None records are ignored — streak must pierce through them
        window = _make_window([Decimal("-5"), None, None, Decimal("-3")])
        assert _compute_trailing_consecutive_losses(window) == 2

    def test_all_open_returns_zero(self) -> None:
        window = _make_window([None, None, None])
        assert _compute_trailing_consecutive_losses(window) == 0

    def test_empty_window_returns_zero(self) -> None:
        assert _compute_trailing_consecutive_losses(deque()) == 0


# ── _count_completed_trades ───────────────────────────────────────────────────


class TestCountCompletedTrades:
    def test_all_open_returns_zero(self) -> None:
        window = _make_window([None, None, None])
        assert _count_completed_trades(window) == 0

    def test_all_closed_returns_correct_count(self) -> None:
        window = _make_window([Decimal("10"), Decimal("-5"), Decimal("0")])
        assert _count_completed_trades(window) == 3

    def test_mixed_open_and_closed(self) -> None:
        window = _make_window([Decimal("10"), None, Decimal("-5"), None])
        assert _count_completed_trades(window) == 2

    def test_empty_window_returns_zero(self) -> None:
        assert _count_completed_trades(deque()) == 0


# ── _count_winning_trades ─────────────────────────────────────────────────────


class TestCountWinningTrades:
    def test_all_wins(self) -> None:
        window = _make_window([Decimal("10"), Decimal("5"), Decimal("1")])
        assert _count_winning_trades(window) == 3

    def test_all_losses(self) -> None:
        window = _make_window([Decimal("-10"), Decimal("-5")])
        assert _count_winning_trades(window) == 0

    def test_break_even_not_counted_as_win(self) -> None:
        window = _make_window([Decimal("0"), Decimal("5")])
        assert _count_winning_trades(window) == 1

    def test_open_positions_excluded(self) -> None:
        window = _make_window([Decimal("10"), None, Decimal("-5")])
        assert _count_winning_trades(window) == 1


# ── _compute_metrics ──────────────────────────────────────────────────────────


class TestComputeMetrics:
    def test_empty_window_all_zeros(self) -> None:
        metrics = _compute_metrics(deque())
        assert metrics.total_signals == 0
        assert metrics.trades_taken == 0
        assert metrics.win_rate == 0.0
        assert metrics.sharpe_ratio == 0.0
        assert metrics.max_drawdown == 0.0
        assert metrics.total_pnl == Decimal("0")
        assert metrics.avg_pnl_per_trade == Decimal("0")
        assert metrics.consecutive_losses == 0

    def test_only_open_positions_pnl_zero(self) -> None:
        window = _make_window([None, None, None])
        metrics = _compute_metrics(window)
        assert metrics.total_signals == 3
        assert metrics.win_rate == 0.0
        assert metrics.total_pnl == Decimal("0")

    def test_correct_win_rate_from_mixed_outcomes(self) -> None:
        window = _make_window([Decimal("10"), None, Decimal("-5"), Decimal("8")])
        metrics = _compute_metrics(window)
        # 2 wins out of 3 completed trades
        assert metrics.win_rate == pytest.approx(2 / 3, rel=0.01)
        assert metrics.total_pnl == Decimal("13")

    def test_hold_signals_not_counted_as_trades_taken(self) -> None:
        d: deque[_TradeRecord] = deque()
        d.append(_make_record(outcome_pnl=Decimal("5"), action="hold"))
        d.append(_make_record(outcome_pnl=Decimal("10"), action="buy"))
        metrics = _compute_metrics(d)
        assert metrics.trades_taken == 1  # only "buy" counts

    def test_consecutive_losses_propagated(self) -> None:
        window = _make_window([Decimal("10"), Decimal("-5"), Decimal("-3"), Decimal("-2")])
        metrics = _compute_metrics(window)
        assert metrics.consecutive_losses == 3


# ── StrategyManager construction ──────────────────────────────────────────────


class TestStrategyManagerConstruction:
    def test_default_construction_window_size_50(self) -> None:
        manager = StrategyManager()
        assert manager._window_size == 50

    def test_custom_window_size_stored(self) -> None:
        manager = StrategyManager(window_size=100)
        assert manager._window_size == 100

    def test_zero_window_size_raises(self) -> None:
        with pytest.raises(ValueError, match="window_size must be >= 1"):
            StrategyManager(window_size=0)

    def test_negative_window_size_raises(self) -> None:
        with pytest.raises(ValueError):
            StrategyManager(window_size=-5)

    def test_custom_thresholds_stored(self) -> None:
        manager = StrategyManager(
            sharpe_warning_threshold=0.3,
            win_rate_warning_threshold=0.35,
            max_drawdown_warning_threshold=0.10,
            consecutive_losses_warning_threshold=4,
        )
        assert manager._sharpe_warning == 0.3
        assert manager._win_rate_warning == 0.35
        assert manager._drawdown_warning == 0.10
        assert manager._consec_warning == 4


# ── record_strategy_result ────────────────────────────────────────────────────


class TestRecordStrategyResult:
    async def test_first_record_appended_to_window(self) -> None:
        manager = StrategyManager()
        await manager.record_strategy_result(
            "agent-1", "rl", _make_signal(), outcome_pnl=Decimal("42")
        )
        window = manager._windows["agent-1"]["rl"]
        assert len(window) == 1
        assert window[0].outcome_pnl == Decimal("42")

    async def test_window_capped_at_window_size(self) -> None:
        manager = StrategyManager(window_size=5)
        for i in range(8):
            await manager.record_strategy_result(
                "agent-1", "rl", _make_signal(), outcome_pnl=Decimal(str(i))
            )
        assert len(manager._windows["agent-1"]["rl"]) == 5

    async def test_open_position_stored_with_none_pnl(self) -> None:
        manager = StrategyManager()
        await manager.record_strategy_result(
            "agent-1", "regime", _make_signal(), outcome_pnl=None
        )
        assert manager._windows["agent-1"]["regime"][0].outcome_pnl is None

    async def test_multiple_strategies_tracked_independently(self) -> None:
        manager = StrategyManager()
        await manager.record_strategy_result("agent-1", "rl", _make_signal(), Decimal("10"))
        await manager.record_strategy_result("agent-1", "ensemble", _make_signal(), Decimal("20"))
        assert len(manager._windows["agent-1"]["rl"]) == 1
        assert len(manager._windows["agent-1"]["ensemble"]) == 1

    async def test_multiple_agents_tracked_independently(self) -> None:
        manager = StrategyManager()
        await manager.record_strategy_result("agent-A", "rl", _make_signal(), Decimal("1"))
        await manager.record_strategy_result("agent-B", "rl", _make_signal(), Decimal("2"))
        assert len(manager._windows["agent-A"]["rl"]) == 1
        assert len(manager._windows["agent-B"]["rl"]) == 1

    async def test_no_session_factory_no_error_when_window_fills(self) -> None:
        manager = StrategyManager(window_size=3, session_factory=None)
        for _ in range(5):
            await manager.record_strategy_result("a1", "rl", _make_signal(), Decimal("1"))
        # Should not raise even when window overflows

    async def test_persist_called_when_window_reaches_capacity(self) -> None:
        mock_factory = MagicMock()
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock()

        patch_target = "agent.trading.strategy_manager.StrategyManager._persist_period_summary"
        with patch(patch_target, new_callable=AsyncMock) as mock_persist:
            manager = StrategyManager(window_size=2, session_factory=mock_factory)
            # First record — window NOT full yet
            await manager.record_strategy_result("a1", "rl", _make_signal(), Decimal("1"))
            mock_persist.assert_not_called()
            # Second record — fills the window
            await manager.record_strategy_result("a1", "rl", _make_signal(), Decimal("2"))
            mock_persist.assert_called_once()


# ── get_performance ───────────────────────────────────────────────────────────


class TestGetPerformance:
    async def test_no_data_returns_empty_list(self) -> None:
        manager = StrategyManager()
        assert await manager.get_performance("unknown") == []

    async def test_specific_strategy_returned(self) -> None:
        manager = StrategyManager()
        for pnl in [Decimal("10"), Decimal("-5")]:
            await manager.record_strategy_result("a1", "rl", _make_signal(), pnl)
        result = await manager.get_performance("a1", strategy_name="rl", period="weekly")
        assert len(result) == 1
        assert result[0].strategy_name == "rl"
        assert result[0].period == "weekly"

    async def test_all_strategies_returned_when_name_omitted(self) -> None:
        manager = StrategyManager()
        await manager.record_strategy_result("a1", "rl", _make_signal(), Decimal("10"))
        await manager.record_strategy_result("a1", "regime", _make_signal(), Decimal("5"))
        result = await manager.get_performance("a1")
        names = {p.strategy_name for p in result}
        assert "rl" in names and "regime" in names

    async def test_unknown_strategy_name_returns_empty(self) -> None:
        manager = StrategyManager()
        await manager.record_strategy_result("a1", "rl", _make_signal(), Decimal("10"))
        assert await manager.get_performance("a1", strategy_name="nonexistent") == []

    async def test_invalid_period_raises(self) -> None:
        manager = StrategyManager()
        with pytest.raises(ValueError, match="Invalid period"):
            await manager.get_performance("a1", period="yearly")

    async def test_win_rate_computed_correctly(self) -> None:
        manager = StrategyManager()
        for pnl in [Decimal("10"), Decimal("5"), Decimal("-3")]:
            await manager.record_strategy_result("a1", "rl", _make_signal(), pnl)
        result = await manager.get_performance("a1", strategy_name="rl")
        assert result[0].win_rate == pytest.approx(2 / 3, rel=0.01)


# ── detect_degradation ────────────────────────────────────────────────────────


class TestDetectDegradation:
    async def test_no_data_returns_empty(self) -> None:
        manager = StrategyManager()
        assert await manager.detect_degradation("unknown") == []

    async def test_below_min_trades_skipped(self) -> None:
        # Default min_trades=10; only 5 completed → no checks run
        manager = StrategyManager(min_trades_for_degradation=10)
        for _ in range(5):
            await manager.record_strategy_result("a1", "rl", _make_signal(), Decimal("-50"))
        assert await manager.detect_degradation("a1") == []

    async def test_win_rate_warning_fires_above_critical_below_warning(self) -> None:
        # win_rate between critical (0.30) and warning (0.40) → warning
        manager = StrategyManager(
            win_rate_warning_threshold=0.40,
            win_rate_critical_threshold=0.30,
            min_trades_for_degradation=5,
        )
        # 3 wins, 7 losses = 30% — exactly at critical boundary (not strictly below)
        # Use 2 wins, 8 losses = 20% to be clearly below warning
        pnls = [Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10")] + [Decimal("-5")] * 7
        for pnl in pnls:
            await manager.record_strategy_result("a1", "rl", _make_signal(), pnl)
        alerts = await manager.detect_degradation("a1")
        win_rate_alerts = [a for a in alerts if a.metric == "win_rate"]
        assert len(win_rate_alerts) >= 1

    async def test_win_rate_critical_fires_below_critical_threshold(self) -> None:
        manager = StrategyManager(
            win_rate_warning_threshold=0.40,
            win_rate_critical_threshold=0.30,
            min_trades_for_degradation=5,
        )
        # 1 win, 9 losses = 10% win rate → below critical (0.30)
        pnls = [Decimal("10")] + [Decimal("-5")] * 9
        for pnl in pnls:
            await manager.record_strategy_result("a1", "rl", _make_signal(), pnl)
        alerts = await manager.detect_degradation("a1")
        critical = [a for a in alerts if a.metric == "win_rate" and a.severity == "critical"]
        assert len(critical) == 1

    async def test_sharpe_warning_fires_when_negative(self) -> None:
        manager = StrategyManager(
            sharpe_warning_threshold=0.5,
            sharpe_critical_threshold=0.0,
            min_trades_for_degradation=5,
        )
        # All losses → negative Sharpe (below critical 0.0 → critical alert)
        for _ in range(12):
            await manager.record_strategy_result("a1", "rl", _make_signal(), Decimal("-3"))
        alerts = await manager.detect_degradation("a1")
        sharpe_alerts = [a for a in alerts if a.metric == "sharpe"]
        assert len(sharpe_alerts) >= 1

    async def test_consecutive_losses_warning_threshold(self) -> None:
        manager = StrategyManager(
            consecutive_losses_warning_threshold=5,
            consecutive_losses_critical_threshold=8,
            consecutive_losses_disable_threshold=12,
            min_trades_for_degradation=5,
        )
        # 1 win + 6 consecutive losses = streak of 6 (> warning 5, < critical 8)
        pnls = [Decimal("10")] + [Decimal("-1")] * 6
        for pnl in pnls:
            await manager.record_strategy_result("a1", "rl", _make_signal(), pnl)
        alerts = await manager.detect_degradation("a1")
        consec_alerts = [a for a in alerts if a.metric == "consecutive_losses"]
        assert len(consec_alerts) >= 1
        assert consec_alerts[0].severity == "warning"

    async def test_consecutive_losses_disable_threshold(self) -> None:
        manager = StrategyManager(
            consecutive_losses_warning_threshold=2,
            consecutive_losses_critical_threshold=3,
            consecutive_losses_disable_threshold=5,
            min_trades_for_degradation=5,
        )
        # 1 win + 8 consecutive losses — exceeds disable threshold (5)
        pnls = [Decimal("50")] + [Decimal("-1")] * 8
        for pnl in pnls:
            await manager.record_strategy_result("a1", "rl", _make_signal(), pnl)
        alerts = await manager.detect_degradation("a1")
        disable_alerts = [
            a for a in alerts
            if a.metric == "consecutive_losses" and a.severity == "disable"
        ]
        assert len(disable_alerts) == 1

    async def test_healthy_strategy_no_alerts(self) -> None:
        manager = StrategyManager(min_trades_for_degradation=5)
        # All profitable, increasing — high Sharpe, 100% win rate, no drawdown
        for i in range(15):
            await manager.record_strategy_result(
                "a1", "rl", _make_signal(), Decimal(str(10 + i))
            )
        assert await manager.detect_degradation("a1") == []

    async def test_alert_fields_fully_populated(self) -> None:
        manager = StrategyManager(
            win_rate_warning_threshold=0.40,
            win_rate_critical_threshold=0.30,
            min_trades_for_degradation=5,
        )
        pnls = [Decimal("10")] + [Decimal("-5")] * 9  # 10% win rate
        for pnl in pnls:
            await manager.record_strategy_result("a1", "bad_strat", _make_signal(), pnl)
        alerts = await manager.detect_degradation("a1")
        win_rate_alerts = [a for a in alerts if a.metric == "win_rate"]
        assert len(win_rate_alerts) == 1
        alert = win_rate_alerts[0]
        assert alert.strategy_name == "bad_strat"
        assert alert.severity == "critical"
        assert alert.threshold_value == 0.30
        assert 0.0 <= alert.current_value <= 1.0
        assert len(alert.recommendation) > 0
        assert isinstance(alert.detected_at, datetime)


# ── suggest_adjustments ───────────────────────────────────────────────────────


class TestSuggestAdjustments:
    async def test_no_data_returns_empty(self) -> None:
        manager = StrategyManager()
        assert await manager.suggest_adjustments("unknown", "rl") == []

    async def test_healthy_strategy_no_suggestions(self) -> None:
        manager = StrategyManager(min_trades_for_degradation=5)
        for i in range(15):
            await manager.record_strategy_result(
                "a1", "healthy", _make_signal(), Decimal(str(20 + i))
            )
        assert await manager.suggest_adjustments("a1", "healthy") == []

    async def test_low_win_rate_suggests_position_size_reduction(self) -> None:
        manager = StrategyManager(
            win_rate_warning_threshold=0.40,
            min_trades_for_degradation=5,
        )
        pnls = [Decimal("10")] + [Decimal("-5")] * 9  # 10% win rate
        for pnl in pnls:
            await manager.record_strategy_result("a1", "weak", _make_signal(), pnl)
        adjustments = await manager.suggest_adjustments("a1", "weak")
        assert any(a.parameter == "position_size_pct" for a in adjustments)

    async def test_low_sharpe_suggests_higher_confidence_threshold(self) -> None:
        manager = StrategyManager(
            sharpe_warning_threshold=0.5,
            min_trades_for_degradation=5,
        )
        for _ in range(12):
            await manager.record_strategy_result("a1", "loser", _make_signal(), Decimal("-2"))
        adjustments = await manager.suggest_adjustments("a1", "loser")
        assert any(a.parameter == "confidence_threshold" for a in adjustments)

    async def test_consecutive_losses_suggest_cooldown(self) -> None:
        manager = StrategyManager(
            consecutive_losses_warning_threshold=5,
            min_trades_for_degradation=5,
        )
        pnls = [Decimal("10")] + [Decimal("-1")] * 7
        for pnl in pnls:
            await manager.record_strategy_result("a1", "streak", _make_signal(), pnl)
        adjustments = await manager.suggest_adjustments("a1", "streak")
        assert any(a.parameter == "cooldown_trades_after_loss_streak" for a in adjustments)

    async def test_suggested_position_size_smaller_than_current(self) -> None:
        manager = StrategyManager(
            win_rate_warning_threshold=0.40,
            min_trades_for_degradation=5,
        )
        pnls = [Decimal("10")] + [Decimal("-5")] * 9
        for pnl in pnls:
            await manager.record_strategy_result("a1", "strat", _make_signal(), pnl)
        adjustments = await manager.suggest_adjustments("a1", "strat")
        size_adj = next((a for a in adjustments if a.parameter == "position_size_pct"), None)
        if size_adj:
            assert float(size_adj.suggested_value) < float(size_adj.current_value)

    async def test_all_adjustment_fields_present(self) -> None:
        manager = StrategyManager(
            win_rate_warning_threshold=0.40,
            min_trades_for_degradation=5,
        )
        pnls = [Decimal("10")] + [Decimal("-5")] * 9
        for pnl in pnls:
            await manager.record_strategy_result("a1", "bad", _make_signal(), pnl)
        adjustments = await manager.suggest_adjustments("a1", "bad")
        for adj in adjustments:
            assert adj.strategy_name == "bad"
            assert adj.parameter
            assert adj.current_value
            assert adj.suggested_value
            assert adj.rationale
            assert adj.expected_impact
            assert adj.priority in ("low", "medium", "high")

    async def test_high_drawdown_suggests_tighter_stop_loss(self) -> None:
        # max_drawdown_warning_threshold = 0.10 (10% of 10000 starting balance = $1000).
        # We need peak-to-trough > $1000.
        # Sequence: +2000 (peak=12000), then -1500 each × 8 = -12000 total from peak.
        # Drawdown at trough = (12000 - trough) / 12000 which exceeds 10%.
        manager = StrategyManager(
            max_drawdown_warning_threshold=0.10,
            min_trades_for_degradation=5,
        )
        pnls = [Decimal("2000")] + [Decimal("-1500")] * 8
        for pnl in pnls:
            await manager.record_strategy_result("a1", "dd_strat", _make_signal(), pnl)
        adjustments = await manager.suggest_adjustments("a1", "dd_strat")
        assert any(a.parameter == "stop_loss_pct" for a in adjustments)


# ── compare_strategies ────────────────────────────────────────────────────────


class TestCompareStrategies:
    async def test_no_data_raises_value_error(self) -> None:
        manager = StrategyManager()
        with pytest.raises(ValueError, match="No performance data"):
            await manager.compare_strategies("unknown")

    async def test_invalid_period_raises(self) -> None:
        manager = StrategyManager()
        await manager.record_strategy_result("a1", "rl", _make_signal(), Decimal("5"))
        with pytest.raises(ValueError, match="Invalid period"):
            await manager.compare_strategies("a1", period="hourly")

    async def test_single_strategy_comparison_still_works(self) -> None:
        manager = StrategyManager()
        for _ in range(5):
            await manager.record_strategy_result("a1", "only", _make_signal(), Decimal("10"))
        comparison = await manager.compare_strategies("a1")
        assert comparison.best_strategy == "only"
        assert comparison.worst_strategy == "only"
        assert len(comparison.ranking) == 1

    async def test_ranking_ordered_by_sharpe_descending(self) -> None:
        manager = StrategyManager()
        # "good": consistent gains → high Sharpe
        for i in range(15):
            await manager.record_strategy_result(
                "a1", "good", _make_signal(), Decimal(str(10 + i * 0.5))
            )
        # "bad": consistent losses → negative Sharpe
        for i in range(15):
            await manager.record_strategy_result(
                "a1", "bad", _make_signal(), Decimal(str(-(10 + i * 0.5)))
            )
        comparison = await manager.compare_strategies("a1")
        assert comparison.ranking[0] == "good"
        assert comparison.ranking[-1] == "bad"
        assert comparison.best_strategy == "good"
        assert comparison.worst_strategy == "bad"

    async def test_comparison_fields_fully_populated(self) -> None:
        manager = StrategyManager()
        for strat in ["rl", "regime", "ensemble"]:
            for pnl in [Decimal("10"), Decimal("-5"), Decimal("8")]:
                await manager.record_strategy_result("a1", strat, _make_signal(), pnl)
        comparison = await manager.compare_strategies("a1", period="daily")
        assert comparison.period == "daily"
        assert len(comparison.strategies) == 3
        assert len(comparison.ranking) == 3
        assert comparison.recommendation
        assert isinstance(comparison.generated_at, datetime)

    async def test_strategies_dict_keyed_by_name(self) -> None:
        manager = StrategyManager()
        for strat in ["rl", "ensemble"]:
            await manager.record_strategy_result("a1", strat, _make_signal(), Decimal("5"))
        comparison = await manager.compare_strategies("a1")
        assert "rl" in comparison.strategies
        assert "ensemble" in comparison.strategies


# ── _build_comparison_recommendation ─────────────────────────────────────────


class TestBuildComparisonRecommendation:
    def _make_perf(self, name: str, sharpe: float, win_rate: float) -> object:
        from agent.models.ecosystem import StrategyPerformance  # noqa: PLC0415
        return StrategyPerformance(
            strategy_name=name,
            period="weekly",
            total_signals=50,
            trades_taken=30,
            win_rate=win_rate,
            sharpe_ratio=sharpe,
            max_drawdown=0.05,
            total_pnl=Decimal("100"),
            avg_pnl_per_trade=Decimal("3.33"),
            consecutive_losses=0,
        )

    def test_single_strategy_no_comparison_possible(self) -> None:
        perfs = {"only": self._make_perf("only", 1.0, 0.6)}
        rec = _build_comparison_recommendation(perfs, ["only"])
        assert "No comparison possible" in rec

    def test_clearly_different_strategies_both_named(self) -> None:
        perfs = {
            "good": self._make_perf("good", 1.2, 0.65),
            "bad": self._make_perf("bad", -0.5, 0.25),
        }
        rec = _build_comparison_recommendation(perfs, ["good", "bad"])
        assert "good" in rec
        assert "bad" in rec

    def test_similar_strategies_no_reallocation(self) -> None:
        perfs = {
            "a": self._make_perf("a", 0.8, 0.55),
            "b": self._make_perf("b", 0.75, 0.53),
        }
        rec = _build_comparison_recommendation(perfs, ["a", "b"])
        assert "No reallocation recommended" in rec

    def test_recommendation_is_non_empty_string(self) -> None:
        perfs = {
            "x": self._make_perf("x", 1.0, 0.6),
            "y": self._make_perf("y", 0.2, 0.45),
        }
        rec = _build_comparison_recommendation(perfs, ["x", "y"])
        assert isinstance(rec, str)
        assert len(rec) > 10


# ── Integration — full workflow ───────────────────────────────────────────────


class TestIntegrationWorkflow:
    """Record trades across two strategies, then verify performance, degradation, and compare."""

    async def test_full_workflow(self) -> None:
        manager = StrategyManager(window_size=50, min_trades_for_degradation=10)

        # Healthy strategy: 15 profitable trades
        for i in range(15):
            await manager.record_strategy_result(
                "agent-xyz", "good", _make_signal("buy"), Decimal(str(5 + i))
            )

        # Degraded strategy: 1 win + 11 consecutive losses
        await manager.record_strategy_result("agent-xyz", "bad", _make_signal("hold"), None)
        for _ in range(11):
            await manager.record_strategy_result(
                "agent-xyz", "bad", _make_signal("buy"), Decimal("-3")
            )

        # get_performance returns both
        perfs = await manager.get_performance("agent-xyz")
        assert len(perfs) == 2

        # detect_degradation flags "bad" but not "good"
        alerts = await manager.detect_degradation("agent-xyz")
        flagged = {a.strategy_name for a in alerts}
        assert "bad" in flagged
        assert "good" not in flagged

        # compare_strategies: "good" ranks first
        comparison = await manager.compare_strategies("agent-xyz")
        assert comparison.best_strategy == "good"
        assert comparison.worst_strategy == "bad"
