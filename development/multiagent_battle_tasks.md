---
type: task-list
title: "Multi-Agent & Agents Battle — Task Breakdown"
status: archived
phase: battles
tags:
  - task
  - battles
---

# Multi-Agent & Agents Battle — Task Breakdown

> **Authority:** `Multiagentbattleplan.md` — all file names, schemas, endpoints MUST match
> **Created:** 2026-03-12
> **Status:** All 6 Phases Complete
> **Estimated Duration:** 6–7 weeks across 6 phases

---

## Risk Assessment

This feature restructures the **core data model** (account → agent). Every table with `account_id` gets re-keyed. The auth middleware changes. The entire frontend re-scopes.

**Non-negotiable safety rules:**
1. Every migration must be reversible (write downgrade path)
2. Migration split into additive steps (no single big-bang migration)
3. Auth middleware must support BOTH old and new paths during transition
4. Frontend changes must not break existing pages before agent scoping is wired
5. Run full test suite after every sub-phase — zero failures before proceeding
6. Each task = one file or one logical unit. No multi-file tasks.

---

## Phase 1: Multi-Agent Backend — Database & Models (Week 1)

### 1.1 Database Schema & Migrations

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 1.1.1 | Create `Agent` SQLAlchemy model in `models.py` — all columns per spec (id, account_id, display_name, api_key, api_key_hash, starting_balance, llm_model, framework, strategy_tags, risk_profile, avatar_url, color, status, created_at, updated_at) | `src/database/models.py` | — | [x] |
| 1.1.2 | Create Alembic migration `007_create_agents_table.py` — agents table + indexes (idx_agents_account, idx_agents_api_key, idx_agents_status). **Additive only — no changes to existing tables yet.** | `alembic/versions/007_create_agents_table.py` | 1.1.1 | [x] |
| 1.1.3 | Create data migration script `scripts/migrate_accounts_to_agents.py` — for each existing account, create an agent row copying api_key, api_key_hash, starting_balance, risk_profile. Print report of migrated rows. **Script only — not an Alembic migration** (run manually with verification). | `scripts/migrate_accounts_to_agents.py` | 1.1.2 | [x] |
| 1.1.4 | Create Alembic migration `008_add_agent_id_to_trading_tables.py` — add nullable `agent_id` (UUID, FK → agents.id) column to: balances, orders, trades, positions, trading_sessions, portfolio_snapshots. **Do NOT drop account_id yet.** | `alembic/versions/008_add_agent_id_to_trading_tables.py` | 1.1.2 | [x] |
| 1.1.5 | Create data backfill script `scripts/backfill_agent_ids.py` — for each row in balances/orders/trades/positions/trading_sessions/portfolio_snapshots, set `agent_id` by looking up the agent created from that account_id. Verify zero NULLs remain. | `scripts/backfill_agent_ids.py` | 1.1.3, 1.1.4 | [x] |
| 1.1.6 | Create Alembic migration `009_enforce_agent_id_not_null.py` — set `agent_id` to NOT NULL on all trading tables. Add FK constraints. Keep `account_id` columns for now (will be dropped later after code changes). | `alembic/versions/009_enforce_agent_id_not_null.py` | 1.1.5 | [x] |
| 1.1.7 | Verify migrations: run `alembic upgrade head` on clean DB, run data migration scripts, verify all constraints pass. Document in this file. | — | 1.1.6 | [x] |

### 1.2 Agent Repository & Service

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 1.2.1 | Create `AgentRepository` — CRUD operations: create, get_by_id, get_by_api_key, list_by_account, update, archive, hard_delete, count_by_account. All async, use existing repository patterns from `account_repo.py`. | `src/database/repositories/agent_repo.py` | 1.1.1 | [x] |
| 1.2.2 | Create `AgentService` — business logic: create_agent (generate API key, create agent + initial USDT balance), get_agent, list_agents, update_agent, clone_agent, reset_agent (archive history + fresh wallet), archive_agent, delete_agent, regenerate_api_key. Follow patterns from `accounts/service.py`. | `src/agents/service.py` (new dir `src/agents/`) | 1.2.1 | [x] |
| 1.2.3 | Create `src/agents/__init__.py` — empty init file for the agents package | `src/agents/__init__.py` | — | [x] |
| 1.2.4 | Create auto-avatar generator — generate identicon-style SVG or PNG from agent_id hash. Simple deterministic color-block avatar. | `src/agents/avatar_generator.py` | — | [x] |
| 1.2.5 | Create Pydantic schemas for agents — `AgentCreate`, `AgentUpdate`, `AgentResponse`, `AgentListResponse`, `AgentOverviewResponse`, `AgentCredentials` (shown once on creation). | `src/api/schemas/agents.py` | 1.2.2 | [x] |
| 1.2.6 | Add agent dependency aliases to `dependencies.py` — `AgentRepoDep`, `AgentServiceDep`. Follow existing patterns (lazy imports inside functions). | `src/dependencies.py` | 1.2.1, 1.2.2 | [x] |

### 1.3 Auth Middleware Update

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 1.3.1 | Update `_resolve_account_from_api_key()` in auth middleware — lookup API key in `agents` table instead of `accounts`. Set `request.state.agent` AND `request.state.account` (via agent.account_id). Existing code that reads `request.state.account` continues to work. | `src/api/middleware/auth.py` | 1.1.2, 1.2.1 | [x] |
| 1.3.2 | Add `get_current_agent()` dependency — returns `request.state.agent`. Create `CurrentAgentDep` type alias. For JWT auth (web UI), resolve agent from `X-Agent-Id` header or query param. | `src/api/middleware/auth.py`, `src/dependencies.py` | 1.3.1 | [x] |
| 1.3.3 | Update `get_current_account()` — ensure it still works for both API key (via agent → account) and JWT auth paths. No breaking changes to existing route signatures. | `src/api/middleware/auth.py` | 1.3.1 | [x] |

### 1.4 Agent API Endpoints

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 1.4.1 | Create agent management routes — `POST /api/v1/agents`, `GET /api/v1/agents`, `GET /api/v1/agents/{agent_id}`, `PUT /api/v1/agents/{agent_id}`, `POST /api/v1/agents/{agent_id}/clone`, `POST /api/v1/agents/{agent_id}/reset`, `POST /api/v1/agents/{agent_id}/archive`, `DELETE /api/v1/agents/{agent_id}`, `POST /api/v1/agents/{agent_id}/regenerate-key`. JWT auth only. | `src/api/routes/agents.py` | 1.2.2, 1.2.5, 1.2.6 | [x] |
| 1.4.2 | Create agent overview routes — `GET /api/v1/agents/overview` (all agents with live equity, PnL, status), `GET /api/v1/agents/compare` (side-by-side for selected agents). | `src/api/routes/agents.py` | 1.4.1 | [x] |
| 1.4.3 | Create `GET /api/v1/agents/{agent_id}/skill.md` — download agent-specific skill.md with injected API key. | `src/api/routes/agents.py` | 1.4.1 | [x] |
| 1.4.4 | Register agent routes in `create_app()` — add router to FastAPI app. | `src/main.py` | 1.4.1 | [x] |

### 1.5 Update Existing Services for Agent Scoping

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 1.5.1 | Update `BalanceManager` — accept `agent_id` instead of (or in addition to) `account_id` for all balance operations. Dual-support during transition. | `src/accounts/balance_manager.py` | 1.1.4 | [x] |
| 1.5.2 | Update `OrderEngine` — use `agent_id` for order creation and lookups. The agent's `risk_profile` is used instead of account's. | `src/order_engine/engine.py` | 1.5.1 | [x] |
| 1.5.3 | Update `RiskManager` — read `risk_profile` from agent instead of account. Same validation logic, different source. | `src/risk/manager.py` | 1.3.1 | [x] |
| 1.5.4 | Update `PortfolioTracker` — scope all calculations to `agent_id`. | `src/portfolio/tracker.py` | 1.5.1 | [x] |
| 1.5.5 | Update existing trade/order routes — resolve agent from request context and pass `agent_id` to services. No breaking changes to API contract (agents still use same endpoints with their API key). | `src/api/routes/trade.py`, `src/api/routes/account.py` | 1.3.2, 1.5.1–1.5.4 | [x] |
| 1.5.6 | Update all repository classes — add `agent_id` versions of query methods (e.g., `get_balances_by_agent`, `get_orders_by_agent`). Keep old methods during transition. | `src/database/repositories/*.py` | 1.1.6 | [x] |

### 1.6 Phase 1 Testing & Verification

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 1.6.1 | Write unit tests for `AgentRepository` — CRUD, list, archive, delete, api_key lookup. | `tests/unit/test_agent_repo.py` | 1.2.1 | [x] |
| 1.6.2 | Write unit tests for `AgentService` — create, clone, reset, regenerate key. Mock repository. | `tests/unit/test_agent_service.py` | 1.2.2 | [x] |
| 1.6.3 | Write unit tests for updated auth middleware — API key resolves to agent, JWT resolves to account, agent context is set. | `tests/unit/test_auth_middleware_agents.py` | 1.3.1 | [x] |
| 1.6.4 | Update ALL existing tests that reference `account_id` in trading contexts — ensure they work with the new agent model. Fix any failures. | `tests/unit/*.py`, `tests/integration/*.py` | 1.5.1–1.5.6 | [x] |
| 1.6.5 | Run full test suite — `pytest tests/` — MUST be zero failures before Phase 2. | — | 1.6.1–1.6.4 | [x] |
| 1.6.6 | Run `ruff check src/ tests/` — zero lint errors. | — | 1.6.5 | [x] |
| 1.6.7 | Run `mypy src/` — zero type errors. | — | 1.6.5 | [x] |

---

## Phase 2: Multi-Agent UI (Week 2–3)

### 2.1 Agent Store & Hooks

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 2.1.1 | Create `agent-store.ts` — Zustand store: `activeAgentId`, `agents[]`, `setActiveAgent()`, `isLoading`. Persist `activeAgentId` to localStorage. | `Frontend/src/stores/agent-store.ts` | Phase 1 complete | [x] |
| 2.1.2 | Create `use-agents.ts` — TanStack Query hooks: `useAgents()` (list), `useAgent(id)` (detail), `useCreateAgent()`, `useUpdateAgent()`, `useCloneAgent()`, `useResetAgent()`, `useArchiveAgent()`, `useDeleteAgent()`, `useRegenerateKey()`. | `Frontend/src/hooks/use-agents.ts` | 2.1.1 | [x] |
| 2.1.3 | Create `use-active-agent.ts` — combines Zustand store + TanStack Query. Returns active agent data, loading state, switch function. Auto-fetches agent list on mount. | `Frontend/src/hooks/use-active-agent.ts` | 2.1.1, 2.1.2 | [x] |
| 2.1.4 | Create `use-agent-overview.ts` — TanStack Query hook for `GET /api/v1/agents/overview`. | `Frontend/src/hooks/use-agent-overview.ts` | 2.1.2 | [x] |

### 2.2 Agent UI Components

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 2.2.1 | Create `AgentAvatar` — renders auto-generated identicon or custom uploaded image. Fallback to initials. | `Frontend/src/components/agents/agent-avatar.tsx` | — | [x] |
| 2.2.2 | Create `AgentColorDot` — small colored circle using agent's assigned hex color. | `Frontend/src/components/agents/agent-color-dot.tsx` | — | [x] |
| 2.2.3 | Create `AgentStatusBadge` — status indicator: Trading (green), Idle (yellow), Disconnected (red), Archived (gray). | `Frontend/src/components/agents/agent-status-badge.tsx` | — | [x] |
| 2.2.4 | Create `AgentCard` — full card: avatar, name, color dot, LLM badge, framework badge, strategy tags, live equity, PnL %, trades, win rate, mini sparkline, status, last active. Click → switch agent. | `Frontend/src/components/agents/agent-card.tsx` | 2.2.1, 2.2.2, 2.2.3 | [x] |
| 2.2.5 | Create `AgentFilters` — sort by (name, equity, PnL, trades, win rate, last active), filter by (status, framework, model), toggle archived. | `Frontend/src/components/agents/agent-filters.tsx` | — | [x] |
| 2.2.6 | Create `AgentGrid` — responsive grid of AgentCards with loading skeletons and empty state. | `Frontend/src/components/agents/agent-grid.tsx` | 2.2.4, 2.2.5 | [x] |
| 2.2.7 | Create `AgentCreateModal` — modal form: name (required), starting balance, LLM model dropdown + custom, framework dropdown + custom, strategy tags, color picker, avatar upload. Shows API key once on success. | `Frontend/src/components/agents/agent-create-modal.tsx` | 2.1.2 | [x] |
| 2.2.8 | Create `AgentEditDrawer` — edit name/model/framework/tags/color/avatar, API key management (masked + regenerate), risk sliders, clone/archive/delete buttons. | `Frontend/src/components/agents/agent-edit-drawer.tsx` | 2.1.2 | [x] |

### 2.3 Agent Switcher & Navigation

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 2.3.1 | Create `AgentSwitcher` — dropdown at top of sidebar: current agent name + color dot + chevron. Dropdown shows all active agents with name, color dot, equity, status. Footer: "+ Create New Agent", "Manage Agents". | `Frontend/src/components/layout/agent-switcher.tsx` | 2.1.3, 2.2.1, 2.2.2, 2.2.3 | [x] |
| 2.3.2 | Update sidebar — add AgentSwitcher below logo, add "Agents" nav item (Grid icon, `/agents`), add "Battles" nav item (Swords icon, `/battles`). | `Frontend/src/components/layout/sidebar.tsx` | 2.3.1 | [x] |
| 2.3.3 | Update `api-client.ts` — inject `X-Agent-Id` header for JWT-authenticated requests using `activeAgentId` from agent-store. | `Frontend/src/lib/api-client.ts` | 2.1.1 | [x] |

### 2.4 Agents Page

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 2.4.1 | Create `/agents` page — assemble AgentGrid + AgentFilters + "Create New Agent" button + AgentCreateModal. Cross-agent view (not scoped to active agent). | `Frontend/src/app/(dashboard)/agents/page.tsx` | 2.2.6, 2.2.7 | [x] |
| 2.4.2 | Create agents loading skeleton. | `Frontend/src/app/(dashboard)/agents/loading.tsx` | — | [x] |

### 2.5 Re-scope Existing Pages

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 2.5.1 | Update `use-account.ts` — include `activeAgentId` in all TanStack Query keys so data refetches on agent switch. | `Frontend/src/hooks/use-account.ts` | 2.1.1 | [x] |
| 2.5.2 | Update `use-trades.ts` — include `activeAgentId` in query keys. | `Frontend/src/hooks/use-trades.ts` | 2.1.1 | [x] |
| 2.5.3 | Update `use-analytics.ts` — include `activeAgentId` in query keys. | `Frontend/src/hooks/use-analytics.ts` | 2.1.1 | [x] |
| 2.5.4 | Update WebSocket subscriptions — scope by active agent (orders, portfolio channels). | `Frontend/src/stores/websocket-store.ts` | 2.1.1 | [x] |
| 2.5.5 | Split settings page — "Account Settings" tab (email, password, display name, theme) + "Agent Settings" tab (API key, risk config, reset/clone/archive). Agent tab changes with agent switcher. | `Frontend/src/app/(dashboard)/settings/page.tsx` | 2.1.3, 2.2.8 | [x] |
| 2.5.6 | Verify all existing pages work with agent scoping — dashboard, wallet, trades, analytics. Manual + automated check. | — | 2.5.1–2.5.5 | [x] |

### 2.6 Phase 2 Verification

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 2.6.1 | Run `pnpm build` in Frontend — zero TypeScript errors. | — | All Phase 2 | [x] |
| 2.6.2 | Verify agent switcher dropdown works end-to-end (create agent → switch → see different data). | — | 2.6.1 | [x] |

---

## Phase 3: Battle Backend (Week 3–4)

### 3.1 Battle Database Schema

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 3.1.1 | Add `Battle`, `BattleParticipant`, `BattleSnapshot` SQLAlchemy models to `models.py` — all columns per spec. BattleSnapshot is a TimescaleDB hypertable. | `src/database/models.py` | Phase 1 complete | [x] |
| 3.1.2 | Create Alembic migration `010_create_battle_tables.py` — battles + battle_participants + battle_snapshots tables with all indexes. `SELECT create_hypertable('battle_snapshots', 'timestamp')`. | `alembic/versions/010_create_battle_tables.py` | 3.1.1 | [x] |

### 3.2 Battle Repository & Service

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 3.2.1 | Create `BattleRepository` — CRUD for battles, participants, snapshots. Methods: create_battle, get_battle, list_battles, update_status, add_participant, remove_participant, get_participants, insert_snapshot, get_snapshots (paginated time-series). | `src/database/repositories/battle_repo.py` | 3.1.1 | [x] |
| 3.2.2 | Create `src/battles/__init__.py` | `src/battles/__init__.py` | — | [x] |
| 3.2.3 | Create `BattleService` — full lifecycle: create_battle, add/remove participants, start (lock config, snapshot wallets), pause/resume agent, stop (force-close positions, calculate rankings), cancel. State machine enforcement (draft→pending→active→completed). | `src/battles/service.py` | 3.2.1 | [x] |
| 3.2.4 | Create `SnapshotEngine` — Celery beat task that runs every 5 seconds for each active battle. Records equity, unrealized PnL, realized PnL, trade count, open positions for each participant. | `src/battles/snapshot_engine.py` | 3.2.1 | [x] |
| 3.2.5 | Create `RankingCalculator` — calculate final rankings for all 5 metrics: ROI %, Total PnL, Sharpe Ratio (from equity curve), Win Rate, Profit Factor. | `src/battles/ranking.py` | 3.2.1 | [x] |
| 3.2.6 | Create `WalletManager` — fresh wallet mode: snapshot agent's current state, provision isolated battle wallet, restore on battle end. Existing wallet mode: no-op (observation layer). | `src/battles/wallet_manager.py` | 1.2.1 | [x] |
| 3.2.7 | Create battle preset configurations — Quick Sprint, Day Trader, Marathon, Scalper Duel, Survival Mode as data constants. | `src/battles/presets.py` | — | [x] |

### 3.3 Battle API & WebSocket

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 3.3.1 | Create Pydantic schemas — `BattleCreate`, `BattleUpdate`, `BattleResponse`, `BattleListResponse`, `BattleParticipantResponse`, `BattleLiveResponse`, `BattleResultsResponse`, `BattleReplayResponse`, `BattlePresetResponse`. | `src/api/schemas/battles.py` | 3.2.3 | [x] |
| 3.3.2 | Create battle routes — all 16 endpoints from spec: CRUD, participant management, start/pause/resume/stop, live snapshot, results, replay. JWT auth only. | `src/api/routes/battles.py` | 3.2.3, 3.3.1 | [x] |
| 3.3.3 | Add battle dependency aliases to `dependencies.py` — `BattleRepoDep`, `BattleServiceDep`. | `src/dependencies.py` | 3.2.1, 3.2.3 | [x] |
| 3.3.4 | Register battle routes in `create_app()`. | `src/main.py` | 3.3.2 | [x] |
| 3.3.5 | Build battle WebSocket channel — handler for `subscribe` to `battle` channel. Broadcast `battle:update` (every 1-2s), `battle:trade` (on any participant trade), `battle:status` (state changes, lead changes, blown up, completed). | `src/api/websocket/channels.py` (BattleChannel added) | 3.2.4 | [x] |
| 3.3.6 | Implement auto-completion logic — timer expiry triggers battle stop, force-close all positions at market price, calculate rankings. Celery task. | `src/tasks/battle_snapshots.py` | 3.2.3, 3.2.5 | [x] |

### 3.4 Phase 3 Testing

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 3.4.1 | Unit tests for `BattleRepository`. | `tests/unit/test_battle_repo.py` | 3.2.1 | [x] |
| 3.4.2 | Unit tests for `BattleService` — lifecycle state machine, pause/resume, start/stop. | `tests/unit/test_battle_service.py` | 3.2.3 | [x] |
| 3.4.3 | Unit tests for `SnapshotEngine`. | `tests/unit/test_snapshot_engine.py` | 3.2.4 | [x] |
| 3.4.4 | Unit tests for `RankingCalculator` — all 5 metrics. | `tests/unit/test_battle_ranking.py` | 3.2.5 | [x] |
| 3.4.5 | Unit tests for `WalletManager` — snapshot/restore, isolation. | `tests/unit/test_wallet_manager.py` | 3.2.6 | [x] |
| 3.4.6 | Integration tests for battle WebSocket channel. | `tests/integration/test_battle_websocket.py` | 3.3.5 | [x] |
| 3.4.7 | Run full test suite — zero failures. | — | 3.4.1–3.4.6 | [x] |
| 3.4.8 | Lint + type check pass. | — | 3.4.7 | [x] |

---

## Phase 4: Battle UI — List & Creation (Week 4–5)

### 4.1 Battle Store & Hooks

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 4.1.1 | Create `battle-store.ts` — Zustand: active battle state, live WS participant data, connection status. | `Frontend/src/stores/battle-store.ts` | Phase 3 complete | [x] |
| 4.1.2 | Create `use-battles.ts` — TanStack Query: `useBattles()` (list with filters), `useBattle(id)`, `useCreateBattle()`, `useUpdateBattle()`, `useDeleteBattle()`, `useAddParticipant()`, `useRemoveParticipant()`, `useStartBattle()`, `usePauseAgent()`, `useResumeAgent()`, `useStopBattle()`. | `Frontend/src/hooks/use-battles.ts` | 4.1.1 | [x] |

### 4.2 Battle List Components

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 4.2.1 | Create `BattleCard` — battle summary: name, status badge, participant count + stacked avatars, duration, date, winner (if completed). | `Frontend/src/components/battles/battle-card.tsx` | 2.2.1 | [x] |
| 4.2.2 | Create `BattleGrid` — responsive grid of BattleCards with loading skeletons, empty state, filters (status, date range), sort (date, duration, participants). | `Frontend/src/components/battles/battle-grid.tsx` | 4.2.1 | [x] |

### 4.3 Battle Creation Wizard

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 4.3.1 | Create `BattlePresetPicker` — visual cards for each preset (Quick Sprint, Day Trader, Marathon, Scalper Duel, Survival Mode, Custom). Shows duration, balance, pairs, description. | `Frontend/src/components/battles/battle-preset-picker.tsx` | — | [x] |
| 4.3.2 | Create `BattleCreateWizard` — 4-step wizard: (1) Choose preset/custom, (2) Select agents multi-select, (3) Configure rules (duration, balance, pairs, ranking metric), (4) Review + Start. | `Frontend/src/components/battles/battle-create-wizard.tsx` | 4.3.1, 4.1.2, 2.1.2 | [x] |

### 4.4 Battles Page

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 4.4.1 | Create `/battles` page — BattleGrid + "+ New Battle" button + BattleCreateWizard. Cross-agent view. | `Frontend/src/app/(dashboard)/battles/page.tsx` | 4.2.2, 4.3.2 | [x] |
| 4.4.2 | Create battles loading skeleton. | `Frontend/src/app/(dashboard)/battles/loading.tsx` | — | [x] |
| 4.4.3 | Run `pnpm build` — zero TypeScript errors. | — | 4.4.1 | [x] |

---

## Phase 5: Battle Live Dashboard (Week 5–6)

### 5.1 Live Data Hook

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 5.1.1 | Create `use-battle-live.ts` — WebSocket integration: subscribe to `battle` channel, parse `battle:update`, `battle:trade`, `battle:status` events, update battle-store. Auto-reconnect. | `Frontend/src/hooks/use-battle-live.ts` | 4.1.1 | [x] |

### 5.2 Live Dashboard Components

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 5.2.1 | Create `BattleTopBar` — battle name, timer/countdown, status badge, participant count, ranking metric label, control buttons (Pause All / Resume All / End Battle). | `Frontend/src/components/battles/battle-top-bar.tsx` | 4.1.2 | [x] |
| 5.2.2 | Create `BattleAgentCard` — individual participant: avatar, name, color, rank badge (#1 gold, #2 silver, #3 bronze), LLM/framework badges, live equity, PnL %, trades + win rate, mini sparkline, status pulse, pause/resume button. | `Frontend/src/components/battles/battle-agent-card.tsx` | 2.2.1, 2.2.2, 2.2.3 | [x] |
| 5.2.3 | Create `BattleAgentCards` — horizontal scrollable row of BattleAgentCards. | `Frontend/src/components/battles/battle-agent-cards.tsx` | 5.2.2 | [x] |
| 5.2.4 | Create `EquityRaceChart` — overlaid multi-line Recharts LineChart. All agents on same time axis, distinct colors, auto-scroll, crosshair hover. The centerpiece visualization. | `Frontend/src/components/battles/equity-race-chart.tsx` | 5.1.1 | [x] |
| 5.2.5 | Create `PnlComparisonBars` — grouped bar chart: realized PnL, unrealized PnL, total PnL per agent. Live updates. | `Frontend/src/components/battles/pnl-comparison-bars.tsx` | 5.1.1 | [x] |
| 5.2.6 | Create `BattleTradeFeed` — unified chronological feed of all trades from all agents. Color-coded by agent color. Agent name, BUY/SELL badge, pair, qty, price, PnL. New trades animate in. Filter by agent. | `Frontend/src/components/battles/battle-trade-feed.tsx` | 5.1.1 | [x] |
| 5.2.7 | Create `StrategyHeatmap` — grid: rows = agents, columns = pairs. Cells = PnL color-coded (red → green). | `Frontend/src/components/battles/strategy-heatmap.tsx` | 5.1.1 | [x] |
| 5.2.8 | Create `RiskRadarChart` — overlaid Recharts RadarChart. 5 axes: position concentration, drawdown depth, trade frequency, win rate, avg hold time. | `Frontend/src/components/battles/risk-radar-chart.tsx` | 5.1.1 | [x] |
| 5.2.9 | Create `BattleMetricsTable` — full sortable table: rank, agent, equity, PnL $, PnL %, trades, win rate, Sharpe, max DD, profit factor, avg duration, best trade, worst trade. | `Frontend/src/components/battles/battle-metrics-table.tsx` | 5.1.1 | [x] |
| 5.2.10 | Create `AgentDeepDiveModal` — full modal with agent's individual dashboard. Reuse existing dashboard components (equity chart, positions, recent trades, allocation, risk). Scoped to battle participant. | `Frontend/src/components/battles/agent-deep-dive-modal.tsx` | 5.1.1 | [x] |

### 5.3 Live Battle Page

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 5.3.1 | Create `/battles/[id]` page — assemble: BattleTopBar + BattleAgentCards row + tabbed main area (Equity Race, PnL Comparison, Trade Feed, Strategy Heatmap, Risk Radar) + BattleMetricsTable bottom section. | `Frontend/src/app/(dashboard)/battles/[id]/page.tsx` | 5.2.1–5.2.10 | [x] |
| 5.3.2 | Create battle detail loading skeleton. | `Frontend/src/app/(dashboard)/battles/[id]/loading.tsx` | — | [x] |
| 5.3.3 | Run `pnpm build` — zero TypeScript errors. | — | 5.3.1 | [x] |

---

## Phase 6: Battle Results & Polish (Week 6–7)

### 6.1 Results & Replay

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 6.1.1 | Create `use-battle-replay.ts` — playback state machine: play, pause, scrub, speed (1x/2x/5x/10x). Uses battle_snapshots time-series data. Drives chart + cards animation. | `Frontend/src/hooks/use-battle-replay.ts` | 4.1.2 | [x] |
| 6.1.2 | Create `BattlePodium` — top 3 agents on podium (#1 center tallest, #2 left, #3 right). Name, avatar, final equity, PnL %, metric value. Gold/silver/bronze. Confetti on first load. | `Frontend/src/components/battles/battle-podium.tsx` | — | [x] |
| 6.1.3 | Create `BattleTimeline` — chronological timeline of key moments: lead changes, biggest/worst trades, agents blown up, max drawdown, pause/resume events. | `Frontend/src/components/battles/battle-timeline.tsx` | — | [x] |
| 6.1.4 | Create `BattleReplayControls` — play/pause/scrub bar + speed selector + key moment markers on scrubber. Controls the equity race chart replay. | `Frontend/src/components/battles/battle-replay-controls.tsx` | 6.1.1 | [x] |

### 6.2 Export & Rematch

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 6.2.1 | Build export functionality — CSV trade history (all participants), CSV equity snapshots, JSON complete battle data. Download buttons on results page. | `Frontend/src/components/battles/battle-export.tsx` or inline in results | 5.3.1 | [x] |
| 6.2.2 | Build "Rematch" button — clones battle config into new draft battle. | Inline in `/battles/[id]` page | 4.1.2 | [x] |

### 6.3 Results View Integration

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 6.3.1 | Update `/battles/[id]` page — detect completed status → show results view: BattlePodium + final standings table + BattleTimeline + replay section (EquityRaceChart + BattleReplayControls) + export buttons + Rematch. | `Frontend/src/app/(dashboard)/battles/[id]/page.tsx` | 6.1.2, 6.1.3, 6.1.4, 6.2.1, 6.2.2 | [x] |

### 6.4 Notifications

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 6.4.1 | Add battle notification events — agent took lead, agent blown up, battle completed, agent idle 5+ min. Integrate with existing notification system. | Backend: `src/battles/service.py`, Frontend: notification store | 3.2.3 | [x] |

### 6.5 Polish & Responsive

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 6.5.1 | Responsive design pass — all agent management pages (mobile + tablet). | Various agent components | Phase 2 complete | [x] |
| 6.5.2 | Responsive design pass — all battle pages (mobile + tablet). | Various battle components | Phase 5, 6.3 complete | [x] |
| 6.5.3 | Error boundaries — add error boundaries for agents page, battles page, battle detail page. | Various page files | All phases | [x] |
| 6.5.4 | Empty states — design empty states for: no agents yet, no battles yet, battle with no participants. | Various components | All phases | [x] |

### 6.6 Final Cleanup

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 6.6.1 | Create Alembic migration `011_drop_account_trading_columns.py` — drop `api_key`, `api_key_hash`, `api_secret_hash`, `starting_balance`, `risk_profile` from `accounts` table. Drop `account_id` from trading tables (keeping `agent_id` only). **Only after all code is updated.** | `alembic/versions/011_drop_account_trading_columns.py` | All phases complete | [x] |
| 6.6.2 | Remove old account-trading code paths — delete dual-support methods, remove `account_id` lookups in repositories. | Various service/repo files | 6.6.1 | [x] |
| 6.6.3 | Final full test suite — `pytest tests/` zero failures. | — | 6.6.2 | [x] |
| 6.6.4 | Final lint + type check — `ruff check src/ tests/` + `mypy src/` zero errors. | — | 6.6.3 | [x] |
| 6.6.5 | Final `pnpm build` — zero TypeScript errors. | — | 6.6.4 | [x] |

### 6.7 Documentation Updates

| # | Task | File(s) | Depends On | Status |
|---|------|---------|------------|--------|
| 6.7.1 | Update `CLAUDE.md` — add multi-agent model description, new component directories, new dependency aliases, new Alembic migrations. | `CLAUDE.md` | All phases | [x] |
| 6.7.2 | Update `docs/skill.md` — document per-agent API key model, battle endpoints. | `docs/skill.md` | All phases | [x] |

---

## Task Summary

| Phase | Tasks | Description |
|-------|-------|-------------|
| Phase 1 | 30 tasks | Multi-Agent Backend (DB, models, auth, service, API, tests) |
| Phase 2 | 22 tasks | Multi-Agent UI (store, hooks, components, page, re-scope) |
| Phase 3 | 20 tasks | Battle Backend (DB, service, snapshots, ranking, WS, tests) |
| Phase 4 | 9 tasks | Battle UI List & Creation (store, hooks, components, wizard) |
| Phase 5 | 15 tasks | Battle Live Dashboard (WebSocket, charts, tables, page) |
| Phase 6 | 17 tasks | Results, Replay, Polish, Cleanup, Documentation |
| **Total** | **113 tasks** | |

---

## Working Rules

1. **One file at a time.** Create/modify one file, verify it works, then proceed.
2. **Tests after each sub-phase.** Never accumulate untested code.
3. **Migrations are separate from code changes.** Run and verify migrations independently.
4. **Auth changes are the highest-risk item.** Test extensively before and after.
5. **Frontend changes must not break existing pages.** Verify all pages after re-scoping.
6. **The battle plan is the authority.** All names, schemas, endpoints match exactly.
7. **Dual-support during transition.** Old `account_id` paths work until final cleanup (Phase 6.6).
8. **No shortcuts on wallet isolation.** Battle wallet management must be transactionally safe.
