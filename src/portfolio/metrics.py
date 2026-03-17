"""Portfolio Performance Metrics — Component 6.

Calculates advanced trading performance metrics from an account's trade history
and portfolio snapshot series.  All computations are pure (no I/O) once the raw
data has been loaded asynchronously by :class:`PerformanceMetrics`.

Classes
-------
Metrics
    Frozen dataclass carrying every computed metric for a given period.

PerformanceMetrics
    Async service that fetches raw trade and snapshot data, then delegates to
    private pure helpers to produce a :class:`Metrics` result.

Dependency direction::

    API routes / SnapshotService → PerformanceMetrics
        → TradeRepository  (trade history for win/loss stats)
        → SnapshotRepository (equity curve for drawdown / Sharpe)
        → AsyncSession

All methods accept an injected ``AsyncSession`` so they participate in the
caller's unit of work without issuing extra commits.

Periods: ``"1d"``, ``"7d"``, ``"30d"``, ``"90d"``, ``"all"``

Example::

    async with session_factory() as session:
        svc = PerformanceMetrics(session)
        m = await svc.calculate(account_id, period="30d")
        print(f"Sharpe: {m.sharpe_ratio:.4f}")
        print(f"Max drawdown: {m.max_drawdown:.2f}%")
        print(f"Win rate: {m.win_rate:.1f}%")
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import logging
import math
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import PortfolioSnapshot, Trade
from src.database.repositories.snapshot_repo import SnapshotRepository
from src.database.repositories.trade_repo import TradeRepository
from src.utils.exceptions import DatabaseError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Risk-free rate used for Sharpe / Sortino (annualised, e.g. 4%).
_RISK_FREE_RATE: float = 0.04

#: Trading days assumed per year for annualisation.
_TRADING_DAYS_PER_YEAR: float = 365.0

#: Snapshot type used to build the equity curve.
_EQUITY_SNAPSHOT_TYPE: str = "hourly"

#: Maximum snapshots to load when period is "all".
_MAX_SNAPSHOTS: int = 5_000

#: Period → lookback in days mapping (None = "all").
_PERIOD_DAYS: dict[str, int | None] = {
    "1d": 1,
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "all": None,
}

_ZERO = Decimal("0")


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class Metrics:
    """All performance metrics for one account over one period.

    All ratio / percentage fields are ``float`` so they integrate cleanly with
    JSON serialisation.  Monetary fields (``avg_win``, ``avg_loss``, etc.) are
    ``Decimal`` to preserve the platform's arithmetic precision.

    Attributes:
        period:                 The period label used for the calculation,
                                e.g. ``"30d"`` or ``"all"``.
        sharpe_ratio:           Annualised Sharpe ratio (risk-adjusted return).
                                ``0.0`` when there is insufficient data.
        sortino_ratio:          Annualised Sortino ratio (downside risk-adjusted
                                return).  ``0.0`` when there are no losing
                                periods.
        max_drawdown:           Largest peak-to-trough equity decline as a
                                percentage (always ``>= 0``).
        max_drawdown_duration:  Number of consecutive hourly snapshots spent in
                                the worst drawdown.
        win_rate:               Percentage of realised trades with
                                ``realized_pnl > 0``.
        profit_factor:          Gross profit divided by gross loss (absolute
                                value).  ``0.0`` when there are no losing
                                trades.
        avg_win:                Mean realized PnL of winning trades.
        avg_loss:               Mean realized PnL of losing trades (always
                                ``<= 0``).
        total_trades:           Number of closed trades (``realized_pnl`` is
                                not NULL) in the period.
        avg_trades_per_day:     ``total_trades / days_elapsed`` (float).
        best_trade:             Highest single realized PnL.
        worst_trade:            Lowest single realized PnL (most negative).
        current_streak:         Positive integer = current consecutive win
                                count; negative = current consecutive loss
                                count; ``0`` = no trades.
    """

    period: str
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_duration: int
    win_rate: float
    profit_factor: float
    avg_win: Decimal
    avg_loss: Decimal
    total_trades: int
    avg_trades_per_day: float
    best_trade: Decimal
    worst_trade: Decimal
    current_streak: int

    @classmethod
    def empty(cls, period: str) -> Metrics:
        """Return a zeroed-out :class:`Metrics` for the given *period*.

        Used when there are no trades or no snapshots to compute from.

        Args:
            period: Period label (e.g. ``"30d"``).

        Returns:
            A :class:`Metrics` instance with all numeric fields set to zero.

        Example::

            m = Metrics.empty("all")
            assert m.sharpe_ratio == 0.0
        """
        return cls(
            period=period,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            max_drawdown=0.0,
            max_drawdown_duration=0,
            win_rate=0.0,
            profit_factor=0.0,
            avg_win=_ZERO,
            avg_loss=_ZERO,
            total_trades=0,
            avg_trades_per_day=0.0,
            best_trade=_ZERO,
            worst_trade=_ZERO,
            current_streak=0,
        )


# ---------------------------------------------------------------------------
# PerformanceMetrics service
# ---------------------------------------------------------------------------


class PerformanceMetrics:
    """Async service that computes performance metrics for an account.

    Fetches closed trade rows and equity-curve snapshots from the database,
    then delegates to private pure helpers to produce a :class:`Metrics`
    result.  All heavy computation runs in-process (no additional I/O after
    the initial data load).

    Args:
        session: An open :class:`~sqlalchemy.ext.asyncio.AsyncSession`.

    Example::

        svc = PerformanceMetrics(session)
        metrics = await svc.calculate(account_id, period="30d")
        print(metrics.sharpe_ratio)
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._trade_repo = TradeRepository(session)
        self._snapshot_repo = SnapshotRepository(session)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def calculate(
        self,
        account_id: UUID,
        period: str = "all",
        *,
        agent_id: UUID | None = None,
    ) -> Metrics:
        """Compute all performance metrics for *account_id* over *period*.

        Loads the minimum necessary data from the database (closed trades +
        hourly equity snapshots), then runs all metric computations in-process.

        Supported period values: ``"1d"``, ``"7d"``, ``"30d"``, ``"90d"``,
        ``"all"``.  Unrecognised values fall back to ``"all"``.

        Args:
            account_id: UUID of the account to analyse.
            period:     Lookback window label (default ``"all"``).

        Returns:
            A fully-populated :class:`Metrics` dataclass.

        Raises:
            DatabaseError: On any SQLAlchemy / database error while loading
                trade or snapshot data.

        Example::

            m = await svc.calculate(account_id, period="7d")
            print(f"Win rate: {m.win_rate:.1f}%")
            print(f"Profit factor: {m.profit_factor:.2f}")
        """
        if period not in _PERIOD_DAYS:
            logger.warning(
                "metrics.calculate.unknown_period",
                extra={"period": period, "account_id": str(account_id)},
            )
            period = "all"

        since = _period_to_since(period)

        trades = await self._load_closed_trades(account_id, since=since, agent_id=agent_id)
        snapshots = await self._load_snapshots(account_id, since=since, agent_id=agent_id)

        if not trades and not snapshots:
            logger.debug(
                "metrics.calculate.no_data",
                extra={"account_id": str(account_id), "period": period},
            )
            return Metrics.empty(period)

        pnl_values = _extract_pnl(trades)
        equity_series = _extract_equity(snapshots)

        sharpe = _sharpe_ratio(equity_series)
        sortino = _sortino_ratio(equity_series)
        max_dd, max_dd_dur = _max_drawdown(equity_series)
        win_rate = _win_rate(pnl_values)
        profit_factor = _profit_factor(pnl_values)
        avg_win, avg_loss = _avg_win_loss(pnl_values)
        total_trades = len(pnl_values)
        avg_trades_per_day = _avg_trades_per_day(total_trades, since)
        best_trade = max(pnl_values, default=_ZERO)
        worst_trade = min(pnl_values, default=_ZERO)
        streak = _current_streak(trades)

        logger.debug(
            "metrics.calculate.done",
            extra={
                "account_id": str(account_id),
                "period": period,
                "total_trades": total_trades,
                "sharpe": round(sharpe, 4),
                "max_drawdown": round(max_dd, 4),
                "win_rate": round(win_rate, 2),
            },
        )
        return Metrics(
            period=period,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_dd,
            max_drawdown_duration=max_dd_dur,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            total_trades=total_trades,
            avg_trades_per_day=avg_trades_per_day,
            best_trade=best_trade,
            worst_trade=worst_trade,
            current_streak=streak,
        )

    # ------------------------------------------------------------------
    # Private data-loading helpers
    # ------------------------------------------------------------------

    async def _load_closed_trades(
        self,
        account_id: UUID,
        *,
        since: datetime | None,
        agent_id: UUID | None = None,
    ) -> Sequence[Trade]:
        """Load all closed-trade rows (realized_pnl IS NOT NULL) for the period.

        Args:
            account_id: Account to load trades for.
            since:      Earliest ``created_at`` boundary (UTC).  ``None``
                        loads the full history.

        Returns:
            Sequence of :class:`~src.database.models.Trade` rows ordered
            oldest-first.

        Raises:
            DatabaseError: On any SQLAlchemy failure.
        """
        from sqlalchemy import select

        from src.database.models import Trade as TradeModel

        try:
            filters = [
                TradeModel.account_id == account_id,
                TradeModel.realized_pnl.is_not(None),
            ]
            if agent_id is not None:
                filters.append(TradeModel.agent_id == agent_id)
            stmt = (
                select(TradeModel)
                .where(*filters)
                .order_by(TradeModel.created_at.asc())
            )
            if since is not None:
                stmt = stmt.where(TradeModel.created_at >= since)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except Exception as exc:
            logger.exception(
                "metrics.load_closed_trades.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError(f"Failed to load trade history for metrics (account '{account_id}').") from exc

    async def _load_snapshots(
        self,
        account_id: UUID,
        *,
        since: datetime | None,
        agent_id: UUID | None = None,
    ) -> Sequence[PortfolioSnapshot]:
        """Load hourly equity snapshots for the equity-curve computation.

        Snapshots are loaded oldest-first so the equity series is already in
        chronological order for the drawdown and return calculations.

        Args:
            account_id: Account to load snapshots for.
            since:      Earliest ``created_at`` boundary (UTC).  ``None``
                        loads up to :data:`_MAX_SNAPSHOTS` rows.

        Returns:
            Sequence of :class:`~src.database.models.PortfolioSnapshot` rows
            ordered oldest-first.

        Raises:
            DatabaseError: On any SQLAlchemy failure.
        """
        from sqlalchemy import select

        try:
            filters = [
                PortfolioSnapshot.account_id == account_id,
                PortfolioSnapshot.snapshot_type == _EQUITY_SNAPSHOT_TYPE,
            ]
            if agent_id is not None:
                filters.append(PortfolioSnapshot.agent_id == agent_id)
            stmt = (
                select(PortfolioSnapshot)
                .where(*filters)
                .order_by(PortfolioSnapshot.created_at.asc())
                .limit(_MAX_SNAPSHOTS)
            )
            if since is not None:
                stmt = stmt.where(PortfolioSnapshot.created_at >= since)
            result = await self._session.execute(stmt)
            return result.scalars().all()
        except Exception as exc:
            logger.exception(
                "metrics.load_snapshots.db_error",
                extra={"account_id": str(account_id), "error": str(exc)},
            )
            raise DatabaseError(f"Failed to load snapshot history for metrics (account '{account_id}').") from exc


# ---------------------------------------------------------------------------
# Pure computation helpers (module-level, no I/O)
# ---------------------------------------------------------------------------


def _period_to_since(period: str) -> datetime | None:
    """Convert a period label to a UTC ``since`` datetime.

    Args:
        period: One of ``"1d"``, ``"7d"``, ``"30d"``, ``"90d"``, ``"all"``.

    Returns:
        A timezone-aware UTC datetime, or ``None`` for ``"all"``.

    Example::

        since = _period_to_since("7d")
        assert since is not None
    """
    days = _PERIOD_DAYS.get(period)
    if days is None:
        return None
    return datetime.now(tz=UTC) - timedelta(days=days)


def _extract_pnl(trades: Sequence[Trade]) -> list[Decimal]:
    """Extract the ``realized_pnl`` from closed-trade rows as ``Decimal`` values.

    Trades with ``NULL`` PnL are silently skipped (they are opening fills
    that never close a position — should not reach this function since we
    filter at query time, but kept as a defensive guard).

    Args:
        trades: Sequence of :class:`~src.database.models.Trade` rows.

    Returns:
        List of ``Decimal`` PnL values, one per closed trade.

    Example::

        pnl = _extract_pnl(trades)
        wins = [p for p in pnl if p > 0]
    """
    result: list[Decimal] = []
    for t in trades:
        if t.realized_pnl is not None:
            result.append(Decimal(str(t.realized_pnl)))
    return result


def _extract_equity(snapshots: Sequence[PortfolioSnapshot]) -> list[float]:
    """Extract ``total_equity`` from snapshot rows as a chronological float series.

    Args:
        snapshots: Sequence of :class:`~src.database.models.PortfolioSnapshot`
                   rows, expected to be ordered oldest-first.

    Returns:
        List of ``float`` equity values in chronological order.

    Example::

        equity = _extract_equity(snapshots)
        peak = max(equity)
    """
    return [float(s.total_equity) for s in snapshots if s.total_equity is not None]


def _period_returns(equity: list[float]) -> list[float]:
    """Compute per-period returns from a chronological equity curve.

    ``r_t = (equity[t] - equity[t-1]) / equity[t-1]``

    Periods where the previous equity is zero are skipped to avoid
    division by zero.

    Args:
        equity: Chronological list of equity values.

    Returns:
        List of per-period fractional returns.

    Example::

        returns = _period_returns([10000.0, 10050.0, 10025.0])
        # → [0.005, -0.0024...]
    """
    if len(equity) < 2:
        return []
    returns: list[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        if prev == 0.0:
            continue
        returns.append((equity[i] - prev) / prev)
    return returns


def _sharpe_ratio(equity: list[float]) -> float:
    """Compute the annualised Sharpe ratio from an equity curve.

    Uses the per-period excess return over the risk-free rate.  Assumes each
    data point is one hour apart (hourly snapshots), so annualisation factor
    is ``sqrt(8760)`` (hours per year).

    Returns ``0.0`` when there are fewer than 2 data points or when the
    standard deviation of returns is zero.

    Args:
        equity: Chronological hourly equity values.

    Returns:
        Annualised Sharpe ratio (float).

    Example::

        s = _sharpe_ratio([10000.0, 10050.0, 10030.0, 10080.0])
    """
    returns = _period_returns(equity)
    if not returns:
        return 0.0

    hourly_rf = _RISK_FREE_RATE / 8760.0
    excess = [r - hourly_rf for r in returns]
    mean_excess = sum(excess) / len(excess)
    std = _std(excess)
    if std == 0.0:
        return 0.0

    annualisation = math.sqrt(8760.0)
    return (mean_excess / std) * annualisation


def _sortino_ratio(equity: list[float]) -> float:
    """Compute the annualised Sortino ratio from an equity curve.

    Identical to :func:`_sharpe_ratio` but uses the downside deviation
    (standard deviation of negative excess returns only) as the risk measure.

    Returns ``0.0`` when there are no downside periods, or fewer than 2
    data points.

    Args:
        equity: Chronological hourly equity values.

    Returns:
        Annualised Sortino ratio (float).

    Example::

        s = _sortino_ratio([10000.0, 10050.0, 9900.0, 10080.0])
    """
    returns = _period_returns(equity)
    if not returns:
        return 0.0

    hourly_rf = _RISK_FREE_RATE / 8760.0
    excess = [r - hourly_rf for r in returns]
    mean_excess = sum(excess) / len(excess)

    downside = [r for r in excess if r < 0.0]
    if not downside:
        return 0.0

    downside_std = _std(downside)
    if downside_std == 0.0:
        return 0.0

    annualisation = math.sqrt(8760.0)
    return (mean_excess / downside_std) * annualisation


def _max_drawdown(equity: list[float]) -> tuple[float, int]:
    """Compute the maximum drawdown percentage and its duration from an equity curve.

    The drawdown at each point is ``(peak - equity) / peak * 100``.  The
    function scans the series once to find both the maximum drawdown value and
    the length (in snapshots) of the worst sustained drawdown window.

    Args:
        equity: Chronological list of equity values.

    Returns:
        Tuple of ``(max_drawdown_pct, duration_in_snapshots)``.  Both values
        are ``0`` when the series is empty or monotonically rising.

    Example::

        dd, dur = _max_drawdown([10000.0, 11000.0, 9000.0, 9500.0, 11000.0])
        # dd ≈ 18.18%, dur = 2
    """
    if not equity:
        return 0.0, 0

    peak = equity[0]
    max_dd = 0.0
    max_dur = 0

    dd_start: int | None = None
    current_dur = 0

    for val in equity:
        if val > peak:
            peak = val
            dd_start = None
            current_dur = 0
        elif peak > 0:
            dd = (peak - val) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
            if dd > 0:
                if dd_start is None:
                    dd_start = 1
                    current_dur = 1
                else:
                    current_dur += 1
                if current_dur > max_dur:
                    max_dur = current_dur
            else:
                dd_start = None
                current_dur = 0

    return max_dd, max_dur


def _win_rate(pnl: list[Decimal]) -> float:
    """Compute the percentage of trades with positive realized PnL.

    Args:
        pnl: List of realized PnL values (one per closed trade).

    Returns:
        Win rate as a percentage (0–100).  ``0.0`` when list is empty.

    Example::

        wr = _win_rate([Decimal("10"), Decimal("-5"), Decimal("7")])
        # → 66.66...
    """
    if not pnl:
        return 0.0
    wins = sum(1 for p in pnl if p > _ZERO)
    return wins / len(pnl) * 100.0


def _profit_factor(pnl: list[Decimal]) -> float:
    """Compute the profit factor: gross profit / gross loss (absolute).

    Args:
        pnl: List of realized PnL values (one per closed trade).

    Returns:
        Profit factor (float).  ``0.0`` when there are no losing trades.
        ``float("inf")`` is clamped to ``0.0`` for clean JSON serialisation.

    Example::

        pf = _profit_factor([Decimal("30"), Decimal("-10"), Decimal("20")])
        # → 5.0  (gross_profit=50, gross_loss=10)
    """
    gross_profit = sum(p for p in pnl if p > _ZERO)
    gross_loss = sum(abs(p) for p in pnl if p < _ZERO)
    if gross_loss == _ZERO:
        return 0.0
    factor = float(gross_profit / gross_loss)
    return factor if math.isfinite(factor) else 0.0


def _avg_win_loss(pnl: list[Decimal]) -> tuple[Decimal, Decimal]:
    """Compute average winning and losing trade sizes.

    Args:
        pnl: List of realized PnL values (one per closed trade).

    Returns:
        Tuple of ``(avg_win, avg_loss)``.  ``avg_win`` is always ``>= 0``.
        ``avg_loss`` is always ``<= 0``.  Both are ``Decimal("0")`` when
        there are no corresponding trades.

    Example::

        avg_w, avg_l = _avg_win_loss([Decimal("10"), Decimal("-5"), Decimal("20")])
        # avg_w = Decimal("15"), avg_l = Decimal("-5")
    """
    wins = [p for p in pnl if p > _ZERO]
    losses = [p for p in pnl if p < _ZERO]
    avg_win = sum(wins, _ZERO) / len(wins) if wins else _ZERO
    avg_loss = sum(losses, _ZERO) / len(losses) if losses else _ZERO
    return avg_win, avg_loss


def _avg_trades_per_day(total_trades: int, since: datetime | None) -> float:
    """Compute average number of trades per calendar day.

    Args:
        total_trades: Number of closed trades in the period.
        since:        Start of the period (UTC), or ``None`` for "all time"
                      (returns ``0.0`` in that case since elapsed days is
                      unknown without the first-trade timestamp).

    Returns:
        Average trades per day (float).  ``0.0`` when ``since`` is ``None``
        or the elapsed time is less than one hour.

    Example::

        avg = _avg_trades_per_day(30, datetime.now(tz=timezone.utc) - timedelta(days=30))
        # → 1.0
    """
    if since is None or total_trades == 0:
        return 0.0
    elapsed = datetime.now(tz=UTC) - since
    days = elapsed.total_seconds() / 86_400.0
    if days < 1 / 24:
        return 0.0
    return total_trades / days


def _current_streak(trades: Sequence[Trade]) -> int:
    """Compute the current consecutive win (+) or loss (-) streak.

    Iterates the trade list in reverse (newest first) and counts consecutive
    winning or losing trades from the most recent fill.

    A trade is a "win" when ``realized_pnl > 0``, a "loss" when
    ``realized_pnl < 0``.  Trades with ``realized_pnl == 0`` break the
    streak.

    Args:
        trades: Sequence of :class:`~src.database.models.Trade` rows, expected
                to be ordered oldest-first (chronological).

    Returns:
        Positive integer = win streak length.
        Negative integer = loss streak length.
        ``0`` when the last trade is break-even or no closed trades exist.

    Example::

        streak = _current_streak(trades)
        if streak > 5:
            print("On a hot streak!")
    """
    closed = [t for t in trades if t.realized_pnl is not None]
    if not closed:
        return 0

    # Walk backwards from the most recent closed trade.
    streak = 0
    direction: int | None = None

    for trade in reversed(closed):
        pnl = Decimal(str(trade.realized_pnl))
        if pnl > _ZERO:
            step = 1
        elif pnl < _ZERO:
            step = -1
        else:
            break

        if direction is None:
            direction = step
        elif step != direction:
            break

        streak += step

    return streak


# ---------------------------------------------------------------------------
# Internal statistics helper
# ---------------------------------------------------------------------------


def _std(values: list[float]) -> float:
    """Compute the population standard deviation of a list of floats.

    Uses the population formula (divide by N) because we are measuring the
    complete sample in the lookback window, not estimating a population
    parameter.

    Args:
        values: List of numeric values.  Must be non-empty.

    Returns:
        Population standard deviation.  ``0.0`` when ``len(values) < 2`` or
        all values are identical.

    Example::

        s = _std([0.01, -0.02, 0.015])
    """
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / n
    return math.sqrt(variance) if variance > 0 else 0.0
