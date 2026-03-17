"""Unit tests for src/tasks/cleanup.py.

Tests the Celery cleanup task that expires stale orders, prunes old snapshots,
and archives old audit log entries.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.celery

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_account(account_id=None):
    """Build a mock Account with an ID."""
    acct = MagicMock()
    acct.id = account_id or uuid4()
    return acct


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
# Tests for _expire_stale_orders
# ---------------------------------------------------------------------------


class TestExpireStaleOrders:
    """Tests for Phase 1 — stale order expiry."""

    async def test_cancels_expired_pending_orders(self):
        """Orders past expiry window are set to expired."""
        mock_factory, mock_session = _mock_session_factory()

        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_session.execute = AsyncMock(return_value=mock_result)

        from src.tasks.cleanup import _expire_stale_orders

        result = await _expire_stale_orders(mock_factory)

        assert result == 5
        mock_session.commit.assert_awaited_once()

    async def test_no_expired_orders_returns_zero(self):
        """No stale orders returns 0."""
        mock_factory, mock_session = _mock_session_factory()

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute = AsyncMock(return_value=mock_result)

        from src.tasks.cleanup import _expire_stale_orders

        result = await _expire_stale_orders(mock_factory)

        assert result == 0


# ---------------------------------------------------------------------------
# Tests for _prune_minute_snapshots
# ---------------------------------------------------------------------------


class TestPruneMinuteSnapshots:
    """Tests for Phase 2 — snapshot pruning."""

    async def test_prunes_old_snapshots(self):
        """Snapshots older than retention deleted per account."""
        accounts = [_make_account(), _make_account()]

        mock_repo = AsyncMock()
        mock_repo.delete_before = AsyncMock(return_value=10)

        def _factory():
            mock_session = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            return mock_ctx

        mock_factory = MagicMock(side_effect=_factory)

        with (
            patch(
                "src.tasks.cleanup._load_all_account_ids",
                new_callable=AsyncMock,
                return_value=[a.id for a in accounts],
            ),
            patch(
                "src.database.repositories.snapshot_repo.SnapshotRepository",
                return_value=mock_repo,
            ),
        ):
            from src.tasks.cleanup import _prune_minute_snapshots

            total, processed, failed = await _prune_minute_snapshots(mock_factory)

        assert total == 20  # 10 per account x 2 accounts
        assert processed == 2
        assert failed == 0

    async def test_prunes_old_portfolio_snapshots(self):
        """Snapshots older than retention window are deleted."""
        accounts = [_make_account()]

        mock_repo = AsyncMock()
        mock_repo.delete_before = AsyncMock(return_value=50)

        def _factory():
            mock_session = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_ctx = MagicMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            return mock_ctx

        mock_factory = MagicMock(side_effect=_factory)

        with (
            patch(
                "src.tasks.cleanup._load_all_account_ids",
                new_callable=AsyncMock,
                return_value=[accounts[0].id],
            ),
            patch(
                "src.database.repositories.snapshot_repo.SnapshotRepository",
                return_value=mock_repo,
            ),
        ):
            from src.tasks.cleanup import _prune_minute_snapshots

            total, processed, failed = await _prune_minute_snapshots(mock_factory)

        assert total == 50
        assert processed == 1

    async def test_no_accounts_returns_zeros(self):
        """No accounts = no deletions."""
        mock_factory, _ = _mock_session_factory()

        with patch(
            "src.tasks.cleanup._load_all_account_ids",
            new_callable=AsyncMock,
            return_value=[],
        ):
            from src.tasks.cleanup import _prune_minute_snapshots

            total, processed, failed = await _prune_minute_snapshots(mock_factory)

        assert total == 0
        assert processed == 0
        assert failed == 0

    async def test_individual_account_failure_isolated(self):
        """One account error does not skip others."""
        accounts = [_make_account(), _make_account(), _make_account()]
        call_count = 0

        mock_repo = AsyncMock()
        mock_repo.delete_before = AsyncMock(return_value=5)

        def _factory():
            nonlocal call_count
            call_count += 1
            mock_session = AsyncMock()
            mock_session.commit = AsyncMock()
            mock_ctx = MagicMock()

            if call_count == 2:
                mock_ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("DB error"))
            else:
                mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)

            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            return mock_ctx

        mock_factory = MagicMock(side_effect=_factory)

        with (
            patch(
                "src.tasks.cleanup._load_all_account_ids",
                new_callable=AsyncMock,
                return_value=[a.id for a in accounts],
            ),
            patch(
                "src.database.repositories.snapshot_repo.SnapshotRepository",
                return_value=mock_repo,
            ),
        ):
            from src.tasks.cleanup import _prune_minute_snapshots

            total, processed, failed = await _prune_minute_snapshots(mock_factory)

        assert processed == 2
        assert failed == 1


# ---------------------------------------------------------------------------
# Tests for _archive_audit_log
# ---------------------------------------------------------------------------


class TestArchiveAuditLog:
    """Tests for Phase 3 — audit log archival."""

    async def test_deletes_old_audit_entries(self):
        """Audit rows older than retention are deleted."""
        mock_factory, mock_session = _mock_session_factory()

        mock_result = MagicMock()
        mock_result.rowcount = 1000
        mock_session.execute = AsyncMock(return_value=mock_result)

        from src.tasks.cleanup import _archive_audit_log

        result = await _archive_audit_log(mock_factory)

        assert result == 1000
        mock_session.commit.assert_awaited_once()

    async def test_no_old_entries_returns_zero(self):
        """No old entries = 0 deleted."""
        mock_factory, mock_session = _mock_session_factory()

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute = AsyncMock(return_value=mock_result)

        from src.tasks.cleanup import _archive_audit_log

        result = await _archive_audit_log(mock_factory)

        assert result == 0


# ---------------------------------------------------------------------------
# Tests for _run_cleanup (full pipeline)
# ---------------------------------------------------------------------------


class TestRunCleanup:
    """Tests for the full cleanup pipeline."""

    async def test_returns_cleanup_counts(self):
        """Return dict has per-category counts."""
        with (
            patch("src.config.get_settings", return_value=MagicMock()),
            patch("src.database.session.get_session_factory", return_value=MagicMock()),
            patch("src.tasks.cleanup._expire_stale_orders", new_callable=AsyncMock, return_value=3),
            patch(
                "src.tasks.cleanup._prune_minute_snapshots",
                new_callable=AsyncMock,
                return_value=(100, 5, 0),
            ),
            patch("src.tasks.cleanup._archive_audit_log", new_callable=AsyncMock, return_value=200),
        ):
            from src.tasks.cleanup import _run_cleanup

            result = await _run_cleanup()

        assert result["orders_expired"] == 3
        assert result["snapshots_deleted"] == 100
        assert result["audit_rows_deleted"] == 200
        assert result["accounts_processed"] == 5
        assert result["accounts_failed"] == 0
        assert result["phases_failed"] == []
        assert "duration_ms" in result

    async def test_no_expired_data_returns_zeros(self):
        """Graceful no-op when nothing to clean."""
        with (
            patch("src.config.get_settings", return_value=MagicMock()),
            patch("src.database.session.get_session_factory", return_value=MagicMock()),
            patch("src.tasks.cleanup._expire_stale_orders", new_callable=AsyncMock, return_value=0),
            patch(
                "src.tasks.cleanup._prune_minute_snapshots",
                new_callable=AsyncMock,
                return_value=(0, 0, 0),
            ),
            patch("src.tasks.cleanup._archive_audit_log", new_callable=AsyncMock, return_value=0),
        ):
            from src.tasks.cleanup import _run_cleanup

            result = await _run_cleanup()

        assert result["orders_expired"] == 0
        assert result["snapshots_deleted"] == 0
        assert result["audit_rows_deleted"] == 0
        assert result["phases_failed"] == []

    async def test_phase_failure_does_not_abort_others(self):
        """One phase error does not skip remaining phases."""
        with (
            patch("src.config.get_settings", return_value=MagicMock()),
            patch("src.database.session.get_session_factory", return_value=MagicMock()),
            patch(
                "src.tasks.cleanup._expire_stale_orders",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DB"),
            ),
            patch(
                "src.tasks.cleanup._prune_minute_snapshots",
                new_callable=AsyncMock,
                return_value=(50, 3, 0),
            ),
            patch("src.tasks.cleanup._archive_audit_log", new_callable=AsyncMock, return_value=100),
        ):
            from src.tasks.cleanup import _run_cleanup

            result = await _run_cleanup()

        assert "expire_orders" in result["phases_failed"]
        assert result["snapshots_deleted"] == 50
        assert result["audit_rows_deleted"] == 100
