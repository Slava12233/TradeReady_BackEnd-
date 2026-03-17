"""Consistency tests: same data through both pipelines produces matching results.

Verifies that the refactored ``results.py`` (backtesting) and ``ranking.py``
(battles) produce consistent metrics by feeding identical trade/snapshot data
through both, via the unified calculator.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock
from uuid import uuid4

from src.backtesting.results import calculate_metrics
from src.backtesting.sandbox import SandboxSnapshot, SandboxTrade
from src.battles.ranking import RankingCalculator
from src.metrics.adapters import (
    from_battle_snapshots,
    from_db_trades,
    from_sandbox_snapshots,
    from_sandbox_trades,
)
from src.metrics.calculator import calculate_unified_metrics

_BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _sandbox_trade(
    pnl: Decimal | None = None,
    quote: Decimal = Decimal("5000"),
    symbol: str = "BTCUSDT",
    minutes_offset: int = 0,
) -> SandboxTrade:
    return SandboxTrade(
        id=f"t-{minutes_offset}",
        symbol=symbol,
        side="sell",
        type="market",
        quantity=Decimal("0.1"),
        price=Decimal("50000"),
        quote_amount=quote,
        fee=Decimal("5"),
        slippage_pct=Decimal("0.01"),
        realized_pnl=pnl,
        simulated_at=_BASE + timedelta(minutes=minutes_offset),
    )


def _sandbox_snapshot(equity: Decimal, hours_offset: int = 0) -> SandboxSnapshot:
    return SandboxSnapshot(
        simulated_at=_BASE + timedelta(hours=hours_offset),
        total_equity=equity,
        available_cash=equity,
        position_value=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        realized_pnl=Decimal("0"),
        positions={},
    )


def _mock_db_trade(
    pnl: Decimal | None = None,
    quote: Decimal = Decimal("5000"),
    symbol: str = "BTCUSDT",
    minutes_offset: int = 0,
) -> MagicMock:
    """Create a mock Trade ORM object with the same data as sandbox trade."""
    trade = MagicMock()
    trade.realized_pnl = pnl
    trade.quote_amount = quote
    trade.symbol = symbol
    trade.created_at = _BASE + timedelta(minutes=minutes_offset)
    return trade


def _mock_battle_snapshot(equity: Decimal, hours_offset: int = 0) -> MagicMock:
    """Create a mock BattleSnapshot ORM object with same data as sandbox snapshot."""
    snap = MagicMock()
    snap.equity = equity
    snap.timestamp = _BASE + timedelta(hours=hours_offset)
    return snap


class TestAdaptersProduceIdenticalInputs:
    """Verify that adapters from different sources produce the same normalised data."""

    def test_trade_adapters_match(self) -> None:
        sandbox_trades = [
            _sandbox_trade(pnl=Decimal("100"), minutes_offset=0),
            _sandbox_trade(pnl=Decimal("-50"), minutes_offset=1),
        ]
        db_trades = [
            _mock_db_trade(pnl=Decimal("100"), minutes_offset=0),
            _mock_db_trade(pnl=Decimal("-50"), minutes_offset=1),
        ]

        sandbox_inputs = from_sandbox_trades(sandbox_trades)
        db_inputs = from_db_trades(db_trades)

        for s, d in zip(sandbox_inputs, db_inputs, strict=False):
            assert s.realized_pnl == d.realized_pnl
            assert s.quote_amount == d.quote_amount
            assert s.symbol == d.symbol
            assert s.timestamp == d.timestamp

    def test_snapshot_adapters_match(self) -> None:
        sandbox_snaps = [
            _sandbox_snapshot(Decimal("10000"), 0),
            _sandbox_snapshot(Decimal("10100"), 1),
        ]
        db_snaps = [
            _mock_battle_snapshot(Decimal("10000"), 0),
            _mock_battle_snapshot(Decimal("10100"), 1),
        ]

        sandbox_inputs = from_sandbox_snapshots(sandbox_snaps)
        db_inputs = from_battle_snapshots(db_snaps)

        for s, d in zip(sandbox_inputs, db_inputs, strict=False):
            assert s.equity == d.equity
            assert s.timestamp == d.timestamp


class TestCrossPipelineConsistency:
    """Verify that backtesting and battle pipelines produce consistent results."""

    def test_same_data_same_core_metrics(self) -> None:
        """Feed identical data through sandbox adapters and DB adapters,
        both via the unified calculator — core metrics must match."""
        sandbox_trades = [
            _sandbox_trade(pnl=Decimal("100"), minutes_offset=0),
            _sandbox_trade(pnl=Decimal("200"), minutes_offset=1),
            _sandbox_trade(pnl=Decimal("-80"), minutes_offset=2),
            _sandbox_trade(pnl=Decimal("-30"), minutes_offset=3),
        ]
        sandbox_snaps = [
            _sandbox_snapshot(Decimal("10000"), 0),
            _sandbox_snapshot(Decimal("10100"), 6),
            _sandbox_snapshot(Decimal("10300"), 12),
            _sandbox_snapshot(Decimal("10190"), 18),
            _sandbox_snapshot(Decimal("10190"), 24),
        ]

        db_trades = [
            _mock_db_trade(pnl=Decimal("100"), minutes_offset=0),
            _mock_db_trade(pnl=Decimal("200"), minutes_offset=1),
            _mock_db_trade(pnl=Decimal("-80"), minutes_offset=2),
            _mock_db_trade(pnl=Decimal("-30"), minutes_offset=3),
        ]
        db_snaps = [
            _mock_battle_snapshot(Decimal("10000"), 0),
            _mock_battle_snapshot(Decimal("10100"), 6),
            _mock_battle_snapshot(Decimal("10300"), 12),
            _mock_battle_snapshot(Decimal("10190"), 18),
            _mock_battle_snapshot(Decimal("10190"), 24),
        ]

        # Through sandbox adapters (backtesting path)
        sandbox_result = calculate_unified_metrics(
            trades=from_sandbox_trades(sandbox_trades),
            snapshots=from_sandbox_snapshots(sandbox_snaps),
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
            snapshot_interval_seconds=86400,
        )

        # Through DB adapters (battle path)
        db_result = calculate_unified_metrics(
            trades=from_db_trades(db_trades),
            snapshots=from_battle_snapshots(db_snaps),
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
            snapshot_interval_seconds=86400,
        )

        # Core metrics must be identical
        assert sandbox_result.win_rate == db_result.win_rate
        assert sandbox_result.profit_factor == db_result.profit_factor
        assert sandbox_result.avg_win == db_result.avg_win
        assert sandbox_result.avg_loss == db_result.avg_loss
        assert sandbox_result.best_trade == db_result.best_trade
        assert sandbox_result.worst_trade == db_result.worst_trade
        assert sandbox_result.total_trades == db_result.total_trades
        assert sandbox_result.max_drawdown_pct == db_result.max_drawdown_pct
        assert sandbox_result.sharpe_ratio == db_result.sharpe_ratio
        assert sandbox_result.sortino_ratio == db_result.sortino_ratio
        assert sandbox_result.roi_pct == db_result.roi_pct
        assert sandbox_result.total_pnl == db_result.total_pnl

    def test_backtest_results_uses_unified_calculator(self) -> None:
        """Verify results.py calculate_metrics produces metrics consistent
        with a direct unified calculator call."""
        sandbox_trades = [
            _sandbox_trade(pnl=Decimal("150"), minutes_offset=0),
            _sandbox_trade(pnl=Decimal("-40"), minutes_offset=1),
        ]
        sandbox_snaps = [
            _sandbox_snapshot(Decimal("10000"), 0),
            _sandbox_snapshot(Decimal("10050"), 6),
            _sandbox_snapshot(Decimal("10110"), 12),
            _sandbox_snapshot(Decimal("10110"), 24),
        ]

        bt_metrics = calculate_metrics(
            trades=sandbox_trades,
            snapshots=sandbox_snaps,
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
        )

        unified = calculate_unified_metrics(
            trades=from_sandbox_trades(sandbox_trades),
            snapshots=from_sandbox_snapshots(sandbox_snaps),
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
            snapshot_interval_seconds=86400,
        )

        # BacktestMetrics should match UnifiedMetrics
        assert bt_metrics.sharpe_ratio == unified.sharpe_ratio
        assert bt_metrics.sortino_ratio == unified.sortino_ratio
        assert bt_metrics.max_drawdown_pct == unified.max_drawdown_pct
        assert bt_metrics.win_rate == unified.win_rate
        assert bt_metrics.profit_factor == unified.profit_factor
        assert bt_metrics.avg_win == unified.avg_win
        assert bt_metrics.avg_loss == unified.avg_loss
        assert bt_metrics.best_trade == unified.best_trade
        assert bt_metrics.worst_trade == unified.worst_trade

    def test_ranking_calculator_uses_unified_calculator(self) -> None:
        """Verify ranking.py compute_participant_metrics produces metrics
        consistent with a direct unified calculator call."""
        db_trades = [
            _mock_db_trade(pnl=Decimal("150"), minutes_offset=0),
            _mock_db_trade(pnl=Decimal("-40"), minutes_offset=1),
        ]
        db_snaps = [
            _mock_battle_snapshot(Decimal("10000"), 0),
            _mock_battle_snapshot(Decimal("10050"), 6),
            _mock_battle_snapshot(Decimal("10110"), 12),
            _mock_battle_snapshot(Decimal("10110"), 24),
        ]

        calc = RankingCalculator()
        agent_id = uuid4()
        pm = calc.compute_participant_metrics(
            agent_id=agent_id,
            start_balance=Decimal("10000"),
            final_equity=Decimal("10110"),
            snapshots=db_snaps,
            trades=db_trades,
        )

        # Direct unified calculation (same interval as battles: 5s)
        unified = calculate_unified_metrics(
            trades=from_db_trades(db_trades),
            snapshots=from_battle_snapshots(db_snaps),
            starting_balance=Decimal("10000"),
            duration_days=Decimal("1"),
            snapshot_interval_seconds=5,
        )

        assert pm.win_rate == unified.win_rate
        assert pm.max_drawdown == unified.max_drawdown_pct
        assert pm.total_trades == unified.total_trades
