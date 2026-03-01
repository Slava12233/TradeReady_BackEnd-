# Binance WebSocket Field Reference

This document describes the Binance WebSocket stream format and field reference for the AiTradingAgent platform.

---

## Combined Stream URL

```
wss://stream.binance.com:9443/stream?streams=btcusdt@trade/ethusdt@trade/...
```

Max 1024 streams per connection. For >1024 pairs, open additional connections.

---

## Stream Name Format

`{symbol_lowercase}@trade` — e.g., `btcusdt@trade`, `ethusdt@trade`

---

## Incoming Message Format

**Wrapper:**

```json
{"stream": "btcusdt@trade", "data": {...}}
```

**Trade event** (data field):

```json
{
  "e": "trade",
  "E": 1672000000000,
  "s": "BTCUSDT",
  "t": 123456789,
  "p": "64521.30000000",
  "q": "0.01200000",
  "b": 88888888,
  "a": 88888889,
  "T": 1672000000000,
  "m": false,
  "M": true
}
```

---

## Field Reference

| Field | Type | Description |
|-------|------|-------------|
| e | string | Event type ("trade") |
| E | int | Event time (ms epoch) |
| s | string | Symbol (e.g. "BTCUSDT") |
| t | int | Trade ID |
| p | string | Price |
| q | string | Quantity |
| b | int | Buyer order ID |
| a | int | Seller order ID |
| T | int | Trade time (ms epoch) |
| m | bool | Is buyer the maker? |
| M | bool | Ignore (internal) |

---

## Fields We Extract

Only these fields are stored in our Tick model:

| Binance Field | Tick Model Field | Notes |
|---------------|------------------|-------|
| s | symbol | str |
| p | price | Decimal |
| q | quantity | Decimal |
| T | timestamp | datetime, converted from ms epoch |
| m | is_buyer_maker | bool |
| t | trade_id | int |

---

## Fetching Trading Pairs

```
GET https://api.binance.com/api/v3/exchangeInfo
```

- **Filter**: `symbols[].status == "TRADING"` AND `symbols[].quoteAsset == "USDT"`
- **Extract**: `symbols[].symbol` (lowercase for stream name)

---

## Connection Limits

| Limit | Value |
|-------|-------|
| Max streams per WebSocket connection | 1024 |
| Max messages per second per connection | 5 |
| Connection lifetime | 24 hours (must reconnect) |
| Authentication | None required for public streams |

---

## Reconnection Strategy

- **On disconnect**: flush tick buffer first
- **Backoff**: 1s, 2s, 4s, 8s, 16s, 32s, 60s (max)
- **On reconnect**: re-subscribe to all streams
- **Logging**: log each reconnection attempt with backoff duration
