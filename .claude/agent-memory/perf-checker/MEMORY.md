# perf-checker — Persistent Memory

<!-- last-updated: 2026-03-21 -->

## Past Audit: agent/strategies/ (2026-03-20)

Report: `development/code-reviews/perf-check-agent-strategies.md`
Result: 15 findings — 0 CRITICAL, 8 HIGH, 5 MEDIUM, 2 LOW

**8 HIGH findings fixed in agent deployment prep (2026-03-20):**
1. `battle_runner.py` — 5 locations: sequential `for` loops over API calls replaced with `asyncio.gather` + `asyncio.Semaphore(5)` (agent creation, resets ×360, strategy assignment, participant registration)
2. `deploy.py:857` + `run.py:679` — `model.predict()` (PyTorch, 5-50ms) offloaded via `asyncio.to_thread` / `run_in_executor`
3. `run.py:575` — `RandomForestClassifier.fit()` (1-3s CPU) wrapped in `run_in_executor`

**Outstanding MEDIUM findings (not yet fixed):**
- `switcher.py:194` — full indicator recomputation per step (O(100×5) per symbol per call); fix: cache on last candle timestamp
- `run.py:1172` — sequential candle fetch per symbol in backtest loop; fix: `asyncio.gather`
- `run.py:384` — `_step_history` list unbounded during run; fix: `deque(maxlen=500)`
- `regime/switcher.py:153` — `regime_history` list unbounded; fix: `deque(maxlen=500)`
- `evolve.py:231` — mutable function attribute for cross-run state contamination (correctness + memory)

## Known Hot Paths

**Backend:**
- Price ingestion: Exchange WS → Redis HSET → asyncpg COPY bulk flush (1s interval, 5000 tick buffer cap)
- Order execution: RiskManager (8-step) → Redis price fetch → fill / queue
- WebSocket broadcast: `RedisPubSubBridge` fans `price_updates` pub/sub to all `ticker:*` subscribers
- Limit/stop order matching: Celery background task (not on request path)

**Frontend:**
- Market table: 600+ pairs, virtual scrolling via `@tanstack/react-virtual`
- WebSocket price fan-out: `PriceBatchBuffer` → `requestAnimationFrame` flush, 100ms minimum interval, Map-based symbol dedup before Zustand dispatch
- Dashboard heavy sections: 8 `next/dynamic` lazy-loaded with skeleton fallbacks
- Candle sparklines: `useDailyCandlesBatch` batches 50 symbols/query (600 symbols → 12 query entries)

## Frontend Performance Patterns (implemented 2026-03-20)

- `React.memo` with custom comparators on table row components (only re-render on price/direction change)
- Always memoize Zustand selector functions to prevent re-subscription churn
- `keepPreviousData` (`placeholderData: keepPreviousData`) on 7 paginated/filtered hooks
- GET deduplication in `api-client.ts` — concurrent identical GETs share one in-flight fetch
- 4 memo'd header islands: `WsStatusBadge`, `NotificationBell`, `UserAvatar`, `SearchShell`
- Route prefetch on sidebar hover via `src/lib/prefetch.ts`
- Debounced search: 300ms

## Performance Budget Targets

- Regime inference: <10ms per call (XGBoost classifier is sub-ms; `generate_training_data()` preprocessing is the bottleneck)
- Live trading step: <500ms total (price fetch + inference + order execution)
- WebSocket tick fan-out: should not block event loop; bridge runs as background asyncio task
- Frontend re-renders: only on price/direction change for market table rows

## Pattern: asyncio.gather with Semaphore

When replacing sequential API call loops:
```python
sem = asyncio.Semaphore(5)
async def bounded(coro):
    async with sem:
        return await coro
results = await asyncio.gather(*[bounded(call(item)) for item in items])
```
Use semaphore bound of 5 for external REST calls, 10 for internal service calls.

## React Performance Rules

- Never pass inline arrow functions as Zustand selectors — memoize with `useMemo` or `useCallback`
- Code-split via `next/dynamic` for: TradingView charts, Recharts, heavy dashboard sections
- `font-mono` (JetBrains Mono) numbers render faster than variable-width fonts in tables
- Bundle analysis: `ANALYZE=true pnpm build` (requires `@next/bundle-analyzer`)
- [feedback_agent_scope.md](feedback_agent_scope.md) — Scope: this agent audits agent/ trading code (Python SDK-backed), not the main src/ platform
- [project_context_builder_cache.md](project_context_builder_cache.md) — ContextBuilder opens a new SDK client per build() call; Task 37 requests a 30s TTL cache
- [project_known_patterns.md](project_known_patterns.md) — Known safe/unsafe patterns discovered in agent/ trading subsystem
