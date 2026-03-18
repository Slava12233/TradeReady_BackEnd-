"""Unit tests for BattleRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.database.models import Battle, BattleParticipant, BattleSnapshot
from src.database.repositories.battle_repo import BattleNotFoundError, BattleRepository
from src.utils.exceptions import DatabaseError


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.delete = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def repo(mock_session):
    return BattleRepository(mock_session)


@pytest.fixture
def sample_battle():
    battle = MagicMock(spec=Battle)
    battle.id = uuid4()
    battle.account_id = uuid4()
    battle.name = "Test Battle"
    battle.status = "draft"
    battle.config = {}
    battle.preset = None
    battle.ranking_metric = "roi_pct"
    battle.started_at = None
    battle.ended_at = None
    battle.created_at = datetime.now(UTC)
    return battle


class TestBattleCRUD:
    async def test_create_battle(self, repo, mock_session, sample_battle):
        mock_session.flush.return_value = None
        mock_session.refresh.return_value = None

        result = await repo.create_battle(sample_battle)
        mock_session.add.assert_called_once_with(sample_battle)
        assert result == sample_battle

    async def test_create_battle_db_error(self, repo, mock_session, sample_battle):
        mock_session.flush.side_effect = SQLAlchemyError("db error")
        with pytest.raises(DatabaseError, match="Failed to create battle"):
            await repo.create_battle(sample_battle)

    async def test_get_battle_found(self, repo, mock_session, sample_battle):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = sample_battle
        mock_session.execute.return_value = mock_result

        result = await repo.get_battle(sample_battle.id)
        assert result == sample_battle

    async def test_get_battle_not_found(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(BattleNotFoundError):
            await repo.get_battle(uuid4())

    async def test_list_battles(self, repo, mock_session, sample_battle):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_battle]
        mock_session.execute.return_value = mock_result

        result = await repo.list_battles(sample_battle.account_id)
        assert len(result) == 1

    async def test_list_battles_with_status_filter(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.list_battles(uuid4(), status="active")
        assert len(result) == 0

    async def test_update_status(self, repo, mock_session, sample_battle):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = sample_battle
        mock_session.execute.return_value = mock_result

        result = await repo.update_status(sample_battle.id, "pending")
        assert result == sample_battle

    async def test_delete_battle(self, repo, mock_session, sample_battle):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = sample_battle
        mock_session.execute.return_value = mock_result

        await repo.delete_battle(sample_battle.id)
        mock_session.delete.assert_called_once_with(sample_battle)


class TestParticipantOperations:
    async def test_add_participant(self, repo, mock_session):
        participant = MagicMock(spec=BattleParticipant)
        participant.battle_id = uuid4()
        participant.agent_id = uuid4()
        mock_session.flush.return_value = None
        mock_session.refresh.return_value = None

        result = await repo.add_participant(participant)
        mock_session.add.assert_called_once_with(participant)
        assert result == participant

    async def test_add_duplicate_participant(self, repo, mock_session):
        participant = MagicMock(spec=BattleParticipant)
        orig = MagicMock()
        orig.__str__ = lambda s: "uq_bp_battle_agent"
        mock_session.flush.side_effect = IntegrityError("", {}, orig)

        with pytest.raises(DatabaseError, match="already a participant"):
            await repo.add_participant(participant)

    async def test_remove_participant(self, repo, mock_session):
        participant = MagicMock(spec=BattleParticipant)
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = participant
        mock_session.execute.return_value = mock_result

        await repo.remove_participant(uuid4(), uuid4())
        mock_session.delete.assert_called_once_with(participant)

    async def test_remove_participant_not_found(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(BattleNotFoundError):
            await repo.remove_participant(uuid4(), uuid4())

    async def test_get_participants(self, repo, mock_session):
        p1 = MagicMock(spec=BattleParticipant)
        p2 = MagicMock(spec=BattleParticipant)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [p1, p2]
        mock_session.execute.return_value = mock_result

        result = await repo.get_participants(uuid4())
        assert len(result) == 2


class TestSnapshotOperations:
    async def test_insert_snapshot(self, repo, mock_session):
        snapshot = MagicMock(spec=BattleSnapshot)
        mock_session.flush.return_value = None

        result = await repo.insert_snapshot(snapshot)
        mock_session.add.assert_called_once_with(snapshot)
        assert result == snapshot

    async def test_insert_snapshots_bulk(self, repo, mock_session):
        snapshots = [MagicMock(spec=BattleSnapshot) for _ in range(3)]
        mock_session.flush.return_value = None

        await repo.insert_snapshots_bulk(snapshots)
        mock_session.add_all.assert_called_once_with(snapshots)

    async def test_get_snapshots(self, repo, mock_session):
        s1 = MagicMock(spec=BattleSnapshot)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [s1]
        mock_session.execute.return_value = mock_result

        result = await repo.get_snapshots(uuid4())
        assert len(result) == 1

    async def test_count_snapshots(self, repo, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 42
        mock_session.execute.return_value = mock_result

        count = await repo.count_snapshots(uuid4())
        assert count == 42
