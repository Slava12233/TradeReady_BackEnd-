"""Strategy performance monitoring, degradation detection, and adjustment suggestions.

:class:`StrategyManager` tracks per-strategy trade outcomes in a rolling in-memory
window, persists period summaries to the ``agent_performance`` table via
:class:`~src.database.repositories.agent_performance_repo.AgentPerformanceRepository`,
and produces :class:`~agent.models.ecosystem.DegradationAlert`,
:class:`~agent.models.ecosystem.Adjustment`, and
:class:`~agent.models.ecosystem.StrategyComparison` outputs for the trading loop.

The manager is **stateful** — it accumulates a rolling window of trade records per
strategy in memory.  Each :meth:`record_strategy_result` call appends to the window
(capped at ``window_size`` entries by a deque) so that degradation checks always
reflect the most recent trades without requiring a DB round-trip on every signal.

Architecture::

    record_strategy_result(agent_id, strategy_name, signal, outcome_pnl)
           │
           └── _windows[agent_id][strategy_name].append(TradeRecord)
                   │
                   └── [if window full → persist_period_summary() → agent_performance table]

    detect_degradation(agent_id)
           │
           └── for each strategy window → _compute_metrics() → check thresholds
                   │
                   └── list[DegradationAlert]

    suggest_adjustments(agent_id, strategy_name)
           │
           └── _compute_metrics() → conservative parameter recommendations
                   │
                   └── list[Adjustment]

    compare_strategies(agent_id)
           │
           └── all strategy windows → rank by Sharpe → StrategyComparison

Usage::

    from agent.trading.strategy_manager import StrategyManager

    manager = StrategyManager()

    # Record a trade outcome (outcome_pnl=None until the position closes)
    await manager.record_strategy_result(
        agent_id="uuid-string",
        strategy_name="ensemble_strategy",
        signal=trading_signal,
        outcome_pnl=Decimal("42.50"),
    )

    # Detect degradation across all strategies for this agent
    alerts = await manager.detect_degradation(agent_id="uuid-string")

    # Get performance over the last weekly window
    perfs = await manager.get_performance(agent_id="uuid-string", period="weekly")

    # Compare strategies
    comparison = await manager.compare_strategies(agent_id="uuid-string")
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from agent.models.ecosystem import (
    Adjustment,
    DegradationAlert,
    StrategyComparison,
    StrategyPerformance,
)
from agent.trading.signal_generator import TradingSignal

logger = structlog.get_logger(__name__)

# ── Module-level constants ──────────────────────────────────────────────────────

# Default rolling window depth (number of trades per strategy per agent).
# 50 trades provide a statistically meaningful short-term sample without
# accumulating unbounded memory in long-running sessions.
_DEFAULT_WINDOW_SIZE: int = 50

# Degradation thresholds — these are the break-even levels below which a
# strategy is no longer contributing positively to portfolio performance.
# All are conservative by design: we prefer false negatives over false positives
# (it is better to miss a mild degradation than to disable a healthy strategy).

# Sharpe ratio must stay above this for the strategy to remain "healthy".
# 0.5 is the lower bound of a marginally positive risk-adjusted return.
_SHARPE_WARNING_THRESHOLD: float = 0.5
_SHARPE_CRITICAL_THRESHOLD: float = 0.0

# Win rate below 40 % signals adverse selection or changing market conditions.
_WIN_RATE_WARNING_THRESHOLD: float = 0.40
_WIN_RATE_CRITICAL_THRESHOLD: float = 0.30

# Maximum drawdown thresholds (fraction of equity, e.g. 0.15 = 15 %).
# "warning" fires if drawdown exceeds 15 %; "critical" fires at 25 %.
_MAX_DRAWDOWN_WARNING_THRESHOLD: float = 0.15
_MAX_DRAWDOWN_CRITICAL_THRESHOLD: float = 0.25

# Consecutive loss streak — 5 in a row is unusual (p < 0.03 for a 50 % win
# rate strategy); 8 consecutive losses is near certain-degradation territory.
_CONSECUTIVE_LOSSES_WARNING_THRESHOLD: int = 5
_CONSECUTIVE_LOSSES_CRITICAL_THRESHOLD: int = 8
_CONSECUTIVE_LOSSES_DISABLE_THRESHOLD: int = 12

# Minimum number of trades in the rolling window before degradation checks
# are meaningful.  Below this threshold all checks are skipped to avoid
# false positives from very small samples.
_MIN_TRADES_FOR_DEGRADATION: int = 10

# Period boundaries used when persisting rolling window summaries.
_PERIOD_WINDOW_DAYS: dict[str, int] = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}


# ── Internal data structures ────────────────────────────────────────────────────


class _TradeRecord:
    """Lightweight in-memory record of one strategy trade outcome.

    Not persisted directly — the rolling window is summarised to
    ``AgentPerformance`` rows at period boundaries.

    Args:
        strategy_name: Strategy that generated the signal.
        signal: The :class:`~agent.trading.signal_generator.TradingSignal`
            that was acted on.
        outcome_pnl: Realised PnL in USDT once the position closes.
            ``None`` while the position is still open.
        recorded_at: UTC timestamp when the record was created.
    """

    __slots__ = ("strategy_name", "signal", "outcome_pnl", "recorded_at")

    def __init__(
        self,
        strategy_name: str,
        signal: TradingSignal,
        outcome_pnl: Decimal | None,
        recorded_at: datetime,
    ) -> None:
        self.strategy_name = strategy_name
        self.signal = signal
        self.outcome_pnl = outcome_pnl
        self.recorded_at = recorded_at


class _StrategyMetrics:
    """Computed performance metrics for one strategy window.

    All ratio fields are ``float`` (dimensionless); monetary PnL is
    ``Decimal`` to avoid precision loss.

    Args:
        total_signals: Total signals recorded in the window (includes HOLDs).
        trades_taken: Signals that resulted in a non-HOLD order.
        win_rate: Fraction of completed trades that were profitable.
        sharpe_ratio: Annualised Sharpe ratio estimated from trade PnL distribution.
        max_drawdown: Peak-to-trough equity decline as a fraction.
        total_pnl: Sum of all realised PnL in the window.
        avg_pnl_per_trade: Mean PnL per completed trade.
        consecutive_losses: Current trailing consecutive-loss streak.
    """

    __slots__ = (
        "total_signals",
        "trades_taken",
        "win_rate",
        "sharpe_ratio",
        "max_drawdown",
        "total_pnl",
        "avg_pnl_per_trade",
        "consecutive_losses",
    )

    def __init__(
        self,
        total_signals: int,
        trades_taken: int,
        win_rate: float,
        sharpe_ratio: float,
        max_drawdown: float,
        total_pnl: Decimal,
        avg_pnl_per_trade: Decimal,
        consecutive_losses: int,
    ) -> None:
        self.total_signals = total_signals
        self.trades_taken = trades_taken
        self.win_rate = win_rate
        self.sharpe_ratio = sharpe_ratio
        self.max_drawdown = max_drawdown
        self.total_pnl = total_pnl
        self.avg_pnl_per_trade = avg_pnl_per_trade
        self.consecutive_losses = consecutive_losses


# ── StrategyManager ────────────────────────────────────────────────────────────


class StrategyManager:
    """Monitors per-strategy performance and detects degradation.

    Maintains an in-memory rolling window of trade records per
    (agent_id, strategy_name) pair.  The window is a bounded
    :class:`collections.deque` so the memory footprint is predictable
    regardless of how long the agent runs.

    Period summaries are optionally persisted to ``agent_performance``
    via the provided session factory.  The session factory is lazy — it
    is only called when :meth:`persist_period_summary` is invoked, not
    at construction.  Passing ``session_factory=None`` (the default)
    disables persistence silently so the manager can be used in tests
    and lightweight scripts without a database connection.

    Args:
        window_size: Maximum number of trade records kept per strategy per
            agent.  Older records are evicted when the window is full.
            Default: ``50``.
        session_factory: Optional async callable that returns an open
            :class:`~sqlalchemy.ext.asyncio.AsyncSession` (e.g.,
            ``async_sessionmaker`` instance from
            ``src.database.session.get_session_factory()``).  When
            ``None``, persistence is skipped.
        sharpe_warning_threshold: Sharpe ratio below which a
            ``"warning"`` degradation alert is generated.  Default: 0.5.
        sharpe_critical_threshold: Sharpe ratio below which a
            ``"critical"`` alert is generated.  Default: 0.0.
        win_rate_warning_threshold: Win rate below which a ``"warning"``
            alert is generated.  Default: 0.40.
        win_rate_critical_threshold: Win rate below which a ``"critical"``
            alert is generated.  Default: 0.30.
        max_drawdown_warning_threshold: Max drawdown above which a
            ``"warning"`` alert is generated (fraction, e.g. ``0.15``).
            Default: 0.15.
        max_drawdown_critical_threshold: Max drawdown above which a
            ``"critical"`` alert is generated.  Default: 0.25.
        consecutive_losses_warning_threshold: Consecutive-loss count
            above which a ``"warning"`` is generated.  Default: 5.
        consecutive_losses_critical_threshold: Count above which a
            ``"critical"`` is generated.  Default: 8.
        consecutive_losses_disable_threshold: Count above which a
            ``"disable"`` is generated.  Default: 12.
        min_trades_for_degradation: Minimum completed trades required
            before degradation checks are meaningful.  Default: 10.

    Example::

        manager = StrategyManager(window_size=50)
        await manager.record_strategy_result(
            agent_id="agent-uuid",
            strategy_name="ensemble_strategy",
            signal=signal,
            outcome_pnl=Decimal("42.50"),
        )
        alerts = await manager.detect_degradation(agent_id="agent-uuid")
    """

    def __init__(
        self,
        *,
        window_size: int = _DEFAULT_WINDOW_SIZE,
        session_factory: Any = None,  # noqa: ANN401
        sharpe_warning_threshold: float = _SHARPE_WARNING_THRESHOLD,
        sharpe_critical_threshold: float = _SHARPE_CRITICAL_THRESHOLD,
        win_rate_warning_threshold: float = _WIN_RATE_WARNING_THRESHOLD,
        win_rate_critical_threshold: float = _WIN_RATE_CRITICAL_THRESHOLD,
        max_drawdown_warning_threshold: float = _MAX_DRAWDOWN_WARNING_THRESHOLD,
        max_drawdown_critical_threshold: float = _MAX_DRAWDOWN_CRITICAL_THRESHOLD,
        consecutive_losses_warning_threshold: int = _CONSECUTIVE_LOSSES_WARNING_THRESHOLD,
        consecutive_losses_critical_threshold: int = _CONSECUTIVE_LOSSES_CRITICAL_THRESHOLD,
        consecutive_losses_disable_threshold: int = _CONSECUTIVE_LOSSES_DISABLE_THRESHOLD,
        min_trades_for_degradation: int = _MIN_TRADES_FOR_DEGRADATION,
    ) -> None:
        # Validate window_size is a positive integer.
        if window_size < 1:
            raise ValueError(f"window_size must be >= 1, got {window_size}.")

        self._window_size = window_size
        self._session_factory = session_factory

        # Degradation thresholds — stored as instance attributes so callers
        # can construct custom instances with domain-specific thresholds.
        self._sharpe_warning = sharpe_warning_threshold
        self._sharpe_critical = sharpe_critical_threshold
        self._win_rate_warning = win_rate_warning_threshold
        self._win_rate_critical = win_rate_critical_threshold
        self._drawdown_warning = max_drawdown_warning_threshold
        self._drawdown_critical = max_drawdown_critical_threshold
        self._consec_warning = consecutive_losses_warning_threshold
        self._consec_critical = consecutive_losses_critical_threshold
        self._consec_disable = consecutive_losses_disable_threshold
        self._min_trades = min_trades_for_degradation

        # _windows[agent_id][strategy_name] → deque[_TradeRecord]
        # defaultdict(lambda: defaultdict(deque)) with maxlen applied on
        # first append (see record_strategy_result).
        self._windows: dict[str, dict[str, deque[_TradeRecord]]] = defaultdict(
            lambda: defaultdict(lambda: deque(maxlen=self._window_size))
        )

        self._log = logger.bind(component="strategy_manager")

    # ── Public API ──────────────────────────────────────────────────────────────

    async def record_strategy_result(
        self,
        agent_id: str,
        strategy_name: str,
        signal: TradingSignal,
        outcome_pnl: Decimal | None = None,
    ) -> None:
        """Append a trade outcome to the rolling window for a strategy.

        Call this once when a signal is generated (``outcome_pnl=None``)
        and again when the corresponding position closes (``outcome_pnl=<value>``).
        The rolling window stores the most recent :attr:`window_size` records.

        When the window reaches capacity after a new append, a period summary
        is persisted to ``agent_performance`` (if a ``session_factory`` was
        supplied at construction).

        Args:
            agent_id: UUID string identifying the agent.
            strategy_name: Name of the strategy that generated the signal.
            signal: The :class:`~agent.trading.signal_generator.TradingSignal`
                that was acted on.  Used to count signals vs taken trades.
            outcome_pnl: Realised PnL in USDT after the position closes.
                Pass ``None`` while the position is still open.
        """
        record = _TradeRecord(
            strategy_name=strategy_name,
            signal=signal,
            outcome_pnl=outcome_pnl,
            recorded_at=datetime.now(UTC),
        )

        window = self._windows[agent_id][strategy_name]
        window.append(record)

        self._log.debug(
            "strategy_manager.record",
            agent_id=agent_id,
            strategy=strategy_name,
            action=signal.action,
            pnl=str(outcome_pnl) if outcome_pnl is not None else "open",
            window_len=len(window),
        )

        # Optionally persist a period summary when the window is at capacity.
        if len(window) == self._window_size and self._session_factory is not None:
            await self._persist_period_summary(agent_id, strategy_name, window, period="weekly")

    async def get_performance(
        self,
        agent_id: str,
        strategy_name: str | None = None,
        period: str = "weekly",
    ) -> list[StrategyPerformance]:
        """Return rolling performance statistics for one or all strategies.

        Computes metrics from the in-memory rolling window, not from the DB.
        For historical DB-backed metrics use the
        :class:`~src.database.repositories.agent_performance_repo.AgentPerformanceRepository`
        directly.

        Args:
            agent_id: UUID string of the agent.
            strategy_name: If supplied, return metrics for that strategy only.
                If ``None``, return metrics for every tracked strategy.
            period: Evaluation window label for the returned
                :class:`~agent.models.ecosystem.StrategyPerformance` objects.
                Must be ``"daily"``, ``"weekly"``, or ``"monthly"``.  This is
                a label only — the actual computation always uses the full
                rolling window.

        Returns:
            A list of :class:`~agent.models.ecosystem.StrategyPerformance`
            objects, one per strategy.  Empty list if no data has been recorded
            yet for this agent.

        Raises:
            ValueError: If ``period`` is not one of the allowed values.
        """
        _validate_period(period)

        agent_windows = self._windows.get(agent_id, {})
        if not agent_windows:
            return []

        target_strategies = (
            [strategy_name]
            if strategy_name is not None
            else list(agent_windows.keys())
        )

        results: list[StrategyPerformance] = []
        for name in target_strategies:
            window = agent_windows.get(name)
            if not window:
                continue
            metrics = _compute_metrics(window)
            results.append(
                StrategyPerformance(
                    strategy_name=name,
                    period=period,
                    total_signals=metrics.total_signals,
                    trades_taken=metrics.trades_taken,
                    win_rate=metrics.win_rate,
                    sharpe_ratio=metrics.sharpe_ratio,
                    max_drawdown=metrics.max_drawdown,
                    total_pnl=metrics.total_pnl,
                    avg_pnl_per_trade=metrics.avg_pnl_per_trade,
                    consecutive_losses=metrics.consecutive_losses,
                )
            )

        return results

    async def detect_degradation(
        self,
        agent_id: str,
    ) -> list[DegradationAlert]:
        """Scan all strategies for the agent and return active degradation alerts.

        Each strategy's rolling window is evaluated against the configured
        thresholds.  Only strategies with at least ``min_trades_for_degradation``
        completed trades in their window are evaluated — smaller windows produce
        unreliable statistics and are silently skipped.

        A single strategy can produce multiple alerts (one per degraded metric).
        The caller is expected to handle deduplication if the same metrics fire
        on consecutive calls.

        Args:
            agent_id: UUID string of the agent to scan.

        Returns:
            A list of :class:`~agent.models.ecosystem.DegradationAlert` objects.
            Empty list when all strategies are within acceptable thresholds.
        """
        agent_windows = self._windows.get(agent_id, {})
        if not agent_windows:
            return []

        alerts: list[DegradationAlert] = []
        now = datetime.now(UTC)

        for strategy_name, window in agent_windows.items():
            if not window:
                continue

            metrics = _compute_metrics(window)
            completed = _count_completed_trades(window)

            if completed < self._min_trades:
                self._log.debug(
                    "strategy_manager.degradation_check.skipped",
                    strategy=strategy_name,
                    completed_trades=completed,
                    required=self._min_trades,
                )
                continue

            # ── Sharpe ratio check ───────────────────────────────────────────
            if metrics.sharpe_ratio < self._sharpe_critical:
                alerts.append(
                    DegradationAlert(
                        strategy_name=strategy_name,
                        metric="sharpe",
                        current_value=round(metrics.sharpe_ratio, 4),
                        threshold_value=self._sharpe_critical,
                        severity="critical",
                        recommendation=(
                            f"Sharpe ratio of {metrics.sharpe_ratio:.2f} is below zero. "
                            f"Consider halving the allocation to {strategy_name} immediately."
                        ),
                        detected_at=now,
                    )
                )
            elif metrics.sharpe_ratio < self._sharpe_warning:
                alerts.append(
                    DegradationAlert(
                        strategy_name=strategy_name,
                        metric="sharpe",
                        current_value=round(metrics.sharpe_ratio, 4),
                        threshold_value=self._sharpe_warning,
                        severity="warning",
                        recommendation=(
                            f"Sharpe ratio of {metrics.sharpe_ratio:.2f} is below the "
                            f"warning threshold of {self._sharpe_warning}. "
                            f"Monitor {strategy_name} and consider reducing position size."
                        ),
                        detected_at=now,
                    )
                )

            # ── Win rate check ───────────────────────────────────────────────
            if metrics.win_rate < self._win_rate_critical:
                alerts.append(
                    DegradationAlert(
                        strategy_name=strategy_name,
                        metric="win_rate",
                        current_value=round(metrics.win_rate, 4),
                        threshold_value=self._win_rate_critical,
                        severity="critical",
                        recommendation=(
                            f"Win rate of {metrics.win_rate:.1%} is critically low. "
                            f"Reduce {strategy_name} position size by 50 % and review entry conditions."
                        ),
                        detected_at=now,
                    )
                )
            elif metrics.win_rate < self._win_rate_warning:
                alerts.append(
                    DegradationAlert(
                        strategy_name=strategy_name,
                        metric="win_rate",
                        current_value=round(metrics.win_rate, 4),
                        threshold_value=self._win_rate_warning,
                        severity="warning",
                        recommendation=(
                            f"Win rate of {metrics.win_rate:.1%} dropped below "
                            f"{self._win_rate_warning:.0%}. "
                            f"Tighten the confidence threshold for {strategy_name}."
                        ),
                        detected_at=now,
                    )
                )

            # ── Max drawdown check ───────────────────────────────────────────
            if metrics.max_drawdown > self._drawdown_critical:
                alerts.append(
                    DegradationAlert(
                        strategy_name=strategy_name,
                        metric="max_drawdown",
                        current_value=round(metrics.max_drawdown, 4),
                        threshold_value=self._drawdown_critical,
                        severity="critical",
                        recommendation=(
                            f"Maximum drawdown of {metrics.max_drawdown:.1%} exceeds the "
                            f"critical threshold of {self._drawdown_critical:.0%}. "
                            f"Halt {strategy_name} and review risk parameters."
                        ),
                        detected_at=now,
                    )
                )
            elif metrics.max_drawdown > self._drawdown_warning:
                alerts.append(
                    DegradationAlert(
                        strategy_name=strategy_name,
                        metric="max_drawdown",
                        current_value=round(metrics.max_drawdown, 4),
                        threshold_value=self._drawdown_warning,
                        severity="warning",
                        recommendation=(
                            f"Maximum drawdown of {metrics.max_drawdown:.1%} exceeded "
                            f"{self._drawdown_warning:.0%}. "
                            f"Tighten the stop-loss or reduce exposure for {strategy_name}."
                        ),
                        detected_at=now,
                    )
                )

            # ── Consecutive losses check ─────────────────────────────────────
            consec = metrics.consecutive_losses
            if consec >= self._consec_disable:
                alerts.append(
                    DegradationAlert(
                        strategy_name=strategy_name,
                        metric="consecutive_losses",
                        current_value=float(consec),
                        threshold_value=float(self._consec_disable),
                        severity="disable",
                        recommendation=(
                            f"{consec} consecutive losing trades in {strategy_name}. "
                            f"Disable this strategy until market conditions are re-evaluated."
                        ),
                        detected_at=now,
                    )
                )
            elif consec >= self._consec_critical:
                alerts.append(
                    DegradationAlert(
                        strategy_name=strategy_name,
                        metric="consecutive_losses",
                        current_value=float(consec),
                        threshold_value=float(self._consec_critical),
                        severity="critical",
                        recommendation=(
                            f"{consec} consecutive losses in {strategy_name}. "
                            f"Reduce allocation by 50 % and review recent market conditions."
                        ),
                        detected_at=now,
                    )
                )
            elif consec >= self._consec_warning:
                alerts.append(
                    DegradationAlert(
                        strategy_name=strategy_name,
                        metric="consecutive_losses",
                        current_value=float(consec),
                        threshold_value=float(self._consec_warning),
                        severity="warning",
                        recommendation=(
                            f"{consec} consecutive losses in {strategy_name}. "
                            f"Monitor closely; consider tightening stop-loss."
                        ),
                        detected_at=now,
                    )
                )

        if alerts:
            self._log.info(
                "strategy_manager.degradation_detected",
                agent_id=agent_id,
                alert_count=len(alerts),
                strategies=[a.strategy_name for a in alerts],
            )

        return alerts

    async def suggest_adjustments(
        self,
        agent_id: str,
        strategy_name: str,
    ) -> list[Adjustment]:
        """Produce conservative parameter adjustment suggestions for a strategy.

        Adjustments are always **conservative** — they reduce exposure or
        tighten thresholds rather than making radical changes.  No suggestion
        increases position size or loosens risk parameters.

        Suggestions are generated from the rolling window statistics and are
        independent of the degradation threshold check.  A strategy that is
        within acceptable thresholds may still receive a suggestion if its
        metrics show directional deterioration.

        Args:
            agent_id: UUID string of the agent.
            strategy_name: Name of the strategy to analyse.

        Returns:
            A list of :class:`~agent.models.ecosystem.Adjustment` objects.
            Empty when the strategy's metrics are strong (no adjustments needed).
        """
        window = self._windows.get(agent_id, {}).get(strategy_name)
        if not window:
            return []

        metrics = _compute_metrics(window)
        completed = _count_completed_trades(window)
        adjustments: list[Adjustment] = []

        # ── Suggestion: reduce position size when win rate is low ─────────────
        # Triggered below warning threshold to be proactive.  Suggest a 25 %
        # reduction (conservative) rather than halving.
        if completed >= self._min_trades and metrics.win_rate < self._win_rate_warning:
            current_pct = "0.05"  # default position size
            suggested_pct = "0.04" if metrics.win_rate >= self._win_rate_critical else "0.03"
            adjustments.append(
                Adjustment(
                    strategy_name=strategy_name,
                    parameter="position_size_pct",
                    current_value=current_pct,
                    suggested_value=suggested_pct,
                    rationale=(
                        f"Win rate of {metrics.win_rate:.1%} over the last "
                        f"{completed} trades is below the {self._win_rate_warning:.0%} "
                        f"warning threshold."
                    ),
                    expected_impact=(
                        f"Reduce daily loss exposure by ~"
                        f"{int((1 - float(suggested_pct) / float(current_pct)) * 100)} % "
                        f"while preserving strategy participation."
                    ),
                    priority="high" if metrics.win_rate < self._win_rate_critical else "medium",
                )
            )

        # ── Suggestion: tighten confidence threshold when Sharpe is low ──────
        # A strategy with low risk-adjusted return is over-trading low-quality
        # signals.  Tightening confidence eliminates the weakest signals.
        if completed >= self._min_trades and metrics.sharpe_ratio < self._sharpe_warning:
            current_conf = "0.55"
            suggested_conf = "0.65" if metrics.sharpe_ratio >= self._sharpe_critical else "0.70"
            adjustments.append(
                Adjustment(
                    strategy_name=strategy_name,
                    parameter="confidence_threshold",
                    current_value=current_conf,
                    suggested_value=suggested_conf,
                    rationale=(
                        f"Sharpe ratio of {metrics.sharpe_ratio:.2f} suggests the strategy "
                        f"is acting on too many low-quality signals."
                    ),
                    expected_impact=(
                        "Higher confidence threshold filters weak signals and should "
                        "improve risk-adjusted returns at the cost of lower trade frequency."
                    ),
                    priority="medium",
                )
            )

        # ── Suggestion: reduce stop-loss on high drawdown ─────────────────────
        # Peak-to-trough drawdown exceeded warning level — tighten the stop-loss
        # to limit future drawdowns without changing position size.
        if completed >= self._min_trades and metrics.max_drawdown > self._drawdown_warning:
            adjustments.append(
                Adjustment(
                    strategy_name=strategy_name,
                    parameter="stop_loss_pct",
                    current_value="0.02",
                    suggested_value="0.015",
                    rationale=(
                        f"Max drawdown of {metrics.max_drawdown:.1%} exceeded the "
                        f"{self._drawdown_warning:.0%} warning level."
                    ),
                    expected_impact=(
                        "Tighter stop-loss caps individual trade losses and should "
                        f"reduce future drawdowns toward {self._drawdown_warning:.0%}."
                    ),
                    priority=(
                        "high" if metrics.max_drawdown > self._drawdown_critical else "medium"
                    ),
                )
            )

        # ── Suggestion: add cooldown after consecutive losses ─────────────────
        # A run of consecutive losses often reflects a temporary regime mismatch.
        # Introducing a cooldown (skip N signals after a loss streak) prevents
        # compounding losses before the strategy adapts.
        if metrics.consecutive_losses >= self._consec_warning:
            adjustments.append(
                Adjustment(
                    strategy_name=strategy_name,
                    parameter="cooldown_trades_after_loss_streak",
                    current_value="0",
                    suggested_value="3",
                    rationale=(
                        f"{metrics.consecutive_losses} consecutive losses detected. "
                        f"A temporary cooldown prevents compounding during a regime mismatch."
                    ),
                    expected_impact=(
                        "Skip the next 3 signals after the loss streak ends. "
                        "Reduces participation but avoids further compounding losses."
                    ),
                    priority=(
                        "high"
                        if metrics.consecutive_losses >= self._consec_critical
                        else "low"
                    ),
                )
            )

        self._log.info(
            "strategy_manager.suggestions_generated",
            agent_id=agent_id,
            strategy=strategy_name,
            count=len(adjustments),
        )
        return adjustments

    async def compare_strategies(
        self,
        agent_id: str,
        period: str = "weekly",
    ) -> StrategyComparison:
        """Rank all tracked strategies for an agent by Sharpe ratio.

        Computes metrics from the in-memory rolling windows and builds
        a :class:`~agent.models.ecosystem.StrategyComparison` with an ordered
        ranking and an ensemble weight recommendation.

        Args:
            agent_id: UUID string of the agent.
            period: Evaluation window label for the comparison output.

        Returns:
            A :class:`~agent.models.ecosystem.StrategyComparison` instance.

        Raises:
            ValueError: If ``period`` is not one of the allowed values.
            ValueError: If no performance data is available for this agent
                (no strategies have been recorded yet).
        """
        _validate_period(period)

        agent_windows = self._windows.get(agent_id, {})
        if not agent_windows:
            raise ValueError(
                f"No performance data available for agent {agent_id!r}. "
                "Record at least one strategy result before comparing."
            )

        perfs: dict[str, StrategyPerformance] = {}
        for strategy_name, window in agent_windows.items():
            if not window:
                continue
            metrics = _compute_metrics(window)
            perfs[strategy_name] = StrategyPerformance(
                strategy_name=strategy_name,
                period=period,
                total_signals=metrics.total_signals,
                trades_taken=metrics.trades_taken,
                win_rate=metrics.win_rate,
                sharpe_ratio=metrics.sharpe_ratio,
                max_drawdown=metrics.max_drawdown,
                total_pnl=metrics.total_pnl,
                avg_pnl_per_trade=metrics.avg_pnl_per_trade,
                consecutive_losses=metrics.consecutive_losses,
            )

        if not perfs:
            raise ValueError(
                f"No non-empty strategy windows found for agent {agent_id!r}."
            )

        # Rank by Sharpe ratio descending.
        ranking = sorted(perfs.keys(), key=lambda s: perfs[s].sharpe_ratio, reverse=True)
        best = ranking[0]
        worst = ranking[-1]

        recommendation = _build_comparison_recommendation(perfs, ranking)

        self._log.info(
            "strategy_manager.compare",
            agent_id=agent_id,
            strategies=ranking,
            best=best,
            worst=worst,
        )

        return StrategyComparison(
            period=period,
            strategies=perfs,
            ranking=ranking,
            best_strategy=best,
            worst_strategy=worst,
            recommendation=recommendation,
            generated_at=datetime.now(UTC),
        )

    # ── Persistence ─────────────────────────────────────────────────────────────

    async def _persist_period_summary(
        self,
        agent_id: str,
        strategy_name: str,
        window: deque[_TradeRecord],
        period: str,
    ) -> None:
        """Write a period summary row to ``agent_performance``.

        Called automatically when the rolling window reaches capacity.
        Silently skipped when no ``session_factory`` was provided.

        Args:
            agent_id: UUID string of the agent.
            strategy_name: Name of the strategy being summarised.
            window: The rolling deque of records (must be non-empty).
            period: Aggregation window label (``"daily"``, ``"weekly"``,
                ``"monthly"``).
        """
        if self._session_factory is None:
            return

        try:
            from src.database.models import AgentPerformance  # noqa: PLC0415
            from src.database.repositories.agent_performance_repo import (  # noqa: PLC0415
                AgentPerformanceRepository,
            )
        except ImportError:
            self._log.warning(
                "strategy_manager.persist.import_error",
                reason="src package not available; skipping persistence.",
            )
            return

        metrics = _compute_metrics(window)
        now = datetime.now(UTC)
        window_days = _PERIOD_WINDOW_DAYS.get(period, 7)
        period_start = now - timedelta(days=window_days)

        perf_row = AgentPerformance(
            agent_id=UUID(agent_id) if isinstance(agent_id, str) else agent_id,
            strategy_name=strategy_name,
            period=period,
            period_start=period_start,
            period_end=now,
            total_trades=metrics.trades_taken,
            winning_trades=_count_winning_trades(window),
            total_pnl=metrics.total_pnl,
            sharpe_ratio=(
                Decimal(str(round(metrics.sharpe_ratio, 4)))
                if metrics.sharpe_ratio != 0.0
                else None
            ),
            max_drawdown_pct=(
                Decimal(str(round(metrics.max_drawdown, 4)))
                if metrics.max_drawdown > 0.0
                else None
            ),
            win_rate=(
                Decimal(str(round(metrics.win_rate, 4)))
                if metrics.trades_taken > 0
                else None
            ),
            extra_metrics={
                "total_signals": metrics.total_signals,
                "consecutive_losses": metrics.consecutive_losses,
                "avg_pnl_per_trade": str(metrics.avg_pnl_per_trade),
            },
        )

        try:
            async with self._session_factory() as session:
                repo = AgentPerformanceRepository(session)
                await repo.create(perf_row)
                await session.commit()
                self._log.info(
                    "strategy_manager.persist.success",
                    agent_id=agent_id,
                    strategy=strategy_name,
                    period=period,
                    total_trades=metrics.trades_taken,
                    sharpe=round(metrics.sharpe_ratio, 4),
                )
        except Exception as exc:  # noqa: BLE001
            self._log.error(
                "strategy_manager.persist.error",
                agent_id=agent_id,
                strategy=strategy_name,
                error=str(exc),
            )


# ── Pure helper functions (no I/O, fully testable) ──────────────────────────────


def _validate_period(period: str) -> None:
    """Raise ValueError if ``period`` is not a valid window label.

    Args:
        period: The period string to validate.

    Raises:
        ValueError: When ``period`` is not ``"daily"``, ``"weekly"``, or
            ``"monthly"``.
    """
    if period not in _PERIOD_WINDOW_DAYS:
        raise ValueError(
            f"Invalid period {period!r}. Must be one of: {list(_PERIOD_WINDOW_DAYS.keys())}."
        )


def _count_completed_trades(window: deque[_TradeRecord]) -> int:
    """Count records with a non-None ``outcome_pnl`` (closed positions).

    Args:
        window: The rolling window deque.

    Returns:
        Number of completed (closed) trades.
    """
    return sum(1 for r in window if r.outcome_pnl is not None)


def _count_winning_trades(window: deque[_TradeRecord]) -> int:
    """Count records with a strictly positive ``outcome_pnl``.

    Args:
        window: The rolling window deque.

    Returns:
        Number of winning (profitable) closed trades.
    """
    return sum(
        1 for r in window if r.outcome_pnl is not None and r.outcome_pnl > Decimal("0")
    )


def _compute_metrics(window: deque[_TradeRecord]) -> _StrategyMetrics:
    """Compute performance metrics from a rolling trade window.

    Only completed trades (non-None ``outcome_pnl``) contribute to win rate,
    Sharpe, drawdown, PnL, and consecutive-loss calculations.  Signals
    without an outcome (still-open positions) count toward ``total_signals``
    and ``trades_taken`` (for non-HOLD actions) but not toward the PnL-based
    metrics.

    The Sharpe ratio is estimated from the distribution of per-trade PnL
    values rather than from equity snapshots.  This is a simplification that
    is appropriate for a short rolling window (< 100 trades) where daily
    snapshot history is unavailable.  The annualisation factor assumes
    ~252 trading days and is applied to the per-trade mean/std-dev.

    The max drawdown is computed as the maximum peak-to-trough decline
    in cumulative PnL over the window, normalised to the initial balance
    using a proxy of $10,000 (platform default).

    Args:
        window: Non-empty deque of :class:`_TradeRecord` instances.

    Returns:
        :class:`_StrategyMetrics` with all fields populated.
    """
    total_signals = len(window)
    trades_taken = sum(1 for r in window if r.signal.action != "hold")
    completed_pnls = [r.outcome_pnl for r in window if r.outcome_pnl is not None]
    completed_count = len(completed_pnls)

    if completed_count == 0:
        return _StrategyMetrics(
            total_signals=total_signals,
            trades_taken=trades_taken,
            win_rate=0.0,
            sharpe_ratio=0.0,
            max_drawdown=0.0,
            total_pnl=Decimal("0"),
            avg_pnl_per_trade=Decimal("0"),
            consecutive_losses=0,
        )

    # Win rate
    winners = sum(1 for p in completed_pnls if p > Decimal("0"))
    win_rate = winners / completed_count

    # Total and average PnL
    total_pnl = sum(completed_pnls, Decimal("0"))
    avg_pnl = total_pnl / completed_count

    # Sharpe ratio (per-trade, then annualised).
    # Using a proxy of 252 trades/year for annualisation (typical for a
    # strategy producing ~1 round-trip per trading day).
    pnl_floats = [float(p) for p in completed_pnls]
    sharpe = _compute_sharpe(pnl_floats, annualisation_factor=252)

    # Max drawdown from cumulative PnL curve.
    # Proxy starting balance = $10,000 (platform default starting balance).
    proxy_balance = 10_000.0
    max_drawdown = _compute_max_drawdown(pnl_floats, starting_balance=proxy_balance)

    # Consecutive loss streak (from the end of the window, looking backwards).
    consecutive_losses = _compute_trailing_consecutive_losses(window)

    return _StrategyMetrics(
        total_signals=total_signals,
        trades_taken=trades_taken,
        win_rate=win_rate,
        sharpe_ratio=sharpe,
        max_drawdown=max_drawdown,
        total_pnl=total_pnl,
        avg_pnl_per_trade=avg_pnl,
        consecutive_losses=consecutive_losses,
    )


def _compute_sharpe(
    pnl_series: list[float],
    *,
    annualisation_factor: float = 252.0,
    risk_free_rate_annual: float = 0.0,
) -> float:
    """Estimate the annualised Sharpe ratio from a per-trade PnL series.

    Uses the sample mean and sample standard deviation of the PnL values.
    Returns 0.0 when fewer than 2 data points are available or when the
    standard deviation is zero (all trades had identical PnL).

    The formula is::

        Sharpe = (mean_pnl - risk_free_per_trade) / std_pnl * sqrt(annual_factor)

    where ``risk_free_per_trade = risk_free_rate_annual / annual_factor``.

    Args:
        pnl_series: List of per-trade realised PnL values (floats).
        annualisation_factor: Trades per year, used for annualisation.
            Default: 252 (one trade per trading day).
        risk_free_rate_annual: Annual risk-free rate.  Default: 0.0.

    Returns:
        Annualised Sharpe ratio as a float, or 0.0 when not computable.
    """
    n = len(pnl_series)
    if n < 2:
        return 0.0

    mean_pnl = sum(pnl_series) / n
    variance = sum((x - mean_pnl) ** 2 for x in pnl_series) / (n - 1)  # sample variance
    std_pnl = math.sqrt(variance)

    if std_pnl == 0.0:
        return 0.0

    risk_free_per_trade = risk_free_rate_annual / annualisation_factor
    return (mean_pnl - risk_free_per_trade) / std_pnl * math.sqrt(annualisation_factor)


def _compute_max_drawdown(
    pnl_series: list[float],
    *,
    starting_balance: float = 10_000.0,
) -> float:
    """Compute the maximum peak-to-trough equity drawdown fraction.

    Builds a cumulative equity curve from the PnL series (starting from
    ``starting_balance``) and finds the maximum decline from any peak.

    Args:
        pnl_series: Chronologically ordered per-trade PnL values.
        starting_balance: Starting equity (used as the denominator for
            normalising the drawdown fraction).  Default: 10,000.

    Returns:
        Maximum drawdown as a fraction in ``[0.0, 1.0]``.  Returns 0.0
        for an empty or single-element series.
    """
    if len(pnl_series) < 2:
        return 0.0

    equity = starting_balance
    peak = equity
    max_dd = 0.0

    for pnl in pnl_series:
        equity += pnl
        if equity > peak:
            peak = equity
        drawdown = (peak - equity) / peak if peak > 0 else 1.0
        if drawdown > max_dd:
            max_dd = drawdown

    # Cap at 1.0 — a drawdown > 100 % is not meaningful for this metric.
    return min(max_dd, 1.0)


def _compute_trailing_consecutive_losses(window: deque[_TradeRecord]) -> int:
    """Count the current trailing streak of consecutive losing trades.

    Iterates the window from the most recent record backwards and counts
    consecutive records with ``outcome_pnl <= 0``.  Open positions
    (``outcome_pnl is None``) are excluded from the count — they neither
    extend nor break the streak.

    Args:
        window: The rolling window deque (newest records at the right end).

    Returns:
        The number of consecutive losing closed trades at the end of the
        window.  Returns 0 if the most recent closed trade was profitable.
    """
    streak = 0
    for record in reversed(window):
        if record.outcome_pnl is None:
            # Skip open positions.
            continue
        if record.outcome_pnl <= Decimal("0"):
            streak += 1
        else:
            break
    return streak


def _build_comparison_recommendation(
    perfs: dict[str, StrategyPerformance],
    ranking: list[str],
) -> str:
    """Build a human-readable ensemble weight recommendation.

    Suggests increasing the weight of the best-performing strategy and
    reducing the weight of the worst, while being explicit about keeping
    changes small (conservative by design).

    Args:
        perfs: Performance stats keyed by strategy name.
        ranking: Strategy names ordered best-to-worst by Sharpe ratio.

    Returns:
        Recommendation string.
    """
    if len(ranking) == 1:
        only = ranking[0]
        return (
            f"Only one strategy tracked ({only!r}). "
            f"Sharpe={perfs[only].sharpe_ratio:.2f}, "
            f"win_rate={perfs[only].win_rate:.1%}. No comparison possible."
        )

    best = ranking[0]
    worst = ranking[-1]
    best_sharpe = perfs[best].sharpe_ratio
    worst_sharpe = perfs[worst].sharpe_ratio

    parts: list[str] = [
        f"Best: {best!r} (Sharpe={best_sharpe:.2f}, win_rate={perfs[best].win_rate:.1%}). "
        f"Worst: {worst!r} (Sharpe={worst_sharpe:.2f}, win_rate={perfs[worst].win_rate:.1%}).",
    ]

    if best_sharpe > 0.5 and worst_sharpe < 0.0:
        parts.append(
            f"Consider increasing {best!r} ensemble weight by 10 pp and "
            f"reducing {worst!r} by 10 pp."
        )
    elif best_sharpe > worst_sharpe + 0.5:
        parts.append(
            f"{best!r} outperforms {worst!r} by {best_sharpe - worst_sharpe:.2f} Sharpe points. "
            f"Consider a small reallocation (+5 pp to {best!r}, -5 pp from {worst!r})."
        )
    else:
        parts.append(
            "Strategies are performing within acceptable range of each other. "
            "No reallocation recommended at this time."
        )

    return " ".join(parts)
