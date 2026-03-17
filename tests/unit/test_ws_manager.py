"""Unit tests for WebSocket ConnectionManager.

Tests connection lifecycle, subscription management, broadcasting,
and heartbeat behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.api.websocket.manager import Connection, ConnectionManager


def _make_connection(
    connection_id=None,
    account_id=None,
    websocket=None,
) -> Connection:
    """Create a Connection instance for testing."""
    return Connection(
        connection_id=connection_id or "conn-test-123",
        account_id=account_id or uuid4(),
        websocket=websocket or MagicMock(),
    )


class TestConnection:
    def test_add_subscription(self) -> None:
        """add_subscription adds channel to set."""
        conn = _make_connection()

        result = conn.add_subscription("ticker:BTCUSDT")

        assert result is True
        assert "ticker:BTCUSDT" in conn.subscriptions

    def test_add_subscription_idempotent(self) -> None:
        """Adding the same channel twice is idempotent."""
        conn = _make_connection()
        conn.add_subscription("ticker:BTCUSDT")

        result = conn.add_subscription("ticker:BTCUSDT")

        assert result is True
        assert len(conn.subscriptions) == 1

    def test_add_subscription_cap_reached(self) -> None:
        """Adding beyond the cap returns False."""
        conn = _make_connection()
        for i in range(10):
            conn.add_subscription(f"channel:{i}")

        result = conn.add_subscription("channel:overflow")

        assert result is False
        assert len(conn.subscriptions) == 10

    def test_remove_subscription(self) -> None:
        """remove_subscription removes channel from set."""
        conn = _make_connection()
        conn.add_subscription("ticker:BTCUSDT")

        conn.remove_subscription("ticker:BTCUSDT")

        assert "ticker:BTCUSDT" not in conn.subscriptions

    def test_remove_nonexistent_subscription(self) -> None:
        """Removing a nonexistent channel is a no-op."""
        conn = _make_connection()
        conn.remove_subscription("ticker:BTCUSDT")  # should not raise

    def test_is_subscribed(self) -> None:
        """is_subscribed returns correct boolean."""
        conn = _make_connection()
        conn.add_subscription("ticker:BTCUSDT")

        assert conn.is_subscribed("ticker:BTCUSDT") is True
        assert conn.is_subscribed("ticker:ETHUSDT") is False

    def test_notify_pong_sets_event(self) -> None:
        """notify_pong sets the internal event."""
        conn = _make_connection()
        assert not conn._pong_event.is_set()

        conn.notify_pong()

        assert conn._pong_event.is_set()


class TestConnectionManager:
    def test_initial_state(self) -> None:
        """New manager has zero active connections."""
        manager = ConnectionManager()

        assert manager.active_count == 0

    async def test_subscribe_to_channel(self) -> None:
        """subscribe adds client to channel subscriber list."""
        manager = ConnectionManager()
        account_id = uuid4()
        conn = _make_connection(connection_id="conn-1", account_id=account_id)
        manager._connections["conn-1"] = conn
        manager._account_index[account_id] = {"conn-1"}

        result = await manager.subscribe("conn-1", "ticker:BTCUSDT")

        assert result is True
        assert "ticker:BTCUSDT" in manager.get_subscriptions("conn-1")

    async def test_subscribe_unknown_connection(self) -> None:
        """subscribe returns False for unknown connection_id."""
        manager = ConnectionManager()

        result = await manager.subscribe("unknown-id", "ticker:BTCUSDT")

        assert result is False

    async def test_unsubscribe_from_channel(self) -> None:
        """unsubscribe removes client from channel."""
        manager = ConnectionManager()
        conn = _make_connection(connection_id="conn-1")
        conn.add_subscription("ticker:BTCUSDT")
        manager._connections["conn-1"] = conn

        await manager.unsubscribe("conn-1", "ticker:BTCUSDT")

        assert "ticker:BTCUSDT" not in manager.get_subscriptions("conn-1")

    async def test_unsubscribe_unknown_connection(self) -> None:
        """unsubscribe is a no-op for unknown connection_id."""
        manager = ConnectionManager()
        await manager.unsubscribe("unknown", "ticker:BTCUSDT")  # should not raise

    def test_get_subscriptions_unknown(self) -> None:
        """get_subscriptions returns empty set for unknown connection."""
        manager = ConnectionManager()

        result = manager.get_subscriptions("unknown")

        assert result == set()

    def test_get_connection(self) -> None:
        """get_connection returns Connection or None."""
        manager = ConnectionManager()
        conn = _make_connection(connection_id="conn-1")
        manager._connections["conn-1"] = conn

        assert manager.get_connection("conn-1") is conn
        assert manager.get_connection("unknown") is None

    async def test_broadcast_to_channel(self) -> None:
        """broadcast_to_channel sends to all subscribers."""
        manager = ConnectionManager()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        conn1 = _make_connection(connection_id="conn-1", websocket=ws1)
        conn1.add_subscription("ticker:BTCUSDT")
        conn2 = _make_connection(connection_id="conn-2", websocket=ws2)
        # conn2 not subscribed

        manager._connections["conn-1"] = conn1
        manager._connections["conn-2"] = conn2

        payload = {"type": "ticker", "symbol": "BTCUSDT", "price": "50000"}
        sent = await manager.broadcast_to_channel("ticker:BTCUSDT", payload)

        assert sent == 1
        ws1.send_json.assert_awaited_once_with(payload)
        ws2.send_json.assert_not_awaited()

    async def test_broadcast_to_account(self) -> None:
        """broadcast_to_account sends to all connections for the account."""
        manager = ConnectionManager()
        account_id = uuid4()
        ws1 = AsyncMock()
        ws2 = AsyncMock()

        conn1 = _make_connection(connection_id="conn-1", account_id=account_id, websocket=ws1)
        conn2 = _make_connection(connection_id="conn-2", account_id=account_id, websocket=ws2)

        manager._connections["conn-1"] = conn1
        manager._connections["conn-2"] = conn2
        manager._account_index[account_id] = {"conn-1", "conn-2"}

        payload = {"type": "order_update", "status": "filled"}
        sent = await manager.broadcast_to_account(account_id, payload)

        assert sent == 2

    async def test_broadcast_skips_disconnected(self) -> None:
        """broadcast skips connections that raise on send."""
        manager = ConnectionManager()
        ws = AsyncMock()
        ws.send_json.side_effect = RuntimeError("connection closed")

        conn = _make_connection(connection_id="conn-1", websocket=ws)
        conn.add_subscription("ticker:BTCUSDT")
        manager._connections["conn-1"] = conn

        payload = {"type": "ticker"}
        sent = await manager.broadcast_to_channel("ticker:BTCUSDT", payload)

        assert sent == 0

    async def test_disconnect_removes_from_pool(self) -> None:
        """disconnect removes connection from registry."""
        manager = ConnectionManager()
        account_id = uuid4()
        ws = MagicMock()
        ws.client_state = MagicMock()  # Not CONNECTED
        ws.close = AsyncMock()

        conn = _make_connection(connection_id="conn-1", account_id=account_id, websocket=ws)
        manager._connections["conn-1"] = conn
        manager._account_index[account_id] = {"conn-1"}

        await manager.disconnect("conn-1")

        assert "conn-1" not in manager._connections
        assert manager.active_count == 0

    async def test_disconnect_unknown_is_noop(self) -> None:
        """disconnect for unknown connection_id is a no-op."""
        manager = ConnectionManager()
        await manager.disconnect("unknown")  # should not raise

    def test_notify_pong(self) -> None:
        """notify_pong signals the correct connection."""
        manager = ConnectionManager()
        conn = _make_connection(connection_id="conn-1")
        manager._connections["conn-1"] = conn

        manager.notify_pong("conn-1")

        assert conn._pong_event.is_set()

    def test_notify_pong_unknown(self) -> None:
        """notify_pong for unknown connection is a no-op."""
        manager = ConnectionManager()
        manager.notify_pong("unknown")  # should not raise

    def test_account_connection_ids(self) -> None:
        """account_connection_ids returns all connection IDs for an account."""
        manager = ConnectionManager()
        account_id = uuid4()
        manager._account_index[account_id] = {"conn-1", "conn-2"}

        result = manager.account_connection_ids(account_id)

        assert result == {"conn-1", "conn-2"}

    def test_account_connection_ids_unknown(self) -> None:
        """account_connection_ids returns empty set for unknown account."""
        manager = ConnectionManager()

        result = manager.account_connection_ids(uuid4())

        assert result == set()
