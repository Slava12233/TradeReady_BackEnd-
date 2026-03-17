"""Unit tests for src/tasks/portfolio_snapshots.py.

Tests the Celery tasks for portfolio snapshot capture and circuit breaker reset.
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


def _mock_redis_client():
    """Build a mock RedisClient."""
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.get_client = MagicMock(return_value=MagicMock())
    return client


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
# Tests for _run_snapshots
# ---------------------------------------------------------------------------


class TestRunSnapshots:
    """Tests for the shared _run_snapshots async body."""

    @pytest.fixture(autouse=True)
    def _patch_deps(self):
        """Patch lazy imports inside _run_snapshots."""
        self.mock_settings = MagicMock()
        self.mock_settings.redis_url = "redis://localhost:6379/0"

        self.mock_redis_client = _mock_redis_client()
        self.mock_snapshot_svc = AsyncMock()
        self.mock_snapshot_svc.capture_minute_snapshot = AsyncMock()
        self.mock_snapshot_svc.capture_hourly_snapshot = AsyncMock()
        self.mock_snapshot_svc.capture_daily_snapshot = AsyncMock()

        self.mock_factory, self.mock_session = _mock_session_factory()
        self.accounts = [_make_account(), _make_account(), _make_account()]

        self.patches = [
            patch("src.config.get_settings", return_value=self.mock_settings),
            patch("src.cache.redis_client.RedisClient", return_value=self.mock_redis_client),
            patch("src.database.session.get_session_factory", return_value=self.mock_factory),
            patch("src.cache.price_cache.PriceCache"),
            patch("src.portfolio.snapshots.SnapshotService", return_value=self.mock_snapshot_svc),
        ]
        for p in self.patches:
            p.start()
        yield
        for p in self.patches:
            p.stop()

    async def test_captures_equity_snapshot_per_account(self):
        """Snapshot row per active account."""
        with patch(
            "src.tasks.portfolio_snapshots._load_active_account_ids",
            new_callable=AsyncMock,
            return_value=[a.id for a in self.accounts],
        ):
            from src.tasks.portfolio_snapshots import _run_snapshots

            result = await _run_snapshots("minute")

        assert result["accounts_processed"] == 3
        assert result["accounts_failed"] == 0
        assert result["snapshot_type"] == "minute"

    async def test_snapshot_includes_position_values(self):
        """Hourly snapshot captures equity + positions."""
        with patch(
            "src.tasks.portfolio_snapshots._load_active_account_ids",
            new_callable=AsyncMock,
            return_value=[self.accounts[0].id],
        ):
            from src.tasks.portfolio_snapshots import _run_snapshots

            result = await _run_snapshots("hourly")

        assert result["snapshot_type"] == "hourly"
        assert result["accounts_processed"] == 1

    async def test_skips_accounts_with_no_activity(self):
        """Inactive accounts not snapshotted — empty list."""
        with patch(
            "src.tasks.portfolio_snapshots._load_active_account_ids",
            new_callable=AsyncMock,
            return_value=[],
        ):
            from src.tasks.portfolio_snapshots import _run_snapshots

            result = await _run_snapshots("minute")

        assert result["accounts_processed"] == 0
        assert result["accounts_failed"] == 0

    async def test_individual_account_failure_isolated(self):
        """One account error does not abort batch."""
        acct_ids = [a.id for a in self.accounts]
        self.mock_snapshot_svc.capture_minute_snapshot = AsyncMock(
            side_effect=[None, RuntimeError("acct2 error"), None]
        )

        with patch(
            "src.tasks.portfolio_snapshots._load_active_account_ids",
            new_callable=AsyncMock,
            return_value=acct_ids,
        ):
            from src.tasks.portfolio_snapshots import _run_snapshots

            result = await _run_snapshots("minute")

        assert result["accounts_processed"] == 2
        assert result["accounts_failed"] == 1

    async def test_returns_snapshot_count(self):
        """Return dict has accounts_processed and snapshot_type."""
        with patch(
            "src.tasks.portfolio_snapshots._load_active_account_ids",
            new_callable=AsyncMock,
            return_value=[self.accounts[0].id],
        ):
            from src.tasks.portfolio_snapshots import _run_snapshots

            result = await _run_snapshots("daily")

        assert result["snapshot_type"] == "daily"
        assert result["accounts_processed"] == 1
        assert "duration_ms" in result


# ---------------------------------------------------------------------------
# Tests for _reset_circuit_breakers
# ---------------------------------------------------------------------------


class TestResetCircuitBreakers:
    """Tests for the circuit breaker reset task."""

    async def test_resets_all_circuit_breakers(self):
        """Calls reset_all on CircuitBreaker and disconnects Redis."""
        mock_redis_client = _mock_redis_client()
        mock_cb = AsyncMock()
        mock_cb.reset_all = AsyncMock()

        with (
            patch("src.config.get_settings", return_value=MagicMock(redis_url="redis://localhost")),
            patch("src.cache.redis_client.RedisClient", return_value=mock_redis_client),
            patch("src.risk.circuit_breaker.CircuitBreaker", return_value=mock_cb),
        ):
            from src.tasks.portfolio_snapshots import _reset_circuit_breakers

            result = await _reset_circuit_breakers()

        mock_cb.reset_all.assert_awaited_once()
        mock_redis_client.disconnect.assert_awaited_once()
        assert "duration_ms" in result

    async def test_redis_disconnected_on_error(self):
        """Redis is disconnected even if reset_all raises."""
        mock_redis_client = _mock_redis_client()
        mock_cb = AsyncMock()
        mock_cb.reset_all = AsyncMock(side_effect=RuntimeError("Redis down"))

        with (
            patch("src.config.get_settings", return_value=MagicMock(redis_url="redis://localhost")),
            patch("src.cache.redis_client.RedisClient", return_value=mock_redis_client),
            patch("src.risk.circuit_breaker.CircuitBreaker", return_value=mock_cb),
        ):
            from src.tasks.portfolio_snapshots import _reset_circuit_breakers

            with pytest.raises(RuntimeError, match="Redis down"):
                await _reset_circuit_breakers()

        mock_redis_client.disconnect.assert_awaited_once()
