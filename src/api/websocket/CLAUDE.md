# WebSocket Server

<!-- last-updated: 2026-03-19 -->

> Real-time bidirectional communication layer: connection lifecycle, channel-based pub/sub, and Redis-to-WebSocket bridging for live price ticks, order updates, portfolio snapshots, and battle events.

## What This Module Does

Manages all WebSocket connections for the trading platform. Clients connect at `ws://host/ws/v1?api_key=ak_live_...`, authenticate via API key, then subscribe to channels to receive real-time data. The module handles:

- **Authentication** on connect (API key validated against DB, close code 4401 on failure)
- **Channel-based subscriptions** with a per-connection cap of 10
- **Heartbeat** (server pings every 30s, expects pong within 10s, disconnects on timeout)
- **Redis pub/sub bridge** that fans Binance price ticks from the `price_updates` Redis channel out to subscribed WebSocket clients
- **Per-account broadcasting** for private channels (orders, portfolio)
- **Per-channel broadcasting** for public channels (ticker, candles, battle)

## Key Files

| File | Purpose |
|------|---------|
| `channels.py` | Channel definitions (5 channels), wire-format serialization, subscription key resolution |
| `handlers.py` | Message dispatch (subscribe/unsubscribe/pong), `RedisPubSubBridge` singleton, bridge lifecycle |
| `manager.py` | `ConnectionManager` + `Connection` dataclass: auth, registry, heartbeat, broadcast, teardown |
| `__init__.py` | Package docstring only |

## Architecture & Patterns

### Connection Lifecycle

```
Client connects  ->  ws://.../ws/v1?api_key=ak_live_...
Server validates ->  DB lookup via AccountRepository (fresh session per attempt)
Server accepts   ->  WebSocket upgrade, assigns UUID connection_id
Heartbeat starts ->  asyncio background task per connection
Client messages  ->  JSON parsed, dispatched by handlers.handle_message()
Server pushes    ->  broadcast_to_channel() or broadcast_to_account()
Disconnect       ->  heartbeat cancelled, registry cleaned, WebSocket closed
```

### Subscription Model

Clients send JSON messages to subscribe/unsubscribe:

```json
{"action": "subscribe",   "channel": "ticker",    "symbol": "BTCUSDT"}
{"action": "subscribe",   "channel": "ticker_all"}
{"action": "subscribe",   "channel": "candles",   "symbol": "BTCUSDT", "interval": "1m"}
{"action": "subscribe",   "channel": "orders"}
{"action": "subscribe",   "channel": "portfolio"}
{"action": "subscribe",   "channel": "battle",    "battle_id": "uuid-here"}
{"action": "unsubscribe", "channel": "ticker",    "symbol": "BTCUSDT"}
{"action": "pong"}
```

Server responds with:
```json
{"type": "subscribed",   "channel": "ticker:BTCUSDT"}
{"type": "unsubscribed", "channel": "ticker:BTCUSDT"}
{"type": "error",        "code": "...", "message": "..."}
```

Error codes: `UNKNOWN_ACTION`, `INVALID_CHANNEL`, `SUBSCRIPTION_LIMIT`.

### Channel Types

| Channel | Key Format | Type | Broadcast Method |
|---------|-----------|------|-----------------|
| **TickerChannel** | `ticker:{SYMBOL}` or `ticker:all` | Public | `broadcast_to_channel()` |
| **CandleChannel** | `candles:{SYMBOL}:{interval}` | Public | `broadcast_to_channel()` |
| **OrderChannel** | `orders` | Private (per-account) | `broadcast_to_account()` |
| **PortfolioChannel** | `portfolio` | Private (per-account) | `broadcast_to_account()` |
| **BattleChannel** | `battle:{battle_id}` | Public | `broadcast_to_channel()` |

Valid candle intervals: `1m`, `5m`, `1h`, `1d`.

### Redis Pub/Sub Bridge

A singleton `RedisPubSubBridge` (started at app startup, stopped at shutdown) listens on the `price_updates` Redis channel. For each tick it:

1. Deserializes JSON from Redis
2. Builds wire-format envelope via `TickerChannel.serialize()`
3. Broadcasts concurrently to both `ticker:{symbol}` and `ticker:all`

Auto-reconnects on Redis errors with a 2-second delay.

### Internal Data Structures

- `ConnectionManager._connections`: `dict[str, Connection]` keyed by `connection_id`
- `ConnectionManager._account_index`: `dict[UUID, set[str]]` mapping `account_id` to connection IDs (one account can have many tabs)
- All mutations to these dicts are protected by an `asyncio.Lock`

## Public API / Interfaces

### ConnectionManager

```python
await manager.connect(websocket, api_key) -> str | None     # Returns connection_id or None
await manager.disconnect(connection_id) -> None
await manager.disconnect_all() -> None                       # Shutdown hook
await manager.broadcast_to_account(account_id, payload) -> int  # Returns send count
await manager.broadcast_to_channel(channel, payload) -> int     # Returns send count
await manager.subscribe(connection_id, channel) -> bool
await manager.unsubscribe(connection_id, channel) -> None
manager.get_connection(connection_id) -> Connection | None
manager.notify_pong(connection_id) -> None
manager.active_count -> int
```

### Channel Classes

Each channel class provides `channel_name(...)` and `serialize(...)` class methods. `BattleChannel` has three serializers: `serialize_update()`, `serialize_trade()`, `serialize_status()`.

### Bridge Lifecycle (called from `src/main.py`)

```python
from src.api.websocket.handlers import start_redis_bridge, stop_redis_bridge

await start_redis_bridge(redis_client, ws_manager)  # startup
await stop_redis_bridge()                            # shutdown
```

### Message Handler

```python
from src.api.websocket.handlers import handle_message

await handle_message(connection_id, parsed_json, manager)
```

### Channel Resolution

```python
from src.api.websocket.channels import resolve_channel_name

channel_key = resolve_channel_name({"channel": "ticker", "symbol": "BTCUSDT"})
# Returns "ticker:BTCUSDT" or None if invalid
```

## Dependencies

- **Upstream**: `src.database.repositories.account_repo.AccountRepository` (WebSocket auth), `src.database.session.get_session_factory` (fresh session per connect), `src.utils.exceptions` (auth errors)
- **Downstream consumers**: `src.main` (startup/shutdown hooks), `src.price_ingestion.broadcaster` (publishes to `price_updates` Redis channel), route handlers that call `broadcast_to_account()` for order/portfolio events
- **External**: `redis.asyncio` (pub/sub), `fastapi.WebSocket`, `starlette.websockets.WebSocketState`

## Common Tasks

**Adding a new channel**: Create a class in `channels.py` with `channel_name()` and `serialize()` class methods. Add resolution logic to `resolve_channel_name()`. If public, add the prefix to `PUBLIC_CHANNEL_PREFIXES`. If private (per-account), add to `PRIVATE_CHANNELS`.

**Broadcasting from a route handler**:
```python
# Public channel
envelope = TickerChannel.serialize(symbol, data)
await manager.broadcast_to_channel(TickerChannel.channel_name(symbol), envelope)

# Private per-account channel
envelope = OrderChannel.serialize(order_data)
await manager.broadcast_to_account(account_id, envelope)
```

**Testing**: The `ConnectionManager` can be instantiated directly in tests. Mock the `_authenticate` method to bypass DB lookup. The bridge requires a mock Redis client with a `.pubsub()` method.

## Gotchas & Pitfalls

- **Auth creates its own DB session** via `get_session_factory()` (lazy import inside `_authenticate`), not through FastAPI DI. This is intentional since the WebSocket endpoint is outside the normal request lifecycle.
- **Subscription cap is 10** per connection. Re-subscribing to the same channel is idempotent (returns `True`, does not count toward the cap).
- **`_send()` auto-disconnects** on any send failure by scheduling `disconnect()` as a fire-and-forget task. This means a dead connection is cleaned up on the next attempted broadcast rather than waiting for the heartbeat to detect it.
- **Bridge is a module-level singleton** (`_bridge_instance`). `start_redis_bridge()` is idempotent; calling it while already running is a no-op.
- **Heartbeat clears the pong event before sending ping** to avoid false positives from a stale pong. Uses `asyncio.shield()` so cancellation of the wait does not cancel the event itself.
- **`ticker:all`** receives every symbol's ticks on a single channel -- high throughput. Clients that only need one pair should use `ticker:{SYMBOL}` instead.
- **All Decimal values are serialized as strings** in wire format (via `_str_decimal`) to avoid floating-point precision loss.
- **Timestamps** are normalized to ISO-8601 UTC strings ending in `Z`, regardless of whether the input is a datetime, millisecond epoch, or string.

## Recent Changes

- `2026-03-17` -- Initial CLAUDE.md created
