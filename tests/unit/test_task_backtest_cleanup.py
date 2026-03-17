"""Unit tests for src/tasks/backtest_cleanup.py.

Tests the Celery tasks for stale backtest cancellation and old detail data cleanup.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.celery

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_session_factory():
    """Build a mock async session factory."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_factory = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory.return_value = mock_ctx

    return mock_factory, mock_session


# ---------------------------------------------------------------------------
# Tests for _cancel_stale_backtests_async
# ---------------------------------------------------------------------------


class TestCancelStaleBacktests:
    """Tests for the stale backtest cancellation task."""

    async def test_cancels_stale_running_sessions(self):
        """Sessions running > threshold are marked as cancelled."""
        mock_factory, mock_session = _mock_session_factory()

        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.database.session.get_session_factory", return_value=mock_factory):
            from src.tasks.backtest_cleanup import _cancel_stale_backtests_async

            result = await _cancel_stale_backtests_async()

        assert result == {"cancelled": 3}
        mock_session.commit.assert_awaited_once()

    async def test_preserves_recent_sessions(self):
        """Sessions within retention window untouched — rowcount 0."""
        mock_factory, mock_session = _mock_session_factory()

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.database.session.get_session_factory", return_value=mock_factory):
            from src.tasks.backtest_cleanup import _cancel_stale_backtests_async

            result = await _cancel_stale_backtests_async()

        assert result == {"cancelled": 0}

    async def test_empty_database_no_op(self):
        """No sessions = no errors, returns zeros."""
        mock_factory, mock_session = _mock_session_factory()

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.database.session.get_session_factory", return_value=mock_factory):
            from src.tasks.backtest_cleanup import _cancel_stale_backtests_async

            result = await _cancel_stale_backtests_async()

        assert result == {"cancelled": 0}

    async def test_returns_cancelled_count(self):
        """Return dict has cancelled key with count."""
        mock_factory, mock_session = _mock_session_factory()

        mock_result = MagicMock()
        mock_result.rowcount = 7
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.database.session.get_session_factory", return_value=mock_factory):
            from src.tasks.backtest_cleanup import _cancel_stale_backtests_async

            result = await _cancel_stale_backtests_async()

        assert "cancelled" in result
        assert result["cancelled"] == 7

    async def test_handles_none_rowcount(self):
        """rowcount=None is treated as 0."""
        mock_factory, mock_session = _mock_session_factory()

        mock_result = MagicMock()
        mock_result.rowcount = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("src.database.session.get_session_factory", return_value=mock_factory):
            from src.tasks.backtest_cleanup import _cancel_stale_backtests_async

            result = await _cancel_stale_backtests_async()

        assert result == {"cancelled": 0}


# ---------------------------------------------------------------------------
# Tests for _cleanup_detail_async
# ---------------------------------------------------------------------------


class TestCleanupDetailData:
    """Tests for the detail data cleanup task."""

    async def test_deletes_old_detail_data(self):
        """Snapshots/trades older than retention deleted."""
        mock_factory, mock_session = _mock_session_factory()

        mock_repo = AsyncMock()
        mock_repo.delete_old_detail_data = AsyncMock(return_value=150)

        with (
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch(
                "src.database.repositories.backtest_repo.BacktestRepository",
                return_value=mock_repo,
            ),
        ):
            from src.tasks.backtest_cleanup import _cleanup_detail_async

            result = await _cleanup_detail_async()

        assert result == {"deleted_rows": 150}
        mock_repo.delete_old_detail_data.assert_awaited_once_with(days=90)
        mock_session.commit.assert_awaited_once()

    async def test_preserves_completed_session_summary(self):
        """Session row kept even when detail data pruned — repo returns 0."""
        mock_factory, mock_session = _mock_session_factory()

        mock_repo = AsyncMock()
        mock_repo.delete_old_detail_data = AsyncMock(return_value=0)

        with (
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch(
                "src.database.repositories.backtest_repo.BacktestRepository",
                return_value=mock_repo,
            ),
        ):
            from src.tasks.backtest_cleanup import _cleanup_detail_async

            result = await _cleanup_detail_async()

        assert result == {"deleted_rows": 0}

    async def test_returns_cleanup_counts(self):
        """Return dict has deleted_rows key."""
        mock_factory, mock_session = _mock_session_factory()

        mock_repo = AsyncMock()
        mock_repo.delete_old_detail_data = AsyncMock(return_value=42)

        with (
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch(
                "src.database.repositories.backtest_repo.BacktestRepository",
                return_value=mock_repo,
            ),
        ):
            from src.tasks.backtest_cleanup import _cleanup_detail_async

            result = await _cleanup_detail_async()

        assert "deleted_rows" in result
        assert result["deleted_rows"] == 42

    async def test_empty_database_no_op(self):
        """No old data to delete returns 0."""
        mock_factory, mock_session = _mock_session_factory()

        mock_repo = AsyncMock()
        mock_repo.delete_old_detail_data = AsyncMock(return_value=0)

        with (
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch(
                "src.database.repositories.backtest_repo.BacktestRepository",
                return_value=mock_repo,
            ),
        ):
            from src.tasks.backtest_cleanup import _cleanup_detail_async

            result = await _cleanup_detail_async()

        assert result == {"deleted_rows": 0}
