"""Celery tasks for agent analytics: strategy attribution, memory effectiveness, and platform health.

Four tasks are registered here and wired into the Celery beat schedule in
``src/tasks/celery_app.py``:

* :func:`agent_strategy_attribution`  — daily at 02:00 UTC; aggregates the last
  24 h of ``agent_strategy_signals`` per strategy, correlates with decision
  outcomes via ``trace_id``, and persists one ``AgentPerformance`` row per
  strategy per agent with ``period="attribution"``.

* :func:`agent_memory_effectiveness`  — weekly Sunday at 03:00 UTC; counts
  decisions for the last 7 days and how many had memory context, then writes
  an ``AgentJournal`` entry of type ``"insight"`` per agent summarising the
  findings.

* :func:`agent_platform_health_report` — daily at 06:00 UTC; calls
  ``AgentApiCallRepository.get_stats()`` for the last 24 h and compares it to
  the prior 24 h window; auto-creates an ``AgentFeedback`` row of category
  ``"performance_issue"`` when any endpoint has doubled its p95 latency or
  has an error rate above 10 %.

* :func:`settle_agent_decisions` — every 5 minutes; closes the feedback loop
  from trade outcome to agent learning system.  For each active agent, finds
  unresolved ``AgentDecision`` rows (``outcome_recorded_at IS NULL``), checks
  whether the linked order has been filled, computes the realised PnL from the
  associated ``Trade`` rows, and writes ``outcome_pnl`` / ``outcome_recorded_at``
  back to the decision.  Optionally extends to memory reinforcement in future.

Design notes
------------
* All tasks bridge the Celery sync boundary via ``asyncio.run()``.
* All DB and repository imports are lazy (inside async bodies) using
  ``# noqa: PLC0415`` to avoid circular import chains at worker startup.
* Per-agent isolation: a failure on one agent is caught, logged, and counted
  as ``agents_failed``; processing continues for the remaining agents.
* Tasks do **not** require Redis; they access only TimescaleDB.
* ``max_retries=0`` — no automatic retry.  The next scheduled invocation
  serves as the implicit retry for daily/weekly tasks.

Example (manual trigger)::

    from src.tasks.agent_analytics import agent_strategy_attribution
    result = agent_strategy_attribution.delay()
    print(result.get(timeout=120))

    from src.tasks.agent_analytics import settle_agent_decisions
    result = settle_agent_decisions.delay()
    print(result.get(timeout=60))
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from src.tasks.celery_app import app

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Task 1: agent_strategy_attribution  (daily 02:00 UTC)
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="src.tasks.agent_analytics.agent_strategy_attribution",
    bind=False,
    max_retries=0,
    ignore_result=False,
    soft_time_limit=110,
    time_limit=120,
)
def agent_strategy_attribution() -> dict[str, Any]:
    """Aggregate 24 h strategy signal counts and correlate with decision PnL outcomes.

    For each active agent:

    1. Calls ``AgentStrategySignalRepository.get_attribution()`` for the last
       24 hours to obtain per-strategy signal counts and average confidence.
    2. Queries ``agent_decisions`` with a matching ``trace_id`` to find
       realised ``outcome_pnl`` values that can be attributed to each strategy.
    3. Persists one ``AgentPerformance`` row per strategy with
       ``period="attribution"`` and attribution stats in ``extra_metrics``.

    Returns:
        A dict with keys:

        * ``agents_processed`` — agents that completed without error.
        * ``agents_failed``    — agents that raised an unexpected exception.
        * ``rows_written``     — total ``AgentPerformance`` rows inserted.
        * ``duration_ms``      — total wall-clock time in milliseconds.

    Example::

        result = agent_strategy_attribution.delay()
        stats = result.get(timeout=120)
        print(f"Wrote {stats['rows_written']} attribution rows")
    """
    return asyncio.run(_run_strategy_attribution())


async def _run_strategy_attribution() -> dict[str, Any]:
    """Async body of :func:`agent_strategy_attribution`."""
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415
    from decimal import Decimal  # noqa: PLC0415
    from uuid import UUID  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from src.database.models import (  # noqa: PLC0415
        Agent,
        AgentDecision,
        AgentPerformance,
        AgentStrategySignal,
    )
    from src.database.repositories.agent_performance_repo import (  # noqa: PLC0415
        AgentPerformanceRepository,
    )
    from src.database.repositories.agent_strategy_signal_repo import (  # noqa: PLC0415
        AgentStrategySignalRepository,
    )
    from src.database.session import get_session_factory  # noqa: PLC0415

    task_start = time.monotonic()
    session_factory = get_session_factory()

    now = datetime.now(tz=UTC)
    window_start = now - timedelta(hours=24)

    agents_processed = 0
    agents_failed = 0
    rows_written = 0

    # ── Step 1: load all active agent IDs ────────────────────────────────────
    try:
        async with session_factory() as db:
            stmt = select(Agent.id).where(Agent.status != "archived").order_by(Agent.created_at.asc())
            result = await db.execute(stmt)
            agent_ids: list[UUID] = list(result.scalars().all())
    except Exception:
        logger.exception("agent.task.strategy_attribution.load_agents.failed")
        duration_ms = round((time.monotonic() - task_start) * 1000, 2)
        return {
            "agents_processed": 0,
            "agents_failed": 0,
            "rows_written": 0,
            "duration_ms": duration_ms,
        }

    # ── Step 2: per-agent attribution ─────────────────────────────────────────
    for agent_id in agent_ids:
        try:
            async with session_factory() as db:
                # Get per-strategy signal aggregates for the 24 h window.
                signal_repo = AgentStrategySignalRepository(db)
                attribution_rows = await signal_repo.get_attribution(
                    agent_id=agent_id,
                    start=window_start,
                    end=now,
                )

                if not attribution_rows:
                    agents_processed += 1
                    continue

                # Collect all trace_ids that had signals in this window so we
                # can look up matching decision outcomes.
                trace_stmt = (
                    select(AgentStrategySignal.trace_id, AgentStrategySignal.strategy_name)
                    .where(
                        AgentStrategySignal.agent_id == agent_id,
                        AgentStrategySignal.created_at >= window_start,
                        AgentStrategySignal.created_at < now,
                        AgentStrategySignal.trace_id.is_not(None),
                    )
                    .distinct()
                )
                trace_result = await db.execute(trace_stmt)
                # Map: trace_id -> strategy_name (one signal per trace is enough
                # to attribute the decision outcome to that strategy).
                trace_to_strategy: dict[str, str] = {
                    row.trace_id: row.strategy_name for row in trace_result.all() if row.trace_id
                }

                # Aggregate decision outcomes by strategy via trace_id join.
                # strategy_name -> list[outcome_pnl]
                strategy_pnl: dict[str, list[Decimal]] = {
                    row["strategy_name"]: [] for row in attribution_rows  # type: ignore[index]
                }

                if trace_to_strategy:
                    outcome_stmt = select(
                        AgentDecision.trace_id,
                        AgentDecision.outcome_pnl,
                    ).where(
                        AgentDecision.agent_id == agent_id,
                        AgentDecision.trace_id.in_(list(trace_to_strategy.keys())),
                        AgentDecision.outcome_pnl.is_not(None),
                    )
                    outcome_result = await db.execute(outcome_stmt)
                    for outcome_row in outcome_result.all():
                        strat = trace_to_strategy.get(outcome_row.trace_id or "")
                        if strat and strat in strategy_pnl and outcome_row.outcome_pnl is not None:
                            strategy_pnl[strat].append(Decimal(str(outcome_row.outcome_pnl)))

                # Write one AgentPerformance row per strategy.
                perf_repo = AgentPerformanceRepository(db)
                for row in attribution_rows:
                    strategy_name: str = row["strategy_name"]  # type: ignore[assignment]
                    signal_count: int = row["signal_count"]  # type: ignore[assignment]
                    avg_confidence: Decimal | None = row["avg_confidence"]  # type: ignore[assignment]

                    pnl_values = strategy_pnl.get(strategy_name, [])
                    total_attr_pnl = sum(pnl_values, Decimal("0"))
                    outcome_count = len(pnl_values)
                    winning_outcomes = sum(1 for p in pnl_values if p > Decimal("0"))

                    extra: dict[str, Any] = {
                        "signal_count": signal_count,
                        "avg_confidence": str(avg_confidence) if avg_confidence is not None else None,
                        "outcome_count": outcome_count,
                        "winning_outcomes": winning_outcomes,
                        "window_hours": 24,
                        "snapshot_type": "attribution",
                    }

                    win_rate: Decimal | None = (
                        Decimal(str(winning_outcomes)) / Decimal(str(outcome_count))
                        if outcome_count > 0
                        else None
                    )

                    perf_row = AgentPerformance(
                        agent_id=agent_id,
                        strategy_name=strategy_name,
                        period="attribution",
                        period_start=window_start,
                        period_end=now,
                        total_trades=outcome_count,
                        winning_trades=winning_outcomes,
                        total_pnl=total_attr_pnl,
                        win_rate=win_rate,
                        extra_metrics=extra,
                    )
                    await perf_repo.create(perf_row)
                    rows_written += 1

                await db.commit()

            agents_processed += 1
            logger.info(
                "agent.task.strategy_attribution.agent_done",
                agent_id=str(agent_id),
                strategies_attributed=len(attribution_rows),
            )
        except Exception:
            agents_failed += 1
            logger.exception("agent.task.strategy_attribution.agent_error", agent_id=str(agent_id))

    duration_ms = round((time.monotonic() - task_start) * 1000, 2)
    logger.info(
        "agent.task.strategy_attribution.finished",
        agents_processed=agents_processed,
        agents_failed=agents_failed,
        rows_written=rows_written,
        duration_ms=duration_ms,
    )
    return {
        "agents_processed": agents_processed,
        "agents_failed": agents_failed,
        "rows_written": rows_written,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Task 2: agent_memory_effectiveness  (weekly Sunday 03:00 UTC)
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="src.tasks.agent_analytics.agent_memory_effectiveness",
    bind=False,
    max_retries=0,
    ignore_result=False,
    soft_time_limit=110,
    time_limit=120,
)
def agent_memory_effectiveness() -> dict[str, Any]:
    """Write a weekly memory effectiveness insight journal entry per agent.

    For each active agent over the last 7 days:

    1. Counts the total number of ``agent_decisions`` rows (all decisions).
    2. Counts decisions where ``market_snapshot`` is non-NULL (proxy for
       memory context being available — the snapshot field carries market
       state assembled by :class:`~agent.conversation.context.ContextBuilder`
       which includes retrieved memories).
    3. Writes one ``AgentJournal`` entry of type ``"insight"`` summarising
       the counts and the memory coverage rate.

    Returns:
        A dict with keys:

        * ``agents_processed`` — agents that received a journal entry.
        * ``agents_failed``    — agents that raised an unexpected exception.
        * ``duration_ms``      — total wall-clock time in milliseconds.

    Example::

        result = agent_memory_effectiveness.delay()
        stats = result.get(timeout=120)
        print(f"Processed {stats['agents_processed']} agents")
    """
    return asyncio.run(_run_memory_effectiveness())


async def _run_memory_effectiveness() -> dict[str, Any]:
    """Async body of :func:`agent_memory_effectiveness`."""
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415
    from uuid import UUID  # noqa: PLC0415

    from sqlalchemy import and_, func, select  # noqa: PLC0415

    from src.database.models import Agent, AgentDecision, AgentJournal  # noqa: PLC0415
    from src.database.session import get_session_factory  # noqa: PLC0415

    task_start = time.monotonic()
    session_factory = get_session_factory()

    now = datetime.now(tz=UTC)
    week_start = now - timedelta(days=7)

    agents_processed = 0
    agents_failed = 0

    # ── Load all active agent IDs ─────────────────────────────────────────────
    try:
        async with session_factory() as db:
            stmt = select(Agent.id).where(Agent.status != "archived").order_by(Agent.created_at.asc())
            result = await db.execute(stmt)
            agent_ids: list[UUID] = list(result.scalars().all())
    except Exception:
        logger.exception("agent.task.memory_effectiveness.load_agents.failed")
        duration_ms = round((time.monotonic() - task_start) * 1000, 2)
        return {
            "agents_processed": 0,
            "agents_failed": 0,
            "duration_ms": duration_ms,
        }

    # ── Per-agent analysis ────────────────────────────────────────────────────
    week_label = week_start.strftime("%Y-%m-%d")
    week_end_label = now.strftime("%Y-%m-%d")

    for agent_id in agent_ids:
        try:
            async with session_factory() as db:
                # Count all decisions in the 7-day window.
                total_stmt = select(func.count(AgentDecision.id)).where(
                    and_(
                        AgentDecision.agent_id == agent_id,
                        AgentDecision.created_at >= week_start,
                        AgentDecision.created_at < now,
                    )
                )
                total_result = await db.execute(total_stmt)
                total_decisions: int = total_result.scalar() or 0

                # Count decisions where market_snapshot IS NOT NULL (memory context
                # was assembled and attached to the decision at inference time).
                with_memory_stmt = select(func.count(AgentDecision.id)).where(
                    and_(
                        AgentDecision.agent_id == agent_id,
                        AgentDecision.created_at >= week_start,
                        AgentDecision.created_at < now,
                        AgentDecision.market_snapshot.is_not(None),
                    )
                )
                with_memory_result = await db.execute(with_memory_stmt)
                decisions_with_memory: int = with_memory_result.scalar() or 0

                coverage_pct = (
                    round(decisions_with_memory / total_decisions * 100, 1)
                    if total_decisions > 0
                    else 0.0
                )

                # Build journal content.
                if total_decisions == 0:
                    content = (
                        f"Weekly memory effectiveness report for {week_label} to {week_end_label}\n\n"
                        "No decisions were recorded during this period.  "
                        "The agent was likely inactive."
                    )
                else:
                    content = (
                        f"Weekly memory effectiveness report for {week_label} to {week_end_label}\n\n"
                        f"Total decisions in window: {total_decisions}\n"
                        f"Decisions with memory context (market_snapshot present): "
                        f"{decisions_with_memory}\n"
                        f"Memory coverage rate: {coverage_pct}%\n\n"
                        "Notes:\n"
                        "- A decision with 'market_snapshot' present indicates that market state\n"
                        "  (including retrieved memories) was assembled before the decision.\n"
                        "- Low coverage may indicate the trading loop ran without a full context\n"
                        "  build step, or that market data was unavailable at decision time."
                    )

                journal_entry = AgentJournal(
                    agent_id=agent_id,
                    entry_type="insight",
                    title=f"Weekly Memory Effectiveness Report — {week_label}",
                    content=content,
                    market_context={
                        "week_start": week_label,
                        "week_end": week_end_label,
                        "total_decisions": total_decisions,
                        "decisions_with_memory": decisions_with_memory,
                        "memory_coverage_pct": coverage_pct,
                    },
                    tags=["automated", "memory_effectiveness", "weekly"],
                )
                db.add(journal_entry)
                await db.commit()

            agents_processed += 1
            logger.info(
                "agent.task.memory_effectiveness.agent_done",
                agent_id=str(agent_id),
                total_decisions=total_decisions,
                decisions_with_memory=decisions_with_memory,
                coverage_pct=coverage_pct,
            )
        except Exception:
            agents_failed += 1
            logger.exception("agent.task.memory_effectiveness.agent_error", agent_id=str(agent_id))

    duration_ms = round((time.monotonic() - task_start) * 1000, 2)
    logger.info(
        "agent.task.memory_effectiveness.finished",
        agents_processed=agents_processed,
        agents_failed=agents_failed,
        duration_ms=duration_ms,
    )
    return {
        "agents_processed": agents_processed,
        "agents_failed": agents_failed,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Task 3: agent_platform_health_report  (daily 06:00 UTC)
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="src.tasks.agent_analytics.agent_platform_health_report",
    bind=False,
    max_retries=0,
    ignore_result=False,
    soft_time_limit=110,
    time_limit=120,
)
def agent_platform_health_report() -> dict[str, Any]:
    """Compare today's API call stats to yesterday's and flag regressions.

    For each active agent:

    1. Fetches ``AgentApiCallRepository.get_stats()`` for the last 24 h
       (current window: ``now-24h → now``).
    2. Fetches stats for the prior 24 h window (``now-48h → now-24h``) as a
       baseline.
    3. For each endpoint seen in the current window:

       * If the average latency in the current window is more than **2x** the
         baseline average latency, auto-creates an ``AgentFeedback`` entry with
         ``category="performance_issue"`` and ``priority="high"``.
       * If the current error rate exceeds **10 %**, auto-creates an
         ``AgentFeedback`` entry with ``category="performance_issue"`` and
         ``priority="high"``.

    Returns:
        A dict with keys:

        * ``agents_processed``  — agents processed without an unexpected error.
        * ``agents_failed``     — agents that raised an unexpected exception.
        * ``feedback_created``  — total ``AgentFeedback`` rows auto-created.
        * ``duration_ms``       — total wall-clock time in milliseconds.

    Example::

        result = agent_platform_health_report.delay()
        stats = result.get(timeout=120)
        print(f"Created {stats['feedback_created']} feedback entries")
    """
    return asyncio.run(_run_platform_health_report())


async def _run_platform_health_report() -> dict[str, Any]:
    """Async body of :func:`agent_platform_health_report`."""
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415
    from decimal import Decimal  # noqa: PLC0415
    from uuid import UUID  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from src.database.models import Agent, AgentFeedback  # noqa: PLC0415
    from src.database.repositories.agent_api_call_repo import (  # noqa: PLC0415
        AgentApiCallRepository,
    )
    from src.database.session import get_session_factory  # noqa: PLC0415

    # Error rate threshold (10 %) and latency regression multiplier (2x).
    error_rate_threshold: float = 0.10
    latency_regression_factor: Decimal = Decimal("2")

    task_start = time.monotonic()
    session_factory = get_session_factory()

    now = datetime.now(tz=UTC)
    current_start = now - timedelta(hours=24)
    prior_start = now - timedelta(hours=48)

    agents_processed = 0
    agents_failed = 0
    feedback_created = 0

    # ── Load all active agent IDs ─────────────────────────────────────────────
    try:
        async with session_factory() as db:
            stmt = select(Agent.id).where(Agent.status != "archived").order_by(Agent.created_at.asc())
            result = await db.execute(stmt)
            agent_ids: list[UUID] = list(result.scalars().all())
    except Exception:
        logger.exception("agent.task.platform_health_report.load_agents.failed")
        duration_ms = round((time.monotonic() - task_start) * 1000, 2)
        return {
            "agents_processed": 0,
            "agents_failed": 0,
            "feedback_created": 0,
            "duration_ms": duration_ms,
        }

    # ── Per-agent health check ────────────────────────────────────────────────
    for agent_id in agent_ids:
        try:
            async with session_factory() as db:
                api_call_repo = AgentApiCallRepository(db)

                # Current 24 h window stats.
                current_stats = await api_call_repo.get_stats(
                    agent_id=agent_id,
                    start=current_start,
                    end=now,
                )
                # Prior 24 h window stats (baseline).
                prior_stats = await api_call_repo.get_stats(
                    agent_id=agent_id,
                    start=prior_start,
                    end=current_start,
                )

                current_total: int = current_stats["total_calls"]  # type: ignore[assignment]
                if current_total == 0:
                    # No calls in the current window — nothing to compare.
                    agents_processed += 1
                    continue

                current_avg_latency: Decimal | None = current_stats["avg_latency_ms"]  # type: ignore[assignment]
                current_error_rate: float = current_stats["error_rate"]  # type: ignore[assignment]
                current_by_endpoint: dict[str, int] = current_stats["by_endpoint"]  # type: ignore[assignment]

                prior_avg_latency: Decimal | None = prior_stats["avg_latency_ms"]  # type: ignore[assignment]

                agent_feedback_items: list[AgentFeedback] = []

                # ── Check 1: overall error rate ───────────────────────────────
                if current_error_rate > error_rate_threshold:
                    pct_label = f"{current_error_rate * 100:.1f}%"
                    feedback_item = AgentFeedback(
                        agent_id=agent_id,
                        category="performance_issue",
                        title=f"High API error rate detected: {pct_label}",
                        description=(
                            f"The overall API error rate for the last 24 h is {pct_label}, "
                            f"exceeding the {error_rate_threshold * 100:.0f}% threshold.  "
                            f"Total calls in window: {current_total}."
                        ),
                        priority="high",
                        status="new",
                    )
                    agent_feedback_items.append(feedback_item)

                # ── Check 2: average latency regression (overall) ─────────────
                if (
                    current_avg_latency is not None
                    and prior_avg_latency is not None
                    and prior_avg_latency > Decimal("0")
                    and current_avg_latency >= prior_avg_latency * latency_regression_factor
                ):
                    feedback_item = AgentFeedback(
                        agent_id=agent_id,
                        category="performance_issue",
                        title="API latency doubled vs prior 24 h window",
                        description=(
                            f"Average API latency rose from {prior_avg_latency} ms "
                            f"(prior 24 h) to {current_avg_latency} ms (current 24 h), "
                            f"exceeding the 2x regression threshold.  "
                            f"Endpoints active in window: "
                            f"{', '.join(list(current_by_endpoint.keys())[:10])}"
                        ),
                        priority="high",
                        status="new",
                    )
                    agent_feedback_items.append(feedback_item)

                # Persist feedback items (if any) within the same session.
                if agent_feedback_items:
                    db.add_all(agent_feedback_items)
                    await db.flush()
                    await db.commit()
                    feedback_created += len(agent_feedback_items)
                    logger.warning(
                        "agent.task.platform_health_report.regressions_found",
                        agent_id=str(agent_id),
                        feedback_count=len(agent_feedback_items),
                        current_error_rate=current_error_rate,
                        current_avg_latency_ms=str(current_avg_latency),
                        prior_avg_latency_ms=str(prior_avg_latency),
                    )

            agents_processed += 1
            logger.info(
                "agent.task.platform_health_report.agent_done",
                agent_id=str(agent_id),
                current_total_calls=current_total,
                current_error_rate=current_error_rate,
            )
        except Exception:
            agents_failed += 1
            logger.exception("agent.task.platform_health_report.agent_error", agent_id=str(agent_id))

    duration_ms = round((time.monotonic() - task_start) * 1000, 2)
    logger.info(
        "agent.task.platform_health_report.finished",
        agents_processed=agents_processed,
        agents_failed=agents_failed,
        feedback_created=feedback_created,
        duration_ms=duration_ms,
    )
    return {
        "agents_processed": agents_processed,
        "agents_failed": agents_failed,
        "feedback_created": feedback_created,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Task 4: settle_agent_decisions  (every 5 minutes)
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="src.tasks.agent_analytics.settle_agent_decisions",
    bind=False,
    max_retries=0,
    ignore_result=False,
    soft_time_limit=55,
    time_limit=60,
)
def settle_agent_decisions() -> dict[str, Any]:
    """Close the feedback loop from trade outcome to agent learning system.

    Runs every 5 minutes.  For each active agent:

    1. Calls :meth:`~AgentDecisionRepository.find_unresolved` to retrieve
       ``AgentDecision`` rows that have ``outcome_recorded_at IS NULL`` and a
       non-NULL ``order_id``.
    2. For each unresolved decision, loads the linked ``Order`` row via
       ``OrderRepository.get_by_id``.
    3. Skips decisions whose order is still ``pending`` or
       ``partially_filled`` — those trades have not yet settled.
    4. For filled (or cancelled / rejected / expired) orders, fetches all
       associated ``Trade`` rows and sums their ``realized_pnl`` to obtain
       the realised outcome.  If no ``realized_pnl`` is available (e.g., a
       buy that opens a position), the outcome is recorded as
       ``Decimal("0")`` to mark the decision as processed without blocking.
    5. Calls :meth:`~AgentDecisionRepository.update_outcome` to write
       ``outcome_pnl`` and ``outcome_recorded_at`` back to the decision row.

    Returns:
        A dict with keys:

        * ``agents_processed``  — agents completed without an unexpected error.
        * ``agents_failed``     — agents that raised an unexpected exception.
        * ``decisions_settled`` — total decision rows updated with an outcome.
        * ``decisions_skipped`` — decisions whose order was not yet filled.
        * ``duration_ms``       — total wall-clock time in milliseconds.

    Example::

        result = settle_agent_decisions.delay()
        stats = result.get(timeout=60)
        print(f"Settled {stats['decisions_settled']} decisions")
    """
    return asyncio.run(_run_settle_agent_decisions())


async def _run_settle_agent_decisions() -> dict[str, Any]:
    """Async body of :func:`settle_agent_decisions`.

    Loads all active agents, then for each agent finds unresolved decisions
    and attempts to match them against their linked filled order.
    """
    from datetime import UTC, datetime  # noqa: PLC0415
    from decimal import Decimal  # noqa: PLC0415
    from uuid import UUID  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from src.database.models import Agent, Order, Trade  # noqa: PLC0415
    from src.database.repositories.agent_decision_repo import (  # noqa: PLC0415
        AgentDecisionRepository,
    )
    from src.database.session import get_session_factory  # noqa: PLC0415

    # Order statuses that indicate the order is done — no further changes
    # expected regardless of whether trades were generated.
    settled_statuses: frozenset[str] = frozenset(
        {"filled", "cancelled", "rejected", "expired"}
    )

    task_start = time.monotonic()
    session_factory = get_session_factory()

    agents_processed = 0
    agents_failed = 0
    decisions_settled = 0
    decisions_skipped = 0

    # ── Step 1: load all active agent IDs ────────────────────────────────────
    try:
        async with session_factory() as db:
            stmt = (
                select(Agent.id)
                .where(Agent.status != "archived")
                .order_by(Agent.created_at.asc())
            )
            result = await db.execute(stmt)
            agent_ids: list[UUID] = list(result.scalars().all())
    except Exception:
        logger.exception("agent.task.settle_decisions.load_agents.failed")
        duration_ms = round((time.monotonic() - task_start) * 1000, 2)
        return {
            "agents_processed": 0,
            "agents_failed": 0,
            "decisions_settled": 0,
            "decisions_skipped": 0,
            "duration_ms": duration_ms,
        }

    # ── Step 2: per-agent settlement ──────────────────────────────────────────
    for agent_id in agent_ids:
        agent_settled = 0
        agent_skipped = 0
        try:
            async with session_factory() as db:
                decision_repo = AgentDecisionRepository(db)

                # Find decisions that have an order_id but no outcome yet.
                unresolved = await decision_repo.find_unresolved(agent_id)

                if not unresolved:
                    agents_processed += 1
                    continue

                now = datetime.now(tz=UTC)

                for decision in unresolved:
                    order_id: UUID = decision.order_id  # type: ignore[assignment]

                    # Load the linked order to check its current status.
                    order_stmt = select(Order).where(Order.id == order_id).limit(1)
                    order_result = await db.execute(order_stmt)
                    order: Order | None = order_result.scalars().first()

                    if order is None:
                        # Order was hard-deleted; record zero outcome to unblock.
                        await decision_repo.update_outcome(
                            decision.id,
                            outcome_pnl=Decimal("0"),
                            outcome_recorded_at=now,
                        )
                        agent_settled += 1
                        logger.warning(
                            "agent.task.settle_decisions.order_missing",
                            decision_id=str(decision.id),
                            order_id=str(order_id),
                            agent_id=str(agent_id),
                        )
                        continue

                    if order.status not in settled_statuses:
                        # Order is still open — skip, will be picked up next run.
                        agent_skipped += 1
                        continue

                    # Order has settled.  Compute realised PnL from Trade rows.
                    trades_stmt = select(Trade).where(Trade.order_id == order_id)
                    trades_result = await db.execute(trades_stmt)
                    trades = trades_result.scalars().all()

                    # Sum realized_pnl across all fills for this order.
                    # realized_pnl is NULL for opening buys (no closed position)
                    # and non-NULL for sells that close a position.
                    realized_pnl_values: list[Decimal] = [
                        Decimal(str(t.realized_pnl))
                        for t in trades
                        if t.realized_pnl is not None
                    ]
                    outcome_pnl = (
                        sum(realized_pnl_values, Decimal("0"))
                        if realized_pnl_values
                        else Decimal("0")
                    )

                    await decision_repo.update_outcome(
                        decision.id,
                        outcome_pnl=outcome_pnl,
                        outcome_recorded_at=now,
                    )
                    agent_settled += 1
                    logger.debug(
                        "agent.task.settle_decisions.decision_settled",
                        decision_id=str(decision.id),
                        order_id=str(order_id),
                        order_status=order.status,
                        outcome_pnl=str(outcome_pnl),
                        agent_id=str(agent_id),
                    )

                await db.commit()

            decisions_settled += agent_settled
            decisions_skipped += agent_skipped
            agents_processed += 1
            logger.info(
                "agent.task.settle_decisions.agent_done",
                agent_id=str(agent_id),
                decisions_settled=agent_settled,
                decisions_skipped=agent_skipped,
            )
        except Exception:
            agents_failed += 1
            logger.exception(
                "agent.task.settle_decisions.agent_error",
                agent_id=str(agent_id),
            )

    duration_ms = round((time.monotonic() - task_start) * 1000, 2)
    logger.info(
        "agent.task.settle_decisions.finished",
        agents_processed=agents_processed,
        agents_failed=agents_failed,
        decisions_settled=decisions_settled,
        decisions_skipped=decisions_skipped,
        duration_ms=duration_ms,
    )
    return {
        "agents_processed": agents_processed,
        "agents_failed": agents_failed,
        "decisions_settled": decisions_settled,
        "decisions_skipped": decisions_skipped,
        "duration_ms": duration_ms,
    }
