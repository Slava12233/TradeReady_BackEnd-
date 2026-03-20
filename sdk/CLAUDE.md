# AgentExchange Python SDK

<!-- last-updated: 2026-03-19 -->

> Universal Python client library for the AgentExchange AI crypto trading platform -- sync, async, and WebSocket.

## What This Module Does

The SDK provides three client classes that wrap the platform's REST and WebSocket APIs. It handles JWT authentication (auto-login via API key + secret, transparent token refresh), exponential-backoff retry on 5xx errors and transport failures, and deserialization of all responses into frozen dataclass models with `Decimal` precision. AI agents use this SDK to trade, fetch market data, monitor portfolios, and stream real-time prices without touching raw HTTP.

## Key Files

| File | Purpose |
|------|---------|
| `agentexchange/__init__.py` | Package root; re-exports all 3 clients, 13 models, 9 exceptions; defines `__version__` |
| `agentexchange/client.py` | `AgentExchangeClient` -- synchronous REST client (httpx, 37 methods) |
| `agentexchange/async_client.py` | `AsyncAgentExchangeClient` -- async REST client (httpx async, 37 methods) |
| `agentexchange/ws_client.py` | `AgentExchangeWS` -- WebSocket client (websockets lib, decorator-based subscriptions) |
| `agentexchange/models.py` | 13 frozen dataclasses: `Price`, `Ticker`, `Candle`, `Balance`, `Position`, `Portfolio`, `PnL`, `Order`, `Trade`, `Performance`, `Snapshot`, `LeaderboardEntry`, `AccountInfo` |
| `agentexchange/exceptions.py` | Exception hierarchy (10 classes) + `raise_for_response()` factory |
| `agentexchange/py.typed` | PEP 561 marker for type-checker discovery |
| `pyproject.toml` | Package config: Python 3.12+, deps `httpx>=0.28` + `websockets>=14.0`, MIT license |
| `README.md` | Usage examples and installation instructions |

## Architecture & Patterns

### Client Design

Both REST clients (`AgentExchangeClient` and `AsyncAgentExchangeClient`) share an identical public API surface of 37 methods organized into 7 groups:

- **Market data** (6): `get_price`, `get_all_prices`, `get_candles`, `get_ticker`, `get_recent_trades`, `get_orderbook`
- **Trading** (9): `place_market_order`, `place_limit_order`, `place_stop_loss`, `place_take_profit`, `get_order`, `get_open_orders`, `cancel_order`, `cancel_all_orders`, `get_trade_history`
- **Account** (6): `get_account_info`, `get_balance`, `get_positions`, `get_portfolio`, `get_pnl`, `reset_account`
- **Analytics** (3): `get_performance`, `get_portfolio_history`, `get_leaderboard`
- **Strategies** (6): `create_strategy`, `get_strategies`, `get_strategy`, `create_version`, `deploy_strategy`, `undeploy_strategy`
- **Strategy Testing** (4): `run_test`, `get_test_status`, `get_test_results`, `compare_versions`
- **Training** (3): `get_training_runs`, `get_training_run`, `compare_training_runs`

### Authentication Flow

1. Constructor stores `api_key` + `api_secret` and sets the `X-API-Key` header on the httpx client
2. On first request, `_ensure_auth()` calls `_login()` which POSTs to `/api/v1/auth/login` to exchange credentials for a JWT
3. JWT is cached with a 30-second safety buffer before expiry; auto-refreshed when expired
4. All subsequent requests use `Authorization: Bearer <jwt>` header

### Retry & Error Handling

- 5xx responses and `httpx.TransportError` are retried up to 3 times with exponential backoff (1s, 2s, 4s)
- Non-2xx responses are parsed through `raise_for_response()` which maps API error codes (e.g., `INSUFFICIENT_BALANCE`) to typed exceptions
- Fallback mapping by HTTP status code when no API error code is present

### WebSocket Client

`AgentExchangeWS` uses a decorator pattern for channel subscriptions:

- `@ws.on_ticker(symbol)` -- price updates (supports `"all"` wildcard)
- `@ws.on_candles(symbol, interval)` -- OHLCV candle updates
- `@ws.on_order_update()` -- order status changes
- `@ws.on_portfolio()` -- portfolio snapshots

Connection management: auto-reconnect with exponential backoff (1s to 60s cap), heartbeat monitoring (40s idle timeout closes stale connections), and `AuthenticationError` stops reconnection permanently.

### Models

All 13 response models are frozen dataclasses with:
- `Decimal` for all monetary/price fields (never `float`)
- `from_dict(data)` classmethod for deserialization from JSON dicts
- Internal helpers: `_decimal()`, `_decimal_opt()`, `_dt()`, `_dt_opt()`, `_uuid()`, `_uuid_opt()`

### Exception Hierarchy

```
AgentExchangeError (base)
  +-- AuthenticationError      (401/403)
  +-- RateLimitError           (429, has retry_after)
  +-- InsufficientBalanceError (400, has asset/required/available)
  +-- OrderError               (400/404)
  +-- InvalidSymbolError       (400/503, has symbol)
  +-- NotFoundError            (404)
  +-- ValidationError          (422, has field)
  +-- ConflictError            (409)
  +-- ServerError              (500/503)
  +-- ConnectionError          (transport-level, status_code=0)
```

`_CODE_TO_EXCEPTION` dict maps 20+ API error codes to exception classes. `_STATUS_TO_EXCEPTION` provides HTTP-status fallbacks.

## Public API / Interfaces

### Sync Client

```python
from agentexchange import AgentExchangeClient

with AgentExchangeClient(api_key="ak_live_...", api_secret="sk_live_...") as client:
    price = client.get_price("BTCUSDT")
    order = client.place_market_order("BTCUSDT", "buy", Decimal("0.001"))
    balance = client.get_balance()
```

### Async Client

```python
from agentexchange import AsyncAgentExchangeClient

async with AsyncAgentExchangeClient(api_key="ak_live_...", api_secret="sk_live_...") as client:
    price = await client.get_price("BTCUSDT")
    order = await client.place_market_order("BTCUSDT", "buy", Decimal("0.001"))
```

### WebSocket Client

```python
from agentexchange import AgentExchangeWS

ws = AgentExchangeWS(api_key="ak_live_...")

@ws.on_ticker("BTCUSDT")
async def handle(data):
    print(data["price"])

await ws.connect()  # blocks with auto-reconnect
```

### Constructor Parameters (all 3 clients)

| Param | Default | Notes |
|-------|---------|-------|
| `api_key` | required | `ak_live_...` format |
| `api_secret` | required (REST only) | `sk_live_...` format |
| `base_url` | `http://localhost:8000` (REST) / `ws://localhost:8000` (WS) | Platform URL |
| `timeout` | `30.0` (REST only) | HTTP timeout in seconds |

## Common Tasks

### Install the SDK locally
```bash
pip install -e sdk/
```

### Run SDK tests
```bash
cd sdk && pytest
```

### Run linting and type checking
```bash
cd sdk && ruff check . && mypy agentexchange/
```

### Add a new REST method
1. Add the method to `AgentExchangeClient` in `client.py`
2. Add the identical `async` version to `AsyncAgentExchangeClient` in `async_client.py`
3. If the response needs a new model, add a frozen dataclass to `models.py` with `from_dict()`
4. Export the new model from `__init__.py` and add to `__all__`

### Add a new WebSocket channel
1. Add a decorator method (e.g., `on_<channel>()`) in `ws_client.py`
2. Update `_dispatch()` to route the message type to the correct channel string
3. Update `_message_loop()` if the server uses a new message type

### Add a new exception type
1. Define the class inheriting from `AgentExchangeError` in `exceptions.py`
2. Add its API error codes to `_CODE_TO_EXCEPTION`
3. Add HTTP status mapping to `_STATUS_TO_EXCEPTION` if needed
4. Export from `__init__.py`

## Gotchas & Pitfalls

- **Sync and async clients must stay in sync.** Every public method on `AgentExchangeClient` must have an identical `async` counterpart on `AsyncAgentExchangeClient`. They share no base class; the duplication is intentional to avoid runtime complexity.
- **`_clean_params()` is duplicated** in both `client.py` and `async_client.py` as a module-level function. Changes must be applied to both files.
- **`ConnectionError` shadows the builtin.** The SDK defines its own `ConnectionError` that inherits from `AgentExchangeError`. Import it explicitly from `agentexchange.exceptions` to avoid confusion with Python's builtin `ConnectionError`.
- **All monetary values are `Decimal`, never `float`.** The `place_*` methods accept `Decimal | float | str` for convenience but convert to `Decimal` internally via `str()` coercion to avoid float precision loss.
- **`Order.from_dict()` handles two response shapes.** The platform returns different key names from placement vs. detail endpoints (`executed_quantity` vs `executed_qty`, `quantity` vs `requested_quantity`). The `from_dict` method normalizes both.
- **WebSocket heartbeat is asymmetric.** The server sends `{"type": "ping"}` as application-level JSON messages (not WebSocket protocol pings). The client responds with `{"type": "pong"}`. The `_heartbeat_loop` closes the connection after 40s of silence as a stale-connection guard.
- **No SDK tests exist in-tree yet.** The `pyproject.toml` references a `tests/` directory with `respx` for mocking, but no test files are present in the repository.
- **`get_settings()` LRU cache** in the main platform can interfere with SDK integration tests -- patch it before the cached instance is created.

## Recent Changes

- `2026-03-17` -- Initial CLAUDE.md created
- `2026-03-18` -- Fixed model count: 12 -> 13 frozen dataclasses (AccountInfo was undercounted)
- `2026-03-19` -- Synced with codebase: confirmed 6 Python files and all documented items exist. No changes needed.
