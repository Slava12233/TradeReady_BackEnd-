"""Conversation history loader and search for the TradeReady agent.

Provides :class:`ConversationHistory` which wraps the repository layer to
load, paginate, and search :class:`~src.database.models.AgentMessage` rows
without the caller needing to manage database sessions directly.

All database operations use a ``session_factory`` (``async_sessionmaker``) to
open short-lived, auto-committed sessions — the same pattern used by
:class:`~agent.conversation.session.AgentSession`.

Usage::

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from agent.conversation.history import ConversationHistory, Message

    history = ConversationHistory(session_factory=my_factory)

    messages = await history.load_session(session_id="...")
    recent   = await history.load_recent(agent_id="...", limit=30)
    matches  = await history.search(agent_id="...", query="BTC drawdown")
    summary  = await history.get_summary(session_id="...")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Message dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Message:
    """A single conversation message returned by :class:`ConversationHistory`.

    This is a lightweight, ORM-free value object.  Callers outside the
    database layer should use this type rather than depending on the
    SQLAlchemy ``AgentMessage`` ORM class directly.

    Attributes:
        id: UUID string of the message record.
        session_id: UUID string of the parent session.
        role: Message role — ``"user"``, ``"assistant"``, ``"system"``, or
            ``"tool"``.
        content: Plain-text body of the message.
        tokens_used: LLM token count, or ``None`` when not recorded.
        created_at: UTC timestamp of message creation.
    """

    id: str
    session_id: str
    role: str
    content: str
    tokens_used: int | None
    created_at: datetime


# ---------------------------------------------------------------------------
# ConversationHistory
# ---------------------------------------------------------------------------


class ConversationHistory:
    """Loads, paginates, and searches conversation messages from the database.

    Wraps :class:`~src.database.repositories.agent_message_repo.AgentMessageRepository`
    and :class:`~src.database.repositories.agent_session_repo.AgentSessionRepository`
    behind a clean, ORM-free interface.

    All methods open their own short-lived database sessions so the caller
    does not need to manage session lifetimes.  Methods degrade gracefully:
    database or import errors are logged and an empty result is returned
    rather than raising, making it safe to call from context-building code
    that must not crash.

    Args:
        session_factory: An ``async_sessionmaker[AsyncSession]`` used to open
            short-lived read-only sessions.  Pass ``None`` only in tests that
            supply ``message_repo`` and ``session_repo`` directly.
        message_repo: Pre-constructed
            :class:`~src.database.repositories.agent_message_repo.AgentMessageRepository`
            for testing.  When supplied, ``session_factory`` is not used for
            message operations.
        session_repo: Pre-constructed
            :class:`~src.database.repositories.agent_session_repo.AgentSessionRepository`
            for testing.  When supplied, ``session_factory`` is not used for
            session operations.

    Example::

        history = ConversationHistory(session_factory=my_factory)
        messages = await history.load_session("550e8400-e29b-41d4-a716-446655440000")
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        message_repo: object | None = None,
        session_repo: object | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._message_repo = message_repo
        self._session_repo = session_repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def load_session(
        self,
        session_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Message]:
        """Load all messages for a single conversation session.

        Returns messages in chronological order (oldest first) with
        optional pagination for very long sessions.

        Args:
            session_id: UUID string of the session to load.
            limit: Maximum number of messages to return.  Defaults to 200.
            offset: Number of messages to skip for pagination.  Defaults to 0.

        Returns:
            List of :class:`Message` objects, oldest first.  Empty list on
            error or if no messages exist.
        """
        log = logger.bind(session_id=session_id, limit=limit, offset=offset)
        try:
            sid = UUID(session_id)

            if self._message_repo is not None:
                rows = await self._message_repo.list_by_session(  # type: ignore[union-attr]
                    sid, limit=limit, offset=offset
                )
                return [_orm_to_message(r) for r in rows]

            async with self._session_factory() as db:  # type: ignore[misc]
                from src.database.repositories.agent_message_repo import (  # noqa: PLC0415
                    AgentMessageRepository,
                )

                repo = AgentMessageRepository(db)
                rows = await repo.list_by_session(sid, limit=limit, offset=offset)
                return [_orm_to_message(r) for r in rows]

        except Exception as exc:  # noqa: BLE001
            log.warning("history.load_session.failed", error=str(exc))
            return []

    async def load_recent(
        self,
        agent_id: str,
        *,
        limit: int = 50,
    ) -> list[Message]:
        """Load the most recent messages across all sessions for an agent.

        Fetches the agent's sessions ordered newest-first, then iterates
        through them collecting messages until ``limit`` is reached.  This
        gives callers a flat chronological view of recent activity without
        needing to know which session each message belongs to.

        Args:
            agent_id: UUID string of the agent.
            limit: Maximum total messages to return across all sessions.
                Defaults to 50.

        Returns:
            List of :class:`Message` objects, oldest first overall.  Empty
            list on error.
        """
        log = logger.bind(agent_id=agent_id, limit=limit)
        try:
            aid = UUID(agent_id)
            messages: list[Message] = []

            if self._session_repo is not None and self._message_repo is not None:
                sessions = await self._session_repo.list_by_agent(  # type: ignore[union-attr]
                    aid, include_closed=True, limit=10, offset=0
                )
                for session_row in sessions:
                    if len(messages) >= limit:
                        break
                    remaining = limit - len(messages)
                    rows = await self._message_repo.list_by_session(  # type: ignore[union-attr]
                        session_row.id, limit=remaining, offset=0
                    )
                    messages.extend(_orm_to_message(r) for r in rows)
                messages.sort(key=lambda m: m.created_at)
                return messages[-limit:]

            async with self._session_factory() as db:  # type: ignore[misc]
                from src.database.repositories.agent_message_repo import (  # noqa: PLC0415
                    AgentMessageRepository,
                )
                from src.database.repositories.agent_session_repo import (  # noqa: PLC0415
                    AgentSessionRepository,
                )

                session_repo = AgentSessionRepository(db)
                sessions = await session_repo.list_by_agent(
                    aid, include_closed=True, limit=10, offset=0
                )

                msg_repo = AgentMessageRepository(db)
                for session_row in sessions:
                    if len(messages) >= limit:
                        break
                    remaining = limit - len(messages)
                    rows = await msg_repo.list_by_session(
                        session_row.id, limit=remaining, offset=0
                    )
                    messages.extend(_orm_to_message(r) for r in rows)

            messages.sort(key=lambda m: m.created_at)
            return messages[-limit:]

        except Exception as exc:  # noqa: BLE001
            log.warning("history.load_recent.failed", error=str(exc))
            return []

    async def search(
        self,
        agent_id: str,
        query: str,
        *,
        limit: int = 20,
    ) -> list[Message]:
        """Search messages for an agent by keyword substring match.

        Performs a case-insensitive search across all messages belonging to
        the agent's sessions.  Results are sorted by relevance — messages
        whose content begins with the query rank first, then matches that
        contain the query, all ordered newest-first within each relevance
        tier.

        Because the ``agent_messages`` table is indexed on
        ``(session_id, created_at)`` rather than on full text, this
        implementation fetches the agent's session IDs first, then issues
        per-session queries with Python-side filtering.  The approach is
        efficient for the typical case of agents with fewer than 100 sessions
        and is correct for all query strings.

        Args:
            agent_id: UUID string of the agent.
            query: Keyword or phrase to search for in message content
                (case-insensitive).
            limit: Maximum number of matching messages to return.  Defaults
                to 20.

        Returns:
            List of :class:`Message` objects ordered by relevance.  Empty
            list on error or no matches.
        """
        log = logger.bind(agent_id=agent_id, query=query, limit=limit)
        if not query or not query.strip():
            return []

        try:
            aid = UUID(agent_id)
            query_lower = query.lower().strip()
            matches: list[Message] = []

            async with self._session_factory() as db:  # type: ignore[misc]
                from src.database.repositories.agent_message_repo import (  # noqa: PLC0415
                    AgentMessageRepository,
                )
                from src.database.repositories.agent_session_repo import (  # noqa: PLC0415
                    AgentSessionRepository,
                )

                session_repo = AgentSessionRepository(db)
                sessions = await session_repo.list_by_agent(
                    aid, include_closed=True, limit=100, offset=0
                )

                msg_repo = AgentMessageRepository(db)
                # Pull up to 500 messages per session to keep latency bounded.
                for session_row in sessions:
                    rows = await msg_repo.list_by_session(
                        session_row.id, limit=500, offset=0
                    )
                    for row in rows:
                        if query_lower in row.content.lower():
                            matches.append(_orm_to_message(row))

            # Sort: messages starting with query rank highest, then newest first.
            def _rank(m: Message) -> tuple[int, datetime]:
                starts = m.content.lower().startswith(query_lower)
                return (0 if starts else 1, m.created_at)

            matches.sort(key=_rank, reverse=True)
            # Keep reverse sort order within tier by timestamp, then cap.
            # Re-sort: ascending rank, then descending created_at within same rank.
            matches.sort(key=lambda m: (0 if m.content.lower().startswith(query_lower) else 1, m.created_at))
            # Reverse the second-level sort to get newest-first per tier.
            result: list[Message] = []
            tier_start: list[Message] = []
            tier_contains: list[Message] = []
            for m in matches:
                if m.content.lower().startswith(query_lower):
                    tier_start.append(m)
                else:
                    tier_contains.append(m)
            tier_start.sort(key=lambda m: m.created_at, reverse=True)
            tier_contains.sort(key=lambda m: m.created_at, reverse=True)
            result = (tier_start + tier_contains)[:limit]

            log.debug("history.search.done", matches=len(result))
            return result

        except Exception as exc:  # noqa: BLE001
            log.warning("history.search.failed", error=str(exc))
            return []

    async def get_summary(self, session_id: str) -> str | None:
        """Return the LLM-generated summary for a closed session.

        Reads the ``summary`` column from the ``agent_sessions`` table.
        Active sessions may not yet have a summary; in that case ``None``
        is returned.

        Args:
            session_id: UUID string of the session.

        Returns:
            The summary text string, or ``None`` if no summary has been
            written yet or the session does not exist.
        """
        log = logger.bind(session_id=session_id)
        try:
            sid = UUID(session_id)

            if self._session_repo is not None:
                row = await self._session_repo.get_by_id(sid)  # type: ignore[union-attr]
                return row.summary

            async with self._session_factory() as db:  # type: ignore[misc]
                from src.database.repositories.agent_session_repo import (  # noqa: PLC0415
                    AgentSessionRepository,
                )

                repo = AgentSessionRepository(db)
                row = await repo.get_by_id(sid)
                return row.summary

        except Exception as exc:  # noqa: BLE001
            log.warning("history.get_summary.failed", error=str(exc))
            return None


# ---------------------------------------------------------------------------
# Private helper
# ---------------------------------------------------------------------------


def _orm_to_message(row: object) -> Message:
    """Convert an :class:`~src.database.models.AgentMessage` ORM row to a
    :class:`Message` value object.

    Uses ``getattr`` so this module does not import the ORM class directly
    (avoids a hard dependency on ``src`` from the ``agent`` package at import
    time, consistent with the lazy-import pattern used throughout this
    package).

    Args:
        row: A hydrated SQLAlchemy ``AgentMessage`` instance.

    Returns:
        A fully-populated :class:`Message` dataclass.
    """
    return Message(
        id=str(getattr(row, "id")),
        session_id=str(getattr(row, "session_id")),
        role=str(getattr(row, "role")),
        content=str(getattr(row, "content")),
        tokens_used=getattr(row, "tokens_used", None),
        created_at=getattr(row, "created_at"),
    )
