"""Unit tests for SnapshotRepository CRUD and history operations.

Tests that SnapshotRepository correctly delegates to the AsyncSession
and handles filtering, pruning, and error scenarios.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.models import PortfolioSnapshot
from src.database.repositories.snapshot_repo import SnapshotRepository
from src.utils.exceptions import DatabaseError


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock AsyncSession."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def repo(mock_session: AsyncMock) -> SnapshotRepository:
    return SnapshotRepository(mock_session)


def _make_snapshot(
    account_id=None,
    agent_id=None,
    snapshot_type="minute",
    total_equity="10523.45000000",
    available_cash="5000.00000000",
    position_value="5523.45000000",
    unrealized_pnl="523.45000000",
    realized_pnl="0.00000000",
) -> PortfolioSnapshot:
    """Create a PortfolioSnapshot instance for testing."""
    return PortfolioSnapshot(
        account_id=account_id or uuid4(),
        agent_id=agent_id,
        snapshot_type=snapshot_type,
        total_equity=Decimal(total_equity),
        available_cash=Decimal(available_cash),
        position_value=Decimal(position_value),
        unrealized_pnl=Decimal(unrealized_pnl),
        realized_pnl=Decimal(realized_pnl),
    )


class TestCreate:
    async def test_create_snapshot_inserts_and_flushes(
        self, repo: SnapshotRepository, mock_session: AsyncMock
    ) -> None:
        """create inserts snapshot, flushes, and refreshes."""
        snap = _make_snapshot()

        result = await repo.create(snap)

        mock_session.add.assert_called_once_with(snap)
        mock_session.flush.assert_awaited_once()
        mock_session.refresh.assert_awaited_once_with(snap)
        assert result is snap

    async def test_create_integrity_error_raises(self, repo: SnapshotRepository, mock_session: AsyncMock) -> None:
        """create raises DatabaseError on constraint violation."""
        snap = _make_snapshot()
        orig = Exception("FK violation")
        mock_session.flush.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(DatabaseError):
            await repo.create(snap)

        mock_session.rollback.assert_awaited_once()

    async def test_create_db_error_raises(self, repo: SnapshotRepository, mock_session: AsyncMock) -> None:
        """create raises DatabaseError on generic SQLAlchemy error."""
        snap = _make_snapshot()
        mock_session.flush.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.create(snap)


class TestGetHistory:
    async def test_get_history_returns_snapshots(self, repo: SnapshotRepository, mock_session: AsyncMock) -> None:
        """get_history returns snapshots for account, ordered by time."""
        snaps = [_make_snapshot(), _make_snapshot(total_equity="10600.00000000")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = snaps
        mock_session.execute.return_value = mock_result

        result = await repo.get_history(uuid4(), "minute")

        assert len(result) == 2

    async def test_get_history_by_agent(self, repo: SnapshotRepository, mock_session: AsyncMock) -> None:
        """get_history with agent_id scopes to agent."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await repo.get_history(uuid4(), "minute", agent_id=uuid4())

        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "agent_id" in compiled

    async def test_get_history_with_time_bounds(self, repo: SnapshotRepository, mock_session: AsyncMock) -> None:
        """get_history with since/until filters by time range."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        since = datetime(2026, 3, 1, tzinfo=UTC)
        until = datetime(2026, 3, 15, tzinfo=UTC)
        await repo.get_history(uuid4(), "hourly", since=since, until=until)

        stmt = mock_session.execute.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": False}))
        assert "created_at" in compiled

    async def test_get_history_with_limit(self, repo: SnapshotRepository, mock_session: AsyncMock) -> None:
        """get_history with limit parameter works."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        await repo.get_history(uuid4(), "daily", limit=50)

        mock_session.execute.assert_awaited_once()

    async def test_get_history_empty_returns_empty(self, repo: SnapshotRepository, mock_session: AsyncMock) -> None:
        """get_history returns empty list when no snapshots."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.get_history(uuid4(), "minute")

        assert result == []

    async def test_get_history_db_error_raises(self, repo: SnapshotRepository, mock_session: AsyncMock) -> None:
        """get_history raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.get_history(uuid4(), "minute")


class TestGetLatest:
    async def test_get_latest_returns_snapshot(self, repo: SnapshotRepository, mock_session: AsyncMock) -> None:
        """get_latest returns the most recent snapshot."""
        snap = _make_snapshot()
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = snap
        mock_session.execute.return_value = mock_result

        result = await repo.get_latest(uuid4(), "hourly")

        assert result is snap

    async def test_get_latest_no_snapshot_returns_none(self, repo: SnapshotRepository, mock_session: AsyncMock) -> None:
        """get_latest returns None when no snapshot exists."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repo.get_latest(uuid4(), "daily")

        assert result is None


class TestListByAccount:
    async def test_list_by_account_returns_snapshots(self, repo: SnapshotRepository, mock_session: AsyncMock) -> None:
        """list_by_account returns all snapshot types for account."""
        snaps = [_make_snapshot(), _make_snapshot(snapshot_type="hourly")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = snaps
        mock_session.execute.return_value = mock_result

        result = await repo.list_by_account(uuid4())

        assert len(result) == 2


class TestDeleteBefore:
    async def test_delete_old_snapshots(self, repo: SnapshotRepository, mock_session: AsyncMock) -> None:
        """delete_before prunes snapshots older than cutoff."""
        mock_result = MagicMock()
        mock_result.rowcount = 15
        mock_session.execute.return_value = mock_result

        cutoff = datetime(2026, 3, 10, tzinfo=UTC)
        result = await repo.delete_before(uuid4(), "minute", cutoff)

        assert result == 15
        mock_session.execute.assert_awaited_once()

    async def test_delete_before_no_old_data_returns_zero(
        self, repo: SnapshotRepository, mock_session: AsyncMock
    ) -> None:
        """delete_before returns 0 when nothing to prune."""
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result

        cutoff = datetime(2026, 3, 10, tzinfo=UTC)
        result = await repo.delete_before(uuid4(), "minute", cutoff)

        assert result == 0

    async def test_delete_before_db_error_raises(self, repo: SnapshotRepository, mock_session: AsyncMock) -> None:
        """delete_before raises DatabaseError on SQLAlchemy error."""
        mock_session.execute.side_effect = SQLAlchemyError("timeout")

        with pytest.raises(DatabaseError):
            await repo.delete_before(uuid4(), "minute", datetime(2026, 3, 10, tzinfo=UTC))

        mock_session.rollback.assert_awaited_once()
