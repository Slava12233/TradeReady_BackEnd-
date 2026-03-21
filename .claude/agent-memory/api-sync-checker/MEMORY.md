# api-sync-checker — Persistent Memory

<!-- last-updated: 2026-03-21 -->

## Key Files to Compare

| Backend | Frontend counterpart |
|---------|---------------------|
| `src/api/schemas/*.py` (12 files) | `Frontend/src/lib/types.ts` |
| `src/api/routes/*.py` (12 routers) | `Frontend/src/lib/api-client.ts` |
| `src/api/websocket/channels.py` | `Frontend/src/lib/websocket-client.ts` + `src/stores/websocket-store.ts` |

## Backend Schema Files

`auth.py`, `account.py`, `agents.py`, `analytics.py`, `backtest.py`, `battles.py`,
`market.py`, `trading.py`, `strategies.py`, `strategy_tests.py`, `training.py`, `waitlist.py`

No re-exports from `__init__.py` — import schemas by specific module.

## Frontend API Client Patterns

- All endpoints under `/api/v1/`
- Auth priority: JWT (`Authorization: Bearer`) → API key (`X-API-Key`) → public
- Agent-scoped requests also inject `X-Agent-Id` from `localStorage.active_agent_id`
- `ApiClientError` class (not plain object) — use `instanceof ApiClientError` in catch blocks
- `getApiKey()` / `getJwtToken()` return empty string on SSR — API calls must be client-side only
- GET deduplication: concurrent identical GETs share one in-flight fetch (Map keyed by URL)
- 3x exponential backoff retry on 5xx: 200/400/800ms
- 4-second request timeout (`REQUEST_TIMEOUT_MS`)

## Decimal Serialization Rule

Backend `Decimal` fields → serialized to `str` in JSON (via `@field_serializer`).
Frontend `types.ts` must type these as `string`, never `number`.

Example affected fields: all price/quantity/balance/fee columns.

## WebSocket Protocol

- Subscription key format: `channel:symbol:interval` (e.g., `ticker:BTCUSDT`, `candles:ETHUSDT:1h`)
- Heartbeat: server sends `{"type":"ping"}`, client responds `{"action":"pong"}` (application-level, not WS protocol ping)
- `WsPingMessage` has no `channel` property — always guard with `"channel" in msg` before switching on `msg.channel`
- Max 10 subscriptions per connection (server enforces hard cap)
- Close code 4401 = auth failure on WebSocket connect
- WebSocket auth uses `api_key` query param only — JWT not supported on WS

## Rate Limit Tiers (headers on every response)

| Tier | Limit |
|------|-------|
| orders (`/trade/*`) | 100/min |
| market_data (`/market/*`) | 1200/min |
- backtest (`/backtest/*`) | 6000/min |
| training (`/training/*`) | 3000/min |
| general (all others) | 600/min |

Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

## Known Type Gotchas

- `OrderBookLevel` interface in `types.ts` is unused — actual `OrderBookResponse` uses `[string, string][]` tuples
- `BacktestCreateRequest.agent_id` is `str | None` (not UUID) for backward compat
- `_BaseSchema` is duplicated per file — no shared base in `__init__.py`
- `dict[str, Any]` / `dict[str, object]` used for dynamic shapes in `backtest.py` and `battles.py`
- `TRADING.feeRate = 0.001` in frontend constants must match backend `TRADING_FEE_PCT`

## Strategy & Training Types (added 2026-03-18)

20 types added to `types.ts` and 20 API functions added to `api-client.ts`:
`StrategyStatus`, `Strategy`, `StrategyDetailResponse`, `StrategyVersion`, `StrategyListResponse`,
`TestRunStatus`, `StrategyTestRun`, `PairBreakdown`, `AggregatedMetrics`, `TestResults`,
`VersionMetrics`, `VersionComparisonResponse`, `TrainingRun`, `TrainingEpisodeMetrics`,
`TrainingEpisode`, `LearningCurveData`, `TrainingRunDetail`, `RunMetrics`,
`TrainingComparisonResponse`, `StrategyDefinition`
