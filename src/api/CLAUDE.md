# API Gateway (`src/api/`)

<!-- last-updated: 2026-03-18 -->

> HTTP + WebSocket gateway that wires middleware, REST routes, Pydantic schemas, and real-time channels into the FastAPI application.

## What This Module Does

This module contains everything between the incoming HTTP/WebSocket request and the service layer. It owns authentication, rate limiting, request logging, REST route definitions, Pydantic request/response validation, and the WebSocket connection lifecycle. The application factory in `src/main.py` assembles all pieces from this module into the running `FastAPI` instance via `create_app()`.

## Key Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package marker (no logic) |
| `middleware/auth.py` | `AuthMiddleware` (Starlette `BaseHTTPMiddleware`), `get_current_account` / `get_current_agent` FastAPI deps, `CurrentAccountDep` / `CurrentAgentDep` aliases |
| `middleware/logging.py` | `LoggingMiddleware` -- structured request/response logging with correlation `request_id`, latency, account context |
| `middleware/rate_limit.py` | `RateLimitMiddleware` -- Redis sliding-window rate limiter with 3 tiers (general 600/min, orders 100/min, market_data 1200/min) |
| `routes/*.py` | 12 REST router modules, each exporting a single `router: APIRouter` |
| `schemas/*.py` | Pydantic v2 request/response models, one file per route module |
| `websocket/manager.py` | `ConnectionManager` -- connection registry, auth, heartbeat, broadcast |
| `websocket/channels.py` | Channel classes (`TickerChannel`, `CandleChannel`, `OrderChannel`, `PortfolioChannel`, `BattleChannel`) + `resolve_channel_name()` |
| `websocket/handlers.py` | `handle_message()` dispatcher, `RedisPubSubBridge` singleton for price fan-out |

## Architecture & Patterns

### Middleware Stack

Starlette adds middleware LIFO. Registration order in `create_app()`:

```
app.add_middleware(RateLimitMiddleware)   # added 3rd, runs 3rd
app.add_middleware(AuthMiddleware)        # added 2nd, runs 2nd
app.add_middleware(LoggingMiddleware)     # added 1st, runs 1st
```

**Execution order on each request:**

```
Request --> CORSMiddleware --> LoggingMiddleware --> AuthMiddleware --> RateLimitMiddleware --> Route handler
```

- `LoggingMiddleware` assigns a `request_id` UUID and measures latency. Skips `/health` and `/metrics` to reduce noise.
- `AuthMiddleware` extracts `X-API-Key` or `Authorization: Bearer` headers, resolves the account (and optionally agent) from the DB, stores them on `request.state.account` / `request.state.agent`. Public paths are whitelisted and passed through. CORS preflight (`OPTIONS`) is always passed through.
- `RateLimitMiddleware` reads `request.state.account` (set by auth), resolves the tier from the URL prefix, and increments a Redis sliding-window counter (`rate_limit:{api_key}:{group}:{minute}`). Injects `X-RateLimit-*` headers on every response. Fails open on Redis errors.

### Public Path Whitelist (Auth Bypass)

Exact matches: `/api/v1/auth/register`, `/api/v1/auth/login`, `/api/v1/auth/user-login`, `/health`, `/docs`, `/redoc`, `/openapi.json`, `/metrics`

Prefix matches: `/docs/*`, `/redoc/*`, `/api/v1/market/*`

### Route Registry

All routers are mounted under `/api/v1/` in `create_app()`. Each route file exports a single `router` with its own prefix and tags:

| Module | Prefix | Auth |
|--------|--------|------|
| `routes/auth.py` | `/api/v1/auth` | Public (register/login) |
| `routes/market.py` | `/api/v1/market` | Public (read-only market data) |
| `routes/trading.py` | `/api/v1/trade` | API key or JWT |
| `routes/account.py` | `/api/v1/account` | API key or JWT |
| `routes/agents.py` | `/api/v1/agents` | JWT only |
| `routes/analytics.py` | `/api/v1/analytics` | API key or JWT |
| `routes/backtest.py` | `/api/v1/backtest` | API key or JWT |
| `routes/battles.py` | `/api/v1/battles` | JWT only |
| `routes/strategies.py` | `/api/v1/strategies` | API key or JWT |
| `routes/strategy_tests.py` | `/api/v1/strategies` | API key or JWT |
| `routes/training.py` | `/api/v1/training` | API key or JWT |
| `routes/waitlist.py` | `/api/v1/waitlist` | Varies |

Additional mounts:
- `health_router` at `/health` (no prefix, public)
- Prometheus ASGI app mounted at `/metrics`
- WebSocket endpoint at `/ws/v1`

### Schema Convention

Each route module (`routes/foo.py`) has a matching schema module (`schemas/foo.py`) containing Pydantic v2 models for request bodies and response envelopes. Schemas use `Decimal` for all monetary fields, never `float`.

### WebSocket Architecture

The WebSocket subsystem has three layers:

1. **`ConnectionManager`** (`websocket/manager.py`) -- singleton on `app.state.ws_manager`. Manages auth (via `api_key` query param, close code 4401 on failure), connection registry keyed by UUID, per-account index for private broadcasts, subscription sets (capped at 10 per connection), and a ping/pong heartbeat loop (30s interval, 10s pong timeout).

2. **Channel classes** (`websocket/channels.py`) -- each channel knows its name pattern and how to serialize raw payloads into wire-format envelopes. Public channels (`ticker`, `candles`, `battle`) broadcast via `broadcast_to_channel()`. Private channels (`orders`, `portfolio`) broadcast via `broadcast_to_account()`.

3. **Handlers + Bridge** (`websocket/handlers.py`) -- `handle_message()` dispatches subscribe/unsubscribe/pong actions. `RedisPubSubBridge` is a singleton background task that subscribes to the `price_updates` Redis pub/sub channel and fans ticks out to all WebSocket clients on `ticker:{symbol}` and `ticker:all`. Auto-reconnects on Redis errors.

### Global Exception Handling

`create_app()` registers two exception handlers:
- `TradingPlatformError` subclasses are serialized to `{"error": {"code": ..., "message": ..., "details": ...}}` with the exception's `http_status`.
- All other `Exception` types return a generic 500 response that does not leak internals.

## Public API / Interfaces

### Auth Dependencies (importable from `src.api.middleware.auth`)

- `get_current_account(request) -> Account` -- reads `request.state.account` (set by middleware), falls back to direct header extraction for tests without middleware.
- `get_current_agent(request) -> Agent | None` -- reads `request.state.agent`; for JWT auth resolves agent from `X-Agent-Id` header.
- `CurrentAccountDep` -- `Annotated[Account, Depends(get_current_account)]`
- `CurrentAgentDep` -- `Annotated[Agent | None, Depends(get_current_agent)]`

### WebSocket Public API

- `ConnectionManager.connect(websocket, api_key) -> str | None`
- `ConnectionManager.disconnect(connection_id)`
- `ConnectionManager.broadcast_to_channel(channel, payload) -> int`
- `ConnectionManager.broadcast_to_account(account_id, payload) -> int`
- `ConnectionManager.subscribe(connection_id, channel) -> bool`
- `start_redis_bridge(redis, manager)` / `stop_redis_bridge()` -- lifecycle hooks called from `lifespan()` in `src/main.py`

## Dependencies

**Upstream (this module depends on):**
- `src.database.repositories.account_repo` / `agent_repo` -- auth resolution
- `src.accounts.auth` -- JWT verification (`verify_jwt`)
- `src.config` -- `get_settings()` for JWT secret
- `src.cache.redis_client` -- Redis for rate limiting and pub/sub bridge
- `src.database.session` -- `get_session_factory()` for middleware DB sessions
- `src.utils.exceptions` -- error hierarchy

**Downstream (depends on this module):**
- `src/main.py` imports all middleware classes, all route routers, and WebSocket handlers/manager
- `src/dependencies.py` does NOT depend on this module (dependency injection is separate)
- Route handlers import service/repo deps from `src/dependencies.py`, not from this module

## Common Tasks

**Add a new REST endpoint to an existing router:**
1. Add Pydantic schemas in `schemas/<module>.py`
2. Add the route function in `routes/<module>.py` using existing dependency aliases from `src/dependencies.py`
3. Use `CurrentAccountDep` / `CurrentAgentDep` for auth

**Add a new router module:**
1. Create `routes/new_module.py` with an `APIRouter(prefix="/api/v1/new", tags=["new"])`
2. Create `schemas/new_module.py` with Pydantic v2 models
3. Import and `include_router()` in `src/main.py`

**Add a new WebSocket channel:**
1. Add a channel class in `websocket/channels.py` following the existing pattern
2. Add a case to `resolve_channel_name()` for client subscribe/unsubscribe
3. If it needs a Redis bridge, extend `RedisPubSubBridge` or create a new bridge

**Make a path public (no auth required):**
Add the exact path to `_PUBLIC_PATHS` or a prefix to `_PUBLIC_PREFIXES` in `middleware/auth.py`. If it should also bypass rate limiting, add to `_PUBLIC_PREFIXES` in `middleware/rate_limit.py`.

## Gotchas & Pitfalls

- **Middleware session isolation:** `AuthMiddleware` opens its OWN DB session via `get_session_factory()`, separate from the per-request session in `src/dependencies.py`. The account/agent objects on `request.state` are detached from the request session. Do not try to lazy-load relationships on them in route handlers.
- **LIFO middleware order:** If you add new middleware, remember Starlette adds LIFO. The last `add_middleware()` call runs first. Get the order wrong and `RateLimitMiddleware` will see no `request.state.account`.
- **Rate limiter fails open:** If Redis is down, the rate limiter returns count=0 and allows all requests through. This is intentional but means Redis outages remove rate limiting.
- **WebSocket auth is separate from REST auth:** The `ConnectionManager._authenticate()` method does its own DB lookup using `api_key` query param. It does not go through `AuthMiddleware`. Agent-scoped WebSocket auth is not yet implemented (uses legacy account lookup only).
- **Subscription cap:** Max 10 subscriptions per WebSocket connection. The 11th subscribe attempt returns an error, not a silent drop.
- **Heartbeat timing:** Server pings every 30s, expects pong within 10s. Clients that do not respond to pings are disconnected. The client must send `{"action": "pong"}` (not a WebSocket protocol-level pong frame).
- **`get_current_account` fallback:** If `AuthMiddleware` is not mounted (common in unit tests), the dependency falls back to calling `_authenticate_request()` directly. This means tests can work with or without the middleware.

## Recent Changes

- `2026-03-17` -- Initial CLAUDE.md created
