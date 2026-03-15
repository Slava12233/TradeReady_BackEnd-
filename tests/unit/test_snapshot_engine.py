"""Unit tests for SnapshotEngine."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.battles.snapshot_engine import SnapshotEngine


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def engine(mock_session):
    eng = SnapshotEngine(mock_session)
    eng._battle_repo = AsyncMock()
    return eng


class TestCaptureSnapshots:
    async def test_captures_for_active_participants(self, engine):
        p1 = MagicMock()
        p1.agent_id = uuid4()
        p1.status = "active"

        p2 = MagicMock()
        p2.agent_id = uuid4()
        p2.status = "paused"

        engine._battle_repo.get_participants.return_value = [p1, p2]
        engine._battle_repo.insert_snapshots_bulk = AsyncMock()

        # Mock the private methods
        engine._get_agent_equity = AsyncMock(return_value=Decimal("10500"))
        engine._get_unrealized_pnl = AsyncMock(return_value=Decimal("200"))
        engine._get_realized_pnl = AsyncMock(return_value=Decimal("300"))
        engine._get_trade_count = AsyncMock(return_value=5)
        engine._get_open_position_count = AsyncMock(return_value=2)

        count = await engine.capture_battle_snapshots(uuid4())

        # Only active participant should be captured
        assert count == 1
        engine._battle_repo.insert_snapshots_bulk.assert_called_once()
        snapshots = engine._battle_repo.insert_snapshots_bulk.call_args[0][0]
        assert len(snapshots) == 1

    async def test_no_snapshots_for_no_active_participants(self, engine):
        p1 = MagicMock()
        p1.status = "paused"

        engine._battle_repo.get_participants.return_value = [p1]

        count = await engine.capture_battle_snapshots(uuid4())
        assert count == 0
        engine._battle_repo.insert_snapshots_bulk.assert_not_called()

    async def test_capture_all_active_battles(self, engine, mock_session):
        battle1 = MagicMock()
        battle1.id = uuid4()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [battle1]
        mock_session.execute.return_value = mock_result

        engine.capture_battle_snapshots = AsyncMock(return_value=3)

        total = await engine.capture_all_active_battles()
        assert total == 3
