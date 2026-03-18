"""Integration tests for battle WebSocket channel."""

from __future__ import annotations

from uuid import uuid4

from src.api.websocket.channels import BattleChannel, resolve_channel_name


class TestBattleChannel:
    def test_channel_name(self):
        battle_id = str(uuid4())
        name = BattleChannel.channel_name(battle_id)
        assert name == f"battle:{battle_id}"

    def test_serialize_update(self):
        battle_id = str(uuid4())
        participants = [
            {
                "agent_id": str(uuid4()),
                "display_name": "AlphaBot",
                "equity": "10500.00",
                "pnl_pct": "5.0",
                "status": "active",
            }
        ]
        envelope = BattleChannel.serialize_update(battle_id, participants)

        assert envelope["channel"] == "battle"
        assert envelope["battle_id"] == battle_id
        assert envelope["type"] == "update"
        assert "timestamp" in envelope
        assert len(envelope["participants"]) == 1

    def test_serialize_trade(self):
        battle_id = str(uuid4())
        raw = {
            "agent_id": str(uuid4()),
            "agent_name": "AlphaBot",
            "agent_color": "#FF5733",
            "side": "BUY",
            "symbol": "BTCUSDT",
            "quantity": "0.5",
            "price": "64521.30",
            "pnl": "125.40",
        }
        envelope = BattleChannel.serialize_trade(battle_id, raw)

        assert envelope["channel"] == "battle"
        assert envelope["type"] == "trade"
        assert envelope["symbol"] == "BTCUSDT"
        assert envelope["side"] == "BUY"

    def test_serialize_status(self):
        battle_id = str(uuid4())
        envelope = BattleChannel.serialize_status(
            battle_id,
            "agent_paused",
            {"agent_id": str(uuid4())},
        )

        assert envelope["channel"] == "battle"
        assert envelope["type"] == "status"
        assert envelope["event"] == "agent_paused"
        assert "timestamp" in envelope

    def test_serialize_status_completed(self):
        battle_id = str(uuid4())
        rankings = [{"agent_id": str(uuid4()), "rank": 1}]
        envelope = BattleChannel.serialize_status(
            battle_id,
            "battle_completed",
            {"rankings": rankings},
        )

        assert envelope["event"] == "battle_completed"
        assert "rankings" in envelope


class TestBattleChannelResolver:
    def test_resolve_battle_channel(self):
        battle_id = str(uuid4())
        payload = {"action": "subscribe", "channel": "battle", "battle_id": battle_id}
        name = resolve_channel_name(payload)
        assert name == f"battle:{battle_id}"

    def test_resolve_battle_missing_id(self):
        payload = {"action": "subscribe", "channel": "battle"}
        name = resolve_channel_name(payload)
        assert name is None

    def test_resolve_battle_empty_id(self):
        payload = {"action": "subscribe", "channel": "battle", "battle_id": ""}
        name = resolve_channel_name(payload)
        assert name is None
