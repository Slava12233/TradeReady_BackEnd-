---
name: websocket-server
description: |
  Teaches the agent how to build the FastAPI WebSocket server for the AiTradingAgent platform.
  Use when: adding WebSocket endpoints, channels, connection lifecycle; implementing subscribe/
  unsubscribe; bridging Redis pub/sub to WebSocket; or working with src/api/websocket/ in this project.
---

# WebSocket Server

## Endpoint

- Path: `/ws/v1`
- Query param: `api_key={key}` (required)
- Auth: validate API key on connection; reject with 401 if invalid.

## Implementation Layout

| Purpose | Path |
|---------|------|
| Connection lifecycle | `src/api/websocket/manager.py` |
| Subscribe/unsubscribe | `src/api/websocket/handlers.py` |
| Channel definitions | `src/api/websocket/channels.py` |

## Channels

| Channel | Format | Description |
|---------|--------|-------------|
| Ticker (single) | `ticker:{symbol}` | Price updates for one symbol |
| Ticker (all) | `ticker:all` | All symbols |
| Candles | `candles:{symbol}:{interval}` | OHLCV candles |
| Orders | `orders` | Order status updates |
| Portfolio | `portfolio` | Account portfolio snapshot |

## Client Messages

```json
{"action": "subscribe", "channel": "ticker:all"}
{"action": "subscribe", "channel": "ticker:BTCUSDT"}
{"action": "subscribe", "channel": "candles:BTCUSDT:1m"}
{"action": "subscribe", "channel": "orders"}
{"action": "subscribe", "channel": "portfolio"}
{"action": "unsubscribe", "channel": "ticker:BTCUSDT"}
```

- `action`: `subscribe` or `unsubscribe`
- `channel`: full channel name
- `symbol`: optional, used for symbol-specific channels

## Server Push Format

- JSON messages, channel-specific payloads.
- Example ticker: `{"type": "ticker", "symbol": "BTCUSDT", "price": "50000", "timestamp": "..."}`

## Subscription Limits

- Max 10 subscriptions per connection.
- Reject subscribe if limit exceeded; return error message.

## Heartbeat

- Server sends `{"type": "ping"}` every 30 seconds.
- Client must respond with `{"type": "pong"}` within 10 seconds.
- Disconnect if no pong within timeout.

## Data Sources

| Channel | Source |
|---------|--------|
| Ticker | Redis pub/sub `price_updates` |
| Orders | Order status change events |
| Portfolio | Periodic snapshot every 5 seconds for subscribed clients |

- Bridge Redis `price_updates` to WebSocket clients subscribed to ticker channels.
- Push order notifications when order status changes (filled, cancelled, etc.).
- Portfolio: aggregate positions/balances; push every 5s to clients subscribed to `portfolio`.

## Connection Lifecycle

1. Accept connection, validate `api_key`.
2. On success: add to connection manager, start heartbeat task.
3. On invalid key: close with 401.
4. Handle subscribe/unsubscribe messages.
5. Forward channel data from Redis/events to subscribed clients.
6. On disconnect: remove from manager, cancel tasks.

## Conventions

- Use `fastapi.WebSocket` for endpoint.
- Store per-connection state: account_id, subscriptions list.
- Use asyncio tasks for heartbeat and Redis subscription loops.
- Graceful shutdown: close all connections on app shutdown.
