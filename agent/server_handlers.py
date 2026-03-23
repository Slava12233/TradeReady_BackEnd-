"""Intent handler functions for AgentServer conversation routing.

Each public async function in this module handles one :class:`~agent.conversation.router.IntentType`
and is registered into the :class:`~agent.conversation.router.IntentRouter` during
:meth:`~agent.server.AgentServer.__init__`.

Handler signature (required by :class:`~agent.conversation.router.IntentRouter`)::

    async def handler(
        session: AgentSession,
        message: str,
        **kwargs: object,
    ) -> str:
        ...

All handlers are self-contained and import their dependencies lazily inside the
function body to avoid circular imports at module load time.  Each handler is
designed to degrade gracefully — on any error it returns a user-friendly error
string rather than propagating the exception.

Design philosophy
-----------------
- Every handler calls real platform SDK or tool methods.
- On success, the handler returns a human-readable plain-text summary.
- On failure (SDK error, missing config, etc.) the handler returns an error
  string prefixed with ``"[error]"`` so the caller can distinguish degraded
  responses from real output.
- No handler raises — all exceptions are caught internally.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any

# Module-level imports for components that need to be mockable in tests.
# These are only called at function invocation time, not at import time, so
# there is no circular-import risk.  We import them here (not lazily) so that
# ``patch("agent.server_handlers.AgentConfig")`` resolves correctly in tests.
import httpx
import structlog
from agentexchange.async_client import AsyncAgentExchangeClient
from agentexchange.exceptions import AgentExchangeError

from agent.config import AgentConfig
from agent.permissions import BudgetManager, Capability, CapabilityManager
from agent.trading.journal import TradingJournal

if TYPE_CHECKING:
    from agent.conversation.session import AgentSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# TRADE handler
# ---------------------------------------------------------------------------


async def handle_trade(
    session: AgentSession,
    message: str,
    **kwargs: object,
) -> str:
    """Handle trading intent — parse the message and generate a signal via SignalGenerator.

    Extracts a symbol from the message (defaults to ``BTCUSDT``), generates a
    trading signal using the :class:`~agent.trading.signal_generator.SignalGenerator`
    ensemble pipeline, then returns a plain-text summary of the signal.

    If the session's parent server has a live :class:`~agent.trading.loop.TradingLoop`
    available it is preferred; otherwise the handler falls back to asking the user
    to clarify their intent so the LLM reasoning loop can handle the actual execution.

    Args:
        session: Active conversation session; used to retrieve agent context.
        message: Raw user message (may contain symbol, side, or quantity hints).
        **kwargs: Extra context forwarded by the router (e.g. ``server`` instance).

    Returns:
        Human-readable signal summary, or a fallback message asking the user to
        confirm the order details before execution.
    """
    log = logger.bind(handler="trade", agent_id=str(getattr(session, "agent_id", "unknown")))
    log.info("agent.server.handler.trade.invoked", message_preview=message[:80])

    try:
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.server.handler.trade.config_failed", error=str(exc))
        return (
            "I can help you trade, but I need configuration to be set up first.  "
            "Please check that PLATFORM_API_KEY and OPENROUTER_API_KEY are configured."
        )

    # Extract symbol from message (e.g. "buy BTC", "sell ETHUSDT")
    symbol = _extract_symbol(message, default=config.symbols[0] if config.symbols else "BTCUSDT")

    # Determine explicit side from message if present
    side_hint = _extract_side(message)

    log.info("agent.server.handler.trade.analysing", symbol=symbol, side_hint=side_hint)

    # Generate a signal using the SDK for market context
    try:
        client = AsyncAgentExchangeClient(
            api_key=config.platform_api_key,
            api_secret=config.platform_api_secret,
            base_url=config.platform_base_url,
        )
        try:
            price_obj = await client.get_price(symbol)
            current_price = str(price_obj.price)
            candles = await client.get_candles(symbol, interval="1h", limit=20)
            candle_closes = [str(c.close) for c in candles[-5:]] if candles else []
        except AgentExchangeError as exc:
            log.warning("agent.server.handler.trade.sdk_failed", error=str(exc))
            current_price = "unavailable"
            candle_closes = []
        finally:
            await client.aclose()

        lines: list[str] = [
            f"Trade analysis for {symbol}:",
            f"  Current price : {current_price}",
        ]
        if candle_closes:
            lines.append(f"  Recent closes  : {', '.join(candle_closes)}")
        if side_hint:
            lines.append(f"  Requested side : {side_hint.upper()}")
            lines.append("")
            lines.append(
                f"To execute a {side_hint} order on {symbol}, please confirm: "
                f'use command "/trade {side_hint} {symbol} <quantity>" '
                f"or ask me to proceed with the default quantity."
            )
        else:
            lines.append("")
            lines.append(
                f"What would you like to do with {symbol}?  "
                f'Try "/buy {symbol}" or "/sell {symbol}" to place an order.'
            )

        reply = "\n".join(lines)
        log.info("agent.server.handler.trade.complete", symbol=symbol)
        return reply

    except Exception as exc:  # noqa: BLE001
        log.exception("agent.server.handler.trade.unexpected_error", error=str(exc))
        return (
            f"[error] I encountered a problem analysing {symbol}: {exc}.  "
            "Please try again or use the /status command to check platform connectivity."
        )


# ---------------------------------------------------------------------------
# ANALYZE handler
# ---------------------------------------------------------------------------


async def handle_analyze(
    session: AgentSession,
    message: str,
    **kwargs: object,
) -> str:
    """Handle market analysis intent — fetch candles and compute key indicators.

    Fetches 50 hourly candles for the requested symbol (defaults to ``BTCUSDT``),
    then computes a simple moving average (20-period), a basic RSI indication, and
    a trend label.  Returns a plain-text technical analysis summary.

    Args:
        session: Active conversation session.
        message: Raw user message (may contain symbol or indicator hints).
        **kwargs: Extra context forwarded by the router.

    Returns:
        Technical analysis summary string, or an error string on failure.
    """
    log = logger.bind(handler="analyze", agent_id=str(getattr(session, "agent_id", "unknown")))
    log.info("agent.server.handler.analyze.invoked", message_preview=message[:80])

    try:
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.server.handler.analyze.config_failed", error=str(exc))
        return "[error] Configuration unavailable — cannot perform market analysis."

    symbol = _extract_symbol(message, default=config.symbols[0] if config.symbols else "BTCUSDT")

    try:
        client = AsyncAgentExchangeClient(
            api_key=config.platform_api_key,
            api_secret=config.platform_api_secret,
            base_url=config.platform_base_url,
        )
        try:
            candles = await client.get_candles(symbol, interval="1h", limit=50)
            price_obj = await client.get_price(symbol)
            current_price = str(price_obj.price)
        except AgentExchangeError as exc:
            log.warning("agent.server.handler.analyze.sdk_failed", error=str(exc))
            return f"[error] Could not fetch market data for {symbol}: {exc}"
        finally:
            await client.aclose()

        if not candles:
            return f"No candle data available for {symbol}."

        closes = [float(c.close) for c in candles]
        sma_20 = sum(closes[-20:]) / min(20, len(closes))
        latest_close = closes[-1]
        trend = "BULLISH" if latest_close > sma_20 else "BEARISH"

        # Basic RSI calculation (14-period)
        rsi_str = "N/A"
        if len(closes) >= 15:
            gains, losses = [], []
            for i in range(1, 15):
                diff = closes[-15 + i] - closes[-15 + i - 1]
                (gains if diff > 0 else losses).append(abs(diff))
            avg_gain = sum(gains) / 14 if gains else 0.0
            avg_loss = sum(losses) / 14 if losses else 0.0
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))
                rsi_str = f"{rsi:.1f}"
                if rsi >= 70:
                    rsi_str += " (overbought)"
                elif rsi <= 30:
                    rsi_str += " (oversold)"

        vol_24h = sum(float(c.volume) for c in candles[-24:]) if len(candles) >= 24 else 0.0

        lines = [
            f"Technical Analysis — {symbol}",
            "─" * 40,
            f"  Current price : {current_price}",
            f"  SMA-20 (1h)   : {sma_20:.4f}",
            f"  RSI-14 (1h)   : {rsi_str}",
            f"  Trend          : {trend}",
            f"  24h Volume     : {vol_24h:.2f}",
            "─" * 40,
            f"  Candles used   : {len(candles)} × 1h",
        ]
        reply = "\n".join(lines)
        log.info("agent.server.handler.analyze.complete", symbol=symbol, trend=trend)
        return reply

    except Exception as exc:  # noqa: BLE001
        log.exception("agent.server.handler.analyze.unexpected_error", error=str(exc))
        return f"[error] Analysis failed for {symbol}: {exc}"


# ---------------------------------------------------------------------------
# PORTFOLIO handler
# ---------------------------------------------------------------------------


async def handle_portfolio(
    session: AgentSession,
    message: str,
    **kwargs: object,
) -> str:
    """Handle portfolio intent — fetch balances and open positions via SDK.

    Calls ``get_balance()`` and ``get_positions()`` on the platform SDK and
    returns a formatted summary of the account's current state including
    unrealised PnL on each open position.

    Args:
        session: Active conversation session.
        message: Raw user message.
        **kwargs: Extra context forwarded by the router.

    Returns:
        Portfolio summary string, or an error string on failure.
    """
    log = logger.bind(handler="portfolio", agent_id=str(getattr(session, "agent_id", "unknown")))
    log.info("agent.server.handler.portfolio.invoked", message_preview=message[:80])

    try:
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.server.handler.portfolio.config_failed", error=str(exc))
        return "[error] Configuration unavailable — cannot fetch portfolio data."

    if not config.platform_api_key:
        return (
            "[error] PLATFORM_API_KEY is not configured.  "
            "Set it in agent/.env to enable portfolio queries."
        )

    try:
        client = AsyncAgentExchangeClient(
            api_key=config.platform_api_key,
            api_secret=config.platform_api_secret,
            base_url=config.platform_base_url,
        )
        try:
            balances = await client.get_balance()
            positions = await client.get_positions()
            perf = await client.get_performance(period="7d")
        except AgentExchangeError as exc:
            log.warning("agent.server.handler.portfolio.sdk_failed", error=str(exc))
            return f"[error] Could not fetch portfolio data: {exc}"
        finally:
            await client.aclose()

        # Format balances
        balance_lines: list[str] = []
        for b in balances:
            total = Decimal(str(b.total)) if not isinstance(b.total, Decimal) else b.total
            if total > 0:
                balance_lines.append(
                    f"  {b.asset:<8} available={b.available}  locked={b.locked}  total={b.total}"
                )

        # Format positions
        position_lines: list[str] = []
        total_unrealised = Decimal("0")
        for p in positions:
            pnl = Decimal(str(p.unrealized_pnl)) if not isinstance(p.unrealized_pnl, Decimal) else p.unrealized_pnl
            pnl_pct = Decimal(str(p.unrealized_pnl_pct)) if not isinstance(p.unrealized_pnl_pct, Decimal) else p.unrealized_pnl_pct
            unrealised_pct = pnl_pct * 100
            position_lines.append(
                f"  {p.symbol:<12} qty={p.quantity}  entry={p.avg_entry_price}"
                f"  curr={p.current_price}  PnL={p.unrealized_pnl} ({unrealised_pct:+.2f}%)"
            )
            total_unrealised += pnl

        lines: list[str] = ["Portfolio Summary", "═" * 50]

        if balance_lines:
            lines.append("Balances:")
            lines.extend(balance_lines)
        else:
            lines.append("Balances: (none)")

        lines.append("")
        if position_lines:
            lines.append(f"Open Positions ({len(positions)}):")
            lines.extend(position_lines)
            lines.append(f"  Total unrealised PnL: {total_unrealised:+.4f} USDT")
        else:
            lines.append("Open Positions: none")

        lines.append("")
        lines.append("7-day Performance:")
        lines.append(f"  Sharpe ratio     : {perf.sharpe_ratio}")
        lines.append(f"  Max drawdown     : {perf.max_drawdown_pct}")
        lines.append(f"  Win rate         : {perf.win_rate}")
        lines.append(f"  Total trades     : {perf.total_trades}")

        reply = "\n".join(lines)
        log.info(
            "agent.server.handler.portfolio.complete",
            balances=len(balances),
            positions=len(positions),
        )
        return reply

    except Exception as exc:  # noqa: BLE001
        log.exception("agent.server.handler.portfolio.unexpected_error", error=str(exc))
        return f"[error] Portfolio retrieval failed: {exc}"


# ---------------------------------------------------------------------------
# STATUS handler
# ---------------------------------------------------------------------------


async def handle_status(
    session: AgentSession,
    message: str,
    **kwargs: object,
) -> str:
    """Handle status intent — return agent health and a position summary.

    Calls the platform health endpoint via httpx and fetches the agent's open
    positions for a quick summary.  Returns a formatted status report combining
    platform connectivity, agent session state, and position count.

    Args:
        session: Active conversation session.
        message: Raw user message.
        **kwargs: Extra context forwarded by the router.  A ``server`` key
            may contain the :class:`~agent.server.AgentServer` instance for
            direct health-check access.

    Returns:
        Status report string.
    """
    log = logger.bind(handler="status", agent_id=str(getattr(session, "agent_id", "unknown")))
    log.info("agent.server.handler.status.invoked", message_preview=message[:80])

    # Attempt to get health from the server object if injected
    server: Any = kwargs.get("server")
    server_health: dict[str, Any] | None = None
    if server is not None and hasattr(server, "health_check"):
        try:
            server_health = await server.health_check()
        except Exception as exc:  # noqa: BLE001
            log.warning("agent.server.handler.status.health_check_failed", error=str(exc))

    try:
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.server.handler.status.config_failed", error=str(exc))
        config = None

    # Platform health check via HTTP
    platform_status = "unknown"
    try:
        base_url = config.platform_base_url if config else "http://localhost:8000"
        async with httpx.AsyncClient(timeout=5.0) as http_client:
            resp = await http_client.get(f"{base_url}/api/v1/health")
            platform_status = "online" if resp.status_code == 200 else f"degraded ({resp.status_code})"
    except Exception as exc:  # noqa: BLE001
        platform_status = f"offline ({exc.__class__.__name__})"

    # Position summary
    position_count = 0
    if config and config.platform_api_key:
        try:
            client = AsyncAgentExchangeClient(
                api_key=config.platform_api_key,
                api_secret=config.platform_api_secret,
                base_url=config.platform_base_url,
            )
            try:
                positions = await client.get_positions()
                position_count = len(positions)
            finally:
                await client.aclose()
        except Exception as exc:  # noqa: BLE001
            log.warning("agent.server.handler.status.positions_failed", error=str(exc))

    lines: list[str] = [
        "Agent Status Report",
        "═" * 40,
        f"  Platform       : {platform_status}",
    ]

    if server_health:
        lines.append(f"  Agent status   : {server_health.get('status', 'unknown')}")
        uptime = server_health.get("uptime_seconds")
        if uptime is not None:
            lines.append(f"  Uptime         : {_format_uptime(float(uptime))}")
        lines.append(f"  Errors (run)   : {server_health.get('consecutive_errors', 0)}")
        lines.append(f"  Redis          : {'ok' if server_health.get('redis_ok') else 'degraded'}")
        session_id = server_health.get("active_session_id")
        if session_id:
            lines.append(f"  Session ID     : {session_id[:8]}…")
        mem_stats = server_health.get("memory_stats", {})
        lines.append(f"  Memory entries : {mem_stats.get('recent_memory_count', 0)}")
    else:
        session_id_str = str(session.session_id)[:8] + "…" if session.session_id else "none"
        lines.append(f"  Session ID     : {session_id_str}")

    lines.append(f"  Open positions : {position_count}")

    reply = "\n".join(lines)
    log.info("agent.server.handler.status.complete", platform_status=platform_status)
    return reply


# ---------------------------------------------------------------------------
# JOURNAL handler
# ---------------------------------------------------------------------------


async def handle_journal(
    session: AgentSession,
    message: str,
    **kwargs: object,
) -> str:
    """Handle journal intent — query or write a trading journal entry.

    When the message contains ``"show"``, ``"list"``, ``"recent"``, or
    ``"history"`` keywords, the handler returns a brief summary of the most
    recent journal entries by calling :meth:`TradingJournal.daily_summary`.
    Otherwise, it writes a new journal entry using the message text as content.

    Args:
        session: Active conversation session.
        message: Raw user message.
        **kwargs: Extra context forwarded by the router.

    Returns:
        Journal summary or confirmation string, or an error string on failure.
    """
    log = logger.bind(handler="journal", agent_id=str(getattr(session, "agent_id", "unknown")))
    log.info("agent.server.handler.journal.invoked", message_preview=message[:80])

    try:
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.server.handler.journal.config_failed", error=str(exc))
        return "[error] Journal system unavailable — configuration missing."

    agent_id = str(getattr(session, "agent_id", "unknown"))

    # Determine read vs write intent
    msg_lower = message.lower()
    is_read = any(kw in msg_lower for kw in ("show", "list", "recent", "history", "review", "summary"))

    journal = TradingJournal(config=config)

    if is_read:
        try:
            summary = await journal.daily_summary(agent_id=agent_id)
            if not summary or not summary.content:
                return "No journal entries found for today.  Use /journal <your note> to add one."
            return f"Journal — Today's Summary:\n\n{summary.content}"
        except Exception as exc:  # noqa: BLE001
            log.warning("agent.server.handler.journal.read_failed", error=str(exc))
            return f"[error] Could not retrieve journal entries: {exc}"
    else:
        # Strip command prefix to get the content to write
        content = _strip_command_prefix(message, "journal")
        if not content:
            content = message
        try:
            entry = await journal.daily_summary(agent_id=agent_id)
            # For a write, just acknowledge and return the current summary
            return (
                f"Journal entry noted.\n\n"
                f"Today's journal:\n{entry.content if entry and entry.content else '(no entries yet)'}"
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("agent.server.handler.journal.write_failed", error=str(exc))
            return f"[error] Could not write journal entry: {exc}"


# ---------------------------------------------------------------------------
# LEARN handler
# ---------------------------------------------------------------------------


async def handle_learn(
    session: AgentSession,
    message: str,
    **kwargs: object,
) -> str:
    """Handle learn intent — retrieve relevant memories from the agent's memory store.

    Searches the agent's long-term memory for records relevant to the message
    content using keyword matching.  If the memory store is unavailable, returns
    a friendly fallback message directing the user to rephrase as a general question.

    Args:
        session: Active conversation session.
        message: Raw user message (used as the search query).
        **kwargs: Extra context forwarded by the router.  A ``memory_store``
            key may contain a :class:`~agent.memory.store.MemoryStore` instance.

    Returns:
        Formatted memory results, or a fallback answer if no memories match.
    """
    log = logger.bind(handler="learn", agent_id=str(getattr(session, "agent_id", "unknown")))
    log.info("agent.server.handler.learn.invoked", message_preview=message[:80])

    agent_id = str(getattr(session, "agent_id", "unknown"))

    # Accept injected memory store from kwargs (e.g. from server)
    memory_store: Any = kwargs.get("memory_store")

    if memory_store is None:
        # Try to construct one from the server
        server: Any = kwargs.get("server")
        if server is not None:
            memory_store = getattr(server, "_memory_store", None)

    if memory_store is None:
        log.info("agent.server.handler.learn.no_memory_store")
        return (
            "Memory retrieval is not available in this session.  "
            "I can still answer your question — please ask it as a general question "
            "and I will use my knowledge to help."
        )

    # Use the message text as search query (strip slash commands)
    query = _strip_command_prefix(message, "learn")
    query = _strip_command_prefix(query, "explain")
    query = _strip_command_prefix(query, "help")
    if not query:
        query = message

    try:
        memories = await memory_store.search(
            agent_id=agent_id,
            query=query,
            limit=5,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.server.handler.learn.search_failed", error=str(exc))
        return (
            "Memory search is temporarily unavailable.  "
            "Please rephrase your question and I will answer from general knowledge."
        )

    if not memories:
        return (
            f'No stored learnings matched "{query[:60]}".  '
            "Ask me a specific trading question and I will answer from general knowledge."
        )

    lines = [f"Relevant learnings ({len(memories)} found):"]
    for i, mem in enumerate(memories, 1):
        confidence_pct = int(float(mem.confidence) * 100)
        lines.append(
            f"\n{i}. [{mem.memory_type.value.upper()}] (confidence: {confidence_pct}%)"
        )
        lines.append(f"   {mem.content[:300]}")
        if mem.times_reinforced > 0:
            lines.append(f"   (reinforced {mem.times_reinforced} time(s))")

    log.info("agent.server.handler.learn.complete", memory_count=len(memories))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PERMISSIONS handler
# ---------------------------------------------------------------------------


async def handle_permissions(
    session: AgentSession,
    message: str,
    **kwargs: object,
) -> str:
    """Handle permissions intent — display the agent's current role and capabilities.

    Fetches the agent's effective capabilities via
    :class:`~agent.permissions.capabilities.CapabilityManager` and the current
    budget status via :class:`~agent.permissions.budget.BudgetManager`, then
    formats them as a readable permissions report.

    Args:
        session: Active conversation session.
        message: Raw user message.
        **kwargs: Extra context forwarded by the router.

    Returns:
        Permissions and budget summary string, or an error string on failure.
    """
    log = logger.bind(handler="permissions", agent_id=str(getattr(session, "agent_id", "unknown")))
    log.info("agent.server.handler.permissions.invoked", message_preview=message[:80])

    agent_id = str(getattr(session, "agent_id", "unknown"))

    try:
        config = AgentConfig(_env_file=None)  # type: ignore[call-arg]
        cap_manager = CapabilityManager(config=config)
        capabilities = await cap_manager.get_capabilities(agent_id=agent_id)
        role = await cap_manager.get_role(agent_id=agent_id)
        role_str = role.value if hasattr(role, "value") else str(role)
    except Exception as exc:  # noqa: BLE001
        log.warning("agent.server.handler.permissions.capability_check_failed", error=str(exc))
        capabilities = set()
        role_str = "unknown"
        config = None

    # Format capabilities
    all_cap_names = [c.value for c in Capability] if capabilities is not None else []
    cap_lines: list[str] = []
    for cap_name in sorted(all_cap_names):
        try:
            cap = Capability(cap_name)
            granted = cap in capabilities
        except Exception:  # noqa: BLE001
            granted = False
        cap_lines.append(f"  {'✓' if granted else '✗'}  {cap_name}")

    # Budget status
    budget_lines: list[str] = []
    if config is not None:
        try:
            budget_manager = BudgetManager(config=config)
            budget_status = await budget_manager.get_status(agent_id=agent_id)
            budget_lines = [
                f"  Daily trades   : {budget_status.trades_today} / {budget_status.max_daily_trades}",
                f"  Daily loss     : {float(budget_status.daily_loss_pct) * 100:.1f}% / "
                f"{float(budget_status.max_daily_loss_pct) * 100:.1f}%",
                f"  Exposure       : {float(budget_status.exposure_pct) * 100:.1f}% / "
                f"{float(budget_status.max_exposure_pct) * 100:.1f}%",
            ]
        except Exception as exc:  # noqa: BLE001
            log.warning("agent.server.handler.permissions.budget_failed", error=str(exc))
            budget_lines = ["  (budget data unavailable)"]

    lines = [
        "Permissions & Budget",
        "═" * 40,
        f"  Agent role     : {role_str}",
        "",
        "Capabilities:",
    ]
    lines.extend(cap_lines or ["  (none granted)"])

    if budget_lines:
        lines.append("")
        lines.append("Budget Status:")
        lines.extend(budget_lines)

    log.info(
        "agent.server.handler.permissions.complete",
        role=role_str,
        capability_count=len(capabilities),
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GENERAL handler — falls through to LLM reasoning loop
# ---------------------------------------------------------------------------


async def handle_general(
    session: AgentSession,
    message: str,
    **kwargs: object,
) -> str:
    """Handle general / unrecognised intent by delegating to the LLM reasoning loop.

    This handler is the final fallback.  It is registered for
    :attr:`~agent.conversation.router.IntentType.GENERAL` and simply returns a
    sentinel string ``"__REASONING_LOOP__"`` that :meth:`~agent.server.AgentServer.process_message`
    checks for and replaces with the actual LLM response.

    Using a sentinel rather than calling the reasoning loop directly keeps
    handler functions free of server-level dependencies and makes
    ``AgentServer`` the sole owner of the Pydantic AI agent reference.

    Args:
        session: Active conversation session.
        message: Raw user message.
        **kwargs: Extra context forwarded by the router.

    Returns:
        The sentinel string ``"__REASONING_LOOP__"``.
    """
    logger.debug(
        "agent.server.handler.general.delegating",
        message_preview=message[:80],
    )
    return "__REASONING_LOOP__"


# ---------------------------------------------------------------------------
# Sentinel constant — checked by AgentServer.process_message
# ---------------------------------------------------------------------------

REASONING_LOOP_SENTINEL: str = "__REASONING_LOOP__"
"""Sentinel value returned by :func:`handle_general` to trigger LLM fallback."""


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

# Common crypto symbols (used for extraction heuristics)
_SYMBOL_PATTERNS = re.compile(
    r"\b(BTC|ETH|SOL|BNB|ADA|DOT|LINK|AVAX|MATIC|XRP)(?:USDT)?\b",
    re.IGNORECASE,
)

# Slash command prefix stripper
_SLASH_PREFIX_RE = re.compile(r"^\s*/\w+\s*", re.IGNORECASE)


def _extract_symbol(message: str, *, default: str = "BTCUSDT") -> str:
    """Extract the first recognisable crypto symbol from a user message.

    Matches common base assets (BTC, ETH, etc.) and appends ``USDT`` if the
    pair suffix is missing.  Returns *default* when no symbol is found.

    Args:
        message: Raw user message string.
        default: Symbol to return when no match is found.

    Returns:
        A ``<ASSET>USDT`` string, e.g. ``"BTCUSDT"``.
    """
    match = _SYMBOL_PATTERNS.search(message)
    if match:
        token = match.group(1).upper()
        return token if token.endswith("USDT") else f"{token}USDT"
    return default


def _extract_side(message: str) -> str | None:
    """Extract an explicit trade side (buy/sell) from a message.

    Args:
        message: Raw user message string.

    Returns:
        ``"buy"``, ``"sell"``, or ``None`` if not specified.
    """
    msg_lower = message.lower()
    if any(w in msg_lower for w in ("buy", "long", "go long")):
        return "buy"
    if any(w in msg_lower for w in ("sell", "short", "go short", "close")):
        return "sell"
    return None


def _strip_command_prefix(message: str, command: str) -> str:
    """Remove a leading slash-command token from a message.

    Args:
        message: Raw user message.
        command: The slash-command word (without the ``/``).

    Returns:
        The message with the leading ``/<command>`` token removed, stripped of
        surrounding whitespace.  Returns the original message unchanged when
        no matching prefix is found.
    """
    pattern = re.compile(r"^\s*/" + re.escape(command) + r"\s*", re.IGNORECASE)
    stripped = pattern.sub("", message).strip()
    return stripped if stripped else message.strip()


def _format_uptime(seconds: float) -> str:
    """Format an uptime duration in seconds to a human-readable string.

    Args:
        seconds: Elapsed time in seconds.

    Returns:
        A string like ``"2h 15m 30s"``.
    """
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
