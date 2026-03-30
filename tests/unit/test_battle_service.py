"""Unit tests for BattleService — lifecycle state machine, pause/resume, start/stop."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.battles.service import BattleInvalidStateError, BattleService


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.rollback = AsyncMock()
    session.commit = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.default_starting_balance = Decimal("10000")
    return settings


@pytest.fixture
def service(mock_session, mock_settings):
    svc = BattleService(mock_session, mock_settings)
    svc._battle_repo = AsyncMock()
    svc._agent_repo = AsyncMock()
    svc._trade_repo = AsyncMock()
    svc._wallet_manager = AsyncMock()
    return svc


@pytest.fixture
def sample_battle():
    battle = MagicMock()
    battle.id = uuid4()
    battle.account_id = uuid4()
    battle.name = "Test Battle"
    battle.status = "draft"
    battle.config = {"wallet_mode": "fresh", "starting_balance": "10000"}
    battle.ranking_metric = "roi_pct"
    battle.started_at = None
    battle.ended_at = None
    battle.created_at = datetime.now(UTC)
    return battle


class TestCreateBattle:
    async def test_create_with_preset(self, service):
        service._battle_repo.create_battle.return_value = MagicMock()
        await service.create_battle(uuid4(), "Sprint Battle", preset="quick_1h")
        service._battle_repo.create_battle.assert_called_once()

    async def test_create_with_custom_config(self, service):
        config = {"duration_type": "fixed", "duration_seconds": 7200}
        service._battle_repo.create_battle.return_value = MagicMock()
        await service.create_battle(uuid4(), "Custom Battle", config=config)
        service._battle_repo.create_battle.assert_called_once()


class TestUpdateBattle:
    async def test_update_draft_battle(self, service, sample_battle):
        sample_battle.status = "draft"
        service._battle_repo.get_battle.return_value = sample_battle
        service._battle_repo.update_battle.return_value = sample_battle

        await service.update_battle(sample_battle.id, sample_battle.account_id, name="New Name")
        service._battle_repo.update_battle.assert_called_once()

    async def test_update_active_battle_fails(self, service, sample_battle):
        sample_battle.status = "active"
        service._battle_repo.get_battle.return_value = sample_battle

        with pytest.raises(BattleInvalidStateError, match="draft"):
            await service.update_battle(sample_battle.id, sample_battle.account_id, name="X")

    async def test_update_wrong_account_fails(self, service, sample_battle):
        service._battle_repo.get_battle.return_value = sample_battle

        from src.utils.exceptions import PermissionDeniedError

        with pytest.raises(PermissionDeniedError):
            await service.update_battle(sample_battle.id, uuid4(), name="X")


class TestParticipantManagement:
    async def test_add_participant(self, service, sample_battle):
        sample_battle.status = "draft"
        service._battle_repo.get_battle.return_value = sample_battle
        agent = MagicMock()
        agent.account_id = sample_battle.account_id
        service._agent_repo.get_by_id.return_value = agent
        service._battle_repo.add_participant.return_value = MagicMock()

        await service.add_participant(sample_battle.id, uuid4(), sample_battle.account_id)
        service._battle_repo.add_participant.assert_called_once()

    async def test_add_participant_active_battle_fails(self, service, sample_battle):
        sample_battle.status = "active"
        service._battle_repo.get_battle.return_value = sample_battle

        with pytest.raises(BattleInvalidStateError):
            await service.add_participant(sample_battle.id, uuid4(), sample_battle.account_id)

    async def test_remove_participant(self, service, sample_battle):
        sample_battle.status = "draft"
        service._battle_repo.get_battle.return_value = sample_battle

        await service.remove_participant(sample_battle.id, uuid4(), sample_battle.account_id)
        service._battle_repo.remove_participant.assert_called_once()


class TestStartBattle:
    async def test_start_with_enough_participants(self, service, sample_battle):
        sample_battle.status = "draft"
        service._battle_repo.get_battle.return_value = sample_battle

        p1 = MagicMock()
        p1.agent_id = uuid4()
        p2 = MagicMock()
        p2.agent_id = uuid4()
        service._battle_repo.get_participants.return_value = [p1, p2]

        agent1 = MagicMock()
        agent1.account_id = sample_battle.account_id
        agent2 = MagicMock()
        agent2.account_id = sample_battle.account_id
        service._agent_repo.get_by_id.side_effect = [agent1, agent2]
        service._wallet_manager.snapshot_wallet.return_value = Decimal("10000")
        service._battle_repo.update_participant.return_value = MagicMock()
        service._battle_repo.update_status.return_value = sample_battle

        await service.start_battle(sample_battle.id, sample_battle.account_id)
        service._battle_repo.update_status.assert_called_once()

    async def test_start_with_one_participant_fails(self, service, sample_battle):
        sample_battle.status = "draft"
        service._battle_repo.get_battle.return_value = sample_battle
        service._battle_repo.get_participants.return_value = [MagicMock()]

        with pytest.raises(BattleInvalidStateError, match="at least 2"):
            await service.start_battle(sample_battle.id, sample_battle.account_id)


class TestPauseResume:
    async def test_pause_agent(self, service, sample_battle):
        sample_battle.status = "active"
        service._battle_repo.get_battle.return_value = sample_battle

        participant = MagicMock()
        participant.status = "active"
        service._battle_repo.get_participant.return_value = participant
        service._battle_repo.update_participant.return_value = participant

        await service.pause_agent(sample_battle.id, uuid4(), sample_battle.account_id)
        service._battle_repo.update_participant.assert_called_once()

    async def test_pause_in_draft_fails(self, service, sample_battle):
        sample_battle.status = "draft"
        service._battle_repo.get_battle.return_value = sample_battle

        with pytest.raises(BattleInvalidStateError, match="active"):
            await service.pause_agent(sample_battle.id, uuid4(), sample_battle.account_id)

    async def test_resume_paused_agent(self, service, sample_battle):
        sample_battle.status = "active"
        service._battle_repo.get_battle.return_value = sample_battle

        participant = MagicMock()
        participant.status = "paused"
        service._battle_repo.get_participant.return_value = participant
        service._battle_repo.update_participant.return_value = participant

        await service.resume_agent(sample_battle.id, uuid4(), sample_battle.account_id)
        service._battle_repo.update_participant.assert_called_once()

    async def test_resume_active_agent_fails(self, service, sample_battle):
        sample_battle.status = "active"
        service._battle_repo.get_battle.return_value = sample_battle

        participant = MagicMock()
        participant.status = "active"
        service._battle_repo.get_participant.return_value = participant

        with pytest.raises(BattleInvalidStateError, match="not paused"):
            await service.resume_agent(sample_battle.id, uuid4(), sample_battle.account_id)


class TestStopBattle:
    async def test_stop_active_battle(self, service, sample_battle):
        sample_battle.status = "active"
        service._battle_repo.get_battle.return_value = sample_battle

        participant = MagicMock()
        participant.agent_id = uuid4()
        participant.snapshot_balance = Decimal("10000")
        service._battle_repo.get_participants.return_value = [participant]

        agent = MagicMock()
        agent.starting_balance = Decimal("10000")
        agent.account_id = sample_battle.account_id
        service._agent_repo.get_by_id.return_value = agent
        service._wallet_manager.get_agent_equity.return_value = Decimal("11000")
        service._battle_repo.get_snapshots.return_value = []
        service._trade_repo.list_by_agent.return_value = []
        service._battle_repo.update_participant.return_value = MagicMock()
        service._wallet_manager.restore_wallet.return_value = None
        service._battle_repo.update_status.return_value = sample_battle

        await service.stop_battle(sample_battle.id, sample_battle.account_id)
        service._battle_repo.update_status.assert_called_once()


class TestCancelBattle:
    async def test_cancel_draft(self, service, sample_battle):
        sample_battle.status = "draft"
        service._battle_repo.get_battle.return_value = sample_battle
        service._battle_repo.update_status.return_value = sample_battle

        await service.cancel_battle(sample_battle.id, sample_battle.account_id)
        service._battle_repo.update_status.assert_called_once()

    async def test_cancel_completed_fails(self, service, sample_battle):
        sample_battle.status = "completed"
        service._battle_repo.get_battle.return_value = sample_battle

        with pytest.raises(BattleInvalidStateError):
            await service.cancel_battle(sample_battle.id, sample_battle.account_id)


class TestStateTransitions:
    def test_valid_transitions(self, service):
        service._validate_transition("draft", "pending")
        service._validate_transition("draft", "cancelled")
        service._validate_transition("pending", "active")
        service._validate_transition("active", "completed")
        service._validate_transition("active", "paused")
        service._validate_transition("paused", "active")

    def test_invalid_transitions(self, service):
        with pytest.raises(BattleInvalidStateError):
            service._validate_transition("draft", "active")
        with pytest.raises(BattleInvalidStateError):
            service._validate_transition("completed", "active")
        with pytest.raises(BattleInvalidStateError):
            service._validate_transition("cancelled", "active")
