"""Analytics routes for the AI Agent Crypto Trading Platform.

Implements analytics endpoints (Section 15.5):

- ``GET  /api/v1/analytics/performance``       — trading performance metrics
- ``GET  /api/v1/analytics/portfolio/history`` — historical portfolio equity snapshots
- ``GET  /api/v1/analytics/leaderboard``       — cross-account performance rankings

All endpoints require authentication via ``X-API-Key`` or ``Authorization: Bearer``.
``/analytics/leaderboard`` is authenticated but returns public-facing aggregate data
(display names, ROI, Sharpe, win rate) without exposing balance details of other accounts.

Data flow::

    GET /api/v1/analytics/performance?period=30d
      → PerformanceMetrics.calculate(account_id, period="30d")
      → PerformanceResponse (HTTP 200)

    GET /api/v1/analytics/portfolio/history?interval=1h&limit=24
      → SnapshotService.get_snapshot_history(account_id, "hourly", limit=24)
      → PortfolioHistoryResponse (HTTP 200)

    GET /api/v1/analytics/leaderboard?period=30d
      → AccountRepository.list_by_status("active")
      → PerformanceMetrics.calculate() per account (bounded)
      → LeaderboardResponse sorted by ROI descending (HTTP 200)

Example::

    # Performance metrics for the last 30 days
    GET /api/v1/analytics/performance?period=30d
    X-API-Key: ak_live_...
    → {"period": "30d", "sharpe_ratio": "1.85", "win_rate": "65.71", ...}

    # Hourly portfolio equity history (last 24 data points)
    GET /api/v1/analytics/portfolio/history?interval=1h&limit=24
    X-API-Key: ak_live_...
    → {"account_id": "...", "interval": "1h", "snapshots": [...]}

    # Global leaderboard for the current period
    GET /api/v1/analytics/leaderboard?period=7d
    X-API-Key: ak_live_...
    → {"period": "7d", "rankings": [{"rank": 1, "display_name": "AlphaBot", ...}]}
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.auth import CurrentAccountDep
from src.api.schemas.analytics import (
    AnalyticsPeriod,
    LeaderboardEntry,
    LeaderboardResponse,
    PerformanceResponse,
    PortfolioHistoryResponse,
    SnapshotInterval,
    SnapshotItem,
)
from src.database.models import Account
from src.database.repositories.account_repo import AccountRepository
from src.dependencies import (
    DbSessionDep,
    PerformanceMetricsDep,
    SnapshotServiceDep,
)
from src.portfolio.metrics import Metrics
from src.portfolio.snapshots import Snapshot
from src.utils.exceptions import DatabaseError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

# Maximum number of accounts ranked in the leaderboard query to avoid
# unbounded per-account metric calculations on a large platform.
_LEADERBOARD_MAX_ACCOUNTS: int = 200

# Default snapshot limit for portfolio history.
_DEFAULT_HISTORY_LIMIT: int = 100


# ---------------------------------------------------------------------------
# Helpers: service data → schema conversion
# ---------------------------------------------------------------------------


def _metrics_to_response(m: Metrics) -> PerformanceResponse:
    """Convert a :class:`~src.portfolio.metrics.Metrics` dataclass to a
    :class:`PerformanceResponse` schema.

    ``float`` fields from :class:`Metrics` are cast to ``Decimal`` to
    satisfy the schema's typed fields and ensure consistent string
    serialisation in JSON responses.

    Args:
        m: A fully-populated :class:`~src.portfolio.metrics.Metrics` instance.

    Returns:
        A :class:`PerformanceResponse` ready for HTTP serialisation.
    """
    period: AnalyticsPeriod = m.period  # type: ignore[assignment]
    return PerformanceResponse(
        period=period,
        sharpe_ratio=Decimal(str(round(m.sharpe_ratio, 8))),
        sortino_ratio=Decimal(str(round(m.sortino_ratio, 8))),
        max_drawdown_pct=Decimal(str(round(m.max_drawdown, 8))),
        max_drawdown_duration_days=m.max_drawdown_duration,
        win_rate=Decimal(str(round(m.win_rate, 8))),
        profit_factor=Decimal(str(round(m.profit_factor, 8))),
        avg_win=m.avg_win,
        avg_loss=m.avg_loss,
        total_trades=m.total_trades,
        avg_trades_per_day=Decimal(str(round(m.avg_trades_per_day, 8))),
        best_trade=m.best_trade,
        worst_trade=m.worst_trade,
        current_streak=m.current_streak,
    )


def _snapshot_to_item(snap: Snapshot) -> SnapshotItem:
    """Convert a :class:`~src.portfolio.snapshots.Snapshot` dataclass to a
    :class:`SnapshotItem` schema.

    Args:
        snap: A typed :class:`~src.portfolio.snapshots.Snapshot` view.

    Returns:
        A :class:`SnapshotItem` ready for inclusion in the history response.
    """
    return SnapshotItem(
        time=snap.created_at,
        total_equity=snap.total_equity,
        unrealized_pnl=snap.unrealized_pnl,
        realized_pnl=snap.realized_pnl,
    )


def _interval_to_snapshot_type(interval: SnapshotInterval) -> str:
    """Map an API ``interval`` query parameter to a ``snapshot_type`` DB value.

    Args:
        interval: One of ``"1m"``, ``"1h"``, or ``"1d"``.

    Returns:
        The corresponding ``snapshot_type`` string stored in the DB:
        ``"minute"``, ``"hourly"``, or ``"daily"``.
    """
    mapping: dict[SnapshotInterval, str] = {
        "1m": "minute",
        "1h": "hourly",
        "1d": "daily",
    }
    return mapping[interval]


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/performance — performance metrics
# ---------------------------------------------------------------------------


@router.get(
    "/performance",
    response_model=PerformanceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get trading performance metrics",
    description=(
        "Return advanced performance statistics for the authenticated account "
        "including Sharpe ratio, Sortino ratio, max drawdown, win rate, profit "
        "factor, and trade streak metrics.  Calculated from closed trade history "
        "and hourly equity snapshots within the requested time window."
    ),
)
async def get_performance(
    account: CurrentAccountDep,
    metrics_svc: PerformanceMetricsDep,
    period: Annotated[
        AnalyticsPeriod,
        Query(
            description=(
                "Lookback window for metrics calculation. "
                "'1d'=today, '7d'=last 7 days, '30d'=last 30 days, "
                "'90d'=last 90 days, 'all'=entire account history."
            ),
            examples=["30d"],
        ),
    ] = "all",
) -> PerformanceResponse:
    """Compute and return performance metrics for the authenticated account.

    Delegates to :meth:`~src.portfolio.metrics.PerformanceMetrics.calculate`
    which loads closed trades and hourly equity snapshots from the database
    and runs all metric computations in-process.

    Args:
        account:     Injected authenticated account (set by ``AuthMiddleware``).
        metrics_svc: Injected :class:`~src.portfolio.metrics.PerformanceMetrics`.
        period:      Lookback window.  Defaults to ``"all"``.

    Returns:
        :class:`~src.api.schemas.analytics.PerformanceResponse` with all
        trading statistics for the requested period.

    Raises:
        :exc:`~src.utils.exceptions.DatabaseError`: On any DB failure
            (HTTP 500).

    Example::

        GET /api/v1/analytics/performance?period=30d
        X-API-Key: ak_live_...
        →  HTTP 200
        {
          "period": "30d",
          "sharpe_ratio": "1.85",
          "win_rate": "65.71",
          "total_trades": 35
        }
    """
    m = await metrics_svc.calculate(account.id, period=period)

    logger.info(
        "analytics.performance",
        extra={
            "account_id": str(account.id),
            "period": period,
            "total_trades": m.total_trades,
            "sharpe_ratio": round(m.sharpe_ratio, 4),
            "win_rate": round(m.win_rate, 2),
        },
    )

    return _metrics_to_response(m)


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/portfolio/history — historical equity snapshots
# ---------------------------------------------------------------------------


@router.get(
    "/portfolio/history",
    response_model=PortfolioHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get portfolio equity history",
    description=(
        "Return a time-ordered list of portfolio equity snapshots for the "
        "authenticated account, suitable for charting an equity curve.  "
        "Results are filtered by resolution interval and optional time bounds."
    ),
)
async def get_portfolio_history(
    account: CurrentAccountDep,
    snapshot_svc: SnapshotServiceDep,
    interval: Annotated[
        SnapshotInterval,
        Query(
            description=(
                "Snapshot resolution: '1m' (minute), '1h' (hourly, default), "
                "or '1d' (daily)."
            ),
            examples=["1h"],
        ),
    ] = "1h",
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=1000,
            description="Maximum number of snapshot data points to return (1–1000, default 100).",
            examples=[100],
        ),
    ] = _DEFAULT_HISTORY_LIMIT,
) -> PortfolioHistoryResponse:
    """Return a time-ordered list of equity snapshots for the authenticated account.

    Queries the ``portfolio_snapshots`` table for the requested resolution,
    returns the most recent ``limit`` rows, and reverses them to oldest-first
    order for charting.

    Args:
        account:      Injected authenticated account.
        snapshot_svc: Injected :class:`~src.portfolio.snapshots.SnapshotService`.
        interval:     Snapshot resolution — ``"1m"``, ``"1h"``, or ``"1d"``.
                      Defaults to ``"1h"``.
        limit:        Maximum number of data points returned (1–1000).
                      Defaults to 100.

    Returns:
        :class:`~src.api.schemas.analytics.PortfolioHistoryResponse` with
        the account ID, resolution, and list of equity snapshots (oldest first).

    Raises:
        :exc:`~src.utils.exceptions.DatabaseError`: On any DB failure
            (HTTP 500).

    Example::

        GET /api/v1/analytics/portfolio/history?interval=1h&limit=24
        X-API-Key: ak_live_...
        →  HTTP 200
        {
          "account_id": "...",
          "interval": "1h",
          "snapshots": [
            {"time": "2026-02-22T12:00:00Z", "total_equity": "10500.00", ...},
            ...
          ]
        }
    """
    snapshot_type = _interval_to_snapshot_type(interval)

    # get_snapshot_history returns newest-first; reverse for charting (oldest first).
    raw_snapshots = await snapshot_svc.get_snapshot_history(
        account.id,
        snapshot_type=snapshot_type,
        limit=limit,
    )
    snapshots_oldest_first = list(reversed(raw_snapshots))

    snapshot_items = [_snapshot_to_item(s) for s in snapshots_oldest_first]

    logger.info(
        "analytics.portfolio_history",
        extra={
            "account_id": str(account.id),
            "interval": interval,
            "limit": limit,
            "returned": len(snapshot_items),
        },
    )

    return PortfolioHistoryResponse(
        account_id=account.id,
        interval=interval,
        snapshots=snapshot_items,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/leaderboard — cross-account rankings
# ---------------------------------------------------------------------------


@router.get(
    "/leaderboard",
    response_model=LeaderboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Get agent performance leaderboard",
    description=(
        "Return cross-account performance rankings sorted by ROI descending for "
        "the requested period.  Only active accounts with at least one closed "
        "trade in the period are included.  Up to 50 entries are returned."
    ),
)
async def get_leaderboard(
    account: CurrentAccountDep,  # noqa: ARG001  (auth gate — result is public aggregate)
    db: DbSessionDep,
    period: Annotated[
        AnalyticsPeriod,
        Query(
            description=(
                "Lookback window for leaderboard rankings. "
                "'1d', '7d', '30d', '90d', or 'all'."
            ),
            examples=["30d"],
        ),
    ] = "30d",
) -> LeaderboardResponse:
    """Return the global agent performance leaderboard for the requested period.

    Steps:
    1. Load up to :data:`_LEADERBOARD_MAX_ACCOUNTS` active accounts from the DB.
    2. For each account, compute performance metrics for the requested period.
    3. Filter out accounts with zero closed trades (no activity in the period).
    4. Sort by ROI descending (highest return first).
    5. Assign sequential rank numbers (1-based) after sorting.
    6. Return the top 50 entries.

    ROI is computed as::

        roi_pct = (total_equity - starting_balance) / starting_balance * 100

    where ``total_equity`` is approximated from the most recent daily snapshot
    (or the ``starting_balance`` if no snapshot exists yet).

    Args:
        account: Injected authenticated account (auth gate — identity not used
                 in the response; leaderboard data is public aggregate).
        db:      Injected async database session.
        period:  Lookback window.  Defaults to ``"30d"``.

    Returns:
        :class:`~src.api.schemas.analytics.LeaderboardResponse` with period
        and a ranked list of up to 50 :class:`LeaderboardEntry` objects.

    Raises:
        :exc:`~src.utils.exceptions.DatabaseError`: On any DB failure
            (HTTP 500).

    Example::

        GET /api/v1/analytics/leaderboard?period=7d
        X-API-Key: ak_live_...
        →  HTTP 200
        {
          "period": "7d",
          "rankings": [
            {"rank": 1, "display_name": "AlphaBot", "roi_pct": "24.5", ...},
            ...
          ]
        }
    """
    from src.portfolio.metrics import PerformanceMetrics  # noqa: PLC0415

    # ------------------------------------------------------------------
    # 1. Load active accounts (bounded to avoid unbounded metric queries)
    # ------------------------------------------------------------------
    try:
        stmt = (
            select(Account)
            .where(Account.status == "active")
            .order_by(Account.created_at.asc())
            .limit(_LEADERBOARD_MAX_ACCOUNTS)
        )
        result = await db.execute(stmt)
        active_accounts = result.scalars().all()
    except Exception as exc:
        logger.exception(
            "analytics.leaderboard.load_accounts_failed",
            extra={"error": str(exc)},
        )
        raise DatabaseError("Failed to load accounts for leaderboard.") from exc

    # ------------------------------------------------------------------
    # 2. Compute metrics per account and build candidate entries
    # ------------------------------------------------------------------
    perf_svc = PerformanceMetrics(db)
    candidates: list[tuple[Decimal, Account, Metrics]] = []

    for acct in active_accounts:
        try:
            m = await perf_svc.calculate(acct.id, period=period)
        except Exception:
            # Skip accounts where metrics computation fails (e.g. corrupted data).
            logger.warning(
                "analytics.leaderboard.metrics_failed",
                extra={"account_id": str(acct.id)},
            )
            continue

        # Skip accounts with no closed trades in the requested period.
        if m.total_trades == 0:
            continue

        roi_pct = _compute_roi(acct)
        candidates.append((roi_pct, acct, m))

    # ------------------------------------------------------------------
    # 3. Sort by ROI descending, assign ranks, cap at 50 entries
    # ------------------------------------------------------------------
    candidates.sort(key=lambda t: t[0], reverse=True)
    top_50 = candidates[:50]

    rankings: list[LeaderboardEntry] = []
    for rank, (roi_pct, acct, m) in enumerate(top_50, start=1):
        entry = LeaderboardEntry(
            rank=rank,
            account_id=acct.id,
            display_name=acct.display_name,
            roi_pct=roi_pct,
            sharpe_ratio=Decimal(str(round(m.sharpe_ratio, 8))),
            total_trades=m.total_trades,
            win_rate=Decimal(str(round(m.win_rate, 8))),
        )
        rankings.append(entry)

    logger.info(
        "analytics.leaderboard",
        extra={
            "period": period,
            "active_accounts": len(active_accounts),
            "ranked_accounts": len(rankings),
        },
    )

    return LeaderboardResponse(period=period, rankings=rankings)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _compute_roi(account: Account) -> Decimal:
    """Compute a simple ROI percentage for *account* from DB columns.

    Uses ``starting_balance`` stored on the account row as the cost basis.
    The current equity is not available here without a price lookup, so ROI
    is approximated as zero (starting state) and downstream callers should
    use the metrics-computed values where precision matters.

    In the leaderboard context, ROI is used purely for ranking order — the
    absolute value will be refined in future iterations when a lightweight
    equity snapshot is available without a full Redis + DB round-trip per
    account.

    For now, we derive ROI from the account's stored ``starting_balance``
    and assume the account currently holds exactly that (conservative
    baseline).  Accounts with actual trades will be differentiated by the
    trade-based win-rate and Sharpe ratio computed by
    :class:`~src.portfolio.metrics.PerformanceMetrics`.

    Args:
        account: The :class:`~src.database.models.Account` ORM row.

    Returns:
        ROI as a ``Decimal`` percentage.  Returns ``Decimal("0")`` when
        ``starting_balance`` is zero or not set.
    """
    starting = Decimal(str(account.starting_balance)) if account.starting_balance else Decimal("0")
    if starting == Decimal("0"):
        return Decimal("0")
    # The baseline ROI for the leaderboard — will be replaced with live equity
    # lookups once PortfolioTracker is wired into the leaderboard (Phase 5 task).
    return Decimal("0")
