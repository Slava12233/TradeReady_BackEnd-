"""Unit tests for database session management.

Tests that the session module correctly creates engines, manages pools,
and handles initialization/cleanup lifecycle.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import src.database.session as session_mod


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset module-level singletons before and after each test."""
    original_engine = session_mod._engine
    original_factory = session_mod._session_factory
    original_pool = session_mod._asyncpg_pool
    session_mod._engine = None
    session_mod._session_factory = None
    session_mod._asyncpg_pool = None
    yield
    session_mod._engine = original_engine
    session_mod._session_factory = original_factory
    session_mod._asyncpg_pool = original_pool


class TestBuildEngine:
    @patch("src.database.session.get_settings")
    @patch("src.database.session.create_async_engine")
    def test_creates_engine_with_database_url(self, mock_create, mock_settings) -> None:
        """_build_engine creates engine with DATABASE_URL from settings."""
        settings = MagicMock()
        settings.database_url = "postgresql+asyncpg://test:test@localhost:5432/test"
        mock_settings.return_value = settings
        mock_engine = MagicMock()
        mock_create.return_value = mock_engine

        result = session_mod._build_engine()

        assert result is mock_engine
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs[0][0] == settings.database_url

    @patch("src.database.session.get_settings")
    @patch("src.database.session.create_async_engine")
    def test_engine_pool_settings(self, mock_create, mock_settings) -> None:
        """_build_engine passes pool_size and max_overflow from code."""
        settings = MagicMock()
        settings.database_url = "postgresql+asyncpg://test:test@localhost/test"
        mock_settings.return_value = settings
        mock_create.return_value = MagicMock()

        session_mod._build_engine()

        call_kwargs = mock_create.call_args
        assert call_kwargs[1]["pool_size"] == 10
        assert call_kwargs[1]["max_overflow"] == 20
        assert call_kwargs[1]["pool_pre_ping"] is True


class TestGetEngine:
    @patch("src.database.session._build_engine")
    def test_get_engine_creates_on_first_call(self, mock_build) -> None:
        """get_engine creates engine on first call."""
        mock_engine = MagicMock()
        mock_build.return_value = mock_engine

        result = session_mod.get_engine()

        assert result is mock_engine
        mock_build.assert_called_once()

    @patch("src.database.session._build_engine")
    def test_get_engine_returns_cached(self, mock_build) -> None:
        """get_engine returns cached engine on subsequent calls."""
        mock_engine = MagicMock()
        mock_build.return_value = mock_engine

        result1 = session_mod.get_engine()
        result2 = session_mod.get_engine()

        assert result1 is result2
        mock_build.assert_called_once()


class TestGetSessionFactory:
    @patch("src.database.session.get_engine")
    def test_creates_factory_on_first_call(self, mock_get_engine) -> None:
        """get_session_factory creates factory with correct config."""
        mock_get_engine.return_value = MagicMock()

        factory = session_mod.get_session_factory()

        assert factory is not None

    @patch("src.database.session.get_engine")
    def test_returns_cached_factory(self, mock_get_engine) -> None:
        """get_session_factory returns cached factory."""
        mock_get_engine.return_value = MagicMock()

        f1 = session_mod.get_session_factory()
        f2 = session_mod.get_session_factory()

        assert f1 is f2


class TestGetAsyncpgPool:
    async def test_raises_if_not_initialized(self) -> None:
        """get_asyncpg_pool raises RuntimeError if pool not init'd."""
        with pytest.raises(RuntimeError, match="not initialised"):
            await session_mod.get_asyncpg_pool()

    async def test_returns_pool_after_init(self) -> None:
        """get_asyncpg_pool returns pool after init_db sets it."""
        mock_pool = MagicMock()
        session_mod._asyncpg_pool = mock_pool

        result = await session_mod.get_asyncpg_pool()

        assert result is mock_pool


class TestCloseDb:
    async def test_closes_pool_and_engine(self) -> None:
        """close_db closes asyncpg pool and disposes engine."""
        mock_pool = AsyncMock()
        mock_engine = AsyncMock()
        session_mod._asyncpg_pool = mock_pool
        session_mod._engine = mock_engine
        session_mod._session_factory = MagicMock()

        await session_mod.close_db()

        mock_pool.close.assert_awaited_once()
        mock_engine.dispose.assert_awaited_once()
        assert session_mod._asyncpg_pool is None
        assert session_mod._engine is None
        assert session_mod._session_factory is None

    async def test_close_db_no_op_when_not_initialized(self) -> None:
        """close_db is a no-op when nothing is initialized."""
        await session_mod.close_db()

        assert session_mod._engine is None
        assert session_mod._asyncpg_pool is None
