"""Adapters to convert domain-specific types into unified metric inputs.

Each adapter maps a source type's fields to the normalised
:class:`MetricTradeInput` / :class:`MetricSnapshotInput` used by
:func:`calculate_unified_metrics`.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import TYPE_CHECKING

from src.database.models import BattleSnapshot, Trade
from src.metrics.calculator import MetricSnapshotInput, MetricTradeInput

if TYPE_CHECKING:
    from src.backtesting.sandbox import SandboxSnapshot, SandboxTrade


def from_sandbox_trades(trades: list[SandboxTrade]) -> list[MetricTradeInput]:
    """Convert sandbox trades to unified metric inputs."""
    return [
        MetricTradeInput(
            realized_pnl=t.realized_pnl,
            quote_amount=t.quote_amount,
            symbol=t.symbol,
            timestamp=t.simulated_at,
        )
        for t in trades
    ]


def from_sandbox_snapshots(snapshots: list[SandboxSnapshot]) -> list[MetricSnapshotInput]:
    """Convert sandbox equity snapshots to unified metric inputs."""
    return [
        MetricSnapshotInput(
            timestamp=s.simulated_at,
            equity=s.total_equity,
        )
        for s in snapshots
    ]


def from_db_trades(trades: Sequence[Trade]) -> list[MetricTradeInput]:
    """Convert live trading DB trade rows to unified metric inputs."""
    return [
        MetricTradeInput(
            realized_pnl=t.realized_pnl,
            quote_amount=t.quote_amount,
            symbol=t.symbol,
            timestamp=t.created_at,
        )
        for t in trades
    ]


def from_battle_snapshots(snapshots: Sequence[BattleSnapshot]) -> list[MetricSnapshotInput]:
    """Convert battle snapshot DB rows to unified metric inputs."""
    return [
        MetricSnapshotInput(
            timestamp=s.timestamp,
            equity=Decimal(str(s.equity)) if not isinstance(s.equity, Decimal) else s.equity,
        )
        for s in snapshots
    ]
