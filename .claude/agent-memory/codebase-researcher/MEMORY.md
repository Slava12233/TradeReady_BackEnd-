# Codebase Researcher Agent Memory

<!-- last-updated: 2026-03-21 -->

## Navigation System: CLAUDE.md Hierarchy

Every directory has a `CLAUDE.md` — read it before exploring files there.
Root `CLAUDE.md` indexes all 70 CLAUDE.md files across backend, frontend, infra, and agent.

### Top-Level CLAUDE.md Paths
- `CLAUDE.md` — root index, architecture overview, code standards
- `development/CLAUDE.md` — planning docs, task boards, timeline
- `tests/CLAUDE.md` — philosophy, fixtures, async patterns
- `tests/unit/CLAUDE.md` — 72 files, 1203 tests, mock patterns
- `tests/integration/CLAUDE.md` — 24 files, 504 tests, app factory
- `alembic/CLAUDE.md` — migration workflow, naming conventions
- `sdk/CLAUDE.md` — sync/async/WebSocket clients
- `scripts/CLAUDE.md` — seed_pairs, backfill_history
- `docs/CLAUDE.md` — 50 MDX pages, 12 sections, 5 REST routes
- `tradeready-gym/CLAUDE.md` — 7 envs, 4 rewards, 3 wrappers

---

## Common Investigation Entry Points

| Flow | Start at | Key files |
|------|----------|-----------|
| Auth | `src/api/middleware/CLAUDE.md` | middleware, `src/accounts/`, `src/agents/` |
| Price | `src/price_ingestion/CLAUDE.md` | ingestion, `src/cache/`, `src/exchange/` |
| Order | `src/api/routes/CLAUDE.md` | routes, `src/risk/`, `src/order_engine/` |
| Agent/AI | `agent/CLAUDE.md` | strategies, conversation, memory, permissions, trading |
| Backtest/Battle | `src/backtesting/CLAUDE.md` | backtesting, battles, metrics, strategies, training, tradeready-gym |

Key: API key auth tries agents table first, falls back to accounts. `DataReplayer` filters `WHERE bucket <= virtual_clock` (no look-ahead).

## Test Locations
- `tests/unit/` — 72 files, 1203 tests, mock all external deps
- `tests/integration/` — 24 files, 504 tests, requires Docker services
- `agent/tests/` — 1133 test functions across 32 files
- `Frontend/src/` (vitest) — 207 unit tests
- `tradeready-gym/` — 25+ compliance tests; `tests/load/locustfile.py` for load tests

## Frontend Navigation
- `Frontend/src/components/CLAUDE.md` — 130+ files, organized by feature (20 feature CLAUDE.md files)
- `Frontend/src/hooks/CLAUDE.md` — 23 hooks, TanStack Query patterns, query keys
- `Frontend/src/stores/CLAUDE.md` — 6 Zustand stores, persistence, agent state
- `Frontend/src/lib/CLAUDE.md` — `api-client.ts`, utilities, constants, chart config
- `Frontend/src/app/CLAUDE.md` — App Router, layouts, route groups
- `Frontend/src/styles/CLAUDE.md` — `chart-theme.ts`, CSS custom properties

---

## Agent-Platform Touchpoint Map

See [reference_agent_platform_touchpoints.md](reference_agent_platform_touchpoints.md) for full details (4 channels, 7+ DB tables, Redis keys, report files).

See [reference_trading_infrastructure.md](reference_trading_infrastructure.md) for the full 13-module trading infrastructure map (2026-03-22): module→class→agent-API mapping, all critical execution paths, and key invariants for every subsystem.

---

## Key Gotchas for Research Tasks

- `get_settings()` uses `@lru_cache` — patch before cached instance is created in tests
- All DB access via repository classes in `src/database/repositories/`
- `Decimal` not `float` for all money/price values
- Lazy imports inside `src/dependencies.py` (avoid circular imports — do not move to module level)
- `BacktestEngine` is a singleton (`_backtest_engine_instance` module-level global)
- `CircuitBreaker` is account-scoped, not a singleton — constructed per-account with `starting_balance`
- WebSocket channels: 5 total — see `src/api/websocket/CLAUDE.md`
- Agent ecosystem DB tables (7): `agent_sessions`, `agent_messages`, `agent_decisions`, `agent_journal`, `agent_learnings`, `agent_feedback`, plus budget/permission/performance/observation repos in `src/database/repositories/agent_*.py`
- Agent memory uses platform's SAME TimescaleDB (shared DB, shared engine); no separate DB
- `PostgresMemoryStore` constructor is `(repo, config)` NOT `(session_factory)` — the CLAUDE.md description is slightly misleading; repos are injected
- Working memory in Redis (`agent:working:{agent_id}` hash) has NO TTL — must explicitly call `clear_working()` on session end or stale state leaks
