"""Attribution-driven weight adjustment for the ensemble MetaLearner.

Reads 7-day strategy PnL attribution from the ``agent_performance`` table
(rows with ``period="attribution"`` written by the
``agent_strategy_attribution`` Celery task) and applies the results to:

1. :class:`~agent.strategies.ensemble.meta_learner.MetaLearner` —
   adjusts per-source weights proportionally to attributed PnL via
   :meth:`~agent.strategies.ensemble.meta_learner.MetaLearner.apply_attribution_weights`.

2. :class:`~agent.strategies.ensemble.circuit_breaker.StrategyCircuitBreaker` —
   any strategy whose 7-day PnL is negative is auto-paused for 48 hours
   via :meth:`~agent.strategies.ensemble.circuit_breaker.StrategyCircuitBreaker.pause`
   (using the ``WEEKLY_DRAWDOWN_PAUSE_SECONDS`` TTL).

Usage (called from :meth:`EnsembleRunner.load_attribution`)::

    from agent.strategies.ensemble.attribution import AttributionLoader
    from src.database.session import get_session_factory

    loader = AttributionLoader(
        session_factory=get_session_factory(),
        meta_learner=runner._meta_learner,
        circuit_breaker=runner._circuit_breaker,
    )
    result = await loader.load_and_apply(agent_id="550e8400-...")

Design notes
------------
* ``AttributionLoader`` has **no** direct dependency on the FastAPI app or
  Celery.  It uses the same lazy-import pattern as the Celery tasks in
  ``src/tasks/``.
* All DB imports are lazy (inside the async method body) to avoid circular
  import chains when the module is imported at strategy startup.
* Failures on individual strategy names are caught and counted; they do not
  abort the whole load.  A Redis outage during circuit-breaker pause is also
  swallowed (the circuit breaker itself is fail-open).
* The 7-day window matches the ``agent_strategy_attribution`` task's
  ``window_hours=24`` granularity — we sum all attribution rows from the
  last 7 days, one row per (strategy, day).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from agent.strategies.ensemble.circuit_breaker import WEEKLY_DRAWDOWN_PAUSE_SECONDS
from agent.strategies.ensemble.meta_learner import MetaLearner

log = structlog.get_logger(__name__)

# Number of trailing days to aggregate when computing 7-day attribution PnL.
_ATTRIBUTION_WINDOW_DAYS: int = 7


@dataclass
class AttributionResult:
    """Summary of one attribution load-and-apply cycle.

    Attributes:
        agent_id: The agent UUID string this load was performed for.
        strategies_loaded: Number of distinct strategies with attribution data.
        strategies_paused: Number of strategies auto-paused due to negative PnL.
        attribution_pnl: The computed per-strategy PnL mapping that was fed to
            the MetaLearner.  Keys are strategy names; values are PnL fractions.
        new_weights: The MetaLearner's normalised weights after applying the
            attribution.  Empty if the MetaLearner was not provided.
        duration_ms: Wall-clock time for the full operation in milliseconds.
        errors: List of per-strategy error strings (if any).
    """

    agent_id: str
    strategies_loaded: int = 0
    strategies_paused: int = 0
    attribution_pnl: dict[str, float] = field(default_factory=dict)
    new_weights: dict[str, float] = field(default_factory=dict)
    duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)


class AttributionLoader:
    """Reads 7-day strategy attribution from the DB and applies it to the ensemble.

    The loader is intentionally stateless between calls — each :meth:`load_and_apply`
    creates its own DB session and returns a fresh :class:`AttributionResult`.

    Args:
        session_factory: An ``async_sessionmaker`` (or any callable returning
            an async context manager that yields an ``AsyncSession``).  Typed
            as ``Any`` to avoid a hard import of ``async_sessionmaker`` at
            module level (consistent with :class:`~agent.logging_writer.LogBatchWriter`
            and ``src.backtesting.engine``).
        meta_learner: The :class:`~agent.strategies.ensemble.meta_learner.MetaLearner`
            instance to update.  When ``None``, weight adjustment is skipped
            (attribution PnL is still logged).
        circuit_breaker: Optional
            :class:`~agent.strategies.ensemble.circuit_breaker.StrategyCircuitBreaker`.
            When provided, strategies with negative 7-day PnL are auto-paused.
            When ``None``, pausing is skipped.
    """

    def __init__(
        self,
        session_factory: Any,  # noqa: ANN401
        meta_learner: MetaLearner | None = None,
        circuit_breaker: Any = None,  # noqa: ANN401
    ) -> None:
        self._session_factory = session_factory
        self._meta_learner = meta_learner
        self._circuit_breaker = circuit_breaker

    async def load_and_apply(
        self,
        agent_id: str,
        *,
        window_days: int = _ATTRIBUTION_WINDOW_DAYS,
        min_weight: float = 0.05,
    ) -> AttributionResult:
        """Load attribution data and apply it to MetaLearner and CircuitBreaker.

        Algorithm
        ---------
        1. Query ``agent_performance`` for rows with ``period="attribution"``
           from the last ``window_days`` days for this agent.
        2. Aggregate ``total_pnl`` per ``strategy_name`` across all rows in
           the window (one row is written per strategy per day by the Celery
           task).
        3. Normalise each strategy's total PnL by the count of rows so the
           scale is consistent with a single-day fraction.
        4. Call :meth:`MetaLearner.apply_attribution_weights` with the
           per-strategy PnL fractions.
        5. For each strategy with a **negative** 7-day total PnL, call
           :meth:`StrategyCircuitBreaker.pause` with the weekly-drawdown TTL.

        Args:
            agent_id: UUID string of the owning agent.  Used to scope the DB
                query and the circuit-breaker keys.
            window_days: Trailing days to aggregate attribution rows.
                Default :data:`_ATTRIBUTION_WINDOW_DAYS` (7).
            min_weight: Floor for MetaLearner weight adjustment (forwarded to
                :meth:`~MetaLearner.apply_attribution_weights`).

        Returns:
            :class:`AttributionResult` describing what was loaded, adjusted,
            and paused.  Never raises — all errors are captured in
            ``result.errors``.
        """
        start = time.monotonic()
        result = AttributionResult(agent_id=agent_id)

        try:
            attribution_pnl = await self._fetch_attribution(
                agent_id=agent_id,
                window_days=window_days,
            )
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"DB fetch failed: {exc}")
            result.duration_ms = round((time.monotonic() - start) * 1000, 2)
            log.error(
                "agent.strategy.ensemble.attribution.fetch_failed",
                agent_id=agent_id,
                error=str(exc),
            )
            return result

        result.strategies_loaded = len(attribution_pnl)
        result.attribution_pnl = attribution_pnl

        if not attribution_pnl:
            log.info(
                "agent.strategy.ensemble.attribution.no_data",
                agent_id=agent_id,
                window_days=window_days,
            )
            result.duration_ms = round((time.monotonic() - start) * 1000, 2)
            return result

        log.info(
            "agent.strategy.ensemble.attribution.loaded",
            agent_id=agent_id,
            window_days=window_days,
            strategies=list(attribution_pnl.keys()),
            pnl={k: round(v, 4) for k, v in attribution_pnl.items()},
        )

        # ── Apply to MetaLearner ──────────────────────────────────────────────
        if self._meta_learner is not None:
            try:
                new_weights = self._meta_learner.apply_attribution_weights(
                    attribution_pnl,
                    min_weight=min_weight,
                )
                result.new_weights = {s.value: round(w, 4) for s, w in new_weights.items()}
            except Exception as exc:  # noqa: BLE001
                result.errors.append(f"MetaLearner weight update failed: {exc}")
                log.error(
                    "agent.strategy.ensemble.attribution.meta_learner_failed",
                    agent_id=agent_id,
                    error=str(exc),
                )

        # ── Auto-pause strategies with negative 7-day PnL ────────────────────
        if self._circuit_breaker is not None:
            for strategy_name, pnl in attribution_pnl.items():
                if pnl < 0.0:
                    try:
                        already_paused = await self._circuit_breaker.is_paused(
                            strategy_name, agent_id
                        )
                        if not already_paused:
                            await self._circuit_breaker.pause(
                                strategy_name,
                                agent_id,
                                pause_seconds=WEEKLY_DRAWDOWN_PAUSE_SECONDS,
                                reason=f"attribution_7d_pnl:{pnl:.4f}",
                            )
                            result.strategies_paused += 1
                            log.warning(
                                "agent.strategy.ensemble.attribution.strategy_paused",
                                agent_id=agent_id,
                                strategy=strategy_name,
                                pnl_7d=round(pnl, 4),
                                pause_seconds=WEEKLY_DRAWDOWN_PAUSE_SECONDS,
                            )
                    except Exception as exc:  # noqa: BLE001
                        result.errors.append(
                            f"Circuit breaker pause failed for {strategy_name!r}: {exc}"
                        )
                        log.error(
                            "agent.strategy.ensemble.attribution.pause_failed",
                            agent_id=agent_id,
                            strategy=strategy_name,
                            error=str(exc),
                        )

        result.duration_ms = round((time.monotonic() - start) * 1000, 2)
        log.info(
            "agent.strategy.ensemble.attribution.applied",
            agent_id=agent_id,
            strategies_loaded=result.strategies_loaded,
            strategies_paused=result.strategies_paused,
            new_weights=result.new_weights,
            duration_ms=result.duration_ms,
            errors=result.errors,
        )
        return result

    async def _fetch_attribution(
        self,
        agent_id: str,
        window_days: int,
    ) -> dict[str, float]:
        """Query the DB for 7-day attribution PnL per strategy.

        Aggregates ``total_pnl`` across all ``agent_performance`` rows with
        ``period="attribution"`` in the trailing ``window_days`` for this agent.
        The result is the raw summed PnL (not averaged) — the Celery task
        already writes one row per strategy per day, so summing gives the
        7-day total attributed PnL for each strategy.

        Returns an empty dict if no rows exist (agent has no attribution data yet).

        Args:
            agent_id: Agent UUID string.
            window_days: Trailing days to include.

        Returns:
            Dict mapping ``strategy_name`` → ``total_pnl`` (float).

        Raises:
            Any DB / import error — callers are expected to catch.
        """
        from datetime import UTC, datetime, timedelta  # noqa: PLC0415
        from decimal import Decimal  # noqa: PLC0415
        from uuid import UUID  # noqa: PLC0415

        from sqlalchemy import func, select  # noqa: PLC0415
        from src.database.models import AgentPerformance  # noqa: PLC0415

        now = datetime.now(tz=UTC)
        window_start = now - timedelta(days=window_days)
        try:
            agent_uuid: UUID | str = UUID(agent_id) if not isinstance(agent_id, UUID) else agent_id  # type: ignore[arg-type]
        except ValueError:
            # Non-UUID strings are accepted in tests where the DB is mocked.
            agent_uuid = agent_id  # type: ignore[assignment]

        async with self._session_factory() as db:
            stmt = (
                select(
                    AgentPerformance.strategy_name,
                    func.sum(AgentPerformance.total_pnl).label("pnl_sum"),
                )
                .where(
                    AgentPerformance.agent_id == agent_uuid,
                    AgentPerformance.period == "attribution",
                    AgentPerformance.period_start >= window_start,
                )
                .group_by(AgentPerformance.strategy_name)
            )
            result = await db.execute(stmt)
            rows = result.all()

        return {
            row.strategy_name: float(row.pnl_sum if row.pnl_sum is not None else Decimal("0"))
            for row in rows
            if row.strategy_name
        }
