---
name: dashboard_agent_analytics_task35
description: Task 35 added 4 agent performance analytics components to the dashboard with new hooks and API client functions
type: project
---

Four new dashboard sections were added under an "Agent Performance Analytics" divider in the dashboard page — all lazy-loaded via `next/dynamic`:

1. `active-trade-monitor.tsx` — Live position monitor with real-time PnL per trade (sorted by abs PnL, memo'd TradeRow, WS pulse indicator)
2. `strategy-attribution-chart.tsx` — Bar chart of avg PnL per direction (buy/sell/hold) from `GET /agents/{id}/decisions/analyze`
3. `equity-comparison-chart.tsx` — Multi-line overlay of equity curves for all agents in parallel via `useQueries`
4. `signal-confidence-histogram.tsx` — Confidence score histogram (10 deciles, gradient coloring from muted → profit)

New hooks:
- `use-agent-decisions.ts` — wraps decision analyze endpoint with filter options
- `use-agent-equity-comparison.ts` — parallel `useQueries` for up to 6 agents, time-merges into single dataset

New types in `types.ts`: `DecisionItem`, `DecisionAnalysisResponse`, `DirectionStats`, `AgentEquityPoint`, `AgentEquityHistoryResponse`

New api-client functions: `getAgentDecisionAnalysis`, `getAgentEquityHistory`

**Why:** The decisions endpoint at `GET /api/v1/agents/{id}/decisions/analyze` was already implemented in the backend (added 2026-03-21). This task surfaced it in the frontend.

**How to apply:** When building analytics that need multi-agent comparisons, use `useQueries` from TanStack Query for parallel fetching. The `use-agent-equity-comparison.ts` pattern (parallel queries → client-side time merge) is reusable.
