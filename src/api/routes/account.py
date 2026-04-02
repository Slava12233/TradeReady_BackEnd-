"""Account routes for the AI Agent Crypto Trading Platform.

Implements authenticated account management endpoints (Section 15.4):

- ``GET  /api/v1/account/info``       — account details, session, risk profile
- ``GET  /api/v1/account/balance``    — per-asset balances + total equity
- ``GET  /api/v1/account/positions``  — open positions with unrealised PnL
- ``GET  /api/v1/account/portfolio``  — full portfolio snapshot (cash + positions + PnL)
- ``GET  /api/v1/account/pnl``        — PnL breakdown with period and win-rate stats
- ``POST /api/v1/account/reset``      — reset account to starting balance (destructive)

All endpoints require authentication via ``X-API-Key`` or ``Authorization: Bearer``.
The :class:`~src.api.middleware.auth.AuthMiddleware` resolves the account before the
handler runs; routes retrieve it through the :func:`get_current_account` dependency.

Data flow::

    GET /api/v1/account/portfolio
      → PortfolioTracker.get_portfolio()   (DB + Redis price lookup)
      → PortfolioResponse (HTTP 200)

    POST /api/v1/account/reset
      → validate confirm flag
      → snapshot pre-reset equity via PortfolioTracker
      → AccountService.reset_account()     (atomic DB reset)
      → ResetResponse (HTTP 200)

Example::

    # Get current portfolio
    GET /api/v1/account/portfolio
    X-API-Key: ak_live_...
    → {"total_equity": "12458.30", "roi_pct": "24.58", ...}

    # Reset account (destructive — wipes all balances + history)
    POST /api/v1/account/reset
    X-API-Key: ak_live_...
    {"confirm": true}
    → {"message": "Account reset successful", "new_session": {...}}
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.auth import CurrentAccountDep, CurrentAgentDep
from src.api.schemas.account import (
    AccountInfoResponse,
    BalanceItem,
    BalancesResponse,
    NewSessionSummary,
    PnLPeriod,
    PnLResponse,
    PortfolioResponse,
    PositionItem,
    PositionsResponse,
    PreviousSessionSummary,
    ResetRequest,
    ResetResponse,
    RiskProfileInfo,
    SessionInfo,
)
from src.database.models import Account, Agent, Position, TradingSession
from src.dependencies import (
    AccountRepoDep,
    AccountServiceDep,
    AgentRepoDep,
    BalanceManagerDep,
    DbSessionDep,
    PortfolioTrackerDep,
    TradeRepoDep,
)
from src.portfolio.tracker import PositionView
from src.utils.exceptions import InputValidationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/account", tags=["account"])

# Default risk profile values (used when risk_profile JSONB is empty/missing)
_DEFAULT_MAX_POSITION_PCT = 25
_DEFAULT_DAILY_LOSS_PCT = 20
_DEFAULT_MAX_OPEN_ORDERS = 50


# ---------------------------------------------------------------------------
# Helpers: ORM → schema conversion
# ---------------------------------------------------------------------------


def _position_view_to_item(
    view: PositionView,
    opened_at: datetime | None = None,
) -> PositionItem:
    """Convert a :class:`~src.portfolio.tracker.PositionView` to :class:`PositionItem`.

    Args:
        view:      The portfolio tracker position view.
        opened_at: The real ``opened_at`` timestamp from the ``positions`` table.
                   Falls back to the current UTC time when ``None``.

    Returns:
        A :class:`PositionItem` suitable for inclusion in API responses.
    """
    return PositionItem(
        symbol=view.symbol,
        asset=view.asset,
        quantity=view.quantity,
        avg_entry_price=view.avg_entry_price,
        current_price=view.current_price,
        market_value=view.market_value,
        unrealized_pnl=view.unrealized_pnl,
        unrealized_pnl_pct=view.unrealized_pnl_pct,
        opened_at=opened_at if opened_at is not None else datetime.now(tz=UTC),
    )


async def _build_opened_at_map(
    agent_id: UUID | None,
    account_id: UUID,
    db: AsyncSession,
) -> dict[str, datetime]:
    """Fetch ``opened_at`` timestamps for all open positions.

    Queries the ``positions`` table and returns a mapping of symbol to
    ``opened_at`` so callers can attach real timestamps to position views.

    Args:
        agent_id:   Agent UUID when using agent-scoped auth; ``None`` for
                    account-level lookups.
        account_id: Account UUID used as the fallback scope.
        db:         Async database session.

    Returns:
        Dictionary mapping symbol strings to their ``opened_at`` datetimes.
    """
    stmt = select(Position.symbol, Position.opened_at).where(
        Position.agent_id == agent_id if agent_id is not None else Position.account_id == account_id
    )
    result = await db.execute(stmt)
    return {row.symbol: row.opened_at for row in result}


def _build_risk_profile_info(
    account: Account,
    agent: Agent | None = None,
) -> RiskProfileInfo:
    """Extract risk profile overrides from the agent or account JSONB field.

    When *agent* is provided and has a non-empty ``risk_profile``, it takes
    precedence over the account's profile.

    Args:
        account: The ORM :class:`~src.database.models.Account` instance.
        agent:   Optional :class:`~src.database.models.Agent` instance.

    Returns:
        A :class:`RiskProfileInfo` with the effective limits.
    """
    if agent is not None and agent.risk_profile:
        profile: dict[str, Any] = dict(agent.risk_profile)
    else:
        profile = account.risk_profile or {}
    return RiskProfileInfo(
        max_position_size_pct=int(profile.get("max_position_size_pct", _DEFAULT_MAX_POSITION_PCT)),
        daily_loss_limit_pct=int(profile.get("daily_loss_limit_pct", _DEFAULT_DAILY_LOSS_PCT)),
        max_open_orders=int(profile.get("max_open_orders", _DEFAULT_MAX_OPEN_ORDERS)),
    )


async def _get_active_session(
    account_id: UUID,
    db: AsyncSession,
) -> TradingSession | None:
    """Fetch the active :class:`~src.database.models.TradingSession` for an account.

    Args:
        account_id: UUID of the account to look up.
        db:         The current async database session.

    Returns:
        The active :class:`TradingSession` row, or ``None`` if none exists.
    """
    stmt = (
        select(TradingSession)
        .where(
            TradingSession.account_id == account_id,
            TradingSession.status == "active",
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# GET /api/v1/account/info — account details
# ---------------------------------------------------------------------------


@router.get(
    "/info",
    response_model=AccountInfoResponse,
    status_code=status.HTTP_200_OK,
    summary="Get account info",
    description=(
        "Return account details, the current trading session, and the "
        "effective risk profile for the authenticated account."
    ),
)
async def get_account_info(
    account: CurrentAccountDep,
    agent: CurrentAgentDep,
    db: DbSessionDep,
) -> AccountInfoResponse:
    """Return the authenticated account's details, session, and risk profile.

    Args:
        account: Injected authenticated account (set by ``AuthMiddleware``).
        db:      Injected async database session.

    Returns:
        :class:`~src.api.schemas.account.AccountInfoResponse` with account
        metadata, active session details, and risk configuration.

    Raises:
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected DB
            failure (HTTP 500).

    Example::

        GET /api/v1/account/info
        X-API-Key: ak_live_...
        →  HTTP 200
        {
          "account_id": "550e8400-...",
          "display_name": "MyTradingBot",
          "status": "active",
          "starting_balance": "10000.00",
          "current_session": {"session_id": "...", "started_at": "..."},
          "risk_profile": {"max_position_size_pct": 25, ...},
          "created_at": "2026-02-20T00:00:00Z"
        }
    """
    active_session = await _get_active_session(account.id, db)

    if active_session is not None:
        session_info = SessionInfo(
            session_id=active_session.id,
            started_at=active_session.started_at,
        )
    else:
        # Defensive: session may be temporarily absent during a concurrent reset.
        # Synthesise a placeholder so the endpoint never 500s.
        session_info = SessionInfo(
            session_id=account.id,  # reuse account UUID as a sentinel
            started_at=account.created_at,
        )

    risk_profile_info = _build_risk_profile_info(account, agent=agent)

    # Use agent's starting_balance when agent context is present
    effective_starting_balance = (
        Decimal(str(agent.starting_balance))
        if agent is not None and agent.starting_balance is not None
        else Decimal(str(account.starting_balance))
    )

    logger.info(
        "account.get_info",
        extra={"account_id": str(account.id)},
    )

    return AccountInfoResponse(
        account_id=account.id,
        api_key=account.api_key,
        display_name=account.display_name,
        status=account.status,  # type: ignore[arg-type]
        starting_balance=effective_starting_balance,
        current_session=session_info,
        risk_profile=risk_profile_info,
        created_at=account.created_at,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/account/balance — per-asset balances
# ---------------------------------------------------------------------------


@router.get(
    "/balance",
    response_model=BalancesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get account balances",
    description=(
        "Return per-asset balance breakdown (available + locked) and the total portfolio equity expressed in USDT."
    ),
)
async def get_balance(
    account: CurrentAccountDep,
    agent: CurrentAgentDep,
    balance_manager: BalanceManagerDep,
    tracker: PortfolioTrackerDep,
) -> BalancesResponse:
    """Return all asset balances and total equity for the authenticated account.

    Args:
        account:         Injected authenticated account.
        balance_manager: Injected :class:`~src.accounts.balance_manager.BalanceManager`.
        tracker:         Injected :class:`~src.portfolio.tracker.PortfolioTracker`
                         (used for total equity calculation).

    Returns:
        :class:`~src.api.schemas.account.BalancesResponse` with a per-asset
        breakdown and a USDT-denominated total equity figure.

    Raises:
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected DB
            failure (HTTP 500).
        :exc:`~src.utils.exceptions.CacheError`: On a Redis failure when
            computing total equity (HTTP 503).

    Example::

        GET /api/v1/account/balance
        →  HTTP 200
        {
          "balances": [
            {"asset": "USDT", "available": "6741.50", "locked": "1500.00", "total": "8241.50"},
            {"asset": "BTC",  "available": "0.50000000", "locked": "0.00000000", "total": "0.50000000"}
          ],
          "total_equity_usdt": "12458.30"
        }
    """
    agent_id = agent.id if agent is not None else None
    raw_balances = await balance_manager.get_all_balances(account.id, agent_id=agent_id)

    balance_items = [
        BalanceItem(
            asset=b.asset,
            available=Decimal(str(b.available)),
            locked=Decimal(str(b.locked)),
            total=Decimal(str(b.available)) + Decimal(str(b.locked)),
        )
        for b in raw_balances
    ]

    portfolio = await tracker.get_portfolio(account.id, agent_id=agent_id)

    # Defensive sync: ensure every asset with an open position appears in
    # the balance list.  The order engine's atomic_execute_buy should always
    # create balance rows, but if a row is missing (e.g. due to a past
    # partial failure or manual DB edit) we surface a zero-balance entry so
    # the frontend wallet never silently hides a held asset.
    balance_asset_set = {item.asset for item in balance_items}
    for pos in portfolio.positions:
        asset = pos.symbol.removesuffix("USDT")
        if asset and asset not in balance_asset_set:
            balance_items.append(
                BalanceItem(
                    asset=asset,
                    available=Decimal(str(pos.quantity)),
                    locked=Decimal("0"),
                    total=Decimal(str(pos.quantity)),
                )
            )
            balance_asset_set.add(asset)
            logger.warning(
                "account.balance.position_without_balance_row",
                extra={
                    "account_id": str(account.id),
                    "asset": asset,
                    "position_qty": str(pos.quantity),
                },
            )

    logger.info(
        "account.get_balance",
        extra={
            "account_id": str(account.id),
            "asset_count": len(balance_items),
            "total_equity_usdt": str(portfolio.total_equity),
        },
    )

    return BalancesResponse(
        balances=balance_items,
        total_equity_usdt=portfolio.total_equity,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/account/positions — open positions
# ---------------------------------------------------------------------------


@router.get(
    "/positions",
    response_model=PositionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get open positions",
    description=(
        "Return all open positions for the authenticated account, each "
        "valued at the current live market price from Redis."
    ),
)
async def get_positions(
    account: CurrentAccountDep,
    agent: CurrentAgentDep,
    tracker: PortfolioTrackerDep,
    db: DbSessionDep,
) -> PositionsResponse:
    """Return all open positions valued at current market prices.

    Args:
        account: Injected authenticated account.
        agent:   Injected authenticated agent (may be None).
        tracker: Injected :class:`~src.portfolio.tracker.PortfolioTracker`.
        db:      Injected async database session (used to fetch ``opened_at``).

    Returns:
        :class:`~src.api.schemas.account.PositionsResponse` with the list of
        open positions and the aggregate unrealised PnL.

    Raises:
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected DB
            failure (HTTP 500).
        :exc:`~src.utils.exceptions.CacheError`: On a Redis failure during
            price lookup (HTTP 503).

    Example::

        GET /api/v1/account/positions
        →  HTTP 200
        {
          "positions": [{"symbol": "BTCUSDT", "quantity": "0.5", ...}],
          "total_unrealized_pnl": "660.65"
        }
    """
    agent_id = agent.id if agent is not None else None
    positions = await tracker.get_positions(account.id, agent_id=agent_id)
    opened_at_map = await _build_opened_at_map(agent_id, account.id, db)

    position_items = [_position_view_to_item(p, opened_at_map.get(p.symbol)) for p in positions]
    total_unrealized_pnl = sum(
        (p.unrealized_pnl for p in positions),
        Decimal("0"),
    )

    logger.info(
        "account.get_positions",
        extra={
            "account_id": str(account.id),
            "open_positions": len(position_items),
            "total_unrealized_pnl": str(total_unrealized_pnl),
        },
    )

    return PositionsResponse(
        positions=position_items,
        total_unrealized_pnl=total_unrealized_pnl,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/account/portfolio — full portfolio snapshot
# ---------------------------------------------------------------------------


@router.get(
    "/portfolio",
    response_model=PortfolioResponse,
    status_code=status.HTTP_200_OK,
    summary="Get portfolio snapshot",
    description=(
        "Return a complete real-time portfolio snapshot combining cash balances, "
        "open positions (valued at live prices), and aggregate PnL / ROI metrics."
    ),
)
async def get_portfolio(
    account: CurrentAccountDep,
    agent: CurrentAgentDep,
    tracker: PortfolioTrackerDep,
    db: DbSessionDep,
) -> PortfolioResponse:
    """Return a full real-time portfolio snapshot for the authenticated account.

    Args:
        account: Injected authenticated account.
        agent:   Injected authenticated agent (may be None).
        tracker: Injected :class:`~src.portfolio.tracker.PortfolioTracker`.
        db:      Injected async database session (used to fetch ``opened_at``).

    Returns:
        :class:`~src.api.schemas.account.PortfolioResponse` with equity,
        cash, positions, PnL, ROI, and a UTC snapshot timestamp.

    Raises:
        :exc:`~src.utils.exceptions.AccountNotFoundError`: If the account
            no longer exists (HTTP 404).
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected DB
            failure (HTTP 500).
        :exc:`~src.utils.exceptions.CacheError`: On a Redis failure during
            price lookup (HTTP 503).

    Example::

        GET /api/v1/account/portfolio
        →  HTTP 200
        {
          "total_equity": "12458.30",
          "available_cash": "6741.50",
          "roi_pct": "24.58",
          "positions": [...],
          "timestamp": "2026-02-23T15:30:45Z"
        }
    """
    agent_id = agent.id if agent is not None else None
    summary = await tracker.get_portfolio(account.id, agent_id=agent_id)
    opened_at_map = await _build_opened_at_map(agent_id, account.id, db)

    position_items = [_position_view_to_item(p, opened_at_map.get(p.symbol)) for p in summary.positions]

    logger.info(
        "account.get_portfolio",
        extra={
            "account_id": str(account.id),
            "total_equity": str(summary.total_equity),
            "roi_pct": str(summary.roi_pct),
        },
    )

    return PortfolioResponse(
        total_equity=summary.total_equity,
        available_cash=summary.available_cash,
        locked_cash=summary.locked_cash,
        total_position_value=summary.total_position_value,
        unrealized_pnl=summary.unrealized_pnl,
        realized_pnl=summary.realized_pnl,
        total_pnl=summary.total_pnl,
        roi_pct=summary.roi_pct,
        starting_balance=summary.starting_balance,
        positions=position_items,
        timestamp=datetime.now(tz=UTC),
    )


# ---------------------------------------------------------------------------
# GET /api/v1/account/pnl — PnL breakdown
# ---------------------------------------------------------------------------


@router.get(
    "/pnl",
    response_model=PnLResponse,
    status_code=status.HTTP_200_OK,
    summary="Get PnL breakdown",
    description=(
        "Return a detailed profit-and-loss breakdown for the requested time "
        "period including realised, unrealised, fees, and win-rate statistics."
    ),
)
async def get_pnl(
    account: CurrentAccountDep,
    agent: CurrentAgentDep,
    tracker: PortfolioTrackerDep,
    trade_repo: TradeRepoDep,
    period: Annotated[
        PnLPeriod,
        Query(
            description="Time window: '1d' (today), '7d', '30d', or 'all'.",
            examples=["7d"],
        ),
    ] = "all",
) -> PnLResponse:
    """Return a detailed PnL breakdown for the authenticated account.

    Computes unrealised PnL from live prices, realised PnL from trade history,
    and calculates fees paid and win-rate statistics within the requested period.

    Args:
        account:    Injected authenticated account.
        agent:      Injected authenticated agent (may be None).
        tracker:    Injected :class:`~src.portfolio.tracker.PortfolioTracker`
                    (unrealised PnL + all-time realised PnL).
        trade_repo: Injected :class:`~src.database.repositories.trade_repo.TradeRepository`
                    (per-period trade statistics).
        period:     One of ``"1d"``, ``"7d"``, ``"30d"``, or ``"all"``
                    (query param, default ``"all"``).

    Returns:
        :class:`~src.api.schemas.account.PnLResponse` with realized, unrealized,
        fees, net PnL, and win-rate stats scoped to the requested period.

    Raises:
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected DB
            failure (HTTP 500).
        :exc:`~src.utils.exceptions.CacheError`: On a Redis failure during
            unrealised PnL calculation (HTTP 503).

    Example::

        GET /api/v1/account/pnl?period=7d
        →  HTTP 200
        {
          "period": "7d",
          "realized_pnl": "1241.30",
          "unrealized_pnl": "660.65",
          "total_pnl": "1901.95",
          "fees_paid": "156.20",
          "net_pnl": "1745.75",
          "winning_trades": 23,
          "losing_trades": 12,
          "win_rate": "65.71"
        }
    """
    agent_id = agent.id if agent is not None else None
    pnl_breakdown = await tracker.get_pnl(account.id, agent_id=agent_id)

    # Fetch the scoped trade list to compute fees + win-rate for the period.
    limit_by_period = _period_to_trade_limit(period)
    period_trades = await trade_repo.list_by_account(
        account.id,
        agent_id=agent_id,
        limit=limit_by_period,
        offset=0,
    )

    fees_paid = sum(
        (Decimal(str(t.fee)) for t in period_trades if t.fee is not None),
        Decimal("0"),
    )
    winning_trades = sum(1 for t in period_trades if t.realized_pnl is not None and Decimal(str(t.realized_pnl)) > 0)
    losing_trades = sum(1 for t in period_trades if t.realized_pnl is not None and Decimal(str(t.realized_pnl)) < 0)
    breakeven_trades = sum(1 for t in period_trades if t.realized_pnl is not None and Decimal(str(t.realized_pnl)) == 0)
    total_trades_with_pnl = winning_trades + losing_trades + breakeven_trades
    win_rate = (
        Decimal(str(winning_trades)) / Decimal(str(total_trades_with_pnl)) * Decimal("100")
        if total_trades_with_pnl > 0
        else Decimal("0")
    )

    realized_pnl = pnl_breakdown.realized_pnl
    unrealized_pnl = pnl_breakdown.unrealized_pnl
    total_pnl = pnl_breakdown.total_pnl
    net_pnl = total_pnl - fees_paid

    logger.info(
        "account.get_pnl",
        extra={
            "account_id": str(account.id),
            "period": period,
            "realized_pnl": str(realized_pnl),
            "unrealized_pnl": str(unrealized_pnl),
            "win_rate": str(win_rate),
        },
    )

    return PnLResponse(
        period=period,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_pnl=total_pnl,
        fees_paid=fees_paid,
        net_pnl=net_pnl,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
    )


# ---------------------------------------------------------------------------
# PUT /api/v1/account/risk-profile — update risk limits
# ---------------------------------------------------------------------------


@router.put(
    "/risk-profile",
    response_model=RiskProfileInfo,
    status_code=status.HTTP_200_OK,
    summary="Update risk profile",
    description=("Update the authenticated account's risk limits. All three fields must be provided."),
)
async def update_risk_profile(
    body: RiskProfileInfo,
    account: CurrentAccountDep,
    agent: CurrentAgentDep,
    account_repo: AccountRepoDep,
    agent_repo: AgentRepoDep,
) -> RiskProfileInfo:
    """Persist updated risk limits for the authenticated account or agent.

    When an agent context is present (via ``X-Agent-Id`` header), the risk
    profile is written to the agent's ``risk_profile`` JSONB field instead of
    the account's, ensuring per-agent risk isolation.

    Args:
        body:         New risk limits to apply.
        account:      Injected authenticated account.
        agent:        Injected authenticated agent (may be None).
        account_repo: Injected :class:`~src.database.repositories.account_repo.AccountRepository`.
        agent_repo:   Injected :class:`~src.database.repositories.agent_repo.AgentRepository`.

    Returns:
        The updated :class:`~src.api.schemas.account.RiskProfileInfo`.
    """
    profile: dict[str, object] = {
        "max_position_size_pct": body.max_position_size_pct,
        "daily_loss_limit_pct": body.daily_loss_limit_pct,
        "max_open_orders": body.max_open_orders,
    }

    if agent is not None:
        # Write to agent's risk_profile when agent context exists
        existing = dict(agent.risk_profile) if agent.risk_profile else {}
        existing.update(profile)
        await agent_repo.update(agent.id, risk_profile=existing)
        logger.info(
            "account.risk_profile_updated",
            extra={"account_id": str(account.id), "agent_id": str(agent.id), "target": "agent"},
        )
    else:
        await account_repo.update_risk_profile(account.id, profile)
        logger.info(
            "account.risk_profile_updated",
            extra={"account_id": str(account.id), "target": "account"},
        )

    return body


def _period_to_trade_limit(period: PnLPeriod) -> int:
    """Map a PnL period string to a reasonable trade fetch limit.

    This is a coarse approximation — a production system would use time-bounded
    queries.  For now we fetch enough trades to cover the period for most
    accounts.

    Args:
        period: One of ``"1d"``, ``"7d"``, ``"30d"``, or ``"all"``.

    Returns:
        An integer upper bound on the number of trades to fetch.
    """
    limits: dict[PnLPeriod, int] = {
        "1d": 500,
        "7d": 2000,
        "30d": 5000,
        "all": 10000,
    }
    return limits.get(period, 10000)


# ---------------------------------------------------------------------------
# POST /api/v1/account/reset — reset account
# ---------------------------------------------------------------------------


@router.post(
    "/reset",
    response_model=ResetResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset account",
    description=(
        "Destructively reset the account: wipe all balances and positions, "
        "close the current trading session, and start fresh with the original "
        "starting balance.  The ``confirm`` flag must be ``true`` in the request body."
    ),
)
async def reset_account(
    body: ResetRequest,
    account: CurrentAccountDep,
    account_service: AccountServiceDep,
    tracker: PortfolioTrackerDep,
    db: DbSessionDep,
) -> ResetResponse:
    """Reset the authenticated account to a clean starting state.

    Steps:
    1. Validate that ``confirm`` is ``True``.
    2. Capture the current portfolio equity snapshot for the
       ``previous_session`` summary (best-effort; does not fail the reset).
    3. Delegate to :meth:`~src.accounts.service.AccountService.reset_account`
       which atomically closes the session, wipes balances, and opens a new
       session.
    4. Return a :class:`~src.api.schemas.account.ResetResponse` summarising
       what was reset and the new session details.

    Args:
        body:            Validated request body containing the ``confirm`` flag.
        account:         Injected authenticated account.
        account_service: Injected :class:`~src.accounts.service.AccountService`.
        tracker:         Injected :class:`~src.portfolio.tracker.PortfolioTracker`
                         (pre-reset equity snapshot).

    Returns:
        :class:`~src.api.schemas.account.ResetResponse` with summaries of the
        closed session and the new session.

    Raises:
        :exc:`~src.utils.exceptions.InputValidationError`: If ``confirm`` is
            ``False`` (HTTP 400).
        :exc:`~src.utils.exceptions.AccountSuspendedError`: If the account
            is suspended (HTTP 403).
        :exc:`~src.utils.exceptions.AccountNotFoundError`: If the account
            no longer exists (HTTP 404).
        :exc:`~src.utils.exceptions.DatabaseError`: On an unexpected DB
            failure (HTTP 500).

    Example::

        POST /api/v1/account/reset
        {"confirm": true}
        →  HTTP 200
        {
          "message": "Account reset successful",
          "previous_session": {"ending_equity": "12458.30", ...},
          "new_session": {"starting_balance": "10000.00", ...}
        }
    """
    if not body.confirm:
        raise InputValidationError(
            "Account reset requires confirm=true in the request body.",
            field="confirm",
        )

    # Snapshot pre-reset equity (best-effort; do not fail the reset if Redis is down).
    pre_reset_equity = Decimal(str(account.starting_balance))
    pre_reset_pnl = Decimal("0")
    pre_reset_session_id: UUID | None = None

    try:
        summary = await tracker.get_portfolio(account.id)
        pre_reset_equity = summary.total_equity
        pre_reset_pnl = summary.total_pnl
    except Exception:
        logger.warning(
            "account.reset.pre_snapshot_failed",
            extra={"account_id": str(account.id)},
        )

    # Determine the active session ID before reset.
    try:
        active_session = await _get_active_session(account.id, db)
        if active_session is not None:
            pre_reset_session_id = active_session.id
            started_at = active_session.started_at
        else:
            pre_reset_session_id = account.id
            started_at = account.created_at
    except Exception:
        pre_reset_session_id = account.id
        started_at = account.created_at

    # Calculate previous session duration in days.
    duration_days = max(
        0,
        (
            datetime.now(tz=UTC) - started_at.replace(tzinfo=UTC)
            if started_at.tzinfo is None
            else datetime.now(tz=UTC) - started_at
        ).days,
    )

    # Determine new starting balance (original or override from request).
    new_balance = body.new_starting_balance or Decimal(str(account.starting_balance))

    # Execute the reset — this is the atomic DB operation.
    new_session = await account_service.reset_account(account.id)

    logger.info(
        "account.reset.success",
        extra={
            "account_id": str(account.id),
            "new_session_id": str(new_session.id),
            "new_starting_balance": str(new_balance),
            "previous_equity": str(pre_reset_equity),
        },
    )

    return ResetResponse(
        message="Account reset successful",
        previous_session=PreviousSessionSummary(
            session_id=pre_reset_session_id or account.id,
            ending_equity=pre_reset_equity,
            total_pnl=pre_reset_pnl,
            duration_days=duration_days,
        ),
        new_session=NewSessionSummary(
            session_id=new_session.id,
            starting_balance=Decimal(str(new_session.starting_balance)),
            started_at=new_session.started_at,
        ),
    )
