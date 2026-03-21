---
type: plan
title: "TradeReady Execution Plan"
status: archived
phase: ccxt-integration
tags:
  - plan
  - ccxt-integration
---

# TradeReady Execution Plan

**Status**: Phase 1 & Phase 2 COMPLETE — Phase 3 next
**Created**: 2026-03-18
**Owner**: Slava & Ilia
**Context**: Pre-launch, bootstrapped, proprietary, fully shipped core platform (now multi-exchange via CCXT)
**Target audience**: LLM agent builders (Claude, GPT, Gemini, LangChain, CrewAI, etc.)

---

## Strategic Summary

TradeReady's core differentiators are shipped and production-ready: step-mode backtesting, battle system, agent-controlled sandboxes, and API-first architecture. The two critical gaps preventing launch are:

1. **Exchange coverage** — Currently Binance-only in a market where competitors offer 13-110+ exchanges
2. **MCP tool coverage** — Only 12 of 86+ endpoints exposed via MCP, while QuantConnect offers 60+ tools

This plan addresses both gaps, then layers on launch strategy (AI trading competition) and monetization (freemium tiers).

---

## Phase 1: CCXT Abstraction Layer (Week 1-2)

> **Goal**: Build a clean exchange abstraction so adding any exchange is trivial. Start with Binance parity, then expand.

### Why This First

- The #1 strategic priority from the competitive research
- Competitors have 13-107+ exchanges; we have 1
- CCXT is free (MIT), supports 110 exchanges, has native Python async support
- The CCXT report recommends the Adapter Pattern — never call CCXT directly

### Current State (What Exists)

| File | What It Does | CCXT Replaces? |
|------|-------------|----------------|
| `src/price_ingestion/binance_ws.py` | `BinanceWebSocketClient` — WS tick streaming | Yes — `ccxt.pro.watchTrades()` |
| `src/price_ingestion/binance_klines.py` | `fetch_binance_klines()` — REST kline fallback | Yes — `ccxt.fetchOHLCV()` |
| `scripts/backfill_history.py` | Historical candle backfill from Binance REST | Yes — universal multi-exchange backfill |
| `scripts/seed_pairs.py` | Fetch trading pairs from Binance exchangeInfo | Yes — `ccxt.fetchMarkets()` |

All four files hardcode `api.binance.com`. No exchange abstraction exists. `ccxt` is not installed.

### Tasks

#### 1.1 — Install CCXT and create the Exchange Adapter interface

**Files to create:**
- `src/exchange/__init__.py`
- `src/exchange/adapter.py` — Abstract base class `ExchangeAdapter`
- `src/exchange/ccxt_adapter.py` — `CCXTAdapter` implementing the interface
- `src/exchange/types.py` — Shared types (`ExchangeTick`, `ExchangeCandle`, `ExchangeMarket`)
- `src/exchange/symbol_mapper.py` — Bidirectional symbol translation (`BTCUSDT` ↔ `BTC/USDT`)
- `src/exchange/CLAUDE.md` — Module documentation

**`ExchangeAdapter` interface (abstract methods):**

```python
class ExchangeAdapter(ABC):
    # Market data (REST)
    async def fetch_markets(self) -> list[ExchangeMarket]
    async def fetch_ticker(self, symbol: str) -> dict
    async def fetch_ohlcv(self, symbol: str, timeframe: str, since: int | None, limit: int) -> list[ExchangeCandle]
    async def fetch_order_book(self, symbol: str, limit: int) -> dict
    async def fetch_trades(self, symbol: str, limit: int) -> list[dict]

    # Real-time streaming (WebSocket)
    async def watch_trades(self, symbol: str) -> AsyncGenerator[ExchangeTick, None]
    async def watch_tickers(self, symbols: list[str]) -> AsyncGenerator[dict, None]

    # Trading (Phase 8 — live execution)
    async def create_order(self, symbol: str, type: str, side: str, amount: Decimal, price: Decimal | None) -> dict
    async def cancel_order(self, order_id: str, symbol: str) -> dict
    async def fetch_balance(self) -> dict

    # Lifecycle
    async def close(self) -> None

    # Metadata
    @property
    def exchange_id(self) -> str
    @property
    def has_websocket(self) -> bool
```

**`CCXTAdapter` implementation:**
- Wraps `ccxt.async_support` for REST, `ccxt.pro` for WebSocket
- Handles symbol translation internally (converts `BTCUSDT` → `BTC/USDT` before calling CCXT, converts back on response)
- Disables builder fee: `exchange.options['builderFee'] = False`
- Exposes exchange-specific rate limit config
- Catches CCXT exceptions and wraps them in our `TradingPlatformError` hierarchy

**`SymbolMapper`:**
- `to_ccxt(symbol: str) -> str` — `"BTCUSDT"` → `"BTC/USDT"`
- `from_ccxt(symbol: str) -> str` — `"BTC/USDT"` → `"BTCUSDT"`
- Must handle edge cases: `SHIBUSDT`, `1000PEPEUSDT`, etc.
- Use CCXT's `exchange.markets` data for authoritative mapping (base/quote split)

**Config changes (`src/config.py`):**
- Add `exchange_id: str = "binance"` (default to Binance for backward compat)
- Add `exchange_api_key: str | None = None` (for future live trading)
- Add `exchange_secret: str | None = None`
- Add `additional_exchanges: list[str] = []` (for multi-exchange price ingestion)

**Dependency changes:**
- Add `ccxt>=4.0.0` to `requirements.txt`

**Acceptance criteria:**
- [x] `CCXTAdapter("binance")` can fetch all USDT markets
- [x] `CCXTAdapter("binance")` can fetch OHLCV candles identical to current `backfill_history.py` output
- [x] `CCXTAdapter("binance")` can stream trades via WebSocket identical to current `BinanceWebSocketClient`
- [x] `CCXTAdapter("okx")` and `CCXTAdapter("bybit")` can fetch markets and OHLCV
- [x] Symbol translation is lossless round-trip for all 600+ USDT pairs (30 unit tests pass)
- [x] All CCXT calls are behind the `ExchangeAdapter` interface — no direct CCXT imports outside `ccxt_adapter.py`

---

#### 1.2 — Migrate price ingestion to use CCXT adapter

**Files to modify:**
- `src/price_ingestion/service.py` — Replace `BinanceWebSocketClient` with `CCXTAdapter.watch_trades()`
- `src/price_ingestion/binance_ws.py` — Keep as fallback / eventually deprecate
- `src/price_ingestion/binance_klines.py` — Replace with `CCXTAdapter.fetch_ohlcv()`
- `src/config.py` — Add exchange config fields

**Architecture change:**
```
BEFORE: BinanceWebSocketClient → Tick → PriceCache + TickBuffer
AFTER:  CCXTAdapter.watch_trades() → ExchangeTick → SymbolMapper → Tick → PriceCache + TickBuffer
```

**Key constraints:**
- Downstream pipeline stays identical: `PriceCache`, `TickBuffer`, `PriceBroadcaster` see the same `Tick` objects
- Redis keys stay `HSET prices BTCUSDT {price}` — symbol format unchanged externally
- `ticks` table schema unchanged — symbol column stays `BTCUSDT` format
- Must handle 600+ pairs across potentially multiple WS connections (CCXT handles connection multiplexing)

**Multi-exchange support (data model change):**
- Add `exchange` column to `ticks` table (VARCHAR(20), default `'binance'`, NOT NULL)
- Add `exchange` column to `candles_backfill` table
- Update Redis key pattern: `HSET prices:{exchange} {SYMBOL} {price}` (keep `HSET prices {SYMBOL} {price}` as alias for default exchange)
- Migration: Alembic migration to add column with default value (safe, non-destructive)

**Acceptance criteria:**
- [x] Price ingestion works identically with CCXT adapter (Binance produces same tick stream)
- [x] Can add a second exchange (e.g., OKX) by config change only
- [x] Zero downtime — old `BinanceWebSocketClient` kept as fallback during transition
- [x] `TickBuffer` flush and `PriceBroadcaster` work unchanged

---

#### 1.3 — Migrate backfill scripts to use CCXT adapter

**Files to modify:**
- `scripts/backfill_history.py` — Replace direct `httpx` calls with `CCXTAdapter.fetch_ohlcv()`
- `scripts/seed_pairs.py` — Replace direct `httpx` calls with `CCXTAdapter.fetch_markets()`

**New capabilities:**
- `--exchange binance|okx|bybit|...` flag on both scripts
- Universal backfill: same code, any exchange
- Pair seeding from any exchange's market data

**Acceptance criteria:**
- [x] `python scripts/backfill_history.py --exchange binance --daily` produces identical output to current script
- [x] `python scripts/backfill_history.py --exchange okx --hourly` backfills OKX candle data
- [x] `python scripts/seed_pairs.py --exchange bybit` seeds Bybit trading pairs

---

#### 1.4 — Update backtesting engine for multi-exchange data

**Files to modify:**
- `src/backtesting/data_replayer.py` — Add `exchange` filter to queries
- `src/backtesting/sandbox.py` — Pass exchange context for price lookups
- `src/api/schemas/backtesting.py` — Add `exchange` field to backtest creation schema

**Key change:**
- `DataReplayer` queries `WHERE exchange = :exchange AND bucket <= virtual_clock`
- Agents can now backtest strategies against OKX or Bybit historical data, not just Binance
- Default to `"binance"` for backward compatibility

**Acceptance criteria:**
- [x] Existing backtests work unchanged (default exchange = binance)
- [x] New backtests can specify `exchange: "okx"` and use OKX candle data (data filtering pending DB migration)
- [x] No look-ahead bias regardless of exchange source

---

### Phase 1 — COMPLETED (2026-03-18)

| Task | Status | Notes |
|------|--------|-------|
| 1.1 — Adapter interface + CCXT implementation | **DONE** | 6 new files in `src/exchange/`, 30 unit tests |
| 1.2 — Migrate price ingestion | **DONE** | `exchange_ws.py` + `exchange_klines.py` + updated `service.py` |
| 1.3 — Migrate backfill scripts | **DONE** | `--exchange` flag added to both scripts |
| 1.4 — Multi-exchange backtesting | **DONE** | `exchange` field in config/schema/engine/replayer (DB column pending migration) |
| Code review | **DONE** | 5 critical issues found and fixed |
| Lint + tests | **DONE** | 0 lint errors, 1012/1012 tests pass |

### Bug Fixes (2026-03-18, post-Phase 1)

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| Battle creation 500 | `model_dump()` produced non-JSON-serializable `datetime` objects in JSONB column | Changed to `model_dump(mode="json")` in `routes/battles.py` |
| Battle invalid state → 500 | Local `BattleInvalidStateError(Exception)` in `service.py` not caught by global handler | Removed local class, imported from `src.utils.exceptions` (maps to HTTP 409) |
| Backtest metrics return None | `_persist_results()` used `db.flush()` — results invisible to concurrent readers | Changed to `db.commit()` in `engine.py:634` |
| 33 test lint errors | Unused imports, unsorted imports, naming conventions | Auto-fixed 24, manually fixed 9. Now 0 errors across `src/` + `tests/` |

---

## Phase 2: MCP Server Expansion (Week 2-3)

> **Goal**: Expand from 12 to 40+ MCP tools covering the full trading lifecycle. This is THE integration point for LLM agent builders.

### Why This Second

- Target audience is LLM agent builders — MCP is how they connect
- QuantConnect has 60+ MCP tools; we have 12 (14% coverage)
- The entire backtesting system (our #1 differentiator) has ZERO MCP tools
- The entire agent management system has ZERO MCP tools
- The entire battle system has ZERO MCP tools

### Current State

**12 tools exist** in `src/mcp/tools.py`:
- Market data: `get_price`, `get_all_prices`, `get_candles` (3)
- Account: `get_balance`, `get_positions`, `get_portfolio`, `reset_account` (4)
- Trading: `place_order`, `cancel_order`, `get_order_status` (3)
- Analytics: `get_performance`, `get_trade_history` (2)

**86+ REST endpoints exist** but are not exposed via MCP.

### Tasks

#### 2.1 — Add backtesting tools (highest priority — our #1 differentiator)

**New MCP tools (8 tools):**

| # | Tool Name | REST Endpoint | Description |
|---|-----------|---------------|-------------|
| 13 | `get_data_range` | `GET /backtest/data-range` | Check available historical data timespan per symbol/exchange |
| 14 | `create_backtest` | `POST /backtest/create` | Create a new backtest session with symbol, timeframe, date range, starting balance |
| 15 | `start_backtest` | `POST /backtest/{id}/start` | Preload data and begin stepping |
| 16 | `step_backtest` | `POST /backtest/{id}/step` | Advance time by one bar — returns current prices, portfolio state, open orders |
| 17 | `step_backtest_batch` | `POST /backtest/{id}/step/batch` | Advance by N bars at once (for fast-forwarding) |
| 18 | `backtest_trade` | `POST /backtest/{id}/trade/order` | Place an order inside the backtest sandbox |
| 19 | `get_backtest_results` | `GET /backtest/{id}/results` | Get full results: metrics, equity curve, trade list |
| 20 | `list_backtests` | `GET /backtest/list` | List all backtest sessions with status and summary metrics |

**Why these 8 tools unlock everything:**
An LLM agent can now autonomously:
1. Check data range → Create backtest → Start it
2. Loop: Step → Observe prices → Decide → Place trades → Step again
3. Get results → Compare with previous runs → Iterate

This is the **step-mode backtesting through MCP** that no competitor offers. It's our strongest marketing story.

**Acceptance criteria:**
- [x] Claude (via MCP) can create, run, trade in, and analyze a backtest end-to-end
- [x] `step_backtest` returns enough state for the LLM to make trading decisions (prices, balance, positions, open orders)
- [x] All 8 tools documented in `docs/mcp_server.md`

---

#### 2.2 — Add missing market data and trading tools

**New MCP tools (7 tools):**

| # | Tool Name | REST Endpoint | Description |
|---|-----------|---------------|-------------|
| 21 | `get_pairs` | `GET /market/pairs` | List all trading pairs with filters (exchange, status, quote asset) |
| 22 | `get_ticker` | `GET /market/ticker/{symbol}` | 24h stats: open, high, low, close, volume, change % |
| 23 | `get_orderbook` | `GET /market/orderbook/{symbol}` | Bid/ask depth for slippage estimation |
| 24 | `get_recent_trades` | `GET /market/trades/{symbol}` | Recent public trades from tick history |
| 25 | `get_open_orders` | `GET /trade/orders/open` | List all pending orders |
| 26 | `cancel_all_orders` | `DELETE /trade/orders/open` | Cancel all open orders at once |
| 27 | `list_orders` | `GET /trade/orders` | List orders with status/symbol filter |

**Acceptance criteria:**
- [x] LLM agents can discover available pairs, assess market conditions, and manage orders fully via MCP

---

#### 2.3 — Add agent management tools

**New MCP tools (6 tools):**

| # | Tool Name | REST Endpoint | Description |
|---|-----------|---------------|-------------|
| 28 | `list_agents` | `GET /agents` | List all agents under the account |
| 29 | `create_agent` | `POST /agents` | Create a new agent with name, starting balance, risk profile |
| 30 | `get_agent` | `GET /agents/{id}` | Get agent details, balance, performance summary |
| 31 | `reset_agent` | `POST /agents/{id}/reset` | Reset agent to starting balance (preserves history) |
| 32 | `update_agent_risk` | `PUT /agents/{id}/risk-profile` | Adjust risk limits (max position, daily loss limit) |
| 33 | `get_agent_skill` | `GET /agents/{id}/skill.md` | Get the agent's personalized skill file (with pre-filled API key) |

**Why these matter:**
LLM agents can now self-provision new sub-agents, configure their risk profiles, and reset them after blow-ups — enabling the "blow up 1,000 accounts before breakfast" workflow entirely through MCP.

---

#### 2.4 — Add battle/competition tools

**New MCP tools (6 tools):**

| # | Tool Name | REST Endpoint | Description |
|---|-----------|---------------|-------------|
| 34 | `create_battle` | `POST /battles` | Create a new battle (agents, rules, mode) |
| 35 | `list_battles` | `GET /battles` | List battles with status filter |
| 36 | `start_battle` | `POST /battles/{id}/start` | Begin the competition |
| 37 | `get_battle_live` | `GET /battles/{id}/live` | Real-time battle state (scores, positions, equity) |
| 38 | `get_battle_results` | `GET /battles/{id}/results` | Final results, rankings, metrics per agent |
| 39 | `get_battle_replay` | `GET /battles/{id}/replay` | Step-by-step replay data for analysis |

---

#### 2.5 — Add missing account and analytics tools

**New MCP tools (4 tools):**

| # | Tool Name | REST Endpoint | Description |
|---|-----------|---------------|-------------|
| 40 | `get_account_info` | `GET /account/info` | Account details, session info, current risk profile |
| 41 | `get_pnl` | `GET /account/pnl` | PnL breakdown: realized, unrealized, fees, win rate |
| 42 | `get_portfolio_history` | `GET /analytics/portfolio/history` | Equity curve snapshots (for charting/analysis) |
| 43 | `get_leaderboard` | `GET /analytics/leaderboard` | Cross-account ranking by ROI |

---

### Phase 2 — COMPLETED (2026-03-18)

| Task | Status | Notes |
|------|--------|-------|
| 2.1 — Backtesting tools (8) | **DONE** | get_data_range, create_backtest, start_backtest, step_backtest, step_backtest_batch, backtest_trade, get_backtest_results, list_backtests |
| 2.2 — Market + trading tools (7) | **DONE** | get_pairs, get_ticker, get_orderbook, get_recent_trades, get_open_orders, cancel_all_orders, list_orders |
| 2.3 — Agent management tools (6) | **DONE** | list_agents, create_agent, get_agent, reset_agent, update_agent_risk, get_agent_skill |
| 2.4 — Battle tools (6) | **DONE** | create_battle, list_battles, start_battle, get_battle_live, get_battle_results, get_battle_replay |
| 2.5 — Account + analytics tools (4) | **DONE** | get_account_info, get_pnl, get_portfolio_history, get_leaderboard |
| Tests | **DONE** | 142 MCP tool tests (up from 67), all 1083 unit tests pass, 0 lint errors |

---

## Phase 3: SDK and Documentation Polish (Week 3-4)

> **Goal**: Make the "first trade in 5 minutes" promise real. Ship TypeScript SDK. Update all docs.

### Tasks

#### 3.1 — TypeScript/JavaScript SDK

**Why:** The doc emphasizes "framework-agnostic, any language." LLM agent builders use TypeScript (LangChain.js, Vercel AI SDK, etc.). Currently only Python SDK exists.

**Deliverables:**
- `sdk-ts/` directory with npm package `@tradeready/sdk`
- Sync client using `fetch` (works in Node.js, Deno, Bun, browsers)
- WebSocket client for real-time streaming
- TypeScript types for all response shapes (generated from Pydantic schemas)
- Published to npm

**Acceptance criteria:**
- [ ] `npm install @tradeready/sdk` works
- [ ] `new TradeReadyClient({ apiKey }).getPrice("BTCUSDT")` returns a price
- [ ] Full parity with Python SDK's 22 methods

---

#### 3.2 — "Build Your First Trading Agent" tutorial

**Target:** An LLM agent developer who has never seen TradeReady before.

**Content:**
1. Get an API key (30 seconds)
2. Connect via MCP / SDK / raw REST (choose your path)
3. Check balance → Check price → Place first trade (2 minutes)
4. Run your first backtest with step-mode (3 minutes)
5. Analyze results and iterate

**Formats:**
- `docs/tutorials/first-agent.md` — written guide
- `examples/` directory with working code:
  - `examples/quickstart_mcp.py` — MCP-based agent
  - `examples/quickstart_sdk.py` — SDK-based agent
  - `examples/quickstart_langchain.py` — LangChain agent
  - `examples/quickstart_crewai.py` — CrewAI multi-agent

---

#### 3.3 — Update existing docs for multi-exchange + expanded MCP

**Files to update:**
- `docs/quickstart.md` — Add exchange selection, updated tool count
- `docs/api_reference.md` — Add exchange parameter to relevant endpoints
- `docs/mcp_server.md` — Document all 40+ tools (currently documents 12)
- `docs/skill.md` — Update with multi-exchange support, new MCP tools
- `docs/backtesting-guide.md` — Add multi-exchange backtesting section
- Framework guides (`langchain.md`, `crewai.md`, etc.) — Update with new tools and examples

---

### Phase 3 — Estimated Effort

| Task | Effort | Dependencies |
|------|--------|-------------|
| 3.1 — TypeScript SDK | 3-5 days | Phase 1 (exchange model), Phase 2 (expanded API) |
| 3.2 — First Agent tutorial | 1-2 days | Phase 2 (MCP tools) |
| 3.3 — Doc updates | 2-3 days | Phase 1 + Phase 2 |
| **Total** | **~6-10 days** | |

---

## Phase 4: Freemium Tier System (Week 4-5)

> **Goal**: Implement usage limits and tier enforcement so we can launch with a monetization model.

### Tier Design

| Feature | Free | Pro ($29/mo) | Enterprise ($99/mo) |
|---------|------|-------------|---------------------|
| Agents | 1 | 10 | Unlimited |
| Exchanges | Binance only | All supported | All + priority |
| Backtests/month | 50 | 500 | Unlimited |
| Backtest max steps | 1,000 | 10,000 | Unlimited |
| Battles/month | 5 | 50 | Unlimited |
| API rate limit | 60 req/min | 300 req/min | 1,000 req/min |
| Historical data | 1 year | 5 years | Full history |
| MCP tools | All | All | All + priority support |
| WebSocket streams | 5 pairs | 50 pairs | Unlimited |

### Tasks

#### 4.1 — Tier model and enforcement middleware

**Files to create/modify:**
- `src/database/models.py` — Add `Subscription` model (tier, limits, billing period, status)
- `src/accounts/tier_service.py` — Tier limit checking, usage counting
- `src/api/middleware/tier_middleware.py` — Enforce tier limits on relevant endpoints
- `alembic/versions/xxx_add_subscription_model.py` — Migration

**Key design decisions:**
- Usage counters in Redis (fast, atomic): `INCR usage:{account_id}:backtests:{month}`
- Tier config in code (not DB) — tiers are product decisions, not user data
- Enforcement at middleware level — tier checks happen before route handlers
- Graceful degradation: return `HTTP 429` with `upgrade_url` in response body

#### 4.2 — Stripe integration for billing

**Files to create:**
- `src/billing/stripe_service.py` — Checkout, webhooks, subscription management
- `src/api/routes/billing.py` — `/api/v1/billing/checkout`, `/webhook/stripe`

#### 4.3 — Account dashboard with usage stats

- Frontend page showing current tier, usage vs. limits, upgrade CTA

---

### Phase 4 — Estimated Effort

| Task | Effort | Dependencies |
|------|--------|-------------|
| 4.1 — Tier model + enforcement | 3-4 days | None |
| 4.2 — Stripe integration | 2-3 days | 4.1 |
| 4.3 — Account dashboard | 2-3 days | 4.1 |
| **Total** | **~7-10 days** | |

---

## Phase 5: AI Trading Competition — Launch Event (Week 5-6)

> **Goal**: Run a public "Alpha Arena"-style competition to launch TradeReady and prove the platform works.

### Competition Design

**Format**: "AI Agent Trading Arena"
- 10-20 AI agents compete trading crypto with $10K virtual USDT each
- Same historical data period (e.g., 3 months of 2025 market data)
- Uses the existing battle system
- Results tracked in real-time via battle `live` endpoint
- Public leaderboard on the website

**Participants**:
- Invite builders from AI agent communities (LangChain Discord, CrewAI Discord, ElizaOS, Twitter/X AI agent builders)
- Allow anyone to enter with their own agent (self-registration)
- Optionally include a "house agent" built with TradeReady's SDK as baseline

**Marketing angle**: "Blow up 1,000 accounts before breakfast — or win the arena"

### Tasks

#### 5.1 — Competition infrastructure
- Public registration flow (account + agent creation)
- Competition-specific battle configuration (same start/end dates, same starting balance, same allowed pairs)
- Public-facing leaderboard page (read-only, no auth required)
- Real-time WebSocket feed for live spectating

#### 5.2 — Marketing and outreach
- Landing page: "AI Agent Trading Arena — powered by TradeReady"
- Twitter/X announcement thread with the four key marketing messages from the competitive research
- Posts in: LangChain Discord, CrewAI Discord, AI agent Twitter/X, r/algotrading, Hacker News
- Direct outreach to AI agent builders with existing projects

#### 5.3 — Post-competition content
- Blog post analyzing results (which strategies won, agent architectures, lessons learned)
- Publish winning agent code (with permission) as templates
- Video walkthrough of the winning strategy's step-by-step backtest replay

---

## Phase 6: Framework Integrations (Week 6-8)

> **Goal**: Official packages for 3+ major AI agent frameworks

### Tasks

#### 6.1 — LangChain/LangGraph tools package

**Deliverable**: `pip install tradeready-langchain`

- `StructuredTool` wrappers for all 40+ MCP tools
- `AgentExecutor` example with ReAct prompt
- LangGraph multi-agent example (analyst + trader + risk manager)
- Published to PyPI

**Note**: `docs/framework_guides/langchain.md` already exists with patterns — build on this.

#### 6.2 — CrewAI integration

**Deliverable**: `pip install tradeready-crewai`

- `@tool`-decorated wrappers
- Pre-built crew templates (3-agent trading crew)
- Sequential and hierarchical process modes

**Note**: `docs/framework_guides/crewai.md` already exists — build on this.

#### 6.3 — Vercel AI SDK / TypeScript agent tools

**Deliverable**: `npm install @tradeready/ai-tools`

- `tool()` definitions compatible with Vercel AI SDK
- Works with OpenAI function calling, Claude tool use, etc.

#### 6.4 — ElizaOS plugin

**Deliverable**: ElizaOS plugin for TradeReady

- Trading actions as ElizaOS skills
- Connects to TradeReady API instead of direct DEX interaction

---

## Execution Order Summary

```
Week 1-2:  Phase 1 — CCXT Abstraction Layer ✅ COMPLETE
           ├── 1.1 Adapter interface + CCXT impl ✅
           ├── 1.2 Migrate price ingestion ✅
           ├── 1.3 Migrate backfill scripts ✅
           └── 1.4 Multi-exchange backtesting ✅

Week 2-3:  Phase 2 — MCP Server Expansion ✅ COMPLETE
           ├── 2.1 Backtesting tools ×8 ✅
           ├── 2.2 Market + trading tools ×7 ✅
           ├── 2.3 Agent management tools ×6 ✅
           ├── 2.4 Battle tools ×6 ✅
           └── 2.5 Account + analytics tools ×4 ✅

Week 3-4:  Phase 3 — SDK + Docs
           ├── 3.1 TypeScript SDK (3-5 days)
           ├── 3.2 "First Agent" tutorial (1-2 days)
           └── 3.3 Doc updates (2-3 days)

Week 4-5:  Phase 4 — Freemium Tiers
           ├── 4.1 Tier model + enforcement (3-4 days)
           ├── 4.2 Stripe integration (2-3 days)
           └── 4.3 Usage dashboard (2-3 days)

Week 5-6:  Phase 5 — Launch Competition
           ├── 5.1 Competition infrastructure (3-4 days)
           ├── 5.2 Marketing + outreach (ongoing)
           └── 5.3 Post-competition content (after event)

Week 6-8:  Phase 6 — Framework Integrations
           ├── 6.1 LangChain package (2-3 days)
           ├── 6.2 CrewAI package (2-3 days)
           ├── 6.3 Vercel AI SDK (2-3 days)
           └── 6.4 ElizaOS plugin (2-3 days)
```

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|-----------|
| CCXT abstraction breaks existing Binance tick streaming | High | Medium | Keep `BinanceWebSocketClient` as fallback; run both in parallel during migration |
| MCP tool explosion makes context window too large for LLMs | Medium | Medium | Group tools logically; let agents discover tools via `get_pairs`/`list_backtests` first |
| Multi-exchange data fills TimescaleDB storage fast | Medium | High | Implement retention policies (e.g., tick data: 30 days, candles: forever) |
| Competition attracts few participants | High | Medium | Seed with internal agents; partner with 2-3 known AI agent builders for guaranteed entries |
| Hummingbot ships Condor before we launch | High | Medium | Our step-mode backtest via MCP is unique — emphasize this, not general exchange coverage |
| TypeScript SDK delays other work | Medium | Medium | Can ship Phase 5 without it — TS SDK is nice-to-have, not blocking |

---

## Success Metrics

| Metric | Target (3 months post-launch) |
|--------|-------------------------------|
| Registered accounts | 500+ |
| Active agents (traded in last 7 days) | 100+ |
| Backtests run | 10,000+ |
| MCP tool calls/day | 5,000+ |
| GitHub stars (SDK repos) | 200+ |
| Competition participants | 20+ |
| Paying customers (Pro/Enterprise) | 20+ |
| Exchanges supported | 5+ (Binance, OKX, Bybit, Coinbase, Hyperliquid) |

---

## What We're NOT Building (Scope Exclusions)

- **Pre-built trading strategies** — We're infrastructure, not an application. Agents bring their own strategies.
- **Natural language strategy creation** — That's Walbi/NickAI territory. Our users write code.
- **On-chain/DeFi execution** — Focus on CEX first. Hyperliquid via CCXT is the closest we get to DeFi.
- **Mobile app** — API-first means no mobile app needed. The frontend is observation-only.
- **Custom exchange connectors** — CCXT handles all exchange connectivity. We don't build custom connectors.

---

*This plan is a living document. Update it as phases complete and priorities shift.*
