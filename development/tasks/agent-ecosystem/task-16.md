---
task_id: 16
title: "Enhanced agent tools — reflect_on_trade and review_portfolio"
type: task
agent: "backend-developer"
phase: 1
depends_on: [9, 3]
status: "pending"
board: "[[agent-ecosystem/README]]"
priority: "medium"
files: ["agent/tools/agent_tools.py"]
tags:
  - task
  - agent
  - ecosystem
---

# Task 16: Enhanced agent tools — reflect_on_trade and review_portfolio

## Assigned Agent: `backend-developer`

## Objective
Create the first batch of agent-specific tools: `reflect_on_trade` (analyze a completed trade and extract learnings) and `review_portfolio` (full portfolio health check with recommendations).

## Files to Create
- `agent/tools/agent_tools.py` — new tool functions

## Tools to Implement

### reflect_on_trade(trade_id: str) -> TradeReflection
1. Fetch trade details via SDK
2. Fetch market context at entry and exit via `agent_observations`
3. Analyze: was entry timing good? Was exit optimal? What was the max adverse excursion?
4. Generate learnings using LLM reasoning
5. Save reflection to `agent_journal` and learnings to `agent_learnings`
6. Return structured reflection

### review_portfolio() -> PortfolioReview
1. Fetch current portfolio via SDK
2. Calculate concentration risk, correlation exposure, unrealized P&L
3. Compare against budget limits from `agent_budgets`
4. Generate recommendations (reduce exposure, take profit, etc.)
5. Return structured review with actionable items

## Acceptance Criteria
- [ ] Both tools follow Pydantic AI tool registration pattern from `agent/tools/`
- [ ] `reflect_on_trade` produces structured `TradeReflection` output
- [ ] `review_portfolio` produces structured `PortfolioReview` output
- [ ] Learnings are persisted to memory system
- [ ] Journal entries are persisted to `agent_journal`
- [ ] Output models defined in `agent/models/`

## Dependencies
- Task 09 (memory store), Task 03 (repos)

## Agent Instructions
1. Read `agent/tools/sdk_tools.py` and `agent/tools/rest_tools.py` for existing tool patterns
2. Read `agent/models/` for output model patterns
3. Register tools with Pydantic AI agent via the same pattern as existing tools
4. Add output models `TradeReflection` and `PortfolioReview` to `agent/models/analysis.py`

## Estimated Complexity
Medium — two tools with SDK integration and persistence.
