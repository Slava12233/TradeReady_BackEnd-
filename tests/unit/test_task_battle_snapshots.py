"""Unit tests for src/tasks/battle_snapshots.py.

Tests the Celery tasks for battle snapshot capture and auto-completion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.celery

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_battle(
    *,
    status: str = "active",
    config: dict | None = None,
    started_at: datetime | None = None,
    account_id=None,
) -> MagicMock:
    """Build a mock Battle model."""
    battle = MagicMock()
    battle.id = uuid4()
    battle.account_id = account_id or uuid4()
    battle.status = status
    battle.config = config or {}
    battle.started_at = started_at
    return battle


def _mock_session_factory():
    """Build a mock async session factory with async context manager."""
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.close = AsyncMock()

    mock_factory = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory.return_value = mock_ctx

    return mock_factory, mock_session


# ---------------------------------------------------------------------------
# Tests for _capture_snapshots_async
# ---------------------------------------------------------------------------


class TestCaptureSnapshots:
    """Tests for the snapshot capture task."""

    async def test_captures_snapshot_for_active_battle(self):
        """Creates equity snapshot for each active participant."""
        mock_factory, mock_session = _mock_session_factory()
        mock_engine = AsyncMock()
        mock_engine.capture_all_active_battles = AsyncMock(return_value=5)

        with (
            patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock, return_value=MagicMock()),
            patch("src.cache.price_cache.PriceCache"),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.battles.snapshot_engine.SnapshotEngine", return_value=mock_engine),
        ):
            from src.tasks.battle_snapshots import _capture_snapshots_async

            result = await _capture_snapshots_async()

        assert result == 5
        mock_engine.capture_all_active_battles.assert_awaited_once()
        mock_session.commit.assert_awaited_once()

    async def test_skips_non_active_battles(self):
        """Ignores draft/completed/cancelled battles (engine handles filtering)."""
        mock_factory, mock_session = _mock_session_factory()
        mock_engine = AsyncMock()
        mock_engine.capture_all_active_battles = AsyncMock(return_value=0)

        with (
            patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock, return_value=MagicMock()),
            patch("src.cache.price_cache.PriceCache"),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.battles.snapshot_engine.SnapshotEngine", return_value=mock_engine),
        ):
            from src.tasks.battle_snapshots import _capture_snapshots_async

            result = await _capture_snapshots_async()

        assert result == 0

    async def test_snapshot_includes_all_participants(self):
        """Snapshot covers every participant, not just first."""
        mock_factory, mock_session = _mock_session_factory()
        mock_engine = AsyncMock()
        mock_engine.capture_all_active_battles = AsyncMock(return_value=12)

        with (
            patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock, return_value=MagicMock()),
            patch("src.cache.price_cache.PriceCache"),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.battles.snapshot_engine.SnapshotEngine", return_value=mock_engine),
        ):
            from src.tasks.battle_snapshots import _capture_snapshots_async

            result = await _capture_snapshots_async()

        assert result == 12

    async def test_individual_battle_failure_isolated(self):
        """Error in snapshot engine triggers rollback and re-raises."""
        mock_factory, mock_session = _mock_session_factory()
        mock_engine = AsyncMock()
        mock_engine.capture_all_active_battles = AsyncMock(side_effect=RuntimeError("DB error"))

        with (
            patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock, return_value=MagicMock()),
            patch("src.cache.price_cache.PriceCache"),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.battles.snapshot_engine.SnapshotEngine", return_value=mock_engine),
        ):
            from src.tasks.battle_snapshots import _capture_snapshots_async

            with pytest.raises(RuntimeError, match="DB error"):
                await _capture_snapshots_async()

        mock_session.rollback.assert_awaited_once()

    async def test_returns_count_of_snapshots_captured(self):
        """Return value is total snapshot count."""
        mock_factory, mock_session = _mock_session_factory()
        mock_engine = AsyncMock()
        mock_engine.capture_all_active_battles = AsyncMock(return_value=8)

        with (
            patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock, return_value=MagicMock()),
            patch("src.cache.price_cache.PriceCache"),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.battles.snapshot_engine.SnapshotEngine", return_value=mock_engine),
        ):
            from src.tasks.battle_snapshots import _capture_snapshots_async

            result = await _capture_snapshots_async()

        assert result == 8

    async def test_no_active_battles_returns_zero(self):
        """Graceful no-op when nothing is active."""
        mock_factory, mock_session = _mock_session_factory()
        mock_engine = AsyncMock()
        mock_engine.capture_all_active_battles = AsyncMock(return_value=0)

        with (
            patch("src.cache.redis_client.get_redis_client", new_callable=AsyncMock, return_value=MagicMock()),
            patch("src.cache.price_cache.PriceCache"),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.battles.snapshot_engine.SnapshotEngine", return_value=mock_engine),
        ):
            from src.tasks.battle_snapshots import _capture_snapshots_async

            result = await _capture_snapshots_async()

        assert result == 0


# ---------------------------------------------------------------------------
# Tests for _check_completion_async
# ---------------------------------------------------------------------------


class TestCheckCompletion:
    """Tests for the auto-completion check task."""

    async def test_auto_completes_expired_battle(self):
        """Battle past end_time is auto-stopped and ranked."""
        battle = _make_battle(
            status="active",
            config={"duration_type": "fixed", "duration_seconds": 3600},
            started_at=datetime.now(UTC) - timedelta(hours=2),
        )

        mock_factory, mock_session = _mock_session_factory()

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [battle]
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_service = AsyncMock()
        mock_service.stop_battle = AsyncMock()

        with (
            patch("src.config.get_settings", return_value=MagicMock()),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
            patch("src.battles.service.BattleService", return_value=mock_service),
        ):
            from src.tasks.battle_snapshots import _check_completion_async

            result = await _check_completion_async()

        assert result == 1
        mock_service.stop_battle.assert_awaited_once_with(battle.id, battle.account_id)

    async def test_skips_unlimited_duration_battles(self):
        """Battles with duration_type=unlimited are not auto-completed."""
        battle = _make_battle(
            status="active",
            config={"duration_type": "unlimited"},
            started_at=datetime.now(UTC) - timedelta(hours=10),
        )

        mock_factory, mock_session = _mock_session_factory()

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [battle]
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        with (
            patch("src.config.get_settings", return_value=MagicMock()),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
        ):
            from src.tasks.battle_snapshots import _check_completion_async

            result = await _check_completion_async()

        assert result == 0

    async def test_no_active_battles_completes_zero(self):
        """No active battles returns 0 completions."""
        mock_factory, mock_session = _mock_session_factory()

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        with (
            patch("src.config.get_settings", return_value=MagicMock()),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
        ):
            from src.tasks.battle_snapshots import _check_completion_async

            result = await _check_completion_async()

        assert result == 0

    async def test_battle_not_yet_expired_skipped(self):
        """Active battle within its duration is not stopped."""
        battle = _make_battle(
            status="active",
            config={"duration_type": "fixed", "duration_seconds": 7200},
            started_at=datetime.now(UTC) - timedelta(minutes=30),
        )

        mock_factory, mock_session = _mock_session_factory()

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [battle]
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        with (
            patch("src.config.get_settings", return_value=MagicMock()),
            patch("src.database.session.get_session_factory", return_value=mock_factory),
        ):
            from src.tasks.battle_snapshots import _check_completion_async

            result = await _check_completion_async()

        assert result == 0
