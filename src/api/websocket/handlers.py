"""WebSocket message handler and Redis pub/sub bridge.

Responsibilities
----------------
1. ``handle_message()`` — parse incoming client JSON and dispatch to
   subscribe/unsubscribe/pong logic.  Every message must carry an
   ``"action"`` field; unknown actions receive an ``"error"`` response.

2. ``RedisPubSubBridge`` — a long-running asyncio task per connection that:

   * Subscribes to the ``price_updates`` Redis pub/sub channel.
   * Deserialises each published tick.
   * Resolves the matching WebSocket channels (``ticker:{symbol}`` and
     ``ticker:all``).
   * Fans the serialised envelope out to all subscribed connections via
     :class:`~src.api.websocket.manager.ConnectionManager`.

   A single bridge instance is shared across all connections (started once
   at application startup), so Redis delivers one copy of each tick
   regardless of how many clients are connected.

3. ``start_redis_bridge()`` / ``stop_redis_bridge()`` — lifecycle helpers
   called from ``src/main.py`` startup/shutdown hooks to manage the
   shared :class:`RedisPubSubBridge` task.

Message protocol
----------------
Client → Server::

    {"action": "subscribe",   "channel": "ticker",  "symbol": "BTCUSDT"}
    {"action": "subscribe",   "channel": "ticker_all"}
    {"action": "subscribe",   "channel": "candles",  "symbol": "BTCUSDT", "interval": "1m"}
    {"action": "subscribe",   "channel": "orders"}
    {"action": "subscribe",   "channel": "portfolio"}
    {"action": "unsubscribe", "channel": "ticker",   "symbol": "BTCUSDT"}
    {"action": "pong"}

Server → Client (success)::

    {"type": "subscribed",   "channel": "ticker:BTCUSDT"}
    {"type": "unsubscribed", "channel": "ticker:BTCUSDT"}
    {"type": "error",        "code": "...", "message": "..."}

Subscription cap
----------------
Each connection may hold at most 10 concurrent subscriptions
(enforced by :class:`~src.api.websocket.manager.Connection`).  Attempting
to add an 11th returns an ``"error"`` response.

Example — wiring in main.py::

    from src.api.websocket.handlers import start_redis_bridge, stop_redis_bridge

    @app.on_event("startup")
    async def startup():
        redis = get_redis_client()
        await start_redis_bridge(redis, app.state.ws_manager)

    @app.on_event("shutdown")
    async def shutdown():
        await stop_redis_bridge()
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis

from src.api.websocket.channels import (
    TickerChannel,
    resolve_channel_name,
)

if TYPE_CHECKING:
    from src.api.websocket.manager import ConnectionManager

logger = logging.getLogger(__name__)

# Redis pub/sub channel that the price ingestion broadcaster publishes to.
_PRICE_UPDATES_CHANNEL: str = "price_updates"

# How long (seconds) to sleep before reconnecting after a Redis pubsub error.
_RECONNECT_DELAY: float = 2.0

# ---------------------------------------------------------------------------
# Shared bridge singleton
# ---------------------------------------------------------------------------

_bridge_instance: RedisPubSubBridge | None = None


async def start_redis_bridge(
    redis: aioredis.Redis,  # type: ignore[type-arg]
    manager: ConnectionManager,
) -> None:
    """Start the shared Redis pub/sub → WebSocket bridge.

    Should be called once during application startup.  Subsequent calls
    while the bridge is already running are no-ops.

    Args:
        redis:   Connected async Redis client.
        manager: The application-level :class:`ConnectionManager`.
    """
    global _bridge_instance  # noqa: PLW0603
    if _bridge_instance is not None and _bridge_instance.is_running:
        logger.debug("ws.bridge already running — skipping start")
        return

    _bridge_instance = RedisPubSubBridge(redis, manager)
    await _bridge_instance.start()
    logger.info("ws.bridge started")


async def stop_redis_bridge() -> None:
    """Stop the shared Redis pub/sub bridge.

    Should be called during application shutdown.  Safe to call even if
    the bridge was never started.
    """
    global _bridge_instance  # noqa: PLW0603
    if _bridge_instance is not None:
        await _bridge_instance.stop()
        _bridge_instance = None
        logger.info("ws.bridge stopped")


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------


async def handle_message(
    connection_id: str,
    payload: dict[str, Any],
    manager: ConnectionManager,
) -> None:
    """Dispatch an incoming client message to the appropriate handler.

    Supported actions:

    * ``"subscribe"``   — add a channel subscription (capped at 10).
    * ``"unsubscribe"`` — remove a channel subscription.
    * ``"pong"``        — respond to a server heartbeat ping.

    Unknown actions or malformed payloads produce a structured error
    response sent back to the client.

    Args:
        connection_id: The ID of the connection that sent the message.
        payload:       The parsed JSON dict from the client.
        manager:       The shared :class:`ConnectionManager`.
    """
    action = payload.get("action", "")

    if action == "pong":
        manager.notify_pong(connection_id)
        return

    if action == "subscribe":
        await _handle_subscribe(connection_id, payload, manager)
        return

    if action == "unsubscribe":
        await _handle_unsubscribe(connection_id, payload, manager)
        return

    # Unknown action
    await _send_error(
        connection_id,
        manager,
        code="UNKNOWN_ACTION",
        message=f"Unknown action {action!r}. Valid actions: subscribe, unsubscribe, pong.",
    )


# ---------------------------------------------------------------------------
# Subscribe / unsubscribe helpers
# ---------------------------------------------------------------------------


async def _handle_subscribe(
    connection_id: str,
    payload: dict[str, Any],
    manager: ConnectionManager,
) -> None:
    """Process a subscribe request from a client.

    Resolves the full channel name from the payload, calls
    :meth:`~ConnectionManager.subscribe`, and sends a confirmation or
    error back to the client.

    Args:
        connection_id: The source connection ID.
        payload:       The raw client message dict.
        manager:       The shared :class:`ConnectionManager`.
    """
    channel = resolve_channel_name(payload)

    if channel is None:
        await _send_error(
            connection_id,
            manager,
            code="INVALID_CHANNEL",
            message=_describe_invalid_channel(payload),
        )
        return

    added = await manager.subscribe(connection_id, channel)

    if not added:
        await _send_error(
            connection_id,
            manager,
            code="SUBSCRIPTION_LIMIT",
            message="Maximum of 10 subscriptions per connection reached.",
        )
        return

    await _send_response(
        connection_id,
        manager,
        {"type": "subscribed", "channel": channel},
    )
    logger.debug(
        "ws.subscribed",
        extra={"connection_id": connection_id, "channel": channel},
    )


async def _handle_unsubscribe(
    connection_id: str,
    payload: dict[str, Any],
    manager: ConnectionManager,
) -> None:
    """Process an unsubscribe request from a client.

    Args:
        connection_id: The source connection ID.
        payload:       The raw client message dict.
        manager:       The shared :class:`ConnectionManager`.
    """
    channel = resolve_channel_name(payload)

    if channel is None:
        await _send_error(
            connection_id,
            manager,
            code="INVALID_CHANNEL",
            message=_describe_invalid_channel(payload),
        )
        return

    await manager.unsubscribe(connection_id, channel)
    await _send_response(
        connection_id,
        manager,
        {"type": "unsubscribed", "channel": channel},
    )
    logger.debug(
        "ws.unsubscribed",
        extra={"connection_id": connection_id, "channel": channel},
    )


# ---------------------------------------------------------------------------
# Outbound helpers
# ---------------------------------------------------------------------------


async def _send_response(
    connection_id: str,
    manager: ConnectionManager,
    payload: dict[str, Any],
) -> None:
    """Send a direct response to a single connection.

    Args:
        connection_id: The target connection.
        manager:       The shared :class:`ConnectionManager`.
        payload:       JSON-serialisable dict to send.
    """
    # _send is private; use the manager's broadcast helper limited to 1 target.
    conn = manager.get_connection(connection_id)
    if conn is None:
        return
    try:
        await conn.websocket.send_json(payload)
    except Exception:  # noqa: BLE001
        pass


async def _send_error(
    connection_id: str,
    manager: ConnectionManager,
    code: str,
    message: str,
) -> None:
    """Send a structured error message to a single connection.

    Args:
        connection_id: The target connection.
        manager:       The shared :class:`ConnectionManager`.
        code:          Short machine-readable error code.
        message:       Human-readable description.
    """
    await _send_response(
        connection_id,
        manager,
        {"type": "error", "code": code, "message": message},
    )


def _describe_invalid_channel(payload: dict[str, Any]) -> str:
    """Produce a human-readable error message for a bad subscribe payload.

    Args:
        payload: The client message that failed resolution.

    Returns:
        A string describing what was wrong and what is valid.
    """
    channel = payload.get("channel", "")
    if not channel:
        return (
            "Missing 'channel' field. "
            "Valid channels: ticker, ticker_all, candles, orders, portfolio."
        )
    if channel in ("ticker",):
        return "Channel 'ticker' requires a non-empty 'symbol' field."
    if channel == "candles":
        missing = []
        if not payload.get("symbol"):
            missing.append("'symbol'")
        if not payload.get("interval"):
            missing.append("'interval' (one of: 1m, 5m, 1h, 1d)")
        return f"Channel 'candles' requires {' and '.join(missing)}."
    return (
        f"Unknown channel {channel!r}. "
        "Valid channels: ticker, ticker_all, candles, orders, portfolio."
    )


# ---------------------------------------------------------------------------
# Redis pub/sub bridge
# ---------------------------------------------------------------------------


class RedisPubSubBridge:
    """Bridges the Redis ``price_updates`` pub/sub channel to WebSocket clients.

    A single long-running asyncio task subscribes to the ``price_updates``
    Redis channel.  For every tick received it:

    1. Deserialises the JSON payload published by
       :class:`~src.price_ingestion.broadcaster.PriceBroadcaster`.
    2. Builds the wire-format envelope via :class:`~src.api.websocket.channels.TickerChannel`.
    3. Fans the envelope out to all connections subscribed to
       ``ticker:{symbol}`` or ``ticker:all`` via
       :meth:`~src.api.websocket.manager.ConnectionManager.broadcast_to_channel`.

    The bridge automatically reconnects with a brief delay on Redis errors
    so that a transient network blip does not permanently silence price
    updates for all connected clients.

    Args:
        redis:   A connected async Redis client.
        manager: The application-level :class:`ConnectionManager`.

    Example::

        bridge = RedisPubSubBridge(redis_client, ws_manager)
        await bridge.start()
        # ... application runs ...
        await bridge.stop()
    """

    def __init__(
        self,
        redis: aioredis.Redis,  # type: ignore[type-arg]
        manager: ConnectionManager,
    ) -> None:
        self._redis = redis
        self._manager = manager
        self._task: asyncio.Task[None] | None = None

    @property
    def is_running(self) -> bool:
        """``True`` when the background listener task is active."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the background pub/sub listener task.

        Idempotent — calling start on an already-running bridge is a no-op.
        """
        if self.is_running:
            return
        self._task = asyncio.create_task(
            self._listen_loop(),
            name="ws-redis-pubsub-bridge",
        )

    async def stop(self) -> None:
        """Cancel the background listener and wait for it to finish.

        Safe to call even if the bridge was never started.
        """
        if self._task is None:
            return
        if not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self._task = None

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _listen_loop(self) -> None:
        """Main pub/sub listener loop with automatic reconnection.

        Runs indefinitely until cancelled.  On any Redis error the loop
        waits ``_RECONNECT_DELAY`` seconds before re-subscribing.
        """
        while True:
            try:
                await self._run_pubsub()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "ws.bridge.redis_error — reconnecting in %.1fs",
                    _RECONNECT_DELAY,
                    extra={"error": str(exc)},
                )
                await asyncio.sleep(_RECONNECT_DELAY)

    async def _run_pubsub(self) -> None:
        """Subscribe to ``price_updates`` and dispatch messages until error.

        Creates a fresh pub/sub object on each call so that reconnection
        gets a clean state.  Exits by raising on any Redis exception,
        which the outer ``_listen_loop`` catches and handles.
        """
        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(_PRICE_UPDATES_CHANNEL)
            logger.info(
                "ws.bridge.subscribed",
                extra={"channel": _PRICE_UPDATES_CHANNEL},
            )
            async for raw_message in pubsub.listen():
                if raw_message["type"] != "message":
                    # Skip subscribe-confirmation and other control messages
                    continue
                await self._dispatch(raw_message["data"])
        finally:
            try:
                await pubsub.unsubscribe(_PRICE_UPDATES_CHANNEL)
                await pubsub.aclose()
            except Exception:  # noqa: BLE001
                pass

    async def _dispatch(self, raw_data: str) -> None:
        """Deserialise a Redis message and fan it out to subscribed clients.

        The ``price_updates`` message format is::

            {
                "symbol": "BTCUSDT",
                "price": "64521.30000000",
                "quantity": "0.01200000",
                "timestamp": 1708000000000,
                "is_buyer_maker": false,
                "trade_id": 123456789
            }

        The handler broadcasts to both ``ticker:{symbol}`` and
        ``ticker:all`` channels so clients subscribed to either variant
        receive every tick.

        Args:
            raw_data: The raw string payload from Redis.
        """
        try:
            tick = json.loads(raw_data)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "ws.bridge.parse_error",
                extra={"error": str(exc), "raw": raw_data[:200]},
            )
            return

        symbol: str = tick.get("symbol", "")
        if not symbol:
            logger.debug("ws.bridge.missing_symbol", extra={"raw": raw_data[:200]})
            return

        envelope = TickerChannel.serialize(symbol, tick)
        per_symbol_channel, all_channel = TickerChannel.channel_names_for_symbol(symbol)

        # Broadcast concurrently to both channel variants
        sent_symbol, sent_all = await asyncio.gather(
            self._manager.broadcast_to_channel(per_symbol_channel, envelope),
            self._manager.broadcast_to_channel(all_channel, envelope),
            return_exceptions=True,
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "ws.bridge.dispatched",
                extra={
                    "symbol": symbol,
                    "sent_symbol": sent_symbol if isinstance(sent_symbol, int) else 0,
                    "sent_all": sent_all if isinstance(sent_all, int) else 0,
                },
            )
