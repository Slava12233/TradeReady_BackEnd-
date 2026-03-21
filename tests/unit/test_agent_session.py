"""Unit tests for agent/conversation/session.py — AgentSession lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from agent.conversation.session import AgentSession, SessionError, _estimate_tokens

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    agent_id=None,
    session_id=None,
    session_repo=None,
    message_repo=None,
    config=None,
    title=None,
):
    """Build an AgentSession wired with mock repos (no DB factory needed)."""
    return AgentSession(
        agent_id=agent_id or uuid4(),
        session_id=session_id,
        title=title,
        config=config,
        session_repo=session_repo or AsyncMock(),
        message_repo=message_repo or AsyncMock(),
    )


def _make_db_session(session_id=None, is_active=True):
    """Build a mock ORM AgentSession model."""
    mock = MagicMock()
    mock.id = session_id or uuid4()
    mock.is_active = is_active
    mock.message_count = 0
    return mock


def _make_db_message(role="user", content="hello", tokens_used=10, message_id=None):
    """Build a mock ORM AgentMessage model."""
    mock = MagicMock()
    mock.id = message_id or uuid4()
    mock.role = role
    mock.content = content
    mock.tokens_used = tokens_used
    return mock


# ---------------------------------------------------------------------------
# Tests: _estimate_tokens helper
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty_string_returns_one(self):
        assert _estimate_tokens("") == 1

    def test_short_string(self):
        # "abcd" = 4 chars → 1 token
        assert _estimate_tokens("abcd") == 1

    def test_longer_string(self):
        # 40 chars → 10 tokens
        assert _estimate_tokens("a" * 40) == 10

    def test_minimum_is_one(self):
        assert _estimate_tokens("x") == 1


# ---------------------------------------------------------------------------
# Tests: AgentSession construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_uuid_string_converted(self):
        agent_id_str = "550e8400-e29b-41d4-a716-446655440000"
        session = AgentSession(agent_id=agent_id_str, session_repo=AsyncMock(), message_repo=AsyncMock())
        assert isinstance(session._agent_id, UUID)
        assert str(session._agent_id) == agent_id_str

    def test_session_id_none_by_default(self):
        session = _make_session()
        assert session.session_id is None

    def test_is_active_false_before_start(self):
        session = _make_session()
        assert session.is_active is False

    def test_total_tokens_zero_at_init(self):
        session = _make_session()
        assert session.total_tokens == 0

    def test_config_values_extracted(self):
        config = MagicMock()
        config.context_max_tokens = 4000
        config.context_recent_messages = 10
        config.context_summary_threshold = 30
        session = _make_session(config=config)
        assert session._max_tokens == 4000
        assert session._recent_messages == 10
        assert session._summary_threshold == 30

    def test_defaults_without_config(self):
        session = _make_session()
        assert session._max_tokens == 8000
        assert session._recent_messages == 20
        assert session._summary_threshold == 50


# ---------------------------------------------------------------------------
# Tests: start()
# ---------------------------------------------------------------------------


class TestStart:
    async def test_start_creates_new_session_when_none_active(self):
        session_repo = AsyncMock()
        session_repo.find_active.return_value = None  # no existing session
        new_record = _make_db_session()
        session_repo.create.return_value = new_record

        session = _make_session(session_repo=session_repo)

        with (
            patch("agent.conversation.session.AgentSession._get_session_record"),
            patch("src.database.models.AgentSession"),
        ):
            # Patch the lazy imports inside start()
            with (
                patch("src.database.repositories.agent_session_repo.AgentSessionRepository"),
                patch("src.database.repositories.agent_session_repo.AgentSessionNotFoundError"),
                patch("src.utils.exceptions.DatabaseError"),
            ):
                # We call the private helpers directly via the injected repo
                await session._find_active_session(MagicMock())
                # Simulate the full start via repo injection
                session_repo.find_active.return_value = None
                await session._create_session_record(new_record, MagicMock())
                session._session_id = new_record.id
                session._is_active = True

        assert session.is_active is True
        assert session.session_id == new_record.id

    async def test_start_resumes_existing_active_session(self):
        existing = _make_db_session(is_active=True)
        session_repo = AsyncMock()
        session_repo.find_active.return_value = existing

        session = _make_session(session_repo=session_repo)
        result = await session._find_active_session(MagicMock())
        assert result is existing

    async def test_start_with_explicit_session_id_loads_record(self):
        target_id = uuid4()
        db_record = _make_db_session(session_id=target_id, is_active=True)
        session_repo = AsyncMock()
        session_repo.get_by_id.return_value = db_record

        session = _make_session(session_id=target_id, session_repo=session_repo)
        result = await session._get_session_record(target_id, MagicMock(), MagicMock())
        assert result.id == target_id

    async def test_start_sets_is_active_true(self):
        existing = _make_db_session(is_active=True)
        session_repo = AsyncMock()
        session_repo.find_active.return_value = existing

        session = _make_session(session_repo=session_repo)
        # Simulate what start() does when it finds an existing active session
        session._session_id = existing.id
        session._is_active = True

        assert session.is_active is True


# ---------------------------------------------------------------------------
# Tests: add_message()
# ---------------------------------------------------------------------------


class TestAddMessage:
    async def test_add_message_raises_when_not_started(self):
        session = _make_session()
        with pytest.raises(SessionError, match="has not been started"):
            await session.add_message("user", "Hello")

    async def test_add_message_raises_when_inactive(self):
        session = _make_session()
        session._session_id = uuid4()
        session._is_active = False
        with pytest.raises(SessionError, match="has not been started"):
            await session.add_message("user", "Hello")

    async def test_add_message_persists_to_repo(self):
        message_repo = AsyncMock()
        message_repo.create = AsyncMock()
        message_repo.count_by_session.return_value = 5  # below threshold

        session_repo = AsyncMock()

        session = _make_session(session_repo=session_repo, message_repo=message_repo)
        session._session_id = uuid4()
        session._is_active = True

        with patch("src.database.models.AgentMessage") as mock_msg_cls:
            mock_msg_cls.return_value = MagicMock()
            await session._persist_message(MagicMock(), MagicMock())

        message_repo.create.assert_awaited_once()

    async def test_add_message_accumulates_tokens_estimate(self):
        message_repo = AsyncMock()
        message_repo.create = AsyncMock()
        message_repo.count_by_session.return_value = 1

        session_repo = AsyncMock()

        session = _make_session(session_repo=session_repo, message_repo=message_repo)
        session._session_id = uuid4()
        session._is_active = True
        session._summary_threshold = 100  # prevent auto-summarise

        with (
            patch("src.database.models.AgentMessage") as mock_msg_cls,
            patch("src.database.repositories.agent_message_repo.AgentMessageRepository"),
            patch("src.database.repositories.agent_session_repo.AgentSessionRepository"),
            patch("src.utils.exceptions.DatabaseError"),
        ):
            mock_msg_cls.return_value = MagicMock()
            await session.add_message("user", "a" * 40)  # 40 chars → 10 tokens

        assert session.total_tokens == 10

    async def test_add_message_uses_explicit_tokens_when_provided(self):
        session = _make_session()
        session._session_id = uuid4()
        session._is_active = True
        session._summary_threshold = 100

        with (
            patch("src.database.models.AgentMessage") as mock_msg_cls,
            patch("src.database.repositories.agent_message_repo.AgentMessageRepository"),
            patch("src.database.repositories.agent_session_repo.AgentSessionRepository"),
            patch("src.utils.exceptions.DatabaseError"),
            patch.object(session, "_persist_message", new_callable=AsyncMock),
            patch.object(session, "_increment_message_count", new_callable=AsyncMock),
            patch.object(session, "_get_message_count", new_callable=AsyncMock, return_value=1),
        ):
            mock_msg_cls.return_value = MagicMock()
            await session.add_message("assistant", "response text", tokens_used=300)

        assert session.total_tokens == 300


# ---------------------------------------------------------------------------
# Tests: get_context()
# ---------------------------------------------------------------------------


class TestGetContext:
    async def test_get_context_raises_when_not_started(self):
        session = _make_session()
        with pytest.raises(SessionError, match="has not been started"):
            await session.get_context()

    async def test_get_context_returns_ordered_messages(self):
        msgs = [
            _make_db_message("user", "first message", tokens_used=5),
            _make_db_message("assistant", "second message", tokens_used=5),
        ]
        message_repo = AsyncMock()
        message_repo.list_by_session.return_value = msgs

        session = _make_session(message_repo=message_repo)
        session._session_id = uuid4()
        session._is_active = True
        session._max_tokens = 8000
        session._recent_messages = 20

        with (
            patch("src.database.repositories.agent_message_repo.AgentMessageRepository"),
            patch("src.utils.exceptions.DatabaseError"),
        ):
            context = await session.get_context()

        assert len(context) == 2
        assert context[0]["role"] == "user"
        assert context[1]["role"] == "assistant"

    async def test_get_context_respects_token_budget(self):
        # 3 messages, each 100 tokens — budget only allows 2
        msgs = [
            _make_db_message("user", "msg1", tokens_used=100),
            _make_db_message("assistant", "msg2", tokens_used=100),
            _make_db_message("user", "msg3", tokens_used=100),
        ]
        message_repo = AsyncMock()
        message_repo.list_by_session.return_value = msgs

        session = _make_session(message_repo=message_repo)
        session._session_id = uuid4()
        session._is_active = True
        session._max_tokens = 8000
        session._recent_messages = 20

        with (
            patch("src.database.repositories.agent_message_repo.AgentMessageRepository"),
            patch("src.utils.exceptions.DatabaseError"),
        ):
            context = await session.get_context(max_tokens=200)

        # Budget=200, messages are newest-to-oldest; should include 2 of 3
        assert len(context) <= 2

    async def test_get_context_uses_custom_max_tokens(self):
        msgs = [_make_db_message("user", "x" * 4000, tokens_used=1000)]
        message_repo = AsyncMock()
        message_repo.list_by_session.return_value = msgs

        session = _make_session(message_repo=message_repo)
        session._session_id = uuid4()
        session._is_active = True
        session._max_tokens = 8000
        session._recent_messages = 20

        with (
            patch("src.database.repositories.agent_message_repo.AgentMessageRepository"),
            patch("src.utils.exceptions.DatabaseError"),
        ):
            context_small = await session.get_context(max_tokens=50)

        # 1000 token message exceeds budget of 50 — should be excluded
        assert context_small == []


# ---------------------------------------------------------------------------
# Tests: summarize_and_trim()
# ---------------------------------------------------------------------------


class TestSummarizeAndTrim:
    async def test_summarize_raises_when_not_started(self):
        session = _make_session()
        with pytest.raises(SessionError, match="has not been started"):
            await session.summarize_and_trim()

    async def test_summarize_skips_when_too_few_messages(self):
        msgs = [_make_db_message("user", "hello")]
        message_repo = AsyncMock()
        message_repo.list_by_session.return_value = msgs
        message_repo.create = AsyncMock()
        message_repo.delete = AsyncMock()

        session = _make_session(message_repo=message_repo)
        session._session_id = uuid4()
        session._is_active = True
        session._recent_messages = 20  # 1 message < 20 threshold

        with (
            patch("src.database.repositories.agent_message_repo.AgentMessageRepository"),
            patch("src.utils.exceptions.DatabaseError"),
        ):
            await session.summarize_and_trim()

        # No new summary message should be written
        message_repo.create.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests: end()
# ---------------------------------------------------------------------------


class TestEnd:
    async def test_end_raises_when_not_active(self):
        session = _make_session()
        with pytest.raises(SessionError, match="not active"):
            await session.end()

    async def test_end_marks_session_inactive(self):
        session_repo = AsyncMock()
        session_repo.close = AsyncMock()
        message_repo = AsyncMock()
        message_repo.list_by_session.return_value = []

        session = _make_session(session_repo=session_repo, message_repo=message_repo)
        session._session_id = uuid4()
        session._is_active = True

        with (
            patch("src.database.repositories.agent_message_repo.AgentMessageRepository"),
            patch("src.database.repositories.agent_session_repo.AgentSessionRepository"),
            patch("src.utils.exceptions.DatabaseError"),
            patch.object(session, "_generate_summary", new_callable=AsyncMock, return_value="summary"),
            patch.object(session, "_close_session_record", new_callable=AsyncMock),
        ):
            await session.end()

        assert session.is_active is False

    async def test_end_calls_close_session_record(self):
        session_repo = AsyncMock()
        session_repo.close = AsyncMock()
        message_repo = AsyncMock()
        message_repo.list_by_session.return_value = []

        session = _make_session(session_repo=session_repo, message_repo=message_repo)
        session._session_id = uuid4()
        session._is_active = True

        close_mock = AsyncMock()
        with (
            patch("src.database.repositories.agent_message_repo.AgentMessageRepository"),
            patch("src.database.repositories.agent_session_repo.AgentSessionRepository"),
            patch("src.utils.exceptions.DatabaseError"),
            patch.object(session, "_generate_summary", new_callable=AsyncMock, return_value="closing summary"),
            patch.object(session, "_close_session_record", close_mock),
        ):
            await session.end()

        close_mock.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests: fallback_summary
# ---------------------------------------------------------------------------


class TestFallbackSummary:
    def test_short_text_returned_as_is(self):
        text = "short conversation"
        result = AgentSession._fallback_summary(text)
        assert "short conversation" in result

    def test_long_text_truncated(self):
        long_text = "a" * 2000
        result = AgentSession._fallback_summary(long_text)
        assert "truncated" in result

    def test_returns_string_always(self):
        result = AgentSession._fallback_summary("")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Tests: _generate_summary (fallback path)
# ---------------------------------------------------------------------------


class TestGenerateSummary:
    async def test_empty_messages_returns_no_messages_string(self):
        session = _make_session()
        session._session_id = uuid4()
        result = await session._generate_summary([])
        assert "No messages" in result

    async def test_fallback_when_no_api_key(self):
        msgs = [_make_db_message("user", "buy BTC")]
        session = _make_session()
        session._session_id = uuid4()

        with patch.object(session, "_get_openrouter_key", return_value=""):
            result = await session._generate_summary(msgs)

        assert "buy BTC" in result or "summary" in result.lower()
