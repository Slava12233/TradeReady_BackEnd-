# API Middleware

<!-- last-updated: 2026-03-20 -->

> Authentication, rate limiting, and structured request logging middleware for the FastAPI/Starlette API layer.

## What This Module Does

Three Starlette `BaseHTTPMiddleware` subclasses that run on every HTTP request in a strict order. Together they authenticate callers, enforce per-account rate limits via Redis, and emit structured JSON logs with correlation IDs.

## Key Files

| File | Purpose |
|------|---------|
| `auth.py` | `AuthMiddleware` — resolves account/agent from `X-API-Key` or `Authorization: Bearer` headers; exposes `get_current_account` / `get_current_agent` FastAPI dependencies and `CurrentAccountDep` / `CurrentAgentDep` type aliases |
| `rate_limit.py` | `RateLimitMiddleware` — per-account sliding-window rate limiter backed by Redis `INCR` + `EXPIRE`; injects `X-RateLimit-*` headers on every response |
| `logging.py` | `LoggingMiddleware` — emits one structlog record per request with `request_id`, method, path, status, latency, client IP, and optional `account_id` |
| `__init__.py` | One-line docstring; no re-exports |

## Architecture & Patterns

### Execution Order

Starlette adds middleware LIFO. Registration order in `create_app()` (`src/main.py`) is:

```
RateLimitMiddleware  →  AuthMiddleware  →  LoggingMiddleware  →  route handler
```

This means **LoggingMiddleware runs first** (outermost), then **AuthMiddleware** populates `request.state.account`, then **RateLimitMiddleware** reads that account to enforce limits. The response flows back in reverse order.

### Auth Flow

1. `AuthMiddleware.dispatch()` skips public paths (`_PUBLIC_PATHS` exact match + `_PUBLIC_PREFIXES` prefix match) and CORS `OPTIONS` requests.
2. Credential extraction: tries `X-API-Key` header first, then `Authorization: Bearer <jwt>`.
3. **API key resolution** (`_resolve_account_from_api_key`): queries `agents` table first (multi-agent flow), falls back to `accounts` table (legacy). Returns `(Account, Agent | None)`.
4. **JWT resolution** (`_resolve_account_from_jwt`): decodes JWT via `verify_jwt()`, fetches account by ID. Agent context comes later via `get_current_agent` dependency reading the `X-Agent-Id` header.
5. Sets `request.state.account` and `request.state.agent` for downstream consumption.
6. Returns 401 JSON on missing/invalid credentials, 403 on suspended accounts, 500 on unexpected errors.

### Rate Limiting

Five tiers (first prefix match wins):

| Prefix | Group | Limit |
|--------|-------|-------|
| `/api/v1/trade/` | `orders` | 100 req/min |
| `/api/v1/market/` | `market_data` | 1200 req/min |
| `/api/v1/backtest/` | `backtest` | 6000 req/min |
| `/api/v1/training/` | `training` | 3000 req/min |
| `/api/v1/` (everything else) | `general` | 600 req/min |

- Redis key pattern: `rate_limit:{api_key}:{group}:{minute_bucket}`
- TTL is 2x the window (120s) to handle boundary overlap.
- **Fails open**: Redis errors are logged and swallowed; the request is allowed through.
- Unauthenticated requests pass through without counting (auth middleware will reject them).
- Public paths (`/api/v1/auth/`, `/health`, `/docs`, `/redoc`, `/openapi.json`, `/metrics`) bypass rate limiting entirely.

### Logging

- Generates a UUID4 `request_id` stored on `request.state.request_id` for correlation.
- Skips `/health` and `/metrics` to avoid liveness-probe noise.
- Log level: `info` for 2xx/3xx, `warning` for 4xx, `error` for 5xx or exceptions.
- Uses `structlog` (not stdlib `logging`).
- Reads `X-Forwarded-For` first hop for client IP, falls back to direct peer address.

## Public API / Interfaces

### Dependencies (from `auth.py`)

```python
from src.api.middleware.auth import get_current_account, get_current_agent
from src.api.middleware.auth import CurrentAccountDep, CurrentAgentDep

# In a route:
async def handler(account: CurrentAccountDep, agent: CurrentAgentDep): ...
```

- `get_current_account(request)` — returns `Account`; raises `AuthenticationError` if unauthenticated. Has a fallback path that calls `_authenticate_request` directly when middleware is bypassed (useful in tests).
- `get_current_agent(request)` — returns `Agent | None`. For API-key auth, reads `request.state.agent`. For JWT auth, resolves from `X-Agent-Id` header via `AgentRepository`.

### Middleware Classes

All three are registered via `app.add_middleware(ClassName)` in `src/main.py`. They take no constructor arguments.

### Request State Set by Middleware

| Attribute | Set by | Type |
|-----------|--------|------|
| `request.state.account` | `AuthMiddleware` | `Account` |
| `request.state.agent` | `AuthMiddleware` | `Agent \| None` |
| `request.state.request_id` | `LoggingMiddleware` | `str` (UUID4) |

## Dependencies

- `src.accounts.auth.verify_jwt` — JWT decode/verify
- `src.config.get_settings` — reads `jwt_secret` for JWT verification
- `src.database.models` — `Account`, `Agent` ORM models
- `src.database.repositories.account_repo.AccountRepository` — account lookup by ID or API key
- `src.database.repositories.agent_repo.AgentRepository` — agent lookup by API key or ID
- `src.database.session.get_session_factory` — creates async DB sessions (lazy-imported to avoid circular imports)
- `src.utils.exceptions` — `AuthenticationError`, `AccountSuspendedError`, `RateLimitExceededError`, `TradingPlatformError`
- `redis.asyncio.Redis` — accessed via `request.app.state.redis` (set during app startup)
- `structlog` — used by `LoggingMiddleware` (not stdlib `logging`)

## Common Tasks

**Add a new public (unauthenticated) endpoint:**
- Exact path: add to `_PUBLIC_PATHS` in `auth.py`
- Prefix: add to `_PUBLIC_PREFIXES` in `auth.py`
- If it should also skip rate limiting: add to `_PUBLIC_PREFIXES` in `rate_limit.py`

**Add a new rate-limit tier:**
- Add a tuple `(prefix, group_name, limit)` to `_TIERS` in `rate_limit.py`. Order matters: first match wins, so put more specific prefixes before general ones.

**Skip logging for a noisy endpoint:**
- Add the path to `_SKIP_LOG_PATHS` in `logging.py`.

**Test a route without middleware:**
- Mount the router directly and use `get_current_account` dependency override. The dependency has a fallback that calls `_authenticate_request` when `request.state.account` is absent.

## Gotchas & Pitfalls

- **Middleware order is LIFO.** The registration order in `create_app()` looks like `RateLimit, Auth, Logging` but execution is reversed: Logging wraps Auth wraps RateLimit. If you change the order, rate limiting will break (it depends on `request.state.account` from auth).
- **Auth middleware opens its own DB session** via `get_session_factory()` rather than using the request-scoped session from `dependencies.py`. This is intentional since middleware runs before FastAPI dependency injection.
- **`get_settings()` is `lru_cache`d.** In tests, patch it before the cached instance is created or JWT verification will use real config values.
- **Rate limiter fails open.** If Redis is down, all requests are allowed through with `current_count = 0`. This is by design but means rate limits are not enforced during Redis outages.
- **Agent resolution differs by auth method.** API-key auth resolves the agent in the middleware itself. JWT auth only resolves the agent lazily when `get_current_agent` reads the `X-Agent-Id` header, so `request.state.agent` may be `None` even when an agent header is present until the dependency runs.
- **Lazy imports** in `_authenticate_request` and `get_current_agent` (`get_session_factory`, `UUID`) are intentional to avoid circular imports. Do not move them to module level.

## Recent Changes

- `2026-03-20` — Added `backtest` (6000/min) and `training` (3000/min) rate limit tiers; rate tier count increased from 3 to 5.
- `2026-03-17` — Initial CLAUDE.md created
