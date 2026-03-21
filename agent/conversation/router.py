"""Intent classification and routing for the agent conversation system.

Classifies incoming user messages into typed intents and maps each intent to
the correct handler function.  Classification is performed entirely in-process
using keyword matching and regular expressions — no LLM call is made, keeping
latency negligible.

Priority order
--------------
1. Slash commands (``/trade``, ``/analyze``, etc.) — always win over NLP.
2. Regex patterns — checked in declaration order; first match wins.
3. Keyword sets — checked only when no regex matches.
4. ``GENERAL`` — fallback when nothing matches.

Handler registry
----------------
The registry is a plain ``dict[IntentType, HandlerFn]`` so new intents can be
added at runtime::

    router = IntentRouter()
    router.register(IntentType.TRADE, my_trade_handler)

Handler signature
-----------------
Every handler must be an async callable with the signature::

    async def handler(
        session: AgentSession,
        message: str,
        **kwargs: object,
    ) -> str:
        ...

Usage::

    from agent.conversation.router import IntentRouter, IntentType

    router = IntentRouter()
    intent, handler = router.route("show me my portfolio balance")
    result = await handler(session, "show me my portfolio balance")
"""

from __future__ import annotations

import re
from collections.abc import Callable, Coroutine
from enum import Enum
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from agent.conversation.session import AgentSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

# Every handler is an async function: (session, message, **kwargs) -> str
HandlerFn = Callable[..., Coroutine[Any, Any, str]]


# ---------------------------------------------------------------------------
# IntentType
# ---------------------------------------------------------------------------


class IntentType(str, Enum):
    """All recognised conversation intents.

    Using ``str`` as the mixin makes the enum JSON-serialisable and lets it
    appear in log output as a plain string without extra formatting.
    """

    TRADE = "trade"
    ANALYZE = "analyze"
    PORTFOLIO = "portfolio"
    JOURNAL = "journal"
    LEARN = "learn"
    PERMISSIONS = "permissions"
    STATUS = "status"
    GENERAL = "general"


# ---------------------------------------------------------------------------
# Built-in placeholder handlers
# ---------------------------------------------------------------------------
# These stubs are used when no concrete handler has been registered for an
# intent.  They return a short acknowledgement string rather than doing real
# work — callers should register their own handlers before routing messages.


async def _default_trade_handler(
    session: AgentSession,  # noqa: ARG001
    message: str,
    **kwargs: object,
) -> str:
    """Default placeholder for trade intent.

    Args:
        session: The active :class:`~agent.conversation.session.AgentSession`.
        message: Raw user message.
        **kwargs: Additional context forwarded by the dispatcher.

    Returns:
        Acknowledgement string.
    """
    return f"[trade handler not registered] received: {message!r}"


async def _default_analyze_handler(
    session: AgentSession,  # noqa: ARG001
    message: str,
    **kwargs: object,
) -> str:
    """Default placeholder for analyze intent.

    Args:
        session: The active :class:`~agent.conversation.session.AgentSession`.
        message: Raw user message.
        **kwargs: Additional context forwarded by the dispatcher.

    Returns:
        Acknowledgement string.
    """
    return f"[analyze handler not registered] received: {message!r}"


async def _default_portfolio_handler(
    session: AgentSession,  # noqa: ARG001
    message: str,
    **kwargs: object,
) -> str:
    """Default placeholder for portfolio intent.

    Args:
        session: The active :class:`~agent.conversation.session.AgentSession`.
        message: Raw user message.
        **kwargs: Additional context forwarded by the dispatcher.

    Returns:
        Acknowledgement string.
    """
    return f"[portfolio handler not registered] received: {message!r}"


async def _default_journal_handler(
    session: AgentSession,  # noqa: ARG001
    message: str,
    **kwargs: object,
) -> str:
    """Default placeholder for journal intent.

    Args:
        session: The active :class:`~agent.conversation.session.AgentSession`.
        message: Raw user message.
        **kwargs: Additional context forwarded by the dispatcher.

    Returns:
        Acknowledgement string.
    """
    return f"[journal handler not registered] received: {message!r}"


async def _default_learn_handler(
    session: AgentSession,  # noqa: ARG001
    message: str,
    **kwargs: object,
) -> str:
    """Default placeholder for learn intent.

    Args:
        session: The active :class:`~agent.conversation.session.AgentSession`.
        message: Raw user message.
        **kwargs: Additional context forwarded by the dispatcher.

    Returns:
        Acknowledgement string.
    """
    return f"[learn handler not registered] received: {message!r}"


async def _default_permissions_handler(
    session: AgentSession,  # noqa: ARG001
    message: str,
    **kwargs: object,
) -> str:
    """Default placeholder for permissions intent.

    Args:
        session: The active :class:`~agent.conversation.session.AgentSession`.
        message: Raw user message.
        **kwargs: Additional context forwarded by the dispatcher.

    Returns:
        Acknowledgement string.
    """
    return f"[permissions handler not registered] received: {message!r}"


async def _default_status_handler(
    session: AgentSession,  # noqa: ARG001
    message: str,
    **kwargs: object,
) -> str:
    """Default placeholder for status intent.

    Args:
        session: The active :class:`~agent.conversation.session.AgentSession`.
        message: Raw user message.
        **kwargs: Additional context forwarded by the dispatcher.

    Returns:
        Acknowledgement string.
    """
    return f"[status handler not registered] received: {message!r}"


async def _default_general_handler(
    session: AgentSession,  # noqa: ARG001
    message: str,
    **kwargs: object,
) -> str:
    """Default placeholder for general / unrecognised intent.

    Args:
        session: The active :class:`~agent.conversation.session.AgentSession`.
        message: Raw user message.
        **kwargs: Additional context forwarded by the dispatcher.

    Returns:
        Acknowledgement string.
    """
    return f"[general handler not registered] received: {message!r}"


# ---------------------------------------------------------------------------
# Slash-command map
# ---------------------------------------------------------------------------

# Maps the exact slash-command token (after the leading ``/``) to an intent.
_SLASH_COMMANDS: dict[str, IntentType] = {
    "trade": IntentType.TRADE,
    "buy": IntentType.TRADE,
    "sell": IntentType.TRADE,
    "order": IntentType.TRADE,
    "analyze": IntentType.ANALYZE,
    "analyse": IntentType.ANALYZE,
    "analysis": IntentType.ANALYZE,
    "chart": IntentType.ANALYZE,
    "portfolio": IntentType.PORTFOLIO,
    "balance": IntentType.PORTFOLIO,
    "positions": IntentType.PORTFOLIO,
    "pnl": IntentType.PORTFOLIO,
    "journal": IntentType.JOURNAL,
    "log": IntentType.JOURNAL,
    "note": IntentType.JOURNAL,
    "learn": IntentType.LEARN,
    "explain": IntentType.LEARN,
    "help": IntentType.LEARN,
    "permissions": IntentType.PERMISSIONS,
    "permission": IntentType.PERMISSIONS,
    "access": IntentType.PERMISSIONS,
    "role": IntentType.PERMISSIONS,
    "status": IntentType.STATUS,
    "health": IntentType.STATUS,
    "ping": IntentType.STATUS,
    "info": IntentType.STATUS,
}

# Pre-compiled regex for extracting the first slash-command token.
# Matches: optional leading whitespace, a forward slash, then one or more
# word characters, then either end-of-string or whitespace.
_SLASH_RE: re.Pattern[str] = re.compile(r"^\s*/(\w+)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Regex-based patterns (checked before keyword sets)
# ---------------------------------------------------------------------------

# Each entry is (compiled_pattern, IntentType).
# Patterns are checked in order — the first match wins.
_REGEX_RULES: list[tuple[re.Pattern[str], IntentType]] = [
    # Trade intent — explicit action verbs + crypto order concepts.
    # Checked first because "buy/sell" are unambiguous execution signals.
    (
        re.compile(
            r"\b(buy|sell|place\s+(?:a\s+)?(?:market|limit)\s+order|open\s+(?:a\s+)?(?:long|short)|"
            r"close\s+(?:my\s+)?position|go\s+(?:long|short))\b",
            re.IGNORECASE,
        ),
        IntentType.TRADE,
    ),
    # Journal intent — note-taking verbs that are unambiguous and short.
    # Checked before LEARN to avoid "log" colliding with educational queries.
    (
        re.compile(
            r"\b(journal|diary|remind\s+me|remember\s+(?:that|this))\b",
            re.IGNORECASE,
        ),
        IntentType.JOURNAL,
    ),
    # Status intent — operational / connectivity queries.
    # "is the server online?" should not fall into LEARN.
    (
        re.compile(
            r"\b(status|health|online|offline|running|alive|ping|uptime|"
            r"connect(?:ion|ed)?)\b",
            re.IGNORECASE,
        ),
        IntentType.STATUS,
    ),
    # Learn intent — educational meta-queries ("what is", "how does", "explain").
    # Checked before PORTFOLIO and ANALYZE so that "explain what a Sharpe ratio
    # is" routes to LEARN rather than PORTFOLIO despite the word "Sharpe".
    (
        re.compile(
            r"\b(what\s+is|what\s+are|how\s+(?:does|do|to)|explain|"
            r"teach(?:\s+me)?|learn|understand|guide|tutorial)\b",
            re.IGNORECASE,
        ),
        IntentType.LEARN,
    ),
    # Analyze intent — technical-analysis verbs and indicator names.
    (
        re.compile(
            r"\b(analys[ei]s?|analyz[ei]|chart|technical|indicator|trend|support|"
            r"resistance|rsi|macd|moving\s+average|bollinger|ema|sma|atr)\b",
            re.IGNORECASE,
        ),
        IntentType.ANALYZE,
    ),
    # Permissions intent — access control and risk limit management.
    (
        re.compile(
            r"\b(permiss(?:ion)?s?|access|role|allow(?:ed)?|restrict(?:ion|ed)?|"
            r"max(?:imum)?\s+(?:trade|exposure|loss)|limit(?:s)?)\b",
            re.IGNORECASE,
        ),
        IntentType.PERMISSIONS,
    ),
    # Portfolio intent — balance, positions, P&L, and performance concepts.
    # Checked after LEARN and ANALYZE so educational questions that happen to
    # mention "Sharpe" or "drawdown" route correctly.
    (
        re.compile(
            r"\b(portfolio|balance|position|holding|p(?:&|and|/)l|profit|loss|"
            r"equity|drawdown|sharpe|performance|return)\b",
            re.IGNORECASE,
        ),
        IntentType.PORTFOLIO,
    ),
    # Journal intent (secondary) — "log" and "note" checked last to avoid
    # false-positives on phrases like "login" or "notebook".
    (
        re.compile(
            r"\b(log(?:ging)?|note|record|entry)\b",
            re.IGNORECASE,
        ),
        IntentType.JOURNAL,
    ),
]

# ---------------------------------------------------------------------------
# Keyword sets (fallback after regex)
# ---------------------------------------------------------------------------

# Each entry is (frozenset_of_keywords, IntentType).
# Keywords are checked by testing whether any word in the message appears in
# the set.  Matched against the lower-cased, tokenised message.
_KEYWORD_RULES: list[tuple[frozenset[str], IntentType]] = [
    (
        frozenset({"trade", "order", "execute", "swap", "exchange", "fill"}),
        IntentType.TRADE,
    ),
    (
        frozenset({"analyse", "analyze", "analysis", "inspect", "review", "forecast"}),
        IntentType.ANALYZE,
    ),
    (
        frozenset({"portfolio", "wallet", "holdings", "assets", "funds", "pnl"}),
        IntentType.PORTFOLIO,
    ),
    (
        frozenset({"journal", "diary", "note", "log", "entry", "notes"}),
        IntentType.JOURNAL,
    ),
    (
        frozenset({"learn", "explain", "tutorial", "guide", "educate", "course"}),
        IntentType.LEARN,
    ),
    (
        frozenset({"permission", "permissions", "role", "access", "allowed", "restrict"}),
        IntentType.PERMISSIONS,
    ),
    (
        frozenset({"status", "health", "ping", "alive", "running", "uptime"}),
        IntentType.STATUS,
    ),
]

# Pre-compiled pattern for splitting a message into word tokens.
_TOKEN_RE: re.Pattern[str] = re.compile(r"\b[a-z]+\b")


# ---------------------------------------------------------------------------
# IntentRouter
# ---------------------------------------------------------------------------


class IntentRouter:
    """Classify user messages into intents and route them to handler functions.

    The router supports three layers of classification:

    1. **Slash commands** — explicit ``/command`` tokens always take priority.
    2. **Regex rules** — fast pattern matching for natural-language variations.
    3. **Keyword sets** — token-level matching as a secondary fallback.
    4. **GENERAL** — returned when nothing else matches.

    A mutable handler registry (``dict[IntentType, HandlerFn]``) allows
    callers to replace individual handlers at runtime without subclassing::

        router = IntentRouter()
        router.register(IntentType.TRADE, my_trade_handler)
        intent, handler = router.route("buy 0.01 BTC")
        result = await handler(session, "buy 0.01 BTC")

    Args:
        handlers: Optional initial mapping from :class:`IntentType` to handler
            callables.  When ``None``, all intents are wired to their built-in
            placeholder implementations.

    Example::

        from agent.conversation.router import IntentRouter, IntentType

        router = IntentRouter()
        intent = router.classify("show my portfolio")
        # IntentType.PORTFOLIO

        intent, handler = router.route("/trade buy BTC")
        # (IntentType.TRADE, <handler>)
    """

    def __init__(
        self,
        handlers: dict[IntentType, HandlerFn] | None = None,
    ) -> None:
        # Build the registry from the supplied mapping, back-filling any
        # missing intents with the built-in placeholder stubs.
        self._registry: dict[IntentType, HandlerFn] = {
            IntentType.TRADE: _default_trade_handler,
            IntentType.ANALYZE: _default_analyze_handler,
            IntentType.PORTFOLIO: _default_portfolio_handler,
            IntentType.JOURNAL: _default_journal_handler,
            IntentType.LEARN: _default_learn_handler,
            IntentType.PERMISSIONS: _default_permissions_handler,
            IntentType.STATUS: _default_status_handler,
            IntentType.GENERAL: _default_general_handler,
        }
        if handlers:
            self._registry.update(handlers)

        self._log = logger.bind(component="IntentRouter")

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def register(self, intent: IntentType, handler: HandlerFn) -> None:
        """Register or replace the handler for a given intent.

        Calling ``register`` a second time for the same intent replaces the
        previous handler without affecting any other entries.

        Args:
            intent:  The :class:`IntentType` this handler should serve.
            handler: An async callable with signature
                ``(session, message, **kwargs) -> str``.

        Example::

            async def my_trade_handler(session, message, **kwargs):
                return "executing trade …"

            router.register(IntentType.TRADE, my_trade_handler)
        """
        self._registry[intent] = handler
        self._log.debug("router.handler_registered", intent=intent.value)

    def classify(self, message: str) -> IntentType:
        """Classify a user message and return the best-matching intent.

        Classification priority:

        1. Slash commands (``/command`` as the first non-whitespace token).
        2. Compiled regex patterns (checked in declaration order).
        3. Keyword token matching.
        4. :attr:`IntentType.GENERAL` fallback.

        Args:
            message: Raw user message string (may contain leading/trailing
                whitespace and mixed case).

        Returns:
            The :class:`IntentType` that best represents the user's request.
        """
        stripped = message.strip()
        if not stripped:
            self._log.debug("router.classify.empty_message")
            return IntentType.GENERAL

        # 1. Slash-command check ─────────────────────────────────────────────
        slash_match = _SLASH_RE.match(stripped)
        if slash_match:
            token = slash_match.group(1).lower()
            intent = _SLASH_COMMANDS.get(token)
            if intent is not None:
                self._log.debug(
                    "router.classify.slash_command",
                    token=token,
                    intent=intent.value,
                )
                return intent
            # Unknown slash command — fall through to NLP classification of
            # the remainder of the message after the slash token.
            stripped = stripped[slash_match.end():].strip() or stripped

        # 2. Regex-based classification ──────────────────────────────────────
        for pattern, intent in _REGEX_RULES:
            if pattern.search(stripped):
                self._log.debug(
                    "router.classify.regex_match",
                    intent=intent.value,
                    pattern=pattern.pattern[:60],
                )
                return intent

        # 3. Keyword-based classification ────────────────────────────────────
        tokens = frozenset(_TOKEN_RE.findall(stripped.lower()))
        for keyword_set, intent in _KEYWORD_RULES:
            if tokens & keyword_set:
                self._log.debug(
                    "router.classify.keyword_match",
                    intent=intent.value,
                    matched_keywords=list(tokens & keyword_set),
                )
                return intent

        # 4. GENERAL fallback ────────────────────────────────────────────────
        self._log.debug("router.classify.fallback", intent=IntentType.GENERAL.value)
        return IntentType.GENERAL

    def get_handler(self, intent: IntentType) -> HandlerFn:
        """Return the registered handler for the given intent.

        Falls back to the :attr:`IntentType.GENERAL` handler when *intent* is
        not present in the registry (which should never happen with the
        built-in stubs, but could occur after manual registry manipulation).

        Args:
            intent: The :class:`IntentType` to look up.

        Returns:
            The async handler callable registered for *intent*, or the
            ``GENERAL`` handler if none is found.
        """
        handler = self._registry.get(intent)
        if handler is None:
            self._log.warning(
                "router.get_handler.missing",
                intent=intent.value,
                fallback=IntentType.GENERAL.value,
            )
            return self._registry[IntentType.GENERAL]
        return handler

    def route(self, message: str) -> tuple[IntentType, HandlerFn]:
        """Classify a message and return the matching (intent, handler) pair.

        Convenience method that combines :meth:`classify` and
        :meth:`get_handler` into a single call::

            intent, handler = router.route("show me my portfolio")
            result = await handler(session, "show me my portfolio")

        Args:
            message: Raw user message string.

        Returns:
            A two-tuple of ``(IntentType, handler_callable)``.
        """
        intent = self.classify(message)
        handler = self.get_handler(intent)
        self._log.info(
            "router.route",
            intent=intent.value,
            message_preview=message[:80],
        )
        return intent, handler
