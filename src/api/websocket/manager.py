"""WebSocket connection lifecycle manager.

Responsibilities
----------------
1. ``ConnectionManager`` — tracks every live WebSocket connection, keyed by a
   unique ``connection_id``.  Each connection carries its authenticated
   ``account_id``, an open :class:`~fastapi.WebSocket` object, the set of
   active subscriptions, and the asyncio tasks (heartbeat, Redis listener) that
   serve it.
2. ``connect()`` — authenticates the connection via the ``api_key`` query
   parameter, accepts the WebSocket, registers the connection, and starts the
   heartbeat task.
3. ``disconnect()`` — cancels all per-connection tasks, removes the connection
   from the registry, and updates the per-account connection count.
4. ``broadcast_to_account()`` — push a JSON payload to all connections belonging
   to a specific account (order/portfolio events).
5. ``broadcast_to_channel()`` — push a payload to all connections subscribed to
   a given channel name (ticker price updates).
6. Heartbeat loop — sends ``{"type": "ping"}`` every 30 seconds and disconnects
   the client if no ``{"type": "pong"}`` is received within 10 seconds.

Connection lifecycle
--------------------
::

    Client connects → ws://.../ws/v1?api_key=ak_live_...
    Server accepts   → validates api_key via DB lookup
    Server registers → assigns connection_id, starts heartbeat
    Client messages  → forwarded to handlers.py for subscribe/unsubscribe
    Server pushes    → ticker/orders/portfolio events forwarded to subscribed ws
    Client disconnects (or ping timeout) → tasks cancelled, state cleaned up

Example::

    from fastapi import WebSocket
    from src.api.websocket.manager import ConnectionManager

    manager = ConnectionManager()

    @app.websocket("/ws/v1")
    async def ws_endpoint(websocket: WebSocket, api_key: str):
        conn_id = await manager.connect(websocket, api_key)
        if conn_id is None:
            return  # rejected — already closed with 4401
        try:
            async for message in websocket.iter_json():
                await handle_message(conn_id, message, manager)
        except Exception:
            pass
        finally:
            await manager.disconnect(conn_id)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from src.database.repositories.account_repo import AccountRepository
from src.utils.exceptions import AccountNotFoundError, AuthenticationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_HEARTBEAT_INTERVAL: float = 30.0  # seconds between server pings
_PONG_TIMEOUT: float = 10.0  # seconds to wait for client pong
_MAX_SUBSCRIPTIONS: int = 10  # per-connection subscription cap

# WebSocket close codes (4xxx are application-defined)
_WS_CLOSE_AUTH_FAILED: int = 4401
_WS_CLOSE_NORMAL: int = 1000


# ---------------------------------------------------------------------------
# Connection state
# ---------------------------------------------------------------------------


@dataclass
class Connection:
    """State container for a single WebSocket connection.

    Attributes:
        connection_id: Unique identifier assigned on connect.
        account_id:    UUID of the authenticated account.
        websocket:     The live FastAPI WebSocket object.
        subscriptions: Set of channel strings the client has subscribed to.
        heartbeat_task: asyncio Task running the ping/pong loop.
        _pong_event:   Internal event set when the client sends a pong.
    """

    connection_id: str
    account_id: UUID
    websocket: WebSocket
    subscriptions: set[str] = field(default_factory=set)
    heartbeat_task: asyncio.Task[None] | None = field(default=None, repr=False)
    _pong_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def add_subscription(self, channel: str) -> bool:
        """Add *channel* to the subscription set if the cap allows.

        Args:
            channel: Full channel name (e.g. ``"ticker:BTCUSDT"``).

        Returns:
            ``True`` if the subscription was added, ``False`` if the cap was
            reached or the client was already subscribed.
        """
        if channel in self.subscriptions:
            return True  # idempotent
        if len(self.subscriptions) >= _MAX_SUBSCRIPTIONS:
            return False
        self.subscriptions.add(channel)
        return True

    def remove_subscription(self, channel: str) -> None:
        """Remove *channel* from the subscription set (no-op if absent).

        Args:
            channel: Full channel name to unsubscribe from.
        """
        self.subscriptions.discard(channel)

    def is_subscribed(self, channel: str) -> bool:
        """Return ``True`` when the connection has an active subscription for *channel*.

        Args:
            channel: Full channel name to check.

        Returns:
            ``True`` if subscribed, ``False`` otherwise.
        """
        return channel in self.subscriptions

    def notify_pong(self) -> None:
        """Signal the heartbeat loop that the client sent a pong."""
        self._pong_event.set()


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Central registry for all active WebSocket connections.

    Manages the full lifecycle of every client connection: authentication,
    registration, heartbeat, broadcast, and teardown.  A single shared instance
    should be created at application startup and attached to ``app.state``.

    Example::

        from src.api.websocket.manager import ConnectionManager

        manager = ConnectionManager()

        @app.on_event("startup")
        async def startup():
            app.state.ws_manager = manager
    """

    def __init__(self) -> None:
        # connection_id → Connection
        self._connections: dict[str, Connection] = {}
        # account_id → {connection_id, ...}  (one account may have many tabs)
        self._account_index: dict[UUID, set[str]] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public: lifecycle
    # ------------------------------------------------------------------

    async def connect(
        self,
        websocket: WebSocket,
        api_key: str,
    ) -> str | None:
        """Authenticate and register a new WebSocket connection.

        Performs the following steps in order:

        1. Validates *api_key* against the database.
        2. Accepts the WebSocket upgrade.
        3. Assigns a unique ``connection_id``.
        4. Registers the :class:`Connection` in the internal registry.
        5. Starts the heartbeat asyncio task.

        Args:
            websocket: The incoming FastAPI WebSocket (not yet accepted).
            api_key:   The raw API key from the ``api_key`` query parameter.

        Returns:
            The ``connection_id`` string on success, or ``None`` if
            authentication failed (the WebSocket has already been closed with
            code 4401 in that case).
        """
        # Authenticate before accepting — avoids allocating state for bad keys
        account_id = await self._authenticate(api_key)
        if account_id is None:
            await websocket.close(code=_WS_CLOSE_AUTH_FAILED)
            return None

        # Accept the WebSocket upgrade
        await websocket.accept()

        connection_id = str(uuid.uuid4())
        conn = Connection(
            connection_id=connection_id,
            account_id=account_id,
            websocket=websocket,
        )

        async with self._lock:
            self._connections[connection_id] = conn
            self._account_index.setdefault(account_id, set()).add(connection_id)

        # Start heartbeat in the background
        conn.heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(connection_id),
            name=f"ws-heartbeat-{connection_id[:8]}",
        )

        logger.info(
            "ws.connected",
            extra={
                "connection_id": connection_id,
                "account_id": str(account_id),
                "total_connections": len(self._connections),
            },
        )
        return connection_id

    async def disconnect(self, connection_id: str) -> None:
        """Tear down a connection and clean up all associated state.

        Cancels the heartbeat task, removes the connection from the registry
        and the per-account index, and closes the WebSocket if still open.

        This method is idempotent — calling it for an unknown ``connection_id``
        is a no-op.

        Args:
            connection_id: The ID returned by :meth:`connect`.
        """
        async with self._lock:
            conn = self._connections.pop(connection_id, None)
            if conn is None:
                return

            account_connections = self._account_index.get(conn.account_id, set())
            account_connections.discard(connection_id)
            if not account_connections:
                self._account_index.pop(conn.account_id, None)

        # Cancel heartbeat outside the lock to avoid deadlock
        if conn.heartbeat_task is not None and not conn.heartbeat_task.done():
            conn.heartbeat_task.cancel()
            try:
                await conn.heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass

        # Close the WebSocket if still open
        if conn.websocket.client_state == WebSocketState.CONNECTED:
            try:
                await conn.websocket.close(code=_WS_CLOSE_NORMAL)
            except Exception:  # noqa: BLE001
                pass

        logger.info(
            "ws.disconnected",
            extra={
                "connection_id": connection_id,
                "account_id": str(conn.account_id),
                "subscriptions": list(conn.subscriptions),
                "total_connections": len(self._connections),
            },
        )

    async def disconnect_all(self) -> None:
        """Disconnect every active connection.

        Called during application shutdown to cleanly close all WebSocket
        connections before the event loop stops.
        """
        async with self._lock:
            ids = list(self._connections.keys())

        for connection_id in ids:
            await self.disconnect(connection_id)

        logger.info("ws.all_disconnected", extra={"count": len(ids)})

    # ------------------------------------------------------------------
    # Public: broadcasting
    # ------------------------------------------------------------------

    async def broadcast_to_account(
        self,
        account_id: UUID,
        payload: dict[str, Any],
    ) -> int:
        """Send *payload* to all connections belonging to *account_id*.

        Used for per-account events such as order status changes and portfolio
        snapshots.

        Args:
            account_id: The account whose connections should receive the message.
            payload:    A JSON-serialisable dict.

        Returns:
            The number of connections the message was successfully sent to.
        """
        async with self._lock:
            ids = set(self._account_index.get(account_id, set()))

        sent = 0
        for connection_id in ids:
            if await self._send(connection_id, payload):
                sent += 1
        return sent

    async def broadcast_to_channel(
        self,
        channel: str,
        payload: dict[str, Any],
    ) -> int:
        """Send *payload* to all connections subscribed to *channel*.

        Used by the Redis pub/sub listener to forward price ticks to clients
        subscribed to ``ticker:{symbol}`` or ``ticker:all`` channels.

        Args:
            channel: Full channel name (e.g. ``"ticker:BTCUSDT"``).
            payload: A JSON-serialisable dict.

        Returns:
            The number of connections the message was successfully sent to.
        """
        async with self._lock:
            targets = [
                conn_id
                for conn_id, conn in self._connections.items()
                if channel in conn.subscriptions
            ]

        sent = 0
        for connection_id in targets:
            if await self._send(connection_id, payload):
                sent += 1
        return sent

    # ------------------------------------------------------------------
    # Public: subscription management (called by handlers)
    # ------------------------------------------------------------------

    async def subscribe(self, connection_id: str, channel: str) -> bool:
        """Subscribe *connection_id* to *channel*.

        Args:
            connection_id: The target connection.
            channel:       Full channel name.

        Returns:
            ``True`` on success, ``False`` if the subscription cap was reached.
        """
        async with self._lock:
            conn = self._connections.get(connection_id)
            if conn is None:
                return False
            return conn.add_subscription(channel)

    async def unsubscribe(self, connection_id: str, channel: str) -> None:
        """Unsubscribe *connection_id* from *channel*.

        Args:
            connection_id: The target connection.
            channel:       Full channel name to remove.
        """
        async with self._lock:
            conn = self._connections.get(connection_id)
            if conn is None:
                return
            conn.remove_subscription(channel)

    def get_subscriptions(self, connection_id: str) -> set[str]:
        """Return a snapshot of the current subscription set.

        Args:
            connection_id: The target connection.

        Returns:
            Frozen copy of the subscription set, or empty set if unknown.
        """
        conn = self._connections.get(connection_id)
        if conn is None:
            return set()
        return set(conn.subscriptions)

    def get_connection(self, connection_id: str) -> Connection | None:
        """Return the :class:`Connection` for *connection_id*, or ``None``.

        Args:
            connection_id: The ID returned by :meth:`connect`.

        Returns:
            The :class:`Connection` instance, or ``None`` if not registered.
        """
        return self._connections.get(connection_id)

    # ------------------------------------------------------------------
    # Public: pong handler (called by message handler on incoming pong)
    # ------------------------------------------------------------------

    def notify_pong(self, connection_id: str) -> None:
        """Signal the heartbeat loop that a pong was received.

        The message handler calls this when it sees ``{"type": "pong"}`` from
        a client.  The heartbeat loop is waiting on the internal event and will
        proceed normally on receiving this signal.

        Args:
            connection_id: The connection that sent the pong.
        """
        conn = self._connections.get(connection_id)
        if conn is not None:
            conn.notify_pong()

    # ------------------------------------------------------------------
    # Public: introspection
    # ------------------------------------------------------------------

    @property
    def active_count(self) -> int:
        """Total number of currently active connections."""
        return len(self._connections)

    def account_connection_ids(self, account_id: UUID) -> set[str]:
        """Return all ``connection_id`` values for *account_id*.

        Args:
            account_id: The account to look up.

        Returns:
            Set of connection IDs; empty set if the account has no connections.
        """
        return set(self._account_index.get(account_id, set()))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _authenticate(self, api_key: str) -> UUID | None:
        """Validate *api_key* and return the account UUID, or ``None`` on failure.

        A fresh DB session is created per connection attempt so that the
        manager does not depend on FastAPI's per-request DI machinery.

        Args:
            api_key: Raw API key string from the WebSocket query parameter.

        Returns:
            The ``account_id`` UUID on success, or ``None`` if the key is
            invalid, the account is not found, or the account is not active.
        """
        from src.database.session import get_session_factory  # noqa: PLC0415

        if not api_key:
            logger.warning("ws.auth_failed", extra={"reason": "empty api_key"})
            return None

        try:
            session_factory = get_session_factory()
            async with session_factory() as session:
                repo = AccountRepository(session)
                account = await repo.get_by_api_key(api_key)

                if account.status != "active":
                    logger.warning(
                        "ws.auth_failed",
                        extra={"reason": "account_not_active", "account_id": str(account.id)},
                    )
                    return None

                return account.id

        except AccountNotFoundError:
            logger.warning("ws.auth_failed", extra={"reason": "unknown_api_key"})
            return None
        except AuthenticationError as exc:
            logger.warning("ws.auth_failed", extra={"reason": exc.message})
            return None
        except Exception as exc:  # noqa: BLE001
            logger.exception("ws.auth_error", extra={"error": str(exc)})
            return None

    async def _send(self, connection_id: str, payload: dict[str, Any]) -> bool:
        """Send *payload* as JSON to the connection identified by *connection_id*.

        Silently drops the message (and triggers disconnect) if the WebSocket
        is no longer open.

        Args:
            connection_id: The target connection.
            payload:       A JSON-serialisable dict.

        Returns:
            ``True`` if the message was sent successfully, ``False`` otherwise.
        """
        conn = self._connections.get(connection_id)
        if conn is None:
            return False

        try:
            await conn.websocket.send_json(payload)
            return True
        except (WebSocketDisconnect, RuntimeError):
            # Client closed the connection — schedule cleanup outside this call
            asyncio.create_task(self.disconnect(connection_id))
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ws.send_failed",
                extra={"connection_id": connection_id, "error": str(exc)},
            )
            asyncio.create_task(self.disconnect(connection_id))
            return False

    async def _heartbeat_loop(self, connection_id: str) -> None:
        """Ping/pong heartbeat loop for a single connection.

        Every ``_HEARTBEAT_INTERVAL`` seconds, sends ``{"type": "ping"}`` to
        the client and waits up to ``_PONG_TIMEOUT`` seconds for a pong.  If
        the pong does not arrive in time the connection is closed.

        This coroutine runs as a background asyncio task created in
        :meth:`connect` and cancelled in :meth:`disconnect`.

        Args:
            connection_id: The connection to keep alive.
        """
        try:
            while True:
                await asyncio.sleep(_HEARTBEAT_INTERVAL)

                conn = self._connections.get(connection_id)
                if conn is None:
                    return

                # Clear pong event before sending ping so we don't pick up a
                # stale pong from the previous cycle.
                conn._pong_event.clear()

                sent = await self._send(connection_id, {"type": "ping"})
                if not sent:
                    return  # _send already scheduled disconnect

                # Wait for pong within the timeout window
                try:
                    await asyncio.wait_for(
                        asyncio.shield(conn._pong_event.wait()),
                        timeout=_PONG_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "ws.heartbeat_timeout",
                        extra={
                            "connection_id": connection_id,
                            "account_id": str(conn.account_id),
                        },
                    )
                    asyncio.create_task(self.disconnect(connection_id))
                    return

        except asyncio.CancelledError:
            # Normal cancellation — suppress and exit cleanly
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "ws.heartbeat_error",
                extra={"connection_id": connection_id, "error": str(exc)},
            )
            asyncio.create_task(self.disconnect(connection_id))
