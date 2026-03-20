---
task_id: 17
title: "Enhanced agent tools — scan_opportunities, journal_entry, request_platform_feature"
agent: "backend-developer"
phase: 1
depends_on: [16]
status: "pending"
priority: "medium"
files: ["agent/tools/agent_tools.py"]
---

# Task 17: Enhanced agent tools — scan_opportunities, journal_entry, request_platform_feature

## Assigned Agent: `backend-developer`

## Objective
Create the second batch of agent-specific tools: opportunity scanner, journal writer, and platform feedback tool.

## Files to Modify
- `agent/tools/agent_tools.py` — add 3 more tools

## Tools to Implement

### scan_opportunities(criteria: dict) -> list[Opportunity]
1. Fetch current prices for all tracked symbols via Redis
2. Apply criteria filters (e.g., "trending up", "high volume", "near support")
3. For each candidate, check against existing positions (avoid duplicates)
4. Rank by signal strength
5. Return top N opportunities with entry/exit suggestions

### journal_entry(content: str, entry_type: str = "reflection") -> JournalEntry
1. Capture current market context (top prices, portfolio state)
2. Auto-tag content based on keywords
3. Save to `agent_journal` table
4. Return saved entry with context

### request_platform_feature(description: str, category: str) -> FeedbackEntry
1. Save to `agent_feedback` table with category and priority
2. Check for duplicate/similar existing requests
3. Return saved entry

## Acceptance Criteria
- [ ] All 3 tools follow existing Pydantic AI tool pattern
- [ ] `scan_opportunities` queries Redis for current prices
- [ ] `journal_entry` auto-captures market context
- [ ] `request_platform_feature` deduplicates similar requests
- [ ] Output models: `Opportunity`, `JournalEntry`, `FeedbackEntry`
- [ ] All 5 tools (Task 16 + 17) registered with the Pydantic AI agent

## Dependencies
- Task 16 (first batch of tools, shared file)

## Agent Instructions
1. Add to the same `agent/tools/agent_tools.py` file
2. For `scan_opportunities`: use Redis `HGETALL prices` for bulk price fetch
3. For `journal_entry`: market context = top 10 prices + portfolio summary
4. For `request_platform_feature`: use `ilike` search on existing feedback to detect duplicates
5. Add output models to `agent/models/analysis.py`

## Estimated Complexity
Medium — three tools with various integrations.
