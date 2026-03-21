---
type: research-report
title: "Agents + Backtesting + Battles: Integration Research"
status: archived
phase: integration
tags:
  - research
  - integration
---

# Agents + Backtesting + Battles: Integration Research

> **Author:** Head Developer
> **Date:** 2026-03-17
> **Status:** Research & Proposal
> **Branch:** V.0.0.2

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture: Current State](#2-system-architecture-current-state)
   - 2.1 [Agents System](#21-agents-system)
   - 2.2 [Backtesting System](#22-backtesting-system)
   - 2.3 [Battle System](#23-battle-system)
3. [How the Three Systems Interact (or Don't)](#3-how-the-three-systems-interact-or-dont)
4. [Gap Analysis](#4-gap-analysis)
5. [Proposed Improvements](#5-proposed-improvements)
   - 5.1 [P0: Agent-Scoped Backtesting](#51-p0-agent-scoped-backtesting)
   - 5.2 [P1: Historical Battles (Backtesting Battles)](#52-p1-historical-battles-backtesting-battles)
   - 5.3 [P1: Shared Metrics Pipeline](#53-p1-shared-metrics-pipeline)
   - 5.4 [P1: Risk Profile Integration in Backtesting](#54-p1-risk-profile-integration-in-backtesting)
   - 5.5 [P1: Fix SnapshotEngine Unrealized PnL](#55-p1-fix-snapshotengine-unrealized-pnl)
   - 5.6 [P2: Battle Replay from Historical Data](#56-p2-battle-replay-from-historical-data)
6. [Implementation Sequencing](#6-implementation-sequencing)
7. [Risk & Considerations](#7-risk--considerations)

---

## 1. Executive Summary

Our platform has three major subsystems built across separate development phases:

| System | Phase Built | Scoping | Trading Mode |
|--------|-------------|---------|--------------|
| **Agents** | Phase 1-2 | `agent_id` (fully scoped) | Live trading |
| **Backtesting** | Pre-agents | `account_id` (legacy) | Historical replay (in-memory sandbox) |
| **Battles** | Phase 3-6 | `agent_id` (via participants) | Live trading only |

**The core problem:** Backtesting was built before the multi-agent architecture and remains account-scoped. Battles only support live trading. These two systems don't talk to each other at all — zero shared code, zero integration.

**What this means for users:**
- An agent cannot own its own backtests — all backtests belong to the account
- There's no way to run a historical battle (agents competing on past data)
- Metrics are calculated differently in backtesting vs battles (duplicated, divergent code)
- Backtesting ignores agent risk profiles entirely
- Battle snapshots report `unrealized_pnl = 0` (hardcoded placeholder)

---

## 2. System Architecture: Current State

### 2.1 Agents System

**Key Files:**
| File | Purpose |
|------|---------|
| `src/database/models.py` (L337-400) | `Agent` ORM model |
| `src/agents/service.py` | AgentService — create, clone, reset, archive, regenerate key |
| `src/agents/avatar_generator.py` | Deterministic SVG identicon from UUID |
| `src/api/routes/agents.py` | 15 REST endpoints (JWT auth only) |
| `src/api/middleware/auth.py` | Dual auth: API key → agents table first, JWT + X-Agent-Id header |
| `src/database/repositories/agent_repo.py` | CRUD, api_key lookup, list/archive/delete |

**Agent Model:**
```
Agent
├── id: UUID (PK)
├── account_id: UUID (FK → accounts, CASCADE)
├── display_name: str
├── api_key / api_key_hash: str (bcrypt, "ak_live_" prefix)
├── starting_balance: Decimal(20,8)
├── llm_model: str | None (e.g., "claude-opus-4")
├── framework: str | None (e.g., "langchain")
├── strategy_tags: list[str] (JSONB)
├── risk_profile: dict (JSONB — per-agent risk overrides)
├── avatar_url: str (SVG data-URI)
├── color: str (hex)
├── status: "active" | "paused" | "archived"
└── created_at / updated_at
```

**Agent Scoping in Trading:**
All trading tables (`balances`, `orders`, `trades`, `positions`, `portfolio_snapshots`) have `agent_id NOT NULL` as FK to `agents.id`. This means:

- Each agent has its own isolated wallet (Balance rows keyed by `agent_id + asset`)
- Orders and trades are tagged with `agent_id` at creation
- Portfolio queries filter by `agent_id`
- Risk validation uses agent's `risk_profile` JSONB overrides

**How services accept agent context:**
```python
# BalanceManager
async def credit(account_id, asset, amount, agent_id=None)
async def get_balance(account_id, asset, agent_id=None)

# OrderEngine
async def place_order(account_id, order, agent_id=None)

# RiskManager
async def validate_order(account_id, order, agent=None)  # Full Agent object for risk_profile

# PortfolioTracker
async def get_portfolio(account_id, agent_id=None)
```

**Auth Flow:**
1. **API Key** (`X-API-Key`): Tries `agents` table first → resolves owning account. Sets both `request.state.account` and `request.state.agent`.
2. **JWT** (`Authorization: Bearer`): Resolves account from JWT. Agent comes from optional `X-Agent-Id` header.

---

### 2.2 Backtesting System

**Key Files:**
| File | Purpose |
|------|---------|
| `src/backtesting/engine.py` | `BacktestEngine` — orchestrator, manages active sessions (singleton) |
| `src/backtesting/sandbox.py` | `BacktestSandbox` — in-memory exchange (balances, orders, positions) |
| `src/backtesting/time_simulator.py` | `TimeSimulator` — virtual clock, steps through time range |
| `src/backtesting/data_replayer.py` | `DataReplayer` — loads prices from TimescaleDB + candles_backfill |
| `src/backtesting/results.py` | Metrics: Sharpe, Sortino, drawdown, win rate, profit factor |
| `src/api/routes/backtest.py` | All backtest REST endpoints |
| `src/database/repositories/backtest_repo.py` | DB persistence (sessions, trades, snapshots) |

**How Backtesting Works:**
```
1. POST /backtest/create  →  Create session in DB (account_id owner)
2. POST /backtest/{id}/start  →  Initialize sandbox, preload ALL price data
3. POST /backtest/{id}/step  →  Advance virtual clock one candle interval
   ├── TimeSimulator advances clock
   ├── DataReplayer loads prices at new virtual_time (from cache)
   └── BacktestSandbox checks pending orders against new prices
4. POST /backtest/{id}/trade/order  →  Place order in sandbox
5. [repeat steps 3-4 until all candles consumed]
6. Auto-complete → persist results, trades, snapshots to DB
```

**BacktestSandbox (in-memory exchange):**
- Completely isolated from live trading infrastructure
- Own balance tracking, order matching, position management
- Applies fees (0.1%) and slippage
- Produces `SandboxTrade` and `SandboxSnapshot` dataclasses
- **Does NOT use:** RiskManager, BalanceManager, OrderEngine, Redis, or any live service

**Data Flow:**
```
TimescaleDB (candles_1m + candles_backfill)
    → DataReplayer.preload_range() [single SQL UNION query]
    → In-memory price cache (dict[symbol, dict[timestamp, price]])
    → DataReplayer.load_prices(virtual_time) [O(log n) bisect lookup]
    → BacktestSandbox.update_prices() → order matching
```

**Look-Ahead Prevention:** `WHERE bucket <= virtual_clock` on every query. Agent can never see future prices.

**DB Models (account-scoped):**
```
BacktestSession
├── id: UUID (PK)
├── account_id: UUID (FK → accounts)  ← NO agent_id!
├── strategy_label, status, config fields
├── progress: virtual_clock, current_step, total_steps
└── results: final_equity, roi_pct, metrics JSONB

BacktestTrade (FK → session, CASCADE)
├── session_id → scoped via session, not agent

BacktestSnapshot (FK → session, CASCADE, TimescaleDB hypertable)
├── session_id → scoped via session, not agent
```

---

### 2.3 Battle System

**Key Files:**
| File | Purpose |
|------|---------|
| `src/battles/service.py` | `BattleService` — lifecycle: create, start, pause, stop, cancel |
| `src/battles/snapshot_engine.py` | `SnapshotEngine` — captures equity every 5s (Celery beat) |
| `src/battles/ranking.py` | `RankingCalculator` — ROI, PnL, Sharpe, Win Rate, Profit Factor, Max DD |
| `src/battles/wallet_manager.py` | `WalletManager` — fresh wallet snapshot/restore |
| `src/battles/presets.py` | 5 presets: Quick Sprint, Day Trader, Marathon, Scalper Duel, Survival |
| `src/api/routes/battles.py` | 16 REST endpoints (JWT auth only) |
| `src/database/repositories/battle_repo.py` | CRUD for battles, participants, snapshots |
| `src/tasks/battle_snapshots.py` | Celery: snapshot every 5s, auto-completion every 10s |

**How Battles Work:**
```
1. POST /battles (draft)  →  Create battle with config
2. POST /battles/{id}/participants  →  Add agents (2+ required)
3. POST /battles/{id}/start  →  Lock config, snapshot/provision wallets, go active
   ├── WalletManager.snapshot_wallet() per agent
   ├── If fresh mode: wipe balances, provision starting_balance USDT
   └── Status: draft → pending → active
4. [Agents trade LIVE via their API keys against real Binance prices]
5. Celery beat (every 5s): SnapshotEngine captures equity for all participants
6. Celery beat (every 10s): Check if duration expired → auto-stop
7. POST /battles/{id}/stop  →  Calculate rankings, restore wallets
   ├── RankingCalculator.compute_participant_metrics() per agent
   ├── RankingCalculator.rank_participants() by chosen metric
   ├── WalletManager.restore_wallet() if fresh mode
   └── Status: active → completed
```

**Battle State Machine:**
```
draft → pending → active → completed
         └─ cancelled   └─ paused → active
```

**Wallet Modes:**
- **`existing`** — Agents trade with their real wallets. Battle is observational.
- **`fresh`** — Snapshot pre-battle equity → wipe → provision fresh USDT → trade → restore on stop.

**DB Models:**
```
Battle
├── id, account_id, name, status
├── config: JSONB (duration, pairs, wallet_mode, starting_balance)
├── preset: str | None
├── ranking_metric: roi_pct | total_pnl | sharpe_ratio | win_rate | profit_factor
└── started_at, ended_at

BattleParticipant
├── battle_id (FK), agent_id (FK)
├── snapshot_balance, final_equity, final_rank
├── status: active | paused | stopped | blown_up
└── UNIQUE(battle_id, agent_id)

BattleSnapshot (TimescaleDB hypertable)
├── battle_id, agent_id, timestamp
├── equity, unrealized_pnl (hardcoded 0!), realized_pnl
└── trade_count, open_positions
```

**5 Presets:**
| Preset | Duration | Balance | Pairs | Purpose |
|--------|----------|---------|-------|---------|
| `quick_1h` | 1 hour | 10,000 | All | Fast comparison |
| `day_trader` | 24 hours | 10,000 | All | Full-day performance |
| `marathon` | 7 days | 10,000 | All | Consistency test |
| `scalper_duel` | 4 hours | 5,000 | BTC+ETH | High-frequency |
| `survival` | Unlimited | 10,000 | All | Last agent standing |

---

## 3. How the Three Systems Interact (or Don't)

### Current Integration Map

```
                    ┌─────────────┐
                    │   AGENTS    │
                    │ (agent_id)  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            ▼            ▼
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │   LIVE     │ │ BACKTESTING│ │  BATTLES   │
     │  TRADING   │ │            │ │            │
     │            │ │            │ │            │
     │ agent_id ✓ │ │ agent_id ✗ │ │ agent_id ✓ │
     └─────┬──────┘ └────────────┘ └─────┬──────┘
           │                             │
           │         NO CONNECTION       │
           │◄────────────────────────────►│
           │                             │
     ┌─────┴──────┐               ┌──────┴─────┐
     │BalanceManager│             │WalletManager│
     │OrderEngine   │◄────────────│SnapEngine  │
     │RiskManager   │  uses live  │RankingCalc │
     │PortfolioTrack│  services   │            │
     └────────────┘               └────────────┘
```

### What's Connected
- **Agents ↔ Live Trading**: Deeply integrated. All services accept `agent_id`. Auth resolves agent context.
- **Agents ↔ Battles**: Connected through `BattleParticipant.agent_id`. Battles use live trading services (BalanceManager, OrderEngine) which are agent-scoped.

### What's NOT Connected
- **Agents ↔ Backtesting**: **Zero integration.** Backtesting uses `account_id` everywhere. No `agent_id` on any backtest model.
- **Backtesting ↔ Battles**: **Zero shared code.** Both compute similar metrics (Sharpe, drawdown, win rate) but with completely separate implementations.
- **Battles ↔ Historical Data**: Battles can only run live. No way to compete on past data.

---

## 4. Gap Analysis

### GAP 1: Backtesting is Account-Scoped (CRITICAL)

**Impact:** Every agent under an account shares the same backtest list. An agent cannot own, run, or view its own backtests independently.

**Evidence:**
- `BacktestSession.account_id` exists, `BacktestSession.agent_id` does NOT exist
- `BacktestEngine.create_session(account_id, config, db)` — no agent_id parameter
- `BacktestRepo.list_sessions(account_id, ...)` — filters by account only
- All API routes in `backtest.py` extract `account_id` only, never agent context
- All DB indexes on backtest tables are on `account_id`

**Contrast with live trading:** Live trading tables enforced `agent_id NOT NULL` since migration 009. Backtesting was never updated to match.

---

### GAP 2: No Historical Battles

**Impact:** Users can only run live battles (real-time, non-deterministic). There's no way to:
- Test agent strategies against each other on historical data
- Run reproducible, deterministic competitions
- Compare agents fairly without waiting for real-time duration
- Evaluate agents without risking real wallet balances

**Current state:** Battle system exclusively uses live trading infrastructure (BalanceManager, OrderEngine via Redis prices). The backtesting infrastructure (DataReplayer, BacktestSandbox, TimeSimulator) is never used by battles.

---

### GAP 3: Duplicated Metrics Code

**Impact:** Two separate implementations compute the same metrics differently, leading to inconsistent results.

| Metric | `results.py` (Backtesting) | `ranking.py` (Battles) |
|--------|---------------------------|------------------------|
| **Sharpe** | `Decimal` math, daily returns, `sqrt(365)` annualization | `float` math, per-snapshot returns, `sqrt(6.3M)` annualization |
| **Win Rate** | Filters trades with `realized_pnl is not None` | Counts all trades in denominator |
| **Profit Factor** | Returns `None` when no losses | Returns `999.99` when no losses |
| **Max Drawdown** | Tracks drawdown duration in days | No duration tracking |
| **Sortino** | Implemented | Not implemented for battles |
| **Input types** | `SandboxTrade` / `SandboxSnapshot` (dataclasses) | `Trade` / `BattleSnapshot` (ORM models) |

These divergences mean the same agent could get different Sharpe ratios depending on whether it was evaluated in a backtest vs a battle, even with identical trades.

---

### GAP 4: Backtesting Ignores Agent Risk Profiles

**Impact:** An agent's `risk_profile` JSONB (max_position_size_pct, max_order_size_pct, daily_loss_limit_pct) is enforced during live trading via `RiskManager.validate_order()` but completely ignored during backtesting.

**What happens:**
- Live: `RiskManager` reads agent's `risk_profile` → enforces 8-step validation chain
- Backtest: `BacktestSandbox.place_order()` → checks balance only, no risk limits

This means a strategy that passes backtesting may fail in live trading because it violates risk limits that weren't applied during the backtest.

---

### GAP 5: Battle Snapshots Report Zero Unrealized PnL

**Impact:** `SnapshotEngine._get_unrealized_pnl()` (line 119-121 of `snapshot_engine.py`) is a hardcoded placeholder:

```python
async def _get_unrealized_pnl(self, agent_id: UUID) -> Decimal:
    """Placeholder — returns 0. Real implementation would need current prices."""
    return Decimal("0")
```

This means all battle snapshots, live views, and replay charts show `unrealized_pnl = 0`, giving an incomplete picture of agent performance during active battles. Only realized PnL (from closed trades) is tracked.

---

## 5. Proposed Improvements

### 5.1 P0: Agent-Scoped Backtesting

**Goal:** Allow agents to own their own backtests, matching the live trading scoping model.

#### Database Changes
**File:** `src/database/models.py`

Add to `BacktestSession`:
```python
agent_id: Mapped[UUID | None] = mapped_column(
    PG_UUID(as_uuid=True),
    ForeignKey("agents.id", ondelete="CASCADE"),
    nullable=True,  # Initially nullable for migration safety
    index=True,
)
agent: Mapped[Agent | None] = relationship("Agent")
```

Add indexes:
- `Index("idx_bt_sessions_agent", "agent_id")`
- `Index("idx_bt_sessions_agent_status", "agent_id", "status")`

No changes needed to `BacktestTrade` or `BacktestSnapshot` — they're scoped via `session_id` FK.

#### Migration
**New file:** `alembic/versions/013_add_agent_id_to_backtest_sessions.py`

1. Add nullable `agent_id` column with FK to `agents.id`
2. Add indexes
3. Backfill: assign first agent per account to existing sessions
4. Follow-up migration 014: enforce NOT NULL (after backfill verified)

#### Engine Changes
**File:** `src/backtesting/engine.py`

- `BacktestConfig` dataclass: add `agent_id: UUID | None = None`
- `_ActiveSession` dataclass: add `agent_id: UUID | None = None`
- `create_session()`: accept and store `agent_id`
- `start()`: load agent's risk profile and pass to sandbox (see 5.4)

#### Repository Changes
**File:** `src/database/repositories/backtest_repo.py`

All methods get optional `agent_id` parameter:
- `list_sessions(account_id, agent_id=None, ...)` — filter by agent when provided
- `get_best_session(account_id, metric, agent_id=None, ...)` — agent-scoped analytics
- `get_sessions_for_compare(session_ids, agent_id=None)` — ownership check

#### API Route Changes
**File:** `src/api/routes/backtest.py`

- Extract agent context from `request.state.agent` or `X-Agent-Id` header
- Pass `agent_id` to engine and repository calls
- `list` endpoint: accept `agent_id` query parameter for filtering

**File:** `src/api/schemas/backtest.py`

- `BacktestCreateRequest`: add optional `agent_id`
- `BacktestListItem` / `BacktestCreateResponse`: add `agent_id` field

---

### 5.2 P1: Historical Battles (Backtesting Battles)

**Goal:** New battle mode where agents compete on historical data using the backtesting infrastructure. Deterministic, reproducible, instant (no waiting for real time).

#### Concept

| Aspect | Live Battle | Historical Battle |
|--------|-------------|-------------------|
| Price source | Live Binance WS via Redis | DataReplayer from TimescaleDB |
| Order execution | Live OrderEngine (DB writes) | BacktestSandbox per agent (in-memory) |
| Time progression | Real-time wall clock | Stepped (synchronized across all agents) |
| Snapshots | Celery task every 5s | Captured at each step in-memory |
| Determinism | Non-deterministic | Fully deterministic & reproducible |
| Wallet impact | Real balances affected | Zero impact on real balances |
| Speed | 1 hour battle = 1 hour wait | 1 hour battle = seconds to compute |

#### Architecture

```
HistoricalBattleEngine
├── TimeSimulator (shared — one virtual clock for all agents)
├── DataReplayer (shared — one price feed for all agents)
├── BacktestSandbox #1 (Agent A's isolated in-memory exchange)
├── BacktestSandbox #2 (Agent B's isolated in-memory exchange)
├── BacktestSandbox #N (Agent N's isolated in-memory exchange)
└── step() → advance clock, load prices, update all sandboxes
```

All agents see the same prices at the same time. Each agent has its own isolated sandbox. No live services involved.

#### Database Changes
**File:** `src/database/models.py`

Add to `Battle`:
- `battle_mode: Mapped[str]` — `"live"` or `"historical"`, default `"live"`
- `backtest_config: Mapped[dict | None]` (JSONB) — `start_time`, `end_time`, `candle_interval`, `pairs`

Add to `BattleParticipant`:
- `backtest_session_id: Mapped[UUID | None]` — FK to `backtest_sessions.id` (links per-agent results)

**New migration:** `alembic/versions/014_add_historical_battle_support.py`

#### New Engine
**New file:** `src/battles/historical_engine.py`

```python
class HistoricalBattleEngine:
    """Orchestrates historical battles using backtesting infrastructure."""

    def __init__(self, battle_id, config, participant_agent_ids): ...
    async def initialize(self, db): ...       # Preload data, create sandboxes
    async def step(self, db): ...             # Advance one step for all agents
    def place_order(self, agent_id, ...): ... # Place order in agent's sandbox
    async def complete(self, db): ...         # Calculate rankings, persist results
```

#### Service Changes
**File:** `src/battles/service.py`

- `create_battle()`: accept `battle_mode` and `backtest_config`
- `start_battle()`: if historical → instantiate `HistoricalBattleEngine` instead of wallet management
- `stop_battle()`: if historical → call engine.complete() for rankings

#### New API Endpoints
**File:** `src/api/routes/battles.py`

- `POST /battles/{id}/step` — advance one step (historical mode only)
- `POST /battles/{id}/step/batch` — advance N steps
- `GET /battles/{id}/market/prices` — prices at virtual_time

#### Historical Presets
**File:** `src/battles/presets.py`

Add:
- `historical_day` — 1-day historical, 1m candles
- `historical_week` — 7-day historical, 5m candles
- `historical_month` — 30-day historical, 1h candles

---

### 5.3 P1: Shared Metrics Pipeline

**Goal:** Unify metrics calculation so backtesting and battles produce consistent results.

#### New Module
**New file:** `src/metrics/calculator.py`

```python
@dataclass(frozen=True, slots=True)
class MetricTradeInput:
    realized_pnl: Decimal | None
    quote_amount: Decimal
    symbol: str
    timestamp: datetime

@dataclass(frozen=True, slots=True)
class MetricSnapshotInput:
    timestamp: datetime
    equity: Decimal

@dataclass(frozen=True, slots=True)
class UnifiedMetrics:
    roi_pct: Decimal
    total_pnl: Decimal
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    max_drawdown_pct: Decimal
    max_drawdown_duration_days: Decimal
    win_rate: Decimal
    profit_factor: Decimal | None
    total_trades: int
    trades_per_day: Decimal
    avg_win: Decimal
    avg_loss: Decimal
    best_trade: Decimal
    worst_trade: Decimal

def calculate_unified_metrics(
    trades: list[MetricTradeInput],
    snapshots: list[MetricSnapshotInput],
    starting_balance: Decimal,
    duration_days: Decimal,
    snapshot_interval_seconds: int = 86400,  # For annualization
) -> UnifiedMetrics: ...
```

The `snapshot_interval_seconds` parameter controls Sharpe annualization:
- Backtesting (daily snapshots): `86400` → `sqrt(365)`
- Battles (5s snapshots): `5` → `sqrt(365.25 * 86400 / 5)`

#### Adapters
**New file:** `src/metrics/adapters.py`

```python
def from_sandbox_trades(trades: list[SandboxTrade]) -> list[MetricTradeInput]: ...
def from_sandbox_snapshots(snaps: list[SandboxSnapshot]) -> list[MetricSnapshotInput]: ...
def from_db_trades(trades: Sequence[Trade]) -> list[MetricTradeInput]: ...
def from_battle_snapshots(snaps: Sequence[BattleSnapshot]) -> list[MetricSnapshotInput]: ...
```

#### Refactor Consumers
- `src/backtesting/results.py`: Thin wrapper around `calculate_unified_metrics()` with sandbox adapters
- `src/battles/ranking.py`: Use `calculate_unified_metrics()` with DB adapters. Remove static methods.

---

### 5.4 P1: Risk Profile Integration in Backtesting

**Goal:** Make `BacktestSandbox` enforce agent risk limits during backtesting.

#### Approach

The full `RiskManager` requires Redis, PriceCache, and DB access — too heavy for the in-memory sandbox. Instead, extract the "pure math" checks into a lightweight `RiskLimits` dataclass that the sandbox can enforce.

**File:** `src/backtesting/sandbox.py`

Add to constructor:
```python
def __init__(
    self,
    session_id: str,
    starting_balance: Decimal,
    slippage_factor: Decimal = ...,
    fee_fraction: Decimal = ...,
    risk_limits: dict | None = None,  # NEW: agent's risk_profile
) -> None:
```

Enforce in `place_order()`:
- **Max position size** — reject if position would exceed `max_position_size_pct` of equity
- **Max order size** — reject if order exceeds `max_order_size_pct` of equity
- **Daily loss halt** — track daily PnL, reject orders if daily loss exceeds `daily_loss_limit_pct`

**File:** `src/backtesting/engine.py`

In `start()`, if session has `agent_id`:
1. Load agent from DB
2. Extract `risk_profile` JSONB
3. Pass as `risk_limits` to `BacktestSandbox()`

---

### 5.5 P1: Fix SnapshotEngine Unrealized PnL

**Goal:** Calculate real unrealized PnL during live battles instead of returning 0.

**File:** `src/battles/snapshot_engine.py`

Replace the placeholder `_get_unrealized_pnl()`:

```python
async def _get_unrealized_pnl(self, agent_id: UUID) -> Decimal:
    """Calculate unrealized PnL from open positions using current Redis prices."""
    positions = await self._get_open_positions(agent_id)
    if not positions:
        return Decimal("0")

    total_unrealized = Decimal("0")
    for pos in positions:
        current_price = await self._price_cache.get_price(pos.symbol)
        if current_price and pos.avg_entry_price:
            unrealized = (current_price - pos.avg_entry_price) * pos.quantity
            total_unrealized += unrealized

    return total_unrealized
```

**Dependency:** Requires injecting `PriceCache` (Redis) into `SnapshotEngine`. Currently it only takes `AsyncSession`.

Change constructor:
```python
def __init__(self, session: AsyncSession, price_cache: PriceCache) -> None:
```

Update Celery task in `src/tasks/battle_snapshots.py` to pass price_cache.

---

### 5.6 P2: Battle Replay from Historical Data

**Goal:** Create a new historical battle from a completed battle's configuration.

**File:** `src/battles/service.py`

```python
async def replay_battle(
    self,
    battle_id: UUID,
    account_id: UUID,
    override_config: dict | None = None,
    override_agents: list[UUID] | None = None,
) -> Battle:
    """Create a new historical battle from an existing battle's config.

    For live battles: uses started_at → ended_at as the time range.
    For historical battles: reuses backtest_config.
    """
```

**File:** `src/api/routes/battles.py`

New endpoint:
- `POST /battles/{id}/replay` — creates new historical battle draft from existing battle config
- Body: `{ "override_config": {}, "agent_ids": [] }` (both optional)

---

## 6. Implementation Sequencing

```
Phase 1 (P0): Agent-Scoped Backtesting          [FOUNDATION — must go first]
├── 1a. Add agent_id to BacktestSession model
├── 1b. Alembic migration (nullable)
├── 1c. Repository changes (agent_id filtering)
├── 1d. Engine changes (accept agent_id)
├── 1e. API route + schema changes
└── 1f. Tests (unit + integration)

Phase 2 (P1): Shared Metrics Pipeline           [Can parallel with Phase 1]
├── 2a. Create src/metrics/calculator.py
├── 2b. Create src/metrics/adapters.py
├── 2c. Refactor results.py to use unified calculator
├── 2d. Refactor ranking.py to use unified calculator
└── 2e. Tests for metrics consistency

Phase 3 (P1): Risk Profile in Backtesting       [Depends on Phase 1]
├── 3a. Add risk_limits parameter to BacktestSandbox
├── 3b. Implement lightweight risk checks in sandbox
├── 3c. Load agent risk profile in engine.start()
└── 3d. Tests for risk enforcement in sandbox

Phase 4 (P1): Fix SnapshotEngine Unrealized PnL [Independent]
├── 4a. Inject PriceCache into SnapshotEngine
├── 4b. Implement real unrealized PnL calculation
├── 4c. Update Celery task dependency injection
└── 4d. Tests

Phase 5 (P1): Historical Battles                [Depends on Phases 1, 2, 3]
├── 5a. Add battle_mode + backtest_config to Battle model
├── 5b. Alembic migration
├── 5c. Build HistoricalBattleEngine
├── 5d. Integrate into BattleService (branch on mode)
├── 5e. New API endpoints (step, prices)
├── 5f. Historical presets
└── 5g. Tests (unit + integration)

Phase 6 (P2): Battle Replay                     [Depends on Phase 5]
├── 6a. replay_battle() service method
├── 6b. API endpoint
└── 6c. Tests
```

**Estimated effort per phase:**
- Phase 1: Medium (model + migration + repo + engine + API)
- Phase 2: Small-Medium (new module + adapters + refactor)
- Phase 3: Small (sandbox changes + engine loading)
- Phase 4: Small (inject PriceCache + implement calculation)
- Phase 5: Large (new engine + service integration + API + presets)
- Phase 6: Small (service method + API endpoint)

---

## 7. Risk & Considerations

### Migration Safety
- Phase 1 migration (agent_id on backtest_sessions) follows the proven pattern from migrations 008/009: add nullable first → backfill → enforce NOT NULL later
- Phase 5 migration (battle_mode on battles) is additive only with defaults — safe for production

### Backward Compatibility
- Account-scoped backtest queries continue to work (agent_id filter is optional)
- All existing live battles remain `battle_mode="live"` by default
- API endpoints are backward-compatible (new params are optional)

### Singleton Lifetime
- `BacktestEngine` is already a singleton with `_active` dict for in-memory sessions
- `HistoricalBattleEngine` needs similar pattern: module-level dict `battle_id → engine`
- Both survive across requests but lost on server restart (orphan detection handles this)

### Performance
- Historical battles preload all price data (like backtesting) — memory scales with `pairs × candles`
- Shared DataReplayer means one preload serves all agents in a battle
- Battle snapshots stored in-memory during execution, flushed to DB on completion

### Testing Strategy
- Each phase needs unit tests for changed components
- Integration test: create agent → run agent-scoped backtest → verify isolation
- Integration test: create historical battle → step through → verify rankings match
- Metrics consistency test: same trades through both pipelines → identical results
