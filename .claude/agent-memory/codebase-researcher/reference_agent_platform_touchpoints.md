---
name: Agent-Platform Touchpoint Map
description: How the agent package interacts with the platform (4 channels, 7+ DB tables, Redis keys)
type: reference
---

# Agent-Platform Touchpoint Map (researched 2026-03-21)

The agent interacts with the platform through 4 channels and writes to 7+ DB tables:

## Agent Integration Channels (outbound: agent -> platform)

1. **SDK** (`AsyncAgentExchangeClient`, 37 methods) -- live prices, candles, orders, balance, positions, performance, trade history, strategies, training
2. **MCP subprocess** (`python -m src.mcp.server`, 58 tools via JSON-RPC stdio) -- full platform surface; `MCP_API_KEY` required; JWT variant for agent/battle endpoints
3. **REST** (`PlatformRESTClient`, 11 methods via httpx) -- backtest lifecycle + strategy management not in SDK
4. **Direct DB** (`agent_tools.py`) -- writes to `agent_journal`, `agent_learnings`, `agent_feedback`; reads from `agent_observations`; only safe in co-located deployment

## Platform DB Tables Written By Agent

- `agent_journal` -- trade decisions, reflections, portfolio reviews, daily/weekly summaries, AB test state
- `agent_learnings` -- key learnings from trade reflections (via MemoryStore)
- `agent_feedback` -- feature requests and bug reports via `request_platform_feature`
- `agent_observations` -- execution observations per trade (via `TradeExecutor`)
- `agent_performance` -- rolling strategy performance summaries (via `StrategyManager`)
- `agent_permissions` -- role/capability overrides (via `CapabilityManager`)
- `agent_budget_limits` -- per-agent financial limits (via `BudgetManager`)

## Redis Keys Written by Agent

- `agent:memory:{agent_id}:recent` -- sorted set of recent memories (1h TTL)
- `agent:working:{agent_id}` -- working memory hash (NO TTL -- must clear on session end)
- `agent:last_regime:{agent_id}` -- last detected market regime (1h TTL)
- `agent:signals:{agent_id}` -- cached signals (1h TTL)
- `agent:permissions:{agent_id}` -- resolved capabilities (5 min TTL)
- `budget:{agent_id}:daily_trades` / `daily_pnl` / `exposure` -- budget counters (TTL = until midnight UTC)

## Report Files (platform -> filesystem)

- `agent/reports/{workflow}-{timestamp}.json` (WorkflowResult per workflow)
- `agent/reports/platform-validation-{timestamp}.json` (PlatformValidationReport for `all` runs)
