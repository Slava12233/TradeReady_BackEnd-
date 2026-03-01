---
name: binance-websocket-integration
description: |
  Teaches the agent how to connect to Binance WebSocket streams, ingest tick data,
  buffer and flush to TimescaleDB, and broadcast prices via Redis.
  Use when: adding WebSocket streams, implementing tick ingestion, configuring
  reconnection logic, optimizing bulk inserts, or working with Binance WS in this project.
---

# Binance WebSocket Integration

## Stream Configuration

- **Combined Stream URL**: `wss://stream.binance.com:9443/stream?streams=btcusdt@trade/ethusdt@trade/...`
- **Max streams per connection**: 1024. Use multiple connections if >1024 pairs.
- **Fetch USDT pairs**: `GET https://api.binance.com/api/v3/exchangeInfo`, filter `status="TRADING"` and `quoteAsset="USDT"`.

## Tick Data Fields

| Field | Meaning |
|-------|---------|
| `s` | symbol |
| `p` | price |
| `q` | quantity |
| `T` | trade time (ms) |
| `m` | is_buyer_maker |
| `t` | trade ID |

## Implementation Stack

- Use `asyncio` + `websockets` library.
- **Files**: `src/price_ingestion/binance_ws.py`, `service.py`, `tick_buffer.py`, `broadcaster.py`.

## Reconnection

- Auto-reconnect with exponential backoff: 1s → 2s → 4s → 8s, max 60s.
- On disconnect, flush buffer before reconnecting.

## Tick Buffer

- In-memory list of ticks.
- **Flush triggers**: size >= 5000 **or** 1 second elapsed.
- Use `asyncpg` COPY command for bulk inserts.
- **Graceful shutdown**: flush remaining buffer before exit.

## Health Monitoring

- Alert if any pair has no tick for 60 seconds.
- Track last-tick timestamp per symbol.

## Performance

- **Target**: 10,000+ ticks/second.
- Prefer bulk COPY over row-by-row inserts.

## Price Broadcaster

- Redis pub/sub channel: `price_updates`.
- Publish tick or aggregated price updates to this channel for downstream consumers.

## Checklist

1. Build stream URL from USDT pairs (max 1024 per connection).
2. Parse tick JSON and extract `s`, `p`, `q`, `T`, `m`, `t`.
3. Append to buffer; flush on size or time threshold.
4. Use asyncpg COPY for bulk insert into TimescaleDB.
5. Publish to Redis `price_updates`.
6. Implement exponential backoff reconnection.
7. Implement 60s no-tick health check.
8. Flush buffer on shutdown.

## References

- For detailed Binance WebSocket field reference, see [references/binance-fields.md](references/binance-fields.md)
