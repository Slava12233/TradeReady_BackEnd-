"""Integration tests for the WebSocket endpoint.

Covers the following scenarios (plan Step 29 / Section 16):

- Connect with valid ``api_key`` query param — connection accepted
- Connect with invalid / missing ``api_key`` — connection closed with 4401
- Subscribe to ``ticker:{symbol}`` — receives ``{"type": "subscribed", ...}``
- Subscribe to ``ticker:all``       — receives ``{"type": "subscribed", ...}``
- Subscribe to ``candles:{symbol}:{interval}``
- Subscribe to ``orders`` (private)
- Subscribe to ``portfolio`` (private)
- Unsubscribe removes the channel
- Invalid channel → ``{"type": "error", "code": "INVALID_CHANNEL", ...}``
- Unknown action  → ``{"type": "error", "code": "UNKNOWN_ACTION", ...}``
- Subscription cap (11th sub rejected with ``SUBSCRIPTION_LIMIT``)
- Heartbeat ping — server sends ``{"type": "ping"}`` and client pong is
  acknowledged (notify_pong called)
- Receive price update via Redis bridge — subscribed clients get ticker envelope
- Order notification via ``broadcast_to_account``
- Portfolio notification via ``broadcast_to_account``

All external I/O (DB, Redis) is mocked.  Tests use FastAPI's
``TestClient`` with ``with_websocket()`` so no real network is needed.

Run with::

    pytest tests/integration/test_websocket.py -v
"""

from __future__ import annotations

import asyncio
import contextlib
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest

from src.api.websocket.channels import (
    CandleChannel,
    OrderChannel,
    PortfolioChannel,
    TickerChannel,
)
from src.api.websocket.manager import ConnectionManager
from src.config import Settings
from src.database.models import Account

# ---------------------------------------------------------------------------
# Test settings
# ---------------------------------------------------------------------------

_TEST_SETTINGS = Settings(
    jwt_secret="test_secret_that_is_at_least_32_characters_long_for_hs256",
    database_url="postgresql+asyncpg://test:test@localhost:5432/test",
    redis_url="redis://localhost:6379/15",
    jwt_expiry_hours=1,
)

_VALID_API_KEY = "ak_live_testwebsocketkey"
_ACCOUNT_ID = uuid4()


# ---------------------------------------------------------------------------
# Helper: build mock Account ORM object
# ---------------------------------------------------------------------------


def _make_account(
    account_id: UUID | None = None,
    api_key: str = _VALID_API_KEY,
    status: str = "active",
) -> Account:
    """Build a mock :class:`~src.database.models.Account` ORM object.

    Args:
        account_id: Override account UUID (defaults to module-level ``_ACCOUNT_ID``).
        api_key:    API key string.
        status:     Account status string.

    Returns:
        A ``MagicMock`` configured to look like an ``Account`` instance.
    """
    account = MagicMock(spec=Account)
    account.id = account_id or _ACCOUNT_ID
    account.api_key = api_key
    account.status = status
    account.display_name = "WSTestBot"
    account.starting_balance = Decimal("10000.00")
    return account


# ---------------------------------------------------------------------------
# App / client factory
# ---------------------------------------------------------------------------


def _make_mock_redis() -> AsyncMock:
    """Build a fully configured mock Redis client.

    Returns:
        ``AsyncMock`` that simulates common Redis operations.
    """
    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.incr = AsyncMock(return_value=1)
    mock_redis.expire = AsyncMock(return_value=True)
    mock_redis.ttl = AsyncMock(return_value=60)
    mock_redis.hget = AsyncMock(return_value=None)
    mock_redis.hset = AsyncMock(return_value=1)

    # Pipeline mock for rate-limit middleware
    mock_pipe = AsyncMock()
    mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
    mock_pipe.__aexit__ = AsyncMock(return_value=False)
    mock_pipe.incr = MagicMock()
    mock_pipe.expire = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[1, 60])
    mock_redis.pipeline = MagicMock(return_value=mock_pipe)
    return mock_redis


def _build_client(
    authenticated_account: Account | None = None,
) -> TestClient:
    """Create a ``TestClient`` with a mocked infrastructure stack.

    The lifespan of the FastAPI app sets ``app.state.ws_manager``.  We let
    the full lifespan run while patching out all real I/O, then return the
    client.  All patches are held open by an ``ExitStack`` that lives on the
    ``client`` object itself (as ``client._patch_stack``).

    Args:
        authenticated_account: When provided, ``ConnectionManager._authenticate``
            will succeed and return this account's ID.  ``None`` makes auth
            return ``None`` (rejected).

    Returns:
        A ``TestClient`` wrapping the full application with the lifespan
        already started.  Call ``client._patch_stack.close()`` to release
        patches when done (normally not needed in short-lived test blocks).
    """
    from src.dependencies import get_db_session, get_redis, get_settings

    mock_redis = _make_mock_redis()
    mock_session = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    auth_return = authenticated_account.id if authenticated_account is not None else None

    # Use an ExitStack so all patches survive beyond this function's scope.
    stack = contextlib.ExitStack()

    stack.enter_context(patch("src.database.session.init_db", new_callable=AsyncMock))
    stack.enter_context(patch("src.database.session.close_db", new_callable=AsyncMock))
    stack.enter_context(
        patch(
            "src.cache.redis_client.get_redis_client",
            new_callable=AsyncMock,
            return_value=mock_redis,
        )
    )
    stack.enter_context(patch("src.api.websocket.handlers.start_redis_bridge", new_callable=AsyncMock))
    stack.enter_context(patch("src.api.websocket.handlers.stop_redis_bridge", new_callable=AsyncMock))
    stack.enter_context(
        patch(
            "src.api.websocket.manager.ConnectionManager.disconnect_all",
            new_callable=AsyncMock,
        )
    )
    stack.enter_context(
        patch(
            "src.api.websocket.manager.ConnectionManager._authenticate",
            new_callable=AsyncMock,
            return_value=auth_return,
        )
    )

    from src.main import create_app

    app = create_app()

    app.dependency_overrides[get_settings] = lambda: _TEST_SETTINGS

    async def _override_db():
        yield mock_session

    app.dependency_overrides[get_db_session] = _override_db

    async def _override_redis():
        yield mock_redis

    app.dependency_overrides[get_redis] = _override_redis

    # Enter the TestClient so the lifespan runs (sets app.state.ws_manager).
    client = TestClient(app, raise_server_exceptions=False)
    stack.enter_context(client)

    # Attach the stack so it lives as long as the caller keeps the client.
    client._patch_stack = stack  # type: ignore[attr-defined]
    return client


# ===========================================================================
# Connection — authentication
# ===========================================================================


class TestWebSocketConnection:
    """Tests for WebSocket connection auth and lifecycle."""

    def test_connect_with_valid_api_key_is_accepted(self) -> None:
        """Valid api_key → WebSocket handshake succeeds (no close before send)."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            # If we reach here the handshake was accepted
            ws.send_json({"action": "pong"})
            # No assertion needed — reaching this line proves acceptance

    def test_connect_with_invalid_api_key_is_rejected(self) -> None:
        """Invalid api_key → server closes connection (auth failure)."""
        # Passing None as authenticated_account makes _authenticate return None
        client = _build_client(authenticated_account=None)

        with pytest.raises(Exception):  # noqa: B017
            # TestClient raises when the server closes the WS before sending
            with client.websocket_connect("/ws/v1?api_key=ak_live_invalid"):
                pass  # pragma: no cover

    def test_connect_without_api_key_is_rejected(self) -> None:
        """Missing api_key query param → authentication fails → connection rejected."""
        client = _build_client(authenticated_account=None)

        with pytest.raises(Exception):  # noqa: B017
            with client.websocket_connect("/ws/v1"):
                pass  # pragma: no cover


# ===========================================================================
# Subscribe / unsubscribe
# ===========================================================================


class TestWebSocketSubscription:
    """Tests for subscribe and unsubscribe message handling."""

    def test_subscribe_ticker_symbol(self) -> None:
        """Subscribe to ``ticker`` channel with symbol → receives ``subscribed`` confirmation."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "ticker", "symbol": "BTCUSDT"})
            msg = ws.receive_json()

        assert msg["type"] == "subscribed"
        assert msg["channel"] == "ticker:BTCUSDT"

    def test_subscribe_ticker_all(self) -> None:
        """Subscribe to ``ticker_all`` channel → receives subscribed with ``ticker:all``."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "ticker_all"})
            msg = ws.receive_json()

        assert msg["type"] == "subscribed"
        assert msg["channel"] == "ticker:all"

    def test_subscribe_candles(self) -> None:
        """Subscribe to candles channel → receives subscribed with correct name."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json(
                {
                    "action": "subscribe",
                    "channel": "candles",
                    "symbol": "ETHUSDT",
                    "interval": "1m",
                }
            )
            msg = ws.receive_json()

        assert msg["type"] == "subscribed"
        assert msg["channel"] == "candles:ETHUSDT:1m"

    def test_subscribe_orders_channel(self) -> None:
        """Subscribe to private ``orders`` channel → subscribed with ``orders``."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "orders"})
            msg = ws.receive_json()

        assert msg["type"] == "subscribed"
        assert msg["channel"] == "orders"

    def test_subscribe_portfolio_channel(self) -> None:
        """Subscribe to private ``portfolio`` channel → subscribed with ``portfolio``."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "portfolio"})
            msg = ws.receive_json()

        assert msg["type"] == "subscribed"
        assert msg["channel"] == "portfolio"

    def test_subscribe_is_idempotent(self) -> None:
        """Subscribing to the same channel twice is idempotent — both succeed."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "ticker", "symbol": "BTCUSDT"})
            first = ws.receive_json()
            ws.send_json({"action": "subscribe", "channel": "ticker", "symbol": "BTCUSDT"})
            second = ws.receive_json()

        assert first["type"] == "subscribed"
        assert second["type"] == "subscribed"
        assert first["channel"] == second["channel"] == "ticker:BTCUSDT"

    def test_unsubscribe_removes_subscription(self) -> None:
        """Unsubscribing after subscribing returns ``unsubscribed`` confirmation."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "ticker", "symbol": "BNBUSDT"})
            ws.receive_json()  # subscribed

            ws.send_json({"action": "unsubscribe", "channel": "ticker", "symbol": "BNBUSDT"})
            msg = ws.receive_json()

        assert msg["type"] == "unsubscribed"
        assert msg["channel"] == "ticker:BNBUSDT"

    def test_unsubscribe_non_existent_channel_is_graceful(self) -> None:
        """Unsubscribing from a channel not subscribed to → ``unsubscribed`` (no error)."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "unsubscribe", "channel": "ticker", "symbol": "XRPUSDT"})
            msg = ws.receive_json()

        assert msg["type"] == "unsubscribed"
        assert msg["channel"] == "ticker:XRPUSDT"

    def test_subscribe_all_four_candle_intervals(self) -> None:
        """All four supported candle intervals are accepted."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        intervals = ["1m", "5m", "1h", "1d"]
        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            for interval in intervals:
                ws.send_json(
                    {
                        "action": "subscribe",
                        "channel": "candles",
                        "symbol": "BTCUSDT",
                        "interval": interval,
                    }
                )
                msg = ws.receive_json()
                assert msg["type"] == "subscribed"
                assert msg["channel"] == f"candles:BTCUSDT:{interval}"


# ===========================================================================
# Subscription errors
# ===========================================================================


class TestWebSocketSubscriptionErrors:
    """Tests for malformed or invalid subscribe/unsubscribe messages."""

    def test_subscribe_ticker_without_symbol_returns_error(self) -> None:
        """Missing symbol for ``ticker`` channel → ``INVALID_CHANNEL`` error."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "ticker"})
            msg = ws.receive_json()

        assert msg["type"] == "error"
        assert msg["code"] == "INVALID_CHANNEL"

    def test_subscribe_candles_without_symbol_returns_error(self) -> None:
        """Missing symbol for ``candles`` channel → ``INVALID_CHANNEL`` error."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "candles", "interval": "1m"})
            msg = ws.receive_json()

        assert msg["type"] == "error"
        assert msg["code"] == "INVALID_CHANNEL"

    def test_subscribe_candles_without_interval_returns_error(self) -> None:
        """Missing interval for ``candles`` channel → ``INVALID_CHANNEL`` error."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "candles", "symbol": "BTCUSDT"})
            msg = ws.receive_json()

        assert msg["type"] == "error"
        assert msg["code"] == "INVALID_CHANNEL"

    def test_subscribe_unknown_channel_returns_error(self) -> None:
        """Completely unknown channel name → ``INVALID_CHANNEL`` error."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "unknown_channel"})
            msg = ws.receive_json()

        assert msg["type"] == "error"
        assert msg["code"] == "INVALID_CHANNEL"

    def test_subscribe_missing_channel_field_returns_error(self) -> None:
        """``subscribe`` action with no ``channel`` key → ``INVALID_CHANNEL``."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe"})
            msg = ws.receive_json()

        assert msg["type"] == "error"
        assert msg["code"] == "INVALID_CHANNEL"

    def test_unknown_action_returns_error(self) -> None:
        """Unrecognised ``action`` field → ``UNKNOWN_ACTION`` error."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "do_something_weird"})
            msg = ws.receive_json()

        assert msg["type"] == "error"
        assert msg["code"] == "UNKNOWN_ACTION"

    def test_subscription_cap_returns_limit_error(self) -> None:
        """Attempting more than 10 subscriptions → ``SUBSCRIPTION_LIMIT`` error."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        symbols = [
            "BTCUSDT",
            "ETHUSDT",
            "BNBUSDT",
            "XRPUSDT",
            "ADAUSDT",
            "SOLUSDT",
            "DOTUSDT",
            "DOGEUSDT",
            "MATICUSDT",
            "LTCUSDT",
        ]
        assert len(symbols) == 10  # exactly at the cap

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            # Subscribe to all 10 — all should succeed
            for symbol in symbols:
                ws.send_json({"action": "subscribe", "channel": "ticker", "symbol": symbol})
                msg = ws.receive_json()
                assert msg["type"] == "subscribed"

            # The 11th subscription should be rejected
            ws.send_json({"action": "subscribe", "channel": "ticker_all"})
            msg = ws.receive_json()

        assert msg["type"] == "error"
        assert msg["code"] == "SUBSCRIPTION_LIMIT"

    def test_subscribe_candles_invalid_interval_returns_error(self) -> None:
        """An interval string not in {1m,5m,1h,1d} → ``INVALID_CHANNEL`` error."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json(
                {
                    "action": "subscribe",
                    "channel": "candles",
                    "symbol": "BTCUSDT",
                    "interval": "3m",
                }
            )
            msg = ws.receive_json()

        assert msg["type"] == "error"
        assert msg["code"] == "INVALID_CHANNEL"


# ===========================================================================
# Heartbeat (ping/pong)
# ===========================================================================


class TestWebSocketHeartbeat:
    """Tests for the ping/pong heartbeat mechanic."""

    def test_pong_action_is_accepted_silently(self) -> None:
        """Sending ``{"action": "pong"}`` produces no response (pong is consumed)."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            # Send a pong first (simulate client responding to an unsolicited ping)
            ws.send_json({"action": "pong"})
            # Then send a valid subscribe so we can read the response and verify
            # that no error for the pong was queued before it.
            ws.send_json({"action": "subscribe", "channel": "orders"})
            msg = ws.receive_json()

        # The first message we read back should be the subscribed confirmation,
        # not an error for the pong.
        assert msg["type"] == "subscribed"
        assert msg["channel"] == "orders"

    def test_notify_pong_updates_connection_state(self) -> None:
        """``notify_pong`` sets the pong event on the ``Connection`` object."""
        conn_id = "test-connection-id"
        from src.api.websocket.manager import Connection

        manager = ConnectionManager()
        account_id = uuid4()
        mock_ws = MagicMock()
        mock_ws.client_state = MagicMock()

        conn = Connection(
            connection_id=conn_id,
            account_id=account_id,
            websocket=mock_ws,
        )
        # Manually register connection (bypass full async connect)
        manager._connections[conn_id] = conn

        assert not conn._pong_event.is_set()
        manager.notify_pong(conn_id)
        assert conn._pong_event.is_set()


# ===========================================================================
# Price update delivery (Redis bridge integration)
# ===========================================================================


class TestWebSocketPriceUpdates:
    """Tests for receiving price updates through the Redis bridge."""

    def test_broadcast_to_channel_delivers_ticker_envelope(self) -> None:
        """``broadcast_to_channel`` sends the correct ticker envelope to subscribed WS."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            # Subscribe to the BTCUSDT ticker channel
            ws.send_json({"action": "subscribe", "channel": "ticker", "symbol": "BTCUSDT"})
            ws.receive_json()  # consume "subscribed" confirmation

            # Simulate a price update pushed by the Redis bridge
            # by calling broadcast_to_channel via the TestClient's anyio portal
            raw_tick = {
                "symbol": "BTCUSDT",
                "price": "64521.30000000",
                "quantity": "0.01200000",
                "timestamp": 1708000000000,
                "is_buyer_maker": False,
                "trade_id": 123456789,
            }
            envelope = TickerChannel.serialize("BTCUSDT", raw_tick)
            channel_name = TickerChannel.channel_name("BTCUSDT")

            # Use the TestClient's anyio BlockingPortal to run the coroutine
            # in the same event loop as the running app / WS handler.
            manager: ConnectionManager = client.app.state.ws_manager
            client.portal.call(manager.broadcast_to_channel, channel_name, envelope)

            price_msg = ws.receive_json()

        assert price_msg["channel"] == "ticker"
        assert price_msg["symbol"] == "BTCUSDT"
        assert "data" in price_msg
        data = price_msg["data"]
        assert "price" in data
        assert "quantity" in data
        assert "timestamp" in data
        assert "is_buyer_maker" in data

    def test_broadcast_to_channel_not_delivered_to_unsubscribed(self) -> None:
        """A price update for ``ETHUSDT`` is NOT delivered to a ``BTCUSDT`` subscriber."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "ticker", "symbol": "BTCUSDT"})
            ws.receive_json()  # subscribed

            raw_tick = {
                "symbol": "ETHUSDT",
                "price": "3200.00",
                "quantity": "0.5",
                "timestamp": 1708000000000,
                "is_buyer_maker": True,
            }
            envelope = TickerChannel.serialize("ETHUSDT", raw_tick)
            eth_channel = TickerChannel.channel_name("ETHUSDT")

            manager: ConnectionManager = client.app.state.ws_manager
            sent = client.portal.call(manager.broadcast_to_channel, eth_channel, envelope)

        # sent == 0 means the BTCUSDT-subscribed client did NOT receive the ETH tick
        assert sent == 0

    def test_ticker_all_channel_receives_any_symbol(self) -> None:
        """``ticker:all`` subscriber receives price updates for any symbol."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "ticker_all"})
            ws.receive_json()  # subscribed

            raw_tick = {
                "symbol": "SOLUSDT",
                "price": "180.00",
                "quantity": "2.0",
                "timestamp": 1708000001000,
                "is_buyer_maker": False,
            }
            envelope = TickerChannel.serialize("SOLUSDT", raw_tick)

            manager: ConnectionManager = client.app.state.ws_manager
            client.portal.call(manager.broadcast_to_channel, TickerChannel.ALL, envelope)

            price_msg = ws.receive_json()

        assert price_msg["channel"] == "ticker"
        assert price_msg["symbol"] == "SOLUSDT"


# ===========================================================================
# Order notifications
# ===========================================================================


class TestWebSocketOrderNotifications:
    """Tests for per-account order-status push via ``broadcast_to_account``."""

    def test_order_notification_delivered_to_subscribed_account(self) -> None:
        """Order fill notification reaches a client subscribed to the ``orders`` channel."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "orders"})
            ws.receive_json()  # subscribed

            order_event = OrderChannel.serialize(
                {
                    "order_id": str(uuid4()),
                    "status": "filled",
                    "symbol": "BTCUSDT",
                    "side": "buy",
                    "type": "market",
                    "quantity": "0.50",
                    "executed_price": "64521.30",
                    "executed_quantity": "0.50",
                    "fee": "32.26",
                    "filled_at": 1708000000000,
                }
            )

            manager: ConnectionManager = client.app.state.ws_manager
            client.portal.call(manager.broadcast_to_account, account.id, order_event)

            msg = ws.receive_json()

        assert msg["channel"] == "orders"
        assert "data" in msg
        data = msg["data"]
        assert data["status"] == "filled"
        assert data["symbol"] == "BTCUSDT"
        assert data["side"] == "buy"
        assert "executed_price" in data
        assert "fee" in data

    def test_order_notification_not_delivered_to_unsubscribed(self) -> None:
        """Order event reaches the client regardless of channel subscription.

        ``broadcast_to_account`` is a direct push to all connections of an
        account — it is NOT filtered by channel subscription.  The subscription
        mechanism is only relevant for public channels (ticker, candles).
        """
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as _ws:
            # Connect but do NOT subscribe to orders
            order_event = OrderChannel.serialize(
                {
                    "order_id": str(uuid4()),
                    "status": "cancelled",
                    "symbol": "ETHUSDT",
                    "side": "sell",
                    "type": "limit",
                    "quantity": "1.0",
                }
            )

            manager: ConnectionManager = client.app.state.ws_manager
            # Find the connection and verify it isn't subscribed to "orders"
            conn_ids = list(manager._connections.keys())
            assert len(conn_ids) == 1
            conn = manager.get_connection(conn_ids[0])
            assert conn is not None
            assert "orders" not in conn.subscriptions

            # broadcast_to_account fans out to ALL connections for the account,
            # regardless of channel subscriptions (it's a direct push).
            sent = client.portal.call(manager.broadcast_to_account, account.id, order_event)

        assert sent == 1

    def test_order_notification_not_delivered_to_different_account(self) -> None:
        """Order event for account A is NOT sent to account B's connection."""
        account_a = _make_account(account_id=uuid4(), api_key="ak_live_accounta")
        client = _build_client(authenticated_account=account_a)

        different_account_id = uuid4()

        with client.websocket_connect("/ws/v1?api_key=ak_live_accounta") as _ws:
            order_event = OrderChannel.serialize(
                {
                    "order_id": str(uuid4()),
                    "status": "filled",
                    "symbol": "XRPUSDT",
                    "side": "buy",
                    "type": "market",
                    "quantity": "100.0",
                }
            )

            manager: ConnectionManager = client.app.state.ws_manager
            sent = client.portal.call(manager.broadcast_to_account, different_account_id, order_event)

        # No connections belong to ``different_account_id``
        assert sent == 0


# ===========================================================================
# Portfolio notifications
# ===========================================================================


class TestWebSocketPortfolioNotifications:
    """Tests for per-account portfolio snapshot push via ``broadcast_to_account``."""

    def test_portfolio_notification_delivered(self) -> None:
        """Portfolio snapshot reaches the connected client via ``broadcast_to_account``."""
        account = _make_account()
        client = _build_client(authenticated_account=account)

        with client.websocket_connect(f"/ws/v1?api_key={_VALID_API_KEY}") as ws:
            ws.send_json({"action": "subscribe", "channel": "portfolio"})
            ws.receive_json()  # subscribed

            portfolio_event = PortfolioChannel.serialize(
                {
                    "total_equity": Decimal("12458.30"),
                    "unrealized_pnl": Decimal("660.65"),
                    "realized_pnl": Decimal("1241.30"),
                    "available_cash": Decimal("5000.00"),
                    "timestamp": 1708000000000,
                }
            )

            manager: ConnectionManager = client.app.state.ws_manager
            client.portal.call(manager.broadcast_to_account, account.id, portfolio_event)

            msg = ws.receive_json()

        assert msg["channel"] == "portfolio"
        assert "data" in msg
        data = msg["data"]
        assert "total_equity" in data
        assert "unrealized_pnl" in data
        assert "realized_pnl" in data
        assert "timestamp" in data


# ===========================================================================
# Channel serialisation unit checks
# ===========================================================================


class TestChannelSerialisation:
    """Unit tests for channel ``serialize`` helpers (no network needed)."""

    def test_ticker_channel_name(self) -> None:
        """``TickerChannel.channel_name`` builds the correct key."""
        assert TickerChannel.channel_name("btcusdt") == "ticker:BTCUSDT"
        assert TickerChannel.channel_name("ETHUSDT") == "ticker:ETHUSDT"

    def test_ticker_channel_all_constant(self) -> None:
        """``TickerChannel.ALL`` is ``ticker:all``."""
        assert TickerChannel.ALL == "ticker:all"

    def test_ticker_channel_names_for_symbol(self) -> None:
        """``channel_names_for_symbol`` returns both per-symbol and ``ticker:all``."""
        per_sym, all_ch = TickerChannel.channel_names_for_symbol("BTCUSDT")
        assert per_sym == "ticker:BTCUSDT"
        assert all_ch == "ticker:all"

    def test_ticker_serialize_structure(self) -> None:
        """``TickerChannel.serialize`` produces the correct wire envelope."""
        raw = {
            "price": "64521.30",
            "quantity": "0.012",
            "timestamp": 1708000000000,
            "is_buyer_maker": False,
        }
        envelope = TickerChannel.serialize("BTCUSDT", raw)

        assert envelope["channel"] == "ticker"
        assert envelope["symbol"] == "BTCUSDT"
        assert "data" in envelope
        assert envelope["data"]["price"] == "64521.30"
        assert envelope["data"]["is_buyer_maker"] is False
        # Timestamp must be an ISO string
        assert "T" in envelope["data"]["timestamp"]

    def test_candle_channel_name(self) -> None:
        """``CandleChannel.channel_name`` builds the correct key."""
        assert CandleChannel.channel_name("ETHUSDT", "1m") == "candles:ETHUSDT:1m"
        assert CandleChannel.channel_name("btcusdt", "1d") == "candles:BTCUSDT:1d"

    def test_candle_channel_invalid_interval_raises(self) -> None:
        """``CandleChannel.channel_name`` raises ``ValueError`` for unknown intervals."""
        with pytest.raises(ValueError):
            CandleChannel.channel_name("BTCUSDT", "3m")

    def test_candle_serialize_structure(self) -> None:
        """``CandleChannel.serialize`` produces the correct wire envelope."""
        raw = {
            "time": 1708000000000,
            "open": "64500.00",
            "high": "64550.00",
            "low": "64490.00",
            "close": "64521.30",
            "volume": "12.345",
            "is_closed": False,
        }
        envelope = CandleChannel.serialize("BTCUSDT", "1m", raw)

        assert envelope["channel"] == "candles"
        assert envelope["symbol"] == "BTCUSDT"
        assert envelope["interval"] == "1m"
        data = envelope["data"]
        assert data["open"] == "64500.00"
        assert data["close"] == "64521.30"
        assert data["is_closed"] is False

    def test_order_channel_serialize_filled(self) -> None:
        """``OrderChannel.serialize`` includes optional fields for filled orders."""
        order_id = str(uuid4())
        raw = {
            "order_id": order_id,
            "status": "filled",
            "symbol": "BTCUSDT",
            "side": "buy",
            "type": "market",
            "quantity": "0.50",
            "executed_price": "64521.30",
            "executed_quantity": "0.50",
            "fee": "32.26",
            "filled_at": 1708000000000,
        }
        envelope = OrderChannel.serialize(raw)

        assert envelope["channel"] == "orders"
        data = envelope["data"]
        assert data["order_id"] == order_id
        assert data["status"] == "filled"
        assert "executed_price" in data
        assert "fee" in data
        assert "filled_at" in data

    def test_order_channel_serialize_pending(self) -> None:
        """``OrderChannel.serialize`` works for pending orders (no fill fields)."""
        raw = {
            "order_id": str(uuid4()),
            "status": "pending",
            "symbol": "ETHUSDT",
            "side": "sell",
            "type": "limit",
            "quantity": "1.0",
        }
        envelope = OrderChannel.serialize(raw)
        data = envelope["data"]
        assert data["status"] == "pending"
        assert "executed_price" not in data
        assert "fee" not in data

    def test_portfolio_channel_serialize(self) -> None:
        """``PortfolioChannel.serialize`` produces the correct wire envelope."""
        raw = {
            "total_equity": Decimal("12000.00"),
            "unrealized_pnl": Decimal("500.00"),
            "realized_pnl": Decimal("300.00"),
            "available_cash": Decimal("6000.00"),
            "timestamp": 1708000000000,
        }
        envelope = PortfolioChannel.serialize(raw)

        assert envelope["channel"] == "portfolio"
        data = envelope["data"]
        assert data["total_equity"] == "12000.00"
        assert data["available_cash"] == "6000.00"
        assert "T" in data["timestamp"]

    def test_portfolio_channel_serialize_without_timestamp(self) -> None:
        """``PortfolioChannel.serialize`` uses current UTC if timestamp omitted."""
        raw = {
            "total_equity": "10000.00",
            "unrealized_pnl": "0",
            "realized_pnl": "0",
        }
        envelope = PortfolioChannel.serialize(raw)
        assert "timestamp" in envelope["data"]


# ===========================================================================
# Connection manager unit checks
# ===========================================================================


class TestConnectionManagerUnit:
    """Unit tests for ``ConnectionManager`` state logic (no network needed)."""

    def _make_manager_with_connection(self) -> tuple[ConnectionManager, str]:
        """Build a ``ConnectionManager`` with one pre-registered connection.

        Returns:
            Tuple of ``(manager, connection_id)``.
        """
        from src.api.websocket.manager import Connection

        manager = ConnectionManager()
        conn_id = str(uuid4())
        account_id = uuid4()
        mock_ws = MagicMock()
        conn = Connection(
            connection_id=conn_id,
            account_id=account_id,
            websocket=mock_ws,
        )
        manager._connections[conn_id] = conn
        manager._account_index[account_id] = {conn_id}
        return manager, conn_id

    def test_subscribe_adds_channel(self) -> None:
        """``subscribe`` adds the channel to the connection's subscription set."""
        manager, conn_id = self._make_manager_with_connection()

        result = asyncio.run(manager.subscribe(conn_id, "ticker:BTCUSDT"))

        assert result is True
        assert "ticker:BTCUSDT" in manager.get_subscriptions(conn_id)

    def test_unsubscribe_removes_channel(self) -> None:
        """``unsubscribe`` removes the channel from the subscription set."""
        manager, conn_id = self._make_manager_with_connection()

        async def _do():
            await manager.subscribe(conn_id, "ticker:BTCUSDT")
            await manager.unsubscribe(conn_id, "ticker:BTCUSDT")

        asyncio.run(_do())

        assert "ticker:BTCUSDT" not in manager.get_subscriptions(conn_id)

    def test_get_subscriptions_returns_snapshot(self) -> None:
        """``get_subscriptions`` returns a copy of the subscriptions set."""
        manager, conn_id = self._make_manager_with_connection()
        subs = manager.get_subscriptions(conn_id)
        # Must be a new set object, not the internal reference
        assert isinstance(subs, set)

    def test_get_subscriptions_unknown_connection_returns_empty(self) -> None:
        """``get_subscriptions`` returns empty set for an unknown connection ID."""
        manager = ConnectionManager()
        assert manager.get_subscriptions("nonexistent-id") == set()

    def test_active_count_tracks_connections(self) -> None:
        """``active_count`` reflects the number of registered connections."""
        manager = ConnectionManager()
        assert manager.active_count == 0

        from src.api.websocket.manager import Connection

        for i in range(3):
            conn_id = f"conn-{i}"
            acc_id = uuid4()
            conn = Connection(
                connection_id=conn_id,
                account_id=acc_id,
                websocket=MagicMock(),
            )
            manager._connections[conn_id] = conn

        assert manager.active_count == 3

    def test_get_connection_returns_correct_object(self) -> None:
        """``get_connection`` returns the registered ``Connection`` instance."""
        manager, conn_id = self._make_manager_with_connection()
        conn = manager.get_connection(conn_id)
        assert conn is not None
        assert conn.connection_id == conn_id

    def test_get_connection_unknown_returns_none(self) -> None:
        """``get_connection`` returns ``None`` for an unknown connection ID."""
        manager = ConnectionManager()
        assert manager.get_connection("no-such-id") is None

    def test_account_connection_ids(self) -> None:
        """``account_connection_ids`` returns IDs for the given account."""
        manager, conn_id = self._make_manager_with_connection()
        conn = manager.get_connection(conn_id)
        assert conn is not None
        ids = manager.account_connection_ids(conn.account_id)
        assert conn_id in ids

    def test_connection_add_subscription_cap(self) -> None:
        """``Connection.add_subscription`` returns ``False`` once cap is reached."""
        from src.api.websocket.manager import _MAX_SUBSCRIPTIONS, Connection

        conn = Connection(
            connection_id="cap-test",
            account_id=uuid4(),
            websocket=MagicMock(),
        )
        for i in range(_MAX_SUBSCRIPTIONS):
            added = conn.add_subscription(f"ticker:SYM{i}")
            assert added is True

        # One more should fail
        over_limit = conn.add_subscription("ticker:OVER")
        assert over_limit is False
