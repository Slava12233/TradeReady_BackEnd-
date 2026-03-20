# TradeReady Agent Ecosystem — Master Plan

> **Vision:** A self-improving AI trading agent that trades, learns, and improves both itself and the platform it runs on. The agent and platform form a feedback loop — the agent identifies what it needs, we build it, the agent gets better, it identifies the next need.

---

## Core Principles

1. **Agent-first development** — every platform feature is evaluated by "does this help the agent trade better?"
2. **Ecosystem feedback loop** — Agent trades → learns → identifies gaps → platform improves → agent improves → repeat
3. **Graduated autonomy** — start with human approval, earn trust through results
4. **One agent first** — build one capable agent, then evolve into specialized teams
5. **No rush, do it right** — architect for the long term, build phase by phase

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────┐
│                    USER INTERFACES                        │
│   CLI (Phase 1) → Telegram (Phase 3) → Chat UI (Phase 4)│
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│                   AGENT CORE                              │
│                                                           │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │ Reasoning    │  │ Memory       │  │ Permission      │ │
│  │ Loop         │  │ System       │  │ System          │ │
│  │ (Pydantic AI │  │              │  │                 │ │
│  │ + OpenRouter)│  │ Conversation │  │ Roles (RBAC)    │ │
│  │              │  │ Journal      │  │ Capabilities    │ │
│  │ Tools:       │  │ Learnings    │  │ Budget limits   │ │
│  │  SDK + MCP   │  │ Patterns     │  │                 │ │
│  └─────────────┘  └──────────────┘  └─────────────────┘ │
│                                                           │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │ Trading     │  │ Strategy     │  │ Platform        │ │
│  │ Engine      │  │ Manager      │  │ Feedback        │ │
│  │             │  │              │  │                 │ │
│  │ 5 strategies│  │ A/B testing  │  │ Gap detection   │ │
│  │ Risk overlay│  │ Auto-tune    │  │ Tool requests   │ │
│  │ Ensemble    │  │ Regime switch│  │ Bug reports     │ │
│  └─────────────┘  └──────────────┘  └─────────────────┘ │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│               PLATFORM (TradeReady)                       │
│                                                           │
│  REST API (86+) │ WebSocket │ MCP (58 tools) │ SDK       │
│  Backtest Engine │ Battle System │ Strategy Registry      │
│  Order Engine │ Risk Manager │ Portfolio Tracker          │
│  TimescaleDB │ Redis │ Celery │ Price Ingestion           │
└──────────────────────────────────────────────────────────┘
```

---

## Data & Storage Architecture

```
┌─────────────────────────────────────────────────┐
│                 PostgreSQL (TimescaleDB)          │
│                                                   │
│  EXISTING TABLES (reference via FK):              │
│  - agents, orders, trades, positions, balances    │
│  - backtest_sessions, battles, strategies         │
│  - training_runs                                  │
│                                                   │
│  NEW AGENT TABLES:                                │
│  - agent_sessions      → conversation sessions    │
│  - agent_messages      → chat history per session │
│  - agent_decisions     → trade decisions + reason │
│  - agent_journal       → trading journal entries  │
│  - agent_learnings     → what the agent learned   │
│  - agent_feedback      → platform improvement ideas│
│  - agent_permissions   → per-agent capability map │
│  - agent_budgets       → daily/weekly trade limits│
│  - agent_performance   → rolling strategy stats   │
│                                                   │
│  HYPERTABLES (time-series):                       │
│  - agent_observations  → market snapshots at each │
│                          decision point           │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│                    Redis                          │
│                                                   │
│  HOT STATE:                                       │
│  - agent:active_session:{agent_id}  → current ctx │
│  - agent:permissions:{agent_id}     → cached perms│
│  - agent:budget:{agent_id}:{date}   → daily usage │
│  - agent:last_regime:{agent_id}     → current mode│
│  - agent:signals:{agent_id}         → latest sigs │
│                                                   │
│  PUB/SUB:                                         │
│  - agent:events     → agent decisions broadcast   │
│  - agent:feedback   → platform improvement queue  │
└─────────────────────────────────────────────────┘
```

---

## Phase 1: Agent Core (Foundation)

**Goal:** A persistent, stateful agent that can hold conversations, remember context, and execute trades through the existing platform.

### 1.1 Agent Server (persistent process)
- `agent/server.py` — long-running async process (not one-shot CLI)
- Event loop: listen for user input → reason → act → respond → persist
- Graceful shutdown, auto-restart on crash
- Health check endpoint for monitoring
- Celery beat integration for scheduled tasks (e.g., morning market review)

### 1.2 Conversation System
- `agent/conversation/` package:
  - `session.py` — `AgentSession` class managing one conversation
  - `history.py` — load/save conversation history from Postgres
  - `context.py` — build LLM context from recent messages + relevant memory
  - `router.py` — classify user intent → route to correct handler
- Context window management: summarize old messages, keep recent ones verbatim
- System prompt dynamically assembled from: base persona + current portfolio state + recent learnings + active strategy info

### 1.3 Memory System
- `agent/memory/` package:
  - `store.py` — abstract memory store interface
  - `postgres_store.py` — Postgres-backed implementation
  - `redis_cache.py` — Redis hot cache for frequently accessed memories
  - `retrieval.py` — search memories by relevance (keyword + recency scoring)
- Memory types:
  - **Episodic** — specific events: "On March 15, BTC dropped 8% and I got stopped out on 3 positions"
  - **Semantic** — learned facts: "SOL correlates with ETH at 0.85 in trending markets"
  - **Procedural** — learned behaviors: "Reduce position size by 50% when ADX drops below 20"
  - **Working** — current session context (Redis)

### 1.4 Database Migrations
- New Alembic migration for all `agent_*` tables
- Foreign keys to existing `agents`, `orders`, `trades` tables
- TimescaleDB hypertable for `agent_observations`

### 1.5 CLI Chat Interface (first UI)
- `agent/cli.py` — interactive REPL
- Commands: `/trade`, `/analyze`, `/portfolio`, `/journal`, `/learn`, `/permissions`, `/status`
- Natural language for everything else → LLM reasoning
- Colored output, markdown rendering in terminal
- Session persistence (resume where you left off)

### 1.6 Enhanced Tool Set
- Extend existing SDK/MCP tools with agent-specific capabilities:
  - `reflect_on_trade(trade_id)` — analyze a completed trade, extract learnings
  - `review_portfolio()` — full portfolio health check with recommendations
  - `scan_opportunities(criteria)` — find trading setups matching criteria
  - `journal_entry(content)` — save a journal entry with market context
  - `request_platform_feature(description)` — log a feature request

---

## Phase 2: Trading Intelligence

**Goal:** Agent actively trades, maintains a journal, and improves its strategies based on outcomes.

### 2.1 Trading Loop
- `agent/trading/` package:
  - `loop.py` — main trading loop (configurable interval: 1h, 4h, 1d)
  - `signal_generator.py` — combines all 5 strategies into actionable signals
  - `execution.py` — execute trades through SDK with pre/post logging
  - `monitor.py` — watch open positions, manage exits
- Loop cycle: observe → analyze → decide → (check permissions) → execute → record → learn

### 2.2 Trading Journal
- Every trade decision persisted with:
  - Market snapshot (prices, indicators, regime)
  - Which strategies fired and their signals
  - Ensemble consensus and confidence
  - Risk assessment from the overlay
  - Final decision and reasoning (LLM-generated narrative)
  - Outcome (P&L, hold duration, max adverse excursion)
  - Post-trade reflection (what went right/wrong)

### 2.3 Strategy Management
- Agent can:
  - Monitor strategy performance in real-time
  - Detect strategy degradation (Sharpe dropping below threshold)
  - Suggest parameter adjustments based on recent performance
  - Run A/B tests: variant A vs variant B over N trades
  - Promote winning variants automatically

### 2.4 Permission System
- `agent/permissions/` package:
  - `roles.py` — RBAC: `viewer`, `paper_trader`, `live_trader`, `admin`
  - `capabilities.py` — granular toggles: `can_trade`, `can_modify_strategy`, `can_adjust_risk`, `can_report`
  - `budget.py` — daily limits: max trades, max exposure, max loss
  - `enforcement.py` — check permissions before every action
- Permission escalation: agent can REQUEST higher permissions with justification
- Audit log: every permission check recorded

---

## Phase 3: Platform Feedback Loop

**Goal:** Agent identifies what it needs from the platform to trade better and communicates it clearly.

### 3.1 Gap Detection
- After each trading session, agent reflects:
  - "What data did I wish I had?"
  - "What tool would have helped?"
  - "What was slow or broken?"
- Structured feedback saved to `agent_feedback` table
- Categorized: `missing_data`, `missing_tool`, `performance_issue`, `bug`, `feature_request`

### 3.2 Self-Assessment
- Weekly automated review:
  - Strategy-level P&L breakdown
  - Win rate by regime, by time of day, by asset
  - Drawdown analysis with root cause
  - Comparison vs benchmarks
- Generates a "Weekly Agent Report" (Pydantic model → JSON → dashboard)

### 3.3 Telegram Integration
- `agent/integrations/telegram.py`
- Bot commands: `/status`, `/portfolio`, `/trade BTCUSDT buy`, `/journal`, `/report`
- Push notifications: trade executed, stop-loss hit, regime change, daily summary
- Inline approval: agent sends trade proposal → user taps Approve/Reject

### 3.4 Real-time Event Handling
- WebSocket subscription to platform events:
  - Price ticks → update market model
  - Order fills → update portfolio state
  - Position changes → trigger risk check
- Polling fallback when WS disconnects
- Reconnection with exponential backoff

---

## Phase 4: User Experience

**Goal:** Rich chat UI in the frontend dashboard for natural interaction with the agent.

### 4.1 Chat UI Component
- `Frontend/src/components/agent-chat/` — React chat interface
- Features:
  - Natural language input
  - Agent responses with markdown, charts, tables
  - Trade proposal cards with Approve/Reject buttons
  - Portfolio visualization inline
  - Strategy performance charts
  - Journal entries with market context
- WebSocket-based real-time communication

### 4.2 Agent Dashboard
- `Frontend/src/app/(app)/agent/` — dedicated agent section
- Pages:
  - `/agent` — agent status, current strategy, P&L today
  - `/agent/journal` — trading journal with filters and search
  - `/agent/memory` — what the agent knows/remembers
  - `/agent/permissions` — configure autonomy level
  - `/agent/feedback` — agent's platform improvement suggestions
  - `/agent/performance` — detailed strategy analytics

### 4.3 Human-in-the-Loop
- Trade approval flow:
  1. Agent proposes trade (shown as a card in chat)
  2. User sees: symbol, direction, size, reasoning, risk assessment
  3. User taps: Approve / Modify / Reject
  4. Agent executes (or adjusts) and reports result
- Configurable: which actions need approval vs autonomous

---

## Phase 5: Multi-Agent Evolution

**Goal:** Split the single agent into specialized roles when complexity warrants it.

### 5.1 Agent Specialization
- **Trader Agent** — executes the trading loop, manages positions
- **Analyst Agent** — market analysis, regime detection, opportunity scanning
- **Risk Agent** — portfolio monitoring, drawdown prevention, position sizing
- **DevOps Agent** — platform monitoring, bug detection, performance tracking

### 5.2 Inter-Agent Communication
- Shared message bus (Redis pub/sub)
- Structured message protocol: `{from, to, type, payload, priority}`
- Orchestrator pattern: one coordinator dispatches tasks to specialists

### 5.3 Agent Cloning & Competition
- Clone an agent with modified parameters
- Run both in parallel (paper-trading)
- Compare performance after N days
- Promote the winner, retire the loser

---

## Milestones (in order)

| # | Milestone | Success Criteria | Estimated Effort |
|---|-----------|-----------------|------------------|
| **M1** | Profitable backtest | Agent autonomously runs backtest, adjusts strategy, achieves Sharpe > 1.0 | 1-2 weeks |
| **M2** | Live paper-trading | Agent trades virtual money against real-time prices for 7 days, positive P&L | 1-2 weeks |
| **M3** | Self-improvement cycle | Agent identifies a gap, suggests improvement, improvement is applied, performance improves measurably | 2-3 weeks |
| **M4** | Full conversation loop | User chats with agent in CLI, discusses market, approves trade, agent executes and reports back | 1-2 weeks |
| **M5** | Trading journal | Every decision logged with reasoning, outcomes tracked, learnings extracted | 1 week |
| **M6** | Permission system | Role + capability + budget-based permission enforcement working | 1 week |
| **M7** | Telegram bot | Agent accessible via Telegram with trade proposals and notifications | 1-2 weeks |
| **M8** | Chat UI | Frontend chat component with trade approval cards and inline charts | 2-3 weeks |
| **M9** | Agent dashboard | Dedicated frontend section for agent status, journal, memory, permissions | 2 weeks |
| **M10** | Multi-agent foundation | Orchestrator + 2 specialized agents communicating via Redis | 2-3 weeks |

---

## Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM Provider | OpenRouter | Already integrated, multi-model access, pay-per-token |
| Agent Framework | Pydantic AI | Already in use, typed outputs, lightweight |
| Platform Integration | SDK + MCP | SDK for fast calls, MCP for LLM tool discovery |
| Conversation Storage | PostgreSQL | Structured data, already running, FK to platform tables |
| Hot State | Redis | Sub-ms reads, already running, pub/sub for events |
| Memory Search | Postgres full-text + recency | Good enough for V1; upgrade to vector DB later if needed |
| Real-time Events | WebSocket + polling fallback | Best reliability, platform WS already exists |
| Permission Model | RBAC + Capabilities + Budget | Maximum flexibility, Claude Code-inspired |
| First UI | CLI REPL | Fastest to build, developer-friendly |
| Journal Format | Structured Pydantic models | Queryable, reportable, LLM-readable |

---

## What We Already Have (don't rebuild)

| Component | Location | Reuse? |
|-----------|----------|--------|
| Pydantic AI agent setup | `agent/main.py`, `agent/workflows/` | Extend, don't replace |
| SDK tools (7 functions) | `agent/tools/sdk_tools.py` | Add new tools alongside |
| MCP server (58 tools) | `src/mcp/server.py` | Add agent-specific tools |
| REST tools (11 functions) | `agent/tools/rest_tools.py` | Add new endpoints |
| 5 trained strategies | `agent/strategies/` | Wire into trading loop |
| Risk overlay | `agent/strategies/risk/` | Use as permission enforcement layer |
| System prompt | `agent/prompts/system.py` | Evolve into dynamic prompt builder |
| Output models | `agent/models/` | Extend with journal/memory models |
| Agent config | `agent/config.py` | Add memory/permission config fields |
| Platform API | `src/api/routes/` | Add `/api/v1/agent/` endpoints |
| WebSocket | `src/api/websocket/` | Subscribe agent to price/order events |
| TimescaleDB | Running | Add new tables |
| Redis | Running | Add agent state keys |
| Docker | `agent/Dockerfile` | Add persistent mode |

---

## Execution Order

```
Phase 1.4 (DB migrations)        ← do first, tables needed by everything
Phase 1.2 (conversation system)  ← core agent identity
Phase 1.3 (memory system)        ← agent needs to remember
Phase 1.1 (agent server)         ← persistent process
Phase 1.5 (CLI chat)             ← first user interface
Phase 1.6 (enhanced tools)       ← agent needs more capabilities
    │
    ▼
Phase 2.4 (permissions)          ← safety before trading
Phase 2.1 (trading loop)         ← the main event
Phase 2.2 (trading journal)      ← learn from every trade
Phase 2.3 (strategy management)  ← optimize continuously
    │
    ▼
MILESTONE M1: Profitable backtest
MILESTONE M2: Live paper-trading
    │
    ▼
Phase 3.1 (gap detection)        ← agent tells us what it needs
Phase 3.2 (self-assessment)      ← weekly performance review
Phase 3.4 (real-time events)     ← react to market in real-time
    │
    ▼
MILESTONE M3: Self-improvement cycle
MILESTONE M4: Full conversation loop
    │
    ▼
Phase 3.3 (Telegram)             ← mobile access
Phase 4.1 (Chat UI)              ← rich frontend experience
Phase 4.2 (Agent dashboard)      ← monitoring and control
Phase 4.3 (Human-in-the-loop)    ← approval workflows
    │
    ▼
MILESTONE M5-M9
    │
    ▼
Phase 5 (Multi-agent)            ← when single agent is proven
```

---

## The Feedback Loop (Why This Matters)

```
    ┌─────────────────────────────────────────┐
    │                                         │
    ▼                                         │
Agent trades ──► Agent learns ──► Agent       │
                                 identifies   │
                                 gaps ────────┤
                                              │
Platform improves ◄── We build ◄── Agent      │
                      what agent   requests ──┘
                      needs
```

This is not just an agent. It's a **self-improving ecosystem** where:
- The agent's trading performance is the KPI
- Every platform feature is justified by "does this help the agent trade better?"
- The agent is both the user and the QA tester of the platform
- Success compounds: better platform → better agent → better feedback → better platform

---

## Next Step

Convert this plan into task files using `/plan-to-tasks` and start with Phase 1.4 (database migrations) + Phase 1.2 (conversation system).
