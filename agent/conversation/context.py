"""Dynamic LLM context assembler for the TradeReady agent.

Builds the full message list that is passed to an LLM API call by combining
multiple data sources in priority order:

1. **System prompt** — the base persona from
   :data:`~agent.prompts.system.SYSTEM_PROMPT`.
2. **Portfolio state** — live portfolio snapshot fetched from the platform
   REST API (via :mod:`agent.tools.sdk_tools`).
3. **Active strategy** — name and status of the agent's deployed strategy
   (from the platform REST API).
4. **Current permissions and budget** — per-session budget and role derived
   from :class:`~agent.config.AgentConfig`.
5. **Recent learnings** — the agent's most recently accessed memories from
   the long-term memory store (:class:`~agent.memory.store.MemoryStore`).
6. **Recent conversation messages** — the tail of the current session from
   :meth:`~agent.conversation.session.AgentSession.get_context`.

Each section degrades gracefully: if the external source is unavailable the
section is simply omitted from the assembled context without failing the
entire build.

Token counting is approximate (1 token ≈ 4 characters) and is used only to
prevent context overflow — it does not need to be exact.

Usage::

    from agent.config import AgentConfig
    from agent.conversation.context import ContextBuilder
    from agent.conversation.session import AgentSession

    builder = ContextBuilder(config=AgentConfig())
    context = await builder.build(agent_id="...", session=my_session)
    # context is list[dict] ready for any OpenAI-compatible chat API.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from agent.config import AgentConfig
    from agent.conversation.session import AgentSession
    from agent.memory.store import MemoryStore

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------

# Rough approximation: 1 token ≈ 4 characters of English text.
_CHARS_PER_TOKEN: int = 4

# Minimum tokens reserved for the actual user prompt / LLM response after
# the context has been assembled.
_RESPONSE_RESERVE_TOKENS: int = 1500

# Maximum PROCEDURAL memories surfaced in the targeted "past experience" block.
_PAST_EXPERIENCE_LIMIT: int = 5

# Maximum EPISODIC memories included in the general learnings section.
_EPISODIC_CONTEXT_CAP: int = 5


def _estimate_tokens(text: str) -> int:
    """Return a rough token count for *text*.

    Args:
        text: The string to estimate.

    Returns:
        Estimated number of tokens (always at least 1).
    """
    return max(1, len(text) // _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# ContextBuilder
# ---------------------------------------------------------------------------


class ContextBuilder:
    """Assembles the LLM context from multiple sources.

    Combines static prompts, live platform data, memory store entries, and
    the active conversation history into a single ``list[dict]`` that can be
    passed directly to any OpenAI-compatible chat completions API.

    The assembly respects a configurable token budget so the context always
    fits within the model's context window even after adding the user message
    and leaving room for the assistant response.

    Args:
        config: :class:`~agent.config.AgentConfig` providing token limits,
            behaviour settings, and platform connectivity details.
        memory_store: Optional :class:`~agent.memory.store.MemoryStore`
            instance.  When provided, recent learnings are included in the
            context.  When ``None``, the learnings section is silently
            skipped.
        platform_api_key: API key used to call the platform REST endpoints
            that fetch portfolio and strategy data.  Defaults to
            ``config.platform_api_key``.

    Example::

        builder = ContextBuilder(config=AgentConfig(), memory_store=store)
        messages = await builder.build(agent_id="...", session=session)
    """

    def __init__(
        self,
        config: AgentConfig,
        *,
        memory_store: MemoryStore | None = None,
        platform_api_key: str | None = None,
    ) -> None:
        self._config = config
        self._memory_store = memory_store
        self._api_key = platform_api_key or config.platform_api_key

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def build(
        self,
        agent_id: str,
        session: AgentSession,
        *,
        max_tokens: int | None = None,
        symbol: str | None = None,
        regime: str | None = None,
    ) -> list[dict[str, Any]]:
        """Assemble a complete LLM context for the given agent and session.

        Fetches each context section independently so that a failure in one
        source (e.g. portfolio API down) does not prevent the others from
        being included.  Each section is added in priority order and the
        assembly stops when the token budget is exhausted.

        Priority order (highest to lowest):
            1. Base system prompt
            2. Current portfolio state
            3. Active strategy information
            4. Current permissions and budget
            5. Recent learnings from memory store (with targeted past-experience
               block when ``symbol``/``regime`` are provided)
            6. Recent conversation messages (from ``session.get_context()``)

        Args:
            agent_id: UUID string of the agent.
            session: The active :class:`~agent.conversation.session.AgentSession`
                whose messages will be appended last.
            max_tokens: Token budget for the assembled context.  Defaults to
                ``config.context_max_tokens - _RESPONSE_RESERVE_TOKENS``.
            symbol: Optional trading pair being analysed (e.g. ``"BTCUSDT"``).
                When provided, the learnings section includes top-5 PROCEDURAL
                memories matching this symbol + regime before the general
                recent-memories list.
            regime: Optional market regime at analysis time (e.g.
                ``"trending_up"``).  Used together with ``symbol`` to scope
                the past-experience query in the learnings section.

        Returns:
            List of ``{"role": str, "content": str}`` dicts, ready to be
            passed to a chat completions API.  Never empty — the system
            prompt is always included.
        """
        log = logger.bind(agent_id=agent_id, session_id=str(session.session_id))

        effective_max = (
            max_tokens
            if max_tokens is not None
            else max(1000, self._config.context_max_tokens - _RESPONSE_RESERVE_TOKENS)
        )

        log.debug("agent.session.context.build.start", max_tokens=effective_max)

        messages: list[dict[str, Any]] = []
        tokens_used = 0

        # ------------------------------------------------------------------
        # 1. Base system prompt (always included)
        # ------------------------------------------------------------------
        system_content = await self._build_system_section()
        system_tokens = _estimate_tokens(system_content)
        messages.append({"role": "system", "content": system_content})
        tokens_used += system_tokens
        log.debug("agent.session.context.section.system", tokens=system_tokens)

        # ------------------------------------------------------------------
        # 2. Portfolio state
        # ------------------------------------------------------------------
        portfolio_block = await self._fetch_portfolio_section()
        if portfolio_block:
            portfolio_tokens = _estimate_tokens(portfolio_block)
            if tokens_used + portfolio_tokens <= effective_max:
                messages.append({
                    "role": "system",
                    "content": portfolio_block,
                })
                tokens_used += portfolio_tokens
                log.debug("agent.session.context.section.portfolio", tokens=portfolio_tokens)
            else:
                log.debug("agent.session.context.section.portfolio.skipped_budget")

        # ------------------------------------------------------------------
        # 3. Active strategy info
        # ------------------------------------------------------------------
        strategy_block = await self._fetch_strategy_section(agent_id)
        if strategy_block:
            strategy_tokens = _estimate_tokens(strategy_block)
            if tokens_used + strategy_tokens <= effective_max:
                messages.append({
                    "role": "system",
                    "content": strategy_block,
                })
                tokens_used += strategy_tokens
                log.debug("agent.session.context.section.strategy", tokens=strategy_tokens)
            else:
                log.debug("agent.session.context.section.strategy.skipped_budget")

        # ------------------------------------------------------------------
        # 4. Current permissions and budget
        # ------------------------------------------------------------------
        permissions_block = self._build_permissions_section()
        permissions_tokens = _estimate_tokens(permissions_block)
        if tokens_used + permissions_tokens <= effective_max:
            messages.append({
                "role": "system",
                "content": permissions_block,
            })
            tokens_used += permissions_tokens
            log.debug("agent.session.context.section.permissions", tokens=permissions_tokens)

        # ------------------------------------------------------------------
        # 5. Recent learnings from memory store
        # ------------------------------------------------------------------
        learnings_block = await self._fetch_learnings_section(
            agent_id, symbol=symbol, regime=regime
        )
        if learnings_block:
            learnings_tokens = _estimate_tokens(learnings_block)
            if tokens_used + learnings_tokens <= effective_max:
                messages.append({
                    "role": "system",
                    "content": learnings_block,
                })
                tokens_used += learnings_tokens
                log.debug("agent.session.context.section.learnings", tokens=learnings_tokens)
            else:
                log.debug("agent.session.context.section.learnings.skipped_budget")

        # ------------------------------------------------------------------
        # 6. Recent conversation messages
        # ------------------------------------------------------------------
        remaining_budget = max(0, effective_max - tokens_used)
        if remaining_budget > 100:  # Only add messages if there is meaningful space.
            try:
                conversation_msgs = await session.get_context(max_tokens=remaining_budget)
                messages.extend(conversation_msgs)
                added_tokens = sum(
                    _estimate_tokens(str(m.get("content", "")))
                    for m in conversation_msgs
                )
                tokens_used += added_tokens
                log.debug(
                    "agent.session.context.section.conversation",
                    message_count=len(conversation_msgs),
                    tokens=added_tokens,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("agent.session.context.section.conversation.failed", error=str(exc))

        log.debug(
            "agent.session.context.build.complete",
            total_sections=len(messages),
            total_tokens=tokens_used,
            max_tokens=effective_max,
        )
        return messages

    async def build_trade_context(
        self,
        agent_id: str,
        session: AgentSession,
        symbol: str,
        regime: str,
        *,
        max_tokens: int | None = None,
    ) -> list[dict[str, Any]]:
        """Assemble LLM context scoped to a specific trading decision.

        Convenience wrapper around :meth:`build` that makes ``symbol`` and
        ``regime`` required rather than optional.  The learnings section will
        always include the targeted "Past experience" block for this symbol +
        regime combination, providing the LLM with up to
        :data:`_PAST_EXPERIENCE_LIMIT` relevant PROCEDURAL memories before
        it analyses the current market conditions.

        This is the preferred entry point when the agent is about to make a
        trade decision for a specific symbol in a known regime, e.g. inside
        :class:`~agent.trading.loop.TradingLoop` before calling the signal
        generator.

        Args:
            agent_id: UUID string of the agent.
            session: The active :class:`~agent.conversation.session.AgentSession`.
            symbol: Trading pair being analysed (e.g. ``"BTCUSDT"``).
            regime: Market regime at analysis time (e.g. ``"trending_up"``).
            max_tokens: Optional token budget override.

        Returns:
            List of ``{"role": str, "content": str}`` dicts, ready to be
            passed to a chat completions API.  Never empty.
        """
        return await self.build(
            agent_id=agent_id,
            session=session,
            max_tokens=max_tokens,
            symbol=symbol,
            regime=regime,
        )

    # ------------------------------------------------------------------
    # Private section builders
    # ------------------------------------------------------------------

    async def _build_system_section(self) -> str:
        """Return the base system prompt text.

        Loads :data:`~agent.prompts.system.SYSTEM_PROMPT` and optionally
        appends the skill context document from ``docs/skill.md`` when it
        is available.

        Returns:
            Complete system prompt string.
        """
        try:
            from agent.prompts.system import SYSTEM_PROMPT  # noqa: PLC0415

            base = SYSTEM_PROMPT

            # Attempt to append skill context (disk or REST fallback).
            try:
                from agent.prompts.skill_context import load_skill_context  # noqa: PLC0415

                skill_text = await load_skill_context(self._config)
                if skill_text:
                    base = base + "\n\n## Platform API Reference\n\n" + skill_text[:4000]
            except Exception as exc:  # noqa: BLE001
                logger.debug("agent.session.context.system.skill_context_skipped", error=str(exc))

            return base

        except ImportError:
            logger.warning("agent.session.context.system.prompt_import_failed")
            return (
                "You are the TradeReady AI trading agent. "
                "Help the user with trading decisions and platform operations."
            )

    async def _fetch_portfolio_section(self) -> str:
        """Fetch the current portfolio state from the platform API.

        Makes a live call to :func:`~agentexchange.async_client.AsyncAgentExchangeClient.get_balance`
        and :func:`~agentexchange.async_client.AsyncAgentExchangeClient.get_performance`
        to build a brief portfolio state summary for the LLM.

        Returns:
            Formatted string describing the current portfolio, or empty
            string if the data is unavailable.
        """
        try:
            from agentexchange.async_client import AsyncAgentExchangeClient  # noqa: PLC0415
            from agentexchange.exceptions import AgentExchangeError  # noqa: PLC0415

            async with AsyncAgentExchangeClient(
                api_key=self._api_key,
                api_secret=self._config.platform_api_secret,
                base_url=self._config.platform_base_url,
            ) as client:
                try:
                    balances = await client.get_balance()
                except AgentExchangeError:
                    balances = []

                try:
                    performance = await client.get_performance(period="7d")
                    perf_str = (
                        f"7d Sharpe: {performance.sharpe_ratio}, "
                        f"Max DD: {performance.max_drawdown_pct}%, "
                        f"Win Rate: {performance.win_rate}%, "
                        f"Total Trades: {performance.total_trades}"
                    )
                except AgentExchangeError:
                    perf_str = "unavailable"

            if not balances and perf_str == "unavailable":
                return ""

            lines: list[str] = ["## Current Portfolio State"]
            if balances:
                lines.append("### Balances")
                for b in balances:
                    if hasattr(b, "asset") and hasattr(b, "available"):
                        lines.append(f"- {b.asset}: available={b.available}, total={b.total}")
            lines.append(f"### 7-Day Performance: {perf_str}")

            return "\n".join(lines)

        except Exception as exc:  # noqa: BLE001
            logger.debug("agent.session.context.portfolio.fetch_failed", error=str(exc))
            return ""

    async def _fetch_strategy_section(self, agent_id: str) -> str:
        """Fetch the agent's active strategy from the platform REST API.

        Calls ``GET /api/v1/strategies`` filtered to deployed strategies.
        Returns a brief description of the first deployed strategy found,
        or an empty string when none is deployed or the endpoint is
        unreachable.

        Args:
            agent_id: UUID string of the agent (used for scoped API calls).

        Returns:
            Formatted string describing the active strategy, or empty
            string if unavailable.
        """
        try:
            import httpx  # noqa: PLC0415

            url = f"{self._config.platform_base_url}/api/v1/strategies"
            headers = {"X-API-Key": self._api_key}
            params = {"status": "deployed", "limit": "1"}

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, headers=headers, params=params)

            if response.status_code != 200:
                return ""

            data = response.json()
            strategies = data if isinstance(data, list) else data.get("strategies", [])
            if not strategies:
                return ""

            strategy = strategies[0]
            name = strategy.get("name", "Unknown")
            status = strategy.get("status", "unknown")
            version = strategy.get("current_version", "?")

            return (
                "## Active Strategy\n"
                f"Name: {name}\n"
                f"Status: {status}\n"
                f"Version: v{version}"
            )

        except Exception as exc:  # noqa: BLE001
            logger.debug("agent.session.context.strategy.fetch_failed", error=str(exc))
            return ""

    def _build_permissions_section(self) -> str:
        """Build a permissions and budget block from the agent config.

        Returns a plain-text block summarising the agent's operational
        constraints for the current session.  This is derived entirely from
        the local :class:`~agent.config.AgentConfig` — no network calls are
        made.

        Returns:
            Formatted string describing current permissions and budget.
        """
        max_pct = int(self._config.max_trade_pct * 100)
        role = self._config.default_agent_role
        max_daily_trades = self._config.default_max_trades_per_day
        max_exposure = self._config.default_max_exposure_pct
        max_daily_loss = self._config.default_max_daily_loss_pct
        min_confidence = self._config.trading_min_confidence

        return (
            "## Current Permissions and Budget\n"
            f"Role: {role}\n"
            f"Max trade size: {max_pct}% of equity per order\n"
            f"Max open exposure: {max_exposure}% of equity\n"
            f"Max daily trades: {max_daily_trades}\n"
            f"Max daily loss: {max_daily_loss}%\n"
            f"Min signal confidence required to trade: {min_confidence}"
        )

    async def _fetch_learnings_section(
        self,
        agent_id: str,
        *,
        symbol: str | None = None,
        regime: str | None = None,
    ) -> str:
        """Fetch recent learnings from the long-term memory store.

        Retrieves up to ``memory_search_limit`` recent memories from the
        configured :class:`~agent.memory.store.MemoryStore` instance, if
        one was supplied.  Memories are formatted as a bulleted list grouped
        by type (procedural first, then semantic, then episodic).

        When ``symbol`` and/or ``regime`` are provided, this method also
        fetches the top-5 PROCEDURAL memories that are relevant to that
        specific trading context (via keyword search) and surfaces them
        first under a "Past experience" sub-heading.  This gives the LLM
        targeted learnings from past trades under similar conditions before
        it makes a new decision.

        Args:
            agent_id: UUID string of the agent.
            symbol: Optional trading pair being analysed (e.g.
                ``"BTCUSDT"``).  Used to scope the past-experience query.
            regime: Optional market regime string at analysis time (e.g.
                ``"trending_up"``).  Combined with ``symbol`` to build the
                search query.

        Returns:
            Formatted string of recent learnings, or empty string if the
            memory store is unavailable or empty.
        """
        if self._memory_store is None:
            return ""

        try:
            from agent.memory.store import MemoryType  # noqa: PLC0415

            lines: list[str] = ["## Recent Learnings"]
            added_ids: set[str] = set()

            # ------------------------------------------------------------------
            # Past experience: targeted PROCEDURAL memories for this context.
            # ------------------------------------------------------------------
            if symbol or regime:
                query_terms = " ".join(filter(None, [symbol, regime]))
                try:
                    past_experience = await self._memory_store.search(
                        agent_id=agent_id,
                        query=query_terms,
                        memory_type=MemoryType.PROCEDURAL,
                        limit=_PAST_EXPERIENCE_LIMIT,
                    )
                    if past_experience:
                        context_label_parts: list[str] = []
                        if symbol:
                            context_label_parts.append(symbol)
                        if regime:
                            context_label_parts.append(f"{regime} regime")
                        context_label = " / ".join(context_label_parts)
                        lines.append(f"### Past Experience ({context_label})")
                        for m in past_experience:
                            confidence_pct = int(float(m.confidence) * 100)
                            reinforcement_note = (
                                f", reinforced {m.times_reinforced}x"
                                if m.times_reinforced > 1
                                else ""
                            )
                            lines.append(
                                f"- {m.content} "
                                f"(confidence: {confidence_pct}%{reinforcement_note})"
                            )
                            added_ids.add(m.id)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(
                        "agent.session.context.learnings.past_experience_failed",
                        agent_id=agent_id,
                        symbol=symbol,
                        regime=regime,
                        error=str(exc),
                    )

            # ------------------------------------------------------------------
            # General recent memories (all types).
            # ------------------------------------------------------------------
            memories = await self._memory_store.get_recent(
                agent_id, limit=self._config.memory_search_limit
            )
            # Exclude any already shown in the past-experience block.
            memories = [m for m in memories if m.id not in added_ids]

            if not memories and not added_ids:
                return ""

            procedural = [m for m in memories if m.memory_type == MemoryType.PROCEDURAL]
            semantic = [m for m in memories if m.memory_type == MemoryType.SEMANTIC]
            episodic = [m for m in memories if m.memory_type == MemoryType.EPISODIC]

            if procedural:
                lines.append("### Rules and Procedures")
                for m in procedural:
                    confidence_pct = int(float(m.confidence) * 100)
                    lines.append(f"- {m.content} (confidence: {confidence_pct}%)")
            if semantic:
                lines.append("### Market Knowledge")
                for m in semantic:
                    lines.append(f"- {m.content}")
            if episodic:
                lines.append("### Recent Experiences")
                for m in episodic[:_EPISODIC_CONTEXT_CAP]:
                    lines.append(f"- {m.content}")

            # If lines only contains the header and nothing else, return empty.
            if len(lines) == 1:
                return ""

            return "\n".join(lines)

        except Exception as exc:  # noqa: BLE001
            logger.debug("agent.session.context.learnings.fetch_failed", agent_id=agent_id, error=str(exc))
            return ""
