"""Unit tests for agent.trading.strategy_manager.

Tests cover:
- _validate_period — valid and invalid period values
- _compute_sharpe — zero, single-point, positive, negative PnL series
- _compute_max_drawdown — monotone gain, monotone loss, recovery
- _compute_trailing_consecutive_losses — all wins, all losses, mixed, open positions
- _count_completed_trades — None vs non-None outcome_pnl
- _count_winning_trades — wins and losses counting
- _compute_metrics — empty window, only open positions, completed trades
- StrategyManager construction — valid and invalid window_size
- StrategyManager.record_strategy_result — window growth and cap
- StrategyManager.get_performance — single strategy, all strategies, unknown strategy
- StrategyManager.detect_degradation — no data, below thresholds, above thresholds
- StrategyManager.suggest_adjustments — no data, weak strategy, healthy strategy
- StrategyManager.compare_strategies — single strategy, ranking, recommendation
- StrategyManager persistence — session_factory=None skips persist silently
"""

from __future__ import annotations

import math
from collections import deque
from datetime import UTC, datetime
from decimal import Decimal
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

# ── Helpers ────────────────────────────────────────────────────────────────────


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
    d: deque[_TradeRecord] = deque()
    for pnl in pnls:
        d.append(_make_record(outcome_pnl=pnl, action=action))
    return d


# ── _validate_period ───────────────────────────────────────────────────────────


class TestValidatePeriod:
    def test_daily_accepted(self) -> None:
        _validate_period("daily")  # no exception

    def test_weekly_accepted(self) -> None:
        _validate_period("weekly")

    def test_monthly_accepted(self) -> None:
        _validate_period("monthly")

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid period"):
            _validate_period("hourly")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            _validate_period("")


# ── _compute_sharpe ────────────────────────────────────────────────────────────


class TestComputeSharpe:
    def test_empty_series_returns_zero(self) -> None:
        assert _compute_sharpe([]) == 0.0

    def test_single_element_returns_zero(self) -> None:
        assert _compute_sharpe([100.0]) == 0.0

    def test_constant_series_returns_zero(self) -> None:
        # All identical PnLs → std dev = 0 → Sharpe = 0.0
        assert _compute_sharpe([10.0, 10.0, 10.0]) == 0.0

    def test_positive_mean_positive_sharpe(self) -> None:
        pnls = [10.0, 12.0, 8.0, 15.0, 9.0]
        sharpe = _compute_sharpe(pnls)
        assert sharpe > 0.0

    def test_negative_mean_negative_sharpe(self) -> None:
        pnls = [-10.0, -12.0, -8.0, -15.0, -9.0]
        sharpe = _compute_sharpe(pnls)
        assert sharpe < 0.0

    def test_annualisation_factor_scales_result(self) -> None:
        pnls = [1.0, 2.0, 3.0, 4.0, 5.0]
        sharpe_252 = _compute_sharpe(pnls, annualisation_factor=252.0)
        sharpe_1 = _compute_sharpe(pnls, annualisation_factor=1.0)
        # sqrt(252) ≈ 15.87 — the ratio should match
        assert abs(sharpe_252 / sharpe_1 - math.sqrt(252)) < 0.01

    def test_two_elements_computable(self) -> None:
        # Minimum viable input — two elements should not return 0.0 for non-equal values
        sharpe = _compute_sharpe([10.0, 20.0])
        assert sharpe != 0.0


# ── _compute_max_drawdown ──────────────────────────────────────────────────────


class TestComputeMaxDrawdown:
    def test_empty_series_returns_zero(self) -> None:
        assert _compute_max_drawdown([]) == 0.0

    def test_single_element_returns_zero(self) -> None:
        assert _compute_max_drawdown([100.0]) == 0.0

    def test_monotone_gain_returns_zero(self) -> None:
        # Equity only goes up — no drawdown.
        assert _compute_max_drawdown([100.0, 200.0, 300.0]) == 0.0

    def test_single_loss_then_recovery(self) -> None:
        # Peak=10000+100=10100; trough=10100-200=9900; dd=(10100-9900)/10100≈1.98%
        dd = _compute_max_drawdown([100.0, -200.0, 100.0], starting_balance=10_000.0)
        assert 0.01 < dd < 0.03

    def test_total_loss_is_one(self) -> None:
        # Starting balance fully lost.
        dd = _compute_max_drawdown([-10_000.0, -100.0], starting_balance=10_000.0)
        assert dd == pytest.approx(1.0, rel=0.01)

    def test_result_bounded_between_zero_and_one(self) -> None:
        pnls = [100.0, -500.0, 200.0, -300.0, 400.0]
        dd = _compute_max_drawdown(pnls, starting_balance=10_000.0)
        assert 0.0 <= dd <= 1.0


# ── _compute_trailing_consecutive_losses ───────────────────────────────────────


class TestComputeTrailingConsecutiveLosses:
    def test_all_wins_returns_zero(self) -> None:
        window = _make_window(
            [Decimal("10"), Decimal("20"), Decimal("5")]
        )
        assert _compute_trailing_consecutive_losses(window) == 0

    def test_all_losses_returns_count(self) -> None:
        window = _make_window(
            [Decimal("-5"), Decimal("-10"), Decimal("-3")]
        )
        assert _compute_trailing_consecutive_losses(window) == 3

    def test_mixed_last_win_breaks_streak(self) -> None:
        window = _make_window(
            [Decimal("-5"), Decimal("-10"), Decimal("15")]
        )
        assert _compute_trailing_consecutive_losses(window) == 0

    def test_mixed_last_losses_only_counts_trailing(self) -> None:
        window = _make_window(
            [Decimal("10"), Decimal("-5"), Decimal("-8"), Decimal("-2")]
        )
        assert _compute_trailing_consecutive_losses(window) == 3

    def test_zero_pnl_counts_as_loss(self) -> None:
        # Zero PnL (break-even) is not a win.
        window = _make_window([Decimal("0"), Decimal("-1")])
        assert _compute_trailing_consecutive_losses(window) == 2

    def test_open_positions_skipped(self) -> None:
        # None records are ignored in the streak calculation.
        window = _make_window(
            [Decimal("-5"), None, None, Decimal("-3")]
        )
        assert _compute_trailing_consecutive_losses(window) == 2

    def test_all_open_returns_zero(self) -> None:
        window = _make_window([None, None, None])
        assert _compute_trailing_consecutive_losses(window) == 0

    def test_empty_window_returns_zero(self) -> None:
        assert _compute_trailing_consecutive_losses(deque()) == 0


# ── _count_completed_trades ────────────────────────────────────────────────────


class TestCountCompletedTrades:
    def test_all_open_returns_zero(self) -> None:
        window = _make_window([None, None, None])
        assert _count_completed_trades(window) == 0

    def test_all_closed_returns_count(self) -> None:
        window = _make_window([Decimal("10"), Decimal("-5"), Decimal("0")])
        assert _count_completed_trades(window) == 3

    def test_mixed(self) -> None:
        window = _make_window([Decimal("10"), None, Decimal("-5"), None])
        assert _count_completed_trades(window) == 2

    def test_empty_returns_zero(self) -> None:
        assert _count_completed_trades(deque()) == 0


# ── _count_winning_trades ──────────────────────────────────────────────────────


class TestCountWinningTrades:
    def test_all_wins(self) -> None:
        window = _make_window([Decimal("10"), Decimal("5"), Decimal("1")])
        assert _count_winning_trades(window) == 3

    def test_all_losses(self) -> None:
        window = _make_window([Decimal("-10"), Decimal("-5")])
        assert _count_winning_trades(window) == 0

    def test_break_even_not_counted(self) -> None:
        window = _make_window([Decimal("0"), Decimal("5")])
        assert _count_winning_trades(window) == 1

    def test_open_positions_excluded(self) -> None:
        window = _make_window([Decimal("10"), None, Decimal("-5")])
        assert _count_winning_trades(window) == 1


# ── _compute_metrics ──────────────────────────────────────────────────────────


class TestComputeMetrics:
    def test_empty_window_returns_zeros(self) -> None:
        metrics = _compute_metrics(deque())
        assert metrics.total_signals == 0
        assert metrics.trades_taken == 0
        assert metrics.win_rate == 0.0
        assert metrics.sharpe_ratio == 0.0
        assert metrics.max_drawdown == 0.0
        assert metrics.total_pnl == Decimal("0")
        assert metrics.avg_pnl_per_trade == Decimal("0")
        assert metrics.consecutive_losses == 0

    def test_only_open_positions(self) -> None:
        window = _make_window([None, None, None])
        metrics = _compute_metrics(window)
        assert metrics.total_signals == 3
        assert metrics.win_rate == 0.0
        assert metrics.total_pnl == Decimal("0")

    def test_mixed_completed_and_open(self) -> None:
        window = _make_window([Decimal("10"), None, Decimal("-5"), Decimal("8")])
        metrics = _compute_metrics(window)
        assert metrics.total_signals == 4
        # trades_taken counts non-HOLD actions; all records in window are 'buy'
        assert metrics.trades_taken == 4
        # 2 wins out of 3 completed
        assert metrics.win_rate == pytest.approx(2 / 3, rel=0.01)
        assert metrics.total_pnl == Decimal("13")
        assert metrics.avg_pnl_per_trade == pytest.approx(Decimal("13") / 3, rel=0.01)

    def test_consecutive_losses_propagated(self) -> None:
        window = _make_window(
            [Decimal("10"), Decimal("-5"), Decimal("-3"), Decimal("-2")]
        )
        metrics = _compute_metrics(window)
        assert metrics.consecutive_losses == 3

    def test_hold_signals_not_counted_as_trades_taken(self) -> None:
        d: deque[_TradeRecord] = deque()
        d.append(_make_record(outcome_pnl=Decimal("5"), action="hold"))
        d.append(_make_record(outcome_pnl=Decimal("10"), action="buy"))
        metrics = _compute_metrics(d)
        # Only the 'buy' counts as a taken trade.
        assert metrics.trades_taken == 1


# ── StrategyManager construction ──────────────────────────────────────────────


class TestStrategyManagerConstruction:
    def test_default_construction(self) -> None:
        manager = StrategyManager()
        assert manager._window_size == 50

    def test_custom_window_size(self) -> None:
        manager = StrategyManager(window_size=100)
        assert manager._window_size == 100

    def test_invalid_window_size_raises(self) -> None:
        with pytest.raises(ValueError, match="window_size must be >= 1"):
            StrategyManager(window_size=0)

    def test_custom_thresholds(self) -> None:
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


# ── StrategyManager.record_strategy_result ────────────────────────────────────


class TestRecordStrategyResult:
    async def test_single_record_appended(self) -> None:
        manager = StrategyManager(window_size=5)
        signal = _make_signal()
        await manager.record_strategy_result(
            agent_id="agent-1",
            strategy_name="rl",
            signal=signal,
            outcome_pnl=Decimal("42"),
        )
        window = manager._windows["agent-1"]["rl"]
        assert len(window) == 1
        assert window[0].outcome_pnl == Decimal("42")

    async def test_window_capped_at_window_size(self) -> None:
        window_size = 5
        manager = StrategyManager(window_size=window_size)
        signal = _make_signal()
        for i in range(window_size + 3):
            await manager.record_strategy_result(
                agent_id="agent-1",
                strategy_name="rl",
                signal=signal,
                outcome_pnl=Decimal(str(i)),
            )
        window = manager._windows["agent-1"]["rl"]
        # deque(maxlen=5) automatically evicts oldest entries
        assert len(window) == window_size

    async def test_open_position_stored_with_none_pnl(self) -> None:
        manager = StrategyManager()
        signal = _make_signal()
        await manager.record_strategy_result(
            agent_id="agent-1",
            strategy_name="regime",
            signal=signal,
            outcome_pnl=None,
        )
        window = manager._windows["agent-1"]["regime"]
        assert window[0].outcome_pnl is None

    async def test_multiple_strategies_tracked_independently(self) -> None:
        manager = StrategyManager()
        signal = _make_signal()
        await manager.record_strategy_result("agent-1", "rl", signal, Decimal("10"))
        await manager.record_strategy_result("agent-1", "ensemble", signal, Decimal("20"))
        assert len(manager._windows["agent-1"]["rl"]) == 1
        assert len(manager._windows["agent-1"]["ensemble"]) == 1

    async def test_persistence_skipped_when_no_session_factory(self) -> None:
        # With no session_factory, _persist_period_summary must be a no-op.
        # We verify this doesn't raise even when the window fills.
        manager = StrategyManager(window_size=3, session_factory=None)
        signal = _make_signal()
        for _ in range(5):  # exceeds window_size → triggers persist path
            await manager.record_strategy_result("a1", "rl", signal, Decimal("1"))
        # No exception = test passes

    async def test_persistence_called_when_window_full(self) -> None:
        mock_factory = MagicMock()
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session.commit = AsyncMock()

        # Patch out the src imports inside _persist_period_summary so they
        # don't require a running database.
        patch_target = (
            "agent.trading.strategy_manager.StrategyManager._persist_period_summary"
        )
        with (
            patch(patch_target, new_callable=AsyncMock) as mock_persist,
        ):
            manager = StrategyManager(window_size=2, session_factory=mock_factory)
            signal = _make_signal()
            # First record — window not yet full.
            await manager.record_strategy_result("a1", "rl", signal, Decimal("1"))
            mock_persist.assert_not_called()
            # Second record — fills the window.
            await manager.record_strategy_result("a1", "rl", signal, Decimal("2"))
            mock_persist.assert_called_once()


# ── StrategyManager.get_performance ───────────────────────────────────────────


class TestGetPerformance:
    async def test_no_data_returns_empty_list(self) -> None:
        manager = StrategyManager()
        result = await manager.get_performance("unknown-agent")
        assert result == []

    async def test_specific_strategy_returned(self) -> None:
        manager = StrategyManager()
        signal = _make_signal()
        await manager.record_strategy_result("a1", "rl", signal, Decimal("10"))
        await manager.record_strategy_result("a1", "rl", signal, Decimal("-5"))
        result = await manager.get_performance("a1", strategy_name="rl", period="weekly")
        assert len(result) == 1
        assert result[0].strategy_name == "rl"
        assert result[0].period == "weekly"

    async def test_all_strategies_returned_when_none_specified(self) -> None:
        manager = StrategyManager()
        signal = _make_signal()
        await manager.record_strategy_result("a1", "rl", signal, Decimal("10"))
        await manager.record_strategy_result("a1", "regime", signal, Decimal("5"))
        result = await manager.get_performance("a1")
        strategy_names = {p.strategy_name for p in result}
        assert "rl" in strategy_names
        assert "regime" in strategy_names

    async def test_unknown_strategy_returns_empty_list(self) -> None:
        manager = StrategyManager()
        signal = _make_signal()
        await manager.record_strategy_result("a1", "rl", signal, Decimal("10"))
        result = await manager.get_performance("a1", strategy_name="nonexistent")
        assert result == []

    async def test_invalid_period_raises(self) -> None:
        manager = StrategyManager()
        with pytest.raises(ValueError, match="Invalid period"):
            await manager.get_performance("a1", period="yearly")

    async def test_win_rate_computed_correctly(self) -> None:
        manager = StrategyManager()
        signal = _make_signal()
        # 2 wins, 1 loss
        for pnl in [Decimal("10"), Decimal("5"), Decimal("-3")]:
            await manager.record_strategy_result("a1", "rl", signal, pnl)
        result = await manager.get_performance("a1", strategy_name="rl")
        assert len(result) == 1
        assert result[0].win_rate == pytest.approx(2 / 3, rel=0.01)


# ── StrategyManager.detect_degradation ────────────────────────────────────────


class TestDetectDegradation:
    async def test_no_data_returns_empty(self) -> None:
        manager = StrategyManager()
        alerts = await manager.detect_degradation("unknown-agent")
        assert alerts == []

    async def test_insufficient_trades_skipped(self) -> None:
        # Below min_trades_for_degradation (default 10), checks are skipped.
        manager = StrategyManager(min_trades_for_degradation=10)
        signal = _make_signal()
        for _ in range(5):  # only 5 completed trades
            await manager.record_strategy_result("a1", "rl", signal, Decimal("-50"))
        alerts = await manager.detect_degradation("a1")
        assert alerts == []

    async def test_win_rate_warning_fires(self) -> None:
        manager = StrategyManager(
            win_rate_warning_threshold=0.40,
            win_rate_critical_threshold=0.30,
            min_trades_for_degradation=5,
        )
        signal = _make_signal()
        # 1 win, 4 losses = 20% win rate → below warning (40%)
        pnls = [Decimal("10")] + [Decimal("-5")] * 4
        for pnl in pnls:
            await manager.record_strategy_result("a1", "rl", signal, pnl)
        alerts = await manager.detect_degradation("a1")
        win_rate_alerts = [a for a in alerts if a.metric == "win_rate"]
        assert len(win_rate_alerts) >= 1
        assert win_rate_alerts[0].severity in ("warning", "critical")

    async def test_consecutive_losses_warning_fires(self) -> None:
        manager = StrategyManager(
            consecutive_losses_warning_threshold=5,
            min_trades_for_degradation=5,
        )
        signal = _make_signal()
        # 1 win followed by 6 losses
        pnls = [Decimal("10")] + [Decimal("-1")] * 6
        for pnl in pnls:
            await manager.record_strategy_result("a1", "rl", signal, pnl)
        alerts = await manager.detect_degradation("a1")
        consec_alerts = [a for a in alerts if a.metric == "consecutive_losses"]
        assert len(consec_alerts) >= 1

    async def test_sharpe_warning_fires_below_threshold(self) -> None:
        manager = StrategyManager(
            sharpe_warning_threshold=0.5,
            min_trades_for_degradation=5,
        )
        signal = _make_signal()
        # All small losses → negative Sharpe
        for _ in range(12):
            await manager.record_strategy_result("a1", "rl", signal, Decimal("-1"))
        alerts = await manager.detect_degradation("a1")
        sharpe_alerts = [a for a in alerts if a.metric == "sharpe"]
        assert len(sharpe_alerts) >= 1
        assert sharpe_alerts[0].current_value < 0.5

    async def test_healthy_strategy_produces_no_alerts(self) -> None:
        manager = StrategyManager(min_trades_for_degradation=5)
        signal = _make_signal()
        # All profitable → high Sharpe, 100% win rate, no drawdown
        for i in range(15):
            await manager.record_strategy_result(
                "a1", "rl", signal, Decimal(str(10 + i))
            )
        alerts = await manager.detect_degradation("a1")
        assert alerts == []

    async def test_consecutive_losses_disable_fires(self) -> None:
        manager = StrategyManager(
            consecutive_losses_disable_threshold=5,
            consecutive_losses_critical_threshold=3,
            consecutive_losses_warning_threshold=2,
            min_trades_for_degradation=5,
        )
        signal = _make_signal()
        # 1 win followed by 6 losses — exceeds disable threshold (5)
        pnls = [Decimal("50")] + [Decimal("-1")] * 8
        for pnl in pnls:
            await manager.record_strategy_result("a1", "rl", signal, pnl)
        alerts = await manager.detect_degradation("a1")
        consec_alerts = [a for a in alerts if a.metric == "consecutive_losses"]
        assert any(a.severity == "disable" for a in consec_alerts)

    async def test_alert_fields_populated_correctly(self) -> None:
        manager = StrategyManager(
            win_rate_warning_threshold=0.40,
            win_rate_critical_threshold=0.30,
            min_trades_for_degradation=5,
        )
        signal = _make_signal()
        pnls = [Decimal("10")] + [Decimal("-5")] * 9  # 10% win rate — below critical (0.30)
        for pnl in pnls:
            await manager.record_strategy_result("a1", "test_strat", signal, pnl)
        alerts = await manager.detect_degradation("a1")
        win_rate_alerts = [a for a in alerts if a.metric == "win_rate"]
        # At 10% win rate the critical threshold (0.30) fires; there should be exactly one alert.
        assert len(win_rate_alerts) == 1
        win_rate_alert = win_rate_alerts[0]
        assert win_rate_alert.strategy_name == "test_strat"
        # Critical threshold fires when win_rate < critical (0.30)
        assert win_rate_alert.threshold_value == 0.30
        assert win_rate_alert.severity == "critical"
        assert 0.0 <= win_rate_alert.current_value <= 1.0
        assert win_rate_alert.recommendation != ""
        assert isinstance(win_rate_alert.detected_at, datetime)


# ── StrategyManager.suggest_adjustments ───────────────────────────────────────


class TestSuggestAdjustments:
    async def test_no_data_returns_empty(self) -> None:
        manager = StrategyManager()
        result = await manager.suggest_adjustments("unknown-agent", "rl")
        assert result == []

    async def test_healthy_strategy_no_suggestions(self) -> None:
        manager = StrategyManager(min_trades_for_degradation=5)
        signal = _make_signal()
        for i in range(15):
            await manager.record_strategy_result(
                "a1", "healthy", signal, Decimal(str(20 + i))
            )
        result = await manager.suggest_adjustments("a1", "healthy")
        assert result == []

    async def test_low_win_rate_suggests_position_size_reduction(self) -> None:
        manager = StrategyManager(
            win_rate_warning_threshold=0.40,
            min_trades_for_degradation=5,
        )
        signal = _make_signal()
        pnls = [Decimal("10")] + [Decimal("-5")] * 9  # 10% win rate
        for pnl in pnls:
            await manager.record_strategy_result("a1", "weak", signal, pnl)
        adjustments = await manager.suggest_adjustments("a1", "weak")
        params = [a.parameter for a in adjustments]
        assert "position_size_pct" in params

    async def test_low_sharpe_suggests_confidence_threshold_increase(self) -> None:
        manager = StrategyManager(
            sharpe_warning_threshold=0.5,
            min_trades_for_degradation=5,
        )
        signal = _make_signal()
        # All losses → negative Sharpe
        for _ in range(12):
            await manager.record_strategy_result("a1", "loser", signal, Decimal("-2"))
        adjustments = await manager.suggest_adjustments("a1", "loser")
        params = [a.parameter for a in adjustments]
        assert "confidence_threshold" in params

    async def test_consecutive_losses_suggests_cooldown(self) -> None:
        manager = StrategyManager(
            consecutive_losses_warning_threshold=5,
            min_trades_for_degradation=5,
        )
        signal = _make_signal()
        pnls = [Decimal("10")] + [Decimal("-1")] * 7
        for pnl in pnls:
            await manager.record_strategy_result("a1", "streak", signal, pnl)
        adjustments = await manager.suggest_adjustments("a1", "streak")
        params = [a.parameter for a in adjustments]
        assert "cooldown_trades_after_loss_streak" in params

    async def test_adjustment_fields_populated(self) -> None:
        manager = StrategyManager(
            win_rate_warning_threshold=0.40,
            min_trades_for_degradation=5,
        )
        signal = _make_signal()
        pnls = [Decimal("10")] + [Decimal("-5")] * 9
        for pnl in pnls:
            await manager.record_strategy_result("a1", "bad_strat", signal, pnl)
        adjustments = await manager.suggest_adjustments("a1", "bad_strat")
        for adj in adjustments:
            assert adj.strategy_name == "bad_strat"
            assert adj.parameter != ""
            assert adj.current_value != ""
            assert adj.suggested_value != ""
            assert adj.rationale != ""
            assert adj.expected_impact != ""
            assert adj.priority in ("low", "medium", "high")

    async def test_suggested_values_are_conservative(self) -> None:
        # Suggested position size must be <= current position size.
        manager = StrategyManager(
            win_rate_warning_threshold=0.40,
            min_trades_for_degradation=5,
        )
        signal = _make_signal()
        pnls = [Decimal("10")] + [Decimal("-5")] * 9
        for pnl in pnls:
            await manager.record_strategy_result("a1", "strat", signal, pnl)
        adjustments = await manager.suggest_adjustments("a1", "strat")
        size_adj = next(
            (a for a in adjustments if a.parameter == "position_size_pct"), None
        )
        if size_adj is not None:
            assert float(size_adj.suggested_value) < float(size_adj.current_value)


# ── StrategyManager.compare_strategies ────────────────────────────────────────


class TestCompareStrategies:
    async def test_no_data_raises_value_error(self) -> None:
        manager = StrategyManager()
        with pytest.raises(ValueError, match="No performance data"):
            await manager.compare_strategies("unknown-agent")

    async def test_invalid_period_raises(self) -> None:
        manager = StrategyManager()
        signal = _make_signal()
        await manager.record_strategy_result("a1", "rl", signal, Decimal("5"))
        with pytest.raises(ValueError, match="Invalid period"):
            await manager.compare_strategies("a1", period="hourly")

    async def test_single_strategy_still_returns_comparison(self) -> None:
        manager = StrategyManager()
        signal = _make_signal()
        for _ in range(5):
            await manager.record_strategy_result("a1", "only", signal, Decimal("10"))
        comparison = await manager.compare_strategies("a1")
        assert comparison.best_strategy == "only"
        assert comparison.worst_strategy == "only"
        assert len(comparison.ranking) == 1

    async def test_ranking_ordered_by_sharpe_descending(self) -> None:
        manager = StrategyManager()
        signal = _make_signal()
        # "good" strategy — consistent gains
        for i in range(15):
            await manager.record_strategy_result(
                "a1", "good", signal, Decimal(str(10 + i * 0.5))
            )
        # "bad" strategy — consistent losses
        for i in range(15):
            await manager.record_strategy_result(
                "a1", "bad", signal, Decimal(str(-(10 + i * 0.5)))
            )
        comparison = await manager.compare_strategies("a1")
        assert comparison.ranking[0] == "good"
        assert comparison.ranking[-1] == "bad"
        assert comparison.best_strategy == "good"
        assert comparison.worst_strategy == "bad"

    async def test_comparison_fields_populated(self) -> None:
        manager = StrategyManager()
        signal = _make_signal()
        for strat in ["rl", "regime", "ensemble"]:
            for pnl in [Decimal("10"), Decimal("-5"), Decimal("8")]:
                await manager.record_strategy_result("a1", strat, signal, pnl)
        comparison = await manager.compare_strategies("a1", period="daily")
        assert comparison.period == "daily"
        assert len(comparison.strategies) == 3
        assert len(comparison.ranking) == 3
        assert comparison.recommendation != ""
        assert isinstance(comparison.generated_at, datetime)

    async def test_strategies_dict_keyed_by_name(self) -> None:
        manager = StrategyManager()
        signal = _make_signal()
        for strat in ["rl", "ensemble"]:
            await manager.record_strategy_result("a1", strat, signal, Decimal("5"))
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

    def test_best_worse_clearly_different(self) -> None:
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


# ── Integration — full workflow ────────────────────────────────────────────────


class TestIntegration:
    """End-to-end scenario: record 15 trades, then get performance, detect, compare."""

    async def test_full_workflow(self) -> None:
        manager = StrategyManager(
            window_size=50,
            min_trades_for_degradation=10,
        )
        signal_buy = _make_signal(action="buy")
        signal_hold = _make_signal(action="hold")

        # Record 15 trades for "ensemble" — good performance
        for i in range(15):
            await manager.record_strategy_result(
                "agent-xyz",
                "ensemble",
                signal_buy,
                Decimal(str(5 + i)),
            )

        # Record 12 trades for "regime" — poor performance
        await manager.record_strategy_result("agent-xyz", "regime", signal_hold, None)
        for _ in range(11):
            await manager.record_strategy_result(
                "agent-xyz", "regime", signal_buy, Decimal("-3")
            )

        # get_performance returns both strategies
        perfs = await manager.get_performance("agent-xyz")
        assert len(perfs) == 2

        # detect_degradation should flag "regime" but not "ensemble"
        alerts = await manager.detect_degradation("agent-xyz")
        flagged = {a.strategy_name for a in alerts}
        assert "regime" in flagged
        assert "ensemble" not in flagged

        # compare returns "ensemble" first (higher Sharpe)
        comparison = await manager.compare_strategies("agent-xyz")
        assert comparison.best_strategy == "ensemble"
        assert comparison.worst_strategy == "regime"
