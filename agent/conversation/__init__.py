"""Conversation session management and intent routing for the TradeReady agent.

Provides :class:`AgentSession` for creating, resuming, persisting, and
closing conversation sessions backed by the platform's ``agent_sessions``
and ``agent_messages`` database tables.

Also provides :class:`IntentRouter` for fast, LLM-free classification of
user messages into typed :class:`IntentType` values and dispatch to the
appropriate handler function.

Public API::

    from agent.conversation import AgentSession, SessionError
    from agent.conversation import IntentType, IntentRouter

Example — session management::

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from agent.conversation import AgentSession

    session = AgentSession(
        agent_id="550e8400-e29b-41d4-a716-446655440000",
        session_factory=my_async_sessionmaker,
    )
    await session.start()
    await session.add_message("user", "What is the current BTC price?")
    context = await session.get_context()
    await session.end()

Example — intent routing::

    from agent.conversation import IntentRouter, IntentType

    router = IntentRouter()
    intent, handler = router.route("show me my portfolio balance")
    result = await handler(session, "show me my portfolio balance")
"""

from agent.conversation.router import IntentRouter, IntentType
from agent.conversation.session import AgentSession, SessionError

__all__ = [
    "AgentSession",
    "IntentRouter",
    "IntentType",
    "SessionError",
]
