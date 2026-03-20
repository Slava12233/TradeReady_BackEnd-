# Exchange Abstraction Layer

> CCXT-powered multi-exchange connectivity — the adapter pattern that lets TradeReady talk to 110+ exchanges through one interface.

<!-- last-updated: 2026-03-19 -->

## What This Module Does

Provides a clean abstraction over exchange connectivity so the rest of the platform never imports CCXT directly. All exchange operations — fetching markets, streaming trades, pulling OHLCV candles, placing orders — go through the `ExchangeAdapter` interface. The current implementation (`CCXTAdapter`) wraps CCXT, but the adapter pattern means CCXT can be replaced without changing any consumer code.

## Key Files

| File | Purpose |
|------|---------|
| `adapter.py` | `ExchangeAdapter` — abstract base class defining the universal exchange interface |
| `ccxt_adapter.py` | `CCXTAdapter` — CCXT-based implementation of `ExchangeAdapter` |
| `types.py` | `ExchangeTick`, `ExchangeCandle`, `ExchangeMarket` — canonical data types returned by adapters |
| `symbol_mapper.py` | `SymbolMapper` — bidirectional translation between `BTCUSDT` (platform) and `BTC/USDT` (CCXT) |
| `factory.py` | `create_adapter()` — factory function that reads config and builds adapters |
| `__init__.py` | Re-exports all public symbols |

## Architecture & Patterns

### Adapter Pattern

```
Consumer code (ingestion, backfill, order engine)
        │
        ▼
  ExchangeAdapter (ABC)     ← depends on this interface only
        │
        ▼
  CCXTAdapter               ← CCXT-specific implementation
        │
        ▼
  ccxt.async_support / ccxt.pro
```

No module outside `src/exchange/` should ever import `ccxt` directly.

### Symbol Translation

Platform uses `BTCUSDT` (concatenated, uppercase). CCXT uses `BTC/USDT` (slash-separated).

`SymbolMapper` handles bidirectional conversion:
- **With market data** (preferred): `load_markets()` builds exact lookup tables from CCXT's market definitions.
- **Heuristic fallback**: Strips known quote assets (`USDT`, `BUSD`, `BTC`, `ETH`, `BNB`) when market data unavailable.

### Initialization

`CCXTAdapter` is lazy — no CCXT objects are created until `initialize()` is called. This keeps imports fast and lets tests create adapters without network calls.

```python
adapter = CCXTAdapter("binance")
await adapter.initialize()   # loads markets, builds symbol maps
# ... use adapter ...
await adapter.close()        # cleanup
```

### Builder Fee

CCXT has an optional 0.01% builder fee on some exchanges. The adapter disables it automatically:
```python
exchange.options["builderFee"] = False
```

## Public API

### `ExchangeAdapter` (abstract)
- `fetch_markets(quote_asset="USDT") -> list[ExchangeMarket]`
- `fetch_ticker(symbol) -> dict`
- `fetch_ohlcv(symbol, timeframe, since, limit) -> list[ExchangeCandle]`
- `fetch_order_book(symbol, limit) -> dict`
- `fetch_trades(symbol, limit) -> list[ExchangeTick]`
- `watch_trades(symbols) -> AsyncGenerator[ExchangeTick]`
- `create_order(symbol, type, side, amount, price) -> dict`
- `cancel_order(order_id, symbol) -> dict`
- `fetch_balance() -> dict[str, Decimal]`
- `close() -> None`
- `exchange_id: str` (property)
- `has_websocket: bool` (property)

### `CCXTAdapter(exchange_id, config=None)`
Implements `ExchangeAdapter`. Additional:
- `initialize() -> None` — must be called before use
- `mapper: SymbolMapper` (property)

### `create_adapter(exchange_id=None, api_key=None, secret=None) -> CCXTAdapter`
Factory that reads from `src.config.Settings`.

### `get_additional_exchange_ids() -> list[str]`
Parses `settings.additional_exchanges` comma-separated string.

## Dependencies

| Dependency | Purpose |
|------------|---------|
| `ccxt` (async_support) | REST exchange operations |
| `ccxt` (pro) | WebSocket streaming |
| `structlog` | Logging |
| `src.config` | Settings (lazy import in factory) |

## Configuration (`src/config.py`)

| Setting | Default | Purpose |
|---------|---------|---------|
| `exchange_id` | `"binance"` | Primary exchange for CCXT |
| `exchange_api_key` | `None` | API key (Phase 8 live trading) |
| `exchange_secret` | `None` | API secret (Phase 8 live trading) |
| `additional_exchanges` | `""` | Comma-separated extra exchange IDs |

## Gotchas

- **Always call `initialize()` before using any fetch/watch method** — raises `RuntimeError` otherwise.
- **Symbol mapping requires market data** — call `initialize()` to load accurate mappings. The heuristic fallback works for 99% of pairs but may fail for exotic ones.
- **CCXT Pro WebSocket is a separate import** — `ccxt.pro` vs `ccxt.async_support`. The adapter handles this internally.
- **`watch_trades()` blocks in a loop** — it's an async generator that yields forever. Cancel the consuming task to stop it.
- **`fetch_ohlcv` doesn't return trade count** — CCXT's unified OHLCV format is `[timestamp, O, H, L, C, V]` with no trade count. The field is set to `0`.
- **Float conversion for orders** — CCXT's `create_order()` expects floats, not Decimals. The adapter converts internally.

## Recent Changes

- `2026-03-18` — Module created with ExchangeAdapter ABC, CCXTAdapter, SymbolMapper, factory
