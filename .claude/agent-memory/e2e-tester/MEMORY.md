# E2E Tester — Project Memory

## Access Points
- REST API: `http://localhost:8000` (Swagger: `http://localhost:8000/docs`)
- Frontend: `http://localhost:3000`
- WebSocket: `ws://localhost:8000/ws/v1?api_key=ak_live_...`
- Prometheus: `http://localhost:9090`; Grafana: `http://localhost:3000` (when using Docker)
- Health check: `GET /health` (public, no auth) — NOT `/api/v1/health` (returns 404)

## Authentication
- **API key auth**: `X-API-Key: ak_live_...` header — tries agents table first, then accounts table
- **JWT auth**: `Authorization: Bearer <jwt>` — resolve account from JWT; agent context via `X-Agent-Id` header
- **WebSocket**: `?api_key=ak_live_...` query param; close code 4401 on failure
- Public endpoints (no auth): `POST /auth/register`, `POST /auth/login`, `POST /auth/user-login`, `GET /health`, all `/api/v1/market/*`
- `POST /auth/login` only accepts **account-level** keys — agent keys return ACCOUNT_NOT_FOUND

## Account & Agent Creation Flow
1. `POST /api/v1/auth/register` → returns one-time `api_key` + `secret` (201) — store these immediately, they are account-level
2. `POST /api/v1/auth/login` (account api_key + secret) → returns JWT for agent management
3. `POST /api/v1/agents` (JWT required) → creates agent, returns API key **once** — store it immediately
4. Agent API key used as `X-API-Key` for all trading operations scoped to that agent
5. `GET /api/v1/agents/{id}` — agent detail; `GET /api/v1/agents` — list agents
- **Balances are agent-scoped**: `register()` does NOT create a balance; `create_agent()` does — an account with no agents has zero balance

## SDK Agent Key Fallback (Task R1-09, 2026-03-23)
- `AsyncAgentExchangeClient` now falls back to X-API-Key-only auth when login fails with ACCOUNT_NOT_FOUND
- Use an **agent API key** as `PLATFORM_API_KEY` in `agent/.env` for the smoke test and other agent workflows
- Set any value for `PLATFORM_API_SECRET` (it's ignored when login fails gracefully)
- This enables balance, trade, and position endpoints to work with agent-scoped data

## Smoke Test Account (Task R1-09, 2026-03-23)
- Account email: smoke_1774289249@agentexchange.io | Account ID: 0f01d497-798d-400f-9645-f6bd25b24d82
- SmokeBot agent API key: ak_live_bTIhiWGdkj4NA_jrfREKpsyM-vSKAQFpFn7gsMAQYKWkJklYU3YJXLBzrGoHTNVl
- SmokeBot agent ID: 553e8d89-a2a9-425e-ab32-32ec116cf8a8
- Current PLATFORM_API_KEY in agent/.env = SmokeBot agent key (10,000 USDT starting balance)

## Backtest Lifecycle
1. `POST /api/v1/backtest/create` — create session (symbol, timeframe, start_time, end_time, starting_balance)
2. `POST /api/v1/backtest/{id}/start` — bulk-preload candles (required before stepping)
3. `POST /api/v1/backtest/{id}/step` or `/step/batch` — advance simulation by 1 or N candle intervals
4. `POST /api/v1/backtest/{id}/trade/order` — place order in sandbox
5. `GET /api/v1/backtest/{id}/results` — fetch completed metrics (only valid after session completes)
6. `GET /api/v1/backtest/{id}/market/candles/{symbol}` — fetch candles up to virtual clock (no look-ahead bias)
- Orphaned sessions (DB "running" but engine has no record) are auto-marked "failed" on `/status` and `/list`

## Battle Lifecycle
- State machine: `draft → pending → active → completed` (with `cancelled` and `paused` branches)
- All battle endpoints require JWT auth
- `POST /api/v1/battles` — create battle (draft)
- `POST /api/v1/battles/{id}/participants` — enroll agents
- `POST /api/v1/battles/{id}/start` — transition to active
- `GET /api/v1/battles/{id}/live` — live equity snapshots
- `GET /api/v1/battles/{id}/results` — final rankings and metrics
- `GET /api/v1/battles/{id}/replay` — historical replay data
- Supports `"live"` and `"historical"` modes

## Key API Endpoints by Domain
| Domain | Base Path | Auth |
|--------|-----------|------|
| Auth | `/api/v1/auth` | Public |
| Account | `/api/v1/account` | API key or JWT |
| Agents | `/api/v1/agents` | JWT only |
| Trading | `/api/v1/trade` | API key or JWT |
| Market | `/api/v1/market` | Public |
| Analytics | `/api/v1/analytics` | API key or JWT |
| Backtest | `/api/v1/backtest` | API key or JWT |
| Battles | `/api/v1/battles` | JWT only |
| Strategies | `/api/v1/strategies` | API key or JWT |
| Training | `/api/v1/training` | API key or JWT |

## Error & Rate Limit Patterns
- Error format: `{"error": {"code": "...", "message": "...", "details": {...}}}`
- Rate limit headers on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- Rate limits: general 600/min, orders 100/min, market_data 1200/min, backtest 6000/min, training 3000/min
- Rate limiter fails open on Redis errors — all requests allowed through

## Platform Testing Agent Workflows (agent/)
- `smoke` — 10-step connectivity check, no LLM — PASSES 10/10 as of 2026-03-23
- `trade` — full trading lifecycle with LLM signal generation
- `backtest` — 7-day MA-crossover backtest with LLM analysis
- `strategy` — create → test → improve → compare cycle
- Config in `agent/.env`; reports saved to `agent/reports/`
- `OPENROUTER_API_KEY` is the only required field; all others have defaults

## Multi-Agent Scoping
- Trading tables keyed by `agent_id` — always scope queries to the correct agent
- Create separate agent for each test scenario to avoid state pollution
- `agent_id` is primary scoping key; `account_id` is secondary
- `POST /account/reset` resets the scoped agent or account to starting balance

## Provisioned Test Account (Task R1-08, 2026-03-22)
- Email: trader@tradeready.ai | Password: Tr@d3r_S3cur3_2026!
- Account ID: ed633e30-4743-4a72-8965-a877e8383358
- 5 agents: Momentum, Balanced, Evolved, Regime-Adaptive, Conservative — each 10,000 USDT
- Momentum agent API key: ak_live_q_aNiV-PkZ0l-Abme26-Lwcyy7OdIyBq59a6ysX2VHHe1p1icKhYvEOSYUk7P49d
- Risk profile fields: `max_position_size_pct`, `daily_loss_limit_pct`, `max_open_orders` (integers, not decimals)
- PUT /agents/{id}/risk-profile accepts RiskProfileInfo (same schema as GET response)
- POST /auth/user-login returns `{"token": "..."}` (not access_token) for JWT
