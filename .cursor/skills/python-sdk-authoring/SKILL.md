---
name: python-sdk-authoring
description: |
  Teaches the agent how to build the Python SDK package for the AiTradingAgent platform.
  Use when: adding SDK clients, response models, exception types; implementing sync/async/WebSocket
  clients; configuring retries, reconnection, or heartbeat; or working with sdk/agentexchange/ in this project.
---

# Python SDK Authoring

## Package Layout

| Purpose | Path |
|---------|------|
| Package root | `sdk/agentexchange/` |
| Setup | `sdk/setup.py` |
| Sync client | `sdk/agentexchange/client.py` |
| Async client | `sdk/agentexchange/async_client.py` |
| WebSocket client | `sdk/agentexchange/ws_client.py` |
| Response models | `sdk/agentexchange/models.py` |
| Exceptions | `sdk/agentexchange/exceptions.py` |

- Package name: `agentexchange`
- Installable via `pip install -e sdk/`

## Clients

### Sync Client (`client.py`)

- Use `httpx.Client` (not `requests`).
- Constructor: `AgentExchangeClient(api_key: str, api_secret: str, base_url: str)`
- No context manager required; call `close()` when done.
- All methods are synchronous.

### Async Client (`async_client.py`)

- Use `httpx.AsyncClient`.
- Constructor: `AsyncAgentExchangeClient(api_key, api_secret, base_url)`
- Use as async context manager: `async with AsyncAgentExchangeClient(...) as client:`
- All methods are `async`.

### WebSocket Client (`ws_client.py`)

- Use `websockets` library.
- Class: `AgentExchangeWS(api_key, api_secret, base_url)`
- Decorator-based event handlers:
  - `@ws.on_ticker` — ticker updates
  - `@ws.on_order_update` — order status changes
  - `@ws.on_portfolio` — portfolio snapshots
- Auto-reconnect with exponential backoff.
- Built-in heartbeat handling (respond to server ping with pong).

## Response Models

- Use `dataclasses` in `models.py` for typed responses.
- Map API JSON to dataclass instances.
- Include all fields returned by the API.

## Exception Hierarchy (`exceptions.py`)

- Base: `AgentExchangeError`
- Subclasses: `AuthenticationError`, `RateLimitError`, `OrderError`, `APIError`, etc.
- Raise appropriate exception on HTTP 4xx/5xx.
- Include error code and message from API response.

## Retry Behavior

- Auto-retry on 5xx responses only.
- Exponential backoff: 1s → 2s → 4s.
- Max 3 retries per request.
- Do not retry on 4xx (client errors).

## API Methods

| Category | Methods |
|----------|---------|
| Market data | `get_price`, `get_all_prices`, `get_candles`, `get_ticker`, `get_recent_trades`, `get_orderbook` |
| Orders | `place_market_order`, `place_limit_order`, `place_stop_loss`, `place_take_profit`, `get_order`, `get_open_orders`, `cancel_order`, `cancel_all_orders` |
| Trades | `get_trade_history` |
| Account | `get_account_info`, `get_balance`, `get_positions`, `get_portfolio`, `get_pnl` |
| Sim/Admin | `reset_account`, `get_performance`, `get_portfolio_history`, `get_leaderboard` |

- All methods accept symbol/order_id/params as needed.
- Return typed models, not raw dicts.

## Conventions

- Use `X-API-Key` and `X-API-Secret` headers for auth.
- Base URL default: `http://localhost:8000` (overridable).
- Log at DEBUG level; no sensitive data in logs.
- Type hints on all public methods and models.
