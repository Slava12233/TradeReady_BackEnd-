# E2E Tester — Project Memory

## Access Points
- REST API: `http://localhost:8000` (Swagger: `http://localhost:8000/docs`)
- Frontend: `http://localhost:3000`
- WebSocket: `ws://localhost:8000/ws/v1?api_key=ak_live_...`
- Prometheus: `http://localhost:9090`; Grafana: `http://localhost:3000` (when using Docker)
- Health check: `GET /health` (public, no auth)

## Authentication
- **API key auth**: `X-API-Key: ak_live_...` header — tries agents table first, then accounts table
- **JWT auth**: `Authorization: Bearer <jwt>` — resolve account from JWT; agent context via `X-Agent-Id` header
- **WebSocket**: `?api_key=ak_live_...` query param; close code 4401 on failure
- Public endpoints (no auth): `POST /auth/register`, `POST /auth/login`, `POST /auth/user-login`, `GET /health`, all `/api/v1/market/*`

## Account & Agent Creation Flow
1. `POST /api/v1/auth/register` → returns one-time `api_key` + `secret` (201)
2. `POST /api/v1/auth/login` (api_key + secret) → returns JWT for agent management
3. `POST /api/v1/agents` (JWT required) → creates agent, returns API key **once** — store it immediately
4. Agent API key used as `X-API-Key` for all trading operations scoped to that agent
5. `GET /api/v1/agents/{id}` — agent detail; `GET /api/v1/agents` — list agents

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

## Trading Endpoints
- `POST /api/v1/trade/order` — place order (market/limit/stop-loss/take-profit)
- `GET /api/v1/trade/orders` — list orders
- `DELETE /api/v1/trade/orders/{id}` — cancel order
- `GET /api/v1/trade/history` — trade history
- Market orders fill immediately with slippage; limit/stop orders queue as pending (matched by Celery)

## Account Endpoints
- `GET /account/balance` — per-asset balances + total equity
- `GET /account/positions` — open positions with unrealized PnL
- `GET /account/portfolio` — full portfolio snapshot
- `GET /account/pnl` — PnL breakdown by period (1d/7d/30d/all)
- `POST /account/reset` — destructive reset to starting balance (requires `confirm: true`)

## Error & Rate Limit Patterns
- Error format: `{"error": {"code": "...", "message": "...", "details": {...}}}`
- Rate limit headers on every response: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- Rate limits: general 600/min, orders 100/min, market_data 1200/min, backtest 6000/min, training 3000/min
- Rate limiter fails open on Redis errors — all requests allowed through

## Platform Testing Agent Workflows (agent/)
- `smoke` — 10-step connectivity check, no LLM
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

## Provisioned Test Account (Task 03, 2026-03-22)
- Email: trader@tradeready.ai | Password: Tr@d3r_S3cur3_2026!
- Account ID: ed633e30-4743-4a72-8965-a877e8383358
- 5 agents: Momentum, Balanced, Evolved, Regime-Adaptive, Conservative — each 10,000 USDT
- Momentum agent API key written to agent/.env as PLATFORM_API_KEY
- Risk profile fields: `max_position_size_pct`, `daily_loss_limit_pct`, `max_open_orders` (integers, not decimals)
- PUT /agents/{id}/risk-profile accepts RiskProfileInfo (same schema as GET response)
- POST /auth/user-login returns `{"token": "..."}` (not access_token) for JWT
