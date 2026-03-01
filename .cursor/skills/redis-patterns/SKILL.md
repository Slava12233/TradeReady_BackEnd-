---
name: redis-patterns
description: |
  Teaches the agent how to use Redis in the AiTradingAgent crypto trading platform.
  Use when: adding caching, rate limiting, circuit breakers; implementing Pub/Sub; or working with Redis in this project.
---

# Redis Patterns

## Stack

- Redis 7+
- Connection pooling (max 50 connections)
- All operations async (`aioredis` / `redis.asyncio`)

## Project Layout

| Purpose | Path |
|---------|------|
| Redis client | `src/cache/redis_client.py` |
| Price cache operations | `src/cache/price_cache.py` |

## Price Cache

- Hash: `prices` — per-pair fields (e.g. `BTCUSDT`, `ETHUSDT`)
- Hash: `prices:meta` — staleness tracking per pair

## Ticker

- Hash: `ticker:{symbol}` — fields: `open`, `high`, `low`, `close`, `volume`, `change_pct`, `last_update`

## Rate Limiting

- Sliding window: `INCR` + `EXPIRE` on key `rate_limit:{api_key}:{endpoint_group}:{minute_bucket}`
- Use minute bucket for window granularity.
- Check limit before increment; return 429 if exceeded.

## Circuit Breaker

- Hash: `circuit_breaker:{account_id}` — fields: `daily_pnl`, `tripped`, `tripped_at`
- Auto-expire at midnight UTC (e.g. TTL to next midnight).
- Check before allowing new trades.

## Pub/Sub

- Channel: `price_updates` — broadcast ticks to WebSocket clients
- Publish on tick; subscribers forward to connected clients.

## Redis Config

- RDB snapshots every 60s + AOF
- Memory policy: `noeviction`
- Typical size: ~50–100 MB for all pairs

## Conventions

- Use `src/cache/redis_client.py` for connection; avoid ad-hoc clients.
- All operations must be async.
- Use connection pooling; reuse connections.
- Set TTL on cache keys to avoid unbounded growth.
- Use pipeline for atomic multi-key operations.
