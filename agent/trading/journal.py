"""Trading journal — records every decision with full context and generates reflections.

:class:`TradingJournal` is the central audit and learning system for the agent trading
loop.  Every decision made by the agent is stored with its full market context, signals,
risk assessment, and reasoning chain.  After a trade round-trips, the journal generates
a post-trade reflection using an LLM (with a deterministic template fallback when the
LLM is unavailable).  Learnings extracted from reflections are written to the agent
memory store.

Architecture::

    TradingJournal
          │
          ├── record_decision()   — persist to agent_decisions table
          ├── record_outcome()    — write back PnL + hold duration to agent_decisions
          ├── generate_reflection() — LLM → JournalEntry in agent_journal table
          │       │
          │       └── _save_learnings_to_memory() — extracted learnings → agent_learnings
          ├── get_entries()       — list entries from agent_journal
          ├── daily_summary()     — aggregate day's decisions → JournalEntry
          └── weekly_review()     — pattern analysis over 7 days → JournalEntry

Usage::

    from agent.config import AgentConfig
    from agent.trading.journal import TradingJournal
    from agent.memory.store import MemoryStore

    journal = TradingJournal(config=config, memory_store=memory_store)

    # Record a decision before execution
    decision_id = await journal.record_decision(
        agent_id="uuid",
        decision=trade_decision,
        market_snapshot={"BTCUSDT": "67500.00"},
        signals=signals,
        risk_assessment={"approved": True},
        reasoning="Ensemble score 0.72, trending regime.",
    )

    # After the trade closes, write back the outcome
    await journal.record_outcome(
        decision_id=decision_id,
        pnl=Decimal("42.50"),
        hold_duration=3600,
        max_adverse_excursion=Decimal("18.00"),
    )

    # Generate a reflective journal entry
    entry = await journal.generate_reflection(decision_id=decision_id)

    # Generate a daily summary
    summary = await journal.daily_summary(agent_id="uuid")

    # Generate a weekly review
    review = await journal.weekly_review(agent_id="uuid")

Integration notes
-----------------
- All DB access uses lazy imports so the module can be imported in test environments
  without a running database.  DB failures are caught and logged — they never surface
  as unhandled exceptions in the trading loop.
- The LLM call in :meth:`generate_reflection` uses ``pydantic_ai.Agent`` with the
  ``agent_cheap_model`` to minimise token costs.  If the import fails or the call
  throws, a deterministic template-based reflection is used as a fallback.
- :meth:`_save_learnings_to_memory` calls :class:`~agent.memory.store.MemoryStore.save`
  on the injected store.  When no store is injected (``memory_store=None``) the method
  silently no-ops.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from datetime import date as DateType
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from agent.config import AgentConfig
from agent.models.ecosystem import JournalEntry, TradeDecision, TradeReflection

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Valid entry types in the agent_journal table (mirrors DB CHECK constraint).
_VALID_ENTRY_TYPES = frozenset(
    {
        "reflection",
        "insight",
        "mistake",
        "improvement",
        "daily_review",
        "weekly_review",
    }
)

# Number of recent decisions to pull for weekly reviews.
_WEEKLY_REVIEW_DECISIONS_LIMIT: int = 200

# Number of recent decisions to pull for daily summaries.
_DAILY_SUMMARY_DECISIONS_LIMIT: int = 100

# Maximum length of the reasoning snippet stored in a decision record.
_REASONING_SNIPPET_MAX_LEN: int = 500


# ---------------------------------------------------------------------------
# TradingJournal
# ---------------------------------------------------------------------------


class TradingJournal:
    """Records every agent decision and generates LLM-powered reflections.

    The journal persists structured data to two tables:

    - ``agent_decisions`` — every trade decision with its market context,
      signals, and reasoning chain.  Outcomes (PnL, hold duration) are
      written back via :meth:`record_outcome`.
    - ``agent_journal`` — qualitative narrative entries (reflections, daily
      summaries, weekly reviews) generated from the decision data.

    Optionally, learnings extracted from LLM reflections are forwarded to
    the injected :class:`~agent.memory.store.MemoryStore` so the agent can
    recall them in future cycles.

    Args:
        config: :class:`~agent.config.AgentConfig` with LLM model settings.
        memory_store: Optional :class:`~agent.memory.store.MemoryStore`
            implementation.  When ``None``, learning persistence is skipped.

    Example::

        journal = TradingJournal(config=AgentConfig(), memory_store=store)
        decision_id = await journal.record_decision(
            agent_id="550e8400-...",
            decision=decision,
            market_snapshot={"BTCUSDT": "67500.00"},
            signals=signals,
            risk_assessment={"approved": True},
            reasoning="Trending regime with 0.72 ensemble confidence.",
        )
    """

    def __init__(
        self,
        config: AgentConfig,
        memory_store: Any = None,  # noqa: ANN401
    ) -> None:
        self._config = config
        self._memory_store = memory_store
        self._log = logger.bind(component="trading_journal")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def record_decision(
        self,
        agent_id: str,
        decision: TradeDecision,
        market_snapshot: dict[str, Any],
        signals: list[Any],
        risk_assessment: dict[str, Any],
        reasoning: str,
    ) -> str:
        """Persist a trade decision with full context to ``agent_decisions``.

        Creates one ``AgentDecision`` row per call.  The row includes the full
        market snapshot, all strategy signals, the risk assessment output, and
        the LLM reasoning chain.  ``outcome_pnl`` and ``outcome_recorded_at``
        remain NULL until :meth:`record_outcome` is called.

        Args:
            agent_id: UUID string of the owning agent.
            decision: The :class:`~agent.models.ecosystem.TradeDecision` that
                was made.
            market_snapshot: Dict of symbol → price/indicator snapshots at
                decision time (e.g. ``{"BTCUSDT": "67500.00"}``).
            signals: List of signal dicts or
                :class:`~agent.trading.signal_generator.TradingSignal` objects
                from the current cycle.  Will be stored as-is in JSONB.
            risk_assessment: Output from the risk overlay pipeline (e.g.
                ``{"approved": True, "gates_passed": 6}``).
            reasoning: Free-text LLM reasoning chain that produced the decision.

        Returns:
            The server-assigned UUID string for the persisted decision row.
            Returns an empty string if persistence fails so callers do not
            need to handle exceptions.

        Raises:
            *Never raises*. All errors are caught and logged.
        """
        try:
            from src.database.models import AgentDecision  # noqa: PLC0415
            from src.database.repositories.agent_decision_repo import (  # noqa: PLC0415
                AgentDecisionRepository,
            )
            from src.database.session import get_session_factory  # noqa: PLC0415
        except ImportError as exc:
            self._log.warning(
                "agent.trade.journal.record_decision.import_failed",
                error=str(exc),
                hint="DB unavailable — skipping decision persistence.",
            )
            return ""

        decision_type = "hold" if decision.action == "hold" else "trade"

        # Normalise signals to JSON-safe list of dicts.
        signals_data: list[dict[str, Any]] = []
        for s in signals:
            if isinstance(s, dict):
                signals_data.append(s)
            elif hasattr(s, "__dict__"):
                signals_data.append(vars(s))
            else:
                try:
                    signals_data.append(s.model_dump())
                except AttributeError:
                    signals_data.append({"raw": str(s)})

        reasoning_snippet = reasoning[:_REASONING_SNIPPET_MAX_LEN]

        try:
            agent_uuid = UUID(agent_id)
        except (ValueError, AttributeError) as exc:
            self._log.error(
                "agent.trade.journal.record_decision.invalid_agent_id",
                agent_id=agent_id,
                error=str(exc),
            )
            return ""

        try:
            factory = get_session_factory()
            session = factory()
            async with session.begin():
                repo = AgentDecisionRepository(session)
                row = AgentDecision(
                    agent_id=agent_uuid,
                    session_id=None,
                    decision_type=decision_type,
                    symbol=decision.symbol,
                    direction=decision.action,
                    confidence=Decimal(str(round(decision.confidence, 4))),
                    reasoning=reasoning_snippet,
                    market_snapshot=market_snapshot,
                    signals=signals_data,
                    risk_assessment=risk_assessment,
                    order_id=None,
                )
                await repo.create(row)
                decision_id = str(row.id)

            self._log.info(
                "agent.trade.journal.record_decision.success",
                decision_id=decision_id,
                agent_id=agent_id,
                symbol=decision.symbol,
                action=decision.action,
                confidence=decision.confidence,
            )
            return decision_id

        except Exception as exc:  # noqa: BLE001
            self._log.error(
                "agent.trade.journal.record_decision.db_error",
                agent_id=agent_id,
                symbol=decision.symbol,
                error=str(exc),
            )
            return ""

    async def record_outcome(
        self,
        decision_id: str,
        pnl: Decimal,
        hold_duration: int,
        max_adverse_excursion: Decimal,
    ) -> None:
        """Write back the realised outcome of a decision to ``agent_decisions``.

        Updates ``outcome_pnl`` and ``outcome_recorded_at`` on the existing
        ``AgentDecision`` row.  ``hold_duration`` and
        ``max_adverse_excursion`` are stored in the ``risk_assessment`` JSONB
        column as supplementary data.

        Args:
            decision_id: UUID string of the ``AgentDecision`` row to update.
            pnl: Realised profit/loss in USDT for the trade.
            hold_duration: Seconds the position was held before closing.
            max_adverse_excursion: Largest unrealised loss during the hold
                period (positive value representing the drawdown magnitude).

        Raises:
            *Never raises*.  All errors are caught and logged.
        """
        try:
            from src.database.repositories.agent_decision_repo import (  # noqa: PLC0415
                AgentDecisionRepository,
            )
            from src.database.session import get_session_factory  # noqa: PLC0415
        except ImportError as exc:
            self._log.warning(
                "agent.trade.journal.record_outcome.import_failed",
                error=str(exc),
                hint="DB unavailable — skipping outcome persistence.",
            )
            return

        try:
            decision_uuid = UUID(decision_id)
        except (ValueError, AttributeError) as exc:
            self._log.error(
                "agent.trade.journal.record_outcome.invalid_decision_id",
                decision_id=decision_id,
                error=str(exc),
            )
            return

        try:
            factory = get_session_factory()
            session = factory()
            async with session.begin():
                repo = AgentDecisionRepository(session)

                # Fetch existing row so we can merge MAE / hold_duration into
                # the JSONB risk_assessment column without overwriting other data.
                existing = await repo.get_by_id(decision_uuid)
                existing_risk: dict[str, Any] = {}
                if existing.risk_assessment and isinstance(existing.risk_assessment, dict):
                    existing_risk = dict(existing.risk_assessment)
                existing_risk["hold_duration_seconds"] = hold_duration
                existing_risk["max_adverse_excursion"] = str(max_adverse_excursion)

                # Use the repo's update_outcome for the primary PnL write-back
                # and patch risk_assessment directly on the ORM object.
                updated = await repo.update_outcome(
                    decision_uuid,
                    outcome_pnl=pnl,
                    outcome_recorded_at=datetime.now(UTC),
                )
                updated.risk_assessment = existing_risk
                await session.flush()

            self._log.info(
                "agent.trade.journal.record_outcome.success",
                decision_id=decision_id,
                pnl=str(pnl),
                hold_duration=hold_duration,
            )

        except Exception as exc:  # noqa: BLE001
            self._log.error(
                "agent.trade.journal.record_outcome.db_error",
                decision_id=decision_id,
                error=str(exc),
            )

    async def generate_reflection(self, decision_id: str) -> JournalEntry:
        """Generate a post-trade reflection journal entry for a decision.

        Fetches the decision row, calls the LLM to produce a structured
        :class:`~agent.models.ecosystem.TradeReflection`, and persists the
        result as an ``AgentJournal`` row with ``entry_type='reflection'``.
        Learnings are extracted and saved to the memory store.

        Falls back to a deterministic template reflection when the LLM is
        unavailable (missing ``pydantic_ai`` dependency, bad API key, or
        network error).

        Args:
            decision_id: UUID string of the ``AgentDecision`` row to reflect on.

        Returns:
            A :class:`~agent.models.ecosystem.JournalEntry` with the full
            reflection text.  ``entry_id`` is populated from the database
            after persistence.

        Raises:
            *Never raises*. Returns a minimal fallback entry on any error.
        """
        decision_row = await self._fetch_decision(decision_id)

        if decision_row is None:
            self._log.warning(
                "agent.trade.journal.generate_reflection.decision_not_found",
                decision_id=decision_id,
            )
            return self._empty_journal_entry("reflection")

        # Build the reflection — try LLM first, fall back to template.
        reflection = await self._llm_reflection(decision_row)
        if reflection is None:
            reflection = self._template_reflection(decision_row)

        # Compose the narrative text.
        pnl_str = str(decision_row.get("outcome_pnl", "N/A"))
        content = self._format_reflection_content(reflection, decision_row)
        market_context = decision_row.get("market_snapshot") or {}

        # Extract tags from the reflection content.
        tags = self._extract_tags(reflection)

        # Persist the journal entry.
        entry_id = await self._persist_journal_entry(
            agent_id=str(decision_row["agent_id"]),
            entry_type="reflection",
            title=f"Trade reflection: {decision_row.get('symbol', 'unknown')} {decision_row.get('direction', '')}",
            content=content,
            market_context=market_context,
            related_decisions=[decision_id],
            tags=tags,
        )

        # Save structured episodic memory for the completed trade (best-effort).
        await self.save_episodic_memory(
            agent_id=str(decision_row["agent_id"]),
            decision_row=decision_row,
        )

        # Save learnings to memory store (best-effort).
        if reflection is not None:
            await self._save_learnings_to_memory(
                agent_id=str(decision_row["agent_id"]),
                learnings=reflection.learnings,
                source=f"reflection_{decision_id}",
                decision_row=decision_row,
            )

        entry = JournalEntry(
            entry_id=entry_id,
            entry_type="reflection",
            content=content,
            market_context=market_context,
            tags=tags,
            created_at=datetime.now(UTC),
        )

        self._log.info(
            "agent.trade.journal.generate_reflection.success",
            decision_id=decision_id,
            entry_id=entry_id,
            pnl=pnl_str,
            learnings=len(reflection.learnings) if reflection else 0,
        )
        return entry

    async def get_entries(
        self,
        agent_id: str,
        entry_type: str | None = None,
        limit: int = 20,
    ) -> list[JournalEntry]:
        """Retrieve recent journal entries for an agent.

        Args:
            agent_id: UUID string of the owning agent.
            entry_type: Optional filter by type (``"reflection"``,
                ``"daily_review"``, ``"weekly_review"``, etc.).
                ``None`` returns all types.
            limit: Maximum number of entries to return (newest first).

        Returns:
            List of :class:`~agent.models.ecosystem.JournalEntry` objects,
            newest first.  Returns an empty list on any error.

        Raises:
            *Never raises*.
        """
        try:
            from src.database.repositories.agent_journal_repo import (  # noqa: PLC0415
                AgentJournalRepository,
            )
            from src.database.session import get_session_factory  # noqa: PLC0415
        except ImportError as exc:
            self._log.warning(
                "agent.trade.journal.get_entries.import_failed",
                error=str(exc),
            )
            return []

        try:
            agent_uuid = UUID(agent_id)
        except (ValueError, AttributeError) as exc:
            self._log.error(
                "agent.trade.journal.get_entries.invalid_agent_id",
                agent_id=agent_id,
                error=str(exc),
            )
            return []

        # Normalise entry_type — ignore unsupported values silently.
        safe_type: str | None = entry_type
        if entry_type is not None and entry_type not in _VALID_ENTRY_TYPES:
            self._log.warning(
                "agent.trade.journal.get_entries.unknown_entry_type",
                entry_type=entry_type,
            )
            safe_type = None

        try:
            factory = get_session_factory()
            session = factory()
            async with session.begin():
                repo = AgentJournalRepository(session)
                rows = await repo.list_by_agent(
                    agent_uuid,
                    entry_type=safe_type,
                    limit=limit,
                )

            return [
                JournalEntry(
                    entry_id=str(row.id),
                    entry_type=row.entry_type,
                    content=row.content,
                    market_context=row.market_context or {},
                    tags=list(row.tags or []),
                    created_at=row.created_at,
                )
                for row in rows
            ]

        except Exception as exc:  # noqa: BLE001
            self._log.error(
                "agent.trade.journal.get_entries.db_error",
                agent_id=agent_id,
                error=str(exc),
            )
            return []

    async def daily_summary(self, agent_id: str) -> JournalEntry:
        """Generate and persist a daily summary for an agent.

        Aggregates all decisions from today (UTC midnight to now), computes
        aggregate statistics (trades taken, win rate, total PnL, dominant
        regime), and produces a narrative summary.

        The entry is persisted to ``agent_journal`` with
        ``entry_type='daily_review'``.

        Args:
            agent_id: UUID string of the owning agent.

        Returns:
            A :class:`~agent.models.ecosystem.JournalEntry` with the daily
            summary content.  Returns an empty fallback entry on any error.

        Raises:
            *Never raises*.
        """
        today_start = datetime.now(UTC).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_end = datetime.now(UTC)

        decisions = await self._fetch_decisions_in_range(
            agent_id=agent_id,
            since=today_start,
            until=today_end,
            limit=_DAILY_SUMMARY_DECISIONS_LIMIT,
        )

        if not decisions:
            content = f"No decisions recorded today ({today_start.date()})."
            entry_id = await self._persist_journal_entry(
                agent_id=agent_id,
                entry_type="daily_review",
                title=f"Daily summary — {today_start.date()}",
                content=content,
                market_context={},
                related_decisions=[],
                tags=["daily_review"],
            )
            return JournalEntry(
                entry_id=entry_id,
                entry_type="daily_review",
                content=content,
                market_context={},
                tags=["daily_review"],
                created_at=datetime.now(UTC),
            )

        stats = self._compute_decision_stats(decisions)
        content = self._format_daily_summary(today_start.date(), stats, decisions)
        tags = self._build_summary_tags(stats)

        entry_id = await self._persist_journal_entry(
            agent_id=agent_id,
            entry_type="daily_review",
            title=f"Daily summary — {today_start.date()}",
            content=content,
            market_context={"date": str(today_start.date()), "stats": stats},
            related_decisions=[str(d.get("id", "")) for d in decisions if d.get("id")],
            tags=tags,
        )

        self._log.info(
            "agent.trade.journal.daily_summary.success",
            agent_id=agent_id,
            date=str(today_start.date()),
            decisions=len(decisions),
            entry_id=entry_id,
        )

        return JournalEntry(
            entry_id=entry_id,
            entry_type="daily_review",
            content=content,
            market_context={"date": str(today_start.date()), "stats": stats},
            tags=tags,
            created_at=datetime.now(UTC),
        )

    async def weekly_review(self, agent_id: str) -> JournalEntry:
        """Generate and persist a weekly review for an agent.

        Analyses the past 7 days of decisions to identify patterns, best/worst
        trades, and strategy performance.  The review narrative is generated
        via a template (the LLM is not invoked here to limit token usage).

        The entry is persisted to ``agent_journal`` with
        ``entry_type='weekly_review'``.

        Args:
            agent_id: UUID string of the owning agent.

        Returns:
            A :class:`~agent.models.ecosystem.JournalEntry` with the weekly
            review content.  Returns an empty fallback entry on any error.

        Raises:
            *Never raises*.
        """
        week_start = datetime.now(UTC) - timedelta(days=7)
        week_end = datetime.now(UTC)

        decisions = await self._fetch_decisions_in_range(
            agent_id=agent_id,
            since=week_start,
            until=week_end,
            limit=_WEEKLY_REVIEW_DECISIONS_LIMIT,
        )

        if not decisions:
            content = (
                f"No decisions recorded in the past 7 days "
                f"({week_start.date()} to {week_end.date()})."
            )
            entry_id = await self._persist_journal_entry(
                agent_id=agent_id,
                entry_type="weekly_review",
                title=f"Weekly review — {week_start.date()} to {week_end.date()}",
                content=content,
                market_context={},
                related_decisions=[],
                tags=["weekly_review"],
            )
            return JournalEntry(
                entry_id=entry_id,
                entry_type="weekly_review",
                content=content,
                market_context={},
                tags=["weekly_review"],
                created_at=datetime.now(UTC),
            )

        stats = self._compute_decision_stats(decisions)
        best_trade = self._find_best_trade(decisions)
        worst_trade = self._find_worst_trade(decisions)
        strategy_breakdown = self._analyse_strategy_performance(decisions)

        content = self._format_weekly_review(
            week_start=week_start.date(),
            week_end=week_end.date(),
            stats=stats,
            best_trade=best_trade,
            worst_trade=worst_trade,
            strategy_breakdown=strategy_breakdown,
        )
        tags = self._build_summary_tags(stats) + ["weekly_review"]

        entry_id = await self._persist_journal_entry(
            agent_id=agent_id,
            entry_type="weekly_review",
            title=f"Weekly review — {week_start.date()} to {week_end.date()}",
            content=content,
            market_context={
                "week_start": str(week_start.date()),
                "week_end": str(week_end.date()),
                "stats": stats,
                "strategy_breakdown": strategy_breakdown,
            },
            related_decisions=[str(d.get("id", "")) for d in decisions if d.get("id")],
            tags=list(set(tags)),
        )

        self._log.info(
            "agent.trade.journal.weekly_review.success",
            agent_id=agent_id,
            decisions=len(decisions),
            entry_id=entry_id,
        )

        return JournalEntry(
            entry_id=entry_id,
            entry_type="weekly_review",
            content=content,
            market_context={
                "week_start": str(week_start.date()),
                "week_end": str(week_end.date()),
                "stats": stats,
            },
            tags=list(set(tags)),
            created_at=datetime.now(UTC),
        )

    # ------------------------------------------------------------------
    # Private — database helpers
    # ------------------------------------------------------------------

    async def _fetch_decision(self, decision_id: str) -> dict[str, Any] | None:
        """Fetch a single decision row by ID as a plain dict.

        Args:
            decision_id: UUID string of the ``AgentDecision`` to fetch.

        Returns:
            A dict representation of the row, or ``None`` if not found or on
            any error.
        """
        try:
            from src.database.repositories.agent_decision_repo import (  # noqa: PLC0415
                AgentDecisionRepository,
            )
            from src.database.session import get_session_factory  # noqa: PLC0415
        except ImportError:
            return None

        try:
            decision_uuid = UUID(decision_id)
        except (ValueError, AttributeError):
            return None

        try:
            factory = get_session_factory()
            session = factory()
            async with session.begin():
                repo = AgentDecisionRepository(session)
                row = await repo.get_by_id(decision_uuid)
                return {
                    "id": str(row.id),
                    "agent_id": str(row.agent_id),
                    "decision_type": row.decision_type,
                    "symbol": row.symbol,
                    "direction": row.direction,
                    "confidence": str(row.confidence) if row.confidence else None,
                    "reasoning": row.reasoning,
                    "market_snapshot": row.market_snapshot or {},
                    "signals": row.signals or [],
                    "risk_assessment": row.risk_assessment or {},
                    "outcome_pnl": str(row.outcome_pnl) if row.outcome_pnl is not None else None,
                    "created_at": row.created_at,
                }
        except Exception as exc:  # noqa: BLE001
            self._log.error(
                "agent.trade.journal.fetch_decision.error",
                decision_id=decision_id,
                error=str(exc),
            )
            return None

    async def _fetch_decisions_in_range(
        self,
        agent_id: str,
        since: datetime,
        until: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Fetch decisions for an agent within a UTC datetime range.

        Args:
            agent_id: UUID string of the owning agent.
            since: Range start (inclusive).
            until: Range end (inclusive).
            limit: Maximum number of rows to return.

        Returns:
            List of decision dicts (newest first).  Returns empty list on
            any error.
        """
        try:
            from sqlalchemy import and_, select  # noqa: PLC0415
            from src.database.models import AgentDecision  # noqa: PLC0415
            from src.database.session import get_session_factory  # noqa: PLC0415
        except ImportError:
            return []

        try:
            agent_uuid = UUID(agent_id)
        except (ValueError, AttributeError):
            return []

        try:
            factory = get_session_factory()
            session = factory()
            async with session.begin():
                stmt = (
                    select(AgentDecision)
                    .where(
                        and_(
                            AgentDecision.agent_id == agent_uuid,
                            AgentDecision.created_at >= since,
                            AgentDecision.created_at <= until,
                        )
                    )
                    .order_by(AgentDecision.created_at.desc())
                    .limit(limit)
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()

            return [
                {
                    "id": str(r.id),
                    "agent_id": str(r.agent_id),
                    "decision_type": r.decision_type,
                    "symbol": r.symbol,
                    "direction": r.direction,
                    "confidence": float(r.confidence) if r.confidence else None,
                    "reasoning": r.reasoning,
                    "market_snapshot": r.market_snapshot or {},
                    "signals": r.signals or [],
                    "risk_assessment": r.risk_assessment or {},
                    "outcome_pnl": str(r.outcome_pnl) if r.outcome_pnl is not None else None,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

        except Exception as exc:  # noqa: BLE001
            self._log.error(
                "agent.trade.journal.fetch_decisions_range.error",
                agent_id=agent_id,
                error=str(exc),
            )
            return []

    async def _persist_journal_entry(
        self,
        agent_id: str,
        entry_type: str,
        title: str,
        content: str,
        market_context: dict[str, Any],
        related_decisions: list[str],
        tags: list[str],
    ) -> str:
        """Persist one row to ``agent_journal`` and return its assigned ID.

        Args:
            agent_id: UUID string of the owning agent.
            entry_type: Category — must be in ``_VALID_ENTRY_TYPES``.
            title: Short title for the entry.
            content: Full body text.
            market_context: Snapshot of market conditions.
            related_decisions: List of ``AgentDecision`` UUID strings.
            tags: Auto-extracted topic tags.

        Returns:
            The server-assigned UUID string.  Returns empty string on failure.
        """
        try:
            from src.database.models import AgentJournal  # noqa: PLC0415
            from src.database.repositories.agent_journal_repo import (  # noqa: PLC0415
                AgentJournalRepository,
            )
            from src.database.session import get_session_factory  # noqa: PLC0415
        except ImportError:
            return ""

        try:
            agent_uuid = UUID(agent_id)
        except (ValueError, AttributeError):
            return ""

        try:
            factory = get_session_factory()
            session = factory()
            async with session.begin():
                repo = AgentJournalRepository(session)
                row = AgentJournal(
                    agent_id=agent_uuid,
                    entry_type=entry_type,
                    title=title[:255],  # enforce VARCHAR(255) limit
                    content=content,
                    market_context=market_context if market_context else None,
                    related_decisions=related_decisions if related_decisions else None,
                    tags=tags if tags else None,
                )
                await repo.create(row)
                return str(row.id)

        except Exception as exc:  # noqa: BLE001
            self._log.error(
                "agent.trade.journal.persist_journal_entry.error",
                agent_id=agent_id,
                entry_type=entry_type,
                error=str(exc),
            )
            return ""

    # ------------------------------------------------------------------
    # Private — LLM reflection
    # ------------------------------------------------------------------

    async def _llm_reflection(
        self, decision_row: dict[str, Any]
    ) -> TradeReflection | None:
        """Call the LLM to generate a structured :class:`~agent.models.ecosystem.TradeReflection`.

        Uses ``config.agent_cheap_model`` to minimise token costs.  Returns
        ``None`` on any failure so the caller can fall back to the template.

        Args:
            decision_row: Dict from :meth:`_fetch_decision` with full decision
                context.

        Returns:
            A :class:`~agent.models.ecosystem.TradeReflection` on success,
            or ``None`` on any error.
        """
        try:
            from pydantic_ai import Agent as PydanticAIAgent  # noqa: PLC0415
        except ImportError:
            self._log.debug(
                "agent.trade.journal.llm_reflection.pydantic_ai_unavailable",
                hint="Falling back to template reflection.",
            )
            return None

        pnl_str = decision_row.get("outcome_pnl") or "unknown"
        symbol = decision_row.get("symbol", "unknown")
        direction = decision_row.get("direction", "unknown")
        confidence = decision_row.get("confidence") or "unknown"
        reasoning = decision_row.get("reasoning") or ""
        risk_data = decision_row.get("risk_assessment") or {}
        mae_str = risk_data.get("max_adverse_excursion", "unknown")
        hold_duration = risk_data.get("hold_duration_seconds", "unknown")

        prompt = (
            f"You are reviewing a trade the agent just completed.\n\n"
            f"Trade details:\n"
            f"  Symbol: {symbol}\n"
            f"  Direction: {direction}\n"
            f"  Confidence at entry: {confidence}\n"
            f"  Realised PnL: {pnl_str} USDT\n"
            f"  Max adverse excursion: {mae_str} USDT\n"
            f"  Hold duration: {hold_duration} seconds\n\n"
            f"Reasoning at entry:\n{reasoning}\n\n"
            f"Please analyse this trade and produce a structured reflection.\n"
            f"Trade ID for reference: {decision_row.get('id', 'unknown')}"
        )

        try:
            import time as _time  # noqa: PLC0415

            from agent.logging_middleware import estimate_llm_cost  # noqa: PLC0415

            reflection_agent = PydanticAIAgent(
                model=self._config.agent_cheap_model,
                output_type=TradeReflection,
                system_prompt=(
                    "You are an expert trading coach reviewing a completed paper trade. "
                    "Provide honest, actionable feedback about entry quality, exit quality, "
                    "and concrete lessons. Be specific and quantitative where possible."
                ),
            )
            _llm_start = _time.monotonic()
            result = await reflection_agent.run(prompt)
            _latency_ms = round((_time.monotonic() - _llm_start) * 1000, 2)

            reflection: TradeReflection = result.output
            _input_tokens: int | None = getattr(
                getattr(result, "usage", None), "input_tokens", None
            )
            _output_tokens: int | None = getattr(
                getattr(result, "usage", None), "output_tokens", None
            )
            self._log.info(
                "agent.llm.completed",
                model=self._config.agent_cheap_model,
                purpose="trade_reflection",
                input_tokens=_input_tokens,
                output_tokens=_output_tokens,
                latency_ms=_latency_ms,
                cost_estimate_usd=estimate_llm_cost(
                    self._config.agent_cheap_model,
                    _input_tokens or 0,
                    _output_tokens or 0,
                ),
            )
            self._log.debug(
                "agent.trade.journal.llm_reflection.success",
                symbol=symbol,
                pnl=pnl_str,
                learnings_count=len(reflection.learnings),
            )
            return reflection

        except Exception as exc:  # noqa: BLE001
            self._log.warning(
                "agent.trade.journal.llm_reflection.llm_error",
                symbol=symbol,
                error=str(exc),
                hint="Falling back to template reflection.",
            )
            self._log.error(
                "agent.llm.failed",
                model=self._config.agent_cheap_model,
                purpose="trade_reflection",
                error=str(exc),
            )
            return None

    def _template_reflection(
        self, decision_row: dict[str, Any]
    ) -> TradeReflection:
        """Generate a deterministic template-based reflection when LLM is unavailable.

        Derives entry/exit quality from PnL and MAE heuristics without any
        LLM call.

        Args:
            decision_row: Dict from :meth:`_fetch_decision`.

        Returns:
            A :class:`~agent.models.ecosystem.TradeReflection` built from
            rule-based heuristics.
        """
        symbol = decision_row.get("symbol") or "unknown"
        direction = decision_row.get("direction") or "unknown"
        risk_data = decision_row.get("risk_assessment") or {}

        # Parse PnL.
        pnl_raw = decision_row.get("outcome_pnl")
        try:
            pnl = Decimal(str(pnl_raw)) if pnl_raw is not None else Decimal("0")
        except Exception:  # noqa: BLE001
            pnl = Decimal("0")

        # Parse MAE.
        mae_raw = risk_data.get("max_adverse_excursion", "0")
        try:
            mae = Decimal(str(mae_raw))
        except Exception:  # noqa: BLE001
            mae = Decimal("0")

        # Heuristic quality ratings.
        confidence_raw = decision_row.get("confidence")
        try:
            confidence = float(confidence_raw) if confidence_raw else 0.5
        except (TypeError, ValueError):
            confidence = 0.5

        entry_quality = "good" if confidence >= 0.7 else "neutral" if confidence >= 0.5 else "poor"
        exit_quality = "good" if pnl > Decimal("0") else "poor" if pnl < Decimal("-10") else "neutral"
        would_take_again = pnl >= Decimal("0") and confidence >= 0.6

        learnings: list[str] = []
        if pnl > Decimal("0"):
            learnings.append(
                f"Profitable {direction} on {symbol}: confidence {confidence:.0%} was justified."
            )
        elif pnl < Decimal("0"):
            learnings.append(
                f"Loss on {direction} {symbol}: review signal alignment before next entry."
            )
        if mae > abs(pnl) * Decimal("2") and abs(pnl) > Decimal("0"):
            learnings.append(
                f"High MAE ({mae:.2f} USDT) relative to outcome ({pnl:.2f} USDT): "
                "consider tighter stop-loss."
            )

        improvement = (
            "Review risk/reward ratio before entry. "
            f"Confidence was {confidence:.0%} — adjust threshold if below historical win rate."
        )

        return TradeReflection(
            trade_id=str(decision_row.get("id", "")),
            symbol=symbol,
            entry_quality=entry_quality,
            exit_quality=exit_quality,
            pnl=pnl,
            max_adverse_excursion=mae,
            learnings=learnings,
            would_take_again=would_take_again,
            improvement_notes=improvement,
        )

    # ------------------------------------------------------------------
    # Public — structured memory creation
    # ------------------------------------------------------------------

    async def save_episodic_memory(
        self,
        agent_id: str,
        decision_row: dict[str, Any],
        entry_price: Decimal | None = None,
        exit_price: Decimal | None = None,
        regime: str | None = None,
    ) -> str:
        """Save a structured EPISODIC memory for a completed trade.

        Encodes the factual record of what happened — entry/exit prices,
        realised PnL, market regime, and the reasoning chain — into a
        single :class:`~agent.memory.store.Memory` record of type
        ``EPISODIC``.  This gives the agent a searchable event log it
        can query later with ``search(symbol + regime)``.

        Args:
            agent_id: UUID string of the owning agent.
            decision_row: Dict from :meth:`_fetch_decision` with trade data.
            entry_price: Optional entry price captured at order placement.
                If not supplied, ``decision_row["market_snapshot"]`` is
                consulted as a fallback.
            exit_price: Optional exit price captured at position close.
            regime: Market regime string at the time of the trade (e.g.
                ``"trending_up"``, ``"ranging"``).  Falls back to the
                ``risk_assessment.detected_regime`` field if not supplied.

        Returns:
            The server-assigned UUID string of the persisted memory, or
            empty string if saving failed or no memory store is configured.

        Raises:
            *Never raises*.  All errors are caught and logged.
        """
        if self._memory_store is None:
            return ""

        try:
            from agent.memory.store import Memory, MemoryType  # noqa: PLC0415
        except ImportError:
            return ""

        symbol = decision_row.get("symbol", "unknown")
        direction = decision_row.get("direction", "unknown")
        pnl_raw = decision_row.get("outcome_pnl")
        pnl_str = f"{float(pnl_raw):.4f}" if pnl_raw is not None else "N/A"
        confidence = decision_row.get("confidence")
        confidence_str = f"{float(confidence):.0%}" if confidence else "unknown"
        reasoning_snippet = (decision_row.get("reasoning") or "")[:200]

        # Derive prices from snapshot if not explicitly provided.
        snapshot: dict[str, Any] = decision_row.get("market_snapshot") or {}
        entry_str = str(entry_price) if entry_price is not None else snapshot.get(symbol, "unknown")
        exit_str = str(exit_price) if exit_price is not None else "unknown"

        # Derive regime from risk assessment if not provided.
        risk_data: dict[str, Any] = decision_row.get("risk_assessment") or {}
        effective_regime = regime or risk_data.get("detected_regime", "unknown")

        content = (
            f"Trade {direction.upper()} {symbol} in {effective_regime} regime: "
            f"entry={entry_str}, exit={exit_str}, PnL={pnl_str} USDT, "
            f"confidence={confidence_str}. Reasoning: {reasoning_snippet}"
        )

        # Confidence of this memory tracks trade signal confidence.
        try:
            mem_confidence = Decimal(str(round(float(confidence), 4))) if confidence else Decimal("0.8000")
            mem_confidence = max(Decimal("0"), min(Decimal("1"), mem_confidence))
        except Exception:  # noqa: BLE001
            mem_confidence = Decimal("0.8000")

        now = datetime.now(UTC)
        try:
            mem = Memory(
                id="",
                agent_id=agent_id,
                memory_type=MemoryType.EPISODIC,
                content=content,
                source=f"trade_{decision_row.get('id', 'unknown')}",
                confidence=mem_confidence,
                times_reinforced=1,
                created_at=now,
                last_accessed_at=now,
            )
            memory_id = await self._memory_store.save(mem)
            self._log.debug(
                "agent.trade.journal.episodic_memory.saved",
                agent_id=agent_id,
                symbol=symbol,
                memory_id=memory_id,
                regime=effective_regime,
            )
            return memory_id
        except Exception as exc:  # noqa: BLE001
            self._log.warning(
                "agent.trade.journal.episodic_memory.save_error",
                agent_id=agent_id,
                symbol=symbol,
                error=str(exc),
            )
            return ""

    async def save_procedural_memory(
        self,
        agent_id: str,
        pattern: str,
        regime: str,
        symbol: str | None = None,
        confidence: Decimal | None = None,
        source: str = "trade_reflection",
    ) -> str:
        """Save or reinforce a PROCEDURAL memory encoding a trading rule.

        Encodes actionable pattern learnings such as "RSI divergence works
        well in trending regime for BTC" or "avoid entries when volume is
        below average in ranging markets".

        Before creating a new record, searches for existing procedural
        memories with similar content.  If a close match is found, that
        memory is reinforced instead of duplicating it.  This causes
        frequently-confirmed patterns to accumulate ``times_reinforced``
        count and surface higher in future retrieval scoring.

        Args:
            agent_id: UUID string of the owning agent.
            pattern: Human-readable rule or pattern discovered
                (e.g. ``"pattern RSI divergence worked in trending_up"``).
            regime: Market regime the pattern applies to.
            symbol: Optional trading pair the pattern applies to.  When
                provided, the content is scoped to that symbol.
            confidence: Certainty of this rule in ``[0, 1]``.  Defaults to
                ``Decimal("0.7500")``.
            source: Origin label for the memory record.

        Returns:
            The UUID string of the saved or reinforced memory, or empty
            string on any error.

        Raises:
            *Never raises*.  All errors are caught and logged.
        """
        if self._memory_store is None:
            return ""

        try:
            from agent.memory.store import Memory, MemoryType  # noqa: PLC0415
        except ImportError:
            return ""

        effective_confidence = confidence if confidence is not None else Decimal("0.7500")

        # Build the canonical content string for this procedural rule.
        scope = f" for {symbol}" if symbol else ""
        content = f"{pattern}{scope} in {regime} regime"

        # Search for an existing matching procedural memory to reinforce.
        try:
            query_terms = f"{symbol or ''} {regime}".strip()
            existing_memories = await self._memory_store.search(
                agent_id=agent_id,
                query=query_terms,
                memory_type=MemoryType.PROCEDURAL,
                limit=5,
            )
            for existing in existing_memories:
                # Treat any existing memory that overlaps significantly as a match.
                if (
                    regime.lower() in existing.content.lower()
                    and (symbol is None or symbol.lower() in existing.content.lower())
                    and len(set(pattern.lower().split()) & set(existing.content.lower().split())) >= 2  # noqa: PLR2004
                ):
                    await self._memory_store.reinforce(existing.id)
                    self._log.debug(
                        "agent.trade.journal.procedural_memory.reinforced",
                        agent_id=agent_id,
                        memory_id=existing.id,
                        times_reinforced=existing.times_reinforced + 1,
                        regime=regime,
                    )
                    return existing.id
        except Exception as exc:  # noqa: BLE001
            self._log.debug(
                "agent.trade.journal.procedural_memory.search_error",
                agent_id=agent_id,
                error=str(exc),
                hint="Proceeding to save new memory.",
            )

        # No matching memory found — create a new one.
        now = datetime.now(UTC)
        try:
            mem = Memory(
                id="",
                agent_id=agent_id,
                memory_type=MemoryType.PROCEDURAL,
                content=content,
                source=source,
                confidence=effective_confidence,
                times_reinforced=1,
                created_at=now,
                last_accessed_at=now,
            )
            memory_id = await self._memory_store.save(mem)
            self._log.debug(
                "agent.trade.journal.procedural_memory.saved",
                agent_id=agent_id,
                symbol=symbol,
                regime=regime,
                memory_id=memory_id,
            )
            return memory_id
        except Exception as exc:  # noqa: BLE001
            self._log.warning(
                "agent.trade.journal.procedural_memory.save_error",
                agent_id=agent_id,
                pattern=pattern[:60],
                error=str(exc),
            )
            return ""

    # ------------------------------------------------------------------
    # Private — memory store integration
    # ------------------------------------------------------------------

    async def _save_learnings_to_memory(
        self,
        agent_id: str,
        learnings: list[str],
        source: str,
        decision_row: dict[str, Any] | None = None,
    ) -> None:
        """Save extracted learnings to the agent memory store.

        Each learning string is classified as EPISODIC or PROCEDURAL based
        on its content, then stored as a separate
        :class:`~agent.memory.store.Memory` record.  Strings that match
        procedural patterns (contain keywords like "avoid", "always",
        "works in", "regime") are saved as PROCEDURAL — the rest are
        saved as EPISODIC.

        When a ``decision_row`` is supplied, this method also calls
        :meth:`save_episodic_memory` to store the full structured trade
        event and :meth:`save_procedural_memory` for any regime-specific
        patterns extracted from the learnings.

        Failures are logged and silently swallowed — memory persistence must
        never block the reflection pipeline.

        Args:
            agent_id: UUID string of the owning agent.
            learnings: Concrete lesson strings to persist.
            source: Origin reference (e.g. ``"reflection_<decision_id>"``).
            decision_row: Optional full decision dict from
                :meth:`_fetch_decision`.  When provided, a structured EPISODIC
                memory is also saved and any regime-scoped rules are saved
                as PROCEDURAL memories.
        """
        if not learnings:
            return

        if self._memory_store is None:
            self._log.debug(
                "agent.trade.journal.save_learnings.no_store",
                hint="No memory store injected — skipping learning persistence.",
            )
            return

        try:
            from agent.memory.store import Memory, MemoryType  # noqa: PLC0415
        except ImportError:
            self._log.debug("agent.trade.journal.save_learnings.import_failed")
            return

        # Derive regime from decision_row for procedural classification.
        regime: str | None = None
        symbol: str | None = None
        if decision_row is not None:
            risk_data: dict[str, Any] = decision_row.get("risk_assessment") or {}
            regime = risk_data.get("detected_regime")
            symbol = decision_row.get("symbol")

        # Keywords that indicate a procedural (rule-based) learning.
        _PROCEDURAL_KEYWORDS = frozenset({
            "avoid", "always", "never", "works in", "regime", "pattern",
            "rule", "when", "should", "must", "consider",
        })

        now = datetime.now(UTC)

        async def _save_one(content: str) -> None:
            try:
                lower = content.lower()
                is_procedural = any(kw in lower for kw in _PROCEDURAL_KEYWORDS)

                if is_procedural and regime:
                    # Delegate to save_procedural_memory for dedup + reinforce.
                    await self.save_procedural_memory(
                        agent_id=agent_id,
                        pattern=content,
                        regime=regime,
                        symbol=symbol,
                        confidence=Decimal("0.7500"),
                        source=source,
                    )
                else:
                    mem = Memory(
                        id="",
                        agent_id=agent_id,
                        memory_type=MemoryType.PROCEDURAL if is_procedural else MemoryType.EPISODIC,
                        content=content,
                        source=source,
                        confidence=Decimal("0.8000"),
                        times_reinforced=1,
                        created_at=now,
                        last_accessed_at=now,
                    )
                    await self._memory_store.save(mem)
            except Exception as exc:  # noqa: BLE001
                self._log.warning(
                    "agent.trade.journal.save_learnings.save_error",
                    content_preview=content[:60],
                    error=str(exc),
                )

        # Save all learnings concurrently; individual failures do not abort others.
        await asyncio.gather(*[_save_one(item) for item in learnings])

        self._log.debug(
            "agent.trade.journal.save_learnings.success",
            agent_id=agent_id,
            count=len(learnings),
            source=source,
        )

    # ------------------------------------------------------------------
    # Private — analytics helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_decision_stats(decisions: list[dict[str, Any]]) -> dict[str, Any]:
        """Compute aggregate statistics from a list of decision dicts.

        Args:
            decisions: List of decision dicts from the database.

        Returns:
            Dict with keys: ``total``, ``trades``, ``holds``, ``buys``,
            ``sells``, ``with_outcome``, ``wins``, ``losses``, ``win_rate``,
            ``total_pnl``, ``avg_pnl``, ``avg_confidence``, ``symbols``.
        """
        total = len(decisions)
        trades = sum(1 for d in decisions if d.get("decision_type") == "trade")
        holds = sum(1 for d in decisions if d.get("decision_type") == "hold")
        buys = sum(1 for d in decisions if d.get("direction") == "buy")
        sells = sum(1 for d in decisions if d.get("direction") == "sell")

        outcomes = [d for d in decisions if d.get("outcome_pnl") is not None]
        wins = sum(1 for d in outcomes if (d.get("outcome_pnl") or 0) > 0)
        losses = sum(1 for d in outcomes if (d.get("outcome_pnl") or 0) < 0)
        win_rate = wins / len(outcomes) if outcomes else 0.0

        pnl_values = [float(d["outcome_pnl"]) for d in outcomes]
        total_pnl = sum(pnl_values)
        avg_pnl = total_pnl / len(pnl_values) if pnl_values else 0.0

        confidences = [
            float(d["confidence"])
            for d in decisions
            if d.get("confidence") is not None
        ]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        symbols: list[str] = list(
            {d["symbol"] for d in decisions if d.get("symbol")}
        )

        return {
            "total": total,
            "trades": trades,
            "holds": holds,
            "buys": buys,
            "sells": sells,
            "with_outcome": len(outcomes),
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 4),
            "total_pnl": round(total_pnl, 4),
            "avg_pnl": round(avg_pnl, 4),
            "avg_confidence": round(avg_confidence, 4),
            "symbols": symbols,
        }

    @staticmethod
    def _find_best_trade(
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Return the decision with the highest realised PnL.

        Args:
            decisions: List of decision dicts.

        Returns:
            The best trade dict or ``None`` if no outcomes exist.
        """
        outcomes = [d for d in decisions if d.get("outcome_pnl") is not None]
        if not outcomes:
            return None
        return max(outcomes, key=lambda d: float(d.get("outcome_pnl") or 0))

    @staticmethod
    def _find_worst_trade(
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Return the decision with the lowest realised PnL.

        Args:
            decisions: List of decision dicts.

        Returns:
            The worst trade dict or ``None`` if no outcomes exist.
        """
        outcomes = [d for d in decisions if d.get("outcome_pnl") is not None]
        if not outcomes:
            return None
        return min(outcomes, key=lambda d: float(d.get("outcome_pnl") or 0))

    @staticmethod
    def _analyse_strategy_performance(
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Break down outcomes by dominant signal source / regime.

        Reads ``risk_assessment.source_contributions`` and
        ``signals[*].regime`` from each decision to produce a per-source
        summary.

        Args:
            decisions: List of decision dicts.

        Returns:
            Dict mapping source name → ``{trades, wins, total_pnl, win_rate}``.
        """
        source_map: dict[str, dict[str, Any]] = {}

        for d in decisions:
            if d.get("outcome_pnl") is None:
                continue

            risk = d.get("risk_assessment") or {}
            sources: dict[str, float] = risk.get("source_contributions") or {}
            pnl = float(d.get("outcome_pnl") or 0)

            if not sources:
                # Fall back to using the direction as a pseudo-source.
                sources = {d.get("direction", "unknown"): 1.0}

            # Credit the dominant source.
            dominant = max(sources, key=lambda k: float(sources[k]))  # type: ignore[arg-type]
            entry = source_map.setdefault(
                dominant, {"trades": 0, "wins": 0, "total_pnl": 0.0}
            )
            entry["trades"] += 1
            entry["total_pnl"] += pnl
            if pnl > 0:
                entry["wins"] += 1

        for k, v in source_map.items():
            v["win_rate"] = round(v["wins"] / v["trades"], 4) if v["trades"] > 0 else 0.0
            v["total_pnl"] = round(v["total_pnl"], 4)

        return source_map

    # ------------------------------------------------------------------
    # Private — formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_reflection_content(
        reflection: TradeReflection,
        decision_row: dict[str, Any],
    ) -> str:
        """Format a :class:`~agent.models.ecosystem.TradeReflection` as prose.

        Args:
            reflection: The structured reflection.
            decision_row: Original decision dict for supplementary context.

        Returns:
            Multi-line string suitable for storage in ``agent_journal.content``.
        """
        symbol = decision_row.get("symbol", "unknown")
        direction = decision_row.get("direction", "unknown")
        pnl_str = str(reflection.pnl)
        mae_str = str(reflection.max_adverse_excursion)
        lines = [
            f"## Trade Reflection: {symbol} {direction.upper()}",
            "",
            f"**Entry quality:** {reflection.entry_quality}  ",
            f"**Exit quality:** {reflection.exit_quality}  ",
            f"**Realised PnL:** {pnl_str} USDT  ",
            f"**Max adverse excursion:** {mae_str} USDT  ",
            f"**Would trade again:** {'Yes' if reflection.would_take_again else 'No'}",
            "",
            "### Learnings",
        ]
        for i, learning in enumerate(reflection.learnings, start=1):
            lines.append(f"{i}. {learning}")

        if reflection.improvement_notes:
            lines.extend(["", "### Improvement Notes", reflection.improvement_notes])

        return "\n".join(lines)

    @staticmethod
    def _format_daily_summary(
        date: DateType,
        stats: dict[str, Any],
        decisions: list[dict[str, Any]],
    ) -> str:
        """Format a daily decision summary as prose.

        Args:
            date: The date being summarised.
            stats: Output from :meth:`_compute_decision_stats`.
            decisions: Raw decision dicts for sampling.

        Returns:
            Multi-line string suitable for storage in ``agent_journal.content``.
        """
        symbols_str = ", ".join(stats.get("symbols") or []) or "none"
        lines = [
            f"## Daily Summary — {date}",
            "",
            f"**Total decisions:** {stats['total']}  ",
            f"**Trades taken:** {stats['trades']}  ",
            f"**Holds:** {stats['holds']}  ",
            f"**Buys / Sells:** {stats['buys']} / {stats['sells']}  ",
            f"**Symbols traded:** {symbols_str}",
            "",
            "### Outcomes",
            f"**Decisions with outcomes:** {stats['with_outcome']}  ",
            f"**Wins:** {stats['wins']}  ",
            f"**Losses:** {stats['losses']}  ",
            f"**Win rate:** {stats['win_rate']:.1%}  ",
            f"**Total PnL:** {stats['total_pnl']:.4f} USDT  ",
            f"**Avg PnL per trade:** {stats['avg_pnl']:.4f} USDT",
            "",
            "### Signal Quality",
            f"**Avg confidence:** {stats['avg_confidence']:.1%}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _format_weekly_review(
        week_start: DateType,
        week_end: DateType,
        stats: dict[str, Any],
        best_trade: dict[str, Any] | None,
        worst_trade: dict[str, Any] | None,
        strategy_breakdown: dict[str, Any],
    ) -> str:
        """Format a weekly review as prose.

        Args:
            week_start: First date of the review window.
            week_end: Last date of the review window.
            stats: Output from :meth:`_compute_decision_stats`.
            best_trade: The best-performing decision dict or ``None``.
            worst_trade: The worst-performing decision dict or ``None``.
            strategy_breakdown: Output from :meth:`_analyse_strategy_performance`.

        Returns:
            Multi-line string suitable for storage in ``agent_journal.content``.
        """
        symbols_str = ", ".join(stats.get("symbols") or []) or "none"
        lines = [
            f"## Weekly Review — {week_start} to {week_end}",
            "",
            f"**Total decisions:** {stats['total']}  ",
            f"**Trades taken:** {stats['trades']}  ",
            f"**Symbols:** {symbols_str}",
            "",
            "### Performance",
            f"**Win rate:** {stats['win_rate']:.1%}  ",
            f"**Total PnL:** {stats['total_pnl']:.4f} USDT  ",
            f"**Avg PnL per trade:** {stats['avg_pnl']:.4f} USDT  ",
            f"**Avg confidence:** {stats['avg_confidence']:.1%}",
            "",
        ]

        if best_trade:
            lines += [
                "### Best Trade",
                f"  Symbol: {best_trade.get('symbol', 'N/A')}  ",
                f"  Direction: {best_trade.get('direction', 'N/A')}  ",
                f"  PnL: {best_trade.get('outcome_pnl', 'N/A')} USDT",
                "",
            ]

        if worst_trade:
            lines += [
                "### Worst Trade",
                f"  Symbol: {worst_trade.get('symbol', 'N/A')}  ",
                f"  Direction: {worst_trade.get('direction', 'N/A')}  ",
                f"  PnL: {worst_trade.get('outcome_pnl', 'N/A')} USDT",
                "",
            ]

        if strategy_breakdown:
            lines.append("### Strategy Performance")
            for source, data in sorted(
                strategy_breakdown.items(),
                key=lambda kv: kv[1].get("total_pnl", 0),
                reverse=True,
            ):
                lines.append(
                    f"  **{source}**: {data['trades']} trades, "
                    f"win_rate={data['win_rate']:.1%}, "
                    f"PnL={data['total_pnl']:.4f} USDT"
                )
            lines.append("")

        # Pattern identification from stats.
        lines.append("### Patterns Identified")
        if stats["win_rate"] >= 0.6:
            lines.append("- Solid week: win rate above 60 %.")
        elif stats["win_rate"] < 0.4:
            lines.append("- Poor week: win rate below 40 % — review signal thresholds.")
        if stats["avg_confidence"] < 0.65:
            lines.append("- Average confidence below 65 % — consider raising the entry bar.")
        if stats["total_pnl"] > 0:
            lines.append(f"- Net profitable week: +{stats['total_pnl']:.4f} USDT.")
        else:
            lines.append(f"- Net losing week: {stats['total_pnl']:.4f} USDT — review risk settings.")

        return "\n".join(lines)

    @staticmethod
    def _extract_tags(reflection: TradeReflection | None) -> list[str]:
        """Extract topic tags from a reflection for the journal row.

        Args:
            reflection: The structured reflection or ``None``.

        Returns:
            A list of lowercase tag strings (e.g. ``["good_entry", "pnl_positive"]``).
        """
        if reflection is None:
            return []

        tags: list[str] = []

        if reflection.entry_quality == "good":
            tags.append("good_entry")
        elif reflection.entry_quality == "poor":
            tags.append("poor_entry")

        if reflection.exit_quality == "poor":
            tags.append("exit_timing")

        if reflection.pnl > Decimal("0"):
            tags.append("pnl_positive")
        elif reflection.pnl < Decimal("0"):
            tags.append("pnl_negative")

        if reflection.max_adverse_excursion > abs(reflection.pnl) * Decimal("2"):
            tags.append("high_mae")

        if reflection.would_take_again:
            tags.append("repeatable")
        else:
            tags.append("avoid_repeat")

        # Tags from learning keywords.
        for learning in reflection.learnings:
            lower = learning.lower()
            if "stop" in lower:
                tags.append("stop_loss")
            if "momentum" in lower or "regime" in lower:
                tags.append("regime_aware")
            if "entry" in lower:
                tags.append("entry_timing")

        return list(dict.fromkeys(tags))  # deduplicate preserving order

    @staticmethod
    def _build_summary_tags(stats: dict[str, Any]) -> list[str]:
        """Build tags for a daily/weekly summary based on aggregate stats.

        Args:
            stats: Output from :meth:`_compute_decision_stats`.

        Returns:
            A list of lowercase tag strings.
        """
        tags: list[str] = []
        win_rate = stats.get("win_rate", 0.0)
        total_pnl = stats.get("total_pnl", 0.0)
        avg_confidence = stats.get("avg_confidence", 0.0)

        if win_rate >= 0.6:
            tags.append("high_win_rate")
        elif win_rate < 0.4:
            tags.append("low_win_rate")

        if total_pnl > 0:
            tags.append("net_profitable")
        elif total_pnl < 0:
            tags.append("net_loss")

        if avg_confidence >= 0.75:
            tags.append("high_confidence")
        elif avg_confidence < 0.55:
            tags.append("low_confidence")

        symbols: list[str] = stats.get("symbols") or []
        for sym in symbols:
            tags.append(sym.lower())

        return tags

    @staticmethod
    def _empty_journal_entry(entry_type: str) -> JournalEntry:
        """Return a minimal placeholder JournalEntry for error paths.

        Args:
            entry_type: The intended entry type.

        Returns:
            A :class:`~agent.models.ecosystem.JournalEntry` with empty content.
        """
        return JournalEntry(
            entry_id="",
            entry_type=entry_type,
            content="Journal entry could not be generated.",
            market_context={},
            tags=[],
            created_at=datetime.now(UTC),
        )
