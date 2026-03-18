"""Backtest engine orchestrator.

``BacktestEngine`` manages the full lifecycle of backtest sessions: create,
start, step, complete, cancel.  Active sessions are held in memory with
their ``TimeSimulator`` and ``BacktestSandbox``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
import time
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from src.backtesting.data_replayer import Candle, DataReplayer
from src.backtesting.results import (
    BacktestMetrics,
    PairStats,
    calculate_metrics,
    calculate_per_pair_stats,
)
from src.backtesting.sandbox import BacktestSandbox, OrderResult, PortfolioSummary
from src.backtesting.time_simulator import TimeSimulator
from src.database.models import BacktestSession as BacktestSessionModel
from src.utils.exceptions import (
    BacktestInvalidStateError,
    BacktestNoDataError,
    BacktestNotFoundError,
)

logger = structlog.get_logger(__name__)

_QUANT8 = Decimal("0.00000001")
_QUANT2 = Decimal("0.01")


# ── Data containers ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    """Configuration for creating a new backtest session."""

    start_time: datetime
    end_time: datetime
    starting_balance: Decimal
    candle_interval: int = 60
    pairs: list[str] | None = None
    strategy_label: str = "default"
    agent_id: UUID | None = None
    exchange: str = "binance"


@dataclass(frozen=True, slots=True)
class StepResult:
    """Result of advancing one step."""

    virtual_time: datetime
    step: int
    total_steps: int
    progress_pct: Decimal
    prices: dict[str, Decimal]
    orders_filled: list[OrderResult]
    portfolio: PortfolioSummary
    is_complete: bool
    remaining_steps: int


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Final result of a completed or cancelled backtest."""

    session_id: str
    status: str
    config: dict[str, Any]
    final_equity: Decimal
    total_pnl: Decimal
    roi_pct: Decimal
    total_trades: int
    total_fees: Decimal
    metrics: BacktestMetrics | None
    per_pair: list[PairStats]
    duration_real_sec: Decimal


@dataclass(frozen=True, slots=True)
class PriceAtTime:
    """A price at the current virtual time."""

    symbol: str
    price: Decimal
    virtual_time: datetime


# ── Active session holder ────────────────────────────────────────────────────


@dataclass
class _ActiveSession:
    """Holds the in-memory state for a running backtest."""

    session_id: str
    account_id: UUID
    agent_id: UUID | None
    config: BacktestConfig
    simulator: TimeSimulator
    sandbox: BacktestSandbox
    replayer: DataReplayer
    current_prices: dict[str, Decimal]
    started_wall: float  # time.monotonic() when started


# ── Engine ───────────────────────────────────────────────────────────────────


class BacktestEngine:
    """Orchestrator for backtest session lifecycle.

    Manages active sessions in-memory (dict of session_id → state).
    Each session has its own TimeSimulator, BacktestSandbox, and DataReplayer.

    Args:
        session_factory: Callable returning async DB sessions.
    """

    def __init__(self, session_factory: Any) -> None:  # noqa: ANN401
        self._session_factory = session_factory
        self._active: dict[str, _ActiveSession] = {}

    async def create_session(self, account_id: UUID, config: BacktestConfig, db: AsyncSession) -> BacktestSessionModel:
        """Create a new backtest session in the database.

        Validates the time range has data and the balance is reasonable.

        Args:
            account_id: Owner account UUID.
            config:     Backtest configuration.
            db:         Active database session.

        Returns:
            The created :class:`BacktestSessionModel`.
        """
        # Validate data availability
        replayer = DataReplayer(db, config.pairs, step_interval=config.candle_interval, exchange=config.exchange)
        data_range = await replayer.get_data_range()

        if data_range is None:
            raise BacktestNoDataError("No historical data available in the database.")

        if config.start_time < data_range.earliest:
            raise BacktestNoDataError(
                f"Start time {config.start_time.isoformat()} is before earliest data "
                f"({data_range.earliest.isoformat()}).",
                details={"earliest": data_range.earliest.isoformat()},
            )

        if config.starting_balance <= Decimal("0"):
            raise BacktestNoDataError(
                "Starting balance must be positive.",
                details={"starting_balance": str(config.starting_balance)},
            )

        # Calculate total steps
        total_seconds = (config.end_time - config.start_time).total_seconds()
        total_steps = int(total_seconds // config.candle_interval)

        session = BacktestSessionModel(
            account_id=account_id,
            agent_id=config.agent_id,
            strategy_label=config.strategy_label,
            status="created",
            candle_interval=config.candle_interval,
            start_time=config.start_time,
            end_time=config.end_time,
            starting_balance=config.starting_balance,
            pairs=config.pairs,
            total_steps=total_steps,
        )
        db.add(session)
        await db.flush()

        logger.info(
            "backtest.session_created",
            session_id=str(session.id),
            account_id=str(account_id),
            strategy=config.strategy_label,
            total_steps=total_steps,
        )
        return session

    async def start(self, session_id: str, db: AsyncSession) -> None:
        """Initialize and start a created backtest session.

        Loads the session from DB, creates the TimeSimulator and Sandbox,
        and loads initial prices.

        Args:
            session_id: UUID string of the session.
            db:         Active database session.
        """
        session = await self._load_session(session_id, db)

        if session.status != "created":
            raise BacktestInvalidStateError(
                f"Cannot start backtest in '{session.status}' state.",
                current_status=session.status,
                required_status="created",
            )

        config = BacktestConfig(
            start_time=session.start_time,
            end_time=session.end_time,
            starting_balance=session.starting_balance,
            candle_interval=session.candle_interval,
            pairs=session.pairs,
            strategy_label=session.strategy_label,
            exchange=getattr(session, "exchange", "binance") or "binance",
        )

        simulator = TimeSimulator(
            start_time=config.start_time,
            end_time=config.end_time,
            interval_seconds=config.candle_interval,
        )

        # Load agent risk profile if agent_id is set
        risk_limits: dict[str, Any] | None = None
        if session.agent_id is not None:
            risk_limits = await self._load_agent_risk_profile(session.agent_id, db)

        sandbox = BacktestSandbox(
            session_id=session_id,
            starting_balance=config.starting_balance,
            risk_limits=risk_limits,
        )

        replayer = DataReplayer(db, config.pairs, step_interval=config.candle_interval, exchange=config.exchange)

        # Bulk-preload all price data for the entire backtest period into
        # memory.  This replaces ~525K individual DB queries with one query.
        data_points = await replayer.preload_range(config.start_time, config.end_time)
        if data_points == 0:
            raise BacktestNoDataError(
                "No historical data found for the requested period.",
            )

        initial_prices = await replayer.load_prices(config.start_time)

        # Capture initial snapshot
        sandbox.capture_snapshot(initial_prices, config.start_time)

        active = _ActiveSession(
            session_id=session_id,
            account_id=session.account_id,
            agent_id=session.agent_id,
            config=config,
            simulator=simulator,
            sandbox=sandbox,
            replayer=replayer,
            current_prices=initial_prices,
            started_wall=time.monotonic(),
        )
        self._active[session_id] = active

        # Update DB
        session.status = "running"
        session.started_at = datetime.now(tz=UTC)
        session.virtual_clock = config.start_time
        await db.flush()

        logger.info("backtest.started", session_id=session_id)

    async def step(self, session_id: str, db: AsyncSession) -> StepResult:
        """Advance one candle step.

        Args:
            session_id: UUID string.
            db:         Active database session.

        Returns:
            :class:`StepResult` with current state after the step.
        """
        active = self._get_active(session_id)

        if active.simulator.is_complete:
            raise BacktestInvalidStateError(
                "Backtest has already completed all steps.",
                current_status="complete",
            )

        # Advance virtual clock
        virtual_time = active.simulator.step()

        # Load prices at new time (served from in-memory cache after preload)
        active.current_prices = await active.replayer.load_prices(virtual_time)

        # Check pending orders
        filled = active.sandbox.check_pending_orders(active.current_prices, virtual_time)

        # Capture snapshot periodically (every 60 steps ≈ 1 hour at 1m candles)
        # to avoid storing 500K+ snapshots in memory.  Always snapshot when
        # orders were filled for accurate equity tracking.
        step_num = active.simulator.current_step
        if filled or step_num % 60 == 0 or active.simulator.is_complete:
            active.sandbox.capture_snapshot(active.current_prices, virtual_time)

        # Get portfolio
        portfolio = active.sandbox.get_portfolio(active.current_prices)

        # Update DB progress periodically (every 500 steps) to reduce writes.
        # Always write on the last step.
        if step_num % 500 == 0 or active.simulator.is_complete:
            session = await self._load_session(session_id, db)
            session.virtual_clock = virtual_time
            session.current_step = step_num
            session.progress_pct = active.simulator.progress_pct
            await db.flush()

        # Capture values before potential cleanup by complete()
        is_complete = active.simulator.is_complete
        current_step = active.simulator.current_step
        total_steps = active.simulator.total_steps
        progress_pct = active.simulator.progress_pct
        remaining_steps = active.simulator.remaining_steps

        # Auto-complete when all steps are done — persist results immediately
        # so they survive server restarts.
        if is_complete:
            await self.complete(session_id, db)

        return StepResult(
            virtual_time=virtual_time,
            step=current_step,
            total_steps=total_steps,
            progress_pct=progress_pct,
            prices=active.current_prices,
            orders_filled=filled,
            portfolio=portfolio,
            is_complete=is_complete,
            remaining_steps=remaining_steps,
        )

    async def step_batch(self, session_id: str, steps: int, db: AsyncSession) -> StepResult:
        """Advance multiple candle steps.

        Args:
            session_id: UUID string.
            steps:      Number of steps to advance.
            db:         Active database session.

        Returns:
            :class:`StepResult` with state after the final step.
        """
        result: StepResult | None = None
        for _ in range(steps):
            # After auto-complete in step(), session is removed from _active
            if session_id not in self._active:
                break
            active = self._get_active(session_id)
            if active.simulator.is_complete:
                break
            result = await self.step(session_id, db)

        if result is None:
            # No steps taken — already complete
            active = self._get_active(session_id)
            portfolio = active.sandbox.get_portfolio(active.current_prices)
            result = StepResult(
                virtual_time=active.simulator.current_time,
                step=active.simulator.current_step,
                total_steps=active.simulator.total_steps,
                progress_pct=active.simulator.progress_pct,
                prices=active.current_prices,
                orders_filled=[],
                portfolio=portfolio,
                is_complete=True,
                remaining_steps=0,
            )
        return result

    async def get_price(self, session_id: str, symbol: str) -> PriceAtTime:
        """Get the current price for a symbol in the backtest.

        Args:
            session_id: UUID string.
            symbol:     Trading pair.

        Returns:
            :class:`PriceAtTime`.
        """
        active = self._get_active(session_id)
        price = active.current_prices.get(symbol, Decimal("0"))
        return PriceAtTime(
            symbol=symbol,
            price=price,
            virtual_time=active.simulator.current_time,
        )

    async def get_candles(self, session_id: str, symbol: str, interval: int = 60, limit: int = 100) -> list[Candle]:
        """Get historical candles up to the current virtual time."""
        active = self._get_active(session_id)
        return await active.replayer.load_candles(symbol, active.simulator.current_time, interval, limit)

    async def execute_order(
        self,
        session_id: str,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Decimal | None,
    ) -> OrderResult:
        """Place an order in the backtest sandbox."""
        active = self._get_active(session_id)
        return active.sandbox.place_order(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            current_prices=active.current_prices,
            virtual_time=active.simulator.current_time,
        )

    async def cancel_order(self, session_id: str, order_id: str) -> bool:
        """Cancel a pending order in the backtest sandbox."""
        active = self._get_active(session_id)
        return active.sandbox.cancel_order(order_id)

    async def get_balance(self, session_id: str) -> list[Any]:
        """Get sandbox balances."""
        return self._get_active(session_id).sandbox.get_balance()

    async def get_positions(self, session_id: str) -> list[Any]:
        """Get sandbox positions."""
        return self._get_active(session_id).sandbox.get_positions()

    async def get_portfolio(self, session_id: str) -> PortfolioSummary:
        """Get sandbox portfolio summary."""
        active = self._get_active(session_id)
        return active.sandbox.get_portfolio(active.current_prices)

    async def complete(self, session_id: str, db: AsyncSession) -> BacktestResult:
        """Complete a backtest: close positions, compute metrics, persist results.

        Args:
            session_id: UUID string.
            db:         Active database session.

        Returns:
            :class:`BacktestResult` with final metrics.
        """
        active = self._get_active(session_id)

        # Close all open positions
        active.sandbox.close_all_positions(active.current_prices, active.simulator.current_time)

        # Final snapshot
        active.sandbox.capture_snapshot(active.current_prices, active.simulator.current_time)

        # Compute metrics
        portfolio = active.sandbox.get_portfolio(active.current_prices)
        duration_days = Decimal(str((active.config.end_time - active.config.start_time).total_seconds() / 86400))
        metrics = calculate_metrics(
            active.sandbox.trades,
            active.sandbox.snapshots,
            active.config.starting_balance,
            duration_days,
        )
        _per_pair = calculate_per_pair_stats(active.sandbox.trades)

        total_pnl = portfolio.total_equity - active.config.starting_balance
        roi_pct = (
            (total_pnl / active.config.starting_balance * Decimal("100")).quantize(_QUANT2)
            if active.config.starting_balance > 0
            else Decimal("0")
        )

        wall_duration = Decimal(str(time.monotonic() - active.started_wall)).quantize(_QUANT2)

        # Persist to DB
        result = await self._persist_results(
            session_id, db, active, portfolio, metrics, total_pnl, roi_pct, wall_duration
        )

        # Remove from active
        self._active.pop(session_id, None)
        return result

    async def cancel(self, session_id: str, db: AsyncSession) -> BacktestResult:
        """Cancel a running backtest and save partial results."""
        active = self._get_active(session_id)

        # Final snapshot at current position
        active.sandbox.capture_snapshot(active.current_prices, active.simulator.current_time)

        portfolio = active.sandbox.get_portfolio(active.current_prices)
        total_pnl = portfolio.total_equity - active.config.starting_balance
        roi_pct = (
            (total_pnl / active.config.starting_balance * Decimal("100")).quantize(_QUANT2)
            if active.config.starting_balance > 0
            else Decimal("0")
        )

        wall_duration = Decimal(str(time.monotonic() - active.started_wall)).quantize(_QUANT2)

        result = await self._persist_results(
            session_id,
            db,
            active,
            portfolio,
            None,
            total_pnl,
            roi_pct,
            wall_duration,
            status="cancelled",
        )

        self._active.pop(session_id, None)
        return result

    def is_active(self, session_id: str) -> bool:
        """Check if a session is currently active in memory."""
        return session_id in self._active

    # ── Internal helpers ─────────────────────────────────────────────────

    def _get_active(self, session_id: str) -> _ActiveSession:
        """Retrieve an active session or raise."""
        active = self._active.get(session_id)
        if active is None:
            raise BacktestNotFoundError(
                f"Backtest session '{session_id}' is not active.",
            )
        return active

    async def _load_agent_risk_profile(self, agent_id: UUID, db: AsyncSession) -> dict[str, Any] | None:
        """Load risk profile from the Agent row. Returns None if agent not found or profile empty."""
        from sqlalchemy import select

        from src.database.models import Agent  # noqa: PLC0415

        stmt = select(Agent).where(Agent.id == agent_id)
        result = await db.execute(stmt)
        agent = result.scalars().first()
        if agent is None:
            logger.warning("backtest.agent_not_found", agent_id=str(agent_id))
            return None
        profile = agent.risk_profile
        if not profile:
            return None
        return profile

    async def _load_session(self, session_id: str, db: AsyncSession) -> BacktestSessionModel:
        """Load session from DB."""
        from sqlalchemy import select

        stmt = select(BacktestSessionModel).where(BacktestSessionModel.id == session_id)
        result = await db.execute(stmt)
        session = result.scalars().first()
        if session is None:
            raise BacktestNotFoundError(session_id=UUID(session_id))
        return session

    async def _persist_results(
        self,
        session_id: str,
        db: AsyncSession,
        active: _ActiveSession,
        portfolio: PortfolioSummary | None,
        metrics: BacktestMetrics | None,
        total_pnl: Decimal,
        roi_pct: Decimal,
        wall_duration: Decimal,
        status: str = "completed",
    ) -> BacktestResult:
        """Save backtest results to DB and return the result object."""
        from src.database.models import BacktestSnapshot, BacktestTrade

        session = await self._load_session(session_id, db)
        now = datetime.now(tz=UTC)

        session.status = status
        session.completed_at = now
        session.duration_real_sec = wall_duration
        session.final_equity = portfolio.total_equity if portfolio else active.config.starting_balance
        session.total_pnl = total_pnl
        session.roi_pct = roi_pct
        session.total_trades = active.sandbox.total_trades
        session.total_fees = active.sandbox.total_fees
        session.metrics = metrics.to_dict() if metrics else None
        session.virtual_clock = active.simulator.current_time
        session.current_step = active.simulator.current_step
        session.progress_pct = active.simulator.progress_pct

        # Bulk insert trades
        for t in active.sandbox.trades:
            db.add(
                BacktestTrade(
                    session_id=UUID(session_id),
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

        # Bulk insert snapshots
        for s in active.sandbox.snapshots:
            db.add(
                BacktestSnapshot(
                    session_id=UUID(session_id),
                    simulated_at=s.simulated_at,
                    total_equity=s.total_equity,
                    available_cash=s.available_cash,
                    position_value=s.position_value,
                    unrealized_pnl=s.unrealized_pnl,
                    realized_pnl=s.realized_pnl,
                    positions=s.positions,
                )
            )

        await db.commit()

        _per_pair = calculate_per_pair_stats(active.sandbox.trades)

        logger.info(
            "backtest.completed",
            session_id=session_id,
            status=status,
            roi_pct=str(roi_pct),
            total_trades=active.sandbox.total_trades,
            duration_sec=str(wall_duration),
        )

        return BacktestResult(
            session_id=session_id,
            status=status,
            config={
                "start_time": active.config.start_time.isoformat(),
                "end_time": active.config.end_time.isoformat(),
                "starting_balance": str(active.config.starting_balance),
                "candle_interval": active.config.candle_interval,
                "pairs": active.config.pairs,
                "strategy_label": active.config.strategy_label,
            },
            final_equity=portfolio.total_equity if portfolio else active.config.starting_balance,
            total_pnl=total_pnl,
            roi_pct=roi_pct,
            total_trades=active.sandbox.total_trades,
            total_fees=active.sandbox.total_fees,
            metrics=metrics,
            per_pair=_per_pair,
            duration_real_sec=wall_duration,
        )
