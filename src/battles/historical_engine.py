"""Historical battle engine — agents compete on past market data.

Uses backtesting infrastructure (TimeSimulator, DataReplayer, BacktestSandbox)
to run deterministic, reproducible battles on historical data.  All agents
share the same clock and price feed but trade in isolated sandboxes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.backtesting.data_replayer import DataReplayer
from src.backtesting.sandbox import BacktestSandbox, OrderResult, PortfolioSummary
from src.backtesting.time_simulator import TimeSimulator
from src.metrics.adapters import from_sandbox_snapshots, from_sandbox_trades
from src.metrics.calculator import calculate_unified_metrics

logger = structlog.get_logger(__name__)

# ── Module-level engine tracking ─────────────────────────────────────────────

_active_engines: dict[str, HistoricalBattleEngine] = {}


def get_engine(battle_id: str) -> HistoricalBattleEngine | None:
    """Retrieve an active historical battle engine by battle ID."""
    return _active_engines.get(battle_id)


def register_engine(battle_id: str, engine: HistoricalBattleEngine) -> None:
    """Register a historical battle engine as active."""
    _active_engines[battle_id] = engine


def remove_engine(battle_id: str) -> None:
    """Remove a historical battle engine from active tracking."""
    _active_engines.pop(battle_id, None)


# ── Data containers ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class HistoricalStepResult:
    """Result of advancing one step for all agents."""

    virtual_time: datetime
    step: int
    total_steps: int
    progress_pct: Decimal
    is_complete: bool
    prices: dict[str, Decimal]
    agent_states: dict[str, AgentStepState]


@dataclass(frozen=True, slots=True)
class AgentStepState:
    """Per-agent state after a step."""

    agent_id: str
    equity: Decimal
    pnl: Decimal
    trade_count: int
    orders_filled: list[OrderResult]


# ── Engine ───────────────────────────────────────────────────────────────────


class HistoricalBattleEngine:
    """Orchestrates historical battles using backtesting infrastructure.

    All agents share one virtual clock and one price feed.  Each agent
    trades in its own isolated BacktestSandbox.

    Args:
        battle_id:             UUID string of the battle.
        config:                Backtest config dict with start_time, end_time,
                               candle_interval, pairs.
        participant_agent_ids: List of agent UUIDs participating.
        starting_balance:      Starting balance for each agent's sandbox.
        ranking_metric:        Metric used to rank at completion.
    """

    def __init__(
        self,
        battle_id: str,
        config: dict[str, Any],
        participant_agent_ids: list[UUID],
        starting_balance: Decimal = Decimal("10000"),
        ranking_metric: str = "roi_pct",
    ) -> None:
        self._battle_id = battle_id
        self._config = config
        self._participant_ids = participant_agent_ids
        self._starting_balance = starting_balance
        self._ranking_metric = ranking_metric

        self._simulator: TimeSimulator | None = None
        self._replayer: DataReplayer | None = None
        self._sandboxes: dict[UUID, BacktestSandbox] = {}
        self._current_prices: dict[str, Decimal] = {}
        self._agent_account_ids: dict[UUID, UUID] = {}
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        """Whether the engine has been initialized."""
        return self._initialized

    @property
    def current_prices(self) -> dict[str, Decimal]:
        """Current prices at the virtual time."""
        return dict(self._current_prices)

    @property
    def virtual_time(self) -> datetime | None:
        """Current virtual clock position."""
        return self._simulator.current_time if self._simulator else None

    async def initialize(self, db: AsyncSession) -> None:
        """Initialize the engine: preload data, create sandboxes.

        Args:
            db: Active database session for data preloading.
        """
        from sqlalchemy import select  # noqa: PLC0415

        from src.database.models import Agent  # noqa: PLC0415

        start_time = datetime.fromisoformat(str(self._config["start_time"]))
        end_time = datetime.fromisoformat(str(self._config["end_time"]))
        candle_interval = int(self._config.get("candle_interval", 60))
        pairs = self._config.get("pairs")

        # Shared clock
        self._simulator = TimeSimulator(
            start_time=start_time,
            end_time=end_time,
            interval_seconds=candle_interval,
        )

        # Shared data feed
        self._replayer = DataReplayer(db, pairs, step_interval=candle_interval)
        data_points = await self._replayer.preload_range(start_time, end_time)
        if data_points == 0:
            msg = "No historical data found for the requested period."
            raise ValueError(msg)

        # Load initial prices
        self._current_prices = await self._replayer.load_prices(start_time)

        # Create per-agent sandboxes
        for agent_id in self._participant_ids:
            # Load agent record for risk profile and account_id
            risk_limits: dict[str, Any] | None = None
            stmt = select(Agent).where(Agent.id == agent_id)
            result = await db.execute(stmt)
            agent = result.scalars().first()
            if agent:
                self._agent_account_ids[agent_id] = agent.account_id
                if agent.risk_profile:
                    risk_limits = agent.risk_profile

            sandbox = BacktestSandbox(
                session_id=f"{self._battle_id}_{agent_id}",
                starting_balance=self._starting_balance,
                risk_limits=risk_limits,
            )
            # Capture initial snapshot
            sandbox.capture_snapshot(self._current_prices, start_time)
            self._sandboxes[agent_id] = sandbox

        self._initialized = True
        logger.info(
            "historical_battle.initialized",
            battle_id=self._battle_id,
            agents=len(self._participant_ids),
            data_points=data_points,
            total_steps=self._simulator.total_steps,
        )

    async def step(self) -> HistoricalStepResult:
        """Advance one step for all agents simultaneously.

        Returns:
            HistoricalStepResult with per-agent states.
        """
        self._ensure_initialized()
        assert self._simulator is not None  # noqa: S101
        assert self._replayer is not None  # noqa: S101

        if self._simulator.is_complete:
            msg = "Battle has already completed all steps."
            raise ValueError(msg)

        # Advance shared clock
        virtual_time = self._simulator.step()

        # Load shared prices
        self._current_prices = await self._replayer.load_prices(virtual_time)

        # Process all sandboxes
        agent_states: dict[str, AgentStepState] = {}
        step_num = self._simulator.current_step

        for agent_id, sandbox in self._sandboxes.items():
            # Check pending orders
            filled = sandbox.check_pending_orders(self._current_prices, virtual_time)

            # Snapshot periodically or when orders filled
            if filled or step_num % 60 == 0 or self._simulator.is_complete:
                sandbox.capture_snapshot(self._current_prices, virtual_time)

            portfolio = sandbox.get_portfolio(self._current_prices)
            pnl = portfolio.total_equity - self._starting_balance

            agent_states[str(agent_id)] = AgentStepState(
                agent_id=str(agent_id),
                equity=portfolio.total_equity,
                pnl=pnl,
                trade_count=sandbox.total_trades,
                orders_filled=filled,
            )

        return HistoricalStepResult(
            virtual_time=virtual_time,
            step=self._simulator.current_step,
            total_steps=self._simulator.total_steps,
            progress_pct=self._simulator.progress_pct,
            is_complete=self._simulator.is_complete,
            prices=dict(self._current_prices),
            agent_states=agent_states,
        )

    async def step_batch(self, n: int) -> HistoricalStepResult:
        """Advance N steps for all agents.

        Args:
            n: Number of steps to advance.

        Returns:
            HistoricalStepResult after the final step.
        """
        self._ensure_initialized()
        assert self._simulator is not None  # noqa: S101

        result: HistoricalStepResult | None = None
        for _ in range(n):
            if self._simulator.is_complete:
                break
            result = await self.step()

        if result is None:
            # Already complete
            result = self._build_current_result()

        return result

    def place_order(
        self,
        agent_id: UUID,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal | None = None,
    ) -> OrderResult:
        """Place an order in an agent's sandbox.

        Args:
            agent_id:   The agent placing the order.
            symbol:     Trading pair.
            side:       "buy" or "sell".
            order_type: "market", "limit", "stop_loss", "take_profit".
            quantity:   Base-asset quantity.
            price:      Target price for non-market orders.

        Returns:
            OrderResult with fill details or pending status.
        """
        self._ensure_initialized()
        assert self._simulator is not None  # noqa: S101

        sandbox = self._sandboxes.get(agent_id)
        if sandbox is None:
            msg = f"Agent {agent_id} is not a participant in this battle."
            raise ValueError(msg)

        return sandbox.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            current_prices=self._current_prices,
            virtual_time=self._simulator.current_time,
        )

    async def complete(self, db: AsyncSession) -> list[dict[str, Any]]:
        """Complete the battle: close positions, compute rankings, persist results.

        Args:
            db: Active database session for persistence.

        Returns:
            Ranked list of participant results.
        """
        from datetime import UTC  # noqa: PLC0415

        from src.database.models import (  # noqa: PLC0415
            BacktestSession,
            BacktestSnapshot,
            BacktestTrade,
            BattleSnapshot,
        )

        self._ensure_initialized()
        assert self._simulator is not None  # noqa: S101

        now = datetime.now(tz=UTC)
        start_time = datetime.fromisoformat(str(self._config["start_time"]))
        end_time = datetime.fromisoformat(str(self._config["end_time"]))
        duration_days = Decimal(str((end_time - start_time).total_seconds() / 86400))

        all_results: list[dict[str, Any]] = []

        for agent_id, sandbox in self._sandboxes.items():
            # Close all open positions
            sandbox.close_all_positions(self._current_prices, self._simulator.current_time)
            sandbox.capture_snapshot(self._current_prices, self._simulator.current_time)

            portfolio = sandbox.get_portfolio(self._current_prices)

            # Compute metrics via unified calculator
            metric_trades = from_sandbox_trades(sandbox.trades)
            metric_snapshots = from_sandbox_snapshots(sandbox.snapshots)
            um = calculate_unified_metrics(
                trades=metric_trades,
                snapshots=metric_snapshots,
                starting_balance=self._starting_balance,
                duration_days=duration_days,
                snapshot_interval_seconds=int(self._config.get("candle_interval", 60)),
            )

            total_pnl = portfolio.total_equity - self._starting_balance
            roi_pct = (
                (total_pnl / self._starting_balance * Decimal("100")).quantize(Decimal("0.01"))
                if self._starting_balance > 0
                else Decimal("0")
            )

            # Serialize metrics for JSONB storage
            metrics_dict: dict[str, Any] | None = None
            if um:
                metrics_dict = {
                    "roi_pct": str(um.roi_pct),
                    "total_pnl": str(um.total_pnl),
                    "sharpe_ratio": str(um.sharpe_ratio) if um.sharpe_ratio is not None else None,
                    "sortino_ratio": str(um.sortino_ratio) if um.sortino_ratio is not None else None,
                    "max_drawdown_pct": str(um.max_drawdown_pct),
                    "max_drawdown_duration_days": str(um.max_drawdown_duration_days),
                    "win_rate": str(um.win_rate),
                    "profit_factor": str(um.profit_factor) if um.profit_factor is not None else None,
                    "total_trades": um.total_trades,
                    "trades_per_day": str(um.trades_per_day),
                    "avg_win": str(um.avg_win),
                    "avg_loss": str(um.avg_loss),
                    "best_trade": str(um.best_trade),
                    "worst_trade": str(um.worst_trade),
                }

            # Create BacktestSession for this agent
            session = BacktestSession(
                account_id=self._agent_account_ids.get(agent_id),
                agent_id=agent_id,
                strategy_label=f"battle_{self._battle_id}",
                status="completed",
                candle_interval=int(self._config.get("candle_interval", 60)),
                start_time=start_time,
                end_time=end_time,
                starting_balance=self._starting_balance,
                pairs=self._config.get("pairs"),
                total_steps=self._simulator.total_steps,
                current_step=self._simulator.current_step,
                progress_pct=Decimal("100.00"),
                virtual_clock=self._simulator.current_time,
                started_at=now,
                completed_at=now,
                final_equity=portfolio.total_equity,
                total_pnl=total_pnl,
                roi_pct=roi_pct,
                total_trades=sandbox.total_trades,
                total_fees=sandbox.total_fees,
                metrics=metrics_dict,
            )
            db.add(session)
            await db.flush()

            # Persist trades
            for t in sandbox.trades:
                db.add(
                    BacktestTrade(
                        session_id=session.id,
                        symbol=t.symbol,
                        side=t.side,
                        type=t.type,
                        quantity=t.quantity,
                        price=t.price,
                        quote_amount=t.quote_amount,
                        fee=t.fee,
                        slippage_pct=t.slippage_pct,
                        realized_pnl=t.realized_pnl,
                        simulated_at=t.simulated_at,
                    )
                )

            # Persist snapshots
            for s in sandbox.snapshots:
                db.add(
                    BacktestSnapshot(
                        session_id=session.id,
                        simulated_at=s.simulated_at,
                        total_equity=s.total_equity,
                        available_cash=s.available_cash,
                        position_value=s.position_value,
                        unrealized_pnl=s.unrealized_pnl,
                        realized_pnl=s.realized_pnl,
                        positions=s.positions,
                    )
                )

            # Create battle snapshots from sandbox snapshots
            for s in sandbox.snapshots:
                db.add(
                    BattleSnapshot(
                        battle_id=UUID(self._battle_id),
                        agent_id=agent_id,
                        timestamp=s.simulated_at,
                        equity=s.total_equity,
                        unrealized_pnl=s.unrealized_pnl,
                        realized_pnl=s.realized_pnl,
                        trade_count=sandbox.total_trades,
                        open_positions=len([p for p in sandbox.get_positions() if p.quantity > 0]),
                    )
                )

            all_results.append(
                {
                    "agent_id": agent_id,
                    "session_id": session.id,
                    "final_equity": portfolio.total_equity,
                    "total_pnl": total_pnl,
                    "roi_pct": roi_pct,
                    "total_trades": sandbox.total_trades,
                    "sharpe_ratio": um.sharpe_ratio,
                    "win_rate": um.win_rate,
                    "max_drawdown": um.max_drawdown_pct,
                }
            )

        await db.flush()

        # Rank results
        metric_key = self._ranking_metric if all_results and self._ranking_metric in all_results[0] else "roi_pct"
        ranked = sorted(
            all_results,
            key=lambda r: r.get(metric_key, Decimal("0")),
            reverse=True,
        )

        logger.info(
            "historical_battle.completed",
            battle_id=self._battle_id,
            agents=len(all_results),
        )

        return ranked

    def get_agent_portfolio(self, agent_id: UUID) -> PortfolioSummary:
        """Get portfolio summary for a specific agent."""
        self._ensure_initialized()
        sandbox = self._sandboxes.get(agent_id)
        if sandbox is None:
            msg = f"Agent {agent_id} is not a participant in this battle."
            raise ValueError(msg)
        return sandbox.get_portfolio(self._current_prices)

    # ── Internal helpers ─────────────────────────────────────────────────

    def _ensure_initialized(self) -> None:
        """Raise if engine has not been initialized."""
        if not self._initialized:
            msg = "HistoricalBattleEngine has not been initialized. Call initialize() first."
            raise RuntimeError(msg)

    def _build_current_result(self) -> HistoricalStepResult:
        """Build a result from current state (used when already complete)."""
        assert self._simulator is not None  # noqa: S101

        agent_states: dict[str, AgentStepState] = {}
        for agent_id, sandbox in self._sandboxes.items():
            portfolio = sandbox.get_portfolio(self._current_prices)
            pnl = portfolio.total_equity - self._starting_balance
            agent_states[str(agent_id)] = AgentStepState(
                agent_id=str(agent_id),
                equity=portfolio.total_equity,
                pnl=pnl,
                trade_count=sandbox.total_trades,
                orders_filled=[],
            )

        return HistoricalStepResult(
            virtual_time=self._simulator.current_time,
            step=self._simulator.current_step,
            total_steps=self._simulator.total_steps,
            progress_pct=self._simulator.progress_pct,
            is_complete=self._simulator.is_complete,
            prices=dict(self._current_prices),
            agent_states=agent_states,
        )
