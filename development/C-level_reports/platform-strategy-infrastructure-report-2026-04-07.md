---
type: research-report
tags:
  - c-level
  - platform
  - strategy-infrastructure
  - api
  - roadmap
date: 2026-04-07
status: complete
audience: C-level executives
---

# Platform Strategy & Infrastructure Report
**TradeReady Platform — April 7, 2026**
**Audience:** C-Level Executives
**Classification:** Internal Strategic Document

---

## 1. Executive Summary

The TradeReady platform is a **production-deployed, simulated crypto exchange** — not an AI trading agent itself. It is the infrastructure that any AI trading agent plugs into: the gym where agents train, the arena where agents compete, and the execution layer where strategies go live.

**The strategic framing:** Think of TradeReady as **"AWS for AI trading agents."** We provide seven core infrastructure services — real-time market data, a backtesting engine, a battle arena, an order execution engine, a strategy registry, Gymnasium environments, and multi-agent management. Any external AI agent project can connect via REST API, Python SDK, WebSocket, Gymnasium environments, or 58 MCP tools, and immediately have access to a production-grade trading infrastructure backed by real Binance market data across 600+ USDT pairs.

**The `agent/` folder in this repository is a reference implementation.** It demonstrates that the platform API surface is complete and sufficient to build a full AI trading brain on top of — including PPO reinforcement learning, genetic algorithm evolution, regime detection, ensemble combining, and walk-forward validation. It is not the production trading agent. The production trading agent will be a separate project that connects to this platform as an external client.

**Current platform state as of April 7, 2026:**
- **100+ REST endpoints** across 10 domains
- **7 Gymnasium environments** installable as `pip install tradeready-gym`
- **58 MCP tools** over stdio transport
- **Python SDK** (sync + async + WebSocket) with 37+ methods
- **5 WebSocket channels** for real-time streaming
- **22 database migrations** applied; production-stable
- **~3,900 test functions** across platform (1,734 unit) and reference agent (1,984)
- **Next.js 16 frontend** for human-facing management and monitoring

---

## 2. Platform Architecture — What We Provide to AI Agents

### 2.1 The Seven Platform Services

The platform offers seven distinct infrastructure services to any external AI agent. These are the products. Every improvement roadmap item maps back to making one of these services faster, richer, or easier to consume.

---

**Service 1: Real-Time Market Data**

The data foundation that every agent depends on. 600+ USDT pairs from Binance WebSocket are ingested continuously, stored in Redis for sub-millisecond lookups, and persisted in TimescaleDB (a PostgreSQL extension) for historical queries.

| Capability | Detail |
|---|---|
| Live price pairs | 600+ USDT pairs |
| Price lookup latency | < 1ms via Redis |
| Historical candle timeframes | 1m, 5m, 15m, 1h, 4h, 1d |
| Data freshness | < 1 second |
| Storage engine | TimescaleDB hypertables (time-series optimized) |

**API surface for agents:**
- `GET /api/v1/market/prices` — all current prices in one call
- `GET /api/v1/market/candles/{symbol}` — OHLCV candles with timeframe and limit params
- `GET /api/v1/market/ticker/{symbol}` — 24-hour statistics
- WebSocket `ticker` channel — streaming price updates
- WebSocket `candles` channel — streaming OHLCV updates
- SDK: `get_price()`, `get_candles()`, `get_ticker()`

---

**Service 2: Backtesting Engine (The Gym)**

The primary training environment for RL and evolutionary agents. The engine replays historical market data through an in-memory sandbox, enforcing strict no-look-ahead-bias rules at the data layer (`WHERE bucket <= virtual_clock`). All arithmetic uses Python `Decimal` with 0.1% fee simulation for realistic P&L.

| Capability | Detail |
|---|---|
| Look-ahead bias | Prevented at query layer (time-gated SQL) |
| Fee simulation | 0.1% per trade, applied to fill price |
| Arithmetic precision | Python `Decimal` — no float rounding errors |
| Session lifecycle | Create → Start → Step (loop) → Complete |
| Isolation | In-memory sandbox — no Redis, no Binance during replay |

**The step-based API is the key design decision.** An agent calls `POST /step` to advance one candle, receives the new market observation, makes a trading decision, calls `POST /trade`, and loops. This maps directly to the Gymnasium `env.step()` interface. An agent can run thousands of backtests in parallel across different time periods, symbols, and parameters.

**API surface for agents:**
- `POST /api/v1/backtest/create` — create a new session
- `POST /api/v1/backtest/{id}/start` — begin time-series replay
- `POST /api/v1/backtest/{id}/step` — advance one candle, receive observation
- `POST /api/v1/backtest/{id}/trade` — place a trade at simulated price
- `GET /api/v1/backtest/{id}/results` — full metrics, trade history, equity curve
- `POST /api/v1/backtest/{id}/complete` — finalize and persist

---

**Service 3: Battle System (The Arena)**

Agents compete head-to-head or in groups on the same time period with the same market data. Two modes are supported: **live mode** (real-time, agents trade simultaneously as prices update) and **historical mode** (deterministic replay for reproducibility and genetic algorithm fitness evaluation).

The battle system is the primary fitness evaluation mechanism for evolutionary strategies. A `BattleRunner` provisions agents, assigns different strategy genomes, runs a battle, and extracts per-agent performance metrics as fitness scores. Deterministic replay means the same genome always produces the same fitness score — essential for evolutionary selection.

| Capability | Detail |
|---|---|
| Battle modes | Live (real-time) + Historical (deterministic replay) |
| Metrics computed | Sharpe, drawdown, equity curve, return, win rate |
| Ranking system | Per-battle leaderboard + cross-battle global leaderboard |
| Use case | Fitness evaluation for genetic algorithms |

**API surface for agents:**
- `POST /api/v1/battles` — create a battle with time range, symbols, participants
- `GET /api/v1/battles/{id}` — status, per-agent metrics, equity curves
- `POST /api/v1/battles/{id}/join` — register an agent as a participant
- `GET /api/v1/battles/leaderboard` — global agent rankings

---

**Service 4: Order Execution Engine**

A realistic simulated exchange with four order types and an 8-step risk validation pipeline. All balances are virtual USDT — no real money is ever at risk. Slippage is proportional to order size relative to estimated daily volume, producing realistic fills without requiring a full order book simulation.

| Capability | Detail |
|---|---|
| Order types | Market, Limit, Stop-Loss, Take-Profit |
| Risk validation | 8-step pipeline: circuit breaker, position limits, balance, exposure, drawdown, volatility, concentration, daily loss |
| Slippage model | Proportional to order size / daily volume estimate |
| Balances | Virtual USDT per agent (isolated wallets) |
| Idempotency | UUID4 idempotency key per execution — safe retries |

**API surface for agents:**
- `POST /api/v1/trade/order` — place any order type
- `GET /api/v1/trade/orders` — list orders with filters
- `GET /api/v1/trade/trades` — execution history
- `GET /api/v1/trade/positions` — open positions and unrealized P&L
- SDK: `place_market_order()`, `place_limit_order()`, `place_stop_loss()`, `cancel_order()`

---

**Service 5: Strategy Registry**

A version-controlled store for trading strategy definitions. Strategies are JSONB documents specifying entry/exit conditions, target pairs, timeframe, and position sizing parameters. The registry supports a full deployment lifecycle and multi-episode testing via Celery workers.

| Capability | Detail |
|---|---|
| Versioning | Immutable versions — creating a new version never modifies past |
| Lifecycle states | `draft → testing → validated → deployed → archived` |
| Testing | Multi-episode orchestration via Celery (N episodes, aggregated stats) |
| Recommendations | 11 improvement suggestions from the `RecommendationEngine` |
| Indicators | 7 built-in: RSI, MACD, Bollinger Bands, ATR, SMA, EMA, VWAP |

An external agent can `CREATE` a strategy, `TEST` it across 50 episodes, review the aggregated results and recommendations, create a new version with parameter adjustments, and `DEPLOY` the winner — all via API.

**API surface for agents:**
- `POST /api/v1/strategies` — create a strategy definition
- `GET /api/v1/strategies` — list strategies with filters
- `POST /api/v1/strategies/{id}/versions` — create an immutable new version
- `POST /api/v1/strategies/{id}/test` — run N-episode multi-backtest via Celery
- `GET /api/v1/strategies/{id}/tests/{test_id}` — poll test results + recommendations
- `POST /api/v1/strategies/{id}/deploy` — deploy validated strategy to live trading

---

**Service 6: Gymnasium Environments (tradeready-gym)**

An installable Python package that wraps the backtesting API as OpenAI Gymnasium-compatible environments. This is the primary integration point for reinforcement learning agents. A researcher or agent project simply runs `pip install tradeready-gym` and has access to seven registered environments without writing any API integration code.

| Environment | Action Space | Primary Use Case |
|---|---|---|
| `TradeReady-BTC-v0` | Discrete (Hold / Buy / Sell) | RL training on BTC |
| `TradeReady-ETH-v0` | Discrete (Hold / Buy / Sell) | RL training on ETH |
| `TradeReady-SOL-v0` | Discrete (Hold / Buy / Sell) | RL training on SOL |
| `TradeReady-BTC-Continuous-v0` | Box [-1.0, 1.0] | PPO / SAC continuous control |
| `TradeReady-ETH-Continuous-v0` | Box [-1.0, 1.0] | PPO / SAC continuous control |
| `TradeReady-Portfolio-v0` | Box (N weights summing to 1) | Multi-asset portfolio allocation |
| `TradeReady-Live-v0` | Discrete / Box | Real-time paper trading (60s steps) |

**Reward functions available (plug-in, configurable):**

| Reward Function | Signal |
|---|---|
| `PnLReward` | Equity delta per step |
| `SharpeReward` | Rolling Sharpe ratio delta |
| `SortinoReward` | Rolling Sortino ratio delta |
| `DrawdownPenaltyReward` | P&L minus scaled drawdown penalty |
| `CompositeReward` | Weighted combination of the above |

**Observation wrappers:**

| Wrapper | Function |
|---|---|
| `FeatureEngineeringWrapper` | Appends SMA and momentum features to base observation |
| `NormalizationWrapper` | Online z-score normalization, clips to [-1, 1] |
| `BatchStepWrapper` | Holds action for N candles, returns summed reward |

Under the hood: `env.reset()` creates a backtest session, `env.step()` calls `POST /step` and translates the response into a numpy observation array. The `TrainingTracker` utility automatically reports per-episode metrics back to the platform's Training Run API.

---

**Service 7: Multi-Agent Management**

Each platform account can create multiple isolated agents. Each agent receives a unique API key, an isolated virtual wallet with a configurable starting balance, a risk profile (position limits, daily loss cap, circuit breaker threshold), and a complete independent trading history.

This isolation is the foundation for genetic algorithm optimization: provision 12 agents, assign each a different strategy genome, run a battle, collect per-agent fitness scores, select winners, breed the next generation. All cleanup and reset is via API.

| Capability | Detail |
|---|---|
| Isolation | Balances, orders, trades, positions keyed by `agent_id` |
| API keys | Per-agent keys (`ak_live_...`) via `secrets.token_urlsafe(48)` |
| Reset | `POST /api/v1/agents/{id}/reset` — wipes balance, trades, positions |
| Max agents | Configurable per account |
| Auth fallback | API key resolves agent → account automatically |

**API surface for agents:**
- `POST /api/v1/agents` — create a new agent with starting balance and risk config
- `GET /api/v1/agents` — list all agents for the account
- `POST /api/v1/agents/{id}/reset` — reset to starting state for new experiment
- `DELETE /api/v1/agents/{id}` — archive an agent
- SDK: `create_agent()`, `list_agents()`, `reset_agent()`

---

## 3. Platform Integration Points

### 3.1 How an External Agent Connects

```
EXTERNAL AI AGENT PROJECT              THIS PLATFORM (TradeReady)
===========================            ==============================

                                        ┌─────────────────────────────┐
Option A: REST API ──────────────────►  │  100+ REST endpoints         │
                                        │  POST /api/v1/trade/order    │
                                        │  POST /backtest/create       │
                                        │  GET  /market/candles/{sym}  │
                                        └─────────────────────────────┘

                                        ┌─────────────────────────────┐
Option B: Python SDK ────────────────►  │  from sdk import             │
                                        │    TradeReadyClient          │
                                        │  client.get_price("BTCUSDT") │
                                        │  client.place_market_order() │
                                        └─────────────────────────────┘

                                        ┌─────────────────────────────┐
Option C: Gymnasium Env ─────────────►  │  import gymnasium            │
                                        │  env = gym.make(             │
                                        │    "TradeReady-Portfolio-v0" │
                                        │  )                           │
                                        │  obs, r, done, info =        │
                                        │    env.step(action)          │
                                        └─────────────────────────────┘

                                        ┌─────────────────────────────┐
Option D: WebSocket ─────────────────►  │  ws://host:8000/ws/v1        │
                                        │    ?api_key=ak_live_...      │
                                        │  Subscribe: ticker, candles, │
                                        │  orders, portfolio, battle   │
                                        └─────────────────────────────┘

                                        ┌─────────────────────────────┐
Option E: MCP Tools ─────────────────►  │  58 tools over stdio         │
                                        │  For LLM-native agents       │
                                        │  (Claude, GPT-4o, etc.)      │
                                        └─────────────────────────────┘
```

### 3.2 Authentication

| Integration Method | Auth Mechanism |
|---|---|
| REST API | `X-API-Key` header (per-agent keys) OR `Authorization: Bearer {jwt}` |
| Python SDK | `api_key` constructor parameter |
| Gymnasium | `api_key` in `gym.make()` environment config dict |
| WebSocket | `api_key` query parameter in the connection URL |
| MCP Tools | `api_key` in stdio transport config |

**Auth resolution order for API keys:** Key is checked against the agents table first. If found, the request is scoped to that agent. If not found, it falls back to the accounts table for account-level operations.

### 3.3 What the Agent Gets Back

Every platform service returns structured data that the agent can act on:

| Data Type | Contents |
|---|---|
| **Price data** | Symbol, price (Decimal), timestamp, 24h volume, 24h change |
| **Candle data** | OHLCV (Decimal), bucket timestamp, symbol, timeframe |
| **Order result** | Order ID, fill price, quantity, fee, slippage applied, status |
| **Portfolio state** | Positions list, balances, unrealized P&L, Sharpe, max drawdown |
| **Backtest step** | Current candle OHLCV, portfolio snapshot, virtual clock, metrics |
| **Backtest results** | Full trade history, equity curve, Sharpe, Sortino, win rate, max drawdown |
| **Battle results** | Per-agent ranking, equity curves, fitness scores, comparison metrics |
| **Strategy test** | N-episode aggregated metrics, standard deviations, 11 recommendations |
| **Training episode** | Episode metrics posted to training run, learning curve data |

---

## 4. Current Platform Capabilities — Detailed Inventory

### 4.1 REST API Surface (100+ Endpoints)

**Market Data**
- `GET /api/v1/market/prices` — all current prices (600+ pairs)
- `GET /api/v1/market/candles/{symbol}` — OHLCV candles with timeframe param
- `GET /api/v1/market/ticker/{symbol}` — 24h stats: volume, high, low, change

**Trading**
- `POST /api/v1/trade/order` — place Market, Limit, Stop-Loss, or Take-Profit order
- `GET /api/v1/trade/orders` — list orders with status/symbol filters
- `GET /api/v1/trade/trades` — execution history with pagination
- `GET /api/v1/trade/positions` — all open positions with unrealized P&L

**Backtesting**
- `POST /api/v1/backtest/create` — create a new sandbox session
- `POST /api/v1/backtest/{id}/start` — begin historical data replay
- `POST /api/v1/backtest/{id}/step` — advance clock by one candle
- `POST /api/v1/backtest/{id}/trade` — place trade at simulated price
- `GET /api/v1/backtest/{id}/results` — metrics, equity curve, trade log
- `POST /api/v1/backtest/{id}/complete` — finalize session and persist

**Battles**
- `POST /api/v1/battles` — create battle with time range, symbols, mode
- `GET /api/v1/battles` — list battles with status filters
- `GET /api/v1/battles/{id}` — detailed results, per-agent equity curves
- `POST /api/v1/battles/{id}/join` — register an agent as a participant
- `GET /api/v1/battles/leaderboard` — global performance rankings

**Strategies**
- `POST /api/v1/strategies` — create a strategy document
- `GET /api/v1/strategies` — list with lifecycle state filters
- `GET /api/v1/strategies/{id}` — strategy detail with version history
- `POST /api/v1/strategies/{id}/versions` — create a new immutable version
- `POST /api/v1/strategies/{id}/test` — launch multi-episode Celery test job
- `GET /api/v1/strategies/{id}/tests/{test_id}` — poll results + recommendations
- `POST /api/v1/strategies/{id}/deploy` — deploy validated strategy to live
- `POST /api/v1/strategies/{id}/undeploy` — revert to validated state

**Agents**
- `POST /api/v1/agents` — create agent with balance and risk config
- `GET /api/v1/agents` — list all agents for authenticated account
- `GET /api/v1/agents/{id}` — agent detail with current performance
- `POST /api/v1/agents/{id}/reset` — reset balance and trading history
- `DELETE /api/v1/agents/{id}` — archive agent

**Portfolio**
- `GET /api/v1/portfolio/summary` — current positions, balance, total equity
- `GET /api/v1/portfolio/equity` — time-series equity curve (snapshots)
- `GET /api/v1/portfolio/performance` — Sharpe, Sortino, max drawdown, win rate

**Training Runs**
- `POST /api/v1/training/runs` — create a named training run
- `POST /api/v1/training/runs/{id}/episodes` — record per-episode metrics
- `PUT /api/v1/training/runs/{id}/complete` — finalize with aggregate stats
- `GET /api/v1/training/runs` — list training runs with filters
- `GET /api/v1/training/runs/{id}` — run detail with learning curves
- `GET /api/v1/training/runs/{id}/learning-curve` — smoothed metric curves
- `GET /api/v1/training/runs/compare` — side-by-side run comparison

**Accounts**
- `POST /api/v1/accounts/register` — create account
- `POST /api/v1/accounts/login` — JWT token
- `GET /api/v1/accounts/me` — account profile
- `POST /api/v1/accounts/api-keys` — generate per-agent API keys

### 4.2 Python SDK

The SDK (`sdk/agentexchange`) ships sync and async clients plus a WebSocket client. It is a thin typed wrapper over the REST API — no business logic, no caching.

| Category | Methods |
|---|---|
| Market data | `get_price`, `get_candles`, `get_ticker` |
| Trading | `place_market_order`, `place_limit_order`, `place_stop_loss`, `place_take_profit`, `cancel_order` |
| Portfolio | `get_balance`, `get_positions`, `get_trades`, `get_orders`, `get_portfolio_summary` |
| Backtesting | `create_backtest`, `start_backtest`, `step_backtest`, `trade_in_backtest`, `get_backtest_results`, `complete_backtest` |
| Battles | `create_battle`, `join_battle`, `get_battle`, `list_battles`, `get_leaderboard` |
| Strategies | `create_strategy`, `list_strategies`, `create_version`, `test_strategy`, `get_test_results`, `deploy_strategy` |
| Agents | `create_agent`, `list_agents`, `get_agent`, `reset_agent` |
| Training | `create_training_run`, `record_episode`, `complete_training_run`, `list_training_runs`, `compare_runs` |
| WebSocket | Subscribe to: `ticker`, `candles`, `orders`, `portfolio`, `battle` channels |

The `AsyncTradeReadyClient` mirrors the sync client but returns awaitables — designed for asyncio-native agent loops.

### 4.3 Gymnasium Environments (tradeready-gym)

Seven registered environments, five reward functions, three observation wrappers. Full compliance with the Gymnasium API — any RL library that accepts a `gym.Env` (Stable Baselines3, RLlib, CleanRL, etc.) works out of the box.

| Environment ID | Assets | Action Space | Observation Dims | Primary User |
|---|---|---|---|---|
| `TradeReady-BTC-v0` | BTC | Discrete (3) | OHLCV + portfolio (9+) | RL training |
| `TradeReady-ETH-v0` | ETH | Discrete (3) | OHLCV + portfolio (9+) | RL training |
| `TradeReady-SOL-v0` | SOL | Discrete (3) | OHLCV + portfolio (9+) | RL training |
| `TradeReady-BTC-Continuous-v0` | BTC | Box [-1, 1] | OHLCV + portfolio (9+) | PPO/SAC |
| `TradeReady-ETH-Continuous-v0` | ETH | Box [-1, 1] | OHLCV + portfolio (9+) | PPO/SAC |
| `TradeReady-Portfolio-v0` | BTC+ETH+SOL | Box (3 weights) | Multi-asset obs | Portfolio alloc |
| `TradeReady-Live-v0` | Configurable | Discrete / Box | Real-time obs | Paper trading |

**Installation:** `pip install -e tradeready-gym/` (editable) or `pip install tradeready-gym` (release)

### 4.4 MCP Server (58 Tools)

The MCP server runs over stdio transport and provides all platform functionality as named tools to LLM-native agents (Claude, GPT-4o, and any other MCP-compatible model). 58 tools cover all seven platform services. An LLM agent calls `get_price`, `place_order`, `create_backtest`, `step_backtest`, `create_battle`, `create_strategy`, `test_strategy`, etc. — no REST knowledge required.

**Tool count by domain:**

| Domain | Tool Count |
|---|---|
| Market data | 6 |
| Trading operations | 8 |
| Portfolio & performance | 7 |
| Backtesting | 8 |
| Battles | 6 |
| Strategies | 10 |
| Training runs | 7 |
| Agent management | 6 |

### 4.5 WebSocket Channels

Five channels are available after authenticating with an API key:

| Channel | Events | Use Case |
|---|---|---|
| `ticker` | Real-time price updates for subscribed symbols | Price-reactive trading loops |
| `candles` | OHLCV candle close events per timeframe | Indicator computation triggers |
| `orders` | Order fill notifications (price, quantity, fee) | Execution confirmation |
| `portfolio` | Balance and position change events | Real-time P&L tracking |
| `battle` | Live battle state updates, ranking changes | Battle monitoring |

---

## 5. Platform Roadmap — Making Infrastructure Better

These items address platform-level improvements that benefit every agent project that integrates with TradeReady. They are not agent-specific features — they make the infrastructure faster, richer, and easier to use.

### 5.1 Batch Step Endpoint (High Priority)

**Problem:** The current backtest API requires one HTTP round-trip per candle. For RL training, this means 500,000+ HTTP calls per training run. Even at 20ms per call, that is 2.8 hours of network overhead per training run.

**Solution:** `POST /api/v1/backtest/{id}/steps` — accepts N steps in one call, returns N observations with cumulative rewards. The agent still controls actions per step; the platform batches the time advancement internally.

**Impact:** 10x to 50x throughput improvement for RL-intensive agent projects. This is the single highest-leverage infrastructure investment.

**Effort:** Medium — the sandbox step logic already exists; this is a batching wrapper and response serialization change.

### 5.2 Deflated Sharpe Ratio as a Platform Service

**Problem:** Every agent project building a strategy search system needs to detect overfitting. The Deflated Sharpe Ratio (DSR) — a statistical test that accounts for multiple-comparison bias — requires access to all backtest results across strategy versions. The platform already has all this data.

**Solution:** `GET /api/v1/strategies/{id}/deflated-sharpe` — the platform computes DSR across all tested versions, returns the probability that the best Sharpe observed is due to luck rather than skill.

**Impact:** Agent projects get overfitting detection for free, without implementing the statistical test themselves. This is a differentiating platform feature.

**Effort:** Medium — DSR formula is well-defined; requires aggregating backtest results already stored in the database.

### 5.3 Server-Side Technical Indicators API

**Problem:** Every agent project re-implements RSI, MACD, Bollinger Bands, ATR, and similar indicators. This is duplicated compute across all clients with potential implementation differences.

**Solution:** `GET /api/v1/market/indicators/{symbol}?indicators=rsi_14,macd_hist,bb_width&timeframe=1h` — the platform computes and caches indicators server-side, returning them alongside OHLCV data.

**Impact:** Reduces client-side complexity significantly. A signal-generation module becomes three API calls instead of 300 lines of indicator math. The platform's `IndicatorEngine` (already built in `src/strategies/`) can be surfaced as a public API endpoint.

**Effort:** Low — the `IndicatorEngine` class already exists and computes all 7 indicators; this is an API surface change.

### 5.4 Strategy Comparison API (Enhancement)

**Problem:** Comparing three or more strategy versions requires N separate API calls and manual aggregation by the agent project.

**Solution:** `GET /api/v1/strategies/compare?ids=uuid1,uuid2,uuid3` — returns a side-by-side metrics table across all specified strategy versions including Sharpe, Sortino, drawdown, win rate, and episode count.

**Impact:** Enables agent projects to implement strategy selection logic with a single API call. The training run comparison endpoint (`GET /api/v1/training/runs/compare`) already demonstrates this pattern.

**Effort:** Low — query pattern already exists in training runs; needs adaptation for strategy domain.

### 5.5 Enhanced Gymnasium Environments

**Three specific improvements:**

1. **More assets in Portfolio-v0** — current implementation supports BTC, ETH, SOL only. Expand to support any symbol combination via configuration parameter. Agents optimizing multi-asset portfolios need more than three assets to find meaningful correlations.

2. **Configurable fee models** — currently hard-coded at 0.1%. Expose as a `fee_rate` parameter in `gym.make()` so agents can train under different fee regimes and study how fee sensitivity affects optimal strategy.

3. **Multi-timeframe observations** — current observation vector is single-timeframe OHLCV. Add support for stacked observations (e.g., 1h + 4h + 1d candles) so agents can learn multi-horizon patterns without building their own feature stacking.

**Effort:** Medium per item. Multi-timeframe requires the most platform work (observation shape changes affect all wrappers).

### 5.6 Webhooks for Async Events

**Problem:** Agent projects must poll to detect when a multi-episode strategy test completes, when a battle ends, or when a Celery retraining job finishes. At scale, polling creates unnecessary load.

**Solution:** `POST /api/v1/webhooks` — register a callback URL for event types: `backtest.completed`, `battle.completed`, `strategy_test.completed`, `strategy.deployed`.

**Impact:** Enables event-driven agent architectures. An evolutionary search loop can sleep until notified, rather than polling every 5 seconds. Reduces API load at scale.

**Effort:** Medium — requires webhook registry table, delivery worker, retry logic with exponential backoff.

### 5.7 SDK Documentation and Agent Project Examples

**Problem:** The SDK, Gym package, and MCP tools are functional but lack worked examples showing how to build a complete agent project on top of the platform.

**Solution:** The `agent/` reference implementation should be extracted and published as a standalone example project with documentation covering:
- "How to train an RL agent using TradeReady-Portfolio-v0"
- "How to run a genetic algorithm strategy search using the Battle API"
- "How to build a regime-adaptive signal generator using the Market Data API"
- "Quickstart: connect an LLM agent via MCP tools in 5 minutes"

**Impact:** Reduces time-to-first-integration for external agent projects from days to hours. The reference implementation already demonstrates all these patterns; this is a documentation and packaging task.

**Effort:** Low — code already exists in `agent/`; work is documentation, cleanup, and example extraction.

---

## 6. The Reference Implementation (agent/ folder)

### What It Is

The `agent/` package in this repository is a **proof-of-concept reference implementation** — not the production trading agent. Its purpose is to demonstrate that the platform API surface is complete and sufficient to build a full AI trading brain on top of.

### What It Contains

| Component | Description |
|---|---|
| `agent/trading/` | `TradingLoop` — 7-step cycle: observe → decide → execute → monitor → journal → learn → sleep |
| `agent/strategies/rl/` | PPO reinforcement learning strategy (Stable Baselines3) |
| `agent/strategies/evolutionary/` | Genetic algorithm with `StrategyGenome`, `BattleRunner`, crossover/mutation |
| `agent/strategies/regime/` | Market regime classifier (XGBoost/RF, 4 regimes, 99.92% accuracy, WFE 97.46%) |
| `agent/strategies/risk/` | Risk overlay: Kelly sizing, drawdown profiles, correlation-aware middleware |
| `agent/strategies/ensemble/` | `EnsembleRunner` + `MetaLearner` dynamic weight optimization |
| `agent/strategies/drift.py` | `DriftDetector` — Page-Hinkley test for concept drift detection |
| `agent/strategies/retrain.py` | `RetrainOrchestrator` — 4 retraining schedules wired into Celery beat |
| `agent/strategies/walk_forward.py` | Walk-Forward Validation with WFE metric, overfit warning at WFE < 50% |
| `agent/conversation/` | Session management, intent routing, LLM reasoning loop |
| `agent/memory/` | Memory store (Postgres + Redis), scored retrieval |
| `agent/permissions/` | Roles, capabilities, budget limits, enforcement (fail-closed) |

### What It Validates

The reference implementation proves three things:

1. **The platform API surface is complete.** If the reference agent can train (RL, 30-day PPO), evolve (genetic algorithm, fitness via battles), detect regimes, assemble strategies into an ensemble, walk-forward validate, detect drift, and trigger retraining — all via platform APIs — then any external agent project can do the same.

2. **The quality bar.** 1,984 test functions across 51 files. The platform's own test suite has 1,734 unit tests. A combined ~3,900 test functions demonstrates the platform's reliability as infrastructure.

3. **The integration patterns.** The reference agent demonstrates how to wire REST, SDK, Gymnasium, WebSocket, and MCP together in a production-grade asyncio architecture. External agent projects can study it as a canonical example.

### What It Is Not

The reference agent is **not** the production trading agent. It was built to validate the platform, not to be deployed as a product. The production trading agent will be a separate project with its own:
- Repository and deployment pipeline
- Architecture decisions (may not use Pydantic AI)
- Strategy choices (may diverge from the 5-strategy ensemble)
- Operational requirements (capital management, live trading controls)

The `agent/` folder should be treated as "example code" in the platform repository — maintained for reference value, but not the product itself.

---

## 7. Platform KPIs

### 7.1 API Performance Targets

| KPI | Target | Rationale |
|---|---|---|
| Backtest step latency (p95) | < 100ms | RL training step budget |
| Order execution latency (p95) | < 50ms | Live trading responsiveness |
| Price feed latency | < 10ms (Redis) | Decision loop freshness |
| API uptime | > 99.9% | Infrastructure reliability |
| Concurrent agents | 1,000+ | Multi-agent evolutionary scale |
| Concurrent backtest sessions | 100+ | Parallel RL training runs |

### 7.2 Data Quality Targets

| KPI | Target | Current State |
|---|---|---|
| USDT pairs available | 600+ | 600+ (Binance WS, production) |
| Historical data depth | 2+ years | TimescaleDB, continuous ingestion |
| Candle gap rate | < 0.1% | Monitored via gap-fill pipeline |
| Price data freshness | < 1 second | Redis sub-ms read, < 1s write lag |

### 7.3 Platform Growth Metrics (Track Forward)

These metrics do not yet have baselines — establish them as the platform opens to external agent projects.

| KPI | Why It Matters |
|---|---|
| Backtests run per day | Indicates RL/evolutionary agent activity |
| Battles run per day | Indicates agent competition and fitness eval usage |
| Strategies created per day | Indicates strategy search pipeline usage |
| Active agents (last 7 days) | Overall platform engagement |
| Gymnasium episodes completed | RL training throughput |
| SDK downloads per month | External adoption signal |
| Time-to-first-backtest (new accounts) | Onboarding friction signal |

---

## 8. Conclusion

TradeReady is a **production-grade trading infrastructure platform** — the gym, the arena, and the execution layer for any AI trading agent project that wants to train, test, compete, and deploy strategies against real Binance market data.

**Seven core services** are live in production: real-time market data (600+ pairs, < 1s freshness), a look-ahead-free backtesting engine, a deterministic battle arena, a realistic order execution engine, a version-controlled strategy registry, seven Gymnasium environments, and multi-agent management with isolated wallets.

**Five integration methods** are available: REST API (100+ endpoints), Python SDK (37+ methods, sync + async), Gymnasium environments (`pip install tradeready-gym`), WebSocket (5 channels), and MCP tools (58 tools over stdio).

**The reference implementation** in `agent/` validates the platform's completeness — a full AI trading brain (RL, genetic, regime, ensemble, walk-forward, retraining) built entirely on top of platform APIs. The production trading agent will be a separate project.

**The platform roadmap** focuses on making the infrastructure faster and more capable for external agents: batch backtesting (10x–50x RL throughput), server-side Deflated Sharpe ratio (overfitting detection as a service), technical indicators API (eliminate duplicated client-side compute), webhooks (event-driven agent architectures), and enhanced Gymnasium environments (more assets, configurable fees, multi-timeframe observations).

The platform is ready for external agent projects to integrate today. The primary investment priorities are the batch step endpoint and the SDK documentation — both unlock the next class of agent sophistication.

---

*Report generated: 2026-04-07*
*Platform version: Production (migration head: 022)*
*Test suite: ~3,900 test functions (platform: 1,734 unit; reference agent: 1,984)*
*Next review: On completion of Module A (Feature Pipeline) or Module B (Signal Interface)*
