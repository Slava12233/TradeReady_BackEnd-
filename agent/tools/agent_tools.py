"""Agent-specific tool functions: reflect_on_trade, review_portfolio,
scan_opportunities, journal_entry, and request_platform_feature.

These tools are designed for use by the autonomous trading agent to perform
post-trade reflection, periodic portfolio review, opportunity scanning, free-form
journaling, and platform feature requests.  Unlike the SDK and REST tools (which
wrap platform API calls), these tools read from and write to the platform's
internal database directly — persisting outputs to ``agent_journal``,
``agent_feedback``, and ``agent_learnings``.

Both tools accept a ``agent_id`` and optional ``session`` context via their
dependency arguments, and they return structured Pydantic v2 output models from
:mod:`agent.models.ecosystem` so the LLM can reason about the results.

Architecture note
-----------------
The agent package normally communicates with the platform exclusively through
the SDK/REST/MCP layers.  These tools are the deliberate exception: they run
inside the same Python process as the platform and need direct database and
Redis access for low-latency read-back of observations and atomic persistence.
This is only safe when the agent is co-located with the platform (e.g. in the
Docker Compose stack).  Never call these tools against a remote database.

Usage::

    from agent.config import AgentConfig
    from agent.tools.agent_tools import get_agent_tools

    config = AgentConfig()
    tools = get_agent_tools(config, agent_id="<uuid-string>")
    # Pass tools to pydantic_ai.Agent(tools=tools)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog

from agent.config import AgentConfig
from agent.models.ecosystem import FeedbackEntry, JournalEntry, Opportunity, PortfolioReview, TradeReflection

logger = structlog.get_logger(__name__)

# Concentration threshold above which a single position is flagged as a risk.
_HIGH_CONCENTRATION_THRESHOLD: float = 0.30

# Fraction of total portfolio in a single asset considered extreme.
_EXTREME_CONCENTRATION_THRESHOLD: float = 0.50

# Budget utilisation fraction above which an "approaching limit" flag is raised.
_BUDGET_UTILIZATION_WARNING: float = 0.75

# Maximum number of opportunities returned by scan_opportunities.
_MAX_OPPORTUNITIES: int = 10

# Minimum signal strength threshold for an opportunity to be returned.
_MIN_SIGNAL_STRENGTH: float = 0.30

# Stop-loss distance as a fraction of entry price for opportunity suggestions.
_DEFAULT_STOP_LOSS_PCT: Decimal = Decimal("0.02")

# Take-profit distance as a fraction of entry price for opportunity suggestions.
_DEFAULT_TAKE_PROFIT_PCT: Decimal = Decimal("0.04")

# Minimum risk/reward ratio for an opportunity to pass the filter.
_MIN_RISK_REWARD: float = 1.5

# Number of characters from the description to use as the auto-generated title.
_FEEDBACK_TITLE_MAX_LEN: int = 80

# Keywords that auto-tag a journal entry with specific topics.
_TAG_KEYWORD_MAP: dict[str, list[str]] = {
    "risk": ["risk", "stop", "loss", "drawdown", "protect", "limit"],
    "entry_timing": ["entry", "enter", "open position", "buy signal", "signal"],
    "exit_timing": ["exit", "close position", "take profit", "stop loss", "sell"],
    "momentum": ["momentum", "trend", "trending", "breakout", "volume"],
    "regime": ["regime", "market condition", "bull", "bear", "ranging"],
    "performance": ["performance", "sharpe", "win rate", "pnl", "profit"],
    "strategy": ["strategy", "algorithm", "parameter", "configuration"],
}


def get_agent_tools(config: AgentConfig, agent_id: str) -> list[Any]:  # noqa: ANN401
    """Build and return agent-specific tool functions for a Pydantic AI agent.

    The returned tools close over ``config`` and ``agent_id``.  They reach into
    the platform database directly using ``src.database.session`` and the
    repository classes.  The SDK client is used for live market and account data.

    Each tool manages its own database session (open → flush → commit → close)
    so that the caller does not need to supply a session context.

    Args:
        config: Resolved :class:`~agent.config.AgentConfig` with platform
            connectivity settings.
        agent_id: String UUID of the agent whose data these tools operate on.

    Returns:
        List of async tool functions ready to be passed to the Pydantic AI
        ``Agent`` constructor's ``tools=`` parameter.
    """
    # ── Shared SDK client (lazy import to keep startup fast) ──────────────────
    from agentexchange.async_client import AsyncAgentExchangeClient  # noqa: PLC0415
    from agentexchange.exceptions import AgentExchangeError  # noqa: PLC0415

    _sdk_client = AsyncAgentExchangeClient(
        api_key=config.platform_api_key,
        api_secret=config.platform_api_secret,
        base_url=config.platform_base_url,
    )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _open_session() -> Any:  # noqa: ANN401
        """Open and return a new SQLAlchemy AsyncSession."""
        from src.database.session import get_session_factory  # noqa: PLC0415

        return get_session_factory()()

    def _now_utc() -> datetime:
        """Return current UTC time (timezone-aware)."""
        return datetime.now(tz=UTC)

    # ── Tool: reflect_on_trade ────────────────────────────────────────────────

    async def reflect_on_trade(  # noqa: ANN202
        ctx: Any,  # noqa: ANN401
        trade_id: str,
    ) -> dict[str, Any]:
        """Perform a post-trade reflection on a completed trade and persist learnings.

        Fetches the trade details and any market observations captured near the
        trade execution time, then reasons about entry quality, exit quality,
        maximum adverse excursion, and what lessons can be drawn.  The structured
        reflection is saved to ``agent_journal`` and extracted learnings are
        written to ``agent_learnings``.

        Call this tool after a full trade round-trip (entry + exit) to build
        the agent's memory and improve future decision-making.

        Args:
            ctx:      Pydantic AI run context (injected automatically).
            trade_id: Platform-assigned trade ID string (format ``trd_...`` or
                      plain UUID) for the **entry** trade of the round-trip.
                      If you have only the exit trade ID, pass that instead —
                      the tool fetches recent trade history to find the pair.

        Returns:
            Serialised :class:`~agent.models.ecosystem.TradeReflection` dict
            with keys: ``trade_id``, ``symbol``, ``entry_quality``,
            ``exit_quality``, ``pnl``, ``max_adverse_excursion``,
            ``learnings``, ``would_take_again``, ``improvement_notes``.
            On failure returns ``{"error": "<message>"}``.
        """
        try:
            # ── 1. Fetch trade history from the SDK ───────────────────────────
            trades_raw = await _sdk_client.get_trade_history(limit=50)
            trade_data: dict[str, Any] | None = None
            for t in trades_raw:
                if str(t.trade_id) == trade_id or trade_id in str(t.trade_id):
                    trade_data = {
                        "trade_id": str(t.trade_id),
                        "symbol": t.symbol,
                        "side": t.side,
                        "quantity": str(t.quantity),
                        "price": str(t.price),
                        "fee": str(t.fee),
                        "total": str(t.total),
                        "executed_at": t.executed_at.isoformat(),
                    }
                    break

            if trade_data is None:
                logger.warning(
                    "reflect_on_trade.trade_not_found",
                    trade_id=trade_id,
                    agent_id=agent_id,
                )
                return {"error": f"Trade {trade_id!r} not found in recent history (last 50 trades)."}

            symbol: str = trade_data["symbol"]
            entry_side: str = trade_data["side"]
            entry_price = Decimal(trade_data["price"])

            # ── 2. Find paired exit trade (opposite side, same symbol) ────────
            exit_trade: dict[str, Any] | None = None
            entry_index: int | None = None
            for idx, t in enumerate(trades_raw):
                if str(t.trade_id) == trade_id:
                    entry_index = idx
                    break

            if entry_index is not None:
                exit_side = "sell" if entry_side == "buy" else "buy"
                for t in trades_raw[:entry_index]:
                    if t.symbol == symbol and t.side == exit_side:
                        exit_trade = {
                            "trade_id": str(t.trade_id),
                            "side": t.side,
                            "price": str(t.price),
                            "executed_at": t.executed_at.isoformat(),
                        }
                        break

            # ── 3. Fetch market observations for context ───────────────────────
            market_context: dict[str, Any] = {}
            current_price_str: str | None = None
            try:
                price_result = await _sdk_client.get_price(symbol)
                current_price_str = str(price_result.price)
                market_context["current_price"] = current_price_str
            except AgentExchangeError as exc:
                logger.warning(
                    "reflect_on_trade.price_fetch_failed",
                    symbol=symbol,
                    error=str(exc),
                )

            # Fetch recent candles as market context proxy
            try:
                candles = await _sdk_client.get_candles(symbol, interval="1h", limit=24)
                if candles:
                    recent = candles[-1]
                    market_context["recent_close"] = str(recent.close)
                    market_context["recent_high"] = str(recent.high)
                    market_context["recent_low"] = str(recent.low)
                    market_context["candles_fetched"] = len(candles)
            except AgentExchangeError as exc:
                logger.warning(
                    "reflect_on_trade.candles_fetch_failed",
                    symbol=symbol,
                    error=str(exc),
                )

            # ── 4. Query agent_observations for entry/exit context ─────────────
            obs_context: dict[str, Any] = {}
            try:
                from src.database.repositories.agent_observation_repo import (  # noqa: PLC0415
                    AgentObservationRepository,
                )
                from src.utils.exceptions import DatabaseError  # noqa: PLC0415

                session = _open_session()
                try:
                    obs_repo = AgentObservationRepository(session)
                    entry_dt = datetime.fromisoformat(trade_data["executed_at"])
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=UTC)

                    # Fetch observations within ±1 hour of the entry trade.
                    from datetime import timedelta  # noqa: PLC0415

                    obs_rows = await obs_repo.get_range(
                        agent_id=UUID(agent_id),
                        since=entry_dt - timedelta(hours=1),
                        until=entry_dt + timedelta(hours=1),
                        limit=5,
                    )
                    if obs_rows:
                        latest_obs = obs_rows[-1]
                        obs_context["regime_at_entry"] = latest_obs.regime
                        obs_context["prices_at_entry"] = latest_obs.prices
                    await session.close()
                except DatabaseError as db_exc:
                    logger.warning(
                        "reflect_on_trade.observations_fetch_failed",
                        agent_id=agent_id,
                        error=str(db_exc),
                    )
                    await session.close()
            except Exception as exc:  # noqa: BLE001
                # Observation fetch is non-critical — degrade gracefully.
                logger.warning(
                    "reflect_on_trade.observations_unavailable",
                    agent_id=agent_id,
                    error=str(exc),
                )

            # ── 5. Analyse entry/exit quality and compute metrics ──────────────
            # PnL calculation: for buy entry, PnL = (exit_price - entry_price) * qty
            quantity = Decimal(trade_data["quantity"])
            fee = Decimal(trade_data["fee"])
            pnl = Decimal("0")
            max_adverse_excursion = Decimal("0")

            if exit_trade is not None:
                exit_price = Decimal(exit_trade["price"])
                if entry_side == "buy":
                    pnl = (exit_price - entry_price) * quantity - fee
                else:
                    pnl = (entry_price - exit_price) * quantity - fee

                # MAE proxy: if current price moves against entry before exit
                if current_price_str is not None:
                    current_price = Decimal(current_price_str)
                    if entry_side == "buy":
                        adverse_move = entry_price - min(current_price, exit_price)
                    else:
                        adverse_move = max(current_price, exit_price) - entry_price
                    max_adverse_excursion = max(Decimal("0"), adverse_move * quantity)
            else:
                # No exit found; estimate MAE from current price movement
                if current_price_str is not None:
                    current_price = Decimal(current_price_str)
                    if entry_side == "buy":
                        adverse_move = entry_price - current_price
                    else:
                        adverse_move = current_price - entry_price
                    max_adverse_excursion = max(Decimal("0"), adverse_move * quantity)

            # Quality heuristics based on PnL and MAE
            if exit_trade is not None:
                exit_price_val = Decimal(exit_trade["price"])
                price_move_pct = abs(exit_price_val - entry_price) / entry_price if entry_price else Decimal("0")
                # Entry quality: good if trade captured > 60% of the subsequent move
                entry_quality = "good" if pnl > Decimal("0") else ("neutral" if pnl == Decimal("0") else "poor")
                # Exit quality: good if the exit price was near the high (buy) or low (sell) of the period
                exit_quality = "good" if pnl > Decimal("0") and price_move_pct > Decimal("0.005") else "neutral"
                if pnl < Decimal("0"):
                    exit_quality = "poor"
            else:
                entry_quality = "neutral"
                exit_quality = "neutral"

            # ── 6. Generate learnings from the analysis ────────────────────────
            learnings: list[str] = []
            improvement_notes: str = ""
            would_take_again: bool = pnl >= Decimal("0")

            if pnl > Decimal("0"):
                learnings.append(
                    f"Profitable {entry_side} trade on {symbol}: PnL {pnl:+.4f} USDT. "
                    "Entry and exit execution were effective."
                )
            elif pnl < Decimal("0"):
                learnings.append(
                    f"Loss on {entry_side} trade on {symbol}: PnL {pnl:.4f} USDT. "
                    "Review entry conditions and stop-loss placement."
                )
                improvement_notes = (
                    "Consider tighter stop-loss or waiting for stronger confirmation signal "
                    "before entering. Max adverse excursion of "
                    f"{max_adverse_excursion:.4f} USDT suggests position was exposed to risk early."
                )
                would_take_again = False
            else:
                learnings.append(
                    f"Break-even {entry_side} trade on {symbol}. "
                    "Entry timing appears neutral. Review exit trigger for optimisation."
                )

            if max_adverse_excursion > Decimal("0"):
                pos_value = entry_price * quantity
                mae_pct = (max_adverse_excursion / pos_value) * 100 if pos_value else Decimal("0")
                if mae_pct > Decimal("5"):
                    learnings.append(
                        f"High maximum adverse excursion ({mae_pct:.1f}% of position). "
                        "Consider tighter stop-loss to reduce drawdown exposure."
                    )

            if obs_context.get("regime_at_entry"):
                learnings.append(
                    f"Market regime at entry was '{obs_context['regime_at_entry']}'. "
                    "Verify this regime supported the trade direction."
                )

            if exit_trade is None:
                learnings.append(
                    "No matched exit trade found. This may be an open position — "
                    "re-run reflection once the position is closed."
                )

            # ── 7. Build structured reflection ────────────────────────────────
            reflection = TradeReflection(
                trade_id=trade_id,
                symbol=symbol,
                entry_quality=entry_quality,
                exit_quality=exit_quality,
                pnl=pnl,
                max_adverse_excursion=max_adverse_excursion,
                learnings=learnings,
                would_take_again=would_take_again,
                improvement_notes=improvement_notes,
            )

            # ── 8. Persist journal entry and learnings to the database ─────────
            try:
                from src.database.models import AgentJournal, AgentLearning  # noqa: PLC0415
                from src.database.repositories.agent_journal_repo import (  # noqa: PLC0415
                    AgentJournalRepository,
                )
                from src.database.repositories.agent_learning_repo import (  # noqa: PLC0415
                    AgentLearningRepository,
                )
                from src.utils.exceptions import DatabaseError as DBError  # noqa: PLC0415

                db_session = _open_session()
                try:
                    journal_repo = AgentJournalRepository(db_session)
                    learning_repo = AgentLearningRepository(db_session)

                    # Compose journal content
                    journal_content = (
                        f"Trade reflection for {trade_id} on {symbol}.\n"
                        f"Side: {entry_side} | Entry price: {entry_price} | "
                        f"PnL: {pnl:+.4f} USDT\n"
                        f"Entry quality: {entry_quality} | Exit quality: {exit_quality}\n"
                        f"Max adverse excursion: {max_adverse_excursion:.4f} USDT\n"
                        f"Would take again: {would_take_again}\n\n"
                        "Learnings:\n" + "\n".join(f"- {item}" for item in learnings)
                    )
                    if improvement_notes:
                        journal_content += f"\n\nImprovement notes:\n{improvement_notes}"

                    journal_entry = AgentJournal(
                        agent_id=UUID(agent_id),
                        entry_type="reflection",
                        title=f"Trade reflection: {symbol} {entry_side} {trade_id[:8]}",
                        content=journal_content,
                        market_context={
                            **market_context,
                            **obs_context,
                            "trade_id": trade_id,
                            "entry_price": str(entry_price),
                            "entry_side": entry_side,
                        },
                        related_decisions=None,
                        tags=["reflection", "trade", symbol.lower(), entry_side],
                    )
                    await journal_repo.create(journal_entry)

                    # Persist each learning as an AgentLearning record
                    now = _now_utc()
                    for learning_text in learnings:
                        # Classify memory type: losses/mistakes are episodic,
                        # rules/procedures are procedural, facts are semantic.
                        if any(
                            kw in learning_text.lower()
                            for kw in ("loss", "poor", "adverse", "consider", "review", "regime")
                        ):
                            mem_type = "procedural"
                        elif "profitable" in learning_text.lower() or "effective" in learning_text.lower():
                            mem_type = "episodic"
                        else:
                            mem_type = "semantic"

                        learning_row = AgentLearning(
                            agent_id=UUID(agent_id),
                            memory_type=mem_type,
                            content=learning_text,
                            source=f"reflect_on_trade:{trade_id}",
                            confidence=Decimal("0.8000"),
                            times_reinforced=1,
                            last_accessed_at=now,
                        )
                        await learning_repo.create(learning_row)

                    await db_session.commit()
                    logger.info(
                        "reflect_on_trade.persisted",
                        trade_id=trade_id,
                        agent_id=agent_id,
                        learnings_count=len(learnings),
                    )
                except DBError as db_exc:
                    await db_session.rollback()
                    logger.warning(
                        "reflect_on_trade.persist_failed",
                        trade_id=trade_id,
                        agent_id=agent_id,
                        error=str(db_exc),
                    )
                finally:
                    await db_session.close()
            except Exception as exc:  # noqa: BLE001
                # Persistence failure is non-fatal; return the reflection anyway.
                logger.warning(
                    "reflect_on_trade.db_unavailable",
                    trade_id=trade_id,
                    agent_id=agent_id,
                    error=str(exc),
                )

            return reflection.model_dump(mode="json")

        except AgentExchangeError as exc:
            logger.warning(
                "reflect_on_trade.sdk_error",
                trade_id=trade_id,
                agent_id=agent_id,
                error=str(exc),
            )
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "reflect_on_trade.unexpected_error",
                trade_id=trade_id,
                agent_id=agent_id,
                error=str(exc),
            )
            return {"error": f"Unexpected error during trade reflection: {exc}"}

    # ── Tool: review_portfolio ────────────────────────────────────────────────

    async def review_portfolio(  # noqa: ANN202
        ctx: Any,  # noqa: ANN401
    ) -> dict[str, Any]:
        """Perform a portfolio health review and persist the assessment to the journal.

        Fetches the current portfolio, calculates concentration risk, unrealised
        P&L, and budget utilisation, then generates actionable recommendations.
        The review is saved to ``agent_journal`` so the agent's learning loop
        can track portfolio health over time.

        Call this tool at the start of each trading cycle, after a large trade,
        or whenever the risk manager fires a warning.

        Args:
            ctx: Pydantic AI run context (injected automatically).

        Returns:
            Serialised :class:`~agent.models.ecosystem.PortfolioReview` dict
            with keys: ``total_value``, ``unrealized_pnl``,
            ``largest_position_pct``, ``num_open_positions``,
            ``budget_utilization_pct``, ``health_score``,
            ``recommendations``, ``risk_flags``.
            On failure returns ``{"error": "<message>"}``.
        """
        try:
            # ── 1. Fetch portfolio data via SDK ───────────────────────────────
            balances_raw = await _sdk_client.get_balance()
            positions_raw = await _sdk_client.get_positions()

            # Total portfolio value = USDT balance + sum of position market values
            usdt_balance = Decimal("0")
            for b in balances_raw:
                if b.asset == "USDT":
                    usdt_balance = b.total

            total_market_value = Decimal("0")
            unrealized_pnl = Decimal("0")
            position_values: list[tuple[str, Decimal]] = []

            for p in positions_raw:
                mkt_val = p.market_value
                pnl_val = p.unrealized_pnl
                total_market_value += mkt_val
                unrealized_pnl += pnl_val
                position_values.append((p.symbol, mkt_val))

            total_value = usdt_balance + total_market_value

            # ── 2. Calculate concentration metrics ────────────────────────────
            num_open_positions = len(position_values)
            largest_position_pct: float = 0.0
            largest_symbol: str = ""

            if total_value > Decimal("0") and position_values:
                largest_val = max(pv for _, pv in position_values)
                largest_position_pct = float(largest_val / total_value)
                largest_symbol = next(sym for sym, pv in position_values if pv == largest_val)

            # ── 3. Fetch budget utilisation from the database ─────────────────
            budget_utilization_pct: float = 0.0
            budget_data: dict[str, Any] = {}
            try:
                from src.database.repositories.agent_budget_repo import (  # noqa: PLC0415
                    AgentBudgetNotFoundError,
                    AgentBudgetRepository,
                )
                from src.utils.exceptions import DatabaseError as DBError  # noqa: PLC0415

                budget_session = _open_session()
                try:
                    budget_repo = AgentBudgetRepository(budget_session)
                    budget_row = await budget_repo.get_by_agent(UUID(agent_id))

                    max_trades = budget_row.max_trades_per_day or config.default_max_trades_per_day
                    if max_trades > 0 and budget_row.trades_today >= 0:
                        budget_utilization_pct = min(1.0, budget_row.trades_today / max_trades)

                    max_loss_pct = budget_row.max_daily_loss_pct or Decimal(str(config.default_max_daily_loss_pct))
                    max_loss_usdt = (
                        total_value * max_loss_pct / Decimal("100")
                        if total_value > Decimal("0")
                        else Decimal("0")
                    )

                    budget_data = {
                        "trades_today": budget_row.trades_today,
                        "max_trades_per_day": max_trades,
                        "loss_today": str(budget_row.loss_today),
                        "max_loss_usdt": str(max_loss_usdt),
                        "exposure_today": str(budget_row.exposure_today),
                        "max_exposure_pct": str(budget_row.max_exposure_pct),
                        "max_daily_loss_pct": str(max_loss_pct),
                    }
                except AgentBudgetNotFoundError:
                    logger.info(
                        "review_portfolio.no_budget_record",
                        agent_id=agent_id,
                    )
                except DBError as db_exc:
                    logger.warning(
                        "review_portfolio.budget_fetch_failed",
                        agent_id=agent_id,
                        error=str(db_exc),
                    )
                finally:
                    await budget_session.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "review_portfolio.budget_unavailable",
                    agent_id=agent_id,
                    error=str(exc),
                )

            # ── 4. Build recommendations and risk flags ────────────────────────
            recommendations: list[str] = []
            risk_flags: list[str] = []

            # Concentration risk
            if largest_position_pct > _EXTREME_CONCENTRATION_THRESHOLD:
                risk_flags.append(
                    f"Extreme concentration in {largest_symbol} "
                    f"({largest_position_pct:.0%} of portfolio). "
                    "Reduce immediately to avoid catastrophic single-asset loss."
                )
                recommendations.append(
                    f"Reduce {largest_symbol} position to below "
                    f"{int(_HIGH_CONCENTRATION_THRESHOLD * 100)}% of portfolio value."
                )
            elif largest_position_pct > _HIGH_CONCENTRATION_THRESHOLD:
                risk_flags.append(
                    f"High concentration in {largest_symbol} "
                    f"({largest_position_pct:.0%} of portfolio)."
                )
                recommendations.append(
                    f"Consider trimming {largest_symbol} position to reduce single-asset risk."
                )

            # Unrealised P&L check
            if total_value > Decimal("0"):
                unrealized_pnl_pct = float(unrealized_pnl / total_value)
                if unrealized_pnl_pct < -0.05:
                    risk_flags.append(
                        f"Significant unrealised loss: {unrealized_pnl_pct:.1%} of portfolio value."
                    )
                    recommendations.append(
                        "Review open positions with large unrealised losses. "
                        "Consider activating stop-losses to limit further drawdown."
                    )
                elif unrealized_pnl_pct > 0.10:
                    recommendations.append(
                        f"Strong unrealised gain ({unrealized_pnl_pct:.1%}). "
                        "Consider locking in some profits via partial exits or trailing stops."
                    )

            # Budget utilisation warnings
            if budget_utilization_pct >= _BUDGET_UTILIZATION_WARNING:
                if budget_utilization_pct >= 1.0:
                    risk_flags.append("Daily trade count limit reached. No further trades today.")
                    recommendations.append(
                        "Daily trade budget exhausted. Switch to monitoring mode until midnight reset."
                    )
                else:
                    risk_flags.append(
                        f"Approaching daily trade limit ({budget_utilization_pct:.0%} used)."
                    )
                    recommendations.append(
                        "Reserve remaining daily trade capacity for high-confidence opportunities only."
                    )

            if budget_data:
                loss_today = Decimal(budget_data.get("loss_today", "0"))
                max_loss_usdt = Decimal(budget_data.get("max_loss_usdt", "0"))
                if max_loss_usdt > Decimal("0"):
                    loss_utilization = float(loss_today / max_loss_usdt)
                    if loss_utilization >= _BUDGET_UTILIZATION_WARNING:
                        risk_flags.append(
                            f"Daily loss budget {loss_utilization:.0%} consumed "
                            f"({loss_today:.2f} of {max_loss_usdt:.2f} USDT)."
                        )
                        recommendations.append(
                            "Consider pausing trading — daily loss budget nearly exhausted."
                        )

            # No positions open
            if num_open_positions == 0:
                recommendations.append(
                    "No open positions. Consider scanning for opportunities if market conditions are favourable."
                )

            # ── 5. Compute health score ────────────────────────────────────────
            # Health = 1.0 degraded by: concentration, adverse PnL, budget usage.
            health_score: float = 1.0

            if largest_position_pct > _EXTREME_CONCENTRATION_THRESHOLD:
                health_score -= 0.40
            elif largest_position_pct > _HIGH_CONCENTRATION_THRESHOLD:
                health_score -= 0.20

            if total_value > Decimal("0"):
                upnl_pct = float(unrealized_pnl / total_value)
                if upnl_pct < -0.10:
                    health_score -= 0.30
                elif upnl_pct < -0.05:
                    health_score -= 0.15

            if budget_utilization_pct >= 1.0:
                health_score -= 0.20
            elif budget_utilization_pct >= _BUDGET_UTILIZATION_WARNING:
                health_score -= 0.10

            health_score = max(0.0, min(1.0, health_score))

            # ── 6. Build structured review ─────────────────────────────────────
            review = PortfolioReview(
                total_value=total_value,
                unrealized_pnl=unrealized_pnl,
                largest_position_pct=largest_position_pct,
                num_open_positions=num_open_positions,
                budget_utilization_pct=budget_utilization_pct,
                health_score=health_score,
                recommendations=recommendations,
                risk_flags=risk_flags,
            )

            # ── 7. Persist review to agent_journal ────────────────────────────
            try:
                from src.database.models import AgentJournal  # noqa: PLC0415
                from src.database.repositories.agent_journal_repo import (  # noqa: PLC0415
                    AgentJournalRepository,
                )
                from src.utils.exceptions import DatabaseError as DBError  # noqa: PLC0415

                journal_session = _open_session()
                try:
                    journal_repo = AgentJournalRepository(journal_session)

                    content_lines = [
                        f"Portfolio review — {_now_utc().strftime('%Y-%m-%d %H:%M UTC')}",
                        f"Total value: {total_value:.2f} USDT",
                        f"Unrealised P&L: {unrealized_pnl:+.2f} USDT",
                        f"Open positions: {num_open_positions}",
                        f"Largest position: {largest_position_pct:.1%}",
                        f"Budget utilisation: {budget_utilization_pct:.1%}",
                        f"Health score: {health_score:.2f}",
                        "",
                    ]
                    if risk_flags:
                        content_lines.append("Risk flags:")
                        content_lines.extend(f"  * {f}" for f in risk_flags)
                        content_lines.append("")
                    if recommendations:
                        content_lines.append("Recommendations:")
                        content_lines.extend(f"  - {r}" for r in recommendations)

                    journal_entry = AgentJournal(
                        agent_id=UUID(agent_id),
                        entry_type="insight",
                        title=f"Portfolio review {_now_utc().strftime('%Y-%m-%d')} — health {health_score:.2f}",
                        content="\n".join(content_lines),
                        market_context={
                            "total_value": str(total_value),
                            "unrealized_pnl": str(unrealized_pnl),
                            "num_open_positions": num_open_positions,
                            "largest_position_pct": largest_position_pct,
                            "budget_utilization_pct": budget_utilization_pct,
                            "health_score": health_score,
                            **budget_data,
                        },
                        related_decisions=None,
                        tags=["portfolio_review", "risk", "health"],
                    )
                    await journal_repo.create(journal_entry)
                    await journal_session.commit()
                    logger.info(
                        "review_portfolio.persisted",
                        agent_id=agent_id,
                        health_score=health_score,
                        risk_flags_count=len(risk_flags),
                    )
                except DBError as db_exc:
                    await journal_session.rollback()
                    logger.warning(
                        "review_portfolio.persist_failed",
                        agent_id=agent_id,
                        error=str(db_exc),
                    )
                finally:
                    await journal_session.close()
            except Exception as exc:  # noqa: BLE001
                # Journal persistence failure is non-fatal.
                logger.warning(
                    "review_portfolio.db_unavailable",
                    agent_id=agent_id,
                    error=str(exc),
                )

            return review.model_dump(mode="json")

        except AgentExchangeError as exc:
            logger.warning(
                "review_portfolio.sdk_error",
                agent_id=agent_id,
                error=str(exc),
            )
            return {"error": str(exc)}
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "review_portfolio.unexpected_error",
                agent_id=agent_id,
                error=str(exc),
            )
            return {"error": f"Unexpected error during portfolio review: {exc}"}

    # ── Tool: scan_opportunities ──────────────────────────────────────────────

    async def scan_opportunities(  # noqa: ANN202
        ctx: Any,  # noqa: ANN401
        criteria: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Scan current market prices for trading opportunities matching given criteria.

        Fetches all current prices from Redis (``HGETALL prices``), applies the
        caller-supplied filter criteria, cross-checks against existing open
        positions to avoid duplicates, ranks candidates by signal strength, and
        returns the top :data:`_MAX_OPPORTUNITIES` opportunities with entry, stop-
        loss, and take-profit suggestions.

        Supported criteria keys
        -----------------------
        - ``trending_up`` (bool) — include only pairs whose price has risen
          (detection proxy: change_pct > 0 from the ticker hash).
        - ``trending_down`` (bool) — include only pairs whose price has fallen.
        - ``min_price`` (str/float/int) — lower bound on current price (USDT).
        - ``max_price`` (str/float/int) — upper bound on current price (USDT).
        - ``symbols`` (list[str]) — restrict scan to this explicit symbol list.
        - ``top_n`` (int) — override the default :data:`_MAX_OPPORTUNITIES` cap.

        Unknown criteria keys are silently ignored so the LLM can experiment
        with additional filters without crashing the tool.

        Args:
            ctx:      Pydantic AI run context (injected automatically).
            criteria: Dict of filter criteria.  All keys are optional.

        Returns:
            List of serialised :class:`~agent.models.ecosystem.Opportunity`
            dicts, sorted descending by ``signal_strength``.  Returns
            ``[{"error": "<message>"}]`` on hard failures.
        """
        try:
            # ── 1. Fetch all current prices from Redis ─────────────────────────
            prices_raw: dict[str, str] = {}
            try:
                from src.cache.redis_client import get_redis_client  # noqa: PLC0415

                redis = await get_redis_client()
                prices_raw = await redis.hgetall("prices")
                logger.info(
                    "scan_opportunities.prices_fetched",
                    count=len(prices_raw),
                    agent_id=agent_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "scan_opportunities.redis_unavailable",
                    agent_id=agent_id,
                    error=str(exc),
                )
                # Fall back to SDK prices for the configured symbols
                for sym in config.symbols:
                    try:
                        p = await _sdk_client.get_price(sym)
                        prices_raw[sym] = str(p.price)
                    except AgentExchangeError:
                        pass

            if not prices_raw:
                return [{"error": "No price data available from Redis or SDK fallback."}]

            # ── 2. Fetch open positions to avoid recommending duplicates ───────
            open_symbols: set[str] = set()
            try:
                positions_raw = await _sdk_client.get_positions()
                open_symbols = {p.symbol for p in positions_raw}
            except AgentExchangeError as exc:
                logger.warning(
                    "scan_opportunities.positions_fetch_failed",
                    agent_id=agent_id,
                    error=str(exc),
                )

            # ── 3. Fetch ticker data for trend signals ─────────────────────────
            # Attempt to read change_pct from ticker hashes stored in Redis.
            ticker_change: dict[str, float] = {}
            try:
                from src.cache.redis_client import get_redis_client as _grc  # noqa: PLC0415

                redis2 = await _grc()
                for sym in list(prices_raw.keys())[:200]:  # cap to avoid latency
                    raw_ticker = await redis2.hgetall(f"ticker:{sym}")
                    if raw_ticker and "change_pct" in raw_ticker:
                        try:
                            ticker_change[sym] = float(raw_ticker["change_pct"])
                        except ValueError:
                            pass
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "scan_opportunities.ticker_fetch_failed",
                    error=str(exc),
                )

            # ── 4. Parse criteria filters ──────────────────────────────────────
            filter_trending_up: bool = bool(criteria.get("trending_up", False))
            filter_trending_down: bool = bool(criteria.get("trending_down", False))
            min_price_raw = criteria.get("min_price")
            max_price_raw = criteria.get("max_price")
            min_price: Decimal | None = Decimal(str(min_price_raw)) if min_price_raw is not None else None
            max_price: Decimal | None = Decimal(str(max_price_raw)) if max_price_raw is not None else None
            explicit_symbols: list[str] | None = criteria.get("symbols")
            top_n: int = int(criteria.get("top_n", _MAX_OPPORTUNITIES))

            # ── 5. Evaluate each symbol ────────────────────────────────────────
            candidates: list[tuple[float, Opportunity]] = []

            symbol_pool = explicit_symbols if explicit_symbols else list(prices_raw.keys())

            for sym in symbol_pool:
                if sym not in prices_raw:
                    continue
                if sym in open_symbols:
                    # Already have an open position — skip to avoid stacking.
                    continue

                try:
                    price = Decimal(prices_raw[sym])
                except Exception:  # noqa: BLE001
                    continue

                # Price range filter
                if min_price is not None and price < min_price:
                    continue
                if max_price is not None and price > max_price:
                    continue

                change_pct_val: float = ticker_change.get(sym, 0.0)

                # Trend filter
                if filter_trending_up and change_pct_val <= 0:
                    continue
                if filter_trending_down and change_pct_val >= 0:
                    continue

                # ── Signal strength heuristic ──────────────────────────────────
                # Use the absolute magnitude of the 24h price change as a proxy
                # for signal strength.  Normalise to [0.0, 1.0] by capping at
                # a ±10 % move being the "maximum" signal.
                abs_change = abs(change_pct_val)
                signal_strength = min(1.0, abs_change / 10.0)

                # Apply minimum threshold
                if signal_strength < _MIN_SIGNAL_STRENGTH and explicit_symbols is None:
                    continue

                # ── Direction ──────────────────────────────────────────────────
                if filter_trending_down:
                    direction = "short"
                else:
                    direction = "long"  # default to long

                # ── Entry / stop-loss / take-profit suggestions ────────────────
                entry_price = price
                if direction == "long":
                    stop_loss_price = entry_price * (1 - _DEFAULT_STOP_LOSS_PCT)
                    take_profit_price = entry_price * (1 + _DEFAULT_TAKE_PROFIT_PCT)
                else:
                    stop_loss_price = entry_price * (1 + _DEFAULT_STOP_LOSS_PCT)
                    take_profit_price = entry_price * (1 - _DEFAULT_TAKE_PROFIT_PCT)

                tp_dist = abs(take_profit_price - entry_price)
                sl_dist = abs(stop_loss_price - entry_price)
                risk_reward = float(tp_dist / sl_dist) if sl_dist > Decimal("0") else 0.0

                if risk_reward < _MIN_RISK_REWARD:
                    continue

                # ── Matched criteria tags ──────────────────────────────────────
                criteria_matched: list[str] = []
                if filter_trending_up and change_pct_val > 0:
                    criteria_matched.append("trending_up")
                if filter_trending_down and change_pct_val < 0:
                    criteria_matched.append("trending_down")
                if min_price is not None and price >= min_price:
                    criteria_matched.append("above_min_price")
                if max_price is not None and price <= max_price:
                    criteria_matched.append("below_max_price")
                if explicit_symbols and sym in explicit_symbols:
                    criteria_matched.append("in_requested_symbols")

                notes = (
                    f"24h change: {change_pct_val:+.2f}%. "
                    f"Signal strength derived from price momentum."
                )

                opp = Opportunity(
                    symbol=sym,
                    direction=direction,
                    signal_strength=signal_strength,
                    entry_price=entry_price,
                    stop_loss_price=stop_loss_price,
                    take_profit_price=take_profit_price,
                    risk_reward_ratio=risk_reward,
                    criteria_matched=criteria_matched,
                    notes=notes,
                )
                candidates.append((signal_strength, opp))

            # ── 6. Sort by signal strength descending and return top N ─────────
            candidates.sort(key=lambda t: t[0], reverse=True)
            results = [opp.model_dump(mode="json") for _, opp in candidates[:top_n]]

            logger.info(
                "scan_opportunities.complete",
                agent_id=agent_id,
                candidates_evaluated=len(candidates),
                results_returned=len(results),
            )
            return results

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "scan_opportunities.unexpected_error",
                agent_id=agent_id,
                error=str(exc),
            )
            return [{"error": f"Unexpected error during opportunity scan: {exc}"}]

    # ── Tool: journal_entry ───────────────────────────────────────────────────

    async def journal_entry(  # noqa: ANN202
        ctx: Any,  # noqa: ANN401
        content: str,
        entry_type: str = "reflection",
    ) -> dict[str, Any]:
        """Write a free-form journal entry and persist it with market context.

        Captures a snapshot of current market prices and portfolio state as
        context, auto-generates topic tags from keywords found in ``content``,
        and saves the entry to ``agent_journal``.

        Valid ``entry_type`` values (maps to DB CHECK constraint)
        ---------------------------------------------------------
        ``"reflection"`` — post-session reasoning (default)
        ``"insight"`` — new understanding or market observation
        ``"observation"`` — raw market observation without interpretation
        ``"daily_review"`` — end-of-day summary
        ``"weekly_review"`` — end-of-week retrospective

        Note: ``"daily_summary"`` and ``"ab_test"`` used in the Pydantic model
        are remapped to ``"daily_review"`` and ``"insight"`` respectively for
        DB compatibility.

        Args:
            ctx:        Pydantic AI run context (injected automatically).
            content:    Full text content to record in the journal.
            entry_type: Category for the journal entry.  Defaults to
                        ``"reflection"``.  Unknown types fall back to
                        ``"insight"``.

        Returns:
            Serialised :class:`~agent.models.ecosystem.JournalEntry` dict with
            keys: ``entry_id``, ``entry_type``, ``content``, ``market_context``,
            ``tags``, ``created_at``.
            On failure returns ``{"error": "<message>"}``.
        """
        # ── Map Pydantic model entry_type values to valid DB values ───────────
        _ENTRY_TYPE_MAP: dict[str, str] = {
            "reflection": "reflection",
            "daily_summary": "daily_review",
            "weekly_review": "weekly_review",
            "observation": "observation",
            "ab_test": "insight",
            "insight": "insight",
            "mistake": "mistake",
            "improvement": "improvement",
            "daily_review": "daily_review",
        }
        db_entry_type = _ENTRY_TYPE_MAP.get(entry_type, "insight")

        try:
            # ── 1. Capture current market context (top prices) ─────────────────
            market_context: dict[str, Any] = {
                "entry_type_requested": entry_type,
                "timestamp": _now_utc().isoformat(),
            }

            try:
                from src.cache.redis_client import get_redis_client  # noqa: PLC0415

                redis = await get_redis_client()
                prices_raw: dict[str, str] = await redis.hgetall("prices")
                # Store only the top 10 most relevant prices as context to
                # keep the JSONB payload compact.
                top_symbols = config.symbols + ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
                top_prices: dict[str, str] = {
                    sym: prices_raw[sym]
                    for sym in top_symbols
                    if sym in prices_raw
                }
                market_context["prices"] = top_prices
                market_context["total_pairs_tracked"] = len(prices_raw)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "journal_entry.price_fetch_failed",
                    agent_id=agent_id,
                    error=str(exc),
                )

            # ── 2. Capture portfolio state ─────────────────────────────────────
            try:
                positions_raw = await _sdk_client.get_positions()
                market_context["open_positions"] = len(positions_raw)
                market_context["open_symbols"] = [p.symbol for p in positions_raw]
            except AgentExchangeError as exc:
                logger.warning(
                    "journal_entry.positions_fetch_failed",
                    agent_id=agent_id,
                    error=str(exc),
                )

            # ── 3. Auto-tag content ────────────────────────────────────────────
            content_lower = content.lower()
            auto_tags: list[str] = []
            for tag, keywords in _TAG_KEYWORD_MAP.items():
                if any(kw in content_lower for kw in keywords):
                    auto_tags.append(tag)

            # Add the entry_type itself as a tag for searchability.
            if entry_type not in auto_tags:
                auto_tags.insert(0, entry_type)

            # ── 4. Persist to agent_journal ────────────────────────────────────
            saved_id: str = ""
            saved_at = _now_utc()

            try:
                from src.database.models import AgentJournal  # noqa: PLC0415
                from src.database.repositories.agent_journal_repo import (  # noqa: PLC0415
                    AgentJournalRepository,
                )
                from src.utils.exceptions import DatabaseError as DBError  # noqa: PLC0415

                db_session = _open_session()
                try:
                    journal_repo = AgentJournalRepository(db_session)

                    # Derive a short title from the first sentence of the content.
                    first_line = content.split("\n")[0][:80].strip()
                    title = first_line if first_line else f"Journal entry — {_now_utc().strftime('%Y-%m-%d %H:%M UTC')}"

                    journal_row = AgentJournal(
                        agent_id=UUID(agent_id),
                        entry_type=db_entry_type,
                        title=title,
                        content=content,
                        market_context=market_context,
                        related_decisions=None,
                        tags=auto_tags,
                    )
                    saved_row = await journal_repo.create(journal_row)
                    await db_session.commit()
                    saved_id = str(saved_row.id)
                    saved_at = saved_row.created_at
                    logger.info(
                        "journal_entry.persisted",
                        entry_id=saved_id,
                        agent_id=agent_id,
                        entry_type=db_entry_type,
                        tags=auto_tags,
                    )
                except DBError as db_exc:
                    await db_session.rollback()
                    logger.warning(
                        "journal_entry.persist_failed",
                        agent_id=agent_id,
                        error=str(db_exc),
                    )
                finally:
                    await db_session.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "journal_entry.db_unavailable",
                    agent_id=agent_id,
                    error=str(exc),
                )

            # ── 5. Build and return the output model ───────────────────────────
            result = JournalEntry(
                entry_id=saved_id,
                entry_type=entry_type,  # return the caller's original type
                content=content,
                market_context=market_context,
                tags=auto_tags,
                created_at=saved_at,
            )
            return result.model_dump(mode="json")

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "journal_entry.unexpected_error",
                agent_id=agent_id,
                error=str(exc),
            )
            return {"error": f"Unexpected error during journal entry: {exc}"}

    # ── Tool: request_platform_feature ────────────────────────────────────────

    async def request_platform_feature(  # noqa: ANN202
        ctx: Any,  # noqa: ANN401
        description: str,
        category: str = "feature_request",
    ) -> dict[str, Any]:
        """Submit a platform feature request or bug report to the feedback table.

        Before persisting, queries ``agent_feedback`` for existing entries with
        similar descriptions (case-insensitive ``ILIKE`` on the first 80 chars of
        ``description``) to prevent duplicate requests.  If a duplicate is found,
        returns the existing entry instead of creating a new one.

        Priority is inferred automatically
        -----------------------------------
        - ``"bug_report"`` → ``"high"``
        - ``"performance"`` → ``"medium"``
        - ``"feature_request"`` → ``"medium"``
        - ``"ux"`` → ``"low"``

        Category mapping (Pydantic → DB CHECK)
        ----------------------------------------
        - ``"feature_request"`` → ``"feature_request"``
        - ``"bug_report"`` → ``"bug"``
        - ``"performance"`` → ``"performance_issue"``
        - ``"ux"`` → ``"missing_tool"``  (closest available DB category)

        Args:
            ctx:         Pydantic AI run context (injected automatically).
            description: Full description of the requested feature or bug.
            category:    Category for the feedback.  Must be one of
                         ``"feature_request"``, ``"bug_report"``,
                         ``"performance"``, or ``"ux"``.  Defaults to
                         ``"feature_request"``.

        Returns:
            Serialised :class:`~agent.models.ecosystem.FeedbackEntry` dict with
            keys: ``feedback_id``, ``description``, ``category``, ``priority``,
            ``is_duplicate``, ``duplicate_of``, ``created_at``.
            On failure returns ``{"error": "<message>"}``.
        """
        # ── Category → DB value and priority mapping ──────────────────────────
        _CATEGORY_TO_DB: dict[str, str] = {
            "feature_request": "feature_request",
            "bug_report": "bug",
            "performance": "performance_issue",
            "ux": "missing_tool",
        }
        _CATEGORY_TO_PRIORITY: dict[str, str] = {
            "feature_request": "medium",
            "bug_report": "high",
            "performance": "medium",
            "ux": "low",
        }
        db_category = _CATEGORY_TO_DB.get(category, "feature_request")
        priority = _CATEGORY_TO_PRIORITY.get(category, "medium")

        try:
            from src.database.models import AgentFeedback  # noqa: PLC0415
            from src.database.repositories.agent_feedback_repo import (  # noqa: PLC0415
                AgentFeedbackRepository,
            )
            from src.utils.exceptions import DatabaseError as DBError  # noqa: PLC0415

            # ── 1. Deduplication — search for similar existing requests ────────
            is_duplicate: bool = False
            duplicate_of: str | None = None

            # Use the first 60 chars of the description as the search phrase to
            # avoid overly broad ILIKE matches on very short strings.
            search_phrase = description[:60].strip()

            db_session = _open_session()
            try:
                feedback_repo = AgentFeedbackRepository(db_session)

                # ILIKE search on description using SQLAlchemy
                from sqlalchemy import select  # noqa: PLC0415

                stmt = (
                    select(AgentFeedback)
                    .where(
                        AgentFeedback.agent_id == UUID(agent_id),
                        AgentFeedback.description.ilike(f"%{search_phrase}%"),
                    )
                    .order_by(AgentFeedback.created_at.desc())
                    .limit(1)
                )
                result_rows = await db_session.execute(stmt)
                existing = result_rows.scalars().first()

                if existing is not None:
                    is_duplicate = True
                    duplicate_of = str(existing.id)
                    logger.info(
                        "request_platform_feature.duplicate_detected",
                        existing_id=duplicate_of,
                        agent_id=agent_id,
                    )
                    # Return the existing entry without creating a new one.
                    existing_entry = FeedbackEntry(
                        feedback_id=duplicate_of,
                        description=existing.description,
                        category=category,
                        priority=priority,
                        is_duplicate=True,
                        duplicate_of=duplicate_of,
                        created_at=existing.created_at,
                    )
                    return existing_entry.model_dump(mode="json")

                # ── 2. No duplicate — create new feedback entry ────────────────
                title = description[:_FEEDBACK_TITLE_MAX_LEN].strip()
                if len(description) > _FEEDBACK_TITLE_MAX_LEN:
                    title = title.rstrip() + "…"

                feedback_row = AgentFeedback(
                    agent_id=UUID(agent_id),
                    category=db_category,
                    title=title,
                    description=description,
                    priority=priority,
                    status="new",
                )
                saved_row = await feedback_repo.create(feedback_row)
                await db_session.commit()
                saved_id = str(saved_row.id)
                saved_at = saved_row.created_at

                logger.info(
                    "request_platform_feature.persisted",
                    feedback_id=saved_id,
                    agent_id=agent_id,
                    category=db_category,
                    priority=priority,
                )

            except DBError as db_exc:
                await db_session.rollback()
                logger.warning(
                    "request_platform_feature.persist_failed",
                    agent_id=agent_id,
                    error=str(db_exc),
                )
                return {"error": f"Database error while saving feedback: {db_exc}"}
            finally:
                await db_session.close()

            # ── 3. Build and return the output model ───────────────────────────
            result = FeedbackEntry(
                feedback_id=saved_id,
                description=description,
                category=category,
                priority=priority,
                is_duplicate=is_duplicate,
                duplicate_of=duplicate_of,
                created_at=saved_at,
            )
            return result.model_dump(mode="json")

        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "request_platform_feature.unexpected_error",
                agent_id=agent_id,
                error=str(exc),
            )
            return {"error": f"Unexpected error during feature request: {exc}"}

    return [
        reflect_on_trade,
        review_portfolio,
        scan_opportunities,
        journal_entry,
        request_platform_feature,
    ]
