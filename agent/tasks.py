"""Celery tasks for agent scheduled activities.

Four tasks are exported, matching the beat schedule registered in
``src/tasks/celery_app.py``:

* :func:`agent_morning_review`       — daily at the configured UTC hour;
  scans current market prices and generates a market summary stored in the
  agent's journal.
* :func:`agent_budget_reset`         — daily at midnight UTC; resets daily
  trade counters (``trades_today``, ``exposure_today``, ``loss_today``) to
  zero for every agent that has a budget record.
* :func:`agent_memory_cleanup`       — daily; removes expired learnings (by
  ``expires_at``) and low-confidence learnings older than
  ``memory_cleanup_age_days`` days that fall below
  ``memory_cleanup_confidence_threshold``.
* :func:`agent_performance_snapshot` — hourly; calculates a rolling
  24-hour performance window for every active agent and persists one
  ``AgentPerformance`` row per agent.

Design notes
------------
* All four tasks are defined in the ``agent/`` package so they run in the
  same worker process as the rest of the platform tasks.  They import from
  ``src/`` (platform backend) which is on ``sys.path`` via ``PYTHONPATH=.``.
* Each task bridges the Celery sync boundary to async code via
  ``asyncio.run()``, consistent with all other tasks in ``src/tasks/``.
* Lazy imports inside async bodies prevent circular import chains and avoid
  loading heavyweight ML modules at worker startup.
* Per-agent isolation: a failure on one agent is logged and counted but does
  not abort processing for other agents.
* The tasks do **not** require the agent server process to be running; they
  operate entirely through the database and Redis.

Example (manual trigger)::

    from agent.tasks import agent_budget_reset
    result = agent_budget_reset.delay()
    print(result.get(timeout=30))
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog
from src.tasks.celery_app import app

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Agent morning review
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="agent.tasks.agent_morning_review",
    bind=False,
    max_retries=0,
    ignore_result=False,
    soft_time_limit=110,
    time_limit=120,
)
def agent_morning_review() -> dict[str, Any]:
    """Run a daily market scan and store a summary journal entry per agent.

    Fetches current prices for the configured default symbols from the Redis
    price cache, builds a brief market summary (price per symbol), and writes
    one ``AgentJournal`` row of type ``"daily_review"`` for every active agent.
    Agents that already have a ``daily_review`` entry today are skipped so the
    task is safe to re-trigger manually.

    Returns:
        A dict with keys:

        * ``agents_processed``  — number of agents that received a journal entry.
        * ``agents_skipped``    — agents skipped (already reviewed today).
        * ``agents_failed``     — agents that raised an exception.
        * ``symbols_scanned``   — number of symbols included in the market scan.
        * ``duration_ms``       — total wall-clock time in milliseconds.

    Example::

        result = agent_morning_review.delay()
        stats = result.get(timeout=120)
        print(f"Reviewed {stats['agents_processed']} agents")
    """
    return asyncio.run(_run_morning_review())


async def _run_morning_review() -> dict[str, Any]:
    """Async body of :func:`agent_morning_review`."""
    from datetime import UTC, datetime  # noqa: PLC0415
    from uuid import UUID  # noqa: PLC0415

    from sqlalchemy import and_, select  # noqa: PLC0415
    from src.cache.price_cache import PriceCache  # noqa: PLC0415
    from src.cache.redis_client import get_redis_client  # noqa: PLC0415
    from src.database.models import Agent, AgentJournal  # noqa: PLC0415
    from src.database.session import get_session_factory  # noqa: PLC0415

    task_start = time.monotonic()
    session_factory = get_session_factory()

    # Default symbols to scan — matches agent/config.py default.
    _DEFAULT_SYMBOLS: list[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    agents_processed = 0
    agents_skipped = 0
    agents_failed = 0
    symbols_scanned = 0

    # ── Step 1: fetch current market prices from Redis ────────────────────────
    market_prices: dict[str, str] = {}
    try:
        redis_client = await get_redis_client()
        price_cache = PriceCache(redis_client)
        for symbol in _DEFAULT_SYMBOLS:
            price = await price_cache.get_price(symbol)
            if price is not None:
                market_prices[symbol] = str(price)
                symbols_scanned += 1
    except Exception:
        logger.exception("agent_morning_review.market_scan.failed")

    # ── Step 2: load all active (non-archived) agent IDs ─────────────────────
    try:
        agent_ids: list[UUID] = []
        async with session_factory() as db:
            stmt = select(Agent.id).where(Agent.status != "archived").order_by(Agent.created_at.asc())
            result = await db.execute(stmt)
            agent_ids = list(result.scalars().all())
    except Exception:
        logger.exception("agent_morning_review.load_agents.failed")
        duration_ms = round((time.monotonic() - task_start) * 1000, 2)
        return {
            "agents_processed": 0,
            "agents_skipped": 0,
            "agents_failed": 0,
            "symbols_scanned": symbols_scanned,
            "duration_ms": duration_ms,
        }

    # ── Step 3: write one daily_review journal entry per agent ───────────────
    today_start = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    for agent_id in agent_ids:
        try:
            async with session_factory() as db:
                # Check whether a daily_review entry already exists today.
                existing_stmt = select(AgentJournal.id).where(
                    and_(
                        AgentJournal.agent_id == agent_id,
                        AgentJournal.entry_type == "daily_review",
                        AgentJournal.created_at >= today_start,
                    )
                )
                existing_result = await db.execute(existing_stmt)
                if existing_result.scalars().first() is not None:
                    agents_skipped += 1
                    continue

                date_str = today_start.strftime("%Y-%m-%d")

                if market_prices:
                    price_lines = "\n".join(
                        f"  {symbol}: {price}" for symbol, price in market_prices.items()
                    )
                    content = (
                        f"Daily morning review for {date_str}\n\n"
                        f"Market prices at scan time:\n{price_lines}\n\n"
                        f"Symbols scanned: {symbols_scanned}"
                    )
                else:
                    content = (
                        f"Daily morning review for {date_str}\n\n"
                        "Market price data unavailable at scan time."
                    )

                journal_entry = AgentJournal(
                    agent_id=agent_id,
                    entry_type="daily_review",
                    title=f"Morning market review — {date_str}",
                    content=content,
                    market_context={"market_prices": market_prices, "symbols_scanned": symbols_scanned},
                    tags=["automated", "morning_review"],
                )
                db.add(journal_entry)
                await db.commit()

            agents_processed += 1
            logger.info("agent_morning_review.journal_written", agent_id=str(agent_id))
        except Exception:
            agents_failed += 1
            logger.exception("agent_morning_review.agent_error", agent_id=str(agent_id))

    duration_ms = round((time.monotonic() - task_start) * 1000, 2)
    logger.info(
        "agent_morning_review.finished",
        agents_processed=agents_processed,
        agents_skipped=agents_skipped,
        agents_failed=agents_failed,
        symbols_scanned=symbols_scanned,
        duration_ms=duration_ms,
    )
    return {
        "agents_processed": agents_processed,
        "agents_skipped": agents_skipped,
        "agents_failed": agents_failed,
        "symbols_scanned": symbols_scanned,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Agent budget reset
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="agent.tasks.agent_budget_reset",
    bind=False,
    max_retries=0,
    ignore_result=False,
    soft_time_limit=110,
    time_limit=120,
)
def agent_budget_reset() -> dict[str, Any]:
    """Reset daily trade counters for every agent at midnight UTC.

    Calls :meth:`~src.database.repositories.agent_budget_repo.AgentBudgetRepository.reset_daily`
    for every agent that has a budget record.  Each reset uses a single atomic
    ``UPDATE ... RETURNING`` statement, so it cannot partially reset an agent's
    counters.  Agents without a budget record are silently skipped.

    Per-agent isolation: a failure on one agent is logged and counted but
    does not abort resets for other agents.

    Returns:
        A dict with keys:

        * ``agents_reset``   — agents whose daily counters were cleared.
        * ``agents_skipped`` — agents with no budget record (nothing to reset).
        * ``agents_failed``  — agents that raised an unexpected exception.
        * ``duration_ms``    — total wall-clock time in milliseconds.

    Example::

        result = agent_budget_reset.delay()
        stats = result.get(timeout=120)
        print(f"Reset {stats['agents_reset']} agent budgets")
    """
    return asyncio.run(_run_budget_reset())


async def _run_budget_reset() -> dict[str, Any]:
    """Async body of :func:`agent_budget_reset`."""
    from uuid import UUID  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415
    from src.database.models import Agent, AgentBudget  # noqa: PLC0415
    from src.database.repositories.agent_budget_repo import (  # noqa: PLC0415
        AgentBudgetNotFoundError,
        AgentBudgetRepository,
    )
    from src.database.session import get_session_factory  # noqa: PLC0415

    task_start = time.monotonic()
    session_factory = get_session_factory()

    agents_reset = 0
    agents_skipped = 0
    agents_failed = 0

    # Load all non-archived agent IDs that have a budget record.
    # Joining with AgentBudget ensures we only iterate agents that have limits
    # configured, avoiding unnecessary reset attempts for agents without budgets.
    try:
        async with session_factory() as db:
            stmt = (
                select(Agent.id)
                .join(AgentBudget, AgentBudget.agent_id == Agent.id)
                .where(Agent.status != "archived")
                .order_by(Agent.created_at.asc())
            )
            result = await db.execute(stmt)
            agent_ids: list[UUID] = list(result.scalars().all())
    except Exception:
        logger.exception("agent_budget_reset.load_agents.failed")
        duration_ms = round((time.monotonic() - task_start) * 1000, 2)
        return {
            "agents_reset": 0,
            "agents_skipped": 0,
            "agents_failed": 0,
            "duration_ms": duration_ms,
        }

    for agent_id in agent_ids:
        try:
            async with session_factory() as db:
                repo = AgentBudgetRepository(db)
                await repo.reset_daily(agent_id)
                await db.commit()
            agents_reset += 1
            logger.info("agent_budget_reset.agent_reset", agent_id=str(agent_id))
        except AgentBudgetNotFoundError:
            # Budget row disappeared between the list query and the reset call.
            agents_skipped += 1
            logger.warning("agent_budget_reset.no_budget_record", agent_id=str(agent_id))
        except Exception:
            agents_failed += 1
            logger.exception("agent_budget_reset.agent_error", agent_id=str(agent_id))

    duration_ms = round((time.monotonic() - task_start) * 1000, 2)
    logger.info(
        "agent_budget_reset.finished",
        agents_reset=agents_reset,
        agents_skipped=agents_skipped,
        agents_failed=agents_failed,
        duration_ms=duration_ms,
    )
    return {
        "agents_reset": agents_reset,
        "agents_skipped": agents_skipped,
        "agents_failed": agents_failed,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Agent memory cleanup
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="agent.tasks.agent_memory_cleanup",
    bind=False,
    max_retries=0,
    ignore_result=False,
    soft_time_limit=110,
    time_limit=120,
)
def agent_memory_cleanup() -> dict[str, Any]:
    """Prune stale and low-confidence memory records for every active agent.

    Two cleanup passes are made per agent:

    1. **Expired learnings** — calls
       :meth:`~src.database.repositories.agent_learning_repo.AgentLearningRepository.prune_expired`
       to delete rows where ``expires_at IS NOT NULL AND expires_at <= now()``.

    2. **Low-confidence old learnings** — deletes rows older than
       ``memory_cleanup_age_days`` days where
       ``confidence < memory_cleanup_confidence_threshold``.
       Rows where ``confidence IS NULL`` are treated as having full confidence
       and are never removed by this pass.

    Both thresholds are read from ``AgentConfig`` so they can be adjusted via
    environment variables without code changes.

    Per-agent isolation: a failure on one agent is logged and counted but
    does not abort cleanup for other agents.

    Returns:
        A dict with keys:

        * ``agents_processed``         — agents that completed both passes.
        * ``agents_failed``            — agents that raised an unexpected exception.
        * ``total_expired_deleted``    — rows removed by the expiry pass.
        * ``total_low_conf_deleted``   — rows removed by the low-confidence pass.
        * ``duration_ms``              — total wall-clock time in milliseconds.

    Example::

        result = agent_memory_cleanup.delay()
        stats = result.get(timeout=120)
        print(f"Deleted {stats['total_expired_deleted']} expired learnings")
    """
    return asyncio.run(_run_memory_cleanup())


async def _run_memory_cleanup() -> dict[str, Any]:
    """Async body of :func:`agent_memory_cleanup`."""
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415
    from decimal import Decimal  # noqa: PLC0415
    from uuid import UUID  # noqa: PLC0415

    from sqlalchemy import (
        and_,  # noqa: PLC0415
        select,  # noqa: PLC0415
    )
    from sqlalchemy import delete as sa_delete  # noqa: PLC0415
    from src.database.models import Agent, AgentLearning  # noqa: PLC0415
    from src.database.repositories.agent_learning_repo import AgentLearningRepository  # noqa: PLC0415
    from src.database.session import get_session_factory  # noqa: PLC0415

    task_start = time.monotonic()
    session_factory = get_session_factory()

    # Read cleanup thresholds from AgentConfig so they are overridable via env vars.
    try:
        from agent.config import AgentConfig  # noqa: PLC0415

        _config = AgentConfig()  # type: ignore[call-arg]
        confidence_threshold = Decimal(str(_config.memory_cleanup_confidence_threshold))
        age_days = _config.memory_cleanup_age_days
    except Exception:
        logger.warning("agent_memory_cleanup.config_load_failed, using defaults")
        confidence_threshold = Decimal("0.2")
        age_days = 90

    agents_processed = 0
    agents_failed = 0
    total_expired_deleted = 0
    total_low_conf_deleted = 0

    # Load all non-archived agent IDs.
    try:
        async with session_factory() as db:
            stmt = select(Agent.id).where(Agent.status != "archived").order_by(Agent.created_at.asc())
            result = await db.execute(stmt)
            agent_ids: list[UUID] = list(result.scalars().all())
    except Exception:
        logger.exception("agent_memory_cleanup.load_agents.failed")
        duration_ms = round((time.monotonic() - task_start) * 1000, 2)
        return {
            "agents_processed": 0,
            "agents_failed": 0,
            "total_expired_deleted": 0,
            "total_low_conf_deleted": 0,
            "duration_ms": duration_ms,
        }

    age_cutoff = datetime.now(tz=UTC) - timedelta(days=age_days)

    for agent_id in agent_ids:
        expired_deleted = 0
        low_conf_deleted = 0
        try:
            # Pass 1: remove learnings past their expires_at.
            async with session_factory() as db:
                repo = AgentLearningRepository(db)
                expired_deleted = await repo.prune_expired(agent_id)
                await db.commit()

            # Pass 2: remove old low-confidence learnings.
            # Only targets rows where confidence IS NOT NULL AND confidence < threshold
            # AND created_at < cutoff.  NULL-confidence rows are preserved as trusted.
            async with session_factory() as db:
                stmt_low_conf = (
                    sa_delete(AgentLearning)
                    .where(
                        and_(
                            AgentLearning.agent_id == agent_id,
                            AgentLearning.confidence.is_not(None),
                            AgentLearning.confidence < confidence_threshold,
                            AgentLearning.created_at < age_cutoff,
                        )
                    )
                    .returning(AgentLearning.id)
                )
                low_conf_result = await db.execute(stmt_low_conf)
                low_conf_deleted = len(low_conf_result.scalars().all())
                await db.commit()

            total_expired_deleted += expired_deleted
            total_low_conf_deleted += low_conf_deleted
            agents_processed += 1
            logger.info(
                "agent_memory_cleanup.agent_done",
                agent_id=str(agent_id),
                expired_deleted=expired_deleted,
                low_conf_deleted=low_conf_deleted,
            )
        except Exception:
            agents_failed += 1
            logger.exception("agent_memory_cleanup.agent_error", agent_id=str(agent_id))

    duration_ms = round((time.monotonic() - task_start) * 1000, 2)
    logger.info(
        "agent_memory_cleanup.finished",
        agents_processed=agents_processed,
        agents_failed=agents_failed,
        total_expired_deleted=total_expired_deleted,
        total_low_conf_deleted=total_low_conf_deleted,
        confidence_threshold=str(confidence_threshold),
        age_days=age_days,
        duration_ms=duration_ms,
    )
    return {
        "agents_processed": agents_processed,
        "agents_failed": agents_failed,
        "total_expired_deleted": total_expired_deleted,
        "total_low_conf_deleted": total_low_conf_deleted,
        "duration_ms": duration_ms,
    }


# ---------------------------------------------------------------------------
# Agent performance snapshot
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[misc]
    name="agent.tasks.agent_performance_snapshot",
    bind=False,
    max_retries=0,
    ignore_result=False,
    soft_time_limit=55,
    time_limit=60,
)
def agent_performance_snapshot() -> dict[str, Any]:
    """Calculate and persist rolling hourly performance stats for every agent.

    For each active agent, queries realised trades over a rolling 24-hour
    window from the ``trades`` table and writes one ``AgentPerformance`` row
    keyed to the agent's ``active_strategy_label`` (or ``"_untagged"`` when
    no active strategy is set).

    Performance metrics calculated per agent:

    * ``total_trades``    — count of trade rows in the 24-hour window.
    * ``winning_trades``  — trades with ``realized_pnl > 0``.
    * ``total_pnl``       — sum of ``realized_pnl`` (``NULL`` treated as ``0``).
    * ``win_rate``        — ``winning_trades / total_trades`` (``None`` if no trades).

    Agents with zero trades in the window are skipped (no row written).
    Sharpe, drawdown, and ``avg_trade_duration`` require a full equity-curve
    series and are left as ``NULL``; a future daily task should back-fill them.

    Per-agent isolation: a failure on one agent is logged and counted but
    does not abort snapshots for other agents.

    Returns:
        A dict with keys:

        * ``agents_processed``    — agents that ran without error.
        * ``agents_failed``       — agents that raised an unexpected exception.
        * ``total_rows_written``  — ``AgentPerformance`` rows inserted.
        * ``duration_ms``         — total wall-clock time in milliseconds.

    Example::

        result = agent_performance_snapshot.delay()
        stats = result.get(timeout=60)
        print(f"Wrote {stats['total_rows_written']} performance rows")
    """
    return asyncio.run(_run_performance_snapshot())


async def _run_performance_snapshot() -> dict[str, Any]:
    """Async body of :func:`agent_performance_snapshot`."""
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415
    from decimal import Decimal  # noqa: PLC0415
    from uuid import UUID  # noqa: PLC0415

    from sqlalchemy import and_, func, select  # noqa: PLC0415
    from src.database.models import Agent, AgentPerformance, Trade  # noqa: PLC0415
    from src.database.repositories.agent_performance_repo import AgentPerformanceRepository  # noqa: PLC0415
    from src.database.session import get_session_factory  # noqa: PLC0415

    task_start = time.monotonic()
    session_factory = get_session_factory()
    now = datetime.now(tz=UTC)
    window_start = now - timedelta(hours=24)

    agents_processed = 0
    agents_failed = 0
    total_rows_written = 0

    # Load all non-archived agents with their active_strategy_label so we can
    # use it as the performance strategy_name without joining on each agent.
    try:
        async with session_factory() as db:
            stmt = (
                select(Agent.id, Agent.active_strategy_label)
                .where(Agent.status != "archived")
                .order_by(Agent.created_at.asc())
            )
            result = await db.execute(stmt)
            agents: list[tuple[UUID, str | None]] = list(result.all())
    except Exception:
        logger.exception("agent_performance_snapshot.load_agents.failed")
        duration_ms = round((time.monotonic() - task_start) * 1000, 2)
        return {
            "agents_processed": 0,
            "agents_failed": 0,
            "total_rows_written": 0,
            "duration_ms": duration_ms,
        }

    for agent_id, active_strategy_label in agents:
        strategy_name = active_strategy_label or "_untagged"
        try:
            async with session_factory() as db:
                # Aggregate trade stats over the rolling 24-hour window.
                stmt_agg = select(
                    func.count().label("total_trades"),
                    func.sum(
                        func.cast(
                            func.case(
                                (Trade.realized_pnl > Decimal("0"), 1),
                                else_=0,
                            ),
                            func.Integer,
                        )
                    ).label("winning_trades"),
                    func.sum(func.coalesce(Trade.realized_pnl, Decimal("0"))).label("total_pnl"),
                ).where(
                    and_(
                        Trade.agent_id == agent_id,
                        Trade.created_at >= window_start,
                        Trade.created_at <= now,
                    )
                )
                agg_result = await db.execute(stmt_agg)
                row = agg_result.one()

                total_trades: int = row.total_trades or 0
                if total_trades == 0:
                    # No trades in window — skip writing a row.
                    agents_processed += 1
                    continue

                winning_trades: int = row.winning_trades or 0
                total_pnl: Decimal = Decimal(str(row.total_pnl or 0))
                win_rate: Decimal | None = (
                    Decimal(str(winning_trades)) / Decimal(str(total_trades))
                    if total_trades > 0
                    else None
                )

                perf_row = AgentPerformance(
                    agent_id=agent_id,
                    strategy_name=strategy_name,
                    period="daily",
                    period_start=window_start,
                    period_end=now,
                    total_trades=total_trades,
                    winning_trades=winning_trades,
                    total_pnl=total_pnl,
                    win_rate=win_rate,
                    extra_metrics={"window_hours": 24, "snapshot_type": "rolling_hourly"},
                )
                perf_repo = AgentPerformanceRepository(db)
                await perf_repo.create(perf_row)
                await db.commit()

            total_rows_written += 1
            agents_processed += 1
            logger.info(
                "agent_performance_snapshot.agent_done",
                agent_id=str(agent_id),
                strategy_name=strategy_name,
                total_trades=total_trades,
                total_pnl=str(total_pnl),
            )
        except Exception:
            agents_failed += 1
            logger.exception("agent_performance_snapshot.agent_error", agent_id=str(agent_id))

    duration_ms = round((time.monotonic() - task_start) * 1000, 2)
    logger.info(
        "agent_performance_snapshot.finished",
        agents_processed=agents_processed,
        agents_failed=agents_failed,
        total_rows_written=total_rows_written,
        duration_ms=duration_ms,
    )
    return {
        "agents_processed": agents_processed,
        "agents_failed": agents_failed,
        "total_rows_written": total_rows_written,
        "duration_ms": duration_ms,
    }
