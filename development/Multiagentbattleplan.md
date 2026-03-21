---
type: plan
title: "Multi-Agent Architecture & Agents Battle — Development Plan"
status: archived
phase: battles
tags:
  - plan
  - battles
---

# Multi-Agent Architecture & Agents Battle — Development Plan

> **Version:** 1.0 | **Date:** March 2026  
> **Status:** Planning Complete — Ready for Implementation  
> **Depends On:** Backend Phase 4, UI Phase 6 (both complete)  
> **Estimated Duration:** 6–7 weeks across 6 phases

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Design Decisions](#2-design-decisions)
3. [Account Model Restructuring](#3-account-model-restructuring)
4. [Database Schema Changes](#4-database-schema-changes)
5. [New API Endpoints](#5-new-api-endpoints)
6. [WebSocket Channels](#6-websocket-channels)
7. [UI Navigation Restructuring](#7-ui-navigation-restructuring)
8. [Agent Management Pages](#8-agent-management-pages)
9. [Agents Battle — Backend](#9-agents-battle--backend)
10. [Agents Battle — Live Dashboard](#10-agents-battle--live-dashboard)
11. [Battle Results & History](#11-battle-results--history)
12. [Component Inventory](#12-component-inventory)
13. [Development Phases & Tasks](#13-development-phases--tasks)
14. [Migration Strategy](#14-migration-strategy)
15. [Risks & Open Questions](#15-risks--open-questions)

---

## 1. Executive Summary

Two interconnected features that represent the next major evolution of AgentExchange:

**Multi-Agent Account Model** — Restructuring the platform from 1-account-1-agent to a workspace model where a single developer account manages unlimited agents. Each agent has its own API key, wallet, risk profile, and performance history. Agents run simultaneously 24/7. The developer switches between them like Slack workspaces via a sidebar dropdown.

**Agents Battle** — A competitive arena where 2+ of the developer's agents trade simultaneously on the same market data. The developer watches them compete head-to-head in a live dashboard with real-time equity racing charts, trade feeds, and comparison metrics. Battles support configurable presets, custom durations, developer-chosen ranking metrics, pause/resume per agent, and full replay history.

The multi-agent model is the foundation that makes battles possible. Without it, battles would require multiple developer accounts. With it, battles become natural: select your agents, set the rules, watch them fight.

### Key Numbers

| Metric | Value |
|---|---|
| Agents per account | Unlimited |
| Simultaneous active agents | All (24/7) |
| Battle participants | 2–8 agents |
| Battle duration options | Presets + full manual control |
| Battle history | Permanent with full replay |
| Estimated development time | 6–7 weeks |

---

## 2. Design Decisions

All 20 clarifying questions answered by the product owner. These decisions are final and form the foundation for this specification.

### Account & Agent Model

| # | Question | Decision |
|---|---|---|
| 1 | Max agents per developer account | **Unlimited** |
| 2 | Can all agents trade simultaneously? | **Yes — all agents run 24/7** |
| 3 | Agent starting balance | **Independent per agent, set at creation** |
| 4 | Risk profiles | **Per-agent, each has its own limits** |
| 5 | Agent creation info | **Name (mandatory), LLM model, framework, strategy — open/flexible fields** |
| 6 | Agent avatars | **Auto-generated + option to upload custom** |
| 7 | API keys | **One API key per agent, grouped under developer account** |
| 8 | Agent reset | **Archive history + option to clone config into fresh agent** |
| 9 | Agent lifecycle | **Both archive and hard delete available** |

### UI & Navigation

| # | Question | Decision |
|---|---|---|
| 10 | Agent switching | **Dropdown at top of sidebar (Slack-style)** |
| 11 | Visual context indicator | **Agent name + colored dot in sidebar** |
| 12 | Cross-agent overview page | **Yes, separate page (not the landing page)** |

### Battle Configuration

| # | Question | Decision |
|---|---|---|
| 13 | Battle participants | **Own agents only (private comparison)** |
| 14 | Duration modes | **Presets + full manual configuration** |
| 15 | Battle wallets | **Developer chooses: fresh equal balance or existing wallet** |
| 16 | Mid-battle control | **Can pause/resume individual agents** |
| 17 | Ranking metric | **Developer picks per battle** |
| 18 | Battle history | **Permanent with full replay capability** |

### Setup & Priority

| # | Question | Decision |
|---|---|---|
| 19 | Setup wizard changes | **Keep as-is, add separate "New Agent" flow** |
| 20 | Build priority | **1) Multi-agent model → 2) Overview page → 3) Battle live → 4) Battle results** |

---

## 3. Account Model Restructuring

### Current Model (1:1)

```
Developer Account = Agent (1:1)
  └─ API Key, Wallet, Orders, Positions, Trades, Risk Profile, Analytics
```

The `accounts` table serves double duty as both developer identity and agent identity. API keys, balances, orders, and risk profiles all live on this single entity.

### New Model (1:Many)

```
Developer Account (1)
  ├─ Agent 1 → API Key, Wallet, Risk Profile, Orders, Positions, Trades
  ├─ Agent 2 → API Key, Wallet, Risk Profile, Orders, Positions, Trades
  ├─ Agent 3 → API Key, Wallet, Risk Profile, Orders, Positions, Trades
  └─ Agent N → ...
```

The developer account becomes a pure identity/auth layer. All trading functionality moves to the agent level.

### What Changes

- **`accounts` table** becomes the developer identity: email, password/JWT, display_name, created_at. No more API key, no balances, no risk profile.
- **New `agents` table** holds everything agent-specific: api_key, api_key_hash, starting_balance, risk_profile, status, avatar, llm_model, framework, strategy_tags.
- **`balances`, `orders`, `positions`, `trades`** all get re-keyed from `account_id` → `agent_id`.
- **API authentication** via `X-API-Key` now resolves to an agent (not account). The agent carries a reference to its parent developer account.
- **JWT auth (web UI)** authenticates the developer. The frontend includes `active_agent_id` in requests or context.

### What Stays The Same

- **Order Execution Engine** — works on agent-scoped balances/positions, no logic changes
- **Risk Management Engine** — reads `risk_profile` from agent instead of account, same logic
- **Portfolio Tracker** — scoped to agent, same calculations
- **Price Ingestion** — completely unchanged, market data is global
- **WebSocket channels** — agent subscribes with its own API key, same flow

---

## 4. Database Schema Changes

### New Table: `agents`

```sql
CREATE TABLE agents (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id       UUID NOT NULL REFERENCES accounts(id),
    display_name     VARCHAR(100) NOT NULL,
    api_key          VARCHAR(64) UNIQUE NOT NULL,
    api_key_hash     VARCHAR(128) NOT NULL,
    starting_balance NUMERIC(20,8) NOT NULL DEFAULT 10000.00,
    llm_model        VARCHAR(100),              -- 'gpt-4', 'claude-3', 'llama-3'
    framework        VARCHAR(100),              -- 'langchain', 'crewai', 'agent-zero'
    strategy_tags    JSONB DEFAULT '[]',         -- ['momentum', 'scalping']
    risk_profile     JSONB DEFAULT '{}',
    avatar_url       TEXT,                       -- null = auto-generate
    color            VARCHAR(7) DEFAULT '#EAB308', -- hex for UI identification
    status           VARCHAR(20) NOT NULL DEFAULT 'active',
                     -- active, idle, disconnected, archived
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agents_account ON agents(account_id);
CREATE INDEX idx_agents_api_key ON agents(api_key);
CREATE INDEX idx_agents_status ON agents(account_id, status);
```

### Modified Table: `accounts`

Strip trading-specific columns. Keep only developer identity:

```sql
ALTER TABLE accounts DROP COLUMN api_key, api_key_hash, api_secret_hash;
ALTER TABLE accounts DROP COLUMN starting_balance, risk_profile;
-- accounts now holds: id, email, display_name, password_hash, status, created_at
```

### Re-keyed Tables

All trading tables change foreign key from `account_id` → `agent_id`:

| Table | Old FK | New FK | Notes |
|---|---|---|---|
| `balances` | `account_id` | `agent_id` | Per-agent asset balances |
| `orders` | `account_id` | `agent_id` | Order ownership |
| `trades` | `account_id` | `agent_id` | Trade history |
| `positions` | `account_id` | `agent_id` | Open positions |
| `trading_sessions` | `account_id` | `agent_id` | Reset/session tracking |

### New Table: `battles`

```sql
CREATE TABLE battles (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id       UUID NOT NULL REFERENCES accounts(id),
    name             VARCHAR(200) NOT NULL,
    status           VARCHAR(20) NOT NULL DEFAULT 'draft',
                     -- draft, pending, active, paused, completed, cancelled
    config           JSONB NOT NULL,
                     -- { duration_type, duration_value, allowed_pairs,
                     --   wallet_mode, starting_balance }
    preset           VARCHAR(50),               -- 'quick_1h', 'day_trader', 'marathon', null=custom
    ranking_metric   VARCHAR(30) NOT NULL DEFAULT 'roi_pct',
                     -- roi_pct, total_pnl, sharpe_ratio, win_rate, profit_factor
    started_at       TIMESTAMPTZ,
    ended_at         TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_battles_account ON battles(account_id);
CREATE INDEX idx_battles_status ON battles(account_id, status);
```

### New Table: `battle_participants`

```sql
CREATE TABLE battle_participants (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    battle_id        UUID NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    agent_id         UUID NOT NULL REFERENCES agents(id),
    snapshot_balance NUMERIC(20,8),             -- starting balance snapshot
    final_equity     NUMERIC(20,8),
    final_rank       INTEGER,
    status           VARCHAR(20) NOT NULL DEFAULT 'active',
                     -- active, paused, stopped, blown_up
    joined_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(battle_id, agent_id)
);

CREATE INDEX idx_bp_battle ON battle_participants(battle_id);
CREATE INDEX idx_bp_agent ON battle_participants(agent_id);
```

### New Table: `battle_snapshots` (TimescaleDB hypertable)

```sql
CREATE TABLE battle_snapshots (
    id               BIGSERIAL,
    battle_id        UUID NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    agent_id         UUID NOT NULL REFERENCES agents(id),
    timestamp        TIMESTAMPTZ NOT NULL,
    equity           NUMERIC(20,8) NOT NULL,
    unrealized_pnl   NUMERIC(20,8),
    realized_pnl     NUMERIC(20,8),
    trade_count      INTEGER,
    open_positions   INTEGER
);

SELECT create_hypertable('battle_snapshots', 'timestamp');
CREATE INDEX idx_battle_snap ON battle_snapshots(battle_id, agent_id, timestamp DESC);
```

At 5-second intervals over a 24h battle with 4 agents → ~69,120 rows. Manageable with TimescaleDB compression.

---

## 5. New API Endpoints

### Agent Management (JWT auth — developer)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/agents` | Create new agent (name, balance, model, framework) |
| `GET` | `/api/v1/agents` | List all agents for developer |
| `GET` | `/api/v1/agents/{agent_id}` | Get agent details + live stats |
| `PUT` | `/api/v1/agents/{agent_id}` | Update agent config (name, model, risk) |
| `POST` | `/api/v1/agents/{agent_id}/clone` | Clone agent config into new agent |
| `POST` | `/api/v1/agents/{agent_id}/reset` | Reset agent (archive history, fresh wallet) |
| `POST` | `/api/v1/agents/{agent_id}/archive` | Archive agent (soft delete) |
| `DELETE` | `/api/v1/agents/{agent_id}` | Hard delete agent + all data |
| `POST` | `/api/v1/agents/{agent_id}/regenerate-key` | Regenerate agent API key |
| `GET` | `/api/v1/agents/{agent_id}/skill.md` | Download agent-specific skill.md |

### Agent Overview (JWT auth — developer)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/agents/overview` | All agents with live equity, PnL, status, trade count |
| `GET` | `/api/v1/agents/compare` | Side-by-side metrics for selected agents |

### Battle Management (JWT auth — developer)

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/battles` | Create battle (name, config, preset) |
| `GET` | `/api/v1/battles` | List battles (filter: active, completed, draft) |
| `GET` | `/api/v1/battles/{battle_id}` | Get battle state + all participants |
| `PUT` | `/api/v1/battles/{battle_id}` | Update battle config (draft only) |
| `DELETE` | `/api/v1/battles/{battle_id}` | Delete/cancel battle |
| `POST` | `/api/v1/battles/{battle_id}/participants` | Add agent to battle |
| `DELETE` | `/api/v1/battles/{battle_id}/participants/{agent_id}` | Remove agent (draft/pending only) |
| `POST` | `/api/v1/battles/{battle_id}/start` | Start battle (all agents begin) |
| `POST` | `/api/v1/battles/{battle_id}/pause/{agent_id}` | Pause individual agent |
| `POST` | `/api/v1/battles/{battle_id}/resume/{agent_id}` | Resume paused agent |
| `POST` | `/api/v1/battles/{battle_id}/stop` | End battle, calculate final rankings |
| `GET` | `/api/v1/battles/{battle_id}/live` | Live snapshot: all participants' metrics |
| `GET` | `/api/v1/battles/{battle_id}/results` | Final results + rankings |
| `GET` | `/api/v1/battles/{battle_id}/replay` | Time-series snapshots for replay |

### Existing Endpoints — Impact

All existing trading endpoints (`/trade/order`, `/account/balance`, etc.) continue to work via `X-API-Key` header. The key now resolves to an agent instead of an account. **No changes needed from the agent/bot side** — the `skill.md` and SDK work identically.

Web UI endpoints that use JWT + account context will add an `active_agent_id` parameter (header or query) to scope requests to the selected agent workspace.

---

## 6. WebSocket Channels

### Existing Channels (unchanged)

All existing channels (`ticker`, `candles`, `orders`, `portfolio`) continue to work. Agent-specific channels are scoped by the API key used in the WebSocket connection.

### New Channel: `battle`

**Subscribe:**
```json
{"action": "subscribe", "channel": "battle", "battle_id": "uuid"}
```

#### `battle:update` — every 1–2 seconds during active battle

```json
{
  "channel": "battle",
  "battle_id": "uuid",
  "type": "update",
  "timestamp": "2026-03-10T15:30:45Z",
  "participants": [
    {
      "agent_id": "uuid",
      "display_name": "AlphaBot",
      "rank": 1,
      "equity": "10450.20",
      "pnl_pct": 4.5,
      "trade_count": 23,
      "win_rate": 65.2,
      "status": "active"
    }
  ]
}
```

#### `battle:trade` — real-time trade events from any participant

```json
{
  "channel": "battle",
  "type": "trade",
  "agent_id": "uuid",
  "agent_name": "AlphaBot",
  "agent_color": "#EAB308",
  "side": "BUY",
  "symbol": "BTCUSDT",
  "quantity": "0.5",
  "price": "64521.30",
  "pnl": "125.40"
}
```

#### `battle:status` — state change events

```json
{"type": "status", "event": "agent_paused", "agent_id": "...", "timestamp": "..."}
{"type": "status", "event": "agent_resumed", "agent_id": "...", "timestamp": "..."}
{"type": "status", "event": "agent_blown_up", "agent_id": "...", "timestamp": "..."}
{"type": "status", "event": "lead_change", "new_leader": "...", "prev_leader": "...", "timestamp": "..."}
{"type": "status", "event": "battle_completed", "rankings": [...], "timestamp": "..."}
```

---

## 7. UI Navigation Restructuring

### Sidebar Changes

The sidebar gets a new **agent switcher** at the top, above the navigation links.

#### Agent Switcher Component (`src/components/layout/agent-switcher.tsx`)

- **Position:** top of sidebar, below the AgentExchange logo
- **Display:** current agent name + colored dot + dropdown chevron
- **Dropdown contents:** all active agents with name, colored dot, live equity, status badge
- **Footer links:** "+ Create New Agent" and "Manage Agents"
- **State:** switching agent updates `activeAgentId` in `agent-store.ts` (Zustand), which scopes all TanStack Query data fetching

### New Navigation Items

| Icon | Label | Route | Scope |
|---|---|---|---|
| Grid | Agents | `/agents` | Developer (cross-agent) |
| Swords | Battles | `/battles` | Developer (cross-agent) |

These two items are **not** agent-scoped — they show developer-level views regardless of which agent is selected.

### Page Scoping Update

| Page | Current Scope | New Scope |
|---|---|---|
| Market Overview | Global | Global (unchanged) |
| Coin Detail | Global | Global (unchanged) |
| Dashboard | Account | **Active Agent** |
| Wallet | Account | **Active Agent** |
| Trades | Account | **Active Agent** |
| Analytics | Account | **Active Agent** |
| Leaderboard | All accounts | All agents (cross-developer) |
| Settings | Account | **Split: dev settings + agent settings** |
| Setup | Account | Kept as-is (first agent onboarding) |
| Agents (**NEW**) | — | Developer (all agents overview) |
| Battles (**NEW**) | — | Developer (battle management) |

### Settings Page Split

Settings becomes two tabs:

- **Account Settings:** developer email, password, display name, notification preferences, theme toggle
- **Agent Settings:** active agent's API key management, risk config, reset/clone/archive actions. Changes with the agent switcher.

---

## 8. Agent Management Pages

### Agents Overview: `/agents`

Grid layout showing all agents as cards. This is the cross-agent overview page.

#### Agent Card Component (`src/components/agents/agent-card.tsx`)

- Agent name + auto-generated avatar (or custom uploaded image)
- Colored dot matching the agent's assigned color
- LLM model badge (e.g., GPT-4, Claude, Llama) — shown only if set
- Framework badge (e.g., LangChain, CrewAI) — shown only if set
- Strategy tags as pills — shown only if set
- Live equity value with animated counter
- PnL % (green/red) since session start
- Total trades count
- Win rate percentage
- Mini sparkline showing equity curve (last 24h)
- Status badge: Trading (green), Idle (yellow), Disconnected (red), Archived (gray)
- Last activity timestamp
- Click card → switch to that agent's dashboard context

#### Page Actions

- **"+ Create New Agent"** button → opens creation modal
- **Sort by:** name, equity, PnL, trades, win rate, last active
- **Filter by:** status (active, idle, disconnected, archived), framework, model
- **Toggle:** show archived agents

### Create Agent Flow

Modal/drawer with the following fields:

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| Agent Name | Text input | **Yes** | — | The only mandatory field |
| Starting Balance | Number input | Yes | $10,000 USDT | Min $100, no max |
| LLM Model | Dropdown + custom text | No | — | Presets: GPT-4, Claude, Llama, Gemini, Mixtral + custom |
| Framework | Dropdown + custom text | No | — | Presets: LangChain, CrewAI, Agent Zero, OpenClaw + custom |
| Strategy Tags | Tag input (free-form) | No | — | e.g., momentum, scalping, mean-reversion |
| Color | Color picker | No | Auto-assigned | Distinct from existing agents |
| Avatar | File upload | No | Auto-generated | identicon-style from agent_id hash |

**On creation:** API key is generated and shown once (same one-time pattern as current setup wizard Step 2). Skill.md is available for download immediately.

### Agent Detail / Edit (`src/components/agents/agent-edit-drawer.tsx`)

Accessible from agent card context menu or the agent settings tab. Provides:

- Edit name, model, framework, tags, color, avatar
- API key management (masked display, regenerate with confirmation)
- Risk profile configuration (same sliders as current settings)
- Clone button → creates new agent with same config + fresh wallet
- Archive button → soft delete with confirmation
- Delete button → hard delete with double confirmation ("type agent name to confirm")

---

## 9. Agents Battle — Backend

### Battle Lifecycle

```
DRAFT → PENDING → ACTIVE → COMPLETED
         └─ CANCELLED   └─ PAUSED → ACTIVE
```

| Status | Description |
|---|---|
| **Draft** | Created, developer configuring rules and adding agents. Can edit everything. |
| **Pending** | Configuration locked, waiting for Start. Wallet snapshots taken if fresh-balance mode. |
| **Active** | Battle running. Snapshots recorded every 5 seconds. Individual agents can be paused/resumed. |
| **Paused** | Entire battle paused (all agents frozen). Timer stops. |
| **Completed** | Duration expired or manual stop. Final rankings calculated. All positions force-closed at market. |
| **Cancelled** | Cancelled before completion. No rankings. Data preserved for reference. |

### Battle Presets

| Preset Name | Duration | Balance | Pairs | Best For |
|---|---|---|---|---|
| Quick Sprint | 1 hour | $10,000 | Top 10 by volume | Fast strategy comparison |
| Day Trader | 24 hours | $10,000 | All pairs | Full-day performance test |
| Marathon | 7 days | $10,000 | All pairs | Endurance and consistency |
| Scalper Duel | 4 hours | $5,000 | BTC + ETH only | High-frequency testing |
| Survival Mode | No time limit | $10,000 | All pairs | Last agent standing |
| Custom | Manual | Manual | Manual | Full control over everything |

Developer can also create fully custom configurations with any duration, balance, pair whitelist, and risk rules.

### Snapshot Engine

A Celery beat task runs every **5 seconds** for each active battle. For each participant, it records: equity, unrealized PnL, realized PnL, trade count, and open position count into `battle_snapshots`.

This powers both the live equity race chart and the post-battle replay feature.

### Wallet Modes

**Fresh Equal Balance:**
When battle starts, the system snapshots each participating agent's current state and provisions a temporary isolated wallet with the configured starting balance. During the battle, trades execute against this battle wallet. When the battle ends, the battle wallet is discarded and the agent reverts to its real wallet state.

**Existing Wallet:**
Agents trade with their real wallets. The battle is purely an observation/comparison layer — no wallet manipulation. This mode tests agents under their actual conditions.

### Ranking Calculation

When a battle completes, final rankings are calculated based on the developer's chosen metric:

| Metric | Formula | Best For |
|---|---|---|
| ROI % | `(final_equity - start_balance) / start_balance × 100` | Pure return comparison |
| Total PnL | `final_equity - start_balance` | Absolute dollar performance |
| Sharpe Ratio | Calculated from equity curve snapshots | Risk-adjusted comparison |
| Win Rate | `winning_trades / total_trades × 100` | Consistency comparison |
| Profit Factor | `gross_profits / gross_losses` | Edge quality comparison |

---

## 10. Agents Battle — Live Dashboard

### Route: `/battles/{battle_id}`

The main event — a real-time competitive visualization where the developer watches agents fight. Every element updates live via WebSocket.

### Layout Structure

#### Top Bar (`src/components/battles/battle-top-bar.tsx`)

- Battle name (editable in draft status)
- Timer / countdown (elapsed time or time remaining depending on mode)
- Status badge: Draft / Pending / Live / Paused / Completed
- Participant count (e.g., "4 agents")
- Ranking metric label (the developer's chosen metric)
- Control buttons: Pause All / Resume All / End Battle

#### Agent Cards Row (`src/components/battles/battle-agent-cards.tsx`)

Horizontal scrollable row of cards — one per participant:

- Agent name + avatar + assigned color
- Current rank with ordinal badge (#1 gold, #2 silver, #3 bronze, rest neutral)
- LLM model + framework badges (if set)
- Live equity (animated counter, colored by profit/loss direction)
- PnL % with green/red styling
- Trade count + win rate
- Mini sparkline (equity last 30 minutes)
- Status indicator: Active (green pulse) / Paused (yellow) / Blown Up (red skull)
- Pause/Resume button per agent
- Click card → opens agent deep-dive modal

#### Main Visualization Area (Tabbed)

**Tab 1: Equity Race** — The centerpiece. Overlaid line chart showing all agents' equity curves on the same time axis. Each agent gets its distinct color. The chart auto-scrolls as time progresses. Hover shows crosshair with all agents' equity at that timestamp. Library: Recharts `LineChart`.

**Tab 2: PnL Comparison** — Grouped bar chart comparing realized PnL, unrealized PnL, and total PnL across all agents. Updates live. Click a bar to see that agent's breakdown. Library: Recharts `BarChart`.

**Tab 3: Live Trade Feed** — Unified chronological feed of all trades from all agents. Each entry shows: agent color dot, agent name, BUY/SELL badge, pair, quantity, price, PnL. New trades animate in from top. Filter by agent. Color-coded by agent's assigned color.

**Tab 4: Strategy Heatmap** — Grid visualization. Rows = agents, columns = trading pairs. Cells show PnL for that agent-pair combination, color-coded from deep red (big loss) through neutral to deep green (big profit). Instantly reveals which agent is best at which pair.

**Tab 5: Risk Radar** — Overlaid radar/spider charts comparing agents across 5 axes: position concentration, drawdown depth, trade frequency, win rate, average hold time. Shows risk profiles at a glance. Library: Recharts `RadarChart`.

#### Bottom Section: Comparison Metrics Table (`src/components/battles/battle-metrics-table.tsx`)

Full sortable data table with all agents as rows:

| Column | Description |
|---|---|
| Rank | Current rank based on chosen metric |
| Agent | Name + color dot + avatar |
| Equity | Current total equity |
| PnL $ | Dollar profit/loss |
| PnL % | Percentage return |
| # Trades | Total trades executed |
| Win Rate | % of winning trades |
| Sharpe | Sharpe ratio from equity curve |
| Max DD | Maximum drawdown percentage |
| Profit Factor | Gross profit / gross loss |
| Avg Duration | Average trade holding time |
| Best Trade | Largest single winning trade |
| Worst Trade | Largest single losing trade |

#### Agent Deep-Dive Modal (`src/components/battles/agent-deep-dive-modal.tsx`)

Clicking any agent card opens a full modal showing that agent's individual dashboard — reuses existing dashboard components (equity chart, positions table, recent trades, allocation pie, risk status) scoped to that battle participant.

---

## 11. Battle Results & History

### Battle List: `/battles`

Grid/list view of all battles (active, completed, draft). Each battle card shows: name, status badge, participant count with stacked agent avatars, duration, date, winner name + avatar (if completed).

- **Filter by:** status (draft, active, completed), date range
- **Sort by:** date, duration, participant count
- **"+ New Battle"** button → opens battle creation wizard

### Battle Results View (completed battles)

When a battle completes, the live dashboard transitions to the results view.

#### Podium Section (`src/components/battles/battle-podium.tsx`)

- Top 3 agents on a podium visualization (#1 center tallest, #2 left, #3 right)
- Each shows: agent name, avatar, final equity, PnL %, ranking metric value
- Gold / silver / bronze color treatment
- Confetti animation on first load

#### Final Standings Table

Same structure as the live comparison table but with final locked values. Includes CSV download button.

#### Key Moments Timeline (`src/components/battles/battle-timeline.tsx`)

Chronological timeline of significant events during the battle:

- Lead changes ("AlphaBot overtook MomentumX at 14:32")
- Biggest single trade ("ScalperBot made +$523 on BTCUSDT")
- Worst single trade ("MeanRevBot lost -$210 on ETHUSDT")
- Agent blown up ("AggressiveBot hit daily loss limit at 16:45")
- Maximum drawdown moments
- Agent paused/resumed events

#### Replay Feature (`src/components/battles/battle-replay-controls.tsx`)

Full equity race chart replay with a timeline scrubber:

- Uses `battle_snapshots` time-series data (5-second intervals)
- Playback speed: 1x, 2x, 5x, 10x
- Play / Pause / Scrub controls
- Scrubber bar with key moment markers
- Agent cards and metrics animate in sync with playback position

#### Export Options

- CSV: full trade history for all participants
- CSV: equity snapshots time-series
- JSON: complete battle data
- **"Rematch"** button: creates new battle with identical configuration

---

## 12. Component Inventory

### Agent Management Components

| Component | Path | Type |
|---|---|---|
| `AgentSwitcher` | `src/components/layout/agent-switcher.tsx` | Layout |
| `AgentCard` | `src/components/agents/agent-card.tsx` | Card |
| `AgentCreateModal` | `src/components/agents/agent-create-modal.tsx` | Modal |
| `AgentEditDrawer` | `src/components/agents/agent-edit-drawer.tsx` | Drawer |
| `AgentGrid` | `src/components/agents/agent-grid.tsx` | Grid |
| `AgentFilters` | `src/components/agents/agent-filters.tsx` | Controls |
| `AgentStatusBadge` | `src/components/agents/agent-status-badge.tsx` | Badge |
| `AgentColorDot` | `src/components/agents/agent-color-dot.tsx` | Indicator |
| `AgentAvatar` | `src/components/agents/agent-avatar.tsx` | Avatar |

### Battle Components

| Component | Path | Type |
|---|---|---|
| `BattleCard` | `src/components/battles/battle-card.tsx` | Card |
| `BattleGrid` | `src/components/battles/battle-grid.tsx` | Grid |
| `BattleCreateWizard` | `src/components/battles/battle-create-wizard.tsx` | Wizard |
| `BattlePresetPicker` | `src/components/battles/battle-preset-picker.tsx` | Selector |
| `BattleTopBar` | `src/components/battles/battle-top-bar.tsx` | Header |
| `BattleAgentCards` | `src/components/battles/battle-agent-cards.tsx` | Row |
| `BattleAgentCard` | `src/components/battles/battle-agent-card.tsx` | Card |
| `EquityRaceChart` | `src/components/battles/equity-race-chart.tsx` | Chart |
| `PnlComparisonBars` | `src/components/battles/pnl-comparison-bars.tsx` | Chart |
| `BattleTradeFeed` | `src/components/battles/battle-trade-feed.tsx` | Feed |
| `StrategyHeatmap` | `src/components/battles/strategy-heatmap.tsx` | Heatmap |
| `RiskRadarChart` | `src/components/battles/risk-radar-chart.tsx` | Chart |
| `BattleMetricsTable` | `src/components/battles/battle-metrics-table.tsx` | Table |
| `BattlePodium` | `src/components/battles/battle-podium.tsx` | Display |
| `BattleTimeline` | `src/components/battles/battle-timeline.tsx` | Timeline |
| `BattleReplayControls` | `src/components/battles/battle-replay-controls.tsx` | Controls |
| `AgentDeepDiveModal` | `src/components/battles/agent-deep-dive-modal.tsx` | Modal |

### New Hooks

| Hook | Path | Purpose |
|---|---|---|
| `useAgents` | `src/hooks/use-agents.ts` | CRUD + list all agents for developer |
| `useActiveAgent` | `src/hooks/use-active-agent.ts` | Get/set active agent context |
| `useAgentOverview` | `src/hooks/use-agent-overview.ts` | Cross-agent live stats |
| `useBattles` | `src/hooks/use-battles.ts` | CRUD + list battles |
| `useBattleLive` | `src/hooks/use-battle-live.ts` | WebSocket live battle data |
| `useBattleReplay` | `src/hooks/use-battle-replay.ts` | Replay playback state machine |

### New Zustand Stores

| Store | Path | Purpose |
|---|---|---|
| `agent-store` | `src/stores/agent-store.ts` | `activeAgentId`, agent list cache, switcher state |
| `battle-store` | `src/stores/battle-store.ts` | Active battle state, live WS participant data |

### New Pages

| Route | Page File | Layout |
|---|---|---|
| `/agents` | `src/app/(dashboard)/agents/page.tsx` | Dashboard (cross-agent) |
| `/battles` | `src/app/(dashboard)/battles/page.tsx` | Dashboard (cross-agent) |
| `/battles/[id]` | `src/app/(dashboard)/battles/[id]/page.tsx` | Dashboard (live/results) |

---

## 13. Development Phases & Tasks

Total estimated time: **6–7 weeks**. Phases are sequential — each builds on the previous.

### Phase 1: Multi-Agent Backend (Week 1–2)

**Goal:** Restructure database and API from 1:1 to 1:many account→agent model.

- [ ] Create `agents` table + Alembic migration
- [ ] Modify `accounts` table — strip agent-specific columns (migration)
- [ ] Re-key `balances`, `orders`, `positions`, `trades` to `agent_id` (migration)
- [ ] Write data migration script: existing accounts → developer + agent pairs
- [ ] Update API key authentication middleware to resolve `X-API-Key` → agent
- [ ] Build `src/database/repositories/agent_repo.py`
- [ ] Build `src/agents/service.py` — CRUD: create, list, get, update, clone, reset, archive, delete
- [ ] Build `src/api/routes/agents.py` — all agent management endpoints
- [ ] Build `src/api/schemas/agents.py` — Pydantic request/response models
- [ ] Build agent overview endpoint (aggregated live stats across all agents)
- [ ] Update `skill.md` generation to be per-agent (inject agent-specific API key)
- [ ] Build auto-generate avatar service (identicon-style from `agent_id` hash)
- [ ] Update all existing services to accept `agent_id` instead of `account_id`
- [ ] Update all existing tests to work with new agent model
- [ ] Run full test suite — zero failures

### Phase 2: Multi-Agent UI (Week 2–3)

**Goal:** Agent switcher in sidebar, agent management page, re-scope all existing pages.

- [ ] Build `src/stores/agent-store.ts` — Zustand: `activeAgentId`, agent list, switcher state
- [ ] Build `src/hooks/use-agents.ts` — TanStack Query: CRUD + list
- [ ] Build `src/hooks/use-active-agent.ts` — get/set active agent, persist selection
- [ ] Build `src/components/layout/agent-switcher.tsx` — sidebar dropdown
- [ ] Build `src/components/agents/agent-avatar.tsx` — auto-gen + custom image
- [ ] Build `src/components/agents/agent-color-dot.tsx` — colored indicator
- [ ] Build `src/components/agents/agent-status-badge.tsx` — status indicator
- [ ] Build `src/components/agents/agent-card.tsx` — full agent card with live stats
- [ ] Build `src/components/agents/agent-filters.tsx` — sort/filter controls
- [ ] Build `src/components/agents/agent-grid.tsx` — responsive grid layout
- [ ] Build `src/components/agents/agent-create-modal.tsx` — creation form
- [ ] Build `src/components/agents/agent-edit-drawer.tsx` — edit/clone/archive/delete
- [ ] Assemble `src/app/(dashboard)/agents/page.tsx`
- [ ] Create `src/app/(dashboard)/agents/loading.tsx` — skeleton loader
- [ ] Update sidebar to include agent switcher + new nav items (Agents, Battles)
- [ ] Update all existing hooks (`use-account`, `use-trades`, `use-analytics`, etc.) to include `activeAgentId` in query keys
- [ ] Update `src/lib/api-client.ts` to inject active agent context for JWT-auth requests
- [ ] Update WebSocket subscriptions to scope by active agent
- [ ] Split settings page into Account Settings + Agent Settings tabs
- [ ] Verify all existing pages (dashboard, wallet, trades, analytics) work with agent scoping
- [ ] Build passes with zero TypeScript errors

### Phase 3: Battle Backend (Week 3–4)

**Goal:** Battle CRUD, lifecycle management, snapshot engine, WebSocket channel.

- [ ] Create `battles` + `battle_participants` + `battle_snapshots` tables + Alembic migration
- [ ] Build `src/database/repositories/battle_repo.py`
- [ ] Build `src/battles/service.py` — full battle lifecycle management
- [ ] Build `src/battles/snapshot_engine.py` — Celery task for 5-second snapshots
- [ ] Build `src/battles/ranking.py` — ranking calculation for all 5 metrics
- [ ] Build `src/battles/wallet_manager.py` — fresh wallet snapshot/isolation logic
- [ ] Build `src/api/routes/battles.py` — all battle management endpoints
- [ ] Build `src/api/schemas/battles.py` — Pydantic request/response models
- [ ] Build battle WebSocket channel handler (`battle:update`, `battle:trade`, `battle:status`)
- [ ] Implement pause/resume per agent (freeze order execution for paused agents)
- [ ] Build preset configuration templates (Quick Sprint, Day Trader, Marathon, etc.)
- [ ] Build battle auto-completion logic (timer expiry, force-close positions)
- [ ] Build replay data endpoint (paginated time-series snapshots)
- [ ] Write unit tests for battle lifecycle, ranking, snapshot engine
- [ ] Write integration tests for battle WebSocket channel

### Phase 4: Battle UI — List & Creation (Week 4–5)

**Goal:** Battle list page, creation wizard with presets, battle management.

- [ ] Build `src/stores/battle-store.ts` — Zustand: active battle, live WS data
- [ ] Build `src/hooks/use-battles.ts` — TanStack Query: CRUD + list
- [ ] Build `src/components/battles/battle-card.tsx` — battle summary card
- [ ] Build `src/components/battles/battle-grid.tsx` — responsive grid
- [ ] Build `src/components/battles/battle-preset-picker.tsx` — visual preset cards
- [ ] Build `src/components/battles/battle-create-wizard.tsx` — 4-step wizard:
  - Step 1: Choose preset or custom
  - Step 2: Select agents (multi-select from agent list)
  - Step 3: Configure rules (duration, balance, pairs, ranking metric)
  - Step 4: Review + Start
- [ ] Assemble `src/app/(dashboard)/battles/page.tsx` — battle list
- [ ] Create `src/app/(dashboard)/battles/loading.tsx` — skeleton
- [ ] Build passes with zero TypeScript errors

### Phase 5: Battle Live Dashboard (Week 5–6)

**Goal:** The main event — real-time battle visualization.

- [ ] Build `src/hooks/use-battle-live.ts` — WebSocket integration for live data
- [ ] Build `src/components/battles/battle-top-bar.tsx` — timer, status, controls
- [ ] Build `src/components/battles/battle-agent-card.tsx` — individual participant card
- [ ] Build `src/components/battles/battle-agent-cards.tsx` — scrollable row
- [ ] Build `src/components/battles/equity-race-chart.tsx` — multi-line Recharts with auto-scroll
- [ ] Build `src/components/battles/pnl-comparison-bars.tsx` — grouped bar chart
- [ ] Build `src/components/battles/battle-trade-feed.tsx` — unified, color-coded feed
- [ ] Build `src/components/battles/strategy-heatmap.tsx` — agent × pair PnL grid
- [ ] Build `src/components/battles/risk-radar-chart.tsx` — overlaid radar charts
- [ ] Build `src/components/battles/battle-metrics-table.tsx` — sortable comparison table
- [ ] Build `src/components/battles/agent-deep-dive-modal.tsx` — reuses dashboard components
- [ ] Assemble `src/app/(dashboard)/battles/[id]/page.tsx` — tabbed live view
- [ ] Create `src/app/(dashboard)/battles/[id]/loading.tsx` — skeleton
- [ ] Build passes with zero TypeScript errors

### Phase 6: Battle Results & Polish (Week 6–7)

**Goal:** Results page, replay, export, notifications, responsive polish.

- [ ] Build `src/hooks/use-battle-replay.ts` — playback state machine
- [ ] Build `src/components/battles/battle-podium.tsx` — top 3 visualization + confetti
- [ ] Build `src/components/battles/battle-timeline.tsx` — key moments chronological view
- [ ] Build `src/components/battles/battle-replay-controls.tsx` — play/pause/scrub/speed
- [ ] Build export functionality (CSV trade history, CSV snapshots, JSON full data)
- [ ] Build "Rematch" button logic (clone battle config into new draft)
- [ ] Add battle-specific notification events to existing notification system:
  - Agent took the lead
  - Agent blown up / hit loss limit
  - Battle completed — results ready
  - Agent idle for 5+ minutes during battle
- [ ] Responsive design pass for all new pages (mobile + tablet)
- [ ] Loading skeletons for all new pages
- [ ] Error boundaries and empty states for all new pages
- [ ] Full build verification — zero TypeScript errors
- [ ] Update `UIdevelopmentProgress.md` with new phases
- [ ] Update `UItasks.md` with all new task entries
- [ ] Update `CLAUDE.md` with new component directories and architecture notes
- [ ] Update `context.md` with multi-agent model description

---

## 14. Migration Strategy

The multi-agent restructuring requires careful migration of existing data.

### Database Migration Steps

1. **Create `agents` table** (additive — no breaking changes yet)
2. **For each existing account**, create an `agents` row with the account's trading data (`api_key`, `starting_balance`, `risk_profile`). Link agent to account via `account_id`.
3. **Add `agent_id` column** to `balances`, `orders`, `positions`, `trades`, `trading_sessions` (nullable initially).
4. **Backfill `agent_id`** in all rows by mapping `account_id` → the newly created agent.
5. **Set `agent_id` to NOT NULL**, add foreign key constraints.
6. **Drop `account_id` column** from trading tables (or keep as denormalized reference).
7. **Strip `api_key` and trading columns** from `accounts` table.

### Zero-Downtime Approach

Steps 1–4 are additive and don't break existing functionality. Steps 5–7 are breaking changes and should be deployed together with the updated API code.

**Key risk:** Existing agents using old API key auth. Since the API key is moving from `accounts` to `agents`, the auth middleware must be updated simultaneously with step 7. A feature flag can be used to gradually roll out the new auth path.

---

## 15. Risks & Open Questions

### Technical Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Battle snapshot volume at scale | High write load with many active battles | TimescaleDB compression + retention policy (raw 30 days, downsample older) |
| Fresh wallet isolation complexity | Edge cases with concurrent orders during snapshot | Use DB transactions, snapshot before unlocking agents |
| WebSocket scalability with many battles | Each battle is a new channel with subscribers | Redis pub/sub fan-out, consider dedicated WS worker for battles |
| Agent switcher re-rendering | Changing agent triggers data refetch across all pages | TanStack Query cache keyed by `agentId`, show stale data during transition |
| Migration data integrity | Re-keying existing trading data is high-risk | Run migration on staging first, verify row counts, add checksums |

### Open Questions for Future Consideration

- Should there be a free tier agent limit even though the decision was unlimited? Revisit for monetization.
- When using fresh battle wallets, should the agent's real wallet be frozen during the battle?
- Should battle snapshots include individual position data (deeper replay) or just aggregate equity?
- How should the leaderboard integrate with battles when public battles are added?
- Should there be a battle template sharing feature (share preset configs with other developers)?

---

*This document is the authority for the Multi-Agent and Agents Battle feature. All implementation — file names, component names, schemas, endpoints — MUST match what is specified here. Do not deviate without explicit product owner approval.*

*Update `tasks.md`, `developmentprogress.md`, `UItasks.md`, `UIdevelopmentProgress.md`, and `CLAUDE.md` as phases are completed.*