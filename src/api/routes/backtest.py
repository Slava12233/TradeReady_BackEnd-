"""Backtest API routes.

Implements the full backtest lifecycle, scoped trading/market/account
routes, results analysis, comparison, and mode management.

All endpoints require authentication (request.state.account).
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.backtest import (
    AccountModeResponse,
    BacktestBestResponse,
    BacktestCompareResponse,
    BacktestCreateRequest,
    BacktestCreateResponse,
    BacktestListItem,
    BacktestListResponse,
    BacktestOrderRequest,
    BacktestResultsResponse,
    BacktestStepBatchRequest,
    DataRangeResponse,
    ModeSwitchRequest,
    StepResponse,
)
from src.backtesting.data_replayer import DataReplayer
from src.backtesting.engine import BacktestConfig
from src.dependencies import BacktestEngineDep, BacktestRepoDep, DbSessionDep
from src.utils.exceptions import BacktestNotFoundError

router = APIRouter(prefix="/api/v1", tags=["backtest"])


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_account_id(request: Request) -> UUID:
    """Extract account_id from auth middleware state."""
    return cast(UUID, request.state.account.id)


def _get_agent_id(request: Request) -> UUID | None:
    """Extract agent_id from auth middleware state or X-Agent-Id header.

    Returns the agent UUID if available from API key auth (request.state.agent)
    or from the X-Agent-Id header (JWT auth). Returns None otherwise.
    """
    agent = getattr(request.state, "agent", None)
    if agent is not None:
        return cast(UUID, agent.id)
    header_val = request.headers.get("x-agent-id")
    if header_val:
        return UUID(header_val)
    return None


def _step_to_response(result: Any) -> StepResponse:  # noqa: ANN401
    """Convert engine StepResult to API response."""
    return StepResponse(
        virtual_time=result.virtual_time,
        step=result.step,
        total_steps=result.total_steps,
        progress_pct=str(result.progress_pct),
        prices={k: str(v) for k, v in result.prices.items()},
        orders_filled=[
            {
                "order_id": o.order_id,
                "status": o.status,
                "executed_price": str(o.executed_price) if o.executed_price else None,
                "executed_qty": str(o.executed_qty) if o.executed_qty else None,
                "fee": str(o.fee) if o.fee else None,
            }
            for o in result.orders_filled
        ],
        portfolio={
            "total_equity": str(result.portfolio.total_equity),
            "available_cash": str(result.portfolio.available_cash),
            "position_value": str(result.portfolio.position_value),
            "unrealized_pnl": str(result.portfolio.unrealized_pnl),
            "realized_pnl": str(result.portfolio.realized_pnl),
            "positions": result.portfolio.positions,
        },
        is_complete=result.is_complete,
        remaining_steps=result.remaining_steps,
    )


# ── BT-1.5.1: Data range (add to market) ────────────────────────────────────


@router.get("/market/data-range", response_model=DataRangeResponse)
async def get_data_range(db: DbSessionDep) -> DataRangeResponse:
    """Return available historical data range for backtesting."""
    replayer = DataReplayer(db)
    data_range = await replayer.get_data_range()

    if data_range is None:
        return DataRangeResponse(
            earliest=None,  # type: ignore[arg-type]
            latest=None,  # type: ignore[arg-type]
            total_pairs=0,
            intervals_available=[],
            data_gaps=[],
        )

    return DataRangeResponse(
        earliest=data_range.earliest,
        latest=data_range.latest,
        total_pairs=data_range.total_pairs,
        intervals_available=["1m", "5m", "1h", "1d"],
        data_gaps=[],
    )


# ── BT-1.5.2: Backtest lifecycle ────────────────────────────────────────────


@router.post("/backtest/create", response_model=BacktestCreateResponse)
async def create_backtest(
    request: Request,
    body: BacktestCreateRequest,
    engine: BacktestEngineDep,
    db: DbSessionDep,
) -> BacktestCreateResponse:
    """Create a new backtest session."""
    account_id = _get_account_id(request)
    # Prefer explicit agent_id from body, fall back to auth context
    agent_id = UUID(body.agent_id) if body.agent_id else _get_agent_id(request)

    config = BacktestConfig(
        start_time=body.start_time,
        end_time=body.end_time,
        starting_balance=body.starting_balance,
        candle_interval=body.candle_interval,
        pairs=body.pairs,
        strategy_label=body.strategy_label,
        agent_id=agent_id,
    )

    session = await engine.create_session(account_id, config, db)

    # Count estimated pairs
    replayer = DataReplayer(db, body.pairs)
    pairs = await replayer.get_available_pairs(body.start_time)

    return BacktestCreateResponse(
        session_id=str(session.id),
        status=session.status,
        total_steps=session.total_steps,
        estimated_pairs=len(pairs),
        agent_id=str(session.agent_id) if session.agent_id else None,
    )


@router.post("/backtest/{session_id}/start")
async def start_backtest(
    request: Request,
    session_id: str,
    engine: BacktestEngineDep,
    db: DbSessionDep,
) -> dict[str, str]:
    """Start a created backtest session."""
    await engine.start(session_id, db)
    return {"status": "running", "session_id": session_id}


@router.post("/backtest/{session_id}/step", response_model=StepResponse)
async def step_backtest(
    request: Request,
    session_id: str,
    engine: BacktestEngineDep,
    db: DbSessionDep,
) -> StepResponse:
    """Advance one candle step."""
    result = await engine.step(session_id, db)
    return _step_to_response(result)


@router.post("/backtest/{session_id}/step/batch", response_model=StepResponse)
async def step_batch_backtest(
    request: Request,
    session_id: str,
    body: BacktestStepBatchRequest,
    engine: BacktestEngineDep,
    db: DbSessionDep,
) -> StepResponse:
    """Advance N candle steps."""
    result = await engine.step_batch(session_id, body.steps, db)
    return _step_to_response(result)


@router.post("/backtest/{session_id}/cancel")
async def cancel_backtest(
    request: Request,
    session_id: str,
    engine: BacktestEngineDep,
    db: DbSessionDep,
) -> dict[str, Any]:
    """Cancel a running backtest and save partial results."""
    result = await engine.cancel(session_id, db)
    return {
        "session_id": result.session_id,
        "status": result.status,
        "total_trades": result.total_trades,
        "roi_pct": str(result.roi_pct),
    }


# ── BT-1.5.3: Backtest-scoped trading ───────────────────────────────────────


@router.post("/backtest/{session_id}/trade/order")
async def backtest_place_order(
    request: Request,
    session_id: str,
    body: BacktestOrderRequest,
    engine: BacktestEngineDep,
) -> dict[str, Any]:
    """Place an order in the backtest sandbox."""
    result = await engine.execute_order(
        session_id,
        body.symbol,
        body.side,
        body.type,
        body.quantity,
        body.price,
    )
    return {
        "order_id": result.order_id,
        "status": result.status,
        "executed_price": str(result.executed_price) if result.executed_price else None,
        "executed_qty": str(result.executed_qty) if result.executed_qty else None,
        "fee": str(result.fee) if result.fee else None,
        "realized_pnl": str(result.realized_pnl) if result.realized_pnl else None,
    }


@router.get("/backtest/{session_id}/trade/orders")
async def backtest_list_orders(
    request: Request,
    session_id: str,
    engine: BacktestEngineDep,
) -> dict[str, Any]:
    """List all orders in the backtest sandbox."""
    active = engine._get_active(session_id)
    orders = active.sandbox.get_orders()
    return {
        "orders": [
            {
                "id": o.id,
                "symbol": o.symbol,
                "side": o.side,
                "type": o.type,
                "quantity": str(o.quantity),
                "price": str(o.price) if o.price else None,
                "status": o.status,
                "executed_price": str(o.executed_price) if o.executed_price else None,
                "fee": str(o.fee) if o.fee else None,
            }
            for o in orders
        ],
        "count": len(orders),
    }


@router.get("/backtest/{session_id}/trade/orders/open")
async def backtest_open_orders(
    request: Request,
    session_id: str,
    engine: BacktestEngineDep,
) -> dict[str, Any]:
    """List pending orders in the backtest sandbox."""
    active = engine._get_active(session_id)
    orders = active.sandbox.get_orders(status="pending")
    return {
        "orders": [
            {
                "id": o.id,
                "symbol": o.symbol,
                "side": o.side,
                "type": o.type,
                "quantity": str(o.quantity),
                "price": str(o.price) if o.price else None,
                "status": o.status,
            }
            for o in orders
        ],
        "count": len(orders),
    }


@router.delete("/backtest/{session_id}/trade/order/{order_id}")
async def backtest_cancel_order(
    request: Request,
    session_id: str,
    order_id: str,
    engine: BacktestEngineDep,
) -> dict[str, Any]:
    """Cancel a pending order in the backtest sandbox."""
    cancelled = await engine.cancel_order(session_id, order_id)
    return {"order_id": order_id, "cancelled": cancelled}


@router.get("/backtest/{session_id}/trade/history")
async def backtest_trade_history(
    request: Request,
    session_id: str,
    engine: BacktestEngineDep,
) -> dict[str, Any]:
    """Get trade history from the backtest sandbox."""
    active = engine._get_active(session_id)
    trades = active.sandbox.get_trades()
    return {
        "trades": [
            {
                "id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "type": t.type,
                "quantity": str(t.quantity),
                "price": str(t.price),
                "quote_amount": str(t.quote_amount),
                "fee": str(t.fee),
                "slippage_pct": str(t.slippage_pct),
                "realized_pnl": str(t.realized_pnl) if t.realized_pnl else None,
                "simulated_at": t.simulated_at.isoformat(),
            }
            for t in trades
        ],
        "count": len(trades),
    }


# ── BT-1.5.4: Backtest-scoped market ────────────────────────────────────────


@router.get("/backtest/{session_id}/market/price/{symbol}")
async def backtest_price(
    request: Request,
    session_id: str,
    symbol: str,
    engine: BacktestEngineDep,
) -> dict[str, Any]:
    """Get price for a symbol at the current virtual time."""
    result = await engine.get_price(session_id, symbol)
    return {
        "symbol": result.symbol,
        "price": str(result.price),
        "virtual_time": result.virtual_time.isoformat(),
    }


@router.get("/backtest/{session_id}/market/prices")
async def backtest_prices(
    request: Request,
    session_id: str,
    engine: BacktestEngineDep,
) -> dict[str, Any]:
    """Get all prices at the current virtual time."""
    active = engine._get_active(session_id)
    return {
        "prices": {k: str(v) for k, v in active.current_prices.items()},
        "virtual_time": active.simulator.current_time.isoformat(),
    }


@router.get("/backtest/{session_id}/market/ticker/{symbol}")
async def backtest_ticker(
    request: Request,
    session_id: str,
    symbol: str,
    engine: BacktestEngineDep,
    db: DbSessionDep,
) -> dict[str, Any]:
    """Get 24h ticker stats at the current virtual time."""
    active = engine._get_active(session_id)
    ticker = await active.replayer.load_ticker_24h(symbol, active.simulator.current_time)

    if ticker is None:
        return {"symbol": symbol, "error": "No data available"}

    return {
        "symbol": ticker.symbol,
        "open": str(ticker.open),
        "high": str(ticker.high),
        "low": str(ticker.low),
        "close": str(ticker.close),
        "volume": str(ticker.volume),
        "trade_count": ticker.trade_count,
        "price_change": str(ticker.price_change),
        "price_change_pct": str(ticker.price_change_pct),
        "virtual_time": active.simulator.current_time.isoformat(),
    }


@router.get("/backtest/{session_id}/market/candles/{symbol}")
async def backtest_candles(
    request: Request,
    session_id: str,
    symbol: str,
    engine: BacktestEngineDep,
    interval: int = Query(default=60, description="Interval in seconds"),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    """Get candles up to the current virtual time."""
    candles = await engine.get_candles(session_id, symbol, interval, limit)
    return {
        "symbol": symbol,
        "interval": interval,
        "candles": [
            {
                "bucket": c.bucket.isoformat(),
                "open": str(c.open),
                "high": str(c.high),
                "low": str(c.low),
                "close": str(c.close),
                "volume": str(c.volume),
                "trade_count": c.trade_count,
            }
            for c in candles
        ],
        "count": len(candles),
    }


# ── BT-1.5.5: Backtest-scoped account ───────────────────────────────────────


@router.get("/backtest/{session_id}/account/balance")
async def backtest_balance(
    request: Request,
    session_id: str,
    engine: BacktestEngineDep,
) -> dict[str, Any]:
    """Get sandbox balances."""
    balances = await engine.get_balance(session_id)
    return {
        "balances": [{"asset": b.asset, "available": str(b.available), "locked": str(b.locked)} for b in balances],
    }


@router.get("/backtest/{session_id}/account/positions")
async def backtest_positions(
    request: Request,
    session_id: str,
    engine: BacktestEngineDep,
) -> dict[str, Any]:
    """Get sandbox positions."""
    positions = await engine.get_positions(session_id)
    return {
        "positions": [
            {
                "symbol": p.symbol,
                "quantity": str(p.quantity),
                "avg_entry_price": str(p.avg_entry_price),
                "realized_pnl": str(p.realized_pnl),
            }
            for p in positions
        ],
    }


@router.get("/backtest/{session_id}/account/portfolio")
async def backtest_portfolio(
    request: Request,
    session_id: str,
    engine: BacktestEngineDep,
) -> dict[str, Any]:
    """Get sandbox portfolio summary."""
    portfolio = await engine.get_portfolio(session_id)
    return {
        "total_equity": str(portfolio.total_equity),
        "available_cash": str(portfolio.available_cash),
        "position_value": str(portfolio.position_value),
        "unrealized_pnl": str(portfolio.unrealized_pnl),
        "realized_pnl": str(portfolio.realized_pnl),
        "positions": portfolio.positions,
    }


# ── Status endpoint (for UI polling) ────────────────────────────────────────


@router.get("/backtest/{session_id}/status", response_model=BacktestListItem)
async def get_backtest_status(
    request: Request,
    session_id: str,
    repo: BacktestRepoDep,
    engine: BacktestEngineDep,
    db: DbSessionDep,
) -> BacktestListItem:
    """Get current status/progress of a backtest session.

    Used by the frontend to poll running backtests for live progress updates.
    Detects orphaned sessions (running in DB but not in engine memory) and
    marks them as failed.
    """
    account_id = _get_account_id(request)
    s = await repo.get_session(UUID(session_id), account_id)

    if s is None:
        raise BacktestNotFoundError(session_id=UUID(session_id))

    # Detect orphaned session: DB says running but engine has no active session
    if s.status in ("running", "created") and session_id not in engine._active:
        from datetime import datetime as _dt

        from sqlalchemy import update as sa_update

        from src.database.models import BacktestSession as BtModel

        now = _dt.now(tz=UTC)
        stmt = sa_update(BtModel).where(BtModel.id == s.id).values(status="failed", completed_at=now)
        await db.execute(stmt)
        await db.commit()
        # Re-fetch the updated session
        s = await repo.get_session(UUID(session_id), account_id)
        if s is None:
            raise BacktestNotFoundError(session_id=UUID(session_id))

    return BacktestListItem(
        session_id=str(s.id),
        agent_id=str(s.agent_id) if s.agent_id else None,
        strategy_label=s.strategy_label,
        start_time=s.start_time,
        end_time=s.end_time,
        status=s.status,
        candle_interval=s.candle_interval,
        starting_balance=str(s.starting_balance) if s.starting_balance is not None else None,
        pairs=s.pairs,
        progress_pct=float(s.progress_pct) if s.progress_pct is not None else 0.0,
        current_step=s.current_step or 0,
        total_steps=s.total_steps or 0,
        virtual_clock=s.virtual_clock,
        final_equity=str(s.final_equity) if s.final_equity is not None else None,
        total_pnl=str(s.total_pnl) if s.total_pnl is not None else None,
        roi_pct=str(s.roi_pct) if s.roi_pct is not None else None,
        total_trades=s.total_trades or 0,
        total_fees=str(s.total_fees) if s.total_fees is not None else None,
        sharpe_ratio=(s.metrics.get("sharpe_ratio") if s.metrics else None),
        max_drawdown_pct=(s.metrics.get("max_drawdown_pct") if s.metrics else None),
        created_at=s.created_at,
        started_at=s.started_at,
        completed_at=s.completed_at,
        duration_real_sec=(float(s.duration_real_sec) if s.duration_real_sec is not None else None),
    )


# ── BT-1.5.6: Results & analysis ────────────────────────────────────────────


@router.get("/backtest/{session_id}/results", response_model=BacktestResultsResponse)
async def get_backtest_results(
    request: Request,
    session_id: str,
    repo: BacktestRepoDep,
) -> BacktestResultsResponse:
    """Get full results of a completed backtest."""
    account_id = _get_account_id(request)
    session = await repo.get_session(UUID(session_id), account_id)

    if session is None:
        raise BacktestNotFoundError(session_id=UUID(session_id))

    # Build metrics with safe defaults for all expected frontend fields
    raw_metrics = session.metrics or {}
    metrics = {
        "sharpe_ratio": raw_metrics.get("sharpe_ratio"),
        "sortino_ratio": raw_metrics.get("sortino_ratio"),
        "max_drawdown_pct": raw_metrics.get("max_drawdown_pct"),
        "max_drawdown_duration_days": raw_metrics.get("max_drawdown_duration_days"),
        "win_rate": raw_metrics.get("win_rate"),
        "profit_factor": raw_metrics.get("profit_factor"),
        "avg_win": raw_metrics.get("avg_win"),
        "avg_loss": raw_metrics.get("avg_loss"),
        "best_trade": raw_metrics.get("best_trade"),
        "worst_trade": raw_metrics.get("worst_trade"),
        "avg_trade_duration_minutes": raw_metrics.get("avg_trade_duration_minutes"),
        "trades_per_day": raw_metrics.get("trades_per_day"),
    }

    return BacktestResultsResponse(
        session_id=str(session.id),
        status=session.status,
        config={
            "start_time": session.start_time.isoformat(),
            "end_time": session.end_time.isoformat(),
            "starting_balance": str(session.starting_balance),
            "candle_interval": str(session.candle_interval),
            "pairs": session.pairs or [],
            "strategy_label": session.strategy_label,
        },
        summary={
            "final_equity": str(session.final_equity) if session.final_equity is not None else "0",
            "total_pnl": str(session.total_pnl) if session.total_pnl is not None else "0",
            "roi_pct": str(session.roi_pct) if session.roi_pct is not None else "0",
            "total_trades": session.total_trades or 0,
            "total_fees": str(session.total_fees) if session.total_fees is not None else "0",
            "duration_real_sec": float(session.duration_real_sec) if session.duration_real_sec else 0,
        },
        metrics=metrics,
        by_pair=[],
    )


@router.get("/backtest/{session_id}/results/equity-curve")
async def get_equity_curve(
    request: Request,
    session_id: str,
    repo: BacktestRepoDep,
    interval: int = Query(default=1, ge=1),
) -> dict[str, Any]:
    """Get equity curve data for a completed backtest."""
    snapshots = await repo.get_snapshots(UUID(session_id))
    return {
        "session_id": session_id,
        "interval": str(interval),
        "snapshots": [
            {
                "simulated_at": s.simulated_at.isoformat(),
                "total_equity": str(s.total_equity),
                "available_cash": str(s.available_cash) if s.available_cash is not None else "0",
                "position_value": str(s.position_value) if s.position_value is not None else "0",
                "unrealized_pnl": str(s.unrealized_pnl) if s.unrealized_pnl is not None else "0",
                "realized_pnl": str(s.realized_pnl) if s.realized_pnl is not None else "0",
            }
            for i, s in enumerate(snapshots)
            if i % interval == 0
        ],
    }


@router.get("/backtest/{session_id}/results/trades")
async def get_backtest_trades(
    request: Request,
    session_id: str,
    repo: BacktestRepoDep,
    limit: int = Query(default=1000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """Get trade log for a completed backtest."""
    trades = await repo.get_trades(UUID(session_id), limit=limit, offset=offset)
    return {
        "session_id": session_id,
        "trades": [
            {
                "id": str(t.id),
                "session_id": session_id,
                "symbol": t.symbol,
                "side": t.side,
                "type": t.type,
                "quantity": str(t.quantity),
                "price": str(t.price),
                "quote_amount": str(t.quote_amount),
                "fee": str(t.fee),
                "slippage_pct": str(t.slippage_pct),
                "realized_pnl": str(t.realized_pnl) if t.realized_pnl else "0",
                "simulated_at": t.simulated_at.isoformat(),
            }
            for t in trades
        ],
        "total": len(trades),
    }


@router.get("/backtest/list", response_model=BacktestListResponse)
async def list_backtests(
    request: Request,
    repo: BacktestRepoDep,
    engine: BacktestEngineDep,
    db: DbSessionDep,
    strategy_label: str | None = Query(default=None),
    status: str | None = Query(default=None),
    agent_id: str | None = Query(default=None, description="Filter by agent UUID"),
    sort_by: str = Query(default="created_at"),
    limit: int = Query(default=50, ge=1, le=200),
) -> BacktestListResponse:
    """List all backtests for the authenticated account."""
    from datetime import datetime as _dt

    account_id = _get_account_id(request)
    agent_uuid = UUID(agent_id) if agent_id else None
    sessions = await repo.list_sessions(
        account_id,
        agent_id=agent_uuid,
        strategy_label=strategy_label,
        status=status,
        sort_by=sort_by,
        limit=limit,
    )

    # Mark orphaned sessions (running in DB but not in engine memory) as failed
    orphan_ids = [s.id for s in sessions if s.status in ("running", "created") and str(s.id) not in engine._active]
    if orphan_ids:
        from sqlalchemy import update as sa_update

        from src.database.models import BacktestSession as BtModel

        now = _dt.now(tz=UTC)
        stmt = sa_update(BtModel).where(BtModel.id.in_(orphan_ids)).values(status="failed", completed_at=now)
        await db.execute(stmt)
        await db.commit()
        # Re-fetch so the response reflects the updated status
        sessions = await repo.list_sessions(
            account_id,
            agent_id=agent_uuid,
            strategy_label=strategy_label,
            status=status,
            sort_by=sort_by,
            limit=limit,
        )

    items = [
        BacktestListItem(
            session_id=str(s.id),
            agent_id=str(s.agent_id) if s.agent_id else None,
            strategy_label=s.strategy_label,
            start_time=s.start_time,
            end_time=s.end_time,
            status=s.status,
            candle_interval=s.candle_interval,
            starting_balance=str(s.starting_balance) if s.starting_balance is not None else None,
            pairs=s.pairs,
            progress_pct=float(s.progress_pct) if s.progress_pct is not None else 0.0,
            current_step=s.current_step or 0,
            total_steps=s.total_steps or 0,
            virtual_clock=s.virtual_clock,
            final_equity=str(s.final_equity) if s.final_equity is not None else None,
            total_pnl=str(s.total_pnl) if s.total_pnl is not None else None,
            roi_pct=str(s.roi_pct) if s.roi_pct is not None else None,
            total_trades=s.total_trades or 0,
            total_fees=str(s.total_fees) if s.total_fees is not None else None,
            sharpe_ratio=(s.metrics.get("sharpe_ratio") if s.metrics else None),
            max_drawdown_pct=(s.metrics.get("max_drawdown_pct") if s.metrics else None),
            created_at=s.created_at,
            started_at=s.started_at,
            completed_at=s.completed_at,
            duration_real_sec=(float(s.duration_real_sec) if s.duration_real_sec is not None else None),
        )
        for s in sessions
    ]
    return BacktestListResponse(backtests=items, total=len(items))


@router.get("/backtest/compare", response_model=BacktestCompareResponse)
async def compare_backtests(
    request: Request,
    repo: BacktestRepoDep,
    sessions: str = Query(description="Comma-separated session IDs"),
) -> BacktestCompareResponse:
    """Compare multiple backtest sessions side-by-side."""
    session_ids = [UUID(s.strip()) for s in sessions.split(",") if s.strip()]
    bt_sessions = await repo.get_sessions_for_compare(session_ids)

    comparisons: list[dict[str, Any]] = []
    best_roi: tuple[str | None, Decimal] = (None, Decimal("-999999"))
    best_sharpe: tuple[str | None, Decimal] = (None, Decimal("-999999"))
    best_dd: tuple[str | None, Decimal] = (None, Decimal("999999"))

    for s in bt_sessions:
        roi = s.roi_pct or Decimal("0")
        sharpe = Decimal(s.metrics.get("sharpe_ratio", "0")) if s.metrics else Decimal("0")
        dd = Decimal(s.metrics.get("max_drawdown_pct", "100")) if s.metrics else Decimal("100")

        comp = {
            "session_id": str(s.id),
            "strategy_label": s.strategy_label,
            "roi_pct": str(roi),
            "sharpe_ratio": str(sharpe),
            "max_drawdown_pct": str(dd),
            "total_trades": s.total_trades,
            "win_rate": s.metrics.get("win_rate") if s.metrics else None,
            "profit_factor": s.metrics.get("profit_factor") if s.metrics else None,
        }
        comparisons.append(comp)

        if roi > best_roi[1]:
            best_roi = (str(s.id), roi)
        if sharpe > best_sharpe[1]:
            best_sharpe = (str(s.id), sharpe)
        if dd < best_dd[1]:
            best_dd = (str(s.id), dd)

    return BacktestCompareResponse(
        comparisons=comparisons,
        best_by_roi=best_roi[0],
        best_by_sharpe=best_sharpe[0],
        best_by_drawdown=best_dd[0],
        recommendation=best_sharpe[0],
    )


@router.get("/backtest/best", response_model=BacktestBestResponse)
async def get_best_backtest(
    request: Request,
    repo: BacktestRepoDep,
    metric: str = Query(default="roi_pct"),
    strategy_label: str | None = Query(default=None),
) -> BacktestBestResponse:
    """Find the best completed backtest by a metric."""
    account_id = _get_account_id(request)
    session = await repo.get_best_session(account_id, metric, strategy_label)

    if session is None:
        raise BacktestNotFoundError("No completed backtests found for this account.")

    value = str(getattr(session, metric, "N/A"))
    return BacktestBestResponse(
        session_id=str(session.id),
        strategy_label=session.strategy_label,
        metric=metric,
        value=value,
    )


# ── BT-1.5.7: Mode management ───────────────────────────────────────────────


@router.get("/account/mode", response_model=AccountModeResponse)
async def get_account_mode(
    request: Request,
    repo: BacktestRepoDep,
    db: DbSessionDep,
) -> AccountModeResponse:
    """Get the current account operating mode."""
    from sqlalchemy import func, select

    from src.database.models import Account, BacktestSession

    account_id = _get_account_id(request)

    # Get account
    stmt = select(Account).where(Account.id == account_id)
    result = await db.execute(stmt)
    account = result.scalars().first()

    # Count active and completed backtests
    active_count_stmt = select(func.count()).where(
        BacktestSession.account_id == account_id,
        BacktestSession.status == "running",
    )
    completed_count_stmt = select(func.count()).where(
        BacktestSession.account_id == account_id,
        BacktestSession.status == "completed",
    )

    active_result = await db.execute(active_count_stmt)
    completed_result = await db.execute(completed_count_stmt)

    return AccountModeResponse(
        mode=account.current_mode if account else "live",
        active_strategy_label=account.active_strategy_label if account else None,
        active_backtests=active_result.scalar_one(),
        total_backtests_completed=completed_result.scalar_one(),
    )


@router.post("/account/mode", response_model=AccountModeResponse)
async def switch_account_mode(
    request: Request,
    body: ModeSwitchRequest,
    db: DbSessionDep,
) -> AccountModeResponse:
    """Switch account between live and backtest mode."""
    from sqlalchemy import update

    from src.database.models import Account

    account_id = _get_account_id(request)

    stmt = (
        update(Account)
        .where(Account.id == account_id)
        .values(
            current_mode=body.mode,
            active_strategy_label=body.strategy_label,
        )
    )
    await db.execute(stmt)

    # Return updated mode
    return await get_account_mode(request, await get_backtest_repo_instance(db), db)


async def get_backtest_repo_instance(db: AsyncSession) -> Any:  # noqa: ANN401
    """Helper to create a BacktestRepository instance."""
    from src.database.repositories.backtest_repo import BacktestRepository

    return BacktestRepository(db)
