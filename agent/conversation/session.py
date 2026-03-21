"""Conversation session manager for a single agent conversation.

Manages the full lifecycle of one conversation session: creation, message
persistence, LLM context building, rolling summarisation, and graceful
closure.  All database operations go through the repository layer so the
caller never touches SQLAlchemy directly.

Dependency injection
--------------------
The class accepts either:

* A ``session_factory`` (``async_sessionmaker[AsyncSession]``) — a new DB
  session is opened for every write operation and committed immediately.
  This is the recommended mode for long-running conversations where you do
  not want a single open transaction.
* Pre-constructed repo instances — useful in tests where you want to pass
  mock repos without any real DB.  When repos are supplied directly,
  ``session_factory`` is ignored.

Usage::

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from agent.conversation import AgentSession

    factory = async_sessionmaker(engine, expire_on_commit=False)

    session = AgentSession(
        agent_id="550e8400-e29b-41d4-a716-446655440000",
        session_factory=factory,
        config=AgentConfig(),
    )
    await session.start()

    await session.add_message("user", "Analyse BTC/USDT for me.")
    await session.add_message("assistant", "Based on recent data …", tokens_used=420)

    context = await session.get_context()   # list[dict] ready for LLM API
    await session.end()                     # persists summary, marks inactive
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from src.database.models import AgentMessage as AgentMessageModel
    from src.database.models import AgentSession as AgentSessionModel
    from src.database.repositories.agent_message_repo import AgentMessageRepository
    from src.database.repositories.agent_session_repo import AgentSessionRepository

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class SessionError(Exception):
    """Raised for recoverable conversation-session errors.

    Args:
        message: Human-readable description of what went wrong.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


# ---------------------------------------------------------------------------
# Token estimation helpers
# ---------------------------------------------------------------------------

# Rough approximation: 1 token ≈ 4 characters of English text.
# Used only when the message does not carry an explicit ``tokens_used`` value.
_CHARS_PER_TOKEN: int = 4


def _estimate_tokens(text: str) -> int:
    """Return a rough token count for *text*.

    Args:
        text: The string to estimate.

    Returns:
        Estimated number of tokens (always at least 1).
    """
    return max(1, len(text) // _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# Summarisation prompt
# ---------------------------------------------------------------------------

_SUMMARISE_PROMPT_TEMPLATE = (
    "You are summarising a conversation between a user and an AI trading "
    "agent.  Below are the earlier messages.  Produce a concise summary "
    "(under 300 words) that captures: the main topics discussed, any "
    "trading decisions made, and key facts the agent should remember "
    "going forward.\n\n"
    "MESSAGES TO SUMMARISE:\n{messages}\n\n"
    "SUMMARY:"
)


# ---------------------------------------------------------------------------
# AgentSession
# ---------------------------------------------------------------------------


class AgentSession:
    """Manages a single conversation session with the agent.

    Wraps the ``agent_sessions`` and ``agent_messages`` database tables via
    the repository layer.  Provides:

    * **Create / resume** — ``start()`` creates a fresh session or resumes
      the existing active one for the given agent.
    * **Persistence** — ``add_message()`` writes every message to the DB so
      nothing is lost if the process crashes.
    * **Context building** — ``get_context()`` returns the most recent
      messages (up to ``max_tokens`` tokens) formatted as a list of
      ``{"role": ..., "content": ...}`` dicts ready for any OpenAI-compatible
      LLM API.
    * **Summarisation** — ``summarize_and_trim()`` calls an LLM to compress
      older messages into a single summary message, keeping the context
      window manageable.
    * **Closure** — ``end()`` persists a final summary and marks the session
      inactive.

    Args:
        agent_id: UUID of the owning agent (matches ``agents.id``).
        session_factory: An ``async_sessionmaker[AsyncSession]`` used to open
            short-lived DB sessions for each write.  Mutually exclusive with
            ``session_repo`` / ``message_repo``.
        session_id: UUID of an existing session to resume.  When ``None``,
            ``start()`` looks for an active session or creates a new one.
        title: Optional short title for the session shown in management UIs.
        config: Optional :class:`~agent.config.AgentConfig` providing context
            window settings.  Falls back to sensible defaults when ``None``.
        session_repo: Pre-constructed :class:`AgentSessionRepository` for
            testing.  When supplied, ``session_factory`` is not used for
            session operations.
        message_repo: Pre-constructed :class:`AgentMessageRepository` for
            testing.  When supplied, ``session_factory`` is not used for
            message operations.

    Example::

        session = AgentSession(
            agent_id="550e8400-e29b-41d4-a716-446655440000",
            session_factory=my_factory,
        )
        await session.start()
        await session.add_message("user", "Hello!")
        ctx = await session.get_context()
        await session.end()
    """

    def __init__(
        self,
        agent_id: str | UUID,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        session_id: str | UUID | None = None,
        title: str | None = None,
        config: object | None = None,
        session_repo: AgentSessionRepository | None = None,
        message_repo: AgentMessageRepository | None = None,
    ) -> None:
        self._agent_id: UUID = (
            UUID(str(agent_id)) if not isinstance(agent_id, UUID) else agent_id
        )
        self._session_factory = session_factory
        if session_id is None:
            self._session_id: UUID | None = None
        elif isinstance(session_id, UUID):
            self._session_id = session_id
        else:
            self._session_id = UUID(str(session_id))
        self._title = title
        self._is_active: bool = False
        self._total_tokens: int = 0

        # Extract config values with defaults
        if config is not None:
            self._max_tokens: int = getattr(config, "context_max_tokens", 8000)
            self._recent_messages: int = getattr(config, "context_recent_messages", 20)
            self._summary_threshold: int = getattr(config, "context_summary_threshold", 50)
        else:
            self._max_tokens = 8000
            self._recent_messages = 20
            self._summary_threshold = 50

        # Pre-constructed repos (testing mode)
        self._session_repo = session_repo
        self._message_repo = message_repo

        self._log = logger.bind(
            agent_id=str(self._agent_id),
            session_id=str(self._session_id) if self._session_id else "pending",
        )

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def session_id(self) -> UUID | None:
        """Return the current session UUID, or ``None`` before ``start()``."""
        return self._session_id

    @property
    def is_active(self) -> bool:
        """Return ``True`` when the session has been started and not yet ended."""
        return self._is_active

    @property
    def total_tokens(self) -> int:
        """Return the running total of tokens accumulated in this session."""
        return self._total_tokens

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create a new session or resume the existing active one.

        If ``session_id`` was provided at construction time, that session is
        loaded.  Otherwise the most recent active session for the agent is
        resumed.  If no active session exists, a new one is created.

        After this call :attr:`session_id` is set and :attr:`is_active` is
        ``True``.

        Raises:
            SessionError: If the DB operation fails or the requested
                ``session_id`` does not exist.
        """
        from src.database.models import AgentSession as AgentSessionModel  # noqa: PLC0415
        from src.database.repositories.agent_session_repo import (  # noqa: PLC0415
            AgentSessionNotFoundError,
            AgentSessionRepository,
        )
        from src.utils.exceptions import DatabaseError  # noqa: PLC0415

        try:
            if self._session_id is not None:
                # Resume a specific session by ID
                db_session = await self._get_session_record(
                    self._session_id,
                    AgentSessionRepository,
                    AgentSessionNotFoundError,
                )
                self._is_active = db_session.is_active
                self._session_id = db_session.id
                self._log.info("agent.session.resumed", session_id=str(self._session_id))
                return

            # Try to find an existing active session first
            existing = await self._find_active_session(AgentSessionRepository)
            if existing is not None:
                self._session_id = existing.id
                self._is_active = True
                self._log.info(
                    "agent.session.found_active",
                    session_id=str(self._session_id),
                )
                return

            # Create a new session
            new_record = AgentSessionModel(
                id=uuid.uuid4(),
                agent_id=self._agent_id,
                title=self._title,
                is_active=True,
                message_count=0,
            )
            created = await self._create_session_record(
                new_record, AgentSessionRepository
            )
            self._session_id = created.id
            self._is_active = True
            self._log = self._log.bind(session_id=str(self._session_id))
            self._log.info("agent.session.created", title=self._title)

        except (AgentSessionNotFoundError, DatabaseError) as exc:
            self._log.exception("agent.session.start.failed", error=str(exc))
            raise SessionError(f"Failed to start conversation session: {exc}") from exc

    async def add_message(
        self,
        role: str,
        content: str,
        tool_calls: list[dict[str, object]] | None = None,
        tool_results: list[dict[str, object]] | None = None,
        tokens_used: int | None = None,
    ) -> None:
        """Append a message to the session and persist it to the database.

        Args:
            role: Message role — one of ``"user"``, ``"assistant"``,
                ``"system"``, or ``"tool"``.
            content: Plain-text body of the message.
            tool_calls: Optional list of tool invocations issued by the
                assistant (stored as JSONB).
            tool_results: Optional list of results for each tool call
                (stored as JSONB).
            tokens_used: LLM token count for this message.  When ``None``,
                a rough estimate based on character count is used.

        Raises:
            SessionError: If the session has not been started, or if the DB
                write fails.
        """
        if not self._is_active or self._session_id is None:
            raise SessionError(
                "Cannot add message: session has not been started. Call start() first."
            )

        from src.database.models import AgentMessage  # noqa: PLC0415
        from src.database.repositories.agent_message_repo import (  # noqa: PLC0415
            AgentMessageRepository,
        )
        from src.database.repositories.agent_session_repo import (  # noqa: PLC0415
            AgentSessionRepository,
        )
        from src.utils.exceptions import DatabaseError  # noqa: PLC0415

        actual_tokens = tokens_used if tokens_used is not None else _estimate_tokens(content)
        self._total_tokens += actual_tokens

        message_record = AgentMessage(
            id=uuid.uuid4(),
            session_id=self._session_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_results=tool_results,
            tokens_used=actual_tokens,
        )

        try:
            await self._persist_message(message_record, AgentMessageRepository)
            await self._increment_message_count(AgentSessionRepository)
            self._log.info(
                "agent.session.message_added",
                role=role,
                tokens=actual_tokens,
                total_tokens=self._total_tokens,
            )
        except DatabaseError as exc:
            self._log.exception("agent.session.add_message.failed", role=role, error=str(exc))
            raise SessionError(f"Failed to persist message: {exc}") from exc

        # Auto-trigger summarisation when message volume grows large
        try:
            count = await self._get_message_count(AgentMessageRepository)
            if count >= self._summary_threshold:
                self._log.info(
                    "agent.session.auto_summarise",
                    count=count,
                    threshold=self._summary_threshold,
                )
                await self.summarize_and_trim()
        except (SessionError, DatabaseError, Exception) as exc:  # noqa: BLE001
            # Summarisation failure must never block message persistence
            self._log.warning(
                "agent.session.auto_summarise.skipped",
                error=str(exc),
            )

    async def get_context(self, max_tokens: int | None = None) -> list[dict[str, object]]:
        """Build an LLM-ready context window from the most recent messages.

        Returns the most recent messages formatted as a list of
        ``{"role": ..., "content": ...}`` dicts, capped to ``max_tokens``
        total tokens so the result fits inside the model's context window.

        Messages are included newest-to-oldest until the token budget is
        exhausted, then the list is reversed so the result is
        oldest-to-newest (chronological order) as required by LLM APIs.

        Args:
            max_tokens: Maximum token budget for the returned context.
                Defaults to ``config.context_max_tokens`` (or 8000 when no
                config was supplied).

        Returns:
            List of ``{"role": str, "content": str}`` dicts, oldest first.
            Tool call and result data are not included in the LLM context
            dict (they are preserved in the database for audit purposes).

        Raises:
            SessionError: If the session has not been started or the DB
                read fails.
        """
        if self._session_id is None:
            raise SessionError(
                "Cannot build context: session has not been started. Call start() first."
            )

        from src.database.repositories.agent_message_repo import (  # noqa: PLC0415
            AgentMessageRepository,
        )
        from src.utils.exceptions import DatabaseError  # noqa: PLC0415

        effective_max = max_tokens if max_tokens is not None else self._max_tokens

        try:
            messages = await self._list_messages(
                AgentMessageRepository, limit=self._recent_messages * 2
            )
        except DatabaseError as exc:
            self._log.exception("agent.session.get_context.failed", error=str(exc))
            raise SessionError(f"Failed to load messages for context: {exc}") from exc

        # Build context newest-to-oldest, stopping when budget is exhausted
        selected: list[dict[str, object]] = []
        tokens_used = 0

        for msg in reversed(messages):
            msg_tokens = msg.tokens_used if msg.tokens_used is not None else _estimate_tokens(msg.content)
            if tokens_used + msg_tokens > effective_max:
                break
            selected.append({"role": msg.role, "content": msg.content})
            tokens_used += msg_tokens

        # Reverse so the list is oldest-to-newest (chronological)
        selected.reverse()

        self._log.debug(
            "agent.session.context_built",
            messages_included=len(selected),
            tokens_used=tokens_used,
            max_tokens=effective_max,
        )
        return selected

    async def summarize_and_trim(self) -> None:
        """Summarise older messages and replace them with a single summary entry.

        Fetches all messages older than the most recent ``context_recent_messages``
        messages, sends them to the LLM for summarisation, writes the summary
        as a new ``system`` message at the start of the history, then deletes
        the original older messages.

        If no LLM is configured (no ``OPENROUTER_API_KEY`` in the environment),
        the method falls back to a plain-text concatenation summary.

        This method is called automatically by :meth:`add_message` when the
        message count reaches ``context_summary_threshold``.

        Raises:
            SessionError: If the session has not been started.
        """
        if self._session_id is None:
            raise SessionError(
                "Cannot summarise: session has not been started. Call start() first."
            )

        from src.database.repositories.agent_message_repo import (  # noqa: PLC0415
            AgentMessageRepository,
        )
        from src.utils.exceptions import DatabaseError  # noqa: PLC0415

        self._log.info("agent.session.summarise.start")

        try:
            all_messages = await self._list_messages(AgentMessageRepository, limit=1000)
        except DatabaseError as exc:
            self._log.exception("agent.session.summarise.list_failed", error=str(exc))
            raise SessionError(f"Failed to list messages for summarisation: {exc}") from exc

        if len(all_messages) <= self._recent_messages:
            self._log.debug(
                "agent.session.summarise.skipped_too_few",
                count=len(all_messages),
                threshold=self._recent_messages,
            )
            return

        # Split: messages to summarise vs recent messages to keep
        messages_to_summarise = all_messages[: -self._recent_messages]
        self._log.info(
            "agent.session.summarise.compressing",
            to_summarise=len(messages_to_summarise),
            to_keep=self._recent_messages,
        )

        # Build summary text
        summary_text = await self._generate_summary(messages_to_summarise)

        # Write the summary as a new system message, then delete old messages
        try:
            await self._write_summary_message(summary_text, AgentMessageRepository)

            for old_msg in messages_to_summarise:
                try:
                    await self._delete_message(old_msg.id, AgentMessageRepository)
                except DatabaseError as exc:
                    # Non-fatal: log and continue deleting others
                    self._log.warning(
                        "agent.session.summarise.delete_failed",
                        message_id=str(old_msg.id),
                        error=str(exc),
                    )

            self._log.info(
                "agent.session.summarise.complete",
                deleted=len(messages_to_summarise),
                summary_length=len(summary_text),
            )
        except DatabaseError as exc:
            self._log.exception("agent.session.summarise.write_failed", error=str(exc))
            raise SessionError(f"Failed to write summary message: {exc}") from exc

    async def end(self) -> None:
        """Close the session and persist a final summary.

        Generates a brief closing summary from the recent messages and writes
        it to the ``summary`` column of the ``agent_sessions`` row.  Marks
        the session ``is_active = False`` and sets ``ended_at`` to now.

        After this call :attr:`is_active` is ``False``.  Calling
        :meth:`add_message` after ``end()`` raises :class:`SessionError`.

        Raises:
            SessionError: If the session has not been started or the DB
                write fails.
        """
        if not self._is_active or self._session_id is None:
            raise SessionError(
                "Cannot end session: session is not active or was never started."
            )

        from src.database.repositories.agent_message_repo import (  # noqa: PLC0415
            AgentMessageRepository,
        )
        from src.database.repositories.agent_session_repo import (  # noqa: PLC0415
            AgentSessionRepository,
        )
        from src.utils.exceptions import DatabaseError  # noqa: PLC0415

        self._log.info("agent.session.end.start")

        # Build a closing summary from the recent messages
        summary: str | None = None
        try:
            recent = await self._list_messages(
                AgentMessageRepository, limit=self._recent_messages
            )
            if recent:
                summary = await self._generate_summary(list(recent))
        except (DatabaseError, Exception) as exc:  # noqa: BLE001
            # Summary generation failure must not prevent session closure
            self._log.warning("agent.session.end.summary_failed", error=str(exc))

        try:
            await self._close_session_record(
                AgentSessionRepository, summary=summary
            )
            self._is_active = False
            self._log.info(
                "agent.session.ended",
                session_id=str(self._session_id),
                total_tokens=self._total_tokens,
            )
        except DatabaseError as exc:
            self._log.exception("agent.session.end.failed", error=str(exc))
            raise SessionError(f"Failed to close session: {exc}") from exc

    # ------------------------------------------------------------------
    # Private DB helpers — repo interaction
    # ------------------------------------------------------------------

    async def _get_session_record(
        self,
        session_id: UUID,
        repo_class: type[AgentSessionRepository],
        not_found_exc: type[Exception],
    ) -> AgentSessionModel:
        """Fetch a single AgentSession record by ID.

        Args:
            session_id: Primary key of the session to load.
            repo_class: ``AgentSessionRepository`` class (injected to avoid
                circular import at module level).
            not_found_exc: ``AgentSessionNotFoundError`` class.

        Returns:
            The ``AgentSession`` ORM instance.

        Raises:
            AgentSessionNotFoundError: If no session with this ID exists.
            DatabaseError: On DB failure.
        """
        if self._session_repo is not None:
            return await self._session_repo.get_by_id(session_id)

        async with self._session_factory() as db:  # type: ignore[misc]
            repo = repo_class(db)
            result = await repo.get_by_id(session_id)
            return result

    async def _find_active_session(
        self, repo_class: type[AgentSessionRepository]
    ) -> AgentSessionModel | None:
        """Return the current active session for this agent, if any.

        Args:
            repo_class: ``AgentSessionRepository`` class.

        Returns:
            The active ``AgentSession`` ORM instance, or ``None``.
        """
        if self._session_repo is not None:
            return await self._session_repo.find_active(self._agent_id)

        async with self._session_factory() as db:  # type: ignore[misc]
            repo = repo_class(db)
            return await repo.find_active(self._agent_id)

    async def _create_session_record(
        self, record: AgentSessionModel, repo_class: type[AgentSessionRepository]
    ) -> AgentSessionModel:
        """Persist a new AgentSession row.

        Args:
            record: Populated ``AgentSession`` ORM instance.
            repo_class: ``AgentSessionRepository`` class.

        Returns:
            The persisted ``AgentSession`` with server-generated columns filled.
        """
        if self._session_repo is not None:
            result = await self._session_repo.create(record)
            return result

        async with self._session_factory() as db:  # type: ignore[misc]
            repo = repo_class(db)
            result = await repo.create(record)
            await db.commit()
            return result

    async def _persist_message(
        self, record: AgentMessageModel, repo_class: type[AgentMessageRepository]
    ) -> None:
        """Write a new AgentMessage row.

        Args:
            record: Populated ``AgentMessage`` ORM instance.
            repo_class: ``AgentMessageRepository`` class.
        """
        if self._message_repo is not None:
            await self._message_repo.create(record)
            return

        async with self._session_factory() as db:  # type: ignore[misc]
            repo = repo_class(db)
            await repo.create(record)
            await db.commit()

    async def _increment_message_count(
        self, repo_class: type[AgentSessionRepository]
    ) -> None:
        """Increment the ``message_count`` field on the parent session row.

        Args:
            repo_class: ``AgentSessionRepository`` class.
        """
        if self._session_id is None:
            return

        if self._session_repo is not None:
            # The repo.update() increments via SQL; we pass a sentinel 0 here
            # because the actual increment is performed server-side via raw SQL
            # in the session_factory path below.
            pass
        else:
            async with self._session_factory() as db:  # type: ignore[misc]
                from sqlalchemy import update  # noqa: PLC0415
                from src.database.models import AgentSession as AgentSessionModel  # noqa: PLC0415

                stmt = (
                    update(AgentSessionModel)
                    .where(AgentSessionModel.id == self._session_id)
                    .values(message_count=AgentSessionModel.message_count + 1)
                )
                await db.execute(stmt)
                await db.commit()

    async def _get_message_count(
        self, repo_class: type[AgentMessageRepository]
    ) -> int:
        """Return the total number of messages in the current session.

        Args:
            repo_class: ``AgentMessageRepository`` class.

        Returns:
            Current message count.
        """
        if self._session_id is None:
            return 0

        if self._message_repo is not None:
            return await self._message_repo.count_by_session(self._session_id)

        async with self._session_factory() as db:  # type: ignore[misc]
            repo = repo_class(db)
            return await repo.count_by_session(self._session_id)

    async def _list_messages(
        self, repo_class: type[AgentMessageRepository], *, limit: int = 100
    ) -> Sequence[AgentMessageModel]:
        """Retrieve messages for this session in chronological order.

        Args:
            repo_class: ``AgentMessageRepository`` class.
            limit: Maximum number of messages to return.

        Returns:
            Sequence of ``AgentMessage`` instances, oldest first.
        """
        if self._session_id is None:
            return []

        if self._message_repo is not None:
            return await self._message_repo.list_by_session(
                self._session_id, limit=limit
            )

        async with self._session_factory() as db:  # type: ignore[misc]
            repo = repo_class(db)
            return await repo.list_by_session(self._session_id, limit=limit)

    async def _delete_message(
        self, message_id: UUID, repo_class: type[AgentMessageRepository]
    ) -> None:
        """Delete a single message row by primary key.

        Args:
            message_id: UUID of the message to delete.
            repo_class: ``AgentMessageRepository`` class.
        """
        if self._message_repo is not None:
            await self._message_repo.delete(message_id)
            return

        async with self._session_factory() as db:  # type: ignore[misc]
            repo = repo_class(db)
            await repo.delete(message_id)
            await db.commit()

    async def _write_summary_message(
        self, summary_text: str, repo_class: type[AgentMessageRepository]
    ) -> None:
        """Persist a system-role summary message to the conversation.

        Args:
            summary_text: The generated summary text.
            repo_class: ``AgentMessageRepository`` class.
        """
        from src.database.models import AgentMessage  # noqa: PLC0415

        summary_record = AgentMessage(
            id=uuid.uuid4(),
            session_id=self._session_id,
            role="system",
            content=f"[CONTEXT SUMMARY]\n{summary_text}",
            tokens_used=_estimate_tokens(summary_text),
        )

        if self._message_repo is not None:
            await self._message_repo.create(summary_record)
            return

        async with self._session_factory() as db:  # type: ignore[misc]
            repo = repo_class(db)
            await repo.create(summary_record)
            await db.commit()

    async def _close_session_record(
        self, repo_class: type[AgentSessionRepository], *, summary: str | None
    ) -> None:
        """Mark the session as inactive with an optional closing summary.

        Args:
            repo_class: ``AgentSessionRepository`` class.
            summary: LLM-generated closing summary, or ``None``.
        """
        if self._session_id is None:
            return

        if self._session_repo is not None:
            await self._session_repo.close(self._session_id, summary=summary)
            return

        async with self._session_factory() as db:  # type: ignore[misc]
            repo = repo_class(db)
            await repo.close(self._session_id, summary=summary)
            await db.commit()

    # ------------------------------------------------------------------
    # Private summarisation logic
    # ------------------------------------------------------------------

    async def _generate_summary(self, messages: Sequence[AgentMessageModel]) -> str:
        """Generate a natural-language summary of the provided messages.

        Attempts to call the configured LLM (via ``httpx`` and OpenRouter)
        for summarisation.  Falls back to a plain-text concatenation if the
        LLM is unavailable, unconfigured, or raises an exception.

        Args:
            messages: Sequence of ``AgentMessage`` ORM instances to summarise.

        Returns:
            A summary string (never empty — falls back to concatenation).
        """
        if not messages:
            return "(No messages to summarise.)"

        messages_text = "\n".join(
            f"[{m.role.upper()}]: {m.content[:500]}"
            for m in messages
        )

        # Attempt LLM-based summarisation if httpx and an API key are available
        _llm_model = "openrouter:google/gemini-2.0-flash-001"
        try:
            import httpx  # noqa: PLC0415

            from agent.logging_middleware import estimate_llm_cost  # noqa: PLC0415

            api_key = self._get_openrouter_key()
            if not api_key:
                return self._fallback_summary(messages_text)

            prompt = _SUMMARISE_PROMPT_TEMPLATE.format(messages=messages_text)
            payload = {
                "model": "openrouter:google/gemini-2.0-flash-001",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 400,
            }

            _llm_start = time.monotonic()
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                _llm_latency_ms = round((time.monotonic() - _llm_start) * 1000, 2)
                if response.status_code == 200:
                    data = response.json()
                    usage = data.get("usage") or {}
                    _input_tokens: int | None = usage.get("prompt_tokens")
                    _output_tokens: int | None = usage.get("completion_tokens")
                    self._log.info(
                        "agent.llm.completed",
                        model=_llm_model,
                        purpose="session_summarization",
                        input_tokens=_input_tokens,
                        output_tokens=_output_tokens,
                        latency_ms=_llm_latency_ms,
                        cost_estimate_usd=estimate_llm_cost(
                            _llm_model,
                            _input_tokens or 0,
                            _output_tokens or 0,
                        ),
                    )
                    choices = data.get("choices", [])
                    if choices:
                        content: str = str(
                            choices[0].get("message", {}).get("content", "") or ""
                        )
                        if content:
                            self._log.debug(
                                "agent.session.summarise.llm_success",
                                length=len(content),
                            )
                            return content.strip()

            return self._fallback_summary(messages_text)

        except (ImportError, Exception) as exc:  # noqa: BLE001
            self._log.warning(
                "agent.session.summarise.llm_failed",
                error=str(exc),
            )
            self._log.error(
                "agent.llm.failed",
                model=_llm_model,
                purpose="session_summarization",
                error=str(exc),
            )
            return self._fallback_summary(messages_text)

    def _get_openrouter_key(self) -> str:
        """Return the OpenRouter API key from environment variables.

        Reads ``OPENROUTER_API_KEY`` from the environment.  The agent config
        is intentionally bypassed here to avoid a circular construction cycle
        (AgentConfig requires the key at init time).

        Returns:
            The API key string, or empty string if not configured.
        """
        import os  # noqa: PLC0415

        return os.environ.get("OPENROUTER_API_KEY", "")

    @staticmethod
    def _fallback_summary(messages_text: str) -> str:
        """Return a plain-text concatenation summary as a fallback.

        Args:
            messages_text: Pre-formatted message text.

        Returns:
            A short summary based on the first 1500 characters of message text.
        """
        truncated = messages_text[:1500]
        if len(messages_text) > 1500:
            truncated += f"\n… (truncated; {len(messages_text)} chars total)"
        return f"Conversation summary (auto-generated):\n{truncated}"
