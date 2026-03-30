"""Unit tests for BattleService.replay_battle() — Phase 6.

Tests:
- Replay a completed live battle -> creates historical draft with correct time range
- Replay a completed historical battle -> reuses backtest_config
- override_agents swaps participants
- override_config merges with source config
- Cannot replay a draft/active battle (only completed)
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_battle(
    *,
    battle_id=None,
    account_id=None,
    status="completed",
    battle_mode="live",
    backtest_config=None,
    config=None,
    started_at=None,
    ended_at=None,
    name="Test Battle",
    ranking_metric="roi_pct",
):
    battle = MagicMock()
    battle.id = battle_id or uuid4()
    battle.account_id = account_id or uuid4()
    battle.status = status
    battle.battle_mode = battle_mode
    battle.backtest_config = backtest_config
    battle.config = config or {"starting_balance": "10000", "wallet_mode": "fresh"}
    battle.started_at = started_at
    battle.ended_at = ended_at
    battle.name = name
    battle.ranking_metric = ranking_metric
    battle.preset = None
    battle.created_at = datetime.now(UTC)
    battle.participants = []
    return battle


def _make_participant(battle_id, agent_id=None):
    p = MagicMock()
    p.id = uuid4()
    p.battle_id = battle_id
    p.agent_id = agent_id or uuid4()
    p.status = "stopped"
    p.snapshot_balance = Decimal("10000")
    p.final_equity = Decimal("10500")
    p.final_rank = 1
    p.joined_at = datetime.now(UTC)
    return p


def _make_agent(account_id, agent_id=None):
    agent = MagicMock()
    agent.id = agent_id or uuid4()
    agent.account_id = account_id
    agent.display_name = "Test Agent"
    agent.starting_balance = Decimal("10000")
    return agent


def _create_service():
    """Create a BattleService with mocked session/settings (lazy import)."""
    from src.battles.service import BattleService  # noqa: PLC0415

    session = AsyncMock()
    settings = MagicMock()
    return BattleService(session, settings)


def _setup_service_for_replay(
    service,
    source,
    participants,
    account_id,
    new_battle=None,
):
    """Wire up common mocks for replay tests.

    get_battle is called:
      1. By replay_battle() to load the source
      2. By add_participant() for each agent (ownership check on the NEW battle)
      3. By replay_battle() at the end to return the final battle
    """
    if new_battle is None:
        new_battle = _make_battle(
            account_id=account_id,
            status="draft",
            battle_mode="historical",
        )

    def _get_battle_side_effect(bid: UUID):
        """Return source for source.id, new_battle for anything else."""
        if bid == source.id:
            return source
        return new_battle

    service._battle_repo.get_battle = AsyncMock(side_effect=_get_battle_side_effect)
    service._battle_repo.get_participants = AsyncMock(return_value=participants)
    service._battle_repo.create_battle = AsyncMock(return_value=new_battle)
    service._battle_repo.add_participant = AsyncMock(side_effect=lambda p: p)
    service._agent_repo.get_by_id = AsyncMock(
        side_effect=lambda aid: _make_agent(account_id, aid),
    )
    return new_battle


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_replay_live_battle_creates_historical_draft():
    """Replay a completed live battle -> creates historical draft with correct time range."""
    account_id = uuid4()
    started = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
    ended = datetime(2026, 3, 10, 13, 0, 0, tzinfo=UTC)

    source = _make_battle(
        account_id=account_id,
        status="completed",
        battle_mode="live",
        started_at=started,
        ended_at=ended,
    )
    agent_a, agent_b = uuid4(), uuid4()
    participants = [
        _make_participant(source.id, agent_a),
        _make_participant(source.id, agent_b),
    ]

    service = _create_service()
    _setup_service_for_replay(service, source, participants, account_id)

    await service.replay_battle(source.id, account_id)

    create_call = service._battle_repo.create_battle.call_args
    created = create_call[0][0]
    assert created.battle_mode == "historical"
    assert created.backtest_config is not None
    assert created.backtest_config["start_time"] == started.isoformat()
    assert created.backtest_config["end_time"] == ended.isoformat()
    assert created.backtest_config["candle_interval"] == 60
    assert created.status == "draft"
    assert created.name == f"Replay: {source.name}"
    assert service._battle_repo.add_participant.call_count == 2


async def test_replay_historical_battle_reuses_backtest_config():
    """Replay a completed historical battle -> reuses backtest_config."""
    account_id = uuid4()
    bt_config = {
        "start_time": "2026-03-01T00:00:00+00:00",
        "end_time": "2026-03-02T00:00:00+00:00",
        "candle_interval": 300,
        "pairs": ["BTCUSDT", "ETHUSDT"],
    }
    source = _make_battle(
        account_id=account_id,
        status="completed",
        battle_mode="historical",
        backtest_config=bt_config,
        started_at=datetime(2026, 3, 15, tzinfo=UTC),
        ended_at=datetime(2026, 3, 15, 0, 5, tzinfo=UTC),
    )
    participants = [_make_participant(source.id), _make_participant(source.id)]

    service = _create_service()
    _setup_service_for_replay(service, source, participants, account_id)

    await service.replay_battle(source.id, account_id)

    created = service._battle_repo.create_battle.call_args[0][0]
    assert created.backtest_config["candle_interval"] == 300
    assert created.backtest_config["pairs"] == ["BTCUSDT", "ETHUSDT"]


async def test_replay_override_agents_replaces_participants():
    """override_agents swaps participants."""
    account_id = uuid4()
    source = _make_battle(
        account_id=account_id,
        status="completed",
        battle_mode="historical",
        backtest_config={
            "start_time": "2026-03-01T00:00:00+00:00",
            "end_time": "2026-03-02T00:00:00+00:00",
            "candle_interval": 60,
        },
    )
    original_agent = uuid4()
    participants = [_make_participant(source.id, original_agent)]
    new_agent_a, new_agent_b = uuid4(), uuid4()

    service = _create_service()
    _setup_service_for_replay(service, source, participants, account_id)

    added_agents: list[UUID] = []

    async def _track_add(p):
        added_agents.append(p.agent_id)
        return p

    service._battle_repo.add_participant = AsyncMock(side_effect=_track_add)

    await service.replay_battle(
        source.id,
        account_id,
        override_agents=[new_agent_a, new_agent_b],
    )

    assert len(added_agents) == 2
    assert new_agent_a in added_agents
    assert new_agent_b in added_agents
    assert original_agent not in added_agents


async def test_replay_override_config_merges():
    """override_config merges with source config."""
    account_id = uuid4()
    bt_config = {
        "start_time": "2026-03-01T00:00:00+00:00",
        "end_time": "2026-03-02T00:00:00+00:00",
        "candle_interval": 60,
        "pairs": ["BTCUSDT"],
    }
    source = _make_battle(
        account_id=account_id,
        status="completed",
        battle_mode="historical",
        backtest_config=bt_config,
    )
    participants = [_make_participant(source.id), _make_participant(source.id)]

    service = _create_service()
    _setup_service_for_replay(service, source, participants, account_id)

    await service.replay_battle(
        source.id,
        account_id,
        override_config={"candle_interval": 300, "pairs": ["ETHUSDT"]},
    )

    created = service._battle_repo.create_battle.call_args[0][0]
    assert created.backtest_config["candle_interval"] == 300
    assert created.backtest_config["pairs"] == ["ETHUSDT"]
    assert created.backtest_config["start_time"] == "2026-03-01T00:00:00+00:00"


@pytest.mark.parametrize("bad_status", ["draft", "pending", "active", "paused", "cancelled"])
async def test_replay_rejects_non_completed(bad_status):
    """Cannot replay a battle that is not completed."""
    from src.battles.service import BattleInvalidStateError  # noqa: PLC0415

    account_id = uuid4()
    source = _make_battle(account_id=account_id, status=bad_status)

    service = _create_service()
    service._battle_repo.get_battle = AsyncMock(return_value=source)

    with pytest.raises(BattleInvalidStateError, match="only replay completed"):
        await service.replay_battle(source.id, account_id)


async def test_replay_rejects_wrong_owner():
    """Cannot replay a battle you don't own."""
    from src.utils.exceptions import PermissionDeniedError  # noqa: PLC0415

    source = _make_battle(account_id=uuid4(), status="completed")

    service = _create_service()
    service._battle_repo.get_battle = AsyncMock(return_value=source)

    with pytest.raises(PermissionDeniedError):
        await service.replay_battle(source.id, uuid4())
