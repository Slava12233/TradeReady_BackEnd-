# API Routes

<!-- last-updated: 2026-04-07 -->

> FastAPI route modules implementing all REST endpoints for the AI Agent Crypto Trading Platform.

## What This Module Does

This directory contains all HTTP route handlers, organized by domain. Each file defines an `APIRouter` with a prefix under `/api/v1/`. Routers are registered in `src/main.py` via `create_app()`. Routes are thin controllers: they validate input via Pydantic schemas, delegate to services/repositories, and return structured responses.

## Key Files

| File | Prefix | Auth | Purpose |
|------|--------|------|---------|
| `auth.py` | `/api/v1/auth` | Public | Registration, login (API key + JWT) |
| `account.py` | `/api/v1/account` | Required | Account info, balances, positions, portfolio, PnL, risk profile, reset |
| `agents.py` | `/api/v1/agents` | JWT only | Multi-agent CRUD, clone, archive, API key management, skill file |
| `trading.py` | `/api/v1/trade` | Required | Order placement, listing, cancellation, trade history |
| `market.py` | `/api/v1/market` | Public | Prices, pairs, tickers, candles, trades, simulated orderbook |
| `analytics.py` | `/api/v1/analytics` | Required | Performance metrics, portfolio history, leaderboard |
| `backtest.py` | `/api/v1` | Required | Backtest lifecycle, sandbox trading/market/account, results, mode management |
| `battles.py` | `/api/v1/battles` | JWT only | Battle lifecycle, participants, live/results/replay, historical battles |
| `strategies.py` | `/api/v1/strategies` | Required | Strategy CRUD, versioning, deploy/undeploy (10 endpoints) |
| `strategy_tests.py` | `/api/v1/strategies` | Required | Strategy testing: start, list, get, cancel, results, compare (6 endpoints) |
| `training.py` | `/api/v1/training` | Required | Training runs: register, report episodes, complete, list, detail, learning curve, compare (7 endpoints) |
| `waitlist.py` | `/api/v1/waitlist` | Public | Landing page email collection |
| `__init__.py` | — | — | Package docstring only |

## Architecture & Patterns

### Authentication model

Three tiers of auth across routes:

1. **Public** (no auth): `auth.py` (register, login, user-login), `market.py` (all endpoints), `waitlist.py`
2. **API key or JWT** (`X-API-Key` / `Authorization: Bearer`): `account.py`, `trading.py`, `analytics.py`, `backtest.py`
3. **JWT only**: `agents.py`, `battles.py` — these manage cross-agent resources owned by the account

Auth is resolved by `AuthMiddleware` before the handler runs. Routes access the result via dependency injection:
- `CurrentAccountDep` — the authenticated `Account` ORM instance
- `CurrentAgentDep` — the `Agent` instance (from API key auth or `X-Agent-Id` header); may be `None`

### Agent scoping

Most endpoints that touch trading data accept an agent context. The pattern is:
```python
agent_id = agent.id if agent is not None else None
result = await some_service.do_thing(account.id, agent_id=agent_id)
```
When `agent_id` is `None`, services fall back to account-level behavior (legacy path).

### Dependency injection

All service/repo instantiation goes through `src/dependencies.py` typed aliases (`DbSessionDep`, `OrderEngineDep`, `BacktestEngineDep`, etc.). Routes never construct services directly.

### Ownership checks

For agent- and battle-scoped endpoints, routes manually verify `resource.account_id == account.id` and raise `PermissionDeniedError` on mismatch. This is done inline (not via middleware) because the check requires loading the resource first.

### Response serialization

- ORM models are converted to Pydantic schemas via helper functions (`_order_to_detail`, `_agent_to_response`, `_battle_to_response`, etc.) defined at module level.
- All monetary values use `Decimal` (never `float`) and are serialized as strings in JSON.
- Backtest routes return raw `dict` responses for several endpoints (not Pydantic models).

### Orphan detection

`backtest.py` detects orphaned sessions (DB status is "running" but the in-memory engine has no record) in both `/status` and `/list` endpoints. It auto-marks them as "failed" via direct SQL UPDATE.

## Public API / Interfaces

### auth.py — 3 endpoints

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/auth/register` | 201 | Create account, returns one-time API key + secret |
| `POST` | `/auth/login` | 200 | Exchange API key + secret for JWT |
| `POST` | `/auth/user-login` | 200 | Exchange email + password for JWT |

### account.py — 7 endpoints

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `GET` | `/account/info` | 200 | Account details, session, risk profile |
| `GET` | `/account/balance` | 200 | Per-asset balances + total equity |
| `GET` | `/account/positions` | 200 | Open positions with unrealized PnL |
| `GET` | `/account/portfolio` | 200 | Full portfolio snapshot (cash + positions + PnL) |
| `GET` | `/account/pnl` | 200 | PnL breakdown by period (1d/7d/30d/all) |
| `PUT` | `/account/risk-profile` | 200 | Update risk limits (agent or account) |
| `POST` | `/account/reset` | 200 | Destructive reset to starting balance (requires `confirm: true`) |

### agents.py — 17 endpoints

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/agents` | 201 | Create agent (returns API key once) |
| `GET` | `/agents` | 200 | List agents (with pagination, archive filter) |
| `GET` | `/agents/overview` | 200 | All active agents with summary |
| `GET` | `/agents/{id}` | 200 | Agent detail |
| `PUT` | `/agents/{id}` | 200 | Update agent config |
| `POST` | `/agents/{id}/clone` | 201 | Clone agent into new agent |
| `POST` | `/agents/{id}/reset` | 200 | Reset agent balances |
| `POST` | `/agents/{id}/archive` | 200 | Soft delete |
| `DELETE` | `/agents/{id}` | 204 | Permanent delete |
| `GET` | `/agents/{id}/api-key` | 200 | Reveal full API key |
| `POST` | `/agents/{id}/regenerate-key` | 200 | Generate new API key (invalidates old) |
| `GET` | `/agents/{id}/risk-profile` | 200 | Get agent risk limits |
| `PUT` | `/agents/{id}/risk-profile` | 200 | Update agent risk limits |
| `GET` | `/agents/{id}/skill.md` | 200 | Download agent-specific skill file (plaintext) |
| `GET` | `/agents/{id}/decisions/trace/{trace_id}` | 200 | Fetch all decisions linked to a distributed trace ID |
| `GET` | `/agents/{id}/decisions/analyze` | 200 | Analyze decision patterns: confidence distribution, outcome correlation |
| `PATCH` | `/agents/{id}/feedback/{feedback_id}` | 200 | Update feedback status/resolution (agent_feedback lifecycle) |

### trading.py — 7 endpoints

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/trade/order` | 201 | Place order (market/limit/stop-loss/take-profit) |
| `GET` | `/trade/order/{id}` | 200 | Get single order by UUID |
| `GET` | `/trade/orders` | 200 | List orders (filter by status, symbol) |
| `GET` | `/trade/orders/open` | 200 | List pending/partially-filled orders |
| `DELETE` | `/trade/order/{id}` | 200 | Cancel single pending order |
| `DELETE` | `/trade/orders/open` | 200 | Cancel all open orders |
| `GET` | `/trade/history` | 200 | Paginated trade execution history |

### market.py — 8 endpoints (all public)

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `GET` | `/market/pairs` | 200 | List all trading pairs (with `has_price` flag) |
| `GET` | `/market/price/{symbol}` | 200 | Current price for one pair |
| `GET` | `/market/prices` | 200 | All prices (optional comma-separated filter) |
| `GET` | `/market/ticker/{symbol}` | 200 | 24h rolling ticker stats |
| `GET` | `/market/tickers` | 200 | Batch 24h tickers (up to 100 symbols) |
| `GET` | `/market/candles/{symbol}` | 200 | OHLCV candles (1m/5m/1h/1d, with Binance fallback) |
| `GET` | `/market/trades/{symbol}` | 200 | Recent public trades from tick history |
| `GET` | `/market/orderbook/{symbol}` | 200 | Simulated order book (synthetic, not real Binance depth) |

### analytics.py — 3 endpoints

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `GET` | `/analytics/performance` | 200 | Sharpe, Sortino, drawdown, win rate, profit factor |
| `GET` | `/analytics/portfolio/history` | 200 | Equity snapshots for charting (1m/1h/1d intervals) |
| `GET` | `/analytics/leaderboard` | 200 | Cross-account rankings by ROI (top 50, max 200 scanned) |

### backtest.py — 27 endpoints

**Lifecycle:**

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/backtest/create` | 200 | Create session (date range, balance, pairs, agent_id) |
| `POST` | `/backtest/{id}/start` | 200 | Initialize sandbox, bulk preload price data |
| `POST` | `/backtest/{id}/step` | 200 | Advance one candle interval |
| `POST` | `/backtest/{id}/step/batch` | 200 | Advance N candles |
| `POST` | `/backtest/{id}/cancel` | 200 | Abort early, save partial results |
| `GET` | `/backtest/{id}/status` | 200 | Progress, equity, virtual time (with orphan detection) |

**Sandbox trading:**

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/backtest/{id}/trade/order` | 200 | Place order in sandbox |
| `GET` | `/backtest/{id}/trade/orders` | 200 | List all sandbox orders |
| `GET` | `/backtest/{id}/trade/orders/open` | 200 | List pending sandbox orders |
| `DELETE` | `/backtest/{id}/trade/order/{oid}` | 200 | Cancel sandbox order |
| `GET` | `/backtest/{id}/trade/history` | 200 | Sandbox trade log |

**Sandbox market data:**

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `GET` | `/backtest/{id}/market/price/{sym}` | 200 | Price at virtual_time |
| `GET` | `/backtest/{id}/market/prices` | 200 | All prices at virtual_time |
| `GET` | `/backtest/{id}/market/ticker/{sym}` | 200 | 24h stats at virtual_time |
| `GET` | `/backtest/{id}/market/candles/{sym}` | 200 | Candles before virtual_time |

**Sandbox account:**

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `GET` | `/backtest/{id}/account/balance` | 200 | Sandbox balances |
| `GET` | `/backtest/{id}/account/positions` | 200 | Sandbox positions |
| `GET` | `/backtest/{id}/account/portfolio` | 200 | Sandbox portfolio summary |

**Results & analysis:**

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `GET` | `/backtest/{id}/results` | 200 | Full results + metrics |
| `GET` | `/backtest/{id}/results/equity-curve` | 200 | Equity curve data points |
| `GET` | `/backtest/{id}/results/trades` | 200 | Complete trade log |
| `GET` | `/backtest/list` | 200 | List backtests (filters, orphan detection) |
| `GET` | `/backtest/compare` | 200 | Compare sessions side-by-side |
| `GET` | `/backtest/best` | 200 | Best session by metric |

**Mode management (under `/account/`):**

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `GET` | `/account/mode` | 200 | Current operating mode (live/backtest) |
| `POST` | `/account/mode` | 200 | Switch mode |

**Market data range (under `/market/`):**

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `GET` | `/market/data-range` | 200 | Earliest/latest timestamps, total pairs |

### battles.py — 20 endpoints (JWT only)

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/battles` | 201 | Create battle (draft) |
| `GET` | `/battles` | 200 | List battles (status filter) |
| `GET` | `/battles/presets` | 200 | 8 preset configurations (5 live + 3 historical) |
| `GET` | `/battles/{id}` | 200 | Battle detail with participants |
| `PUT` | `/battles/{id}` | 200 | Update config (draft only) |
| `DELETE` | `/battles/{id}` | 204 | Delete/cancel battle |
| `POST` | `/battles/{id}/participants` | 201 | Add agent to battle |
| `DELETE` | `/battles/{id}/participants/{aid}` | 204 | Remove agent |
| `POST` | `/battles/{id}/start` | 200 | Lock config, snapshot wallets, begin |
| `POST` | `/battles/{id}/pause/{aid}` | 200 | Pause one agent |
| `POST` | `/battles/{id}/resume/{aid}` | 200 | Resume paused agent |
| `POST` | `/battles/{id}/stop` | 200 | Calculate rankings, complete |
| `GET` | `/battles/{id}/live` | 200 | Real-time metrics for all participants |
| `GET` | `/battles/{id}/results` | 200 | Final results (completed only) |
| `GET` | `/battles/{id}/replay` | 200 | Time-series snapshots for replay |
| `POST` | `/battles/{id}/step` | 200 | Advance historical battle one step |
| `POST` | `/battles/{id}/step/batch` | 200 | Advance historical battle N steps |
| `POST` | `/battles/{id}/trade/order` | 200 | Place order in historical battle |
| `GET` | `/battles/{id}/market/prices` | 200 | Prices at virtual time (historical) |
| `POST` | `/battles/{id}/replay` | 201 | Create new draft from completed battle config |

### waitlist.py — 1 endpoint (public)

| Method | Path | Status | Description |
|--------|------|--------|-------------|
| `POST` | `/waitlist/subscribe` | 201 | Add email to launch waitlist |

## Dependencies

Each route file imports from these layers (never from other route files):

- **Schemas** (`src/api/schemas/`): Pydantic v2 request/response models per domain
- **Auth middleware** (`src/api/middleware/auth`): `CurrentAccountDep`, `CurrentAgentDep`
- **Dependency aliases** (`src/dependencies`): All `*Dep` typed aliases for services/repos
- **ORM models** (`src/database/models`): Only for type hints and direct DB queries (analytics, backtest)
- **Exceptions** (`src/utils/exceptions`): Typed exceptions auto-serialized by the global handler
- **Domain services**: Imported lazily inside dependency functions (never at module level to avoid circular imports)

## Common Tasks

### Adding a new endpoint

1. **Pick the right file** based on the domain, or create a new file if it is a new domain.
2. **Define the Pydantic schemas** in `src/api/schemas/<domain>.py` for request and response bodies.
3. **Add the route handler** following the existing pattern:
   ```python
   @router.post("/new-thing", response_model=NewThingResponse, status_code=status.HTTP_201_CREATED)
   async def create_new_thing(
       body: NewThingRequest,
       account: CurrentAccountDep,
       agent: CurrentAgentDep,
       some_service: SomeServiceDep,
   ) -> NewThingResponse:
       agent_id = agent.id if agent is not None else None
       result = await some_service.create(account.id, agent_id=agent_id, **body.model_dump())
       return NewThingResponse(...)
   ```
4. **Register the router** in `src/main.py` if it is a new file: `app.include_router(new_router)`.
5. **Add tests**: Unit test the handler logic; integration test the full HTTP round-trip using `create_app()`.
6. **Run checks**: `ruff check src/api/routes/<file>.py` and `mypy src/api/routes/<file>.py`.

### Making an endpoint public (no auth)

Add the path to the whitelist in `src/api/middleware/auth.py`. The middleware skips auth for whitelisted paths.

### Adding a new backtest sandbox endpoint

Follow the pattern in `backtest.py`: call `engine._get_active(session_id)` to get the in-memory session, then operate on `active.sandbox` or `active.simulator`. Return a raw `dict` (backtest routes do not consistently use Pydantic response models).

## Gotchas & Pitfalls

- **`backtest.py` uses `/api/v1` as its router prefix**, not `/api/v1/backtest`. This is because it also registers endpoints under `/account/mode` and `/market/data-range`. Be careful not to create path conflicts with `account.py` or `market.py`.
- **Lazy imports inside handlers**: Several files use `from src.utils.exceptions import SomeError` inside the handler body (guarded by `# noqa: PLC0415`) to avoid circular imports. Follow this pattern when importing exception classes that live in modules that import from routes.
- **Agent context can be `None`**: `CurrentAgentDep` returns `None` when no agent context is present (e.g., legacy account-level API keys). Always guard with `agent.id if agent is not None else None`.
- **`battles.py` GET and POST on the same path** (`/{battle_id}/replay`): FastAPI resolves by HTTP method. GET returns replay data; POST creates a new battle draft from a completed battle.
- **Backtest routes access private engine attributes**: Several handlers call `engine._get_active(session_id)` and `engine._active` directly. This is intentional but fragile — changes to the engine's internal data structures will break these routes.
- **Leaderboard is bounded**: `analytics.py` caps leaderboard computation at 200 accounts (`_LEADERBOARD_MAX_ACCOUNTS`) to prevent unbounded per-account metric queries.
- **Market candles have a Binance fallback**: When local TimescaleDB data is insufficient, `market.py` fetches candles from the Binance public API and merges them. This adds external network dependency to an otherwise local-only endpoint.
- **Orderbook is synthetic**: The `/market/orderbook/{symbol}` endpoint generates fake bid/ask levels around the mid-price. It does not reflect real Binance liquidity.
- **`waitlist.py` uses `structlog`** while all other route files use stdlib `logging`. Be aware of this inconsistency.
- **Decimal consistency**: All monetary values must use `Decimal(str(value))` when converting from ORM fields. Never use `Decimal(float_value)` or bare `float`.

## Recent Changes

- `2026-04-07` — `backtest.py`: Fixed orphan detection in `/backtest/{id}/status` that prematurely marked newly-created sessions as `"failed"` before they could register in the in-memory engine. Now checks `is_active()` before applying orphan timeout. Fixed compare endpoint (`GET /backtest/compare`) returning null metrics for cancelled sessions.
- `2026-04-07` — `battles.py`: `GET /battles/{id}/live` now computes and returns `elapsed_minutes`, `remaining_minutes`, and `updated_at`. Uses `model_validate()` on the typed `BattleLiveParticipantSchema` to enforce the 13-field contract.
- `2026-04-02` (BUG-017) — `account.py`: `/account/positions` now fetches `opened_at` from the `Position` table directly via a separate query, replacing the epoch sentinel (`1970-01-01`) that was previously returned. Also fixed `asyncio.gather` on a shared DB session (caused `IllegalStateChangeError`); positions and portfolio queries now run sequentially.
- `2026-04-02` (BUG-012) — `market.py`: `GET /market/tickers` `symbols` query parameter is now optional; when omitted all cached tickers are returned. Previously required, causing 422 errors for clients that expected bulk fetch behavior.
- `2026-04-02` (BUG-003) — `battles.py`: `_battle_to_response()` now checks SQLAlchemy `inspect(battle).attrs.participants.loaded_value` state before accessing the relationship, preventing `MissingGreenlet` errors when participants are not eagerly loaded.
- `2026-04-02` (BUG-015) — `trading.py` schema: `OrderRequest.price` now accepts `stop_price` as an alias via `AliasChoices`, so stop-loss/take-profit orders submitted with `stop_price` field are correctly parsed.
- `2026-04-02` — `auth.py`: `POST /auth/register` response now includes `agent_id` and `agent_api_key` (both nullable). Clients should use `agent_api_key` as `X-API-Key` for all trading endpoints.
- `2026-03-21` — `agents.py` gained 3 new endpoints: `GET /decisions/trace/{trace_id}` (distributed trace lookup), `GET /decisions/analyze` (decision pattern analysis), `PATCH /feedback/{feedback_id}` (feedback lifecycle management). Total agents.py endpoints: 14 → 17.
- `2026-03-20` — `backtest.py` `/backtest/create` interval parameter now accepts string shorthand (`"1h"`, `"5m"`) in addition to raw seconds integers, via `parse_interval()` from `src/utils/helpers.py`.
- `2026-03-17` — Initial CLAUDE.md created
